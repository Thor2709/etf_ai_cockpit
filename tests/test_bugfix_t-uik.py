"""Bug-fix batch T-UIK: UI and cross-page items K04-K11 (docs/development/BUGFIX-PLAN-2026-10-10.md, section K)."""

from __future__ import annotations

import pandas as pd

from etf_cockpit.backtest.engine import run_backtest
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices


# --- K10: slowness -------------------------------------------------------------------------------


def test_k10_backtest_signal_log_only_holds_enabled_instruments() -> None:
    """A disabled instrument with price rows must not enter the signal log: the cache validator
    only accepts enabled ids, so one such row made every cold start recalculate the backtest (40-60 s)."""

    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    disabled = config.universe.etfs[-1]
    disabled.enabled = False
    assert disabled.id in set(prices["etf_id"]) and disabled.id not in config.universe.enabled_ids

    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert not report.signal_log.empty
    assert set(report.signal_log["etf_id"]) <= set(config.universe.enabled_ids)


def test_k10_heavy_evidence_routes_build_behind_the_skeleton() -> None:
    from etf_cockpit.app import router

    assert {"/signals", "/backtests", "/forward-evidence"} <= router._DEFERRED_RENDER_ROUTES
