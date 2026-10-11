from datetime import date

import pandas as pd

from etf_cockpit.application.data_service import _carry_forward_failed_instruments
from etf_cockpit.data.providers import ProviderResult


def _prices(ids, day):
    return pd.DataFrame({"etf_id": ids, "date": [pd.Timestamp(day)] * len(ids), "close": [10.0] * len(ids)})


def test_failed_instrument_keeps_stored_history_and_others_refresh(tmp_path):
    stored = tmp_path / "prices.parquet"
    _prices(["A", "B"], "2026-10-01").to_parquet(stored, index=False)
    partial = ProviderResult("yfinance", "prices", "error", "Partial refresh rejected; no incomplete Yahoo Finance price set was committed. B/B.OL: no rows returned", _prices(["A"], "2026-10-08"))

    result = _carry_forward_failed_instruments(partial, clean_path=stored)

    assert result.ok
    assert sorted(result.data["etf_id"]) == ["A", "B"]
    b_rows = result.data[result.data["etf_id"] == "B"]
    assert b_rows["date"].max() == pd.Timestamp("2026-10-01")  # kept as stored, never filled forward
    assert "B" in result.message and "stored history kept" in result.message


def test_stored_rows_of_fetched_instruments_are_replaced_not_duplicated(tmp_path):
    stored = tmp_path / "prices.parquet"
    _prices(["A", "B"], "2026-10-01").to_parquet(stored, index=False)
    partial = ProviderResult("yfinance", "prices", "error", "B/B.OL: no rows returned", _prices(["A"], "2026-10-08"))

    data = _carry_forward_failed_instruments(partial, clean_path=stored).data

    assert data[data["etf_id"] == "A"]["date"].tolist() == [pd.Timestamp("2026-10-08")]


def test_complete_or_empty_results_are_unchanged(tmp_path):
    ok = ProviderResult("yfinance", "prices", "ok", "fine", _prices(["A"], "2026-10-08"))
    empty = ProviderResult("yfinance", "prices", "error", "no rows", None)
    assert _carry_forward_failed_instruments(ok, clean_path=tmp_path / "x.parquet") is ok
    assert _carry_forward_failed_instruments(empty, clean_path=tmp_path / "x.parquet") is empty


def test_stock_fundamentals_refresh_failure_is_reported_not_raised(monkeypatch):
    from etf_cockpit.application import data_service, stock_service

    def boom(_config):
        raise OSError("offline")

    monkeypatch.setattr(stock_service, "refresh_universe_stock_fundamentals", boom)
    assert data_service._refresh_stock_fundamentals(object(), None) == "Stock fundamentals not refreshed: OSError: offline"


def test_stock_fundamentals_refresh_reports_rows_and_gaps(monkeypatch):
    from types import SimpleNamespace

    from etf_cockpit.application import data_service, stock_service

    monkeypatch.setattr(stock_service, "refresh_universe_stock_fundamentals", lambda _c: SimpleNamespace(rows_added=3, failures={"X": "none"}))
    assert data_service._refresh_stock_fundamentals(object(), None) == "Stock fundamentals refreshed: 3 new rows. Without data: X."
