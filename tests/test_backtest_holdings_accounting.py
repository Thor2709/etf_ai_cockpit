"""Holdings accounting for run_backtest (bug-hunt S2-01, decision D7)."""

from __future__ import annotations

import math

import pandas as pd

from etf_cockpit.backtest.engine import run_backtest
from etf_cockpit.core.config import load_config


def _prices(ids: list[str], factor_a: dict[int, float], factor_b: dict[int, float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=260)
    rows = []
    for j, date in enumerate(dates):
        a = 100.0 * max((v for k, v in factor_a.items() if j >= k), default=1.0)
        b = 100.0 * max((v for k, v in factor_b.items() if j >= k), default=1.0)
        rows.extend([(date, ids[0], a), (date, ids[1], b)])
    return pd.DataFrame(rows, columns=["date", "etf_id", "adjusted_close"])


def test_drifted_holdings_value_both_legs_without_rebalance():
    config = load_config()
    ids = config.universe.enabled_ids[:2]
    prices = _prices(ids, {221: 2.0}, {240: 2.0})
    result = run_backtest(config, prices, rebalance_frequency_days=10000, transaction_cost_bps=0)
    # 50/50 start, both legs double in sequence and nothing is traded: units held are fixed.
    assert math.isclose(result.equity_curves["equal_weight"].iloc[-1], 20000.0)


def test_equal_weight_rebalance_charges_for_drifted_holdings():
    config = load_config()
    ids = config.universe.enabled_ids[:2]
    prices = _prices(ids, {221: 2.0}, {}).assign(volume=1_000_000.0)
    result = run_backtest(config, prices, rebalance_frequency_days=10, transaction_cost_bps=10)
    trades = result.trade_log
    equal = trades[trades["strategy"] == "equal_weight"]
    # The first rebalance must restore 50/50 from the drifted 2/3 : 1/3 mix (turnover 1/3).
    assert not equal.empty
    assert math.isclose(float(equal.iloc[0]["turnover"]), 1.0 / 3.0, rel_tol=1e-9)
    # Buy-and-hold keeps its drifted holdings and never trades.
    assert trades[trades["strategy"] == "buy_and_hold"].empty
