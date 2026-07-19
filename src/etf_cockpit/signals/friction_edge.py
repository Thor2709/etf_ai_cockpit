from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


@dataclass(frozen=True)
class FrictionEdgeResult:
    evidence_score: float | None
    gross_bps: float | None
    volatility_penalty_bps: float | None
    cost_bps: float | None
    net_bps: float | None
    edge_to_cost_ratio: float | None
    scenario: str
    status: str = "unavailable"
    reason: str = "Friction-adjusted edge unavailable."
    source_dataset: str = "score_to_edge_proxy"
    execution_allowed: bool = False


@dataclass(frozen=True)
class FrictionAdjustedReturnResult:
    """Distribution-based return estimate after the configured order cost."""

    q10_return: float | None
    q50_return: float | None
    q90_return: float | None
    net_q10_return: float | None
    net_expected_return: float | None
    net_q90_return: float | None
    order_value_eur: float | None
    cost_bps: float | None
    cost_eur: float | None
    return_to_cost_ratio: float | None
    status: str = "unavailable"
    reason: str = "Friction-adjusted return unavailable."
    source_dataset: str = "forecast_return_distribution"
    distribution_version: str = "expected-return-distribution.v1"
    execution_allowed: bool = False


def estimate_friction_adjusted_return(
    distribution: Mapping[str, object] | None,
    *,
    order_value_eur: float | None,
    cost_estimate: Mapping[str, object] | None,
) -> FrictionAdjustedReturnResult:
    """Subtract a size-specific cost estimate from a return distribution.

    ``distribution`` contains horizon returns as decimal fractions, not score
    values.  The cost estimate is expected to come from the shared local cost
    model and must describe the same order size.  Every malformed or missing
    input fails closed to explicit unavailable values.
    """

    if not isinstance(distribution, Mapping):
        return _return_unavailable("Expected-return distribution is unavailable.")
    q10 = _finite(distribution.get("q10_return"))
    q50 = _finite(distribution.get("q50_return"))
    q90 = _finite(distribution.get("q90_return"))
    if any(value is None for value in (q10, q50, q90)) or not q10 <= q50 <= q90:
        return _return_unavailable("Expected-return quantiles are missing, non-finite or not ordered.")
    order_value = _finite(order_value_eur)
    if order_value is None or order_value <= 0.0:
        return _return_unavailable("A positive order size is required for a friction-adjusted return estimate.")
    if not isinstance(cost_estimate, Mapping):
        return _return_unavailable("Order-size cost estimate is unavailable.")
    cost_bps = _finite(cost_estimate.get("total_cost_bps"))
    cost_eur = _finite(cost_estimate.get("total_cost_eur"))
    if cost_bps is None or cost_bps < 0.0 or cost_eur is None or cost_eur < 0.0:
        return _return_unavailable("Order-size cost estimate is missing, negative or non-finite.")
    cost_fraction = cost_bps / 10_000.0
    net_q10 = q10 - cost_fraction
    net_q50 = q50 - cost_fraction
    net_q90 = q90 - cost_fraction
    ratio = None if cost_fraction == 0.0 else net_q50 / cost_fraction
    return FrictionAdjustedReturnResult(
        q10_return=round(q10, 12),
        q50_return=round(q50, 12),
        q90_return=round(q90, 12),
        net_q10_return=round(net_q10, 12),
        net_expected_return=round(net_q50, 12),
        net_q90_return=round(net_q90, 12),
        order_value_eur=round(order_value, 8),
        cost_bps=round(cost_bps, 8),
        cost_eur=round(cost_eur, 8),
        return_to_cost_ratio=None if ratio is None else round(ratio, 12),
        status="available",
        reason="Expected-return distribution adjusted by the shared order-size cost model.",
    )


def estimate_friction_edge(
    evidence_score: float | None,
    volatility: float | None,
    costs: Mapping[str, float] | None,
    scenario: str = "base",
) -> FrictionEdgeResult:
    """Estimate a deterministic score-to-edge proxy under a cost scenario.

    This deliberately remains a research display calculation. Missing,
    non-finite, out-of-range or unsupported values produce explicit N/A
    fields rather than a made-up edge or an execution signal.
    """

    scenario = str(scenario or "").strip().lower()
    if scenario not in {"low", "base", "high"}:
        return _unavailable(scenario, "Unsupported friction scenario; use low, base or high.")
    score = _finite(evidence_score)
    volatility_value = _finite(volatility)
    if score is None or not 0.0 <= score <= 10.0:
        return _unavailable(scenario, "Evidence score is missing or outside the supported 0-10 range.")
    if volatility_value is None or volatility_value < 0.0:
        return _unavailable(scenario, "Volatility is missing, negative or non-finite.")
    if not isinstance(costs, Mapping) or scenario not in costs:
        return _unavailable(scenario, "Selected cost scenario is unavailable.")
    cost = _finite(costs.get(scenario))
    if cost is None or cost < 0.0:
        return _unavailable(scenario, "Selected cost is missing, negative or non-finite.")

    gross = max(0.0, (score - 5.0) * 25.0)
    volatility_penalty = volatility_value * 20.0
    net = gross - volatility_penalty - cost
    ratio = None if cost == 0.0 else net / cost
    return FrictionEdgeResult(
        evidence_score=score,
        gross_bps=gross,
        volatility_penalty_bps=volatility_penalty,
        cost_bps=cost,
        net_bps=net,
        edge_to_cost_ratio=ratio,
        scenario=scenario,
        status="available",
        reason="Gross/net edge proxy computed from deterministic score, volatility and configured costs.",
    )


def _finite(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _unavailable(scenario: str, reason: str) -> FrictionEdgeResult:
    return FrictionEdgeResult(None, None, None, None, None, None, scenario, reason=reason)


def _return_unavailable(reason: str) -> FrictionAdjustedReturnResult:
    return FrictionAdjustedReturnResult(None, None, None, None, None, None, None, None, None, None, reason=reason)


__all__ = [
    "FrictionAdjustedReturnResult",
    "FrictionEdgeResult",
    "estimate_friction_adjusted_return",
    "estimate_friction_edge",
]
