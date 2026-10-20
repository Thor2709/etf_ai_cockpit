from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Mapping

from etf_cockpit.core.values import finite_float_or_none as _finite
from etf_cockpit.models.calibration import log_to_simple_return


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
    horizon_days: int | None
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

    ``distribution`` contains horizon LOG returns as decimal fractions, not
    score values (forecast unit contract, see ``models.base``).  They are
    converted with ``expm1`` to simple returns here, at the monetary boundary,
    before the simple cost fraction is subtracted and before any euro or
    basis-point figure is derived.  The reported quantiles are simple returns.
    The cost estimate is expected to come from the shared local cost
    model and must describe the same order size.  Every malformed or missing
    input fails closed to explicit unavailable values.
    """

    if not isinstance(distribution, Mapping):
        return _return_unavailable("Expected-return distribution is unavailable.")
    q10 = _finite(distribution.get("q10_return"))
    q50 = _finite(distribution.get("q50_return"))
    q90 = _finite(distribution.get("q90_return"))
    horizon = _finite(distribution.get("horizon_days"))
    if (
        any(value is None for value in (q10, q50, q90, horizon))
        or horizon <= 0
        or not horizon.is_integer()
        or not q10 <= q50 <= q90
    ):
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
    estimated_order_value = _finite(cost_estimate.get("order_value_eur"))
    if estimated_order_value is None or not isclose(estimated_order_value, order_value, rel_tol=1e-9, abs_tol=1e-8):
        return _return_unavailable("Order-size cost estimate does not match the requested order value.")
    expected_cost_eur = order_value * cost_bps / 10_000.0
    if not isclose(cost_eur, expected_cost_eur, rel_tol=1e-9, abs_tol=1e-7):
        return _return_unavailable("Order-size cost estimate has inconsistent basis-point and euro totals.")
    cost_fraction = cost_bps / 10_000.0
    q10, q50, q90 = (log_to_simple_return(value) for value in (q10, q50, q90))
    if any(value is None for value in (q10, q50, q90)):
        return _return_unavailable("Expected-return quantiles are outside the representable log-return range.")
    q10, q50, q90 = float(q10), float(q50), float(q90)
    net_q10 = q10 - cost_fraction
    net_q50 = q50 - cost_fraction
    net_q90 = q90 - cost_fraction
    ratio = None if cost_fraction == 0.0 else net_q50 / cost_fraction
    return FrictionAdjustedReturnResult(
        q10_return=round(q10, 12),
        q50_return=round(q50, 12),
        q90_return=round(q90, 12),
        horizon_days=int(horizon),
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


@dataclass(frozen=True)
class FrictionGateResult:
    """Propose-or-hold verdict: expected net benefit must exceed every friction cost."""

    status: str
    propose: bool
    expected_benefit_bps: float | None
    turnover_cost_bps: float | None
    spread_cost_bps: float | None
    uncertainty_cost_bps: float | None
    required_bps: float | None
    net_benefit_bps: float | None
    reason: str
    execution_allowed: bool = False


def evaluate_friction_gate(
    expected_benefit_bps: float | None,
    *,
    order_value_eur: float | None,
    cost_estimate: Mapping[str, object] | None,
    uncertainty_bps: float | None = 0.0,
) -> FrictionGateResult:
    """Propose a trade only when the expected net benefit exceeds the friction.

    The friction is the order-size cost (commission, impact, FX, gap: the
    turnover cost), the spread (the upper end of the spread range when the
    spread is unknown) and the uncertainty cost.  A size-neutral estimate
    (order value 0 or not matching the order) is not valid for a gate, and any
    missing or non-finite input fails closed to ``unavailable`` / no proposal.
    """

    def unavailable(reason: str) -> FrictionGateResult:
        return FrictionGateResult("unavailable", False, None, None, None, None, None, None, reason)

    benefit = _finite(expected_benefit_bps)
    if benefit is None:
        return unavailable("Expected benefit is missing or non-finite.")
    order_value = _finite(order_value_eur)
    if order_value is None or order_value <= 0.0:
        return unavailable("A positive order size is required: a size-neutral cost cannot gate a trade.")
    if not isinstance(cost_estimate, Mapping):
        return unavailable("Order-size cost estimate is unavailable.")
    estimated_value = _finite(cost_estimate.get("order_value_eur"))
    if estimated_value is None or not isclose(estimated_value, order_value, rel_tol=1e-9, abs_tol=1e-8):
        return unavailable("Cost estimate does not describe the requested order size.")
    total_cost = _finite(cost_estimate.get("total_cost_bps"))
    spread = _finite(cost_estimate.get("spread_bps"))
    if total_cost is None or total_cost < 0.0 or spread is None or spread < 0.0:
        return unavailable("Cost estimate is missing, negative or non-finite.")
    spread_range = cost_estimate.get("spread_range_bps")
    if isinstance(spread_range, (list, tuple)) and len(spread_range) == 2:
        spread_high = _finite(spread_range[1])
        if spread_high is not None and spread_high > spread:
            spread = spread_high
    uncertainty = _finite(uncertainty_bps)
    if uncertainty is None or uncertainty < 0.0:
        return unavailable("Uncertainty cost is missing, negative or non-finite.")
    turnover_cost = max(0.0, total_cost - (_finite(cost_estimate.get("spread_bps")) or 0.0))
    required = turnover_cost + spread + uncertainty
    net = benefit - required
    propose = net > 0.0
    return FrictionGateResult(
        status="pass" if propose else "blocked",
        propose=propose,
        expected_benefit_bps=round(benefit, 8),
        turnover_cost_bps=round(turnover_cost, 8),
        spread_cost_bps=round(spread, 8),
        uncertainty_cost_bps=round(uncertainty, 8),
        required_bps=round(required, 8),
        net_benefit_bps=round(net, 8),
        reason=(
            "Expected benefit exceeds turnover, spread and uncertainty costs."
            if propose
            else "Expected benefit does not exceed turnover, spread and uncertainty costs."
        ),
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


def _unavailable(scenario: str, reason: str) -> FrictionEdgeResult:
    return FrictionEdgeResult(None, None, None, None, None, None, scenario, reason=reason)


def _return_unavailable(reason: str) -> FrictionAdjustedReturnResult:
    return FrictionAdjustedReturnResult(
        q10_return=None,
        q50_return=None,
        q90_return=None,
        horizon_days=None,
        net_q10_return=None,
        net_expected_return=None,
        net_q90_return=None,
        order_value_eur=None,
        cost_bps=None,
        cost_eur=None,
        return_to_cost_ratio=None,
        reason=reason,
    )


__all__ = [
    "FrictionAdjustedReturnResult",
    "FrictionEdgeResult",
    "FrictionGateResult",
    "evaluate_friction_gate",
    "estimate_friction_adjusted_return",
    "estimate_friction_edge",
]
