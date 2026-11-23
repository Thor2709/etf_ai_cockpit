"""D4: a column-pruned price read gives the full read's frame for those columns."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.data import duckdb_store

_CONFIG = SimpleNamespace(data=SimpleNamespace(allow_synthetic_sample_data=False))


def _store(monkeypatch, tmp_path):
    path = tmp_path / "prices_daily.parquet"
    rows = [
        {"date": date(2026, 11, day), "etf_id": etf_id, "close": 10.0 + day, "adjusted_close": 9.0 + day,
         "currency": currency, "source": source, "provider_symbol": None if etf_id == "BBB" else f"{etf_id}.DE",
         "volume": 100}
        for day in (5, 6) for etf_id, currency, source in (
            ("AAA", "EUR", "yfinance"), ("BBB", "USD", "yfinance"), ("SYN", "EUR", "synthetic_sample"))
    ]
    duckdb_store.write_prices(pd.DataFrame(rows), path)
    monkeypatch.setattr(duckdb_store, "PRICE_PARQUET", path)
    return duckdb_store.load_prices(config=_CONFIG)


def test_a_column_pruned_read_equals_the_full_read_and_keeps_the_synthetic_gate(monkeypatch, tmp_path):
    full = _store(monkeypatch, tmp_path)
    columns = ["etf_id", "date", "adjusted_close"]

    pruned = duckdb_store.load_prices(config=_CONFIG, columns=columns)

    assert "SYN" not in set(full["etf_id"])
    assert pruned.equals(full[columns])
