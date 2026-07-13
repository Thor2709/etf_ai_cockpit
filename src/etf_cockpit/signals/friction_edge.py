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
