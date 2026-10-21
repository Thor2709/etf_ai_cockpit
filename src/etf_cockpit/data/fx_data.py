from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
import shutil
import sys
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR, SNAPSHOTS_DIR
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.types import DatasetMetadata
from etf_cockpit.data.import_pipeline import _snapshot_existing_clean, _source_path
from etf_cockpit.data.provenance import metadata_from_frame, price_staleness_status, sha256_dataframe
from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.validation import _business_days_between
from etf_cockpit.data.reference_data import _first_present, _metadata_to_json

FX_CLEAN_PATH = CLEAN_DIR / "fx.parquet"
DATE_COLUMNS = ("as_of_date", "date", "rate_date")
RATE_COLUMNS = ("rate", "fx_rate", "exchange_rate", "mid")
FX_RATE_CONSISTENCY_TOLERANCE = 1e-6

# Stored prices are already in major units (the provider scales pence once), so a minor-unit label
# only names the major currency and must never trigger a second /100.
MINOR_UNIT_MAJOR_CURRENCY = {"GBp": "GBP", "GBX": "GBP", "ILA": "ILS", "ZAc": "ZAR"}

# Calendar look-back covered by an FX identity: the ok staleness band (3 business days) plus weekends/holidays.
_FX_LOOKBACK_CALENDAR_DAYS = 10


@dataclass(frozen=True)
class FxValidation:
    frame: pd.DataFrame
    errors: list[str]
    warnings: list[str]
    metadata: DatasetMetadata | None

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class FxImportCommit:
    raw_path: Path
    clean_path: Path
    previous_snapshot_path: Path | None
    metadata_path: Path
    rows: int
    checksum: str
    warnings: list[str]
    metadata: DatasetMetadata


@dataclass(frozen=True)
class FxRate:
    base_currency: str
    quote_currency: str
    rate: float
    source: str


@dataclass(frozen=True)
class FxRateSnapshot:
    decision_date: date | None
    as_of_date: date | None
    rates: tuple[FxRate, ...]
    source_snapshot: str | None
    age_business_days: int | None
    staleness_status: str
    available: bool
    reason: str | None


@dataclass(frozen=True)
class FxRateLeg:
    from_currency: str
    to_currency: str
    observed_pair: str
    observed_rate: float
    applied_rate: float
    inverted: bool
    source: str


@dataclass(frozen=True)
class FxCrossRate:
    base_currency: str
    quote_currency: str
    rate: float
    as_of_date: date | None
    source_snapshot: str | None
    legs: tuple[FxRateLeg, ...]
    label: str
    execution_allowed: Literal[False] = False


def validate_fx_rates(
    frame: pd.DataFrame,
    *,
    source_name: str = "fx_rates",
    provider_or_manual_source: str = "manual",
    ingested_at: datetime | None = None,
    today: date | None = None,
) -> FxValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if frame.empty:
        return FxValidation(_empty_fx_frame(), ["FX import contains no rows."], [], None)

    date_column = _first_present(frame, DATE_COLUMNS)
    rate_column = _first_present(frame, RATE_COLUMNS)
    if date_column is None:
        errors.append(f"FX rates require one dated column: {', '.join(DATE_COLUMNS)}.")
    if rate_column is None:
        errors.append(f"FX rates require one rate column: {', '.join(RATE_COLUMNS)}.")
    if "pair" not in frame.columns and not {"base_currency", "quote_currency"}.issubset(frame.columns):
        errors.append("FX rates require either a pair column or base_currency and quote_currency columns.")
    if errors:
        return FxValidation(_empty_fx_frame(), errors, warnings, None)

    parsed_dates = pd.to_datetime(frame[date_column], errors="coerce", utc=False)
    if parsed_dates.isna().any():
        errors.append("FX rates contain invalid or missing as_of_date values.")
    parsed_ingested_at: pd.Series | None = None
    if "ingested_at" in frame.columns:
        # Each row keeps its own ingestion time; batch metadata never overwrites it.
        parsed_ingested_at = pd.to_datetime(frame["ingested_at"], errors="coerce", utc=True)
    elif ingested_at is not None:
        parsed_ingested_at = pd.to_datetime(pd.Series([ingested_at] * len(frame), index=frame.index), errors="coerce", utc=True)
    if parsed_ingested_at is not None and parsed_ingested_at.isna().any():
        errors.append("FX rates contain invalid or missing ingested_at values.")
    if frame[rate_column].map(lambda value: isinstance(value, (bool, np.bool_))).any():
        errors.append("FX rates must be numeric values, not booleans.")
    rates = pd.to_numeric(frame[rate_column], errors="coerce")
    if not rates.map(math.isfinite).all() or (rates <= 0).any():
        errors.append("FX rates must be finite numeric values greater than zero.")
    elif not rates.map(_usable_rate).all():
        errors.append("FX rates must be above the subnormal guard and have a finite inverse.")
    currencies = _parse_currency_pairs(frame)
    errors.extend(currencies.errors)
    warnings.extend(currencies.warnings)
    if errors:
        return FxValidation(_empty_fx_frame(), errors, warnings, None)

    normalised = pd.DataFrame()
    normalised["as_of_date"] = parsed_dates.dt.date
    normalised["base_currency"] = currencies.base_currency
    normalised["quote_currency"] = currencies.quote_currency
    normalised["pair"] = normalised["base_currency"] + "/" + normalised["quote_currency"]
    normalised["rate"] = rates.astype(float)
    normalised["source"] = _column_or_default(frame, "source", "manual_import")
    if parsed_ingested_at is not None:
        normalised["ingested_at"] = parsed_ingested_at
    duplicates = normalised.duplicated(["as_of_date", "pair"])
    if duplicates.any():
        errors.append("FX rates contain duplicate date/pair rows.")
    errors.extend(_fx_rate_consistency_errors(normalised))
    if errors:
        return FxValidation(_empty_fx_frame(), errors, warnings, None)

    latest = max(normalised["as_of_date"])
    reference_date = today or (ingested_at.date() if ingested_at is not None else date.today())
    if latest > reference_date:
        errors.append("FX rates contain future-dated quotes.")
        return FxValidation(_empty_fx_frame(), errors, warnings, None)
    age_days = _business_days_between(latest, reference_date)
    staleness = price_staleness_status(age_days)
    normalised["staleness_status"] = staleness
    metadata = metadata_from_frame(
        normalised,
        source_name=source_name,
        source_type="fx",
        as_of_date=latest,
        currency="mixed",
        provider_or_manual_source=provider_or_manual_source,
        staleness_status=staleness,
        age_days=age_days,
        notes="FX rates are explicit and dated; OK <= 3 business days, warning 4-10, block > 10.",
    )
    return FxValidation(normalised, errors, warnings, metadata)


def commit_fx_import(
    result: ProviderResult,
    *,
    clean_path: Path = FX_CLEAN_PATH,
    raw_dir: Path = RAW_DIR / "fx",
    snapshots_dir: Path = SNAPSHOTS_DIR / "fx",
) -> FxImportCommit:
    if not result.ok or result.data is None:
        raise ValueError("Cannot commit a provider result that did not load FX rates.")
    validation = validate_fx_rates(
        result.data,
        source_name=result.metadata.source_name if result.metadata else "fx_rates",
        provider_or_manual_source=result.metadata.provider_or_manual_source if result.metadata else "manual",
        ingested_at=(result.metadata.ingested_at if result.metadata and result.metadata.ingested_at else datetime.now(timezone.utc)),
    )
    if not validation.ok or validation.metadata is None:
        raise ValueError("; ".join(validation.errors))

    frame = validation.frame
    checksum = sha256_dataframe(frame)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    raw_path = _store_raw_fx_import(result, frame, raw_dir, timestamp, checksum)
    previous_snapshot_path = _snapshot_existing_clean(clean_path, snapshots_dir, timestamp)
    metadata_path = snapshots_dir / f"{timestamp}_{checksum[:12]}_fx_metadata.json"
    metadata_payload = json.dumps(
        {
            "dataset_type": "fx",
            "provider_name": result.provider_name,
            "message": result.message,
            "rows": len(frame),
            "checksum": checksum,
            "raw_path": str(raw_path),
            "clean_path": str(clean_path),
            "previous_snapshot_path": str(previous_snapshot_path) if previous_snapshot_path else None,
            "warnings": validation.warnings,
            "metadata": _metadata_to_json(validation.metadata),
        },
        indent=2,
    ).encode("utf-8")
    atomic_write_group(
        (
            AtomicWriteRequest(clean_path, parquet_payload(frame), validate_parquet_file),
            AtomicWriteRequest(metadata_path, metadata_payload, lambda path: json.loads(path.read_text(encoding="utf-8"))),
        )
    )
    return FxImportCommit(raw_path, clean_path, previous_snapshot_path, metadata_path, len(frame), checksum, validation.warnings, validation.metadata)


def load_fx_rates(path: Path = FX_CLEAN_PATH) -> pd.DataFrame:
    if not path.exists():
        return _empty_fx_frame()
    return pd.read_parquet(path)


def build_fx_rate_snapshot(
    frame: pd.DataFrame,
    *,
    decision_time: date | datetime | str | None,
    known_at: date | datetime | str | None = None,
) -> FxRateSnapshot:
    """Select a same-date, point-in-time FX snapshot or return an unavailable one."""

    decision_date, _, _ = _decision_cutoff(decision_time)
    if decision_date is None:
        return FxRateSnapshot(None, None, (), None, None, "block", False, "Analysis decision time is missing or invalid.")
    known_date, cutoff, date_only = _decision_cutoff(decision_time if known_at is None else known_at)
    if known_date is None or (cutoff is None and not date_only):
        return FxRateSnapshot(decision_date, None, (), None, None, "block", False, "FX knowledge cutoff is missing or invalid.")
    if frame.empty:
        return FxRateSnapshot(decision_date, None, (), None, None, "missing", False, "FX rates are missing.")

    date_column = _first_present(frame, DATE_COLUMNS)
    if date_column is None:
        return FxRateSnapshot(decision_date, None, (), None, None, "missing", False, "FX rates have no quote date.")
    if "ingested_at" not in frame.columns:
        return FxRateSnapshot(
            decision_date,
            None,
            (),
            None,
            None,
            "unknown",
            False,
            "FX rates have no ingested_at timestamp; point-in-time availability cannot be verified.",
        )

    quote_dates = pd.to_datetime(frame[date_column], errors="coerce", utc=False)
    ingested = pd.to_datetime(frame["ingested_at"], errors="coerce", utc=True)
    if quote_dates.isna().any():
        return FxRateSnapshot(decision_date, None, (), None, None, "unknown", False, "FX rates contain a missing or invalid quote date.")
    if ingested.isna().any():
        return FxRateSnapshot(decision_date, None, (), None, None, "unknown", False, "FX rates contain a missing or invalid ingested_at timestamp.")

    quote_days = quote_dates.dt.date
    known_by_decision = ingested.dt.date.lt(known_date) if date_only else ingested.le(cutoff)
    eligible = quote_days.le(decision_date) & known_by_decision
    if not bool(eligible.any()):
        return FxRateSnapshot(
            decision_date,
            None,
            (),
            None,
            None,
            "missing",
            False,
            "No FX snapshot was known by the analysis decision time.",
        )

    latest = max(quote_days[eligible])
    latest_rows = frame.loc[eligible & quote_days.eq(latest)].copy()
    validation = validate_fx_rates(latest_rows, today=decision_date)
    if not validation.ok or validation.metadata is None:
        reason = "; ".join(validation.errors) or "FX snapshot metadata is unavailable."
        return FxRateSnapshot(decision_date, latest, (), None, None, "block", False, reason)

    normalised = validation.frame.sort_values(["pair", "source"], kind="stable").reset_index(drop=True)
    age = _business_days_between(latest, decision_date)
    staleness = price_staleness_status(age)
    rates = tuple(
        FxRate(
            base_currency=str(row.base_currency),
            quote_currency=str(row.quote_currency),
            rate=float(row.rate),
            source=str(row.source),
        )
        for row in normalised.itertuples(index=False)
    )
    checksum = sha256_dataframe(normalised)
    if staleness == "ok":
        reason = None
    else:
        freshness = "stale" if staleness == "block" else "not fresh"
        reason = f"FX snapshot is {freshness} ({staleness}; {age} business days old); conversion is unavailable."
    return FxRateSnapshot(decision_date, latest, rates, checksum, age, staleness, staleness == "ok", reason)


def fx_cross_rate(
    snapshot: FxRateSnapshot,
    base_currency: str,
    quote_currency: str,
    *,
    tolerance: float = FX_RATE_CONSISTENCY_TOLERANCE,
) -> FxCrossRate | None:
    """Derive a rate while recording every direct or reciprocal quote leg."""

    base = _normalise_currency(base_currency)
    quote = _normalise_currency(quote_currency)
    if base is None or quote is None:
        raise ValueError("FX conversion requires three-letter currency codes.")
    if base == quote:
        return FxCrossRate(base, quote, 1.0, snapshot.as_of_date, snapshot.source_snapshot, (), "Identity reference rate; informational and non-executable.")
    if not snapshot.available:
        return None

    graph: dict[str, list[FxRateLeg]] = {}
    for row in snapshot.rates:
        if not _usable_rate(row.rate):
            return None
        pair = f"{row.base_currency}/{row.quote_currency}"
        graph.setdefault(row.base_currency, []).append(
            FxRateLeg(row.base_currency, row.quote_currency, pair, row.rate, row.rate, False, row.source)
        )
        graph.setdefault(row.quote_currency, []).append(
            FxRateLeg(row.quote_currency, row.base_currency, pair, row.rate, 1.0 / row.rate, True, row.source)
        )
    for legs in graph.values():
        legs.sort(key=lambda leg: (leg.to_currency, leg.inverted, leg.observed_pair, leg.source))

    queue = deque([(base, 1.0, (), frozenset({base}))])
    matches: list[tuple[float, tuple[FxRateLeg, ...]]] = []
    shortest: int | None = None
    while queue:
        current, factor, path, visited = queue.popleft()
        if shortest is not None and len(path) >= shortest:
            continue
        for leg in graph.get(current, ()):
            if leg.to_currency in visited:
                continue
            next_factor = factor * leg.applied_rate
            if not _usable_rate(next_factor):
                return None
            next_path = path + (leg,)
            if leg.to_currency == quote:
                shortest = len(next_path) if shortest is None else shortest
                if len(next_path) == shortest:
                    matches.append((next_factor, next_path))
            elif shortest is None or len(next_path) < shortest:
                queue.append((leg.to_currency, next_factor, next_path, visited | {leg.to_currency}))
    if not matches:
        return None
    matches.sort(key=lambda item: tuple((leg.observed_pair, leg.inverted, leg.from_currency) for leg in item[1]))
    selected_rate, selected_legs = matches[0]
    if any(not math.isclose(rate, selected_rate, rel_tol=tolerance, abs_tol=0.0) for rate, _ in matches[1:]):
        return None
    sources = ", ".join(sorted({leg.source for leg in selected_legs if leg.source})) or "unspecified source"
    return FxCrossRate(
        base,
        quote,
        selected_rate,
        snapshot.as_of_date,
        snapshot.source_snapshot,
        selected_legs,
        f"{sources} reference rate; informational and non-executable.",
    )


def major_currency(value: object) -> str | None:
    """Three-letter major currency code of a quote-currency label (minor units named by their major)."""

    text = str(value).strip() if value is not None else ""
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    return _normalise_currency(MINOR_UNIT_MAJOR_CURRENCY.get(text, text))


@dataclass(frozen=True)
class EurRateSeries:
    """EUR per one major unit of ``currency`` for each requested session (NaN = unavailable)."""

    currency: str
    rates: pd.Series
    reasons: pd.Series


class EurRateBook:
    """Point-in-time, session-dated currency->EUR rates built on the canonical FX path.

    Rows are filtered to those ingested by ``known_by`` (same cut-off rule as
    ``build_fx_rate_snapshot``). A session reads the latest quote dated on or before it, never a
    later one, and only while that quote is within the ``ok`` staleness band. A quote date whose
    rows are duplicated, contradictory (reciprocal/cycle) or lack an unambiguous ``fx_cross_rate``
    leg is unavailable. 1 is never assumed for a foreign currency.
    """

    def __init__(self, fx: pd.DataFrame | None, *, known_by: date | datetime | str | None) -> None:
        self.unavailable_reason: str | None = None
        self._rows: pd.DataFrame = pd.DataFrame()
        self._by_date: dict[date, pd.DataFrame] = {}
        self._dates: list[date] = []
        self._cross: dict[tuple[date, str], tuple[float | None, str | None]] = {}
        try:
            self._prepare(fx, known_by)
        except Exception as exc:  # malformed frames fail closed with an explicit reason
            self._rows = pd.DataFrame()
            self._by_date = {}
            self._dates = []
            self.unavailable_reason = f"FX rates could not be read ({type(exc).__name__})."

    def _prepare(self, fx: pd.DataFrame | None, known_by: date | datetime | str | None) -> None:
        if fx is None or fx.empty:
            self.unavailable_reason = "FX rates are missing."
            return
        known_date, cutoff, date_only = _decision_cutoff(known_by)
        if known_date is None or (cutoff is None and not date_only):
            self.unavailable_reason = "FX knowledge cutoff is missing or invalid."
            return
        date_column = _first_present(fx, DATE_COLUMNS)
        rate_column = _first_present(fx, RATE_COLUMNS)
        if date_column is None:
            self.unavailable_reason = "FX rates have no quote date."
            return
        if rate_column is None:
            self.unavailable_reason = "FX rates have no rate column."
            return
        if "pair" not in fx.columns and not {"base_currency", "quote_currency"}.issubset(fx.columns):
            self.unavailable_reason = "FX rates have no currency pair."
            return
        if "ingested_at" not in fx.columns:
            self.unavailable_reason = "FX rates have no ingested_at timestamp; point-in-time availability cannot be verified."
            return
        quote_dates = pd.to_datetime(fx[date_column], errors="coerce", utc=False)
        ingested = pd.to_datetime(fx["ingested_at"], errors="coerce", utc=True)
        if quote_dates.isna().any():
            self.unavailable_reason = "FX rates contain a missing or invalid quote date."
            return
        if ingested.isna().any():
            self.unavailable_reason = "FX rates contain a missing or invalid ingested_at timestamp."
            return
        if fx[rate_column].map(lambda value: isinstance(value, (bool, np.bool_))).any():
            self.unavailable_reason = "FX rates must be numeric values, not booleans."
            return
        rates = pd.to_numeric(fx[rate_column], errors="coerce")
        if not rates.map(_usable_rate).all():
            self.unavailable_reason = "FX rates must be finite numeric values above the subnormal guard with a finite inverse."
            return
        pairs = _parse_currency_pairs(fx)
        if pairs.errors:
            self.unavailable_reason = "; ".join(pairs.errors)
            return
        known = ingested.dt.date.lt(known_date) if date_only else ingested.le(cutoff)
        rows = pd.DataFrame(
            {
                "as_of_date": quote_dates.dt.date,
                "base_currency": pairs.base_currency,
                "quote_currency": pairs.quote_currency,
                "rate": rates.astype(float),
                "source": _column_or_default(fx, "source", "unspecified"),
                "ingested_at": ingested,
            }
        )
        rows = rows.loc[known & rows["as_of_date"].le(known_date)].copy()
        if rows.empty:
            self.unavailable_reason = "No FX snapshot was known by the analysis decision time."
            return
        rows["pair"] = rows["base_currency"] + "/" + rows["quote_currency"]
        rows = rows.sort_values(["as_of_date", "pair", "source", "ingested_at"], kind="stable").reset_index(drop=True)
        self._rows = rows
        self._by_date = {day: frame for day, frame in rows.groupby("as_of_date", sort=True)}
        self._dates = sorted(self._by_date)

    def identity(self, start: date, end: date) -> str:
        """SHA-256 of the known FX rows dated within the window (plus the as-of look-back)."""

        if self.unavailable_reason is not None:
            return hashlib.sha256(f"fx:unavailable:{self.unavailable_reason}".encode("utf-8")).hexdigest()
        first = start - timedelta(days=_FX_LOOKBACK_CALENDAR_DAYS)
        window = self._rows.loc[self._rows["as_of_date"].ge(first) & self._rows["as_of_date"].le(end)]
        frame = window[["as_of_date", "pair", "rate", "source", "ingested_at"]].copy()
        frame["rate"] = frame["rate"].map(repr)
        frame["ingested_at"] = frame["ingested_at"].map(lambda value: pd.Timestamp(value).isoformat())
        return sha256_dataframe(frame.reset_index(drop=True))

    def series(self, currency: str, sessions: Iterable[date]) -> EurRateSeries:
        major = major_currency(currency)
        days = list(sessions)
        index = pd.Index(days, dtype=object)
        if major is None:
            return EurRateSeries(
                str(currency),
                pd.Series(np.nan, index=index, dtype=float),
                pd.Series("quote currency is unknown", index=index, dtype=object),
            )
        if major == "EUR":
            return EurRateSeries(major, pd.Series(1.0, index=index, dtype=float), pd.Series([None] * len(days), index=index, dtype=object))
        values: list[float] = []
        reasons: list[str | None] = []
        for session in days:
            rate, reason = self._rate(major, session)
            values.append(float("nan") if rate is None else rate)
            reasons.append(reason)
        return EurRateSeries(major, pd.Series(values, index=index, dtype=float), pd.Series(reasons, index=index, dtype=object))

    def _rate(self, currency: str, session: date) -> tuple[float | None, str | None]:
        if self.unavailable_reason is not None:
            return None, self.unavailable_reason
        position = bisect.bisect_right(self._dates, session)
        if position == 0:
            return None, f"no {currency}/EUR FX quote dated on or before {session.isoformat()}"
        quote_day = self._dates[position - 1]
        if quote_day != session:
            age = _business_days_between(quote_day, session)
            if price_staleness_status(age) != "ok":
                return None, f"latest FX quote {quote_day.isoformat()} is {age} business days older than {session.isoformat()}"
        key = (quote_day, currency)
        if key not in self._cross:
            self._cross[key] = self._cross_rate(quote_day, currency)
        rate, reason = self._cross[key]
        if rate is None:
            return None, f"{reason} on {quote_day.isoformat()}"
        return rate, None

    def _cross_rate(self, quote_day: date, currency: str) -> tuple[float | None, str | None]:
        dated = self._by_date[quote_day]
        # The outcome is a pure function of the day's quotes, so identical content is validated once per process
        # instead of once per EurRateBook (a backtest builds several books over the same several thousand days).
        content = (
            quote_day,
            currency,
            tuple(
                zip(
                    dated["as_of_date"].tolist(),
                    dated["pair"].tolist(),
                    dated["base_currency"].tolist(),
                    dated["quote_currency"].tolist(),
                    dated["rate"].tolist(),
                    dated["source"].tolist(),
                    strict=True,
                )
            ),
        )
        known = _CROSS_RATE_MEMO.get(content)
        if known is None:
            known = self._compute_cross_rate(dated, quote_day, currency)
            if len(_CROSS_RATE_MEMO) >= _CROSS_RATE_MEMO_LIMIT:
                _CROSS_RATE_MEMO.clear()
            _CROSS_RATE_MEMO[content] = known
        return known

    @staticmethod
    def _compute_cross_rate(dated: pd.DataFrame, quote_day: date, currency: str) -> tuple[float | None, str | None]:
        if dated.duplicated(["as_of_date", "pair"]).any():
            return None, "FX rates contain duplicate date/pair rows"
        errors = _fx_rate_consistency_errors(dated)
        if errors:
            return None, "FX quotes are contradictory (" + errors[0] + ")"
        snapshot = FxRateSnapshot(
            decision_date=quote_day,
            as_of_date=quote_day,
            rates=tuple(
                FxRate(str(row.base_currency), str(row.quote_currency), float(row.rate), str(row.source))
                for row in dated.itertuples(index=False)
            ),
            source_snapshot=None,
            age_business_days=0,
            staleness_status="ok",
            available=True,
            reason=None,
        )
        cross = fx_cross_rate(snapshot, currency, "EUR")
        if cross is None or not _usable_rate(cross.rate):
            return None, f"no unambiguous {currency}/EUR rate"
        return float(cross.rate), None


_CROSS_RATE_MEMO: dict[tuple[object, ...], tuple[float | None, str | None]] = {}
_CROSS_RATE_MEMO_LIMIT = 100_000


SAMPLE_PRICE_SOURCE = "synthetic_sample"


def sample_fx_rates(prices: pd.DataFrame) -> pd.DataFrame:
    """Deterministic synthetic ``<currency>/EUR`` quotes for a purely synthetic (sample) price frame.

    The sample pipeline has no FX file, so without this its non-EUR sample instruments would have no
    EUR basis. The quotes carry ``source=synthetic_sample`` and exist only in memory; they are never
    persisted and never used for real (provider) prices.
    """

    columns = ["as_of_date", "base_currency", "quote_currency", "rate", "source", "ingested_at"]
    if prices.empty or not {"date", "currency"}.issubset(prices.columns):
        return pd.DataFrame(columns=columns)
    days = sorted({day for day in pd.to_datetime(prices["date"], errors="coerce").dt.date.dropna()})
    currencies = sorted({code for code in prices["currency"].map(major_currency).dropna().unique() if code != "EUR"})
    if not days or not currencies:
        return pd.DataFrame(columns=columns)
    known_at = (pd.Timestamp(days[0]) - pd.Timedelta(days=1)).tz_localize("UTC").isoformat()
    frames = []
    for currency in currencies:
        seed = int.from_bytes(hashlib.sha256(f"sample-fx:{currency}".encode("utf-8")).digest()[:4], "big")
        steps = np.random.default_rng(seed).normal(0.0, 0.002, size=len(days))
        frames.append(
            pd.DataFrame(
                {
                    "as_of_date": days,
                    "base_currency": currency,
                    "quote_currency": "EUR",
                    "rate": 0.1 * np.exp(np.cumsum(steps)),
                    "source": SAMPLE_PRICE_SOURCE,
                    "ingested_at": known_at,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def fx_rates_for_prices(prices: pd.DataFrame | None) -> pd.DataFrame:
    """FX rates behind an EUR price basis: the synthetic sample quotes for a sample-only frame, else the canonical store."""

    if (
        prices is not None
        and not prices.empty
        and "source" in prices.columns
        and prices["source"].astype(str).isin({SAMPLE_PRICE_SOURCE, "sample_generator"}).all()
    ):
        return sample_fx_rates(prices)
    return load_fx_rates()


def fx_data_inventory(path: Path = FX_CLEAN_PATH) -> dict[str, object]:
    frame = load_fx_rates(path)
    if frame.empty:
        return {"dataset_type": "fx", "present": False, "path": str(path)}
    latest = pd.to_datetime(frame["as_of_date"], errors="coerce").max()
    staleness = str(frame["staleness_status"].dropna().iloc[0]) if "staleness_status" in frame.columns and frame["staleness_status"].notna().any() else "unknown"
    return {
        "dataset_type": "fx",
        "present": True,
        "path": str(path),
        "rows": len(frame),
        "as_of_date": latest.date().isoformat() if pd.notna(latest) else None,
        "pairs": sorted(frame["pair"].dropna().astype(str).unique().tolist()),
        "staleness_status": staleness,
        "checksum": sha256_dataframe(frame),
    }


@dataclass(frozen=True)
class _CurrencyPairs:
    base_currency: pd.Series
    quote_currency: pd.Series
    errors: list[str]
    warnings: list[str]


def _parse_currency_pairs(frame: pd.DataFrame) -> _CurrencyPairs:
    errors: list[str] = []
    warnings: list[str] = []
    if "pair" in frame.columns:
        pairs = frame["pair"].fillna("").astype(str).str.upper().str.strip()
        base_values = []
        quote_values = []
        for value in pairs:
            compact = re.sub(r"[^A-Z]", "", value)
            if len(compact) != 6:
                base_values.append("")
                quote_values.append("")
                continue
            base_values.append(compact[:3])
            quote_values.append(compact[3:])
        base = pd.Series(base_values, index=frame.index)
        quote = pd.Series(quote_values, index=frame.index)
        for field, parsed in (("base_currency", base), ("quote_currency", quote)):
            if field not in frame.columns:
                continue
            explicit = frame[field].fillna("").astype(str).str.upper().str.strip()
            if (explicit != parsed).any():
                errors.append("FX rates contain contradictory pair and base/quote currency fields.")
                break
    else:
        base = frame["base_currency"].fillna("").astype(str).str.upper().str.strip()
        quote = frame["quote_currency"].fillna("").astype(str).str.upper().str.strip()
    currency_pattern = re.compile(r"^[A-Z]{3}$")
    bad = ~base.map(lambda value: bool(currency_pattern.match(value))) | ~quote.map(lambda value: bool(currency_pattern.match(value)))
    if bad.any():
        errors.append("FX rates contain invalid currency codes or pairs.")
    same = base == quote
    if same.any():
        warnings.append("FX rates include same-currency pairs; these are retained but usually unnecessary.")
    return _CurrencyPairs(base, quote, errors, warnings)


def _fx_rate_consistency_errors(frame: pd.DataFrame, *, tolerance: float = FX_RATE_CONSISTENCY_TOLERANCE) -> list[str]:
    errors: list[str] = []
    for as_of_date, dated in frame.groupby("as_of_date", sort=True):
        direct = {
            (str(row.base_currency), str(row.quote_currency)): float(row.rate)
            for row in dated.itertuples(index=False)
        }
        for (base, quote), rate in sorted(direct.items()):
            if base == quote:
                if not math.isclose(rate, 1.0, rel_tol=0.0, abs_tol=tolerance):
                    errors.append(f"FX same-currency rate {base}/{quote} must equal 1 on {as_of_date}.")
                continue
            reciprocal = direct.get((quote, base))
            if reciprocal is not None and not math.isclose(rate * reciprocal, 1.0, rel_tol=tolerance, abs_tol=0.0):
                errors.append(f"FX reciprocal quotes {base}/{quote} and {quote}/{base} are inconsistent on {as_of_date}.")

        graph: dict[str, list[tuple[str, float]]] = {}
        for (base, quote), rate in direct.items():
            if base == quote:
                continue
            graph.setdefault(base, []).append((quote, rate))
            graph.setdefault(quote, []).append((base, 1.0 / rate))

        relative_values: dict[str, float] = {}
        for currency in sorted(graph):
            if currency in relative_values:
                continue
            relative_values[currency] = 1.0
            pending = [currency]
            while pending:
                current = pending.pop()
                for neighbour, rate in graph[current]:
                    implied_value = relative_values[current] * rate
                    if neighbour in relative_values:
                        if not math.isclose(
                            implied_value,
                            relative_values[neighbour],
                            rel_tol=tolerance,
                            abs_tol=0.0,
                        ):
                            errors.append(
                                f"FX triangular/cycle quotes are inconsistent for {current}/{neighbour} on {as_of_date}."
                            )
                    else:
                        relative_values[neighbour] = implied_value
                        pending.append(neighbour)
    return errors


def _decision_cutoff(value: date | datetime | str | None) -> tuple[date | None, pd.Timestamp | None, bool]:
    if value is None:
        return None, None, False
    if isinstance(value, datetime):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return timestamp.date(), timestamp, False
    if isinstance(value, date):
        return value, None, True
    text = str(value).strip()
    if not text:
        return None, None, False
    if len(text) == 10:
        parsed_date = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed_date):
            return None, None, False
        return parsed_date.date(), None, True
    timestamp = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(timestamp):
        return None, None, False
    return timestamp.date(), timestamp, False


def _usable_rate(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        rate = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(rate)
        and rate >= sys.float_info.min
        and math.isfinite(1.0 / rate)
        and 1.0 / rate >= sys.float_info.min
    )


def _normalise_currency(value: str) -> str | None:
    currency = str(value or "").strip().upper()
    return currency if re.fullmatch(r"[A-Z]{3}", currency) else None


def _column_or_default(frame: pd.DataFrame, column: str, default: str) -> pd.Series:
    if column in frame.columns:
        return frame[column].fillna(default).astype(str).str.strip().replace("", default)
    return pd.Series([default] * len(frame), index=frame.index)


def _empty_fx_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["as_of_date", "base_currency", "quote_currency", "pair", "rate", "source", "ingested_at", "staleness_status"])


def _store_raw_fx_import(result: ProviderResult, frame: pd.DataFrame, raw_dir: Path, timestamp: str, checksum: str) -> Path:
    source_path = _source_path(result.metadata)
    if source_path and source_path.exists() and source_path.is_file():
        raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_{source_path.name}"
        shutil.copy2(source_path, raw_path)
        return raw_path
    raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_fx.parquet"
    frame.to_parquet(raw_path, index=False)
    return raw_path
