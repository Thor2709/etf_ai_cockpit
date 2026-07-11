from __future__ import annotations

from etf_cockpit.data.fundamentals import build_fundamental_evidence


def test_missing_and_weak_fundamentals_are_not_confused() -> None:
    missing = build_fundamental_evidence({}, "MSFT", "2026-07-10")
    weak = build_fundamental_evidence({"valuation": -1, "profitability": 2}, "MSFT", "2026-07-10")
    assert missing.eligibility == "not_score_eligible"
    assert "valuation" in missing.missing_fields
    assert weak.eligibility == "eligible_negative_evidence"
    assert weak.values["valuation"] == -1
