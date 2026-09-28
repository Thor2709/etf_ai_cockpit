from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.data import duckdb_store


def _prices(close: float) -> pd.DataFrame:
    return pd.DataFrame([{"date": "2026-01-02", "etf_id": "SYNTHETIC-ETF", "close": close, "adj_close": close}])


def test_failed_price_write_leaves_previous_complete_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "prices_daily.parquet"
    duckdb_store.write_prices(_prices(100.0), path)

    def broken_payload(_frame: object) -> bytes:
        raise OSError("simulated interruption")

    monkeypatch.setattr(duckdb_store, "parquet_payload", broken_payload)
    with pytest.raises(OSError):
        duckdb_store.write_prices(_prices(101.0), path)

    assert pd.read_parquet(path)["close"].tolist() == [100.0]
    assert [item.name for item in tmp_path.iterdir()] == ["prices_daily.parquet"]
