from __future__ import annotations

import pandas as pd

from etf_cockpit.backtest.engine import run_backtest
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices


def test_basic_backtest_run_on_sample_data() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    report = run_backtest(config, prices, rebalance_frequency_days=42)
    assert set(report.results["strategy_name"]) >= {"buy_and_hold", "equal_weight", "momentum_only", "trend_only", "signal_strategy"}
    assert (report.results["cost_drag"] >= 0).all()
    assert not report.equity_curves.empty
    assert report.metadata["cost_model_id"] == "execution-cost-v1"
    assert report.metadata["cost_model_execution_allowed"] is False
    assert set(report.trade_log["cost_model_id"]) <= {"execution-cost-v1"}


def test_backtest_trades_execute_after_signal_date() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert not report.trade_log.empty
    signal_dates = pd.to_datetime(report.trade_log["signal_date"])
    execution_dates = pd.to_datetime(report.trade_log["execution_date"])
    assert (execution_dates > signal_dates).all()


def test_backtest_advanced_diagnostics_are_estimated() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert report.results["probabilistic_sharpe"].notna().all()
    assert report.results["deflated_sharpe"].notna().all()
    assert report.results["pbo_probability_backtest_overfitting"].between(0, 1).all()
    assert set(report.results["parameter_sensitivity_status"]) <= {"stable", "mixed", "fragile", "insufficient_history"}
    assert "not_run" not in set(report.results["parameter_sensitivity_status"])
    assert set(report.results["backtest_quality"]) <= {"low", "medium"}


def test_backtest_hit_rate_is_paired_with_payoff_diagnostics() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    report = run_backtest(config, prices, rebalance_frequency_days=42)

    required = {
        "return_hit_rate",
        "average_win_return",
        "average_loss_return",
        "payoff_ratio",
        "expected_value_per_period",
        "payoff_asymmetry_warning",
    }

    assert required <= set(report.results.columns)
    assert report.results["return_hit_rate"].dropna().between(0, 1).all()
    assert report.results["payoff_asymmetry_warning"].notna().all()
    rows_with_hit_rate = report.results[report.results["return_hit_rate"].notna()]
    assert rows_with_hit_rate["payoff_ratio"].notna().any()
    assert rows_with_hit_rate["expected_value_per_period"].notna().any()
