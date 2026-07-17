from __future__ import annotations

import inspect

import pandas as pd
import pytest

from etf_cockpit.app.pages.backtests import backtests_page
from etf_cockpit.backtest.engine import BacktestDataUnavailableError, run_backtest
from etf_cockpit.backtest.metrics import tail_event_diagnostics
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices


def test_tail_event_diagnostics_expose_worst_windows_and_loss_clustering() -> None:
    index = pd.bdate_range("2026-01-01", periods=14)
    equity = pd.Series(
        [100.0, 105.0, 100.0, 96.0, 92.0, 90.0, 95.0, 94.0, 100.0, 99.0, 101.0, 100.0, 103.0, 104.0],
        index=index,
    )

    diagnostics = tail_event_diagnostics(equity)

    assert diagnostics["worst_1d_return"] < 0
    assert diagnostics["worst_5d_return"] < diagnostics["worst_1d_return"]
    assert diagnostics["worst_10d_return"] < 0
    assert diagnostics["loss_cluster_max_days"] == 4
    assert diagnostics["worst_drawdown_start"] == index[1].date()
    assert diagnostics["worst_drawdown_end"] == index[5].date()


def test_backtest_rejects_insufficient_complete_adjusted_price_history() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=259, end_date=pd.Timestamp("2026-06-26").date())

    with pytest.raises(BacktestDataUnavailableError, match="not_enough_data"):
        run_backtest(config, prices)


def test_backtest_report_makes_data_and_execution_assumptions_explicit() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    missing_date = pd.to_datetime(prices["date"]).sort_values().iloc[280]
    prices = prices.loc[~((pd.to_datetime(prices["date"]) == missing_date) & (prices["etf_id"] == config.universe.enabled_ids[0]))].copy()

    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert report.metadata["price_field"] == "adjusted_close"
    assert report.metadata["forward_fill_used"] is False
    assert report.metadata["missing_observation_rows"] >= 1
    assert report.metadata["lookahead_protection"] == "history_truncated_at_signal_date"
    assert report.metadata["execution_delay_sessions"] == 1
    assert report.metadata["benchmark_strategy"] == "buy_and_hold"
    assert report.metadata["data_status"] == "warning"
    required_trade_fields = {
        "signal_date",
        "execution_date",
        "decision_price",
        "next_open_reference_price",
        "close_to_next_open_gap",
        "arrival_price_assumption",
        "spread_proxy",
        "same_bar_execution_avoided",
    }
    assert required_trade_fields <= set(report.trade_log.columns)
    assert report.trade_log["same_bar_execution_avoided"].eq(True).all()
    assert (pd.to_datetime(report.trade_log["execution_date"]) > pd.to_datetime(report.trade_log["signal_date"])).all()
    required_result_fields = {
        "worst_1d_return",
        "worst_5d_return",
        "worst_10d_return",
        "loss_cluster_max_days",
        "overfitting_warning",
        "parameter_sensitivity_status",
    }
    assert required_result_fields <= set(report.results.columns)
    assert report.results["overfitting_warning"].notna().all()


def test_backtests_page_exposes_lab_evidence_sections() -> None:
    source = inspect.getsource(backtests_page)

    assert "Tail-event diagnostics" in source
    assert "Operational execution evidence" in source
    assert "Overfitting warning" in source
    assert "next-open" in source
