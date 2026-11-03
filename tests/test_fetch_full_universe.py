from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import universe_fetch as fetch
from etf_cockpit.core import atomic_io
from etf_cockpit.core.config import DataProvidersConfig, ProviderSection
from etf_cockpit.data.universe_store import UniverseRecord, universe_payload_revision


class FakeProvider:
    """Picklable offline provider, including real process evidence and action rows."""

    def __init__(self, root, limiter):
        self.root = root
        self.limiter = limiter

    def fetch(self, item, start, end):
        self.limiter.acquire("fake.provider.test")
        calls = self.root / "calls"
        calls.mkdir(exist_ok=True)
        (calls / item.key).write_text(item.identifier)
        behavior_path = self.root / "behavior.json"
        behavior = json.loads(behavior_path.read_text()) if behavior_path.exists() else {}
        mode = behavior.get(item.identifier)
        if mode == "missing":
            raise ValueError("not listed by fake provider")
        dates = pd.bdate_range(start, end)
        known = pd.Timestamp("2024-02-01T12:00:00Z")
        if item.kind == "fx":
            frame = pd.DataFrame({"as_of_date": dates, "pair": item.identifier, "rate": 0.92,
                                  "source": "fake", "provider_symbol": item.symbol,
                                  "fetched_at": known, "ingested_at": known,
                                  "available_at": known, "availability_basis": "live_ingestion"})
        else:
            frame = pd.DataFrame({"date": dates, "etf_id": item.identifier, "open": 10.0, "high": 12.0,
                                  "low": 9.0, "close": 11.0, "adjusted_close": 10.5, "volume": 100,
                                  "currency": item.currency, "is_adjusted": mode != "unadjusted",
                                  "source": "fake", "provider_symbol": item.symbol, "dividends": 0.0,
                                  "stock_splits": 0.0, "fetched_at": known, "ingested_at": known, "available_at": known})
            if len(frame) > 1:
                frame.loc[1, "dividends"] = 0.5
                frame.loc[1, "stock_splits"] = 2.0
        if mode == "gap":
            frame = frame.drop(frame.index[1])
        return frame


class NoFetch:
    def __init__(self, root, limiter):
        raise AssertionError("covered instruments must not construct a provider")


def _root(path):
    config = path / "configs"
    config.mkdir(parents=True)
    records = [UniverseRecord("A", "A", isin_status="needs_verification", ticker="A", currency="USD"),
               UniverseRecord("B", "B", isin_status="needs_verification", ticker="B"),
               UniverseRecord("DISABLED", "Disabled", isin_status="needs_verification", ticker="DISABLED", enabled=False)]
    payload = {"schema_version": 2, "records": [asdict(row) for row in records], "allow_cross_tier_duplicates": False}
    payload["revision"] = universe_payload_revision(payload)
    (config / "universe_store.json").write_text(json.dumps(payload))
    # Test fixture only; production never edits configuration.
    (config / "paper_bots_v1.yaml").write_text("benchmark:\n  instrument_id: BENCH\n  yahoo_symbol: BENCH.DE\n  currency: EUR\n")
    return path


def _options(root, **kwargs):
    return fetch.FetchOptions(root, date(2024, 1, 2), date(2024, 1, 5), root / "staging",
                              warmup_days=0, fill_days=0, workers=1, rate_per_host=1000.0, **kwargs)


def _prices(root):
    return pd.read_parquet(root / "data/validated/prices/prices_daily.parquet")


def _store_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in (root / "data").rglob("*")
            if path.is_file() and path.suffix in {".parquet", ".json"}}


def test_parallel_two_processes_equals_serial_canonical_rows(tmp_path):
    serial, parallel = _root(tmp_path / "serial"), _root(tmp_path / "parallel")
    one = fetch.fetch_full_universe(_options(serial, promote=True), provider_factory=FakeProvider)
    two = fetch.fetch_full_universe(replace(_options(parallel, promote=True), workers=2), provider_factory=FakeProvider)
    assert one["missing"] == two["missing"] == 0
    assert one["promotion"] == two["promotion"] == "committed"
    assert len({row["pid"] for row in two["rows"]}) == 2
    pd.testing.assert_frame_equal(_prices(serial), _prices(parallel))
    pd.testing.assert_frame_equal(pd.read_parquet(serial / "data/clean/fx.parquet"), pd.read_parquet(parallel / "data/clean/fx.parquet"))
    assert set(_prices(parallel)["etf_id"]) == {"A", "B", "BENCH"}
    assert _prices(parallel)["dividends"].sum() > 0
    assert _prices(parallel)["stock_splits"].sum() > 0
    assert {"source", "fetched_at", "ingested_at", "available_at"} <= set(_prices(parallel))


def test_missing_and_unadjusted_instruments_reported_without_filling(tmp_path, monkeypatch):
    root = _root(tmp_path / "root")
    (root / "behavior.json").write_text(json.dumps({"A": "missing", "B": "unadjusted", "BENCH": "gap"}))
    report = fetch.fetch_full_universe(_options(root, promote=True), provider_factory=FakeProvider)
    missing = {row["identifier"]: row["reason"] for row in report["rows"] if row["status"] == "missing"}
    assert missing == {"A": "not listed by fake provider", "B": "unadjusted-only or unverifiable adjustment basis"}
    prices = _prices(root)
    assert set(prices["etf_id"]) == {"BENCH"}
    assert len(prices) == 3
    assert pd.Timestamp("2024-01-03") not in prices["date"].tolist()
    assert (prices[["open", "close", "adjusted_close"]] > 0).all().all()
    assert json.loads((root / "staging/report.json").read_text())["missing"] == 2

    # Exercise the real adapter chain with offline responses, including distinct
    # corporate-action column names and the configured fallback declaration order.
    from etf_cockpit.data.stooq_provider import StooqProvider
    from etf_cockpit.data.tiingo_provider import TiingoProvider
    from etf_cockpit.data.yfinance_provider import YFinanceProvider

    settings = DataProvidersConfig(providers={
        "prices": ProviderSection(active_provider="yfinance"),
        "stooq": ProviderSection(active_provider="stooq"),
        "tiingo": ProviderSection(active_provider="tiingo"),
        "twelvedata": ProviderSection(active_provider="none"),
    })
    monkeypatch.setattr(fetch, "load_config", lambda _: SimpleNamespace(data_providers=settings))
    monkeypatch.setattr(fetch, "_yahoo_session", lambda _: SimpleNamespace(close=lambda: None))
    item = fetch.FetchItem("prices", "C", "C.DE", "EUR")
    limiter = fetch.SharedHostLimiter(root / "offline-limiter", 1000)
    good = FakeProvider(root, limiter).fetch(item, options_start := date(2024, 1, 2), options_end := date(2024, 1, 5))
    raw = good.assign(is_adjusted=False)
    alternate = good.rename(columns={"dividends": "dividend", "stock_splits": "split_factor"})
    alternate["split_factor"] = alternate["split_factor"].replace(0, 1)
    seen = []

    def reply(name, frame):
        seen.append(name)
        return frame.copy()

    monkeypatch.setattr(YFinanceProvider, "_download_one", lambda *_args, **_kwargs: reply("yfinance", raw))
    monkeypatch.setattr(StooqProvider, "fetch_daily_prices", lambda *_args: reply("stooq", raw))
    monkeypatch.setattr(TiingoProvider, "fetch_daily_prices", lambda *_args: reply("tiingo", alternate))
    chain = fetch.ProviderChain(root, limiter)
    result = chain.fetch(item, options_start, options_end)
    chain.close()
    assert seen == ["yfinance", "stooq", "tiingo"]
    assert result["is_adjusted"].all() and result["split_factor"].min() == 1

    (root / "configs/paper_bots_v1.yaml").write_text("benchmark:\n  instrument_id: UNKNOWN\n  yahoo_symbol: UNKNOWN\n")
    unknown = fetch.fetch_full_universe(_options(root), provider_factory=FakeProvider)
    assert next(row for row in unknown["rows"] if row["identifier"] == "UNKNOWN")["reason"] == "canonical quote currency is missing"


def test_429_retry_after_honoured_with_shared_host_cooldown_and_fake_clock(tmp_path):
    class Clock:
        value = 0.0
        sleeps = []

        def now(self):
            return self.value

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.value += seconds

    class Response:
        def __init__(self, status, retry="0"):
            self.status_code = status
            self.headers = {"Retry-After": retry}

        def close(self):
            pass

    clock = Clock()
    limiter = fetch.SharedHostLimiter(tmp_path, 1.0, clock=clock.now, sleep=clock.sleep, wall_clock=clock.now)
    responses = iter([Response(429, "7"), Response(429, "Thu, 01 Jan 1970 00:00:12 GMT"), Response(200)])
    times = []

    def send():
        times.append(clock.now())
        return next(responses)

    assert limiter.request(send, "https://example.test/prices").status_code == 200
    assert times == [0, 7, 12]
    other = fetch.SharedHostLimiter(tmp_path, 1.0, clock=clock.now, sleep=clock.sleep)
    other.acquire("example.test")
    assert clock.now() == 13
    other.acquire("different.test")
    assert clock.now() == 13


def test_promote_is_only_writer_and_failure_mid_promotion_is_atomic(tmp_path, monkeypatch):
    from scripts import fetch_full_universe as cli

    root = _root(tmp_path / "root")
    options = _options(root)
    monkeypatch.setattr(cli, "fetch_full_universe", lambda options: fetch.fetch_full_universe(options, provider_factory=FakeProvider))
    assert cli.main(["--root", str(root), "--start", "2024-01-02", "--end", "2024-01-05", "--warmup-days", "0", "--fill-days", "0",
                     "--workers", "1", "--rate-per-host", "1000", "--staging", str(options.staging)]) == 0
    report = json.loads((options.staging / "report.json").read_text())
    assert report["promotion"] == "not_requested"
    assert not (root / "data").exists()
    fetch.fetch_full_universe(replace(options, promote=True, resume=True), provider_factory=NoFetch)
    before = _store_bytes(root)
    real_replace = atomic_io.os.replace
    replaced = []

    def fail_mid_publish(source, destination):
        destination = Path(destination)
        if destination in {root / "data/clean/prices.parquet", root / "data/clean/fx.parquet"}:
            replaced.append(destination)
            if len(replaced) == 2:
                raise OSError("injected mid-promotion failure")
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(atomic_io.os, "replace", fail_mid_publish)
        with pytest.raises(OSError, match="injected mid-promotion"):
            fetch.fetch_full_universe(replace(options, promote=True, resume=True), provider_factory=NoFetch)
    assert len(replaced) >= 2
    assert _store_bytes(root) == before
    assert json.loads((root / "staging/report.json").read_text())["promotion"] == "failed"


def test_resume_skips_covered_staging_and_canonical_but_refetches_gaps(tmp_path):
    root = _root(tmp_path / "root")
    options = _options(root)
    fetch.fetch_full_universe(options, provider_factory=FakeProvider)
    staged = fetch.fetch_full_universe(replace(options, resume=True), provider_factory=NoFetch)
    assert {row["status"] for row in staged["rows"]} == {"resumed_staging"}
    fetch.fetch_full_universe(replace(options, promote=True, resume=True), provider_factory=NoFetch)
    canonical = fetch.fetch_full_universe(replace(options, staging=root / "fresh-staging", resume=True), provider_factory=NoFetch)
    assert {row["status"] for row in canonical["rows"]} == {"resumed_canonical"}
    prices = _prices(root)
    prices = prices.loc[~(prices["etf_id"].eq("A") & prices["date"].eq(pd.Timestamp("2024-01-03")))]
    prices.to_parquet(root / "data/validated/prices/prices_daily.parquet", index=False)
    gap = fetch.fetch_full_universe(replace(options, staging=root / "gap-staging", resume=True), provider_factory=FakeProvider)
    assert [(row["identifier"], row["status"]) for row in gap["rows"] if row["status"] == "staged"] == [("A", "staged")]

    class ConcurrentWriter(FakeProvider):
        def fetch(self, item, start, end):
            frame = super().fetch(item, start, end)
            # A different canonical writer removes a previously covered item
            # while the one missing instrument is being fetched.
            changed = _prices(self.root)
            changed.loc[changed["etf_id"].ne("B")].to_parquet(self.root / "data/validated/prices/prices_daily.parquet", index=False)
            return frame

    with pytest.raises(ValueError, match="canonical resume coverage changed during fetch: B"):
        fetch.fetch_full_universe(replace(options, staging=root / "race-staging", resume=True, promote=True), provider_factory=ConcurrentWriter)
    assert "B" not in set(_prices(root)["etf_id"])
    assert not _prices(root).loc[_prices(root)["etf_id"].eq("A"), "date"].eq(pd.Timestamp("2024-01-03")).any()


def _offline_action_chain(root, monkeypatch, missing_column=None, periods=4):
    from etf_cockpit.data import yfinance_provider as yahoo

    settings = DataProvidersConfig(providers={
        "prices": ProviderSection(active_provider="yfinance"),
        "stooq": ProviderSection(active_provider="stooq"),
        "tiingo": ProviderSection(active_provider="tiingo", api_key="offline-fixture"),
        "twelvedata": ProviderSection(active_provider="twelvedata", api_key="offline-fixture"),
    })
    monkeypatch.setattr(fetch, "load_config", lambda _: SimpleNamespace(data_providers=settings))
    monkeypatch.setattr(fetch, "_yahoo_session", lambda _: SimpleNamespace(close=lambda: None))
    raw = pd.DataFrame({"Open": 10.0, "High": 12.0, "Low": 9.0, "Close": 11.0,
                        "Adj Close": 10.5, "Volume": 100, "Dividends": 0.0, "Stock Splits": 0.0},
                       index=pd.bdate_range("2024-01-02", periods=periods))
    seen = []

    def download(*_args, **_kwargs):
        seen.append("yfinance")
        return raw.drop(columns=[missing_column]) if missing_column else raw.copy()

    monkeypatch.setattr(yahoo, "_import_yfinance", lambda: SimpleNamespace(download=download))
    monkeypatch.setattr(yahoo, "_minor_unit_divisor", lambda *_args, **_kwargs: 1)

    def http_reply(_limiter, url, **_kwargs):
        if "stooq.com" in url:
            seen.append("stooq")
            return SimpleNamespace(text=raw.rename_axis("Date").reset_index().to_csv(index=False),
                                   raise_for_status=lambda: None)
        name = "tiingo" if "tiingo.com" in url else "twelvedata"
        seen.append(name)
        frame = raw.drop(columns=[missing_column]) if missing_column else raw.copy()
        frame = frame.rename_axis("date").reset_index().rename(columns={
            "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adjClose",
            "Volume": "volume", "Dividends": "divCash", "Stock Splits": "splitFactor",
        })
        if "splitFactor" in frame:
            frame["splitFactor"] = 1.0
        values = frame.to_dict("records")
        payload = values if name == "tiingo" else {"values": values, "meta": {"currency": "EUR"}}
        return SimpleNamespace(json=lambda: payload)

    monkeypatch.setattr(fetch, "_http_get", http_reply)
    return raw, seen


def _assert_missing_action_column(tmp_path, monkeypatch, column):
    from etf_cockpit.data.yfinance_provider import YFinanceProvider

    root = _root(tmp_path / "root")
    _, seen = _offline_action_chain(root, monkeypatch, column)
    options = _options(root)
    options.staging.mkdir()
    item = fetch.FetchItem("prices", "B", "B", "EUR")
    result_path = options.staging / "worker.json"
    fetch._worker([item], options, options.start, options.end, result_path, fetch.ProviderChain)
    row, = json.loads(result_path.read_text())
    assert row["status"] == "missing"
    assert row["reason"] == "corporate_action_columns_missing"
    assert seen == ["yfinance", "stooq", "tiingo", "twelvedata"]
    assert not (options.staging / f"{item.key}.parquet").exists()
    assert not (root / "data").exists()
    # The other canonical writer uses public Yahoo price acquisition too.
    result = YFinanceProvider().fetch_prices(["B"], options.start, options.end)
    assert not result.ok and result.data is None
    with pytest.raises(ValueError, match="^corporate_action_columns_missing$"):
        YFinanceProvider().fetch_daily_prices("B", options.start, options.end)
    assert YFinanceProvider().validate_symbol("B")  # Listing-only callers keep their existing behavior.


def test_missing_dividends_column_reports_missing_without_staging(tmp_path, monkeypatch):
    _assert_missing_action_column(tmp_path, monkeypatch, "Dividends")


def test_missing_stock_splits_column_reports_missing_without_staging(tmp_path, monkeypatch):
    _assert_missing_action_column(tmp_path, monkeypatch, "Stock Splits")


@pytest.mark.parametrize("marker", [None, False, "true", True], ids=["absent", "false", "string", "missing-provider"])
def test_promote_refuses_staging_without_action_evidence(tmp_path, monkeypatch, capsys, marker):
    from scripts import fetch_full_universe as cli

    root = _root(tmp_path / "root")
    options = _options(root)
    report = fetch.fetch_full_universe(options, provider_factory=FakeProvider)
    staged_row = next(row for row in report["rows"] if row["kind"] == "prices")
    stage = Path(staged_row["path"])
    frame = pd.read_parquet(stage)
    if marker is None:
        frame = frame.drop(columns="actions_evidenced")
    else:
        frame["actions_evidenced"] = marker
    if marker is True:
        frame = frame.drop(columns="provider")
    frame.to_parquet(stage, index=False)
    monkeypatch.setattr(cli, "fetch_full_universe", lambda options: fetch.fetch_full_universe(options, provider_factory=NoFetch))
    with pytest.raises(SystemExit) as error:
        cli.main(["--root", str(root), "--start", "2024-01-02", "--end", "2024-01-05", "--warmup-days", "0",
                  "--fill-days", "0", "--workers", "1", "--rate-per-host", "1000", "--staging", str(options.staging),
                  "--resume", "--promote"])
    assert error.value.code == 2
    expected = "staged corporate-action provider" if marker is True else "staged corporate actions are not evidenced"
    assert expected in capsys.readouterr().err
    assert json.loads((options.staging / "report.json").read_text())["promotion"] == "failed"
    assert _store_bytes(root) == {}


def test_present_zero_action_columns_are_kept_with_provider_evidence(tmp_path, monkeypatch):
    from etf_cockpit.data.yfinance_provider import YFinanceProvider

    root = _root(tmp_path / "root")
    raw, seen = _offline_action_chain(root, monkeypatch)
    options = _options(root)
    options.staging.mkdir()
    item = fetch.FetchItem("prices", "B", "B", "EUR")
    result_path = options.staging / "worker.json"
    fetch._worker([item], options, options.start, options.end, result_path, fetch.ProviderChain)
    row, = json.loads(result_path.read_text())
    assert row["status"] == "staged"
    assert seen == ["yfinance"]
    frame = pd.read_parquet(row["path"])
    assert len(frame) == len(raw)
    assert frame[["dividends", "stock_splits"]].eq(0.0).all().all()
    assert frame["is_adjusted"].all() and frame["actions_evidenced"].eq(True).all()
    assert frame["provider"].eq("yfinance").all()
    items, revision = fetch._items(root)
    fetch.promote_staging(options, [row], items, revision)
    assert _prices(root)[["dividends", "stock_splits"]].eq(0.0).all().all()
    # Present but unknown action values must remain unknown, never zero-filled.
    raw.iloc[0, raw.columns.get_loc("Dividends")] = float("nan")
    strict = YFinanceProvider()._download_one(symbol="B", etf_id="B", start_date=options.start,
                                             end_date=options.end, require_actions=True)
    assert pd.isna(strict["dividends"].iloc[0])


def _quarantine_fixture(tmp_path, monkeypatch, periods=100):
    root = _root(tmp_path / "root")
    raw, seen = _offline_action_chain(root, monkeypatch, periods=periods)
    raw.index = pd.bdate_range(end="2024-05-20", periods=periods)
    item = fetch.FetchItem("prices", "B", "B", "EUR")
    _, revision = fetch._items(root)
    monkeypatch.setattr(fetch, "_items", lambda _: ([item], revision))
    options = replace(_options(root), start=raw.index[0].date(), end=raw.index[-1].date())
    return root, raw, seen, item, options


def test_six_missing_high_among_100_exceeds_quarantine_cap(tmp_path, monkeypatch):
    _, raw, seen, item, options = _quarantine_fixture(tmp_path, monkeypatch)
    raw.iloc[:6, raw.columns.get_loc("High")] = float("nan")
    report = fetch.fetch_full_universe(options)
    row, = report["rows"]
    assert row["status"] == "missing"
    assert "6 invalid OHLC rows exceed quarantine cap 5 of 100 rows" in row["reason"]
    assert row["provider_attempts"][0]["reason"] == "6 invalid OHLC rows exceed quarantine cap 5 of 100 rows"
    assert seen == ["yfinance", "stooq", "tiingo", "twelvedata"]
    assert not (options.staging / f"{item.key}.parquet").exists()


def test_one_missing_high_among_100_is_quarantined_and_audited(tmp_path, monkeypatch):
    from etf_cockpit.data.yfinance_provider import YFinanceProvider

    _, raw, seen, _, options = _quarantine_fixture(tmp_path, monkeypatch)
    raw.iloc[10, raw.columns.get_loc("High")] = float("nan")
    report = fetch.fetch_full_universe(options)
    row, = report["rows"]
    expected = [{"date": raw.index[10].date().isoformat(), "reason": "OHLC missing, non-finite or non-positive"}]
    assert row["status"] == "staged" and row["rows"] == 99
    assert row["dropped_rows"] == expected
    staged = pd.read_parquet(row["path"])
    assert staged.attrs["dropped_rows"] == expected
    assert pd.Timestamp(raw.index[10]) not in set(staged["date"])
    assert json.loads((options.staging / "report.json").read_text())["rows"][0]["dropped_rows"] == expected
    assert seen == ["yfinance"]
    # Listing/FX callers retain the existing drop-missing behavior.
    legacy = YFinanceProvider()._download_one(symbol="B", etf_id="B", start_date=options.start, end_date=options.end)
    assert len(legacy) == 99 and legacy["high"].notna().all()


@pytest.mark.parametrize(("column", "reason"), [("Volume", "Required volume values"),
                                               ("Dividends", "missing/invalid corporate actions"),
                                               ("Stock Splits", "missing/invalid corporate actions")])
def test_missing_high_cannot_hide_invalid_volume_or_actions(tmp_path, monkeypatch, column, reason):
    _, raw, _, item, options = _quarantine_fixture(tmp_path, monkeypatch)
    settings = DataProvidersConfig(providers={"prices": ProviderSection(active_provider="yfinance")})
    monkeypatch.setattr(fetch, "load_config", lambda _: SimpleNamespace(data_providers=settings))
    raw.iloc[10, raw.columns.get_loc("High")] = float("nan")
    raw.iloc[10, raw.columns.get_loc(column)] = -1.0
    report = fetch.fetch_full_universe(options)
    row, = report["rows"]
    assert row["status"] == "missing"
    assert reason in row["provider_attempts"][0]["reason"]
    assert not (options.staging / f"{item.key}.parquet").exists()


def test_one_invalid_ohlc_among_100_is_quarantined_and_audited(tmp_path, monkeypatch):
    _, raw, seen, item, options = _quarantine_fixture(tmp_path, monkeypatch)
    raw.iloc[10, raw.columns.get_loc("High")] = 10.0  # Below close, without changing any prices.
    report = fetch.fetch_full_universe(options)
    row, = report["rows"]
    expected = [{"date": raw.index[10].date().isoformat(), "reason": "high below open/close"}]
    assert row["status"] == "staged" and row["rows"] == 99
    assert row["dropped_rows"] == expected and row["absent_weekdays"] == 1
    assert row["provider_attempts"] == [{"provider": "yfinance", "status": "accepted"}]
    assert seen == ["yfinance"]
    staged = pd.read_parquet(row["path"])
    assert staged.attrs["dropped_rows"] == expected
    assert json.loads((options.staging / "report.json").read_text())["rows"][0]["dropped_rows"] == expected
    assert staged["actions_evidenced"].eq(True).all()
    assert pd.Timestamp(raw.index[10]) not in set(staged["date"])
    assert staged["close"].eq(11.0).all() and staged["adjusted_close"].eq(10.5).all()
    assert not fetch._covered(staged, item, options.start, options.end)
    reused = fetch.fetch_full_universe(replace(options, only_missing=True), provider_factory=NoFetch)
    assert reused["rows"][0]["dropped_rows"] == expected
    assert reused["rows"] == report["rows"]
    assert reused["selected"] == 0 and "nothing to fetch" in reused["message"]


@pytest.mark.parametrize(("periods", "bad_rows", "status"), [(100, 5, "staged"), (100, 6, "missing"),
                                                            (1000, 10, "staged"), (1000, 11, "missing")])
def test_invalid_ohlc_cap_rejects_history_and_reports_fallbacks(tmp_path, monkeypatch, periods, bad_rows, status):
    _, raw, seen, item, options = _quarantine_fixture(tmp_path, monkeypatch, periods)
    raw.iloc[:bad_rows, raw.columns.get_loc("High")] = 10.0
    report = fetch.fetch_full_universe(options)
    row, = report["rows"]
    assert row["status"] == status
    if status == "missing":
        assert "exceed quarantine cap" in row["reason"]
        assert seen == ["yfinance", "stooq", "tiingo", "twelvedata"]
        assert [attempt["provider"] for attempt in row["provider_attempts"]] == seen
        assert not (options.staging / f"{item.key}.parquet").exists()
    else:
        assert row["rows"] == periods - bad_rows and len(row["dropped_rows"]) == bad_rows
        assert seen == ["yfinance"]


@pytest.mark.parametrize("adjusted", [float("nan"), 0.0, -1.0, float("inf")], ids=["missing", "zero", "negative", "infinite"])
def test_invalid_adjusted_close_remains_instrument_rejection(tmp_path, monkeypatch, adjusted):
    _, raw, seen, item, options = _quarantine_fixture(tmp_path, monkeypatch)
    raw.iloc[10, raw.columns.get_loc("Adj Close")] = adjusted
    raw.iloc[10, raw.columns.get_loc("High")] = 10.0  # Cannot hide bad adjusted close by quarantining this date.
    report = fetch.fetch_full_universe(options)
    row, = report["rows"]
    assert row["status"] == "missing"
    assert "Adjusted close is missing or non-positive" in row["reason"]
    assert seen == ["yfinance", "stooq", "tiingo", "twelvedata"]
    assert not (options.staging / f"{item.key}.parquet").exists()


def test_only_missing_cli_refetches_only_missing_and_reuses_staged_bytes(tmp_path, monkeypatch, capsys):
    from scripts import fetch_full_universe as cli

    root = _root(tmp_path / "root")
    options = _options(root)
    (root / "behavior.json").write_text(json.dumps({"A": "missing", "B": "gap"}))
    first = fetch.fetch_full_universe(options, provider_factory=FakeProvider)
    preserved = {row["path"]: Path(row["path"]).read_bytes() for row in first["rows"] if row["status"] == "staged"}
    (root / "behavior.json").write_text("{}")
    calls = []

    class MissingOnly(FakeProvider):
        def fetch(self, item, start, end):
            calls.append(item.identifier)
            return super().fetch(item, start, end)

    monkeypatch.setattr(cli, "fetch_full_universe", lambda options: fetch.fetch_full_universe(options, provider_factory=MissingOnly))
    args = ["--root", str(root), "--start", "2024-01-02", "--end", "2024-01-05", "--warmup-days", "0",
            "--fill-days", "0", "--workers", "1", "--staging", str(options.staging), "--only-missing"]
    assert cli.main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert calls == ["A"] and second["missing"] == 0
    assert {row["identifier"] for row in second["rows"] if row["status"] == "resumed_staging"} == {"B", "BENCH", "USD/EUR"}
    assert all(Path(path).read_bytes() == payload for path, payload in preserved.items())
    calls.clear()
    assert cli.main(args) == 0
    assert calls == []


def test_only_missing_refuses_changed_window_or_missing_stage(tmp_path):
    root = _root(tmp_path / "root")
    options = _options(root)
    first = fetch.fetch_full_universe(options, provider_factory=FakeProvider)
    with pytest.raises(ValueError, match="same window and universe revision"):
        fetch.fetch_full_universe(replace(options, end=date(2024, 1, 4), only_missing=True), provider_factory=NoFetch)
    # Evidence must still be valid when the report selects work to fetch.
    first["rows"][-1].update(status="missing", reason="retry fixture")
    (options.staging / "report.json").write_text(json.dumps(first))
    Path(first["rows"][0]["path"]).unlink()
    with pytest.raises(ValueError):
        fetch.fetch_full_universe(replace(options, only_missing=True), provider_factory=NoFetch)


@pytest.mark.parametrize("row_only", [False, True], ids=["full-report", "row-only-report"])
def test_only_missing_copied_report_selects_by_kind_and_identifier_and_merges(tmp_path, monkeypatch, capsys, row_only):
    from scripts import fetch_full_universe as cli

    root = _root(tmp_path / "root")
    items, revision = fetch._items(root)
    items.append(fetch.FetchItem("prices", "USD/EUR", "PAIR-ETF", "EUR"))
    monkeypatch.setattr(fetch, "_items", lambda _: (items, revision))
    options = _options(root)
    first = fetch.fetch_full_universe(options, provider_factory=FakeProvider)
    copied = tmp_path / "copied-staging"
    copied.mkdir()
    missing = {("prices", "A"), ("fx", "USD/EUR")}
    preserved = {}
    for row in first["rows"]:
        key = (row["kind"], row["identifier"])
        if key in missing:
            row.clear()
            row.update(kind=key[0], identifier=key[1], status="missing", reason="first run missing")
        else:
            stage = copied / Path(row["path"]).name
            preserved[stage] = Path(row["path"]).read_bytes()
            stage.write_bytes(preserved[stage])
            row["path"] = str(stage)
    (copied / "report.json").write_text(json.dumps({"rows": first["rows"]} if row_only else first))
    calls = []

    class MissingOnly(FakeProvider):
        def fetch(self, item, start, end):
            calls.append((item.kind, item.identifier))
            return super().fetch(item, start, end)

    monkeypatch.setattr(cli, "fetch_full_universe", lambda options: fetch.fetch_full_universe(options, provider_factory=MissingOnly))
    assert cli.main(["--root", str(root), "--start", "2024-01-02", "--end", "2024-01-05", "--warmup-days", "0",
                     "--fill-days", "0", "--workers", "1", "--staging", str(copied), "--only-missing"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(calls) == missing and len(calls) == 2
    assert report["selected"] == 2 and report["missing"] == 0
    assert len(report["rows"]) == len(first["rows"])
    assert {(row["kind"], row["identifier"]) for row in report["rows"] if row["status"] == "staged"} == missing
    assert {(row["kind"], row["identifier"]) for row in report["rows"] if row["status"] == "resumed_staging"} == {
        (item.kind, item.identifier) for item in items
    } - missing
    assert all(stage.read_bytes() == payload for stage, payload in preserved.items())
    assert json.loads((copied / "report.json").read_text()) == report
    assert report["execution_allowed"] is False


@pytest.mark.parametrize("rows", [[], [{"kind": "fx", "identifier": "A", "status": "missing", "reason": "unmatched kind"}],
                                  [{"kind": "prices", "identifier": "B", "status": "staged", "reason": "copied summary"}]])
def test_only_missing_zero_selection_is_clean_cli_noop(tmp_path, monkeypatch, capsys, rows):
    from scripts import fetch_full_universe as cli

    root = _root(tmp_path / "root")
    options = _options(root)
    options.staging.mkdir()
    (options.staging / "report.json").write_text(json.dumps({"rows": rows}))
    monkeypatch.setattr(cli, "fetch_full_universe", lambda options: fetch.fetch_full_universe(options, provider_factory=NoFetch))
    assert cli.main(["--root", str(root), "--start", "2024-01-02", "--end", "2024-01-05", "--warmup-days", "0",
                     "--fill-days", "0", "--workers", "2", "--staging", str(options.staging), "--only-missing", "--promote"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["rows"] == rows and report["selected"] == 0
    assert "nothing to fetch" in report["message"]
    assert report["promotion"] == "not_requested"
    assert not list(options.staging.glob("run-*"))
    assert _store_bytes(root) == {}
