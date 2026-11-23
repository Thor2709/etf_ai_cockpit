"""A non-incremental refresh that gets a shorter series for an id keeps that id's stored series (D1 rule)."""

from __future__ import annotations

from datetime import date

from etf_cockpit.application.data_service import DataService
from tests.application.test_incremental_price_refresh import (
    _TODAY, _FakeProvider, _bar, _prepare, _price_frame, _result, _stored,
)


def test_non_incremental_refresh_shorter_than_the_stored_history_keeps_the_stored_series(monkeypatch, tmp_path):
    shared = date(2026, 10, 30)
    stored = _price_frame("AAA", [_bar(date(2010, 1, 4)), _bar(shared)])
    fetched = _price_frame("AAA", [_bar(date(2020, 1, 2), 90), _bar(shared, 101), _bar(_TODAY, 102)])
    fetched = fetched._append(_price_frame("BBB", [_bar(shared), _bar(_TODAY)]), ignore_index=True)
    provider = _FakeProvider(("AAA", "BBB"), [_result(fetched)])
    clean_path = _prepare(monkeypatch, tmp_path, provider, stored)

    message = DataService(config=None).refresh_yfinance_data(
        years=5, include_reference_data=False, include_fundamentals=False, incremental=False,
    )

    final = _stored(clean_path)
    aaa = final[final["etf_id"] == "AAA"]
    assert set(aaa["date"]) == {date(2010, 1, 4), shared}  # one adjustment basis, unchanged
    assert aaa["close"].eq(100).all()
    assert set(final.loc[final["etf_id"] == "BBB", "date"]) == {shared, _TODAY}
    assert "Full refetch unavailable for: AAA." in message
