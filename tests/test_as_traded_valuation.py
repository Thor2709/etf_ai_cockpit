"""Valuation reverses later splits without changing adjusted return inputs."""

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import build_stock_evidence
from etf_cockpit.analysis.stock_universe import as_traded_close, market_inputs
from etf_cockpit.data.stock_fundamentals import load_stock_config
from etf_cockpit.features.momentum import momentum
from etf_cockpit.features.returns import daily_log_returns


def _prices() -> pd.DataFrame:
    return pd.DataFrame({
        "etf_id": ["NVDA"] * 4,
        "date": pd.to_datetime(["2022-10-17", "2022-11-30", "2024-06-10", "2024-06-11"]),
        "close": [11.888, 12.0, 121.0, 120.0],
        "adjusted_close": [11.5, 11.6, 120.5, 119.5],
        "volume": [100.0, 200.0, 300.0, 400.0],
        "currency": ["USD"] * 4,
        "stock_splits": [0.0, 0.0, 10.0, 0.0],
        "dividends": [0.0] * 4,
        "actions_evidenced": [True] * 4,
    })


def _market(prices, decision="2022-10-18T12:00:00+00:00", config=None):
    return market_inputs(prices, None, "USD", datetime.fromisoformat(decision), pd.DataFrame(), config or load_stock_config())


def _periods():
    known = datetime(2022, 2, 15, tzinfo=timezone.utc)
    statement = sm.Period(date(2021, 12, 31), "FY", known, "USD", "sec_edgar", {
        "net_income_parent": 10e9, "revenue": 30e9, "ebit": 12e9,
        "cfo": 12e9, "capex": 2e9, "equity_parent": 20e9,
        "minority_interest": 0.0, "ib_debt": 5e9, "lease_liabilities": 0.0, "cash_sti": 2e9,
    })
    shares = sm.Period(date(2022, 9, 30), "SHARES", datetime(2022, 10, 10, tzinfo=timezone.utc),
                       "", "sec_dei", {"shares_outstanding": 2.5e9})
    return [statement, shares]


def _evidence(market, decision="2022-10-18T12:00:00+00:00", config=None):
    return build_stock_evidence("NVDA", _periods(), datetime.fromisoformat(decision), market, None, config or load_stock_config())


def test_pre_split_date_uses_as_traded_price_and_reported_shares():
    market = _market(_prices())
    assert market.price == pytest.approx(118.88, rel=1e-12)
    assert market.price_date == date(2022, 10, 17)
    metrics = _evidence(market).metrics
    cap = 118.88 * 2.5e9
    assert metrics["market_cap"].value == pytest.approx(cap, rel=1e-9)
    assert metrics["pe"].value == pytest.approx(cap / 10e9, rel=1e-9)
    assert metrics["ev"].value == pytest.approx(cap + 3e9, rel=1e-9)
    assert metrics["pb"].value == pytest.approx(cap / 20e9, rel=1e-9)
    assert metrics["fcf_yield"].value == pytest.approx(10e9 / cap, rel=1e-9)


@pytest.mark.parametrize("day, expected", [(date(2024, 6, 10), 121.0), (date(2024, 6, 11), 120.0)])
def test_split_day_and_post_split_date_are_unchanged(day, expected):
    assert as_traded_close(_prices(), day) == (expected, None)
    market = _market(_prices(), f"{day.isoformat()}T23:59:59+00:00")
    # A bar is first known the next day; the helper itself uses the exact date.
    assert market.price_date < day
    next_day = (pd.Timestamp(day) + pd.Timedelta(days=1)).date()
    assert _market(_prices(), f"{next_day}T12:00:00+00:00").price == expected


def test_two_splits_compound_including_a_reverse_split():
    prices = _prices()
    prices.loc[3, "stock_splits"] = 0.5
    assert as_traded_close(prices, date(2022, 10, 17)) == (59.44, None)
    assert as_traded_close(prices, date(2024, 6, 10)) == (60.5, None)
    assert as_traded_close(prices, date(2024, 6, 11)) == (120.0, None)
    prices.loc[3, "stock_splits"] = 3.0
    assert as_traded_close(prices, date(2022, 10, 17))[0] == pytest.approx(356.64)


def test_no_split_instrument_is_unchanged():
    prices = _prices().assign(stock_splits=0.0)
    market = _market(prices, "2022-12-01T12:00:00+00:00")
    assert market.price == 12.0
    assert market.price_series == ((date(2022, 10, 17), 11.888), (date(2022, 11, 30), 12.0))
    assert _evidence(market, "2022-12-01T12:00:00+00:00").metrics["market_cap"].value == 12.0 * 2.5e9


@pytest.mark.parametrize("evidence", [None, False, pd.NA, "True", 1])
def test_missing_actions_evidence_gives_unavailable_with_a_reason(evidence):
    prices = _prices()
    if evidence is None:
        prices = prices.drop(columns="actions_evidenced")
    else:
        prices["actions_evidenced"] = pd.Series([True, True, evidence, True], dtype=object)
    market = _market(prices)
    assert market.price is None and not market.price_series
    assert "actions_evidence_missing" in market.unavailable_reason
    metrics = _evidence(market).metrics
    for key in ("market_cap", "pe", "ev", "pb", "fcf_yield", "dividend_yield", "pe_percentile"):
        assert not metrics[key].available
        assert "actions_evidence_missing" in metrics[key].reason


@pytest.mark.parametrize("ratio", [None, pd.NA, -1.0, float("inf"), "invalid"])
def test_invalid_split_history_fails_closed(ratio):
    prices = _prices()
    prices["stock_splits"] = prices["stock_splits"].astype(object)
    prices.loc[2, "stock_splits"] = ratio
    value, reason = as_traded_close(prices, date(2022, 10, 17))
    assert value is None and "split_history_invalid" in reason


def test_missing_split_column_fails_closed():
    value, reason = as_traded_close(_prices().drop(columns="stock_splits"), date(2022, 10, 17))
    assert value is None and "split_history_missing" in reason


def test_month_end_history_uses_as_traded_prices_and_original_bar_dates():
    prices = _prices()
    # October's sampled bar is before this split, despite its calendar month end.
    prices.loc[1, "date"] = pd.Timestamp("2022-10-20")
    prices.loc[1, "stock_splits"] = 2.0
    prices.loc[0, "date"] = pd.Timestamp("2022-09-30")
    market = _market(prices, "2022-12-01T12:00:00+00:00")
    assert market.price_series == ((date(2022, 9, 30), 237.76), (date(2022, 10, 20), 120.0))


def test_historical_pe_matches_explicit_as_traded_market_inputs():
    config = load_stock_config()
    config["valuation"]["history_min_points"] = 2
    decision = "2022-12-01T12:00:00+00:00"
    prices = _prices()
    restored = _market(prices, decision, config)
    # Independent no-split reference containing the prices actually traded then.
    reference = prices.assign(stock_splits=0.0)
    reference.loc[:1, "close"] = [118.88, 120.0]
    expected = _evidence(_market(reference, decision, config), decision, config)
    actual = _evidence(restored, decision, config)
    assert actual.history_points == expected.history_points == 2
    assert actual.metrics["pe_percentile"].available
    assert actual.metrics == expected.metrics


def test_dividend_yield_uses_consistent_share_units():
    prices = _prices()
    prices.loc[0, "date"] = pd.Timestamp("2021-10-17")
    prices.loc[1, "date"] = pd.Timestamp("2022-10-17")
    prices.loc[1, "dividends"] = 0.2
    market = _market(prices)
    assert market.price == 120.0
    assert market.dividends_per_share_12m == 2.0
    assert _evidence(market).metrics["dividend_yield"].value == pytest.approx(0.2 / 12.0)


def test_momentum_returns_and_liquidity_inputs_are_unchanged():
    prices = _prices()
    before = prices.copy(deep=True)
    returns = daily_log_returns(prices["adjusted_close"])
    trend = momentum(prices["adjusted_close"], horizon=2)
    liquidity = prices["volume"] * prices["close"]
    _market(prices, "2024-06-12T12:00:00+00:00")
    for day in prices["date"].dt.date:
        as_traded_close(prices, day)
    pd.testing.assert_frame_equal(prices, before)
    pd.testing.assert_series_equal(daily_log_returns(prices["adjusted_close"]), returns)
    pd.testing.assert_series_equal(momentum(prices["adjusted_close"], horizon=2), trend)
    pd.testing.assert_series_equal(prices["volume"] * prices["close"], liquidity)
    assert np.isfinite(returns.dropna()).all()


def test_future_prices_are_not_used_to_restore_a_past_close():
    prices = _prices()
    prices.loc[2:, ["close", "adjusted_close"]] = float("nan")
    assert _market(prices).price == pytest.approx(118.88)


@pytest.mark.parametrize("kind", ["duplicate_date", "invalid_date", "mixed_instruments"])
def test_ambiguous_history_fails_closed(kind):
    prices = _prices()
    if kind == "duplicate_date":
        prices.loc[3, "date"] = prices.loc[2, "date"]
    elif kind == "invalid_date":
        prices.loc[3, "date"] = pd.NaT
    else:
        prices.loc[3, "etf_id"] = "OTHER"
    value, reason = as_traded_close(prices, date(2022, 10, 17))
    assert value is None and "ambiguous" in reason
