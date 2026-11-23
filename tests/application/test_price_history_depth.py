"""D1/D3: a refresh keeps stored price history older than its fetch span; a max run deepens prices and FX."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from etf_cockpit.application.data_service import MAX_HISTORY_YEARS, DataService
from etf_cockpit.core.values import years_before
from tests.application.test_incremental_price_refresh import (
    _TODAY, _FakeProvider, _bar, _capture_fx_commits, _fx_config, _fx_frame, _fx_result, _prepare, _price_frame,
    _result, _run, _stored, _UTC,
)

_OLD = years_before(_TODAY, 5) - timedelta(days=400)
_SHARED = date(2026, 10, 30)


def test_incremental_merge_keeps_bars_older_than_the_fetch_span(monkeypatch, tmp_path):
    stored = _price_frame("AAA", [_bar(_OLD), _bar(_SHARED)])
    provider = _FakeProvider(("AAA",), [_result(_price_frame("AAA", [_bar(_SHARED), _bar(_TODAY)]))])

    clean_path, _message = _run(provider, monkeypatch, tmp_path, stored)

    assert set(_stored(clean_path)["date"]) == {_OLD, _SHARED, _TODAY}


def test_full_refetch_starts_at_the_oldest_stored_bar(monkeypatch, tmp_path):
    stored = _price_frame("AAA", [_bar(_OLD), _bar(_SHARED)])
    window = _price_frame("AAA", [_bar(_SHARED, 101, adjusted=110), _bar(_TODAY, 102, adjusted=111)])
    full = _price_frame("AAA", [_bar(_OLD, 90), _bar(_SHARED, 101), _bar(_TODAY, 102)])
    provider = _FakeProvider(("AAA",), [_result(window), _result(full)])

    clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    assert provider.calls[1] == (("AAA",), _OLD, _TODAY)
    assert set(_stored(clean_path)["date"]) == {_OLD, _SHARED, _TODAY}
    assert "1 full refetches" in message


def test_full_refetch_shorter_than_the_stored_history_keeps_the_stored_series(monkeypatch, tmp_path):
    old = [_bar(date(2010, 1, 4)), _bar(date(2010, 1, 5))]
    stored = _price_frame("AAA", [*old, _bar(_SHARED)])
    window = _price_frame("AAA", [_bar(_SHARED, 101, adjusted=110), _bar(_TODAY, 102, adjusted=111)])
    full = _price_frame("AAA", [_bar(date(2020, 1, 2), 90), _bar(_SHARED, 101), _bar(_TODAY, 102)])
    provider = _FakeProvider(("AAA",), [_result(window), _result(full)])

    clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    final = _stored(clean_path)
    assert set(final["date"]) == {date(2010, 1, 4), date(2010, 1, 5), _SHARED}  # one adjustment basis, unchanged
    assert final["close"].eq(100).all()
    assert "Full refetch unavailable for: AAA." in message


def test_finite_run_backfills_a_shallow_fx_pair_from_the_price_start(monkeypatch, tmp_path):
    price_start = years_before(_TODAY, 10)
    stamp = pd.Timestamp("2026-11-07T20:00:00", tz=_UTC).to_pydatetime()
    prices = _price_frame("AAA", [_bar(price_start), _bar(_TODAY)]).assign(currency="USD")
    provider = _FakeProvider(
        ("AAA",), [_result(prices)],
        fx_results=[_fx_result(_fx_frame("USD/EUR", [(price_start, 0.9, stamp), (date(2026, 11, 7), 0.93, stamp)]))],
    )
    clean_path = _prepare(monkeypatch, tmp_path, provider)
    fx_path = clean_path.parent / "fx.parquet"
    _fx_frame("USD/EUR", [(date(2026, 11, 7), 0.92, stamp)]).to_parquet(fx_path, index=False)
    _capture_fx_commits(monkeypatch, tmp_path, fx_path)

    DataService(config=_fx_config(("USD",))).refresh_yfinance_data(
        years=10, include_reference_data=False, include_fundamentals=False, include_fx=True,
    )

    assert provider.fx_calls == [(("USD/EUR",), price_start, _TODAY)]


def test_max_history_run_fetches_prices_and_every_fx_pair_from_the_max_start(monkeypatch, tmp_path):
    start = years_before(_TODAY, MAX_HISTORY_YEARS)
    stamp = pd.Timestamp("2026-11-07T20:00:00", tz=_UTC).to_pydatetime()
    provider = _FakeProvider(
        ("AAA",), [_result(_price_frame("AAA", [_bar(_OLD), _bar(_TODAY)]))],
        fx_results=[_fx_result(_fx_frame("USD/EUR", [(_OLD, 0.9, stamp), (date(2026, 11, 7), 0.93, stamp)]))],
    )
    clean_path = _prepare(monkeypatch, tmp_path, provider)
    fx_path = clean_path.parent / "fx.parquet"
    _fx_frame("USD/EUR", [(date(2026, 11, 7), 0.92, stamp)]).to_parquet(fx_path, index=False)
    _capture_fx_commits(monkeypatch, tmp_path, fx_path)

    DataService(config=_fx_config(("USD",))).refresh_yfinance_data(
        years=None, include_reference_data=False, include_fundamentals=False, include_fx=True,
    )

    assert provider.calls == [((), start, _TODAY)]
    assert provider.fx_calls == [(("USD/EUR",), start, _TODAY)]
    fx = pd.read_parquet(fx_path)
    assert pd.to_datetime(fx["as_of_date"]).dt.date.min() == _OLD
