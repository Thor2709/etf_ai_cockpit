"""Local-first macro, factor, risk-free and benchmark observations.

The warehouse deliberately accepts already downloaded source payloads.  It does
not fetch remote services.  Raw observations are stored in the existing
append-only bitemporal ledger, so a decision-time query cannot see a revision
that was not available on that date.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
from numbers import Integral
from pathlib import Path
import sqlite3
from typing import Iterable, Literal, Mapping

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.data.bitemporal import BitemporalError, BitemporalStore


_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"
_ALLOWED_KINDS = {"macro", "factor", "risk_free", "benchmark"}
_ALLOWED_FREQUENCIES = {"daily", "monthly", "quarterly", "annual", "irregular"}
RISK_FREE_PROXY_CONFIG_PATH = CONFIG_DIR / "risk_free_proxies.json"
_OFFICIAL_CURVE_AUTHORITIES = {"official_regulator", "official_public_file"}
_UNIT_FACTORS = {
    ("percentage", "decimal"): 0.01,
    ("percent", "decimal"): 0.01,
    ("basis_points", "decimal"): 0.0001,
    ("bps", "decimal"): 0.0001,
    ("decimal", "percentage"): 100.0,
    ("decimal", "percent"): 100.0,
    ("decimal", "basis_points"): 10000.0,
    ("decimal", "bps"): 10000.0,
}


class MacroWarehouseError(ValueError):
    """Raised when a local warehouse contract cannot be trusted."""


class MacroObservation(BaseModel):
    """One source observation with both effective and availability metadata."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    series_id: str
    period_start: str
    value: float
    unit: str
    frequency: str
    country: str | None = None
    currency: str | None = None
    dataset_kind: str = "macro"
    source_id: str
    source_authority: str | None = None
    source_checksum: str
    source_terms: str = "manual_review_required"
    methodology: str = ""
    published_at: str
    available_at: str
    observed_at: str
    ingested_at: str
    revised_at: str | None = None
    revision: int = Field(default=1, ge=1, strict=True)
    timezone_confidence: str = "exact"
    availability_confidence: str = "exact"
    transformation_version: str = "identity.v1"
    source_observation_ids: tuple[str, ...] = ()
    curve_id: str | None = None
    curve_type: str | None = None
    curve_version: str | None = None
    tenor_years: float | None = Field(default=None, gt=0, strict=True, allow_inf_nan=False)
    curve_point_count: int | None = Field(default=None, ge=1, strict=True)
    interpolation: str | None = None
    extrapolation_allowed: StrictBool = False
    compounding: str | None = None
    day_count: str | None = None
    reinvestment: str | None = None
    freshness: str | None = None
    freshness_status: str | None = None
    benchmark_id: str | None = None
    benchmark_version: str | None = None
    benchmark_category: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _strict_curve_rate(cls, values: object) -> object:
        if not isinstance(values, Mapping):
            return values
        curve_fields = ("curve_id", "curve_type", "curve_version", "tenor_years")
        if not any(values.get(field) is not None for field in curve_fields):
            return values
        rate = values.get("value")
        if isinstance(rate, bool) or not isinstance(rate, float) or not math.isfinite(rate):
            raise ValueError("curve rate must be a finite float")
        return values

    @property
    def stable_id(self) -> str:
        return f"{self.series_id}:{self.period_start}"

    @property
    def observation_id(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @property
    def availability_status(self) -> str:
        return "available" if self.country and self.currency else "unavailable_context"

    def ledger_value(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "series_id": self.series_id,
            "period_start": self.period_start,
            "value": self.value,
            "unit": self.unit,
            "frequency": self.frequency,
            "country": self.country,
            "currency": self.currency,
            "dataset_kind": self.dataset_kind,
            "source_terms": self.source_terms,
            "source_authority": self.source_authority,
            "methodology": self.methodology,
            "transformation_version": self.transformation_version,
            "source_observation_ids": list(self.source_observation_ids),
            "curve_id": self.curve_id,
            "curve_type": self.curve_type,
            "curve_version": self.curve_version,
            "tenor_years": self.tenor_years,
            "curve_point_count": self.curve_point_count,
            "interpolation": self.interpolation,
            "extrapolation_allowed": self.extrapolation_allowed,
            "compounding": self.compounding,
            "day_count": self.day_count,
            "reinvestment": self.reinvestment,
            "freshness": self.freshness,
            "freshness_status": self.freshness_status,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "benchmark_category": self.benchmark_category,
        }

    @classmethod
    def from_ledger(cls, record: Mapping[str, object]) -> MacroObservation:
        value = record.get("value")
        if not isinstance(value, Mapping):
            raise MacroWarehouseError("macro ledger value is malformed")
        return cls(
            **dict(value),
            source_id=str(record["source_id"]),
            source_checksum=str(record["source_checksum"]),
            published_at=str(record["published_at"]),
            available_at=str(record["available_at"]),
            observed_at=str(record["observed_at"]),
            ingested_at=str(record["ingested_at"]),
            revised_at=record.get("revised_at"),
            revision=record["revision"],
            timezone_confidence=str(record["timezone_confidence"]),
            availability_confidence=str(record["availability_confidence"]),
        )


def _timestamp(value: str | date | datetime, field_name: str) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if len(text) == 4 and text.isdigit():
            text = f"{text}-01-01"
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _format_timestamp(parsed)


def _format_timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond:
        return normalized.isoformat(timespec="microseconds")
    return normalized.strftime(_TIMESTAMP_FORMAT)


def _explicit_timestamp(value: str | date | datetime, field_name: str) -> str:
    """Normalize a curve timestamp only when its timezone is explicit."""

    if isinstance(value, date) and not isinstance(value, datetime):
        raise MacroWarehouseError(f"{field_name} must be an explicit timezone-aware timestamp")
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MacroWarehouseError(
                f"{field_name} must be an explicit timezone-aware timestamp"
            ) from exc
    if parsed.tzinfo is None:
        raise MacroWarehouseError(f"{field_name} must be an explicit timezone-aware timestamp")
    return _format_timestamp(parsed)


def _timestamp_value(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _period_start(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise MacroWarehouseError("macro observation period_start is required")
    if len(text) == 4 and text.isdigit():
        return f"{text}-01-01"
    if len(text) == 7 and text[4] == "-":
        return f"{text}-01"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise MacroWarehouseError(f"invalid macro period_start: {value!r}") from exc


def _source_checksum(value: str | bytes) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _positive_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise MacroWarehouseError("macro revision must be a positive integer")
    return int(value)


def _validate(observation: MacroObservation) -> MacroObservation:
    if observation.dataset_kind not in _ALLOWED_KINDS:
        raise MacroWarehouseError(f"unsupported macro dataset_kind: {observation.dataset_kind}")
    if observation.frequency not in _ALLOWED_FREQUENCIES:
        raise MacroWarehouseError(f"unsupported macro frequency: {observation.frequency}")
    if not observation.dataset_id.strip() or not observation.series_id.strip():
        raise MacroWarehouseError("macro dataset_id and series_id are required")
    if len(observation.source_checksum) != 64 or any(char not in "0123456789abcdefABCDEF" for char in observation.source_checksum):
        raise MacroWarehouseError("macro source_checksum must be a SHA-256 value")
    revision = _positive_revision(observation.revision)
    curve_evidence = any(
        value is not None
        for value in (
            observation.curve_id,
            observation.curve_type,
            observation.tenor_years,
        )
    )
    if curve_evidence and observation.dataset_kind != "risk_free":
        raise MacroWarehouseError("curve observations must have dataset_kind risk_free")
    if curve_evidence and observation.dataset_id != f"curve:{observation.curve_id}":
        raise MacroWarehouseError("curve dataset identity does not match curve_id")
    timestamp_normalizer = _explicit_timestamp if curve_evidence else _timestamp
    normalized = {
        field_name: timestamp_normalizer(getattr(observation, field_name), field_name)
        for field_name in ("published_at", "available_at", "observed_at", "ingested_at")
    }
    if _timestamp_value(normalized["observed_at"]) > _timestamp_value(normalized["available_at"]):
        raise MacroWarehouseError("macro effective/observed_at cannot be after available_at")
    if _timestamp_value(normalized["published_at"]) > _timestamp_value(normalized["available_at"]):
        raise MacroWarehouseError("macro published_at cannot be after available_at")
    if observation.revised_at is not None:
        timestamp_normalizer(observation.revised_at, "revised_at")
    return observation.model_copy(
        update={
            "period_start": _period_start(observation.period_start),
            **normalized,
            "revised_at": (
                timestamp_normalizer(observation.revised_at, "revised_at")
                if observation.revised_at
                else None
            ),
            "source_checksum": observation.source_checksum.lower(),
            "revision": revision,
        }
    )


class CurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenor_years: float = Field(gt=0, strict=True, allow_inf_nan=False)
    rate: float = Field(strict=True, allow_inf_nan=False)


class CurveSnapshot(BaseModel):
    """Official local curve snapshot; rates are decimal values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    curve_id: str
    dataset_kind: Literal["risk_free"] = "risk_free"
    curve_version: str
    curve_type: str
    currency: str
    effective_at: str
    published_at: str
    available_at: str
    ingested_at: str
    source_id: str
    source_authority: Literal["official_regulator", "official_public_file"] | None = None
    source_checksum: str
    source_terms: str
    methodology: str
    interpolation: str = "linear"
    extrapolation_allowed: StrictBool = False
    compounding: str | None = None
    day_count: str | None = None
    reinvestment: str | None = None
    freshness: str | None = None
    freshness_status: str | None = None
    points: tuple[CurvePoint, ...]
    revision: int = Field(default=1, ge=1, strict=True)
    execution_allowed: StrictBool = False

    @model_validator(mode="after")
    def _execution_must_remain_disabled(self) -> CurveSnapshot:
        if self.execution_allowed is not False:
            raise ValueError("curve snapshots cannot grant execution authority")
        return self


class BenchmarkMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    benchmark_id: str
    version: str
    category: str
    currency: str
    effective_at: str
    available_at: str
    ingested_at: str
    source_id: str
    source_checksum: str
    source_terms: str
    methodology: str
    coverage: tuple[str, ...] = ()
    revision: int = Field(default=1, ge=1)
    execution_allowed: Literal[False] = False


class RiskFreeProxyMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: str
    minimum_horizon_years: float = Field(ge=0, strict=True, allow_inf_nan=False)
    maximum_horizon_years: float = Field(gt=0, strict=True, allow_inf_nan=False)
    curve_id: str
    fallback_curve_ids: tuple[str, ...] = ()
    methodology: str
    execution_allowed: StrictBool = False

    @model_validator(mode="after")
    def _execution_must_remain_disabled(self) -> RiskFreeProxyMapping:
        if self.execution_allowed is not False:
            raise ValueError("risk-free mappings cannot grant execution authority")
        return self


def load_risk_free_proxy_mappings(
    path: Path | None = None,
) -> tuple[RiskFreeProxyMapping, ...]:
    """Load the explicit local mapping contract; absent or malformed config fails closed."""

    target = Path(path) if path is not None else RISK_FREE_PROXY_CONFIG_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping) or payload.get("schema_version") != "1.0":
            return ()
        if payload.get("execution_allowed") is not False:
            return ()
        rows = payload.get("mappings")
        if not isinstance(rows, list):
            return ()
        mappings = tuple(RiskFreeProxyMapping.model_validate(row) for row in rows)
        if any(
            item.minimum_horizon_years > item.maximum_horizon_years
            or len(item.currency.strip()) != 3
            or not item.curve_id.strip()
            or not item.methodology.strip()
            for item in mappings
        ):
            return ()
        signatures = {
            (
                item.currency.upper(),
                item.minimum_horizon_years,
                item.maximum_horizon_years,
                item.curve_id,
            )
            for item in mappings
        }
        if len(signatures) != len(mappings):
            return ()
        return mappings
    except (OSError, TypeError, ValueError):
        return ()


def _validate_curve(snapshot: CurveSnapshot) -> CurveSnapshot:
    if snapshot.dataset_kind != "risk_free":
        raise MacroWarehouseError("curve snapshots must have dataset_kind risk_free")
    if snapshot.curve_type not in {"spot", "par", "forward"}:
        raise MacroWarehouseError(f"unsupported curve_type: {snapshot.curve_type}")
    if snapshot.interpolation not in {"linear", "none"}:
        raise MacroWarehouseError(f"unsupported interpolation policy: {snapshot.interpolation}")
    if snapshot.extrapolation_allowed:
        raise MacroWarehouseError("curve extrapolation policy is unsupported")
    if snapshot.execution_allowed is not False:
        raise MacroWarehouseError("curve snapshots cannot grant execution authority")
    revision = _positive_revision(snapshot.revision)
    if snapshot.source_authority not in _OFFICIAL_CURVE_AUTHORITIES:
        raise MacroWarehouseError("cash curve provenance must explicitly identify an official source")
    points = tuple(sorted(snapshot.points, key=lambda item: item.tenor_years))
    if len(points) < 1 or len({item.tenor_years for item in points}) != len(points):
        raise MacroWarehouseError("curve tenor points must be non-empty and unique")
    if any(not math.isfinite(item.rate) for item in points):
        raise MacroWarehouseError("curve rates must be finite")
    if len(snapshot.source_checksum) != 64 or any(
        character not in "0123456789abcdefABCDEF"
        for character in snapshot.source_checksum
    ):
        raise MacroWarehouseError("curve source_checksum must be a SHA-256 value")
    if snapshot.compounding is not None and snapshot.compounding not in {"annual", "continuous", "simple"}:
        raise MacroWarehouseError(f"unsupported curve compounding: {snapshot.compounding}")
    if snapshot.day_count is not None and snapshot.day_count not in {"ACT/360", "ACT/365F", "ACT/ACT-ISDA"}:
        raise MacroWarehouseError(f"unsupported curve day count: {snapshot.day_count}")
    if snapshot.reinvestment != "reinvested_income":
        raise MacroWarehouseError("curve reinvestment convention is unsupported")
    for freshness in (snapshot.freshness, snapshot.freshness_status):
        if freshness is not None and freshness not in {"fresh", "stale", "conflicted", "malformed", "unavailable"}:
            raise MacroWarehouseError(f"unsupported curve freshness: {freshness}")
    effective_at = _explicit_timestamp(snapshot.effective_at, "effective_at")
    published_at = _explicit_timestamp(snapshot.published_at, "published_at")
    available_at = _explicit_timestamp(snapshot.available_at, "available_at")
    if _timestamp_value(effective_at) > _timestamp_value(available_at):
        raise MacroWarehouseError("curve effective_at cannot be after available_at")
    if _timestamp_value(published_at) > _timestamp_value(available_at):
        raise MacroWarehouseError("curve published_at cannot be after available_at")
    return snapshot.model_copy(
        update={
            "currency": snapshot.currency.upper(),
            "effective_at": effective_at,
            "published_at": published_at,
            "available_at": available_at,
            "ingested_at": _explicit_timestamp(snapshot.ingested_at, "ingested_at"),
            "points": points,
            "revision": revision,
        }
    )


def _validate_benchmark(metadata: BenchmarkMetadata) -> BenchmarkMetadata:
    required = {
        "benchmark_id": metadata.benchmark_id,
        "version": metadata.version,
        "currency": metadata.currency,
        "source_id": metadata.source_id,
        "source_terms": metadata.source_terms,
        "methodology": metadata.methodology,
    }
    missing = sorted(name for name, value in required.items() if not value.strip())
    if missing:
        raise MacroWarehouseError(
            f"benchmark metadata missing required fields: {', '.join(missing)}"
        )
    if metadata.execution_allowed:
        raise MacroWarehouseError("benchmark metadata cannot grant execution authority")
    if metadata.category not in {
        "sovereign",
        "aggregate",
        "corporate",
        "high_yield",
        "duration",
    }:
        raise MacroWarehouseError(f"unsupported benchmark category: {metadata.category}")
    if len(metadata.source_checksum) != 64 or any(
        character not in "0123456789abcdefABCDEF"
        for character in metadata.source_checksum
    ):
        raise MacroWarehouseError("benchmark source_checksum must be a SHA-256 value")
    return metadata.model_copy(
        update={
            "currency": metadata.currency.upper(),
            "effective_at": _timestamp(metadata.effective_at, "effective_at"),
            "available_at": _timestamp(metadata.available_at, "available_at"),
            "ingested_at": _timestamp(metadata.ingested_at, "ingested_at"),
            "source_checksum": metadata.source_checksum.lower(),
        }
    )


def interpolate_curve(
    points: Iterable[CurvePoint],
    tenor_years: float,
    *,
    policy: str,
    extrapolation_allowed: bool = False,
) -> float:
    """Apply the declared bounded curve interpolation policy."""

    ordered = tuple(sorted(points, key=lambda item: item.tenor_years))
    if not ordered or not math.isfinite(tenor_years) or tenor_years <= 0:
        raise MacroWarehouseError("curve tenor is unavailable")
    if extrapolation_allowed:
        raise MacroWarehouseError("curve extrapolation policy is unsupported")
    if tenor_years < ordered[0].tenor_years or tenor_years > ordered[-1].tenor_years:
        raise MacroWarehouseError("curve tenor is outside observed coverage")
    for point in ordered:
        if tenor_years == point.tenor_years:
            return point.rate
    if policy == "none":
        raise MacroWarehouseError("curve tenor is unavailable without interpolation")
    if policy != "linear":
        raise MacroWarehouseError(f"unsupported interpolation policy: {policy}")
    for left, right in zip(ordered, ordered[1:]):
        if left.tenor_years < tenor_years < right.tenor_years:
            weight = (tenor_years - left.tenor_years) / (
                right.tenor_years - left.tenor_years
            )
            return left.rate + weight * (right.rate - left.rate)
    raise MacroWarehouseError("curve interpolation failed")


def parse_world_bank_records(
    payload: Iterable[Mapping[str, object]],
    *,
    dataset_id: str,
    source_id: str,
    source_checksum: str,
    available_at: str,
    ingested_at: str,
    unit: str = "level",
    methodology: str = "World Bank indicator snapshot",
    source_terms: str = "world_bank_public_terms_review_required",
) -> list[MacroObservation]:
    """Parse a saved World Bank indicator response without making a request."""

    rows: list[MacroObservation] = []
    for row in payload:
        country = row.get("countryiso3code") or row.get("country")
        value = row.get("value")
        if value is None or str(value).strip() == "":
            continue
        period = row.get("date") or row.get("period")
        rows.append(
            MacroObservation(
                dataset_id=dataset_id,
                series_id=str(row.get("indicator_id") or row.get("series_id") or dataset_id),
                period_start=_period_start(period),
                value=float(value),
                unit=unit,
                frequency="annual",
                country=str(country).strip() if country else None,
                source_id=source_id,
                source_checksum=source_checksum,
                source_terms=source_terms,
                methodology=methodology,
                published_at=available_at,
                available_at=available_at,
                observed_at=_timestamp(period, "observed_at"),
                ingested_at=ingested_at,
            )
        )
    return [_validate(row) for row in rows]


def parse_csv_records(
    content: str | bytes,
    *,
    dataset_id: str,
    source_id: str,
    available_at: str,
    ingested_at: str,
    unit: str = "level",
    frequency: str = "monthly",
    dataset_kind: str = "macro",
    source_terms: str = "manual_review_required",
    methodology: str = "Local CSV snapshot",
) -> list[MacroObservation]:
    """Parse a local CSV with ``series_id``, ``period_start`` and ``value`` columns."""

    raw = content if isinstance(content, bytes) else content.encode("utf-8")
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    checksum = _source_checksum(raw)
    parsed: list[MacroObservation] = []
    for row in rows:
        value = row.get("value")
        if value is None or not str(value).strip():
            continue
        parsed.append(
            MacroObservation(
                dataset_id=dataset_id,
                series_id=str(row.get("series_id") or dataset_id),
                period_start=_period_start(row.get("period_start") or row.get("date")),
                value=float(value),
                unit=str(row.get("unit") or unit),
                frequency=str(row.get("frequency") or frequency),
                country=str(row.get("country") or "").strip() or None,
                currency=str(row.get("currency") or "").strip() or None,
                dataset_kind=str(row.get("dataset_kind") or dataset_kind),
                source_id=source_id,
                source_checksum=checksum,
                source_terms=source_terms,
                methodology=methodology,
                published_at=str(row.get("published_at") or available_at),
                available_at=str(row.get("available_at") or available_at),
                observed_at=str(row.get("observed_at") or row.get("period_start") or row.get("date")),
                ingested_at=ingested_at,
                revision=_csv_revision(row.get("revision")),
            )
        )
    return [_validate(row) for row in parsed]


def _csv_revision(value: object) -> int:
    if value is None or not str(value).strip():
        return 1
    raise MacroWarehouseError(
        "CSV revision identity is textual; use the typed local import path"
    )


def _transformed_value(value: float, source_unit: str, target_unit: str) -> float:
    if source_unit == target_unit:
        return value
    factor = _UNIT_FACTORS.get((source_unit, target_unit))
    if factor is None:
        raise MacroWarehouseError(f"unsupported unit conversion: {source_unit} -> {target_unit}")
    return value * factor


def transform_observations(
    observations: Iterable[MacroObservation],
    *,
    target_unit: str | None = None,
    target_frequency: str | None = None,
    transformation_version: str = "macro-transform.v1",
) -> list[MacroObservation]:
    """Return derived rows while retaining source IDs and reversible metadata."""

    source_rows = [_validate(row) for row in observations]
    if not source_rows:
        return []
    if target_frequency is not None and target_frequency not in _ALLOWED_FREQUENCIES:
        raise MacroWarehouseError(f"unsupported target frequency: {target_frequency}")
    if target_frequency in {None, "irregular"} or target_frequency == source_rows[0].frequency:
        grouped = [[row] for row in source_rows]
    else:
        frame = pd.DataFrame([row.model_dump(mode="json") for row in source_rows])
        frame["period"] = pd.to_datetime(frame["period_start"], utc=True)
        if target_frequency == "quarterly":
            frame["group_period"] = frame["period"].dt.tz_localize(None).dt.to_period("Q").astype(str)
        elif target_frequency == "annual":
            frame["group_period"] = frame["period"].dt.year.astype(str)
        else:
            raise MacroWarehouseError(f"frequency conversion to {target_frequency} is not supported")
        grouped = []
        for _, group in frame.groupby(["dataset_id", "series_id", "country", "currency", "group_period"], dropna=False, sort=True):
            grouped.append([source_rows[int(index)] for index in group.index])

    transformed: list[MacroObservation] = []
    for group in grouped:
        first = group[0]
        unit = target_unit or first.unit
        frequency = target_frequency or first.frequency
        value = sum(_transformed_value(row.value, row.unit, unit) for row in group) / len(group)
        source_ids = tuple(sorted(row.observation_id for row in group))
        raw = json.dumps({"source_ids": source_ids, "unit": unit, "frequency": frequency, "version": transformation_version}, sort_keys=True).encode("utf-8")
        transformed.append(
            _validate(
                first.model_copy(
                    update={
                        "period_start": min(row.period_start for row in group),
                        "value": value,
                        "unit": unit,
                        "frequency": frequency,
                        "available_at": max(row.available_at for row in group),
                        "published_at": max(row.published_at for row in group),
                        "observed_at": max(row.observed_at for row in group),
                        "ingested_at": max(row.ingested_at for row in group),
                        "revision": max(row.revision for row in group),
                        "transformation_version": transformation_version,
                        "source_observation_ids": source_ids,
                        "source_checksum": _source_checksum(raw),
                    }
                )
            )
        )
    return transformed


def _curve_history_issue(rows: Iterable[MacroObservation], curve_id: str) -> str | None:
    """Return an integrity error for a persisted curve revision history."""

    snapshots: dict[tuple[datetime, int], dict[str, object]] = {}
    for row in rows:
        if row.dataset_id != f"curve:{curve_id}" or row.curve_id != curve_id:
            return "curve dataset identity does not match curve_id"
        if row.dataset_kind != "risk_free":
            return "curve dataset_kind must be risk_free"
        if row.unit != "decimal":
            return "curve unit must be decimal"
        effective_at = _timestamp_value(_explicit_timestamp(row.observed_at, "observed_at"))
        available_at = _timestamp_value(_explicit_timestamp(row.available_at, "available_at"))
        key = (effective_at, row.revision)
        point_key = row.tenor_years
        signature = (
            row.dataset_kind,
            row.curve_version,
            row.curve_type,
            row.curve_point_count,
            row.currency,
            row.source_id,
            row.source_authority,
            row.source_checksum,
            row.source_terms,
            row.methodology,
            row.published_at,
            row.interpolation,
            row.extrapolation_allowed,
            row.compounding,
            row.day_count,
            row.reinvestment,
            row.freshness,
            row.freshness_status,
        )
        snapshot = snapshots.setdefault(
            key,
            {"available_at": available_at, "signature": signature, "tenors": set()},
        )
        if snapshot["available_at"] != available_at or snapshot["signature"] != signature:
            return "curve revision identity is conflicted"
        tenors = snapshot["tenors"]
        assert isinstance(tenors, set)
        if point_key in tenors:
            return "curve revision identity is duplicated; curve tenor points are duplicated"
        tenors.add(point_key)

    by_effective: dict[datetime, list[tuple[int, datetime]]] = {}
    for (effective_at, revision), snapshot in snapshots.items():
        available_at = snapshot["available_at"]
        assert isinstance(available_at, datetime)
        by_effective.setdefault(effective_at, []).append((revision, available_at))
    for revisions in by_effective.values():
        previous_revision = 0
        for revision, _available_at in sorted(revisions, key=lambda item: (item[1], item[0])):
            if revision <= previous_revision:
                return "curve revision history regresses"
            previous_revision = revision
    return None


def _macro_manifest(
    rows: list[MacroObservation],
    resolved_run_id: str,
    batch_hash: str,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "warehouse_version": "macro-warehouse.v1",
        "run_id": resolved_run_id,
        "batch_sha256": batch_hash,
        "row_count": len(rows),
        "dataset_ids": sorted({row.dataset_id for row in rows}),
        "source_ids": sorted({row.source_id for row in rows}),
        "source_terms": sorted({row.source_terms for row in rows}),
        "transformations": sorted({row.transformation_version for row in rows}),
        "execution_allowed": False,
    }


def _append_macro_rows(
    store: BitemporalStore,
    rows: list[MacroObservation],
    *,
    resolved_run_id: str,
    connection: sqlite3.Connection,
) -> None:
    for row in rows:
        store.record_observation(
            dataset_id=row.dataset_id,
            entity_id=row.series_id,
            stable_id=row.stable_id,
            value=row.ledger_value(),
            source_id=row.source_id,
            source_checksum=row.source_checksum,
            revision=row.revision,
            valid_from=f"{row.period_start}T00:00:00+00:00",
            available_at=row.available_at,
            observed_at=row.observed_at,
            published_at=row.published_at,
            run_id=resolved_run_id,
            ingested_at=row.ingested_at,
            revised_at=row.revised_at,
            timezone_confidence=row.timezone_confidence,
            availability_confidence=row.availability_confidence,
            _connection=connection,
        )


class MacroWarehouse:
    """Adapter exposing macro observations and explicit unavailable summaries."""

    def _manifest_path(self, root: Path) -> Path:
        return Path(root) / "data" / "macro_warehouse" / "manifest.json"

    def ingest(self, observations: Iterable[MacroObservation], *, root: Path, run_id: str | None = None) -> dict[str, object]:
        rows = [_validate(row) for row in observations]
        if not rows:
            raise MacroWarehouseError("cannot ingest an empty macro batch")
        batch_payload = [row.model_dump(mode="json") for row in rows]
        batch_hash = _source_checksum(json.dumps(batch_payload, sort_keys=True, separators=(",", ":")))
        resolved_run_id = run_id or f"macro-{batch_hash[:24]}"
        manifest = _macro_manifest(rows, resolved_run_id, batch_hash)
        try:
            with BitemporalStore(Path(root)) as store:
                with store.store.transaction() as connection:
                    _append_macro_rows(
                        store,
                        rows,
                        resolved_run_id=resolved_run_id,
                        connection=connection,
                    )
                    atomic_write_json(self._manifest_path(Path(root)), manifest)
        except BitemporalError as exc:
            raise MacroWarehouseError(str(exc)) from exc
        return manifest

    def observations(self, *, root: Path, dataset_id: str | None = None) -> list[MacroObservation]:
        with BitemporalStore(Path(root)) as store:
            rows = store.observations(dataset_id)
        return [MacroObservation.from_ledger(row.__dict__) for row in rows]

    def observations_as_of(self, *, root: Path, decision_time: str) -> list[MacroObservation]:
        """Return the latest valid revision available at a decision cutoff."""

        dataset_ids = sorted({row.dataset_id for row in self.observations(root=root)})
        selected: list[MacroObservation] = []
        for dataset_id in dataset_ids:
            frame = self.as_of(root=root, dataset_id=dataset_id, decision_time=decision_time)
            selected.extend(MacroObservation.model_validate(row) for row in frame.to_dict("records"))
        return selected

    def as_of(self, *, root: Path, dataset_id: str, decision_time: str) -> pd.DataFrame:
        with BitemporalStore(Path(root)) as store:
            frame = store.as_of(dataset_id, decision_time)
        if frame.empty:
            return pd.DataFrame(columns=list(MacroObservation.model_fields))
        payloads = [MacroObservation.from_ledger(row).model_dump(mode="json") for row in frame.to_dict("records")]
        return pd.DataFrame(payloads)

    def ingest_curve(self, snapshot: CurveSnapshot, *, root: Path) -> dict[str, object]:
        curve = _validate_curve(snapshot)
        observations = [
            MacroObservation(
                dataset_id=f"curve:{curve.curve_id}",
                series_id=f"{curve.curve_id}:{point.tenor_years:g}Y",
                period_start=curve.effective_at[:10],
                value=point.rate,
                unit="decimal",
                frequency="irregular",
                currency=curve.currency,
                dataset_kind="risk_free",
                source_id=curve.source_id,
                source_authority=curve.source_authority,
                source_checksum=curve.source_checksum,
                source_terms=curve.source_terms,
                methodology=curve.methodology,
                published_at=curve.published_at,
                available_at=curve.available_at,
                observed_at=curve.effective_at,
                ingested_at=curve.ingested_at,
                revision=curve.revision,
                curve_id=curve.curve_id,
                curve_type=curve.curve_type,
                curve_version=curve.curve_version,
                tenor_years=point.tenor_years,
                curve_point_count=len(curve.points),
                interpolation=curve.interpolation,
                extrapolation_allowed=False,
                compounding=curve.compounding,
                day_count=curve.day_count,
                reinvestment=curve.reinvestment,
                freshness=curve.freshness,
                freshness_status=curve.freshness_status,
            )
            for point in curve.points
        ]
        batch_payload = [row.model_dump(mode="json") for row in observations]
        batch_hash = _source_checksum(
            json.dumps(batch_payload, sort_keys=True, separators=(",", ":"))
        )
        resolved_run_id = f"macro-{batch_hash[:24]}"
        manifest = _macro_manifest(observations, resolved_run_id, batch_hash)
        try:
            with BitemporalStore(Path(root)) as store:
                with store.store.transaction() as connection:
                    existing = [
                        MacroObservation.from_ledger(row.__dict__)
                        for row in store.observations(
                            f"curve:{curve.curve_id}",
                            _connection=connection,
                        )
                    ]
                    effective_at = _timestamp_value(curve.effective_at)
                    if any(
                        _timestamp_value(
                            _explicit_timestamp(row.observed_at, "observed_at")
                        )
                        == effective_at
                        and row.revision >= curve.revision
                        for row in existing
                    ):
                        raise MacroWarehouseError(
                            "curve revision must advance without duplicate identity"
                        )
                    history_issue = _curve_history_issue(
                        [*existing, *observations], curve.curve_id
                    )
                    if history_issue is not None:
                        raise MacroWarehouseError(history_issue)
                    _append_macro_rows(
                        store,
                        observations,
                        resolved_run_id=resolved_run_id,
                        connection=connection,
                    )
                    atomic_write_json(self._manifest_path(Path(root)), manifest)
        except BitemporalError as exc:
            raise MacroWarehouseError(str(exc)) from exc
        return manifest

    def ingest_benchmark(
        self, metadata: BenchmarkMetadata, *, root: Path
    ) -> dict[str, object]:
        metadata = _validate_benchmark(metadata)
        row = MacroObservation(
            dataset_id=f"benchmark:{metadata.benchmark_id}",
            series_id=metadata.benchmark_id,
            period_start=_timestamp(metadata.effective_at, "effective_at")[:10],
            value=float(metadata.revision),
            unit="metadata_version",
            frequency="irregular",
            currency=metadata.currency.upper(),
            dataset_kind="benchmark",
            source_id=metadata.source_id,
            source_checksum=metadata.source_checksum,
            source_terms=metadata.source_terms,
            methodology=metadata.methodology,
            published_at=metadata.available_at,
            available_at=metadata.available_at,
            observed_at=metadata.effective_at,
            ingested_at=metadata.ingested_at,
            revision=metadata.revision,
            benchmark_id=metadata.benchmark_id,
            benchmark_version=metadata.version,
            benchmark_category=metadata.category,
            source_observation_ids=tuple(sorted(metadata.coverage)),
        )
        return self.ingest([row], root=root)

    def curve_rate(
        self,
        *,
        root: Path,
        curve_id: str,
        tenor_years: float,
        decision_time: str,
    ) -> dict[str, object]:
        try:
            history = self.observations(
                root=root, dataset_id=f"curve:{curve_id}"
            )
            cutoff = _timestamp_value(
                _explicit_timestamp(decision_time, "decision_time")
            )
            eligible_history = [
                row
                for row in history
                if _timestamp_value(
                    _explicit_timestamp(row.available_at, "available_at")
                )
                <= cutoff
            ]
            history_issue = _curve_history_issue(eligible_history, curve_id)
            if history_issue is not None:
                return {
                    "status": "unavailable",
                    "reason": history_issue,
                    "curve_id": curve_id,
                    "execution_allowed": False,
                }
            frame = self.as_of(
                root=root,
                dataset_id=f"curve:{curve_id}",
                decision_time=decision_time,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "status": "unavailable",
                "reason": f"curve snapshot row is malformed: {exc}",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        if frame.empty:
            return {
                "status": "unavailable",
                "reason": "no then-known curve snapshot is available",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        try:
            rows = [
                MacroObservation.model_validate(item)
                for item in frame.to_dict("records")
            ]
        except ValueError as exc:
            return {
                "status": "unavailable",
                "reason": f"curve snapshot row is malformed: {exc}",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        if any(
            row.dataset_id != f"curve:{curve_id}" or row.curve_id != curve_id
            for row in rows
        ):
            return {
                "status": "unavailable",
                "reason": "curve dataset identity does not match curve_id",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        if any(
            row.availability_confidence != "exact"
            or row.timezone_confidence != "exact"
            for row in rows
        ):
            return {
                "status": "unavailable",
                "reason": "curve availability and timezone confidence must be exact",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        if any(
            _timestamp_value(_explicit_timestamp(row.published_at, "published_at"))
            > _timestamp_value(_explicit_timestamp(row.available_at, "available_at"))
            for row in rows
        ):
            return {
                "status": "unavailable",
                "reason": "curve published_at cannot be after available_at",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        latest_effective_at = max(
            _timestamp_value(_explicit_timestamp(row.observed_at, "observed_at"))
            for row in rows
        )
        rows = [
            row
            for row in rows
            if _timestamp_value(_explicit_timestamp(row.observed_at, "observed_at"))
            == latest_effective_at
        ]
        metadata_signatures = {
            (
                row.revision,
                row.curve_id,
                row.source_checksum,
                row.source_terms,
                row.curve_version,
                row.curve_type,
                row.curve_point_count,
                row.currency,
                row.methodology,
                row.observed_at,
                row.published_at,
                row.available_at,
                row.interpolation,
                row.extrapolation_allowed,
                row.compounding,
                row.day_count,
                row.reinvestment,
                row.freshness,
                row.freshness_status,
                row.source_id,
                row.source_authority,
            )
            for row in rows
        }
        if len(metadata_signatures) != 1:
            return {
                "status": "unavailable",
                "reason": "curve snapshot metadata is conflicted",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        point_count = rows[0].curve_point_count
        if point_count is None or point_count != len(rows):
            return {
                "status": "unavailable",
                "reason": "curve snapshot is incomplete",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        tenors = [row.tenor_years for row in rows]
        if any(tenor is None for tenor in tenors) or len(set(tenors)) != len(tenors):
            return {
                "status": "unavailable",
                "reason": "curve tenor points must be complete and unique",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        if rows[0].reinvestment != "reinvested_income":
            return {
                "status": "unavailable",
                "reason": "curve reinvestment convention is unsupported",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        if any(
            row.freshness is not None
            and row.freshness_status is not None
            and row.freshness != row.freshness_status
            for row in rows
        ):
            return {
                "status": "unavailable",
                "reason": "curve snapshot freshness is conflicted",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        if any(
            not row.source_id.strip()
            or row.source_authority not in _OFFICIAL_CURVE_AUTHORITIES
            or not row.source_terms.strip()
            or not row.methodology.strip()
            or not row.curve_version
            or not row.curve_type
            or not row.interpolation
            or len(row.source_checksum) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in row.source_checksum)
            for row in rows
        ):
            return {
                "status": "unavailable",
                "reason": "curve snapshot official lineage is incomplete",
                "curve_id": curve_id,
                "execution_allowed": False,
            }
        points = tuple(
            CurvePoint(tenor_years=float(row.tenor_years), rate=row.value)
            for row in rows
        )
        try:
            rate = interpolate_curve(
                points,
                tenor_years,
                policy=str(rows[0].interpolation),
                extrapolation_allowed=rows[0].extrapolation_allowed,
            )
        except MacroWarehouseError as exc:
            return {
                "status": "unavailable",
                "reason": str(exc),
                "curve_id": curve_id,
                "coverage": sorted(point.tenor_years for point in points),
                "interpolation": rows[0].interpolation,
                "execution_allowed": False,
            }
        return {
            "status": "available",
            "curve_id": curve_id,
            "dataset_kind": rows[0].dataset_kind,
            "curve_type": rows[0].curve_type,
            "curve_version": rows[0].curve_version,
            "curve_revision": rows[0].revision,
            "currency": rows[0].currency,
            "tenor_years": tenor_years,
            "rate": rate,
            "unit": "decimal",
            "source_id": rows[0].source_id,
            "source_authority": rows[0].source_authority,
            "source_checksum": rows[0].source_checksum,
            "source_terms": rows[0].source_terms,
            "methodology": rows[0].methodology,
            "effective_at": _timestamp(rows[0].observed_at, "effective_at"),
            "published_at": _timestamp(rows[0].published_at, "published_at"),
            "available_at": _timestamp(rows[0].available_at, "available_at"),
            "vintage": _timestamp(rows[0].available_at, "available_at"),
            "interpolation": rows[0].interpolation,
            "extrapolation_allowed": rows[0].extrapolation_allowed,
            "compounding": rows[0].compounding,
            "day_count": rows[0].day_count,
            "reinvestment": rows[0].reinvestment,
            "freshness": rows[0].freshness,
            "freshness_status": rows[0].freshness_status,
            "fallback": False,
            "execution_allowed": False,
        }

    def risk_free_rate(
        self,
        *,
        root: Path,
        mappings: Iterable[RiskFreeProxyMapping],
        currency: str,
        horizon_years: float,
        decision_time: str,
    ) -> dict[str, object]:
        matches = [
            item
            for item in mappings
            if item.currency.upper() == currency.upper()
            and item.minimum_horizon_years <= horizon_years <= item.maximum_horizon_years
        ]
        if not matches:
            return {
                "status": "unavailable",
                "reason": "no currency+horizon cash proxy mapping is declared",
                "currency": currency.upper(),
                "horizon_years": horizon_years,
                "execution_allowed": False,
            }
        if len(matches) > 1:
            return {
                "status": "unavailable",
                "reason": "multiple currency+horizon cash proxy mappings overlap",
                "currency": currency.upper(),
                "horizon_years": horizon_years,
                "execution_allowed": False,
            }
        mapping = matches[0]
        for index, curve_id in enumerate((mapping.curve_id, *mapping.fallback_curve_ids)):
            selected = self.curve_rate(
                root=root,
                curve_id=curve_id,
                tenor_years=horizon_years,
                decision_time=decision_time,
            )
            if selected["status"] == "available":
                if str(selected.get("currency", "")).upper() != currency.upper():
                    continue
                return {
                    **selected,
                    "mapping_methodology": mapping.methodology,
                    "fallback": index > 0,
                    "fallback_from": mapping.curve_id if index > 0 else None,
                }
        return {
            "status": "unavailable",
            "reason": "declared primary and fallback curves are unavailable",
            "currency": currency.upper(),
            "horizon_years": horizon_years,
            "fallback_curve_ids": list(mapping.fallback_curve_ids),
            "execution_allowed": False,
        }

    def cash_comparison(
        self,
        *,
        root: Path,
        mappings: Iterable[RiskFreeProxyMapping],
        currency: str,
        start_date: str,
        end_date: str,
        decision_time: str,
        adjusted_prices: object,
        inflation_context: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Build a descriptive cash comparison from then-known spot evidence."""

        from etf_cockpit.features.cash_comparison import (
            build_cash_comparison,
            period_start_knowledge_cutoff,
        )

        try:
            from etf_cockpit.features.cash_comparison import year_fraction

            mapping_rows = tuple(mappings)
            knowledge_cutoff = period_start_knowledge_cutoff(start_date)
            last_result: dict[str, object] | None = None
            for day_count in ("ACT/365F", "ACT/360", "ACT/ACT-ISDA"):
                selected = self.risk_free_rate(
                    root=root,
                    mappings=mapping_rows,
                    currency=currency,
                    horizon_years=year_fraction(start_date, end_date, day_count),
                    decision_time=knowledge_cutoff,
                )
                if selected.get("status") != "available":
                    if last_result is None:
                        last_result = dict(selected)
                    continue
                if selected.get("day_count") != day_count:
                    if last_result is None:
                        last_result = {
                            "status": "unavailable",
                            "reason": "selected curve day count does not match the requested exact tenor",
                            "currency": str(currency).upper(),
                            "horizon_years": year_fraction(start_date, end_date, day_count),
                            "execution_allowed": False,
                        }
                    continue
                result = build_cash_comparison(
                    adjusted_prices=adjusted_prices,
                    start_date=start_date,
                    end_date=end_date,
                    instrument_currency=currency,
                    cash_evidence=selected,
                    decision_time=decision_time,
                    knowledge_cutoff=knowledge_cutoff,
                    inflation_context=inflation_context,
                ).as_dict()
                if result.get("status") == "available":
                    return result
                last_result = result
            return last_result or {
                "status": "unavailable",
                "reason": "no currency+horizon cash proxy mapping is declared",
                "execution_allowed": False,
            }
        except (
            ArithmeticError,
            BitemporalError,
            MacroWarehouseError,
            TypeError,
            ValueError,
            OSError,
        ) as exc:
            return {
                "status": "unavailable",
                "reason": f"cash comparison evidence is malformed: {type(exc).__name__}",
                "currency": str(currency).upper(),
                "start_date": str(start_date),
                "end_date": str(end_date),
                "execution_allowed": False,
            }

    cash_total_return = cash_comparison

    def issuer_credit_curve(
        self, *, issuer_id: str, decision_time: str
    ) -> dict[str, object]:
        return {
            "status": "unavailable",
            "reason": "issuer-specific credit curves are unsupported",
            "issuer_id": issuer_id,
            "decision_time": decision_time,
            "execution_allowed": False,
        }

    def curve_benchmark_coverage(
        self, *, root: Path, decision_time: str
    ) -> dict[str, object]:
        rows = self.observations_as_of(root=root, decision_time=decision_time)
        curves: list[MacroObservation] = []
        for curve_id in sorted({row.curve_id for row in rows if row.curve_id}):
            candidates = [row for row in rows if row.curve_id == curve_id]
            latest = max(row.observed_at for row in candidates)
            curves.extend(row for row in candidates if row.observed_at == latest)
        benchmarks: list[MacroObservation] = []
        for benchmark_id in sorted(
            {row.benchmark_id for row in rows if row.benchmark_id}
        ):
            candidates = [row for row in rows if row.benchmark_id == benchmark_id]
            latest = max(row.observed_at for row in candidates)
            selected = [row for row in candidates if row.observed_at == latest]
            if len({row.benchmark_version for row in selected}) != 1:
                continue
            benchmarks.extend(selected)
        return {
            "status": "available" if curves or benchmarks else "unavailable",
            "curve_ids": sorted({str(row.curve_id) for row in curves}),
            "curve_types": sorted({str(row.curve_type) for row in curves}),
            "currencies": sorted({str(row.currency) for row in curves if row.currency}),
            "benchmark_ids": sorted({str(row.benchmark_id) for row in benchmarks}),
            "benchmark_versions": sorted(
                {str(row.benchmark_version) for row in benchmarks}
            ),
            "source_ids": sorted({row.source_id for row in curves + benchmarks}),
            "methodologies": sorted(
                {row.methodology for row in curves + benchmarks if row.methodology}
            ),
            "decision_time": decision_time,
            "issuer_credit": "unavailable",
            "execution_allowed": False,
        }

    def summary(self, *, root: Path, decision_time: str | None = None) -> dict[str, object]:
        try:
            rows = self.observations(root=Path(root))
        except (BitemporalError, MacroWarehouseError, OSError) as exc:
            return {"status": "unavailable", "reason": f"{type(exc).__name__}: local warehouse requires manual review", "row_count": 0}
        if not rows:
            return {"status": "unavailable", "reason": "no local macro/factor snapshots have been ingested", "row_count": 0}
        latest = max(row.observed_at for row in rows)
        if decision_time:
            available = [row for row in rows if row.available_at <= _timestamp(decision_time, "decision_time")]
        else:
            available = rows
        return {
            "status": "available" if available else "unavailable",
            "row_count": len(available),
            "total_row_count": len(rows),
            "dataset_ids": sorted({row.dataset_id for row in available}),
            "dataset_kinds": sorted({row.dataset_kind for row in available}),
            "latest_observed_at": latest,
            "missing_country_or_currency_count": sum(not row.country or not row.currency for row in available),
            "decision_time": decision_time,
            "execution_allowed": False,
        }


__all__ = [
    "BenchmarkMetadata",
    "CurvePoint",
    "CurveSnapshot",
    "MacroObservation",
    "MacroWarehouse",
    "MacroWarehouseError",
    "RiskFreeProxyMapping",
    "RISK_FREE_PROXY_CONFIG_PATH",
    "interpolate_curve",
    "load_risk_free_proxy_mappings",
    "parse_csv_records",
    "parse_world_bank_records",
    "transform_observations",
]
