"""Strict-xfail reproductions for bug-hunt slice S2."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest


def test_s2_01_geometric_portfolio_value():
    from etf_cockpit.backtest.engine import run_backtest
    from etf_cockpit.core.config import load_config

    config = load_config()
    ids = config.universe.enabled_ids[:2]
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame(
        [(d, k, 100.0 if k == ids[1] or j <= 220 else 200.0) for j, d in enumerate(dates) for k in ids],
        columns=["date", "etf_id", "adjusted_close"],
    )
    result = run_backtest(config, prices, rebalance_frequency_days=10000, transaction_cost_bps=0)
    assert math.isclose(result.equity_curves["equal_weight"].iloc[-1], 15000.0)


def test_s2_02_holdout_weights_use_training_only():
    from etf_cockpit.portfolio.optimiser import OptimiserConstraints, PortfolioOptimiser

    train = pd.DataFrame({"A": np.tile([-0.001, 0.001], 35), "B": np.tile([-0.02, 0.02], 35)})
    tail = pd.DataFrame({"A": np.tile([-0.05, 0.07], 15), "B": np.tile([-0.001, 0.003], 15)})
    constraints = OptimiserConstraints(max_weight=1.0)
    weights = PortfolioOptimiser(train).solve("inverse_volatility", constraints=constraints).weights
    result = PortfolioOptimiser(pd.concat([train, tail], ignore_index=True)).compare(
        ["inverse_volatility"], constraints=constraints
    )
    actual = result.set_index("method").loc["inverse_volatility", "validation_return_ann"]
    assert math.isclose(actual, float((tail @ weights).mean() * 252))


def _two_asset_prices(*, a_rows: int = 41) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=41)
    return pd.DataFrame(
        [
            (d, k, 100 * np.exp(0.01 * np.sin(j * (1 if k == "A" else 2))))
            for j, d in enumerate(dates)
            for k in ["A", "B"]
            if k == "B" or j < a_rows
        ],
        columns=["date", "etf_id", "adjusted_close"],
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S2-03: Explicit cash-only allocations become fully invested portfolios")
def test_s2_03_explicit_cash_only_weights_remain_zero():
    from etf_cockpit.portfolio.robust_risk import build_robust_risk_report

    allocation = pd.DataFrame({"etf_id": ["A", "B"], "current_weight": [0.0, 0.0]})
    report = build_robust_risk_report(_two_asset_prices(), allocation, bootstrap_reps=0)
    assert report["portfolio"]["weight_sum"] == 0.0


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S2-04: Weekly and monthly aggregation discard the first day's performance")
def test_s2_04_month_includes_first_day_pnl():
    from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series
    from etf_cockpit.portfolio.valuation import SNAPSHOT_COLUMNS

    rows = []
    for d, v, ret, pnl in [("2025-01-31", 100, 0, 0), ("2025-02-03", 110, 0.1, 10), ("2025-02-04", 110, 0, 0)]:
        rows.append(
            dict(
                dict.fromkeys(SNAPSHOT_COLUMNS, 0),
                date=d,
                total_value=v,
                securities_value=v,
                invested_capital=100,
                period_return=ret,
                investment_pnl=pnl,
                valuation_status="available",
                flow_status="available",
                availability_evidence="timestamped",
                missing_reasons="",
                execution_allowed=False,
            )
        )
    result = build_portfolio_performance_series(
        pd.DataFrame(rows), metric="investment_pnl", aggregation="month", currency="EUR"
    )
    assert result.points[-1].value == 10.0


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S2-05: Missing historical returns pass as complete stress coverage")
def test_s2_05_missing_historical_mark_is_partial():
    from etf_cockpit.portfolio.stress_testing import StressScenario, run_stress_scenario

    allocation = pd.DataFrame({"instrument_id": ["A", "B"], "weight": [0.5, 0.5]})
    hist = pd.DataFrame({"date": ["2024-02-01"], "instrument_id": ["A"], "adjusted_return": [-0.1]})
    scenario = StressScenario("s", "s", {"equity": 0}, historical_date="2024-02-01")
    result = run_stress_scenario(scenario, allocation, historical_returns=hist)
    assert result.status == "partial" and result.coverage["missing_instruments"] == ["B"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S2-06: Default stress correlation rejects valid portfolio forecasts")
def test_s2_06_default_stress_accepts_valid_psd_matrix():
    from etf_cockpit.portfolio.forecast_aggregation import _correlation_root, load_portfolio_forecast_config

    config = load_portfolio_forecast_config()
    matrix = np.full((3, 3), config.stress_correlation)
    np.fill_diagonal(matrix, 1.0)
    assert _correlation_root(matrix) is not None


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S2-07: Factor attribution ignores portfolio allocation weights")
def test_s2_07_factor_attribution_uses_actual_weights():
    from etf_cockpit.portfolio.attribution import build_performance_attribution
    from etf_cockpit.portfolio.factor_risk import build_factor_risk_report

    ids = list("ABCDE")
    dates = pd.bdate_range("2024-01-01", periods=6)
    allocation = pd.DataFrame(
        {"etf_id": ids, "current_weight": [1, 0, 0, 0, 0], "momentum_120d": [-2, -1, 0, 1, 2]}
    )
    prices = pd.DataFrame(
        [(d, k, 100 * np.exp((j + 1) * 0.01 * (n - 2))) for j, d in enumerate(dates) for n, k in enumerate(ids)],
        columns=["date", "etf_id", "adjusted_close"],
    )
    factor = build_factor_risk_report(prices, allocation)
    result = build_performance_attribution(
        prices, allocation, factor_returns=factor["factor_returns"], factor_exposures=factor["exposure_matrix"]
    )
    contribution = result["factor_attribution"].set_index("factor").loc["momentum", "contribution"]
    assert contribution < -0.01


@pytest.mark.xfail(strict=True, raises=ValueError, reason="S2-08: Sparse validation history crashes otherwise valid risk analysis")
def test_s2_08_sparse_holdout_falls_back_without_crashing():
    from etf_cockpit.portfolio.robust_risk import build_robust_risk_report

    allocation = pd.DataFrame({"etf_id": ["A", "B"], "current_weight": [0.5, 0.5]})
    report = build_robust_risk_report(_two_asset_prices(a_rows=28), allocation, bootstrap_reps=1)
    assert any(str(w).startswith("out_of_sample_") for w in report["diagnostics"]["warnings"])
