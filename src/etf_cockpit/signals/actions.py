from __future__ import annotations

from typing import Mapping

from etf_cockpit.core.config import AppConfig
from etf_cockpit.governance.migrations import LegacyAction
from etf_cockpit.signals.research_states import (
    InternalSignalIntent,
    ResearchState,
    internal_intent_for_legacy_action,
    research_state_for_legacy_action,
)


_MANUAL_REVIEW_CODES = {
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


def preliminary_action(
    config: AppConfig,
    *,
    total_score: float | None = None,
    score_distribution: Mapping[str, float | None] | None = None,
    confidence: float,
    current_weight: float,
    drift: float,
    hard_band: float,
    trend_200: float,
) -> LegacyAction:
    if score_distribution is not None:
        return _distribution_action(
            config,
            score_distribution=score_distribution,
            confidence=confidence,
            current_weight=current_weight,
            drift=drift,
            hard_band=hard_band,
            trend_200=trend_200,
        )
    if total_score is None:
        return "hold"
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


def _distribution_action(
    config: AppConfig,
    *,
    score_distribution: Mapping[str, float | None],
    confidence: float,
    current_weight: float,
    drift: float,
    hard_band: float,
    trend_200: float,
) -> LegacyAction:
    """Map separated score distributions to a compatibility intent.

    Order and review policy consume attractiveness, expected return,
    risk/implementation and evidence coverage together. No legacy composite is
    used for this path.
    """

    attractiveness = score_distribution.get("attractiveness")
    expected_return = score_distribution.get("expected_return")
    risk = score_distribution.get("risk_implementation")
    evidence = score_distribution.get("evidence_confidence")
    coverage = score_distribution.get("coverage")
    if any(value is None for value in (attractiveness, expected_return, risk, evidence, coverage)):
        return "hold"
    if float(coverage) < 0.5 or float(evidence) < 0.5:
        return "hold"

    limits = config.risks.signal_limits
    if drift > hard_band and (float(attractiveness) < 0.45 or float(expected_return) < 0.45 or float(risk) < 0.40):
        if confidence >= limits.min_confidence_for_trim:
            return "trim"
    if drift < -hard_band and float(attractiveness) >= 0.55 and float(expected_return) >= 0.55 and float(risk) >= 0.45:
        if confidence >= limits.min_confidence_for_buy:
            return "buy" if current_weight <= 0 else "add"
    if (
        float(attractiveness) <= 0.35
        and float(expected_return) <= 0.40
        and float(risk) <= 0.40
        and confidence >= 0.65
        and current_weight > 0
        and trend_200 <= 0
    ):
        return "sell"
    if current_weight > 0 and (float(attractiveness) < 0.45 or float(expected_return) < 0.45 or float(risk) < 0.40):
        if confidence >= limits.min_confidence_for_trim:
            return "trim"
    if float(attractiveness) >= 0.60 and float(expected_return) >= 0.55 and float(risk) >= 0.50:
        if confidence >= limits.min_confidence_for_buy:
            return "buy" if current_weight <= 0 else "add"
    if limits.no_trade_lower < float(attractiveness) < limits.no_trade_upper and abs(drift) <= hard_band:
        return "no_trade"
    return "hold"


def apply_gate_result(candidate: LegacyAction, blocked_by: list[str]) -> LegacyAction:
    if any(code in _MANUAL_REVIEW_CODES for code in blocked_by):
        return "manual_review"
    if "model_disagreement" in blocked_by:
        return "manual_review"
    if blocked_by and candidate in {"buy", "add", "trim", "sell"}:
        return "no_trade"
    return candidate


def advisory_action(action: LegacyAction) -> LegacyAction:
    if action in {"buy", "add"}:
        return "add_candidate"
    if action in {"trim", "sell"}:
        return "trim_candidate"
    return action


def preliminary_intent(
    config: AppConfig,
    *,
    total_score: float,
    confidence: float,
    current_weight: float,
    drift: float,
    hard_band: float,
    trend_200: float,
) -> InternalSignalIntent:
    """Return analytical intent; legacy text stays at the compatibility seam."""

    return internal_intent_for_legacy_action(
        preliminary_action(
            config,
            total_score=total_score,
            confidence=confidence,
            current_weight=current_weight,
            drift=drift,
            hard_band=hard_band,
            trend_200=trend_200,
        )
    )


def apply_gate_intent(candidate: InternalSignalIntent, blocked_by: list[str]) -> InternalSignalIntent:
    """Apply compatibility gate outcomes without returning public action text."""

    if any(code in _MANUAL_REVIEW_CODES for code in blocked_by):
        return InternalSignalIntent.NONE
    if blocked_by and candidate in {InternalSignalIntent.INCREASE, InternalSignalIntent.DECREASE, InternalSignalIntent.EXIT}:
        return InternalSignalIntent.NONE
    return candidate


def internal_signal_intent(action: object) -> InternalSignalIntent:
    """Compatibility adapter from v1 action text to analytical intent."""

    return internal_intent_for_legacy_action(action)


def public_research_state(action: object) -> ResearchState:
    """Compatibility adapter that fails closed on unknown action text."""

    return research_state_for_legacy_action(action)


__all__ = [
    "advisory_action",
    "apply_gate_intent",
    "apply_gate_result",
    "internal_signal_intent",
    "preliminary_intent",
    "preliminary_action",
    "public_research_state",
]
