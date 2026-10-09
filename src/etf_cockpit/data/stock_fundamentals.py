"""Canonical store and refresh for normal-stock fundamentals (one path per source, one merge rule).

Three small tables live under ``data/clean``:

* ``stock_fundamentals.parquet`` - one row per (instrument, period, source, known_at version)
* ``stock_snapshots.parquet``    - one row per fetch: profile, analyst fields, status and reason
* ``stock_fx.parquet``           - daily FX closes needed to compare a quote currency with the statements

Rows are only ever appended (a value that did not change is not re-appended), so ``known_at`` keeps
the first time each value was seen and the point-in-time view is exact for later replays.
Source order comes from ``configs/stock_fundamentals_v1.yaml``: filings first, then yfinance.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from etf_cockpit.analysis.stock_metrics import PERIOD_FIELDS, Period, as_utc
from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data import stock_sources as src

CONFIG_NAME = "stock_fundamentals_v1.yaml"
PERIOD_COLUMNS = ["instrument_id", "period_end", "period_type", "fiscal_year", "currency", "source", "source_ref", "known_at", *PERIOD_FIELDS]
SNAPSHOT_COLUMNS = [
    "instrument_id", "known_at", "source", "status", "reason", "quote_currency", "financial_currency", "long_name",
    "sector", "industry", "country", "quote_type", "market_cap_provider", "shares_outstanding", "eps_current",
    "eps_90d_ago", "revisions_up_30d", "revisions_down_30d", "cik",
]
FX_COLUMNS = ["pair", "date", "rate", "known_at"]
_CONFIG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class StockTarget:
    instrument_id: str
    name: str
    yahoo_symbol: str
    cik: str | None = None
    region: str = ""
    sector: str = ""
    currency: str = ""


@dataclass
class RefreshReport:
    per_instrument: dict[str, str] = field(default_factory=dict)  # id -> one-line outcome
    rows_added: int = 0
    failures: dict[str, str] = field(default_factory=dict)


def store_paths(root: Path | None = None) -> dict[str, Path]:
    base = Path(root or ROOT) / "data" / "clean"
    return {
        "periods": base / "stock_fundamentals.parquet",
        "snapshots": base / "stock_snapshots.parquet",
        "fx": base / "stock_fx.parquet",
    }


def config_path(root: Path | None = None) -> Path:
    candidate = Path(root or ROOT) / "configs" / CONFIG_NAME
    if candidate.is_file():
        return candidate
    return Path(__file__).resolve().parents[3] / "configs" / CONFIG_NAME


def load_stock_config(root: Path | None = None) -> dict[str, Any]:
    path = config_path(root)
    stamp = path.stat().st_mtime
    cached = _CONFIG_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _CONFIG_CACHE[str(path)] = (stamp, loaded)
    return loaded


# ---------------------------------------------------------------------------------------------
# Table I/O
# ---------------------------------------------------------------------------------------------


def _read(path: Path, columns: Sequence[str]) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=list(columns))
    try:
        frame = pd.read_parquet(path)
    except Exception:  # unreadable store: treated as empty, never as data
        return pd.DataFrame(columns=list(columns))
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame


def _write(path: Path, frame: pd.DataFrame) -> None:
    atomic_write_bytes(path, parquet_payload(frame.reset_index(drop=True)), validate_parquet_file)


def read_periods(root: Path | None = None) -> pd.DataFrame:
    return _read(store_paths(root)["periods"], PERIOD_COLUMNS)


def read_snapshots(root: Path | None = None) -> pd.DataFrame:
    return _read(store_paths(root)["snapshots"], SNAPSHOT_COLUMNS)


def read_fx(root: Path | None = None) -> pd.DataFrame:
    return _read(store_paths(root)["fx"], FX_COLUMNS)


def _concat(frames: Sequence[pd.DataFrame], columns: Sequence[str]) -> pd.DataFrame:
    parts = [frame.reindex(columns=list(columns)).astype(object) for frame in frames if not frame.empty]
    if not parts:
        return pd.DataFrame(columns=list(columns))
    combined = pd.concat(parts, ignore_index=True)
    return combined.infer_objects()


def _same(left: object, right: object) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    try:
        return abs(float(left) - float(right)) <= 1e-9 * max(1.0, abs(float(left)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return left == right


def append_period_rows(existing: pd.DataFrame, instrument_id: str, rows: Iterable[Mapping[str, Any]]) -> tuple[pd.DataFrame, int]:
    """Append rows whose values differ from the latest stored version of the same (period, source)."""

    frame = existing
    added = []
    latest: dict[tuple[str, str, str], pd.Series] = {}
    mine = frame[frame["instrument_id"].astype(str) == instrument_id]
    for _, row in mine.sort_values("known_at").iterrows():
        latest[(str(row["period_end"]), str(row["period_type"]), str(row["source"]))] = row
    for row in rows:
        key = (str(row["period_end"]), str(row["period_type"]), str(row["source"]))
        previous = latest.get(key)
        record = {column: row.get(column) for column in PERIOD_COLUMNS}
        record["instrument_id"] = instrument_id
        if previous is not None and all(_same(previous.get(name), record.get(name)) for name in (*PERIOD_FIELDS, "currency")):
            continue
        added.append(record)
        latest[key] = pd.Series(record)
    if not added:
        return frame, 0
    new = pd.DataFrame(added, columns=PERIOD_COLUMNS)
    combined = new if frame.empty else _concat([frame, new], PERIOD_COLUMNS)
    return combined, len(added)


# ---------------------------------------------------------------------------------------------
# Point-in-time view
# ---------------------------------------------------------------------------------------------


def _row_period(row: Mapping[str, Any], fields: Mapping[str, str]) -> Period | None:
    known = as_utc(row.get("known_at"))
    end = as_utc(row.get("period_end"))
    if known is None or end is None:
        return None
    values = {name: float(row[name]) for name in PERIOD_FIELDS if name in row and pd.notna(row.get(name))}
    return Period(
        period_end=end.date(),
        period_type=str(row.get("period_type")),
        known_at=known,
        currency=str(row.get("currency") or ""),
        source=str(row.get("source") or ""),
        values=values,
        field_sources=dict(fields),
        source_ref=str(row.get("source_ref") or ""),
    )


def periods_for(instrument_id: str, frame: pd.DataFrame, chain: Sequence[str], *, snap_days: int = 4) -> list[Period]:
    """Merged point-in-time versions: the first source in ``chain`` wins, later sources fill gaps.

    A later source only fills a field for the same period (period ends within ``snap_days``) and the
    same currency; each field remembers its source. One version is produced per distinct ``known_at``
    so a replay at an earlier decision time never sees a value that was learned later.
    """

    mine = frame[frame["instrument_id"].astype(str) == str(instrument_id)]
    if mine.empty:
        return []
    rank = {name: index for index, name in enumerate(chain)}
    rows = [dict(row) for _, row in mine.iterrows()]
    for row in rows:
        row["_rank"] = rank.get(str(row.get("source")), len(rank))
        row["_end"] = as_utc(row.get("period_end"))
        row["_known"] = as_utc(row.get("known_at"))
    rows = [row for row in rows if row["_end"] is not None and row["_known"] is not None]
    # cluster period ends of the same type (sources may differ by a day)
    clusters: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (str(item["period_type"]), item["_end"], item["_rank"])):
        for cluster in clusters:
            if cluster["type"] == row["period_type"] and abs((cluster["end"] - row["_end"]).days) <= snap_days:
                cluster["rows"].append(row)
                break
        else:
            clusters.append({"type": row["period_type"], "end": row["_end"], "rows": [row]})
    periods: list[Period] = []
    for cluster in clusters:
        by_source: dict[str, list[dict[str, Any]]] = {}
        for row in cluster["rows"]:
            by_source.setdefault(str(row["source"]), []).append(row)
        times = sorted({row["_known"] for row in cluster["rows"]})
        last: tuple | None = None
        for moment in times:
            chosen: list[dict[str, Any]] = []
            for source in sorted(by_source, key=lambda name: rank.get(name, len(rank))):
                known = [row for row in by_source[source] if row["_known"] <= moment]
                if known:
                    chosen.append(max(known, key=lambda item: item["_known"]))
            if not chosen:
                continue
            primary = chosen[0]
            values: dict[str, Any] = {}
            field_sources: dict[str, str] = {}
            for row in chosen:
                if str(row.get("currency") or "") != str(primary.get("currency") or ""):
                    continue
                for name in PERIOD_FIELDS:
                    if name not in values and name in row and pd.notna(row.get(name)):
                        values[name] = row[name]
                        field_sources[name] = str(row["source"])
            signature = (tuple(sorted((k, float(v)) for k, v in values.items())), str(primary.get("currency")))
            if signature == last:
                continue
            last = signature
            merged = {**primary, **values, "known_at": moment.isoformat(), "period_end": primary["period_end"]}
            period = _row_period(merged, field_sources)
            if period is not None:
                periods.append(period)
    return periods


def latest_snapshot(instrument_id: str, snapshots: pd.DataFrame, decision_time: datetime, *, ok_only: bool = True) -> dict[str, Any] | None:
    mine = snapshots[snapshots["instrument_id"].astype(str) == str(instrument_id)]
    if ok_only:
        mine = mine[mine["status"].astype(str) == "ok"]
    best: dict[str, Any] | None = None
    best_time: datetime | None = None
    for _, row in mine.iterrows():
        known = as_utc(row.get("known_at"))
        if known is None or known > decision_time:
            continue
        if best_time is None or known >= best_time:
            best, best_time = {k: (None if pd.isna(v) else v) for k, v in row.items()}, known
    return best


def no_data_reason(instrument_id: str, snapshots: pd.DataFrame, decision_time: datetime, periods_present: bool) -> str | None:
    """Why an instrument has no usable fundamentals: the newest fetch outcome, or 'never fetched'."""

    mine = snapshots[snapshots["instrument_id"].astype(str) == str(instrument_id)]
    if mine.empty:
        return "fundamentals were never fetched for this instrument: run 'Refresh stock fundamentals'"
    newest = mine.sort_values("known_at").iloc[-1]
    if str(newest.get("status")) != "ok" and str(newest.get("reason") or ""):
        return str(newest["reason"])
    if not periods_present:
        return "the last fetch returned no statements for this instrument"
    return None


def fx_rate(pair: str, on_date: date, fx: pd.DataFrame, *, max_age_days: int = 7) -> tuple[float | None, str | None]:
    """Latest stored close of ``pair`` on or before ``on_date`` (never a later one)."""

    rows = fx[fx["pair"].astype(str) == pair]
    best: tuple[date, float] | None = None
    for _, row in rows.iterrows():
        when = as_utc(row.get("date"))
        if when is None or when.date() > on_date:
            continue
        if best is None or when.date() >= best[0]:
            best = (when.date(), float(row["rate"]))
    if best is None or (on_date - best[0]).days > max_age_days:
        return None, None
    return best[1], best[0].isoformat()


# ---------------------------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------------------------


def refresh_stock_fundamentals(
    targets: Sequence[StockTarget],
    *,
    root: Path | None = None,
    now: datetime | None = None,
    config: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    yfinance_fetch: Callable[..., src.FetchResult] = src.fetch_yfinance,
    edgar_fetch: Callable[..., src.FetchResult] = src.fetch_edgar,
    cik_resolver: Callable[..., str | None] = src.resolve_cik,
    fx_fetch: Callable[..., list[tuple[str, float]]] = src.fetch_fx_rates,
    progress: Callable[[str], None] | None = None,
) -> RefreshReport:
    """Fetch the configured source chain for each target and append new or changed facts."""

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg = dict(config) if config is not None else load_stock_config(root)
    env = os.environ if environ is None else environ
    chain = list((cfg.get("sources", {}) or {}).get("chain", ["sec_edgar", "yfinance"]))
    agent = src.sec_user_agent(cfg, env)
    paths = store_paths(root)
    periods = read_periods(root)
    snapshots = read_snapshots(root)
    fx = read_fx(root)
    report = RefreshReport()
    snapshot_rows: list[dict[str, Any]] = []
    fx_rows: list[dict[str, Any]] = []
    for target in targets:
        notes: list[str] = []
        cik = target.cik
        for source in chain:
            if source == "sec_edgar":
                if cik is None and agent:
                    try:
                        cik = cik_resolver(target.yahoo_symbol, agent)
                    except Exception as exc:
                        notes.append(f"SEC ticker lookup failed: {str(exc)[:80]}")
                if cik is None:
                    if "." not in target.yahoo_symbol:  # a non-US listing has no CIK: not a gap worth reporting
                        notes.append("SEC EDGAR skipped: " + ("no CIK resolved" if agent else "no SEC User-Agent configured (set ETF_COCKPIT_SEC_EDGAR_USER_AGENT)"))
                    continue
                result = edgar_fetch(cik, cfg, user_agent=agent)
            elif source == "yfinance":
                result = yfinance_fetch(target.yahoo_symbol, cfg, now=stamp)
            else:
                continue
            periods, added = append_period_rows(periods, target.instrument_id, result.rows)
            report.rows_added += added
            if result.status != "ok":
                notes.append(f"{result.source}: {result.reason or result.status}")
            if result.snapshot:
                row = {column: result.snapshot.get(column) for column in SNAPSHOT_COLUMNS}
                row.update(instrument_id=target.instrument_id, known_at=result.snapshot.get("known_at") or stamp.isoformat(), source=result.source, status=result.status, reason=result.reason, cik=cik)
                snapshot_rows.append(row)
            if result.source == "yfinance" and result.status == "ok":
                fx_rows.extend(_needed_fx(result.snapshot, fx_fetch, stamp, cfg))
        report.per_instrument[target.instrument_id] = "; ".join(notes) if notes else "ok"
        if notes and not any(True for _ in periods[periods["instrument_id"].astype(str) == target.instrument_id].itertuples()):
            report.failures[target.instrument_id] = "; ".join(notes)
        if progress:
            progress(f"{target.instrument_id}: {report.per_instrument[target.instrument_id]}")
    _write(paths["periods"], periods)
    if snapshot_rows:
        _write(paths["snapshots"], _concat([snapshots, pd.DataFrame(snapshot_rows, columns=SNAPSHOT_COLUMNS)], SNAPSHOT_COLUMNS))
    if fx_rows:
        merged = _concat([fx, pd.DataFrame(fx_rows, columns=FX_COLUMNS)], FX_COLUMNS)
        _write(paths["fx"], merged.drop_duplicates(["pair", "date"], keep="first"))
    return report


def _needed_fx(snapshot: Mapping[str, Any], fx_fetch: Callable[..., list[tuple[str, float]]], stamp: datetime, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Daily FX closes: quote -> statement currency (same-date comparison) and quote -> EUR (size bands)."""

    minor = (config.get("reporting", {}) or {}).get("minor_currency_units", {}) or {}
    quote = str(snapshot.get("quote_currency") or "")
    financial = str(snapshot.get("financial_currency") or "")
    if not quote:
        return []
    quote_major = str(minor.get(quote, [quote])[0])
    financial_major = str(minor.get(financial, [financial])[0]) if financial else ""
    rows: list[dict[str, Any]] = []
    for target in dict.fromkeys(item for item in (financial_major, "EUR") if item and item != quote_major):
        try:
            series = fx_fetch(quote_major, target)
        except Exception:
            continue
        rows.extend({"pair": f"{quote_major}{target}", "date": day, "rate": rate, "known_at": stamp.isoformat()} for day, rate in series if day)
    return rows


def targets_from_universe(records: Iterable[Mapping[str, Any]], *, excluded_sectors: Sequence[str]) -> list[StockTarget]:
    """Stock targets from universe records (dict-like). No ids are listed in code: type and sector decide."""

    blocked = {item.casefold() for item in excluded_sectors}
    targets = []
    for record in records:
        kind = str(record.get("instrument_type") or record.get("asset_type") or "").casefold()
        if kind != "stock" or not bool(record.get("enabled", True)):
            continue
        if str(record.get("lifecycle") or ""):  # delisted or merged: stored history is kept, nothing new is fetched
            continue
        if str(record.get("sector") or "").casefold() in blocked:
            continue
        symbol = str(record.get("provider_symbol") or record.get("ticker") or "").strip()
        if not symbol:
            continue
        targets.append(
            StockTarget(
                str(record["id"]),
                str(record.get("name") or record["id"]),
                symbol,
                (str(record["cik"]).zfill(10) if record.get("cik") else None),
                str(record.get("region") or ""),
                str(record.get("sector") or ""),
                str(record.get("currency") or ""),
            )
        )
    return targets
