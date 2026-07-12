from __future__ import annotations

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.types import Action
from etf_cockpit.signals.research_states import (
    InternalSignalIntent,
    ResearchState,
    internal_intent_for_legacy_action,
    research_state_for_legacy_action,
)


def preliminary_action(
    config: AppConfig,
    *,
    total_score: float,
    confidence: float,
    current_weight: float,
    drift: float,
    hard_band: float,
    trend_200: float,
) -> Action:
    limits = config.risks.signal_limits
    if drift > hard_band and total_score <= 0.35 and confidence >= limits.min_confidence_for_trim:
        return "trim"
    if drift < -hard_band and total_score >= 0.20 and confidence >= limits.min_confidence_for_buy:
        return "buy" if current_weight <= 0 else "add"
    if total_score <= limits.sell_threshold and confidence >= 0.65 and current_weight > 0 and trend_200 <= 0:
        return "sell"
    if total_score <= limits.trim_threshold and confidence >= limits.min_confidence_for_trim and current_weight > 0:
        return "trim"
    if total_score >= limits.add_threshold and confidence >= limits.min_confidence_for_buy:
        return "buy" if current_weight <= 0 else "add"
    if limits.no_trade_lower < total_score < limits.no_trade_upper:
        return "no_trade" if abs(drift) <= hard_band else "hold"
    return "hold"


def apply_gate_result(candidate: Action, blocked_by: list[str]) -> Action:
    manual_review_codes = {
        "portfolio_validation_block",
        "target_total_invalid",
        "empty_prices",
        "missing_columns",
        "missing_adjusted_close",
        "missing_currency",
        "stale_data",
        "invalid_ohlc",
        "model_disagreement",
    }
    if any(code in manual_review_codes for code in blocked_by):
        return "manual_review"
    if "model_disagreement" in blocked_by:
        return "manual_review"
    if blocked_by and candidate in {"buy", "add", "trim", "sell"}:
        return "no_trade"
    return candidate


def advisory_action(action: Action) -> Action:
    if action in {"buy", "add"}:
        return "add_candidate"
    if action in {"trim", "sell"}:
        return "trim_candidate"
    return action


def internal_signal_intent(action: object) -> InternalSignalIntent:
    """Compatibility adapter from v1 action text to analytical intent."""

    return internal_intent_for_legacy_action(action)


def public_research_state(action: object) -> ResearchState:
    """Compatibility adapter that fails closed on unknown action text."""

    return research_state_for_legacy_action(action)


__all__ = [
    "advisory_action",
    "apply_gate_result",
    "internal_signal_intent",
    "preliminary_action",
    "public_research_state",
]
