from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application import data_service
from etf_cockpit.application.data_service import DataService
from etf_cockpit.core.values import years_before
from etf_cockpit.data.provenance import metadata_from_frame
from etf_cockpit.data.providers import ProviderResult


_TODAY = date(2026, 11, 8)
_UTC = timezone.utc


class _FrozenDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 8)


class _FakeProvider:
    def __init__(
        self,
        ids: tuple[str, ...],
        results: list[ProviderResult],
        *,
        fx_results: list[ProviderResult] | None = None,
    ):
        self.ids = ids
        self.results = list(results)
        self.fx_results = list(fx_results or [])
        self.calls: list[tuple[tuple[str, ...], date, date]] = []
        self.fx_calls: list[tuple[tuple[str, ...], date, date]] = []

    def _symbol_map(self, symbols):
        selected = tuple(symbols) if symbols else self.ids
        return {instrument_id: instrument_id for instrument_id in selected}

    def fetch_prices(self, symbols, start_date, end_date):
        self.calls.append((tuple(symbols), start_date, end_date))
        assert self.results, "unexpected provider call"
        return self.results.pop(0)

    def fetch_fx(self, pairs, start_date, end_date):
        self.fx_calls.append((tuple(pairs), start_date, end_date))
        assert self.fx_results, "unexpected FX provider call"
        return self.fx_results.pop(0)


def _price_frame(instrument_id: str, rows: list[tuple[date, float, float, datetime]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": day,
                "etf_id": instrument_id,
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "adjusted_close": adjusted,
                "volume": 100.0,
                "currency": "EUR",
                "provider_symbol": instrument_id,
                "source": "yfinance",
                "is_adjusted": True,
                "dividends": 0.0,
                "stock_splits": 0.0,
                "capital_gains": 0.0,
                "fetched_at": available_at + timedelta(minutes=1),
                "ingested_at": available_at + timedelta(minutes=2),
                "available_at": available_at,
                "provider": "yfinance",
                "actions_evidenced": True,
            }
            for day, close, adjusted, available_at in rows
        ]
    )


def _bar(day: date, close: float = 100.0, adjusted: float | None = None, *, hour: int = 21):
    available_at = datetime(day.year, day.month, day.day, hour, tzinfo=_UTC)
    return day, close, close if adjusted is None else adjusted, available_at


def _result(frame: pd.DataFrame | None, *, status: str = "ok", message: str = "Downloaded test prices.") -> ProviderResult:
    metadata = (
        metadata_from_frame(
            frame,
            source_name="yfinance",
            source_type="prices",
            as_of_date=_TODAY,
            provider_or_manual_source="Yahoo Finance via yfinance",
        )
        if frame is not None
        else None
    )
    return ProviderResult("yfinance", "prices", status, message, frame, metadata)


def _prepare(monkeypatch, tmp_path: Path, provider: _FakeProvider, stored: pd.DataFrame | None = None):
    clean_dir = tmp_path / "data" / "clean"
    clean_path = clean_dir / "prices.parquet"
    clean_dir.mkdir(parents=True)
    if stored is not None:
        stored.to_parquet(clean_path, index=False)

    monkeypatch.setattr(data_service, "date", _FrozenDate)
    monkeypatch.setattr(data_service, "CLEAN_DIR", clean_dir)
    monkeypatch.setattr(data_service, "ROOT", tmp_path)
    monkeypatch.setattr(data_service.YFinanceProvider, "from_config", classmethod(lambda cls, _config: provider))
    monkeypatch.setattr(data_service, "validate_prices", lambda *_args, **_kwargs: SimpleNamespace(issues=[]))
    monkeypatch.setattr(data_service, "_refresh_stock_fundamentals", lambda *_args: "Stock fundamentals refreshed.")
    from etf_cockpit.data import holdings_registry

    monkeypatch.setattr(holdings_registry, "collect_daily", lambda *_args, **_kwargs: ())
    commit = data_service.commit_price_import

    def commit_to_tmp(result):
        return commit(
            result,
            clean_path=clean_path,
            compatibility_path=tmp_path / "data" / "compat" / "prices.parquet",
            raw_dir=tmp_path / "data" / "raw" / "prices",
            snapshots_dir=tmp_path / "data" / "snapshots" / "prices",
        )

    monkeypatch.setattr(data_service, "commit_price_import", commit_to_tmp)
    return clean_path


def _run(provider: _FakeProvider, monkeypatch, tmp_path: Path, stored: pd.DataFrame | None = None, **kwargs):
    clean_path = _prepare(monkeypatch, tmp_path, provider, stored)
    message = DataService(config=None).refresh_yfinance_data(
        years=5,
        include_reference_data=False,
        incremental=True,
        **kwargs,
    )
    return clean_path, message


def _stored(clean_path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(clean_path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def _fx_frame(pair: str, rows: list[tuple[date, float, datetime]]) -> pd.DataFrame:
    base, quote = pair.split("/")
    return pd.DataFrame(
        [
            {
                "as_of_date": day,
                "base_currency": base,
                "quote_currency": quote,
                "pair": pair,
                "rate": rate,
                "source": "yfinance",
                "provider_symbol": pair.replace("/", ""),
                "ingested_at": ingested_at,
                "available_at": ingested_at,
                "availability_basis": "live_ingestion",
                "staleness_status": "unknown",
                "fetched_at": ingested_at + timedelta(minutes=1),
                "provider": "yfinance",
            }
            for day, rate, ingested_at in rows
        ]
    )


def _fx_result(frame: pd.DataFrame | None, *, status: str = "ok", message: str = "Downloaded test FX.") -> ProviderResult:
    return ProviderResult("yfinance", "fx", status, message, frame)


def _fx_config(currencies: tuple[str, ...]):
    return SimpleNamespace(
        targets=SimpleNamespace(base_currency="EUR"),
        universe=SimpleNamespace(etfs=[SimpleNamespace(currency=currency) for currency in currencies]),
    )


def _capture_fx_commits(monkeypatch, tmp_path: Path, clean_path: Path):
    commits: list[ProviderResult] = []
    commit = data_service.commit_fx_import

    def commit_to_tmp(result):
        commits.append(result)
        return commit(
            result,
            clean_path=clean_path,
            raw_dir=tmp_path / "data" / "raw" / "fx",
            snapshots_dir=tmp_path / "data" / "snapshots" / "fx",
        )

    monkeypatch.setattr(data_service, "commit_fx_import", commit_to_tmp)
    return commits


def _read_fx(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    return frame


def test_incremental_merge_keeps_history_and_appends_new_day(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    window_start = date(2026, 10, 19)
    before_window = window_start - timedelta(days=1)
    shared = date(2026, 10, 30)
    stored_only_window = date(2026, 11, 2)
    old = _price_frame("AAA", [_bar(floor), _bar(before_window), _bar(shared), _bar(stored_only_window)])
    window = _price_frame("AAA", [_bar(shared), _bar(_TODAY)])
    provider = _FakeProvider(("AAA",), [_result(window)])

    clean_path, message = _run(provider, monkeypatch, tmp_path, old)

    final = _stored(clean_path)
    assert set(final["date"]) == {floor, before_window, shared, stored_only_window, _TODAY}
    assert final["date"].min() == floor
    assert final["date"].max() == _TODAY
    assert len(final) == len(old) + 1
    assert provider.calls == [((), date(2026, 10, 19), _TODAY)]
    assert "1 incremental instruments, 0 full refetches" in message


def test_adjusted_close_mismatch_full_refetches_only_that_instrument(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    old_only = floor + timedelta(days=10)
    shared = date(2026, 10, 30)
    stored = pd.concat(
        [
            _price_frame("AAA", [_bar(floor), _bar(old_only), _bar(shared)]),
            _price_frame("BBB", [_bar(floor), _bar(old_only), _bar(shared)]),
        ],
        ignore_index=True,
    )
    window = pd.concat(
        [
            _price_frame("AAA", [_bar(shared, 101, adjusted=110), _bar(_TODAY, 102, adjusted=111)]),
            _price_frame("BBB", [_bar(shared), _bar(_TODAY)]),
        ],
        ignore_index=True,
    )
    full = _price_frame("AAA", [_bar(floor, 80), _bar(shared, 105), _bar(_TODAY, 106)])
    provider = _FakeProvider(("AAA", "BBB"), [_result(window), _result(full)])

    clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    final = _stored(clean_path)
    aaa = final[final["etf_id"].eq("AAA")]
    bbb = final[final["etf_id"].eq("BBB")]
    assert set(aaa["date"]) == {floor, shared, _TODAY}
    assert set(bbb["date"]) == {floor, old_only, shared, _TODAY}
    assert aaa.loc[aaa["date"].eq(shared), "close"].iloc[0] == 105
    assert bbb.loc[bbb["date"].eq(shared), "close"].iloc[0] == 100
    assert provider.calls[1][0] == ("AAA",)
    assert "1 incremental instruments, 1 full refetches" in message


def test_currency_label_change_with_matching_adjusted_close_full_refetches_only_that_instrument(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    shared = date(2026, 10, 30)
    stored = pd.concat(
        [
            _price_frame("AAA", [_bar(floor), _bar(shared)]),
            _price_frame("BBB", [_bar(floor), _bar(shared)]),
        ],
        ignore_index=True,
    )
    window = pd.concat(
        [
            _price_frame("AAA", [_bar(shared), _bar(_TODAY)]).assign(currency="USD"),
            _price_frame("BBB", [_bar(shared), _bar(_TODAY)]),
        ],
        ignore_index=True,
    )
    full = _price_frame("AAA", [_bar(floor), _bar(shared), _bar(_TODAY)]).assign(currency="USD")
    provider = _FakeProvider(("AAA", "BBB"), [_result(window), _result(full)])

    clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    final = _stored(clean_path)
    assert set(final.loc[final["etf_id"].eq("AAA"), "currency"]) == {"USD"}
    assert set(final.loc[final["etf_id"].eq("BBB"), "currency"]) == {"EUR"}
    assert provider.calls[1][0] == ("AAA",)
    assert "1 currency mismatch" in message


def test_multiple_stored_currency_labels_force_full_refetch(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    shared = date(2026, 10, 30)
    stored = pd.concat(
        [
            _price_frame("AAA", [_bar(floor)]).assign(currency="GBP"),
            _price_frame("AAA", [_bar(shared)]),
        ],
        ignore_index=True,
    )
    window = _price_frame("AAA", [_bar(shared), _bar(_TODAY)])
    full = _price_frame("AAA", [_bar(floor), _bar(shared), _bar(_TODAY)])
    provider = _FakeProvider(("AAA",), [_result(window), _result(full)])

    _clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    assert provider.calls[1][0] == ("AAA",)
    assert "1 currency mismatch" in message


def test_missing_history_or_no_shared_date_uses_full_refetch(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    old_day = date(2022, 2, 2)
    stored = _price_frame("BBB", [_bar(old_day)])
    window = pd.concat(
        [_price_frame("AAA", [_bar(_TODAY)]), _price_frame("BBB", [_bar(_TODAY, 101)])],
        ignore_index=True,
    )
    full = pd.concat(
        [
            _price_frame("AAA", [_bar(floor), _bar(_TODAY)]),
            _price_frame("BBB", [_bar(floor), _bar(_TODAY, 101)]),
        ],
        ignore_index=True,
    )
    provider = _FakeProvider(("AAA", "BBB"), [_result(window), _result(full)])

    clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    final = _stored(clean_path)
    assert set(final["etf_id"]) == {"AAA", "BBB"}
    assert set(final["date"]) == {floor, _TODAY}
    assert provider.calls[1][0] == ("AAA", "BBB")
    assert "0 incremental instruments, 2 full refetches" in message


def test_revised_in_window_bar_replaces_old_bar_and_keeps_old_availability(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    before_window = date(2026, 10, 15)
    revised_day = date(2026, 10, 30)
    stored = _price_frame("AAA", [_bar(floor), _bar(before_window), _bar(revised_day, 100, hour=21)])
    revised = _price_frame("AAA", [_bar(revised_day, 102, adjusted=100, hour=23), _bar(_TODAY)])
    provider = _FakeProvider(("AAA",), [_result(revised)])

    clean_path, _message = _run(provider, monkeypatch, tmp_path, stored)

    final = _stored(clean_path)
    revised_row = final[final["date"].eq(revised_day)].iloc[0]
    prior_row = final[final["date"].eq(before_window)].iloc[0]
    assert revised_row["close"] == 102
    assert pd.Timestamp(revised_row["available_at"]) == pd.Timestamp("2026-10-30T23:00:00Z")
    assert pd.Timestamp(prior_row["available_at"]) == pd.Timestamp("2026-10-15T21:00:00Z")


def test_failed_full_refetch_keeps_stored_rows_and_discards_window_rows(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    before_window = date(2026, 10, 18)
    shared = date(2026, 10, 30)
    stored = _price_frame("AAA", [_bar(floor), _bar(before_window), _bar(shared)])
    window = _price_frame("AAA", [_bar(shared, 101, adjusted=110), _bar(_TODAY, 102, adjusted=111)])
    provider = _FakeProvider(
        ("AAA",),
        [
            _result(window),
            _result(
                _price_frame("AAA", [_bar(floor, 80), _bar(shared, 80), _bar(_TODAY, 80)]),
                status="error",
                message="AAA/AAA: full refetch failed",
            ),
        ],
    )

    clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    final = _stored(clean_path)
    expected = _stored_from_frame(stored)
    pd.testing.assert_frame_equal(
        final.sort_values("date").reset_index(drop=True),
        expected.sort_values("date").reset_index(drop=True),
        check_dtype=False,
    )
    assert _TODAY not in set(final["date"])
    assert "Full refetch unavailable for: AAA" in message


def test_failed_full_refetch_without_stored_history_reports_missing_instrument(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    stored = _price_frame("BBB", [_bar(floor), _bar(date(2026, 10, 30))])
    window = _price_frame("AAA", [_bar(_TODAY)])
    failed_full = _price_frame("AAA", [_bar(floor, 80), _bar(_TODAY, 80)])
    provider = _FakeProvider(
        ("AAA", "BBB"),
        [
            _result(window, status="error", message="BBB/BBB: no rows returned"),
            _result(failed_full, status="error", message="AAA/AAA: full refetch failed"),
        ],
    )

    clean_path, message = _run(provider, monkeypatch, tmp_path, stored)

    final = _stored(clean_path)
    assert set(final["etf_id"]) == {"BBB"}
    assert "PARTIAL refresh, not ok: no price data for AAA." in message


def _stored_from_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.date
    return result


def test_empty_store_incremental_mode_uses_full_refresh(monkeypatch, tmp_path):
    floor = years_before(_TODAY, 5)
    full = _price_frame("AAA", [_bar(floor), _bar(_TODAY)])
    provider = _FakeProvider(("AAA",), [_result(full)])

    clean_path, message = _run(provider, monkeypatch, tmp_path)

    assert set(_stored(clean_path)["date"]) == {floor, _TODAY}
    assert provider.calls == [((), floor, _TODAY)]
    assert "Incremental refresh:" not in message


def test_skip_fundamentals_never_calls_stock_refresh(monkeypatch, tmp_path):
    calls: list[bool] = []
    window = _price_frame("AAA", [_bar(_TODAY)])
    provider = _FakeProvider(("AAA",), [_result(window)])
    _prepare(monkeypatch, tmp_path, provider)
    monkeypatch.setattr(data_service, "_refresh_stock_fundamentals", lambda *_args: calls.append(True) or "unexpected")

    message = DataService(config=None).refresh_yfinance_data(
        years=5,
        include_reference_data=False,
        incremental=True,
        include_fundamentals=False,
    )

    assert calls == []
    assert "Stock fundamentals skipped (weekly job)." in message


def test_include_fx_refreshes_configured_pairs_merges_rows_and_commits_once(monkeypatch, tmp_path):
    price = _price_frame("AAA", [_bar(_TODAY)])
    stored_latest = datetime(2026, 11, 7, 20, tzinfo=_UTC)
    stored_old = datetime(2026, 11, 1, 20, tzinfo=_UTC)
    stored_cad = datetime(2026, 11, 3, 20, tzinfo=_UTC)
    jpy_fetch = _fx_frame("JPY/EUR", [(_TODAY, 0.0062, datetime(2026, 11, 8, 20, tzinfo=_UTC))])
    usd_fetch = _fx_frame("USD/EUR", [(date(2026, 11, 7), 0.93, datetime(2026, 11, 8, 20, tzinfo=_UTC))])
    provider = _FakeProvider(
        ("AAA",),
        [_result(price)],
        fx_results=[_fx_result(jpy_fetch), _fx_result(usd_fetch)],
    )
    clean_path = _prepare(monkeypatch, tmp_path, provider)
    fx_path = clean_path.parent / "fx.parquet"
    stored_fx = pd.concat(
        [
            _fx_frame("USD/EUR", [(date(2026, 11, 1), 0.91, stored_old)]),
            _fx_frame("USD/EUR", [(date(2026, 11, 7), 0.92, stored_latest)]),
            _fx_frame("CAD/EUR", [(date(2026, 11, 3), 0.67, stored_cad)]),
        ],
        ignore_index=True,
    )
    stored_fx.to_parquet(fx_path, index=False)
    commits = _capture_fx_commits(monkeypatch, tmp_path, fx_path)

    message = DataService(config=_fx_config(("USD", "JPY", "EUR"))).refresh_yfinance_data(
        years=5,
        include_reference_data=False,
        include_fundamentals=False,
        include_fx=True,
    )

    assert set(provider.fx_calls) == {
        (("JPY/EUR",), years_before(_TODAY, 5), _TODAY),
        (("USD/EUR",), date(2026, 10, 24), _TODAY),
    }
    assert len(commits) == 1
    merged_input = commits[0].data
    old_usd = merged_input.loc[
        merged_input["pair"].eq("USD/EUR") & (pd.to_datetime(merged_input["as_of_date"]).dt.date == date(2026, 11, 1))
    ].iloc[0]
    assert pd.Timestamp(old_usd["ingested_at"]) == pd.Timestamp(stored_old)
    assert pd.Timestamp(old_usd["fetched_at"]) == pd.Timestamp(stored_old + timedelta(minutes=1))

    final = _read_fx(fx_path)
    assert set(final["pair"]) == {"USD/EUR", "JPY/EUR", "CAD/EUR"}
    usd_nov_1 = final.loc[final["pair"].eq("USD/EUR") & final["as_of_date"].eq(date(2026, 11, 1))].iloc[0]
    usd_nov_7 = final.loc[final["pair"].eq("USD/EUR") & final["as_of_date"].eq(date(2026, 11, 7))].iloc[0]
    assert usd_nov_1["rate"] == 0.91
    assert pd.Timestamp(usd_nov_1["ingested_at"]) == pd.Timestamp(stored_old)
    assert usd_nov_7["rate"] == 0.93
    assert len(final.loc[final["pair"].eq("USD/EUR") & final["as_of_date"].eq(date(2026, 11, 7))]) == 1
    assert "Validated and committed 1 price rows" in message


def test_failed_fx_pair_keeps_stored_rows_and_price_commit(monkeypatch, tmp_path):
    price = _price_frame("AAA", [_bar(_TODAY)])
    old_ingested = datetime(2026, 11, 7, 20, tzinfo=_UTC)
    provider = _FakeProvider(
        ("AAA",),
        [_result(price)],
        fx_results=[_fx_result(None, status="error", message="JPY/EUR: no rows returned")],
    )
    clean_path = _prepare(monkeypatch, tmp_path, provider)
    fx_path = clean_path.parent / "fx.parquet"
    stored = _fx_frame("JPY/EUR", [(date(2026, 11, 7), 0.006, old_ingested)])
    stored.to_parquet(fx_path, index=False)
    commits = _capture_fx_commits(monkeypatch, tmp_path, fx_path)

    service = DataService(config=_fx_config(("JPY", "EUR")))
    message = service.refresh_yfinance_data(
        years=5,
        include_reference_data=False,
        include_fundamentals=False,
        include_fx=True,
    )

    assert service.last_operation_succeeded
    assert clean_path.is_file()
    assert _stored(clean_path)["date"].max() == _TODAY
    assert _read_fx(fx_path)["rate"].tolist() == [0.006]
    assert len(commits) == 0
    assert "FX not refreshed: JPY/EUR" in message


def test_include_fx_false_never_calls_fetch_fx(monkeypatch, tmp_path):
    provider = _FakeProvider(("AAA",), [_result(_price_frame("AAA", [_bar(_TODAY)]))])

    _run(provider, monkeypatch, tmp_path)

    assert provider.fx_calls == []
