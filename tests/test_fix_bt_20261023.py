from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.backtest import engine
from etf_cockpit.backtest.benchmarks import target_weights
from etf_cockpit.backtest.engine import (
    _apply_capacity_limits,
    _apply_minimum_trade_band,
    _fx_rate_pivot,
    _weighted_reference_price,
    run_backtest,
)
from etf_cockpit.backtest.metrics import _adjacent_log_returns, max_drawdown
from etf_cockpit.core.config import load_config
from etf_cockpit.data.fx_data import sample_fx_rates
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.features.feature_pipeline import eur_basis_prices


@pytest.fixture(scope="module")
def bt_inputs():
    config = load_config()
    prices = generate_sample_prices(config, periods=270, end_date=date(2026, 6, 26))
    return config, prices


def test_a05_f1_rebalance_history_and_benchmark_use_eur_prices(bt_inputs, monkeypatch) -> None:
    config, source_prices = bt_inputs
    item = next(item for item in config.universe.etfs if item.currency != "EUR" and item.id in set(source_prices["etf_id"]))
    prices = source_prices.copy()
    prices.loc[prices["etf_id"].eq(item.id), "adjusted_close"] = 100.0
    fx = sample_fx_rates(prices)
    currency_rows = fx["base_currency"].eq(item.currency)
    fx.loc[currency_rows, "rate"] = 0.1 * np.exp(0.002 * np.arange(int(currency_rows.sum())))

    captured_history: list[pd.DataFrame] = []
    captured_benchmarks: list[pd.Series] = []
    original_momentum = engine.momentum_weights
    original_metrics = engine.performance_metrics

    def record_history(history: pd.DataFrame, columns: list[str]) -> pd.Series:
        captured_history.append(history.copy())
        return original_momentum(history, columns)

    def record_benchmark(equity, benchmark=None, **kwargs):
        if benchmark is not None:
            captured_benchmarks.append(benchmark.copy())
        return original_metrics(equity, benchmark=benchmark, **kwargs)

    monkeypatch.setattr(engine, "momentum_weights", record_history)
    monkeypatch.setattr(engine, "performance_metrics", record_benchmark)
    monkeypatch.setattr(engine, "_validated_benchmark_data_id", lambda *_args, **_kwargs: item.id)

    report = run_backtest(config, prices, rebalance_frequency_days=42, fx_rates=fx)

    expected_eur = eur_basis_prices(
        prices,
        fx,
        configured_currency={member.id: str(member.currency or "EUR") for member in config.universe.etfs},
        known_by=pd.Timestamp("2026-06-27T00:00:00Z"),
    ).frame
    assert captured_history
    decision_day = captured_history[0].index[-1]
    expected_history_price = float(
        expected_eur.loc[
            pd.to_datetime(expected_eur["date"]).eq(decision_day) & expected_eur["etf_id"].eq(item.id),
            "adjusted_close",
        ].iloc[0]
    )
    assert captured_history[0].loc[decision_day, item.id] == pytest.approx(expected_history_price)
    assert captured_history[0].loc[decision_day, item.id] != pytest.approx(100.0)

    first_curve_day = report.equity_curves.index[0]
    expected_benchmark = float(
        expected_eur.loc[
            pd.to_datetime(expected_eur["date"]).eq(first_curve_day) & expected_eur["etf_id"].eq(item.id),
            "adjusted_close",
        ].iloc[0]
    )
    assert captured_benchmarks
    assert captured_benchmarks[0].loc[first_curve_day] == pytest.approx(expected_benchmark)


def test_a05_f2_drawdown_peak_and_returns_respect_equity_gaps() -> None:
    equity = pd.Series(
        [100.0, 90.0, np.nan, 50.0],
        index=pd.date_range("2024-01-01", periods=4, freq="D"),
    )

    assert max_drawdown(equity) == pytest.approx(-0.5)
    returns = _adjacent_log_returns(equity)
    assert len(returns) == 1
    assert returns.iloc[0] == pytest.approx(np.log(0.9))


def test_a05_f3_missing_active_fx_return_marks_nav_unavailable(bt_inputs) -> None:
    config, prices = bt_inputs
    item = next(item for item in config.universe.etfs if item.currency != "EUR" and item.id in set(prices["etf_id"]))
    fx = sample_fx_rates(prices)
    sessions = pd.to_datetime(prices["date"]).drop_duplicates().sort_values().reset_index(drop=True)
    gap_day = sessions.iloc[225]
    duplicate = fx.loc[
        fx["base_currency"].eq(item.currency)
        & pd.to_datetime(fx["as_of_date"]).eq(gap_day),
    ].iloc[0].copy()
    duplicate["rate"] = float(duplicate["rate"]) * 2.0
    fx = pd.concat([fx, duplicate.to_frame().T], ignore_index=True)

    report = run_backtest(config, prices, rebalance_frequency_days=10_000, fx_rates=fx)

    equal_weight = report.equity_curves["equal_weight"]
    assert np.isfinite(equal_weight.loc[:gap_day].iloc[:-1]).any()
    assert pd.isna(equal_weight.loc[gap_day])
    assert equal_weight.loc[gap_day:].isna().all()


def test_a05_f4_executes_start_index_rebalance(bt_inputs) -> None:
    config, prices = bt_inputs

    for frequency, expected_rebalances in ((21, 3), (40, 2)):
        report = run_backtest(config, prices, rebalance_frequency_days=frequency)

        assert report.metadata["walk_forward_periods"] == expected_rebalances


def test_a05_f5_fx_rows_known_after_session_are_excluded() -> None:
    fx = pd.DataFrame(
        [
            {
                "as_of_date": "2024-01-02",
                "base_currency": "NOK",
                "quote_currency": "EUR",
                "rate": 0.09,
                "source": "synthetic_sample",
                "ingested_at": "2024-01-02T12:00:00Z",
            }
        ]
    )
    sessions = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])

    converted = _fx_rate_pivot(
        sessions,
        ["KOG"],
        {"KOG": "NOK"},
        fx,
        pd.Timestamp("2024-01-05T00:00:00Z"),
    )

    assert pd.isna(converted.loc[sessions[0], "KOG"])
    assert converted.loc[sessions[1], "KOG"] == pytest.approx(0.09)


def test_a05_f6_existing_cash_funds_buys_and_secondary_capacity_reductions_are_logged() -> None:
    current = pd.Series({"A": 0.50, "B": 0.50, "C": 0.0})
    target = pd.Series({"A": 0.0, "B": 0.46, "C": 0.06})
    banded = _apply_minimum_trade_band(
        current, target, notional_eur=10_000.0, min_trade_eur=500.0
    )
    assert banded["C"] == pytest.approx(0.06)
    assert float(banded.sum()) == pytest.approx(0.56)

    capped, info = _apply_capacity_limits(
        current,
        pd.Series({"A": 0.0, "B": 0.40, "C": 0.60}),
        notional_eur=10_000.0,
        volume_row=pd.Series({"A": 0.0, "B": 1_000_000.0, "C": 1_000_000.0}),
        price_row=pd.Series({"A": 100.0, "B": 100.0, "C": 100.0}),
        adv_by_instrument={"A": 1_000_000.0, "B": 1_000_000.0, "C": 1_000_000.0},
        participation=0.1,
        manual_quote_ids=set(),
        checked_ids={"A", "B", "C"},
    )
    assert capped["C"] == pytest.approx(0.10)
    assert float(info["unfilled_eur"]) == pytest.approx(10_000.0)
    assert "partial_fill_sell_shortfall" in info["statuses"]["C"]


def test_a05_f7_calendar_resolver_gets_explicit_cutoff_without_price_identity(bt_inputs, monkeypatch) -> None:
    config, source_prices = bt_inputs
    prices = source_prices.drop(columns=engine._CALENDAR_COLUMNS, errors="ignore").copy()
    columns = [instrument_id for instrument_id in config.universe.enabled_ids if instrument_id in set(prices["etf_id"])]
    base = target_weights(config, columns)
    target_id = next(instrument_id for instrument_id in columns if base[instrument_id] < 1.0 - 1e-12)
    calls: list[tuple[str, object]] = []

    def all_weight_one(_history, ids):
        return pd.Series({instrument_id: float(instrument_id == target_id) for instrument_id in ids})

    def resolve(instrument_id: str, cutoff: object):
        calls.append((instrument_id, cutoff))
        return {"status": "unavailable", "instrument_id": instrument_id, "execution_allowed": False}

    monkeypatch.setattr(engine, "momentum_weights", all_weight_one)
    monkeypatch.setattr(engine, "_canonical_session_close_timestamp", lambda *_args, **_kwargs: None)

    run_backtest(config, prices, rebalance_frequency_days=10_000, calendar_identity_resolver=resolve)

    assert calls
    assert any(instrument_id == target_id for instrument_id, _ in calls)
    assert all(pd.Timestamp(cutoff).tzinfo is not None for _, cutoff in calls)


def test_a05_f8_untraded_price_cannot_supply_weighted_reference() -> None:
    values = pd.Series({"A": np.nan, "B": 500.0})
    changed_weights = pd.Series({"A": 1.0, "B": 0.0})

    assert _weighted_reference_price(values, changed_weights) is None
