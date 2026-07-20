from __future__ import annotations

import json
from pathlib import Path


def _checker():
    try:
        from etf_cockpit.governance.static_checks import run_static_execution_boundary_check
    except ImportError:
        return None
    return run_static_execution_boundary_check


def test_production_place_order_symbol_is_a_boundary_violation(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def place_order(): pass\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert report.violations[0].code == "PROHIBITED_ORDER_SYMBOL"


def test_sort_order_is_not_a_false_positive(tmp_path: Path) -> None:
    (tmp_path / "safe.py").write_text("sort_order = 'asc'\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "pass"


def test_local_replay_symbols_and_mapping_get_are_not_false_positives(tmp_path: Path) -> None:
    replay = tmp_path / "src" / "etf_cockpit" / "backtest" / "event_engine.py"
    replay.parent.mkdir(parents=True)
    replay.write_text("class OrderRequest: pass\n", encoding="utf-8")
    paper = tmp_path / "src" / "etf_cockpit" / "portfolio" / "paper_trading.py"
    paper.parent.mkdir(parents=True)
    paper.write_text("def cancel_order(): pass\nstate = {'orders': {}}\nstate['orders'].get('x')\n", encoding="utf-8")

    checker = _checker()
    report = checker(tmp_path) if checker else None

    assert report is not None
    assert report.result == "pass"


def test_context_aware_scans_reject_import_endpoint_ui_and_execution_config(tmp_path: Path) -> None:
    (tmp_path / "broker.py").write_text("import broker_sdk\n", encoding="utf-8")
    (tmp_path / "endpoint.py").write_text(
        "import requests\nrequests.post('https://broker.example/orders')\n", encoding="utf-8"
    )
    (tmp_path / "ui.py").write_text("button = 'Place order'\n", encoding="utf-8")
    (tmp_path / "settings.yaml").write_text("execution_allowed: true\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert {item.code for item in report.violations} >= {
        "PROHIBITED_BROKER_DEPENDENCY",
        "PROHIBITED_ORDER_ENDPOINT",
        "PROHIBITED_UI_ORDER_CONTROL",
        "EXECUTION_AUTHORITY_ENABLED",
    }


def test_order_router_symbols_and_ini_authority_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "router.py").write_text("class OrderRouter: pass\n", encoding="utf-8")
    (tmp_path / "settings.ini").write_text("[policy]\nexecution_allowed = true\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert any(item.code == "PROHIBITED_ORDER_SYMBOL" for item in report.violations)
    assert any(item.code == "EXECUTION_AUTHORITY_ENABLED" for item in report.violations)


def test_arbitrary_env_and_opaque_credential_resources_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.env").write_text(
        "EXECUTION_ALLOWED=true\nEXECUTABLE_AUTHORITY=true\n", encoding="utf-8"
    )
    (tmp_path / "private.pem").write_bytes(b"opaque-private-key-bytes")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    codes = {item.code for item in report.violations}
    assert "EXECUTION_AUTHORITY_ENABLED" in codes
    assert "PROHIBITED_CREDENTIAL_RESOURCE" in codes


def test_imported_order_symbols_and_indirect_order_url_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "imports.py").write_text(
        "from helper import place_order\nfrom helper import OrderRouter as Router\n",
        encoding="utf-8",
    )
    (tmp_path / "endpoint.py").write_text(
        "import requests\nurl = 'https://broker.example/orders'\nrequests.post(url)\n",
        encoding="utf-8",
    )
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    codes = {item.code for item in report.violations}
    assert "PROHIBITED_ORDER_SYMBOL" in codes
    assert "PROHIBITED_ORDER_ENDPOINT" in codes


def test_production_package_data_and_models_are_scanned(tmp_path: Path) -> None:
    """Runtime/cache exclusions must not hide production package source."""

    for package in ("data", "models"):
        package_root = tmp_path / "src" / "etf_cockpit" / package
        package_root.mkdir(parents=True)
        (package_root / "bad.py").write_text("def place_order(): pass\n", encoding="utf-8")

    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert {
        Path(item.path).parent.as_posix()
        for item in report.violations
        if item.code == "PROHIBITED_ORDER_SYMBOL"
    } >= {"src/etf_cockpit/data", "src/etf_cockpit/models"}


def test_private_key_credential_resources_are_scanned(tmp_path: Path) -> None:
    (tmp_path / "broker.pem").write_text("BROKER_API_KEY=not-a-real-key\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert any(item.code == "PROHIBITED_CREDENTIAL_RESOURCE" for item in report.violations)


def test_env_and_ini_default_authority_flags_are_rejected(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("EXECUTION_ALLOWED=true\n", encoding="utf-8")
    (tmp_path / "settings.ini").write_text(
        "[DEFAULT]\nexecutable_authority = true\n", encoding="utf-8"
    )
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert sum(item.code == "EXECUTION_AUTHORITY_ENABLED" for item in report.violations) >= 2


def test_future_allow_list_does_not_hide_executable_or_config_files(tmp_path: Path) -> None:
    future = tmp_path / "docs" / "architecture" / "future"
    future.mkdir(parents=True)
    (future / "bad.py").write_text("def place_order(): pass\n", encoding="utf-8")
    (future / "bad.yaml").write_text("execution_allowed: true\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert {item.code for item in report.violations} >= {
        "PROHIBITED_ORDER_SYMBOL",
        "EXECUTION_AUTHORITY_ENABLED",
    }


def test_short_ui_order_labels_and_scalar_order_urls_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "ui.py").write_text("button = 'Buy'\nsubmit = 'Submit'\n", encoding="utf-8")
    (tmp_path / "settings.yaml").write_text(
        "url: https://broker.example/orders\n", encoding="utf-8"
    )
    (tmp_path / "safe.py").write_text("sort_order = 'asc'\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert {item.code for item in report.violations} >= {
        "PROHIBITED_UI_ORDER_CONTROL",
        "PROHIBITED_ORDER_ENDPOINT",
    }
    assert not any(item.path == "safe.py" for item in report.violations)


def test_cancel_dialog_button_is_not_an_order_control(tmp_path: Path) -> None:
    dialog_path = tmp_path / "src" / "etf_cockpit" / "app" / "dialog.py"
    dialog_path.parent.mkdir(parents=True)
    dialog_path.write_text(
        "import flet as ft\n"
        "dialog = ft.AlertDialog(actions=[ft.TextButton('Cancel')])\n",
        encoding="utf-8",
    )
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "pass"


def test_plain_cancel_label_on_order_control_is_rejected(tmp_path: Path) -> None:
    order_path = tmp_path / "src" / "etf_cockpit" / "app" / "order_dialog.py"
    order_path.parent.mkdir(parents=True)
    order_path.write_text(
        "import flet as ft\n"
        "order_cancel_button = ft.TextButton('Cancel')\n",
        encoding="utf-8",
    )
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert any(item.code == "PROHIBITED_UI_ORDER_CONTROL" for item in report.violations)


def test_plain_cancel_label_on_explicit_order_control_call_is_rejected(tmp_path: Path) -> None:
    order_path = tmp_path / "src" / "etf_cockpit" / "app" / "order_controls.py"
    order_path.parent.mkdir(parents=True)
    order_path.write_text(
        "def render(order_control):\n"
        "    return order_control('Cancel')\n",
        encoding="utf-8",
    )
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert any(item.code == "PROHIBITED_UI_ORDER_CONTROL" for item in report.violations)


def test_dynamic_broker_imports_and_variant_dependency_manifests_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "loader.py").write_text(
        "import importlib\nsdk = importlib.import_module('broker_sdk')\n", encoding="utf-8"
    )
    (tmp_path / "requirements-prod.txt").write_text("ccxt==4.0\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert sum(item.code == "PROHIBITED_BROKER_DEPENDENCY" for item in report.violations) >= 2


def test_future_docs_and_test_fixtures_are_explicitly_allow_listed(tmp_path: Path) -> None:
    future = tmp_path / "docs" / "architecture" / "future"
    future.mkdir(parents=True)
    (future / "contract.md").write_text("def place_order(): pass\nexecution_allowed: true\n", encoding="utf-8")
    fixtures = tmp_path / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "future_fixture.py").write_text("def place_order(): pass\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "pass"


def test_report_is_machine_readable_deterministic_and_non_executable(tmp_path: Path) -> None:
    (tmp_path / "safe.py").write_text("sort_order = 'asc'\n", encoding="utf-8")
    checker = _checker()
    first = checker(tmp_path) if checker else None
    second = checker(tmp_path) if checker else None
    assert first is not None and second is not None
    assert first.schema_version == "1.0"
    assert first.policy_checksum == second.policy_checksum
    assert first.violations == second.violations
    assert first.scanned_files == second.scanned_files
    assert first.execution_allowed is False
    assert first.executable_authority is False
    payload = json.loads(first.model_dump_json())
    assert payload["result"] == "pass"
    assert payload["generated_at"]
