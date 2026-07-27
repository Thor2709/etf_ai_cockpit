from __future__ import annotations

from pathlib import Path

from etf_cockpit.application.architecture import build_report, find_violations


ROOT = Path(__file__).resolve().parents[1]


def test_presentation_uses_application_facade_without_implementation_imports() -> None:
    report = build_report(ROOT)

    assert report["status"] == "passed"
    assert report["violation_count"] == 0
    assert find_violations(ROOT) == ()


def test_diagnostics_boundary_report_is_user_visible() -> None:
    report = build_report(ROOT)

    assert report["boundary"] == "presentation-to-application"
    assert report["status"] == "passed"


def test_fixed_income_analysis_has_no_concrete_persistence_imports() -> None:
    source = (
        Path("src/etf_cockpit/analysis/fixed_income_analytics.py")
        .read_text(encoding="utf-8")
    )
    assert "import pandas" not in source
    assert "core.atomic_io" not in source
    assert "data.local_storage" not in source
    assert "sqlite3" not in source
