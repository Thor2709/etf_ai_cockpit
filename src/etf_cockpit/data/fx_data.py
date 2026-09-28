from __future__ import annotations

import json
import math
import re
import shutil
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Literal

import pandas as pd

from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR, SNAPSHOTS_DIR
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.types import DatasetMetadata
from etf_cockpit.data.provenance import metadata_from_frame, price_staleness_status, sha256_dataframe
from etf_cockpit.data.providers import ProviderResult

FX_CLEAN_PATH = CLEAN_DIR / "fx.parquet"
DATE_COLUMNS = ("as_of_date", "date", "rate_date")
RATE_COLUMNS = ("rate", "fx_rate", "exchange_rate", "mid")
FX_RATE_CONSISTENCY_TOLERANCE = 1e-6


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
    if ingested_at is not None:
        parsed_ingested_at = pd.to_datetime(pd.Series([ingested_at] * len(frame), index=frame.index), errors="coerce", utc=True)
    elif "ingested_at" in frame.columns:
        parsed_ingested_at = pd.to_datetime(frame["ingested_at"], errors="coerce", utc=True)
    if parsed_ingested_at is not None and parsed_ingested_at.isna().any():
        errors.append("FX rates contain invalid or missing ingested_at values.")
    rates = pd.to_numeric(frame[rate_column], errors="coerce")
    if rates.isna().any() or (rates <= 0).any():
        errors.append("FX rates must be numeric and positive.")
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
    age_days = _business_days_between(latest, today or date.today())
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
) -> FxRateSnapshot:
    """Select a same-date, point-in-time FX snapshot or return an unavailable one."""

    decision_date, cutoff, date_only = _decision_cutoff(decision_time)
    if decision_date is None:
        return FxRateSnapshot(None, None, (), None, None, "block", False, "Analysis decision time is missing or invalid.")
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
    known_by_decision = ingested.dt.date.lt(decision_date) if date_only else ingested.le(cutoff)
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
    if any(not math.isclose(rate, selected_rate, rel_tol=tolerance, abs_tol=tolerance) for rate, _ in matches[1:]):
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
            if reciprocal is not None and not math.isclose(rate * reciprocal, 1.0, rel_tol=tolerance, abs_tol=tolerance):
                errors.append(f"FX reciprocal quotes {base}/{quote} and {quote}/{base} are inconsistent on {as_of_date}.")

        currencies = sorted({currency for pair in direct for currency in pair})

        def oriented_rate(base: str, quote: str) -> float | None:
            if (base, quote) in direct:
                return direct[(base, quote)]
            reverse = direct.get((quote, base))
            return None if reverse is None else 1.0 / reverse

        for first, middle, last in combinations(currencies, 3):
            first_middle = oriented_rate(first, middle)
            middle_last = oriented_rate(middle, last)
            first_last = oriented_rate(first, last)
            if first_middle is None or middle_last is None or first_last is None:
                continue
            implied = first_middle * middle_last
            if not math.isclose(implied, first_last, rel_tol=tolerance, abs_tol=tolerance):
                errors.append(
                    f"FX triangular quotes {first}/{middle}, {middle}/{last}, and {first}/{last} "
                    f"are inconsistent on {as_of_date}."
                )
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


def _normalise_currency(value: str) -> str | None:
    currency = str(value or "").strip().upper()
    return currency if re.fullmatch(r"[A-Z]{3}", currency) else None


def _business_days_between(start: date, end: date) -> int:
    if start >= end:
        return 0
    return len(pd.bdate_range(pd.Timestamp(start) + pd.offsets.BDay(1), pd.Timestamp(end)))


def _first_present(frame: pd.DataFrame, columns: tuple[str, ...]) -> str | None:
    for column in columns:
        if column in frame.columns:
            return column
    return None


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


def _snapshot_existing_clean(clean_path: Path, snapshots_dir: Path, timestamp: str) -> Path | None:
    if not clean_path.exists():
        return None
    snapshot_path = snapshots_dir / f"{timestamp}_previous_{clean_path.name}"
    shutil.copy2(clean_path, snapshot_path)
    return snapshot_path


def _source_path(metadata: DatasetMetadata | None) -> Path | None:
    if metadata is None:
        return None
    try:
        return Path(metadata.provider_or_manual_source)
    except Exception:
        return None


def _metadata_to_json(metadata: DatasetMetadata) -> dict[str, object]:
    return {
        "source_name": metadata.source_name,
        "source_type": metadata.source_type,
        "as_of_date": metadata.as_of_date.isoformat() if metadata.as_of_date else None,
        "ingested_at": metadata.ingested_at.isoformat() if metadata.ingested_at else None,
        "currency": metadata.currency,
        "timezone": metadata.timezone,
        "provider_or_manual_source": metadata.provider_or_manual_source,
        "checksum": metadata.checksum,
        "staleness_status": metadata.staleness_status,
        "age_days": metadata.age_days,
        "notes": metadata.notes,
    }
