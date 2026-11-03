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
