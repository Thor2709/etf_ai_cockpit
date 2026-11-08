from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.application.data_service import _quarantine_invalid_ohlc
from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.universe_store import SPAREBANKEN_ROWS


def _result(frame: pd.DataFrame) -> ProviderResult:
    return ProviderResult("yfinance", "prices", "ok", "test", frame)


def test_invalid_ohlc_rows_are_quarantined_not_committed():
    frame = pd.DataFrame(
        {
            "etf_id": ["A", "A", "B"],
            "open": [10.0, 10.0, 5.0],
            "high": [11.0, 9.0, 6.0],  # second row: high below open -> impossible
            "low": [9.0, 8.0, 4.0],
            "close": [10.5, 8.5, 5.5],
        }
    )
    clean, quarantined = _quarantine_invalid_ohlc(_result(frame))
    assert len(clean.data) == 2
    assert len(quarantined) == 1
    assert quarantined["quarantine_reason"].tolist() == ["invalid_ohlc"]


def test_valid_frame_passes_through_untouched():
    frame = pd.DataFrame({"etf_id": ["A"], "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]})
    clean, quarantined = _quarantine_invalid_ohlc(_result(frame))
    assert quarantined is None
    assert clean.data.equals(frame)


def test_sparebank_fallback_symbols_are_listed_symbols():
    tickers = {row[1]: row[2] for row in SPAREBANKEN_ROWS}
    assert tickers["JAEREN"] == "JAREN.OL"
    assert "SADG" not in tickers  # merged into Sparebanken Norge (SBNOR) in 2024


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf"), -float("inf"), None])
@pytest.mark.parametrize("has_history", [True, False])
def test_full_refresh_rejects_whole_adjusted_series(monkeypatch, tmp_path, invalid, has_history):
    from datetime import date
    from types import SimpleNamespace

    from etf_cockpit.application import data_service
    from etf_cockpit.data import holdings_registry
    from etf_cockpit.data.provenance import metadata_from_frame, sha256_dataframe

    today = date.today()
    recent = pd.bdate_range(end=today, periods=3)
    fetched = pd.DataFrame({
        "etf_id": ["A", "B", "B"], "date": recent,
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0,
        "adjusted_close": [10.0, invalid, 10.0], "volume": 100.0, "currency": "EUR",
        "available_at": pd.to_datetime([today] * 3, utc=True), "source": "yfinance",
    })
    stored = fetched.iloc[[1]].assign(
        date=recent[0], adjusted_close=9.5, available_at=pd.Timestamp(recent[0], tz="UTC"), source="stored"
    ).reset_index(drop=True)
    clean_path = tmp_path / "data" / "clean" / "prices.parquet"
    clean_path.parent.mkdir(parents=True)
    if has_history:
        stored.to_parquet(clean_path, index=False)
    metadata = metadata_from_frame(fetched, source_name="yfinance", source_type="prices", as_of_date=today)
    result = ProviderResult("yfinance", "prices", "ok", "Fetched prices.", fetched, metadata)
    provider = SimpleNamespace(fetch_prices=lambda *_: result, _symbol_map=lambda _: {"A": "A", "B": "B"})
    monkeypatch.setattr(data_service.YFinanceProvider, "from_config", classmethod(lambda *_: provider))
    monkeypatch.setattr(data_service, "ROOT", tmp_path)
    monkeypatch.setattr(data_service, "CLEAN_DIR", clean_path.parent)
    monkeypatch.setattr(holdings_registry, "collect_daily", lambda *_args, **_kwargs: ())
    committed = []
    real_commit = data_service.commit_price_import

    def commit(result):
        committed.append(result)
        return real_commit(
            result, clean_path=clean_path, compatibility_path=tmp_path / "compat" / "prices.parquet",
            raw_dir=tmp_path / "raw", snapshots_dir=tmp_path / "snapshots",
        )

    monkeypatch.setattr(data_service, "commit_price_import", commit)
    message = data_service.DataService(config=None).refresh_yfinance_data(
        include_reference_data=False, include_fundamentals=False,
    )

    assert len(committed) == 1, message
    final = pd.read_parquet(clean_path)
    pd.testing.assert_frame_equal(final.loc[final.etf_id.eq("A")].reset_index(drop=True), fetched.iloc[[0]])
    if has_history:
        pd.testing.assert_frame_equal(final.loc[final.etf_id.eq("B")].reset_index(drop=True), stored)
    else:
        assert set(final.etf_id) == {"A"}
        assert "PARTIAL refresh, not ok: no price data for B." in message
    assert committed[0].metadata.checksum == sha256_dataframe(committed[0].data)
    quarantine = pd.read_parquet(tmp_path / "data" / "quality" / f"price_quarantine_{today.isoformat()}.parquet")
    pd.testing.assert_frame_equal(
        quarantine.drop(columns="quarantine_reason"), fetched.loc[fetched.etf_id.eq("B")].reset_index(drop=True),
    )
    assert quarantine.quarantine_reason.tolist() == ["invalid_adjusted_close"] * 2
    assert "Adjusted close invalid from Yahoo, stored history kept: B." in message
    assert "Validated and committed" in message
    assert "validation blocked" not in message


def test_adjusted_quarantine_rejects_all_ids_when_column_is_missing():
    from etf_cockpit.data.price_quarantine import quarantine_invalid_adjusted_close

    frame = pd.DataFrame({"etf_id": ["A", "B"], "close": [10.0, 20.0]})
    clean, quarantine = quarantine_invalid_adjusted_close(_result(frame))

    assert clean.data.empty
    pd.testing.assert_frame_equal(quarantine.drop(columns="quarantine_reason"), frame)
    assert quarantine.quarantine_reason.tolist() == ["invalid_adjusted_close"] * 2
