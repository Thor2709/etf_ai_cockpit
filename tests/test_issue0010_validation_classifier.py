from __future__ import annotations

from scripts.classify_validation import build_report


def test_issue0010_persistence_surface_has_high_validation_tier() -> None:
    assert build_report(["src/etf_cockpit/audit/thesis_diary.py"])["tier"] == "H"
    assert build_report(["src/etf_cockpit/audit/local_llm.py"], ordinary_issues_since_full_gate=0)["tier"] == "O"
    assert build_report(["docs/product-completion/PROGRESS.md"])["tier"] == "E"
