"""CB1: the backtest honours the configured minimum trade (no-trade band) instead of charging a flat fee on dust."""

from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.backtest.engine import _apply_minimum_trade_band, run_backtest
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices

END = pd.Timestamp("2026-06-26").date()


def _weights(**values: float) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_orders_below_the_minimum_trade_are_dropped_and_full_exits_still_sell() -> None:
    current = _weights(A=0.50, B=0.30, C=0.015, D=0.0, E=0.185)
    target = _weights(A=0.505, B=0.30, C=0.0, D=0.004, E=0.191)
    # 10_000 EUR book, 100 EUR minimum: A +50 EUR, D +40 EUR and E +60 EUR are dust; C leaves the target set in full.
    executed = _apply_minimum_trade_band(current, target, notional_eur=10_000.0, min_trade_eur=100.0)
    assert executed["A"] == pytest.approx(0.50)
    assert executed["D"] == pytest.approx(0.0)
    assert executed["E"] == pytest.approx(0.185)
    assert executed["C"] == pytest.approx(0.0)
    assert float(executed.sum()) <= float(target.sum()) + 1e-12


def test_skipped_sells_never_fund_buys_so_the_book_cannot_exceed_the_intended_one() -> None:
    current = _weights(A=0.505, B=0.495, C=0.0)
    target = _weights(A=0.50, B=0.40, C=0.10)
    # The 50 EUR sell of A is dust and stays held; the buys are scaled down by that surplus.
    executed = _apply_minimum_trade_band(current, target, notional_eur=10_000.0, min_trade_eur=100.0)
    assert executed["A"] == pytest.approx(0.505)
    assert float(executed.sum()) <= float(target.sum()) + 1e-12
    assert (executed - current).clip(lower=0.0).sum() < (target - current).clip(lower=0.0).sum()


def test_a_zero_minimum_disables_the_band() -> None:
    current = _weights(A=0.5, B=0.5)
    target = _weights(A=0.501, B=0.499)
    assert _apply_minimum_trade_band(current, target, notional_eur=10_000.0, min_trade_eur=0.0).equals(target)


def test_run_backtest_skips_dust_rebalances_and_rejects_a_negative_minimum() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=340, end_date=END)
    kwargs = {"rebalance_frequency_days": 42}
    unbanded = run_backtest(config, prices, min_trade_value_eur=0.0, **kwargs)
    banded = run_backtest(config, prices, min_trade_value_eur=1_000_000_000.0, **kwargs)
    # The band is opt-in: leaving it out keeps every order exactly as before (the golden stays untouched).
    default = run_backtest(config, prices, **kwargs)
    assert default.trade_log.equals(unbanded.trade_log)

    def rebalances(report: object, strategy: str) -> int:
        log = report.trade_log  # type: ignore[attr-defined]
        return int((log["strategy"] == strategy).sum()) if len(log) else 0

    assert rebalances(unbanded, "equal_weight") > 0
    # Equal weight never leaves its target set, so with every order below the minimum it never trades again.
    assert rebalances(banded, "equal_weight") == 0
    cost = lambda report: float(report.results.set_index("strategy_name").loc["equal_weight", "cost_drag"])  # noqa: E731
    assert cost(banded) < cost(unbanded)
    with pytest.raises(ValueError, match="min_trade_value_eur"):
        run_backtest(config, prices, min_trade_value_eur=-1.0, **kwargs)
