from __future__ import annotations

from etf_cockpit.signals.friction_edge import estimate_friction_edge


def test_friction_edge_reports_gross_net_and_ratio_across_scenarios() -> None:
    result = estimate_friction_edge(8.0, 0.2, {"low": 5, "base": 15, "high": 30}, "base")
    assert result.gross_bps > result.net_bps
    assert result.edge_to_cost_ratio > 0
    assert result.scenario == "base"


def test_friction_edge_supports_low_base_high_cost_boundaries_deterministically() -> None:
    costs = {"low": 5.0, "base": 15.0, "high": 30.0}
    low = estimate_friction_edge(8.0, 0.2, costs, "low")
    base = estimate_friction_edge(8.0, 0.2, costs, "base")
    high = estimate_friction_edge(8.0, 0.2, costs, "high")

    assert low.cost_bps < base.cost_bps < high.cost_bps
    assert low.net_bps > base.net_bps > high.net_bps
    assert low.status == base.status == high.status == "available"
    assert low.execution_allowed is base.execution_allowed is high.execution_allowed is False


def test_friction_edge_rejects_missing_non_finite_and_unsupported_inputs() -> None:
    for kwargs in (
        {"evidence_score": None, "volatility": 0.2, "costs": {"base": 10}},
        {"evidence_score": 8.0, "volatility": float("nan"), "costs": {"base": 10}},
        {"evidence_score": 8.0, "volatility": 0.2, "costs": {"base": 10}, "scenario": "stress"},
        {"evidence_score": 11.0, "volatility": 0.2, "costs": {"base": 10}},
    ):
        result = estimate_friction_edge(**kwargs)
        assert result.status == "unavailable"
        assert result.net_bps is None
        assert result.reason
