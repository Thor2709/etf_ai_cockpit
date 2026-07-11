from __future__ import annotations

from etf_cockpit.signals.friction_edge import estimate_friction_edge


def test_friction_edge_reports_gross_net_and_ratio_across_scenarios() -> None:
    result = estimate_friction_edge(8.0, 0.2, {"low": 5, "base": 15, "high": 30}, "base")
    assert result.gross_bps > result.net_bps
    assert result.edge_to_cost_ratio > 0
    assert result.scenario == "base"
