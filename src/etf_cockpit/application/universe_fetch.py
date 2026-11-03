"""Full-universe acquisition; workers stage evidence, one parent promotes it.

Dates are inclusive. Warmup/fill are calendar-day request padding, never data
imputation; the padded end is capped at today. Resume requires every weekday
in the padded window (conservative for holidays/unknown exchange calendars).
The active provider precedes other explicitly enabled adapters in configuration
declaration order. No disabled source is enabled as an implicit fallback.
Adjusted price backfills are known at retrieval, not at their historical close.
Benchmark currency must come from its universe record or explicit configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import time
from typing import Callable
from urllib.parse import urlsplit
import uuid

import numpy as np
import pandas as pd
import requests
import yaml

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group
from etf_cockpit.core.config import load_config
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.http_fetch import requests_get_checked, same_host_https
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.data.fx_data import validate_fx_rates
from etf_cockpit.data.import_pipeline import (
    _json_validator,
    _parquet_bytes,
    _parquet_validator,
    _metadata_to_json,
)
from etf_cockpit.data.provenance import metadata_from_frame, sha256_dataframe
from etf_cockpit.data.universe_store import load_universe
from etf_cockpit.data.validation import validate_prices


@dataclass(frozen=True)
class FetchOptions:
    root: Path
    start: date
    end: date
    staging: Path
    warmup_days: int = 400
    fill_days: int = 10
    workers: int = 4
    rate_per_host: float = 1.0
    promote: bool = False
    resume: bool = False

    def window(self) -> tuple[date, date]:
        if self.start > self.end or self.end > date.today():
            raise ValueError("start <= end <= today is required")
        if self.warmup_days < 0 or self.fill_days < 0 or self.workers < 1:
            raise ValueError("padding must be non-negative and workers positive")
        if not math.isfinite(self.rate_per_host) or self.rate_per_host <= 0:
            raise ValueError("rate-per-host must be finite and positive")
        return self.start - timedelta(days=self.warmup_days), min(date.today(), self.end + timedelta(days=self.fill_days))


@dataclass(frozen=True)
class FetchItem:
    kind: str
    identifier: str
    symbol: str
    currency: str

    @property
    def key(self) -> str:
        return hashlib.sha256(json.dumps(self.__dict__, sort_keys=True).encode()).hexdigest()


class SharedHostLimiter:
    """Native file locks share admission/cooldowns across all fetch processes.

    Four attempts maximum; Retry-After seconds or HTTP dates are a lower bound
    on exponential backoff. Sleep occurs outside the guard; admission rechecks
    shared cooldowns so another process cannot bypass a newly received 429.
    """

    def __init__(self, directory: Path, rate: float, *, clock=time.time, sleep=time.sleep, wall_clock=time.time):
        self.directory, self.interval = directory, 1.0 / rate
        self.clock, self.sleep, self.wall_clock = clock, sleep, wall_clock

    def _paths(self, host: str) -> tuple[Path, Path]:
        key = hashlib.sha256(host.casefold().encode()).hexdigest()
        return self.directory / f"{key}.guard", self.directory / f"{key}.json"

    def acquire(self, host: str) -> None:
        guard, state = self._paths(host)
        while True:
            with persistent_file_guard(guard):
                now = self.clock()
                delay = max(0.0, (float(state.read_text()) if state.exists() else now) - now)
                if delay == 0:
                    state.write_text(str(now + self.interval))
                    return
            self.sleep(delay)

    def defer(self, host: str, seconds: float) -> None:
        guard, state = self._paths(host)
        with persistent_file_guard(guard):
            previous = float(state.read_text()) if state.exists() else 0.0
            state.write_text(str(max(previous, self.clock() + seconds)))

    def request(self, call: Callable, url: str):
        host = urlsplit(url).hostname
        if not host:
            raise ValueError("provider URL needs a host")
        for attempt in range(4):
            self.acquire(host)
            response = call()
            if response.status_code != 429:
                return response
            value = response.headers.get("Retry-After", "0")
            try:
                retry_after = float(value)
            except (TypeError, ValueError):
                try:
                    retry_after = parsedate_to_datetime(value).timestamp() - self.wall_clock()
                except (TypeError, ValueError, OverflowError):
                    retry_after = 0.0
            delay = max(2.0 ** attempt, retry_after if math.isfinite(retry_after) else 0.0)
            self.defer(host, delay)
            response.close()
        raise RuntimeError("HTTP 429: retry budget exhausted; host cooldown retained")


def _http_get(limiter: SharedHostLimiter, url: str, **kwargs):
    def get_one(target, **arguments):
        return limiter.request(lambda: requests.get(target, **arguments), target)

    kwargs.pop("allow_redirects", None)
    return requests_get_checked(get_one, url, allowed=same_host_https(url), **kwargs)


def _yahoo_session(limiter: SharedHostLimiter):
    # Use yfinance's optional HTTP backend when installed, with its supported
    # requests fallback; this lane does not add a mandatory dependency.
    try:
        from curl_cffi.requests import Session
        session_options = {"impersonate": "chrome"}
    except ImportError:
        from requests import Session
        session_options = {}

    class LimitedSession(Session):
        def request(self, method, url, *args, **kwargs):
            send = super().request
            return limiter.request(lambda: send(method, url, *args, **kwargs), url)

    return LimitedSession(**session_options)


class ProviderChain:
    """Reuse existing adapters and normalization; no alternate price calculation."""

    def __init__(self, root: Path, limiter: SharedHostLimiter):
        self.config = load_config(root / "configs")
        self.limiter = limiter
        self.yahoo_session = None

    def close(self):
        if self.yahoo_session is not None:
            self.yahoo_session.close()

    def fetch(self, item: FetchItem, start: date, end: date) -> pd.DataFrame:
        from etf_cockpit.data.stooq_provider import StooqProvider
        from etf_cockpit.data.tiingo_provider import TiingoProvider
        from etf_cockpit.data.twelvedata_provider import TwelveDataProvider
        from etf_cockpit.data.yfinance_provider import YFinanceProvider

        section = self.config.data_providers.section("prices" if item.kind == "prices" else "fx")
        candidates = [(section.active_provider, section), *(
            (entry.active_provider, entry) for key, entry in self.config.data_providers.providers.items()
            if key == entry.active_provider and entry.active_provider not in {"none", ""}
        )]
        seen, reasons = set(), []
        for name, settings in candidates:
            name = name.strip().lower()
            if name in seen or name in {"none", ""}:
                continue
            seen.add(name)
            try:
                symbol = settings.symbols_map.get(item.identifier, item.symbol)
                if name == "yfinance":
                    if self.yahoo_session is None:
                        self.yahoo_session = _yahoo_session(self.limiter)
                    adapter = YFinanceProvider(settings, session=self.yahoo_session, instrument_metadata={item.identifier: {"currency": item.currency}})
                    if item.kind == "fx":
                        result = adapter.fetch_fx([item.identifier], start, end + timedelta(days=1))
                        if not result.ok:
                            raise ValueError(result.message)
                        frame = result.data
                    else:
                        frame = adapter._download_one(symbol=symbol, etf_id=item.identifier, start_date=start,
                                                      end_date=end + timedelta(days=1), require_actions=True)
                elif item.kind == "prices" and name == "stooq":
                    frame = StooqProvider(settings, http_get=lambda url, **kw: _http_get(self.limiter, url, **kw)).fetch_daily_prices(symbol, start, end)
                elif item.kind == "prices" and name in {"tiingo", "twelvedata"}:
                    adapter_type = TiingoProvider if name == "tiingo" else TwelveDataProvider

                    class ActionsRequiredProvider(adapter_type):
                        def _normalise(self, raw, symbol, currency):
                            _require_action_columns(raw)
                            return super()._normalise(raw, symbol, currency)

                    adapter = ActionsRequiredProvider(settings, default_currency=item.currency, transport=lambda url, headers: _http_get(self.limiter, url, headers=headers, timeout=30))
                    frame = adapter.fetch_daily_prices(symbol, start, end)
                else:
                    raise ValueError("adapter does not support full adjusted history/actions for this dataset")
                if item.kind == "prices" and "etf_id" in frame:
                    if not frame["etf_id"].isin([item.identifier, symbol]).all():
                        raise ValueError("provider returned the wrong instrument")
                    frame["etf_id"] = item.identifier
                return _validate_frame(frame, item, start, end)
            except Exception as exc:
                reasons.append(f"{name}: {redact_text(str(exc))}")
        if any(reason.endswith(": corporate_action_columns_missing") for reason in reasons):
            raise ValueError("corporate_action_columns_missing")
        raise ValueError("; ".join(reasons) or "no enabled provider")


def _items(root: Path) -> tuple[list[FetchItem], str]:
    snapshot = load_universe(root)
    if snapshot.integrity_errors:
        raise ValueError("canonical universe integrity failed: " + "; ".join(snapshot.integrity_errors))
    if not snapshot.records:
        raise ValueError("canonical universe store is empty or missing")
    records = {row.instrument_id: row for row in snapshot.records}
    prices = {key: FetchItem("prices", key, row.ticker, row.currency) for key, row in records.items() if row.enabled}
    path = root / "configs" / "paper_bots_v1.yaml"
    benchmark = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("benchmark", {}) if path.exists() else {}
    benchmark_id = str(benchmark.get("instrument_id", "")).strip()
    if benchmark_id:
        record = records.get(benchmark_id)
        symbol = str(benchmark.get("yahoo_symbol") or (record.ticker if record else ""))
        currency = record.currency if record else str(benchmark.get("currency", ""))
        prices[benchmark_id] = FetchItem("prices", benchmark_id, symbol, currency)
    else:
        raise ValueError("configured paper-bot benchmark is missing")
    currencies = sorted({item.currency.upper() for item in prices.values() if item.currency} - {"EUR"})
    items = [*prices.values(), *(FetchItem("fx", f"{ccy}/EUR", f"{ccy}/EUR", ccy) for ccy in currencies)]
    return sorted(items, key=lambda item: (item.kind, item.identifier)), snapshot.revision


def _require_action_columns(frame: pd.DataFrame) -> None:
    # Check the provider's raw schema before normalization can introduce columns.
    for aliases in (("dividend", "dividends", "Dividends", "divCash"),
                    ("split_factor", "stock_splits", "Stock Splits", "splitFactor", "splits")):
        if not any(column in frame for column in aliases):
            raise ValueError("corporate_action_columns_missing")


def _validate_frame(frame: pd.DataFrame, item: FetchItem, start: date, end: date) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("no rows returned")
    frame = frame.copy()
    column = "date" if item.kind == "prices" else "as_of_date"
    dates = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    frame[column] = dates
    frame = frame.loc[dates.between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    if frame.empty:
        raise ValueError("no rows in requested window")
    if item.kind == "prices":
        _require_action_columns(frame)
        if "is_adjusted" not in frame or not frame["is_adjusted"].map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value)).all():
            raise ValueError("unadjusted-only or unverifiable adjustment basis")
        for aliases in (("dividend", "dividends"), ("split_factor", "stock_splits")):
            column = next((key for key in aliases if key in frame and frame[key].notna().all()), aliases[0])
            values = pd.to_numeric(frame[column], errors="coerce") if column in frame else pd.Series([float("nan")])
            if not np.isfinite(values).all() or (values < 0).any() or (column == "split_factor" and (values == 0).any()):
                raise ValueError(f"missing/invalid corporate actions: {column}")
            frame[column] = values
        if "etf_id" in frame and not frame["etf_id"].isin([item.identifier, item.symbol]).all():
            raise ValueError("provider returned the wrong instrument")
        frame["etf_id"] = item.identifier
        if "currency" not in frame or not frame["currency"].eq(item.currency).all():
            raise ValueError("provider currency does not match canonical instrument currency")
        report = validate_prices(frame, as_of_date=end, calendar_resolver=lambda _: None)
        blocks = [issue.message for issue in report.issues if issue.severity == "block" and issue.code != "insufficient_history"]
        if blocks:
            raise ValueError("; ".join(blocks))
    else:
        result = validate_fx_rates(frame, today=end)
        if not result.ok:
            raise ValueError("; ".join(result.errors))
        if not result.frame["pair"].eq(item.identifier).all():
            raise ValueError("provider returned the wrong FX pair")
        # The validator normalizes rates but intentionally projects its schema.
        # Keep source identifiers and actual fetch timestamps alongside it.
        frame = frame.reset_index(drop=True)
        for column in result.frame:
            frame[column] = result.frame[column].to_numpy()
    if "source" not in frame or frame["source"].isna().any() or frame["source"].astype(str).str.strip().eq("").any():
        raise ValueError("provider provenance is missing")
    for column in ("fetched_at", "ingested_at", "available_at"):
        if column in frame and pd.to_datetime(frame[column], utc=True, errors="coerce").isna().any():
            raise ValueError(f"invalid {column}")
    if frame.duplicated(["date" if item.kind == "prices" else "as_of_date"]).any():
        raise ValueError("provider returned duplicate dates")
    return frame.sort_values("date" if item.kind == "prices" else "as_of_date").reset_index(drop=True)


def _stamp(frame: pd.DataFrame, item: FetchItem) -> pd.DataFrame:
    frame = frame.copy()
    now = pd.Timestamp.now(tz="UTC")
    if "fetched_at" not in frame:
        frame["fetched_at"] = frame["ingested_at"] if "ingested_at" in frame else now
    if "ingested_at" not in frame:
        frame["ingested_at"] = frame["fetched_at"]
    if "available_at" not in frame:
        frame["available_at"] = frame["fetched_at"]
        if item.kind == "fx":
            frame["availability_basis"] = "live_ingestion"
    return frame


def _covered(frame: pd.DataFrame, item: FetchItem, start: date, end: date) -> bool:
    try:
        frame = _validate_frame(frame, item, start, end)
        if any(column not in frame or pd.to_datetime(frame[column], utc=True, errors="coerce").isna().any() for column in ("fetched_at", "available_at")):
            return False
        dates = pd.DatetimeIndex(pd.to_datetime(frame["date" if item.kind == "prices" else "as_of_date"]))
        expected = pd.bdate_range(start, end)
        return bool(len(expected)) and expected.difference(dates).empty
    except (ValueError, KeyError, TypeError):
        return False


def _read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _coverage_groups(frames):
    groups = {}
    for kind, frame in frames.items():
        column = "etf_id" if kind == "prices" else "pair"
        groups[kind] = frame.groupby(column, sort=False) if column in frame else None
    return groups


def _stored_item(groups, item):
    group = groups[item.kind]
    return group.get_group(item.identifier) if group is not None and item.identifier in group.indices else pd.DataFrame()


def _worker(items, options, start, end, result_path, factory):
    limiter = SharedHostLimiter(options.staging / "limiter", options.rate_per_host)
    rows = []
    provider = None
    try:
        provider = factory(options.root, limiter)
        for item in items:
            row = {"kind": item.kind, "identifier": item.identifier, "pid": os.getpid()}
            try:
                if not item.symbol:
                    raise ValueError("canonical provider symbol is missing")
                if not item.currency:
                    raise ValueError("canonical quote currency is missing")
                frame = _stamp(provider.fetch(item, start, end), item)
                frame = _validate_frame(frame, item, start, end)
                frame["provider"] = frame["source"]
                if item.kind == "prices":
                    frame["actions_evidenced"] = True
                stage = options.staging / f"{item.key}.parquet"
                atomic_write_bytes(stage, _parquet_bytes(frame), validator=_parquet_validator(len(frame)))
                dates = pd.to_datetime(frame["date" if item.kind == "prices" else "as_of_date"])
                row.update(status="staged", path=str(stage), rows=len(frame), checksum=sha256_dataframe(frame),
                           first_date=dates.min().date().isoformat(), last_date=dates.max().date().isoformat(),
                           absent_weekdays=len(pd.bdate_range(start, end).difference(pd.DatetimeIndex(dates))))
            except Exception as exc:
                row.update(status="missing", reason=redact_text(str(exc)))
            rows.append(row)
    except Exception as exc:
        received = {(row["kind"], row["identifier"]) for row in rows}
        rows.extend({"kind": item.kind, "identifier": item.identifier, "status": "missing", "reason": f"worker initialization failed: {redact_text(str(exc))}"}
                    for item in items if (item.kind, item.identifier) not in received)
    finally:
        try:
            if provider is not None and callable(getattr(provider, "close", None)):
                provider.close()
        finally:
            result_path.write_text(json.dumps(rows), encoding="utf-8")


def _destination(root: Path, relative: str) -> Path:
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(current):
            raise ValueError("canonical destination must not traverse links")
        current = current.parent
    return path


def promote_staging(options: FetchOptions, rows: list[dict], items: list[FetchItem], revision: str) -> None:
    """One serial merge and durable atomic publication using the import writer.

    Raw evidence, previous snapshots, prices, FX and metadata share a transaction.
    Its optimistic precondition also detects writers outside this CLI's guard.
    """
    start, end = options.window()
    root = options.root
    by_key = {(item.kind, item.identifier): item for item in items}
    with persistent_file_guard(_destination(root, "data/.universe-fetch.guard"), timeout_seconds=30):
        if load_universe(root).revision != revision:
            raise ValueError("canonical universe changed during fetch")
        prices_path = _destination(root, "data/validated/prices/prices_daily.parquet")
        clean_path = _destination(root, "data/clean/prices.parquet")
        fx_path = _destination(root, "data/clean/fx.parquet")
        originals = {path: path.read_bytes() if path.exists() else None for path in (prices_path, clean_path, fx_path)}
        frames = {"prices": [], "fx": []}
        resumed = _coverage_groups({"prices": _read(prices_path), "fx": _read(fx_path)}) if any(row["status"] == "resumed_canonical" for row in rows) else {}
        for row in rows:
            if row["status"] == "resumed_canonical":
                item = by_key[(row["kind"], row["identifier"])]
                if not _covered(_stored_item(resumed, item), item, start, end):
                    raise ValueError(f"canonical resume coverage changed during fetch: {item.identifier}")
                continue
            if row["status"] not in {"staged", "resumed_staging"}:
                continue
            item = by_key[(row["kind"], row["identifier"])]
            stage = options.staging / f"{item.key}.parquet"
            frame = _read(stage)
            if item.kind == "prices":
                if ("actions_evidenced" not in frame or frame.empty
                        or not frame["actions_evidenced"].map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value)).all()):
                    raise ValueError(f"staged corporate actions are not evidenced: {item.identifier}")
                if "provider" not in frame or "source" not in frame or not frame["provider"].eq(frame["source"]).all():
                    raise ValueError(f"staged corporate-action provider is missing or inconsistent: {item.identifier}")
            frame = _validate_frame(frame, item, start, end)
            if any(column not in frame for column in ("fetched_at", "ingested_at", "available_at")):
                raise ValueError("staged availability provenance is missing")
            frames[item.kind].append(frame)
        extra, merged = [], {}
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for kind, batches in frames.items():
            if not batches:
                continue
            incoming = pd.concat(batches, ignore_index=True)
            canonical = prices_path if kind == "prices" else fx_path
            stored = _read(canonical)
            date_column, id_column = ("date", "etf_id") if kind == "prices" else ("as_of_date", "pair")
            combined = pd.concat([stored, incoming], ignore_index=True) if not stored.empty else incoming
            combined[date_column] = pd.to_datetime(combined[date_column])
            combined = combined.drop_duplicates([id_column, date_column], keep="last").sort_values([id_column, date_column]).reset_index(drop=True)
            merged[kind] = combined
            payload = _parquet_bytes(combined)
            checksum = sha256_dataframe(combined)
            raw_checksum = sha256_dataframe(incoming)
            snapshot_dir = f"data/snapshots/{kind}"
            raw_path = _destination(root, f"data/raw/{kind}/{timestamp}_{raw_checksum[:12]}_{kind}.parquet")
            extra.append(AtomicWriteRequest(raw_path, _parquet_bytes(incoming), _parquet_validator(len(incoming))))
            previous = None
            if originals[canonical] is not None:
                previous = _destination(root, f"{snapshot_dir}/{timestamp}_previous_{canonical.name}")
                extra.append(AtomicWriteRequest(previous, originals[canonical], _parquet_validator(len(stored))))
            metadata = {"dataset_type": kind, "provider_name": "universe_fetch", "rows": len(combined), "checksum": checksum,
                        "raw_path": str(raw_path), "clean_path": str(clean_path if kind == "prices" else fx_path),
                        "raw_checksum": raw_checksum,
                        "compatibility_path": str(prices_path) if kind == "prices" else None,
                        "previous_snapshot_path": str(previous) if previous else None,
                        "metadata": _metadata_to_json(metadata_from_frame(
                            combined, source_name="universe_fetch", source_type=kind,
                            as_of_date=combined[date_column].max().date(), currency="mixed",
                            provider_or_manual_source="per-row provider provenance; full-universe fetch",
                        )),
                        "universe_revision": revision, "execution_allowed": False,
                        "sources": sorted(incoming["source"].astype(str).unique().tolist()),
                        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
                        "availability": "per-row fetched_at/ingested_at/available_at retained"}
            meta_path = _destination(root, f"{snapshot_dir}/{timestamp}_{checksum[:12]}_{kind}_metadata.json")
            extra.append(AtomicWriteRequest(meta_path, json.dumps(metadata, indent=2).encode(), _json_validator))
            if kind == "fx":
                extra.append(AtomicWriteRequest(fx_path, payload, _parquet_validator(len(combined))))

        def precondition():
            if load_universe(root).revision != revision:
                raise ValueError("canonical universe changed before promotion")
            for path, original in originals.items():
                if (path.read_bytes() if path.exists() else None) != original:
                    raise ValueError("canonical store changed before promotion")

        if "prices" in merged:
            # Same serialization and atomic group path used by commit_price_import.
            payload = _parquet_bytes(merged["prices"])
            extra.extend(AtomicWriteRequest(path, payload, _parquet_validator(len(merged["prices"]))) for path in (prices_path, clean_path))
        atomic_write_group(extra, precondition=precondition)


def fetch_full_universe(options: FetchOptions, *, provider_factory=ProviderChain) -> dict:
    start, end = options.window()
    options = FetchOptions(**{**options.__dict__, "root": options.root.resolve(), "staging": options.staging.resolve()})
    for relative in ("configs", "data/clean", "data/validated", "data/raw", "data/snapshots"):
        protected = options.root / relative
        if options.staging == options.root or options.staging.is_relative_to(protected) or protected.is_relative_to(options.staging):
            raise ValueError("staging must be separate from canonical stores/configs")
    options.staging.mkdir(parents=True, exist_ok=True)
    items, revision = _items(options.root)
    report = {"execution_allowed": False, "start": start.isoformat(), "end": end.isoformat(), "universe_revision": revision,
              "workers": options.workers, "promotion": "not_requested", "rows": []}
    # A single invocation owns this staging namespace; fetch processes write disjoint files.
    with persistent_file_guard(options.staging / ".fetch.guard", timeout_seconds=30):
        pending = []
        canonical = {"prices": pd.DataFrame(), "fx": pd.DataFrame()}
        if options.resume:
            canonical = {"prices": _read(options.root / "data/validated/prices/prices_daily.parquet"), "fx": _read(options.root / "data/clean/fx.parquet")}
        canonical = _coverage_groups(canonical)
        for item in items:
            stage = options.staging / f"{item.key}.parquet"
            row = {"kind": item.kind, "identifier": item.identifier}
            if options.resume and stage.exists() and _covered(_read(stage), item, start, end):
                row.update(status="resumed_staging", path=str(stage))
            elif options.resume:
                if _covered(_stored_item(canonical, item), item, start, end):
                    row.update(status="resumed_canonical")
                else:
                    pending.append(item)
                    continue
            else:
                pending.append(item)
                continue
            report["rows"].append(row)
        run_dir = options.staging / f"run-{uuid.uuid4().hex}"
        run_dir.mkdir()
        count = min(options.workers, len(pending))
        processes = []
        for index in range(count):
            packet = (pending[index::count], options, start, end, run_dir / f"worker-{index}.json", provider_factory)
            if options.workers == 1:
                _worker(*packet)
            else:
                process = multiprocessing.get_context("spawn").Process(target=_worker, args=packet)
                process.start()
                processes.append(process)
        for process in processes:
            process.join()
        for index in range(count):
            result_path = run_dir / f"worker-{index}.json"
            results = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else []
            received = {(row["kind"], row["identifier"]) for row in results}
            results.extend({"kind": item.kind, "identifier": item.identifier, "status": "missing", "reason": "fetch worker did not complete"}
                           for item in pending[index::count] if (item.kind, item.identifier) not in received)
            report["rows"].extend(results)
        report["rows"].sort(key=lambda row: (row["kind"], row["identifier"]))
        report["missing"] = sum(row["status"] == "missing" for row in report["rows"])
        report_path = options.staging / "report.json"
        try:
            if options.promote:
                promote_staging(options, report["rows"], items, revision)
                report["promotion"] = "committed"
        except Exception as exc:
            report.update(promotion="failed", promotion_reason=redact_text(str(exc)))
            raise
        finally:
            atomic_write_bytes(report_path, json.dumps(report, indent=2).encode(), validator=_json_validator)
    return report
