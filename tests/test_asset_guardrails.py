from __future__ import annotations

from etf_cockpit.data.universe_store import support_decision


def test_unsupported_assets_never_become_score_eligible() -> None:
    for asset_type in ("futures", "options", "crypto", "forex"):
        decision = support_decision(asset_type, "daily", False, False)
        assert decision.supported is False
        assert decision.score_eligible is False


def test_research_only_assets_are_explicitly_marked_without_silent_scoring() -> None:
    for asset_type in ("futures", "options"):
        decision = support_decision(asset_type, "daily", False, False)
        assert decision.risk_state == "research_only"
        assert "research" in decision.reason.lower()
