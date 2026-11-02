"""Data-readiness launch gate (PLAN-T4-20261023, D10): no replay or paper bot starts on incomplete data (application; ADR-0002).

``evaluate_readiness`` checks every decision date of an interval against the stored point-in-time inputs and fails closed:

* the date has a stored score run and an eligibility log;
* point-in-time membership is verified for every admitted instrument;
* enough scoreable stocks and ETFs;
* enough admitted instruments with every headline-weight > 0 family available and fresh;
* prices (per date for admitted instruments, and benchmark prices over the interval's sessions);
* FX to EUR for every foreign currency of an admitted instrument (the canonical ``EurRateBook``);
* per-gate results stored for every scored row.

Only existing stores are read through the existing loaders; nothing is written. An unavailable input is a FAIL with its reason,
never an assumed pass. ``execution_allowed`` stays false.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from etf_cockpit.application.score_backfill import CALENDAR_INSTRUMENT_ID
from etf_cockpit.core.paths import CODE_CONFIG_DIR, CONFIG_DIR, ROOT
from etf_cockpit.data.duckdb_store import SYNTHETIC_PRICE_SOURCES, load_prices
from etf_cockpit.data.fx_data import EurRateBook, load_fx_rates, major_currency
from etf_cockpit.data.replay_membership import ListingHistory
from etf_cockpit.data.score_history_backfill import (
    load_backfill_eligibility,
    load_backfill_manifest,
    load_backfill_score_history,
)
from etf_cockpit.signals.canonical_scoring import headline_evidence_weights

_CONFIG_NAME = "data_readiness_v1.yaml"
# The data root (ETF_COCKPIT_ROOT) may be a checkout without this file: fall back to the configs next to this code.
CONFIG_PATH = CONFIG_DIR / _CONFIG_NAME if (CONFIG_DIR / _CONFIG_NAME).is_file() else CODE_CONFIG_DIR / _CONFIG_NAME
PRICES_RELATIVE_PATH = Path("data") / "clean" / "prices.parquet"
FX_RELATIVE_PATH = Path("data") / "clean" / "fx.parquet"
CHECKS = ("scored_run", "pit_membership", "universe_counts", "family_completeness", "prices", "fx", "gate_results")
CAVEATS = (
    "Prices carry no per-bar known_at: price knowledge time is the file time, so price point-in-time is bounded by the dated rows only.",
    "Family availability is read from the stored score rows (pit_terms_unavailable, missing_components); it is not re-derived.",
    "Delisted prices without a free source stay unverified (D9).",
)


@dataclass(frozen=True)
class ReadinessThresholds:
    policy_version: str
    decision_cadence_sessions: int
    min_scoreable_stocks: int
    min_scoreable_etfs: int
    stock_count_asset_types: frozenset[str]
    etf_count_asset_types: frozenset[str]
    min_family_complete_share: float
    stock_like_asset_types: frozenset[str]
    etf_policy_asset_types: frozenset[str]
    fresh_statuses: frozenset[str]
    min_price_coverage_share: float
    max_stale_business_days: int
    max_gate_wiring_failures: int
    gate_results_column: str
    max_gap_ids_listed: int


def load_thresholds(path: Path = CONFIG_PATH) -> ReadinessThresholds:
    """Read the versioned thresholds; any missing or invalid entry raises ``ValueError`` (the gate never guesses a threshold)."""

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"data readiness thresholds cannot be read: {path} ({type(exc).__name__})") from exc
    if not isinstance(raw, dict):
        raise ValueError("data readiness thresholds must be a mapping")

    def number(key: str, *, integer: bool, low: float, high: float | None = None) -> Any:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"data readiness threshold {key} must be a finite number")
        if integer and float(value) != int(value):
            raise ValueError(f"data readiness threshold {key} must be an integer")
        if value < low or (high is not None and value > high):
            raise ValueError(f"data readiness threshold {key} is out of range")
        return int(value) if integer else float(value)

    def names(key: str) -> frozenset[str]:
        value = raw.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"data readiness threshold {key} must be a non-empty list of names")
        return frozenset(item.strip().casefold() for item in value)

    column = raw.get("gate_results_column")
    if not isinstance(column, str) or not column.strip():
        raise ValueError("data readiness threshold gate_results_column must be a column name")
    if raw.get("execution_allowed") is not False:
        raise ValueError("data readiness policy must keep execution_allowed false")
    return ReadinessThresholds(
        policy_version=str(raw.get("policy_version") or ""),
        decision_cadence_sessions=number("decision_cadence_sessions", integer=True, low=1),
        min_scoreable_stocks=number("min_scoreable_stocks", integer=True, low=1),
        min_scoreable_etfs=number("min_scoreable_etfs", integer=True, low=1),
        stock_count_asset_types=names("stock_count_asset_types"),
        etf_count_asset_types=names("etf_count_asset_types"),
        min_family_complete_share=number("min_family_complete_share", integer=False, low=0.0001, high=1.0),
        stock_like_asset_types=names("stock_like_asset_types"),
        etf_policy_asset_types=names("etf_policy_asset_types"),
        fresh_statuses=names("fresh_statuses"),
        min_price_coverage_share=number("min_price_coverage_share", integer=False, low=0.0001, high=1.0),
        max_stale_business_days=number("max_stale_business_days", integer=True, low=0),
        max_gate_wiring_failures=number("max_gate_wiring_failures", integer=True, low=0),
        gate_results_column=column.strip(),
        max_gap_ids_listed=number("max_gap_ids_listed", integer=True, low=0),
    )


@dataclass
class ReadinessInputs:
    """The stored inputs (read-only). ``unavailable`` maps an input name to why it could not be read."""

    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    eligibility: pd.DataFrame = field(default_factory=pd.DataFrame)
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    fx: pd.DataFrame = field(default_factory=pd.DataFrame)
    membership: ListingHistory | None = None
    unavailable: dict[str, str] = field(default_factory=dict)
    manifest: dict[str, object] = field(default_factory=dict)


def load_inputs(root: Path) -> ReadinessInputs:
    """Read the existing stores under ``root`` through the existing loaders. Nothing is created or written."""

    root = Path(root)
    inputs = ReadinessInputs()

    def attempt(name: str, loader) -> Any:
        try:
            return loader()
        except Exception as exc:  # fail closed: the reason is reported, the input stays unavailable
            inputs.unavailable[name] = f"{type(exc).__name__}: {str(exc)[:160]}"
            return None

    history = attempt("history", lambda: load_backfill_score_history(root))
    inputs.history = history if history is not None else pd.DataFrame()
    eligibility = attempt("eligibility", lambda: load_backfill_eligibility(root))
    inputs.eligibility = eligibility if eligibility is not None else pd.DataFrame()
    inputs.manifest = attempt("manifest", lambda: load_backfill_manifest(root)) or {}
    prices = attempt("prices", lambda: load_prices(root / PRICES_RELATIVE_PATH))
    inputs.prices = prices if prices is not None else pd.DataFrame()
    fx_path = root / FX_RELATIVE_PATH
    fx = attempt("fx", lambda: load_fx_rates(fx_path) if fx_path.is_file() else pd.DataFrame())
    inputs.fx = fx if fx is not None else pd.DataFrame()
    membership_path = root / "data" / "derived" / "universe_membership" / "membership.sqlite"
    if membership_path.is_file():
        inputs.membership = attempt("membership", lambda: ListingHistory.from_root(root))
    else:
        inputs.unavailable["membership"] = f"listing membership store is missing: {membership_path.as_posix()}"
    return inputs


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    detail: str
    gaps: dict[str, tuple[str, ...]] = field(default_factory=dict)  # gap label -> instrument ids (capped) ; counts in ``counts``
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DateReport:
    day: str
    checks: dict[str, CheckResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.checks.values())


@dataclass(frozen=True)
class ReadinessReport:
    start: str
    end: str
    policy_version: str
    every: int
    dates: tuple[DateReport, ...]
    interval: dict[str, CheckResult]
    caveats: tuple[str, ...] = CAVEATS
    execution_allowed: bool = False

    @property
    def passed(self) -> bool:
        return bool(self.dates) and all(item.passed for item in self.dates) and all(item.passed for item in self.interval.values())

    def failed_dates(self) -> list[str]:
        return [item.day for item in self.dates if not item.passed]

    def summary(self) -> dict[str, object]:
        failed_by_check = {name: sum(1 for item in self.dates if not item.checks[name].passed) for name in CHECKS}
        family_gaps: dict[str, int] = {}
        for item in self.dates:
            for family, count in item.checks["family_completeness"].counts.items():
                if family.startswith("missing:"):
                    family_gaps[family[8:]] = family_gaps.get(family[8:], 0) + count
        return {
            "status": "PASS" if self.passed else "FAIL",
            "policy_version": self.policy_version,
            "start": self.start,
            "end": self.end,
            "every_sessions": self.every,
            "decision_dates": len(self.dates),
            "dates_passed": len(self.dates) - len(self.failed_dates()),
            "dates_failed": len(self.failed_dates()),
            "failed_by_check": failed_by_check,
            "interval_checks": {name: {"passed": result.passed, "detail": result.detail} for name, result in self.interval.items()},
            "family_gap_instrument_dates": dict(sorted(family_gaps.items())),
            "failed_dates": self.failed_dates(),
            "caveats": list(self.caveats),
            "execution_allowed": False,
        }

    def format_text(self) -> str:
        lines = [
            f"DATA READINESS {self.start}..{self.end} policy={self.policy_version} every={self.every} sessions "
            f"decision_dates={len(self.dates)} -> {'PASS' if self.passed else 'FAIL'}"
        ]
        for name, result in self.interval.items():
            lines.append(f"  interval {name}: {'ok' if result.passed else 'FAIL'} - {result.detail}")
        for item in self.dates:
            if item.passed:
                lines.append(f"{item.day} PASS")
                continue
            if not item.checks["scored_run"].passed:  # every other check depends on it: one line, not seven
                lines.append(f"{item.day} FAIL scored_run: {item.checks['scored_run'].detail} (all other checks unavailable)")
                continue
            lines.append(f"{item.day} FAIL " + "; ".join(f"{name}: {result.detail}" for name, result in item.checks.items() if not result.passed))
            for name, result in item.checks.items():
                for label, ids in result.gaps.items():
                    if result.passed:
                        continue
                    shown = ", ".join(ids)
                    lines.append(f"    {name}/{label}: {result.counts.get(label, len(ids))}" + (f" [{shown}]" if shown else ""))
        lines.extend(f"note: {text}" for text in self.caveats)
        return "\n".join(lines)


def evaluate_readiness(
    inputs: ReadinessInputs,
    start: date,
    end: date,
    thresholds: ReadinessThresholds,
    *,
    every: int | None = None,
) -> ReadinessReport:
    """Check every decision date in ``[start, end]``. Decision dates are the benchmark-calendar sessions at the chosen cadence."""

    if end < start:
        raise ValueError("end must not be before start")
    cadence = thresholds.decision_cadence_sessions if every is None else int(every)
    if cadence < 1:
        raise ValueError("every must be at least 1 session")
    context = _Context(inputs, thresholds)
    days = context.schedule(start, end)[::cadence] if context.prices_usable else []
    dates = tuple(_evaluate_date(day, context) for day in days)
    interval = {
        "decision_dates": _decision_dates_check(days, context, start, end),
        "benchmark_sessions": _benchmark_sessions_check(context, start, end),
    }
    return ReadinessReport(start.isoformat(), end.isoformat(), thresholds.policy_version, cadence, dates, interval)


def paper_bot_readiness_failure(root: Path | None, start: date, end: date) -> str | None:
    """Return the canonical readiness report when a paper-bot interval is blocked."""

    try:
        report = evaluate_readiness(
            load_inputs(Path(root or ROOT)), start, end, load_thresholds()
        )
    except Exception as exc:
        return f"DATA READINESS {start.isoformat()}..{end.isoformat()} -> FAIL\n  gate unavailable: {type(exc).__name__}: {str(exc)[:160]}"
    if report.passed:
        return None
    failures = {
        name for name, result in report.interval.items() if not result.passed
    }
    families: set[str] = set()
    for item in report.dates:
        for name, result in item.checks.items():
            if not result.passed:
                failures.add(name)
            if name == "family_completeness":
                families.update(
                    label.removeprefix("missing:")
                    for label, count in result.counts.items()
                    if label.startswith("missing:") and count
                )
    labels = sorted(failures | families)
    return report.format_text() + "\nfailing checks/families: " + (", ".join(labels) or "unknown")


class _Context:
    """Per-run lookups built once (one pass over each store), shared by every date."""

    def __init__(self, inputs: ReadinessInputs, thresholds: ReadinessThresholds) -> None:
        self.inputs = inputs
        self.thresholds = thresholds
        self.prices = _clean_prices(inputs.prices)
        self.price_column = _price_column(self.prices)
        self.prices_usable = not self.prices.empty and self.price_column is not None
        if self.prices_usable:
            self.prices = self.prices.assign(__usable=_usable_prices(self.prices[self.price_column]))
        self.usable = self.prices.loc[self.prices["__usable"]] if self.prices_usable else self.prices
        self.history = _by_day(inputs.history)
        self.eligibility = _by_day(inputs.eligibility)
        self.price_dates: dict[str, np.ndarray] = {}
        # instrument -> (sorted unique dates, currencies quoted on each date): currency is resolved as of each decision date.
        self.currency_rows: dict[str, tuple[np.ndarray, list[frozenset[str]]]] = {}
        if self.prices_usable:
            for instrument, group in self.usable.groupby("etf_id", sort=False):
                self.price_dates[str(instrument)] = np.unique(np.array(group["date"].tolist(), dtype="datetime64[D]"))
            if "currency" in self.prices.columns:
                quoted = self.prices.dropna(subset=["currency"])
                for instrument, group in quoted.groupby("etf_id", sort=False):
                    by_day: dict[Any, set[str]] = {}
                    for day, value in zip(group["date"], group["currency"]):
                        if str(value).strip():
                            by_day.setdefault(day, set()).add(str(value).strip())
                    ordered = sorted(by_day)
                    self.currency_rows[str(instrument)] = (np.array(ordered, dtype="datetime64[D]"), [frozenset(by_day[day]) for day in ordered])
        self.weighted: dict[str, tuple[str, ...]] = {}
        self.weight_error: str | None = None
        try:
            for policy in ("ETF", "STOCK"):
                self.weighted[policy] = tuple(sorted(key for key, value in headline_evidence_weights(policy).items() if value > 0))
        except Exception as exc:  # the score policy must be readable; never assume which families carry weight
            self.weight_error = f"headline weights unavailable ({type(exc).__name__})"

    def currency_at(self, key: str, day: date) -> str | None:
        """The quote currency on the latest row dated on or before ``day``; rows after ``day`` are never used, a conflict is unknown."""

        entry = self.currency_rows.get(key)
        if entry is None:
            return None
        position = int(np.searchsorted(entry[0], np.datetime64(day, "D"), side="right"))
        if position == 0 or len(entry[1][position - 1]) != 1:
            return None
        return next(iter(entry[1][position - 1]))

    def schedule(self, start: date, end: date) -> list[date]:
        """Expected sessions in ``[start, end]``, independent of benchmark rows: a date quoted by a strict majority of the
        instruments, or by the benchmark. A session whose benchmark row is missing therefore stays scheduled (and fails)."""

        window = self.prices.loc[(self.prices["date"] >= start) & (self.prices["date"] <= end)]
        if window.empty:
            return []
        total = window["etf_id"].nunique()
        per_day = window.groupby("date")["etf_id"].nunique()
        benchmark = set(window.loc[window["etf_id"].eq(CALENDAR_INSTRUMENT_ID), "date"])
        return sorted(day for day, count in per_day.items() if count * 2 > total or day in benchmark)

    def reason(self, name: str, default: str) -> str:
        reason = self.inputs.unavailable.get(name)
        return f"unavailable: {reason}" if reason else default


def _clean_prices(prices: pd.DataFrame) -> pd.DataFrame:
    if prices is None or prices.empty or not {"etf_id", "date"}.issubset(prices.columns):
        return pd.DataFrame()
    frame = prices
    if "source" in frame.columns:
        frame = frame.loc[~frame["source"].astype(str).isin(SYNTHETIC_PRICE_SOURCES)]
    frame = frame.assign(date=pd.to_datetime(frame["date"], errors="coerce").dt.date).dropna(subset=["date"])
    frame = frame.assign(etf_id=frame["etf_id"].astype(str))
    return frame.reset_index(drop=True)


def _price_column(prices: pd.DataFrame) -> str | None:
    """The price the scores use: ``adjusted_close`` when stored, else ``close``; none stored means prices are unavailable."""

    for name in ("adjusted_close", "close"):
        if name in prices.columns:
            return name
    return None


def _usable_prices(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.notna() & np.isfinite(numeric.fillna(0.0)) & numeric.gt(0)


def _by_day(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if frame is None or frame.empty or "as_of_date" not in frame.columns:
        return {}
    return {str(day): group for day, group in frame.groupby(frame["as_of_date"].astype(str), sort=False)}


def _result(passed: bool, detail: str, gaps: Mapping[str, Sequence[str]] | None = None, counts: Mapping[str, int] | None = None, *, cap: int = 10) -> CheckResult:
    shown = {label: tuple(sorted(map(str, ids)))[:cap] for label, ids in (gaps or {}).items()}
    sized = {label: len(tuple(ids)) for label, ids in (gaps or {}).items()}
    return CheckResult(passed, detail, shown, {**sized, **dict(counts or {})})


def _fail(detail: str) -> CheckResult:
    return CheckResult(False, detail)


def _evaluate_date(day: date, context: _Context) -> DateReport:
    iso = day.isoformat()
    run = context.history.get(iso)
    log = context.eligibility.get(iso)
    checks: dict[str, CheckResult] = {}
    if run is None or run.empty:
        checks["scored_run"] = _fail(context.reason("history", "no stored score run for this decision date"))
    elif log is None or log.empty:
        checks["scored_run"] = _fail(context.reason("eligibility", "no eligibility log rows for this decision date"))
    else:
        checks["scored_run"] = CheckResult(True, f"{len(run)} scored rows")
    admitted: list[str] = []
    if log is not None and not log.empty and {"instrument_id", "eligible"}.issubset(log.columns):
        admitted = sorted(set(log.loc[log["eligible"].eq(True), "instrument_id"].astype(str)))
    if not checks["scored_run"].passed or not admitted:
        reason = checks["scored_run"].detail if not checks["scored_run"].passed else "no admitted instrument at this date"
        reason = reason.removeprefix("unavailable: ")
        for name in CHECKS[1:]:
            checks[name] = _fail(f"unavailable: {reason}")
        return DateReport(iso, checks)
    cap = context.thresholds.max_gap_ids_listed
    checks["pit_membership"] = _membership_check(day, admitted, log, context, cap)
    checks["universe_counts"] = _counts_check(run, admitted, context.thresholds)
    checks["family_completeness"] = _family_check(run, admitted, context, cap)
    checks["prices"] = _price_check(day, admitted, context, cap)
    checks["fx"] = _fx_check(day, admitted, context, cap)
    checks["gate_results"] = _gate_check(run, context.thresholds, cap)
    return DateReport(iso, {name: checks[name] for name in CHECKS})


def _membership_check(day: date, admitted: list[str], log: pd.DataFrame, context: _Context, cap: int) -> CheckResult:
    membership = context.inputs.membership
    if membership is None:
        return _fail(context.reason("membership", "unavailable: no point-in-time listing history"))
    if "membership_status" not in log.columns:
        return _fail("unavailable: eligibility log has no membership_status")
    status = dict(zip(log["instrument_id"].astype(str), log["membership_status"].astype(str)))
    logged = [key for key in admitted if status.get(key) != "listed"]
    try:
        snapshot = membership.snapshot(day, admitted)
    except Exception as exc:
        return _fail(f"unavailable: listing membership cannot be evaluated ({type(exc).__name__})")
    unverified = set(snapshot.unverified_ids) | set(snapshot.delisting_unverified_ids)
    recomputed = [key for key in admitted if key not in snapshot.eligible_ids or key in unverified]
    bad = sorted(set(logged) | set(recomputed))
    if bad:
        return _result(False, f"{len(bad)} of {len(admitted)} admitted instruments lack verified membership", {"unverified": bad}, cap=cap)
    return CheckResult(True, f"{len(admitted)} admitted instruments verified")


def _counts_check(run: pd.DataFrame, admitted: list[str], thresholds: ReadinessThresholds) -> CheckResult:
    if not {"instrument_id", "asset_type", "final_combined_score_10"}.issubset(run.columns):
        return _fail("unavailable: score rows lack instrument_id, asset_type or final_combined_score_10")
    rows = run.loc[run["instrument_id"].astype(str).isin(admitted), ["instrument_id", "asset_type", "final_combined_score_10"]].copy()
    rows["instrument_id"] = rows["instrument_id"].astype(str)
    score = pd.to_numeric(rows["final_combined_score_10"], errors="coerce").astype(float)
    rows["score"] = score.where(np.isfinite(score))
    rows["kind"] = rows["asset_type"].astype(str).str.strip().str.casefold()
    # One instrument is one row: exact duplicates collapse, conflicting duplicates are rejected (never counted).
    distinct = rows.groupby("instrument_id").agg(
        n_kind=("kind", "nunique"), n_score=("score", lambda s: s.dropna().nunique()), n_null=("score", lambda s: int(s.isna().sum())), n=("score", "size")
    )
    conflicting = distinct.index[(distinct["n_kind"] > 1) | (distinct["n_score"] > 1) | ((distinct["n_null"] > 0) & (distinct["n_null"] < distinct["n"]))]
    scoreable = rows.loc[rows["score"].notna() & ~rows["instrument_id"].isin(conflicting)].drop_duplicates("instrument_id")
    kind = scoreable["kind"]
    stocks = int(kind.isin(thresholds.stock_count_asset_types).sum())
    etfs = int(kind.isin(thresholds.etf_count_asset_types).sum())
    problems = []
    if stocks < thresholds.min_scoreable_stocks:
        problems.append(f"stocks {stocks}<{thresholds.min_scoreable_stocks}")
    if etfs < thresholds.min_scoreable_etfs:
        problems.append(f"etfs {etfs}<{thresholds.min_scoreable_etfs}")
    counts = {"scoreable_stocks": stocks, "scoreable_etfs": etfs}
    if len(conflicting):
        problems.append(f"{len(conflicting)} instruments with conflicting duplicate score rows")
    if problems:
        return CheckResult(False, "; ".join(problems), counts=counts)
    return CheckResult(True, f"stocks {stocks}, etfs {etfs}", counts=counts)


def _family_check(run: pd.DataFrame, admitted: list[str], context: _Context, cap: int) -> CheckResult:
    thresholds = context.thresholds
    if context.weight_error:
        return _fail(f"unavailable: {context.weight_error}")
    needed = {"instrument_id", "asset_type", "freshness_status", "pit_terms_unavailable", "missing_components"}
    if not needed.issubset(run.columns):
        return _fail(f"unavailable: score rows lack {', '.join(sorted(needed - set(run.columns)))}")
    unique = run.drop_duplicates("instrument_id", keep="first")
    rows = unique.set_index(unique["instrument_id"].astype(str))
    missing_by_family: dict[str, list[str]] = {}
    not_fresh: list[str] = []
    unclassified: list[str] = []
    not_scored: list[str] = []
    unavailable_metadata: list[str] = []
    complete = 0
    for key in admitted:
        if key not in rows.index:
            not_scored.append(key)
            continue
        row = rows.loc[key]
        kind = str(row["asset_type"]).strip().casefold()
        policy = "STOCK" if kind in thresholds.stock_like_asset_types else "ETF" if kind in thresholds.etf_policy_asset_types else None
        if policy is None:
            unclassified.append(key)
            continue
        fields = [row[column] for column in ("pit_terms_unavailable", "missing_components")]
        if not all(isinstance(value, str) for value in fields) or not isinstance(row["freshness_status"], str):
            unavailable_metadata.append(key)  # null or malformed availability metadata is unavailable, never apparent completeness
            continue
        absent = {part for value in fields for part in value.split("|") if part.strip()}
        missing = [family for family in context.weighted[policy] if family in absent]
        for family in missing:
            missing_by_family.setdefault(f"missing:{family}", []).append(key)
        fresh = str(row["freshness_status"]).strip().casefold() in thresholds.fresh_statuses
        if not fresh:
            not_fresh.append(key)
        if not missing and fresh:
            complete += 1
    share = complete / len(admitted)
    gaps: dict[str, list[str]] = dict(missing_by_family)
    for label, ids in (("not_fresh", not_fresh), ("unclassified_asset_type", unclassified), ("not_scored", not_scored), ("metadata_unavailable", unavailable_metadata)):
        if ids:
            gaps[label] = ids
    detail = f"{complete}/{len(admitted)} admitted complete and fresh ({share:.1%}, need {thresholds.min_family_complete_share:.0%})"
    return _result(share >= thresholds.min_family_complete_share, detail, gaps, {"complete": complete, "admitted": len(admitted)}, cap=cap)


def _price_check(day: date, admitted: list[str], context: _Context, cap: int) -> CheckResult:
    if not context.prices_usable:
        return _fail(context.reason("prices", "unavailable: no stored prices"))
    target = np.datetime64(day, "D")
    stale = context.thresholds.max_stale_business_days
    lacking: list[str] = []
    for key in admitted:
        series = context.price_dates.get(key)
        position = 0 if series is None else int(np.searchsorted(series, target, side="right"))  # rows dated after the day are never used
        if position == 0 or int(np.busday_count(series[position - 1], target)) > stale:
            lacking.append(key)
    share = 1.0 - len(lacking) / len(admitted)
    detail = f"{len(admitted) - len(lacking)}/{len(admitted)} admitted instruments priced ({share:.1%}, need {context.thresholds.min_price_coverage_share:.0%})"
    return _result(share >= context.thresholds.min_price_coverage_share, detail, {"no_recent_price": lacking} if lacking else {}, cap=cap)


def _fx_check(day: date, admitted: list[str], context: _Context, cap: int) -> CheckResult:
    foreign: dict[str, list[str]] = {}
    unknown: list[str] = []
    for key in admitted:
        currency = context.currency_at(key, day)
        major = major_currency(currency) if currency else None
        if major is None:
            unknown.append(key)
        elif major != "EUR":
            foreign.setdefault(major, []).append(key)
    gaps: dict[str, list[str]] = {}
    if unknown:
        gaps["currency_unknown"] = unknown
    if foreign:
        book = EurRateBook(context.inputs.fx if not context.inputs.fx.empty else None, known_by=datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc))
        for currency, members in sorted(foreign.items()):
            rate = book.series(currency, [day])
            value = rate.rates.iloc[0]
            if not (pd.notna(value) and float(value) > 0):
                reason = str(rate.reasons.iloc[0] or "rate unavailable")[:100]
                gaps[f"{currency}_to_EUR ({reason})"] = members
    if gaps:
        return _result(False, f"FX unavailable for {len([k for k in gaps if k != 'currency_unknown'])} currencies" + ("; currency unknown for some instruments" if unknown else ""), gaps, cap=cap)
    return CheckResult(True, f"{len(foreign)} foreign currencies available" if foreign else "no foreign currency needed")


def _gate_check(run: pd.DataFrame, thresholds: ReadinessThresholds, cap: int) -> CheckResult:
    column = thresholds.gate_results_column
    if column not in run.columns:
        return _fail(f"unavailable: score rows have no {column} column (per-gate results are not stored)")
    failing = [str(key) for key, value in zip(run["instrument_id"], run[column]) if not _gates_well_formed(value)]
    if len(failing) > thresholds.max_gate_wiring_failures:
        return _result(False, f"{len(failing)} of {len(run)} scored rows store no valid per-gate results", {"gate_wiring": failing}, cap=cap)
    return CheckResult(True, f"{len(run)} rows with per-gate results")


def _gates_well_formed(value: object) -> bool:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return False
    if isinstance(parsed, np.ndarray):
        parsed = parsed.tolist()
    if not isinstance(parsed, list) or not parsed:
        return False
    return all(
        isinstance(item, Mapping) and str(item.get("gate_id") or "").strip() and isinstance(item.get("passed"), bool)
        and "severity" in item and "reason" in item
        for item in parsed
    )


def _decision_dates_check(days: list[date], context: _Context, start: date, end: date) -> CheckResult:
    if not days:
        reason = context.reason("prices", f"no {CALENDAR_INSTRUMENT_ID} benchmark session between {start} and {end}")
        return _fail(reason)
    if not context.prices_usable:
        return _fail(context.reason("prices", "unavailable: no stored prices"))
    benchmark = set(context.usable.loc[context.usable["etf_id"].eq(CALENDAR_INSTRUMENT_ID), "date"])
    missing = [day.isoformat() for day in days if day not in benchmark]
    if missing:
        return _fail(f"{len(missing)} scheduled decision dates have no usable {CALENDAR_INSTRUMENT_ID} price (e.g. {', '.join(missing[:3])})")
    return CheckResult(True, f"{len(days)} decision dates")


def _benchmark_sessions_check(context: _Context, start: date, end: date) -> CheckResult:
    if not context.prices_usable:
        return _fail(context.reason("prices", "unavailable: no stored prices"))
    sessions = set(context.schedule(start, end))
    window = context.usable.loc[(context.usable["date"] >= start) & (context.usable["date"] <= end)]
    benchmark = set(window.loc[window["etf_id"].eq(CALENDAR_INSTRUMENT_ID), "date"]) & sessions
    if not sessions:
        return _fail("unavailable: no price session in the interval")
    share = len(benchmark) / len(sessions)
    need = context.thresholds.min_price_coverage_share
    detail = f"{CALENDAR_INSTRUMENT_ID} priced on {len(benchmark)}/{len(sessions)} sessions ({share:.2%}, need {need:.0%})"
    return CheckResult(share >= need, detail, counts={"sessions": len(sessions), "benchmark_sessions": len(benchmark)})


__all__ = [
    "CAVEATS",
    "CHECKS",
    "CONFIG_PATH",
    "CheckResult",
    "DateReport",
    "ReadinessInputs",
    "ReadinessReport",
    "ReadinessThresholds",
    "evaluate_readiness",
    "load_inputs",
    "load_thresholds",
    "paper_bot_readiness_failure",
]
