from __future__ import annotations

from etf_cockpit.data.universe_store import support_decision
from etf_cockpit.app.pages.onboarding import OnboardingProfile, validate_onboarding


def test_supported_and_rejected_asset_decisions_are_explicit() -> None:
    assert support_decision("etf", "daily", False, False).supported is True
    assert support_decision("crypto", "daily", False, False).supported is False
    assert support_decision("stock", "intraday", False, False).supported is False
    assert support_decision("etf", "daily", True, False).risk_state == "high_risk_manual_review"


def test_onboarding_rejects_empty_scope_and_preserves_unresolved_symbols() -> None:
    report = validate_onboarding(OnboardingProfile("EUR", "EU", (), "balanced", "medium"))
    assert report.valid is False
    assert "asset_scope" in report.errors
    valid = validate_onboarding(OnboardingProfile("EUR", "EU", ("UNKNOWN",), "balanced", "medium"))
    assert valid.valid is True
    assert valid.unresolved_symbols == ("UNKNOWN",)
