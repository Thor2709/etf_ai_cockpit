"""OD-1 = b: an ECB reference rate is available at its publish time (16:00 Frankfurt time), a Yahoo close at its close."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.application import data_service
from etf_cockpit.data.ecb_fx import commit_ecb_fx, parse_ecb_fx_csv
from etf_cockpit.data.fx_data import build_fx_rate_snapshot, load_fx_rates, stamp_fx_availability, validate_fx_rates
from tests.application.test_incremental_price_refresh import (
    _FakeProvider, _capture_fx_commits, _fx_config, _fx_frame, _fx_result,
)

_UTC = timezone.utc
_FETCHED = datetime(2026, 11, 8, 10, 0, tzinfo=_UTC)
_CSV = b"""KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-01-05,1.1700,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-07-06,1.1800,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-07-07,,M
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-11-06,1.1600,A
"""


def _yahoo(rows: list[tuple[str, date, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [{"as_of_date": day, "pair": pair, "base_currency": pair[:3], "quote_currency": pair[4:], "rate": rate,
          "source": "yfinance"} for pair, day, rate in rows]
    )
    return stamp_fx_availability(frame, ingested_at=_FETCHED)


def _commit_store(tmp_path: Path, frame: pd.DataFrame) -> Path:
    path = tmp_path / "fx.parquet"
    frame.to_parquet(path, index=False)
    return path


def _commit_ecb(tmp_path: Path, path: Path, content: bytes = _CSV):
    return commit_ecb_fx(
        parse_ecb_fx_csv(content, fetched_at=_FETCHED), clean_path=path,
        raw_dir=tmp_path / "raw", snapshots_dir=tmp_path / "snapshots",
    )


def test_an_ecb_rate_is_stamped_at_its_frankfurt_publish_time():
    rows = parse_ecb_fx_csv(_CSV, fetched_at=_FETCHED)

    assert list(rows["pair"]) == ["EUR/USD"] * 3  # the blank 2026-07-07 value is skipped, never filled
    assert list(rows["rate"]) == [1.17, 1.18, 1.16]
    assert list(rows["available_at"]) == [
        pd.Timestamp("2026-01-05T15:00Z"), pd.Timestamp("2026-07-06T14:00Z"), pd.Timestamp("2026-11-06T15:00Z"),
    ]  # 16:00 CET in winter, 16:00 CEST in summer
    assert set(rows["source"]) == {"ecb"} and set(rows["availability_basis"]) == {"ecb_publication"}
    assert validate_fx_rates(rows, today=date(2026, 11, 8)).ok


def test_a_reader_sees_the_ecb_rate_from_its_publish_time_and_yahoo_from_its_close(tmp_path):
    path = _commit_store(tmp_path, _yahoo([("CLP/EUR", date(2026, 11, 6), 0.00098)]))
    _commit_ecb(tmp_path, path)
    store = load_fx_rates(path)

    def pairs(when: str) -> set[str]:
        snapshot = build_fx_rate_snapshot(store, decision_time=pd.Timestamp(when).to_pydatetime())
        return {f"{rate.base_currency}/{rate.quote_currency}" for rate in snapshot.rates if snapshot.as_of_date == date(2026, 11, 6)}

    assert pairs("2026-11-06T14:59Z") == set()
    assert pairs("2026-11-06T15:01Z") == {"EUR/USD"}
    assert pairs("2026-11-07T00:00:01Z") == {"EUR/USD", "CLP/EUR"}


def test_an_ecb_rate_replaces_the_yahoo_rate_of_the_same_day_and_currency(tmp_path):
    path = _commit_store(tmp_path, _yahoo([
        ("USD/EUR", date(2026, 11, 5), 0.86), ("USD/EUR", date(2026, 11, 6), 0.87), ("CLP/EUR", date(2026, 11, 6), 0.00098),
    ]))

    _commit_ecb(tmp_path, path)

    store = load_fx_rates(path).sort_values(["as_of_date", "pair"]).reset_index(drop=True)
    kept = list(zip(store["as_of_date"].astype(str), store["pair"], store["source"]))
    assert ("2026-11-06", "USD/EUR", "yfinance") not in kept
    assert ("2026-11-06", "EUR/USD", "ecb") in kept and ("2026-11-05", "USD/EUR", "yfinance") in kept
    assert ("2026-11-06", "CLP/EUR", "yfinance") in kept  # the ECB publishes no CLP rate


def test_a_yahoo_fx_refresh_keeps_the_ecb_rates(monkeypatch, tmp_path):
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    fx_path = clean_dir / "fx.parquet"
    _commit_ecb(tmp_path, fx_path)
    monkeypatch.setattr(data_service, "CLEAN_DIR", clean_dir)
    _capture_fx_commits(monkeypatch, tmp_path, fx_path)
    stamp = datetime(2026, 11, 7, 20, 0, tzinfo=_UTC)
    provider = _FakeProvider((), [], fx_results=[_fx_result(_fx_frame("USD/EUR", [(date(2026, 11, 5), 0.86, stamp), (date(2026, 11, 6), 0.87, stamp)]))])

    messages = data_service._refresh_yfinance_fx(
        provider, _fx_config(("USD",)), start_date=date(2026, 11, 1), full_history=False,
        prices=pd.DataFrame(), end_date=date(2026, 11, 8), publish_guard=None,
    )

    assert messages == []
    store = load_fx_rates(fx_path)
    on_day = store[pd.to_datetime(store["as_of_date"]).dt.date == date(2026, 11, 6)]
    assert list(on_day["source"]) == ["ecb"]
    assert len(store[store["source"] == "ecb"]) == 3
