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
