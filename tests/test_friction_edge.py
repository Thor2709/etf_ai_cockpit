from __future__ import annotations

import pandas as pd

from etf_cockpit.models.forecast_scores import forecast_return_distributions
from etf_cockpit.signals.friction_edge import estimate_friction_edge
from etf_cockpit.signals.friction_edge import estimate_friction_adjusted_return


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


def test_friction_adjusted_return_uses_order_size_and_preserves_quantile_order() -> None:
    result = estimate_friction_adjusted_return(
        {"q10_return": -0.04, "q50_return": 0.06, "q90_return": 0.14},
        order_value_eur=2_000.0,
        cost_estimate={"total_cost_bps": 25.0, "total_cost_eur": 5.0},
    )

    assert result.status == "available"
    assert result.q50_return == 0.06
    assert result.net_expected_return == 0.0575
    assert result.net_q10_return < result.net_expected_return < result.net_q90_return
    assert result.order_value_eur == 2_000.0
    assert result.return_to_cost_ratio == 23.0
    assert result.execution_allowed is False


def test_friction_adjusted_return_fails_closed_without_positive_order_or_cost() -> None:
    for order_value, cost in (
        (None, {"total_cost_bps": 10.0, "total_cost_eur": 1.0}),
        (0.0, {"total_cost_bps": 10.0, "total_cost_eur": 1.0}),
        (1_000.0, None),
        (1_000.0, {"total_cost_bps": -1.0, "total_cost_eur": 1.0}),
    ):
        result = estimate_friction_adjusted_return(
            {"q10_return": 0.0, "q50_return": 0.01, "q90_return": 0.02},
            order_value_eur=order_value,
            cost_estimate=cost,
        )
        assert result.status == "unavailable"
        assert result.net_expected_return is None
        assert result.reason


def test_forecast_return_distribution_aggregates_allowed_model_quantiles() -> None:
    forecasts = pd.DataFrame(
        [
            {"model_name": "baseline", "etf_id": "VWCE", "horizon_days": 60, "expected_return": 0.05, "q10_return": -0.03, "q50_return": 0.05, "q90_return": 0.13, "status": "ok", "model_allowed_in_score": True},
            {"model_name": "timesfm", "etf_id": "VWCE", "horizon_days": 60, "expected_return": 0.07, "q10_return": -0.01, "q50_return": 0.07, "q90_return": 0.15, "status": "ok", "model_allowed_in_score": True},
            {"model_name": "toto", "etf_id": "VWCE", "horizon_days": 60, "expected_return": 0.50, "q10_return": 0.40, "q50_return": 0.50, "q90_return": 0.60, "status": "ok", "model_allowed_in_score": False},
        ]
    )

    distribution = forecast_return_distributions(forecasts)["VWCE"]

    assert distribution["status"] == "available"
    assert distribution["q10_return"] == -0.02
    assert distribution["q50_return"] == 0.06
    assert distribution["q90_return"] == 0.14
    assert distribution["model_count"] == 2
