from __future__ import annotations

from pathlib import Path


def _checker():
    try:
        from etf_cockpit.governance.static_checks import run_static_execution_boundary_check
    except ImportError:
        return None
    return run_static_execution_boundary_check


def test_current_production_package_inventory_passes() -> None:
    root = Path(__file__).resolve().parents[2]
    checker = _checker()
    report = checker(root) if checker else None
    assert report is not None
    assert report.result == "pass"
    assert report.scanned_files > 0


def test_immutable_completion_sources_are_not_production_inventory(tmp_path: Path) -> None:
    source = tmp_path / "docs" / "product-completion" / "sources" / "archived.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"url": "https://broker.example/orders"}\n', encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "pass"
    assert not any(item.path.startswith("docs/product-completion/sources/") for item in report.violations)


def test_injected_dependency_and_resource_violations_fail(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("alpaca-trade-api==1.0\n", encoding="utf-8")
    (tmp_path / "secrets.env").write_text("BROKER_API_KEY=not-a-real-key\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "fail"
    assert {item.code for item in report.violations} >= {
        "PROHIBITED_BROKER_DEPENDENCY",
        "PROHIBITED_CREDENTIAL_RESOURCE",
    }


def test_ignored_generated_package_roots_are_not_scanned(tmp_path: Path) -> None:
    """Generated package output is covered by package gates, not source scanning."""

    generated = tmp_path / "build" / "vendor" / "bad.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("def place_order(): pass\n", encoding="utf-8")
    checker = _checker()
    report = checker(tmp_path) if checker else None
    assert report is not None
    assert report.result == "pass"
    assert not any(item.path.startswith("build/") for item in report.violations)


def test_future_documents_have_no_runnable_order_or_credential_examples() -> None:
    root = Path(__file__).resolve().parents[2]
    future = root / "docs" / "architecture" / "future"
    documents = sorted(future.glob("*.md"))
    assert len(documents) == 3
    for path in documents:
        text = path.read_text(encoding="utf-8").lower()
        assert text.startswith("# future-only / no-authority")
        assert "api_key=" not in text
        assert "password=" not in text
        assert "def place_order" not in text
        assert "requests.post" not in text
