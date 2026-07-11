from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class FrictionEdgeResult:
    evidence_score: float
    gross_bps: float
    volatility_penalty_bps: float
    cost_bps: float
    net_bps: float
    edge_to_cost_ratio: float | None
    scenario: str


def estimate_friction_edge(evidence_score: float | None, volatility: float | None, costs: Mapping[str, float], scenario: str = "base") -> FrictionEdgeResult:
    score = 0.0 if evidence_score is None else max(0.0, min(10.0, float(evidence_score)))
    gross = max(0.0, (score - 5.0) * 25.0)
    volatility_penalty = max(0.0, float(volatility or 0.0)) * 20.0
    cost = max(0.0, float(costs.get(scenario, costs.get("base", 0.0))))
    net = gross - volatility_penalty - cost
    ratio = None if cost == 0 else net / cost
    return FrictionEdgeResult(score, gross, volatility_penalty, cost, net, ratio, scenario)
