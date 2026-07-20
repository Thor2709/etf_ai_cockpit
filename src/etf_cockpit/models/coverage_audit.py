"""Deterministic local coverage and subgroup model-monitoring evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import REPORTS_DIR
from etf_cockpit.models.calibration import evaluate_forecast_calibration


COVERAGE_SCHEMA_VERSION = "coverage-audit.v1"
DIMENSIONS = ("geography", "sector", "size", "currency", "listing")
_UNAVAILABLE = "unavailable"
_DIMENSION_COLUMNS = {
    "geography": ("geography", "region", "country"),
    "sector": ("sector",),
    "size": ("size", "size_bucket", "market_cap_bucket"),
    "currency": ("currency",),
    "listing": ("listing", "exchange", "listing_venue"),
}


@dataclass(frozen=True)
class CoverageThresholds:
    """Explicit thresholds; no aggregate metric can override these limits."""

    minimum_observation_coverage: float = 0.8

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_observation_coverage <= 1.0:
            raise ValueError("minimum_observation_coverage must be in (0, 1]")


@dataclass(frozen=True)
class CoverageGroup:
    dimension: str
    bucket: str
    universe_count: int
    observed_count: int
    observation_coverage: float
    forecast_count: int
    matured_forecasts: int
    mean_mase: float | None
    directional_accuracy: float | None
    interval_coverage: float | None
    selected_count: int
    status: str
    authority: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"warnings": list(self.warnings)}


@dataclass(frozen=True)
class CoverageAudit:
    schema_version: str
    as_of_date: str | None
    universe_count: int
    observed_instrument_count: int
    supported_universe: tuple[str, ...]
    unsupported_zones: tuple[str, ...]
    authority: str
    thresholds: CoverageThresholds
    groups: tuple[CoverageGroup, ...]
    provenance: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "as_of_date": self.as_of_date,
            "universe_count": self.universe_count,
            "observed_instrument_count": self.observed_instrument_count,
            "supported_universe": list(self.supported_universe),
            "unsupported_zones": list(self.unsupported_zones),
            "authority": self.authority,
            "thresholds": asdict(self.thresholds),
            "groups": [group.to_dict() for group in self.groups],
            "provenance": dict(self.provenance),
        }


def build_coverage_audit(
    universe: Iterable[object],
    prices: pd.DataFrame | None,
    forecasts: pd.DataFrame | None = None,
    signals: Iterable[object] = (),
    *,
    as_of_date: date | str | None = None,
    thresholds: CoverageThresholds | None = None,
) -> CoverageAudit:
    """Build coverage evidence from the enabled local universe.

    Coverage is based on rows containing ``adjusted_close``. Missing subgroup
    metadata is an explicit unsupported zone. Model metrics are descriptive
    only and never upgrade a group whose observation coverage is below the
    configured threshold.
    """

    policy = thresholds or CoverageThresholds()
    records = _universe_records(universe)
    instrument_ids = tuple(sorted(records))
    price_ids = _observed_price_ids(prices)
    calibration = _calibration_by_instrument(forecasts, prices)
    forecast_counts = _forecast_counts(forecasts)
    selected_counts = _selected_counts(signals)
    groups: list[CoverageGroup] = []
    supported_by_instrument: dict[str, bool] = {instrument_id: True for instrument_id in instrument_ids}

    for dimension in DIMENSIONS:
        buckets: dict[str, list[str]] = defaultdict(list)
        for instrument_id in instrument_ids:
            buckets[_dimension_value(records[instrument_id], dimension)].append(instrument_id)
        for bucket, members in sorted(buckets.items()):
            member_ids = tuple(sorted(members))
            observed_count = len(set(member_ids) & price_ids)
            coverage = round(observed_count / len(member_ids), 6) if member_ids else 0.0
            warnings: list[str] = []
            if bucket == _UNAVAILABLE:
                warnings.append(f"missing_{dimension}_metadata")
            if observed_count == 0:
                warnings.append("no_adjusted_price_history")
            elif coverage < policy.minimum_observation_coverage:
                warnings.append("coverage_below_threshold")
            if coverage < 1.0 and observed_count > 0:
                warnings.append("synthetic_missingness_observed")
            status = "supported" if not warnings else "unsupported"
            authority = "evidence_only" if status == "supported" else "unsupported"
            for instrument_id in member_ids:
                supported_by_instrument[instrument_id] &= status == "supported"
            metric = _group_metric(member_ids, calibration)
            groups.append(
                CoverageGroup(
                    dimension=dimension,
                    bucket=bucket,
                    universe_count=len(member_ids),
                    observed_count=observed_count,
                    observation_coverage=coverage,
                    forecast_count=sum(forecast_counts.get(instrument_id, 0) for instrument_id in member_ids),
                    matured_forecasts=metric[0],
                    mean_mase=metric[1],
                    directional_accuracy=metric[2],
                    interval_coverage=metric[3],
                    selected_count=sum(selected_counts.get(instrument_id, 0) for instrument_id in member_ids),
                    status=status,
                    authority=authority,
                    warnings=tuple(sorted(set(warnings))),
                )
            )

    unsupported = tuple(f"{group.dimension}:{group.bucket}" for group in groups if group.status != "supported")
    supported = tuple(sorted(instrument_id for instrument_id, is_supported in supported_by_instrument.items() if is_supported))
    authority = "evidence_only" if groups and not unsupported else "manual_review" if groups else "unavailable"
    return CoverageAudit(
        schema_version=COVERAGE_SCHEMA_VERSION,
        as_of_date=_date_text(as_of_date),
        universe_count=len(instrument_ids),
        observed_instrument_count=len(set(instrument_ids) & price_ids),
        supported_universe=supported,
        unsupported_zones=unsupported,
        authority=authority,
        thresholds=policy,
        groups=tuple(groups),
        provenance={
            "universe": "enabled local configuration",
            "price_value": "adjusted_close",
            "aggregate_metrics_inherit_authority": False,
            "protected_attribute_inference": False,
            "optional_forecasts": bool(forecasts is not None and not forecasts.empty),
        },
    )


def write_coverage_audit(report: CoverageAudit, directory: Path = REPORTS_DIR) -> tuple[Path, Path]:
    """Write a deterministic JSON/Markdown local audit and return both paths."""

    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    json_path = directory / "coverage_audit.json"
    markdown_path = directory / "coverage_audit.md"
    json_path.write_text(payload, encoding="utf-8")
    markdown_path.write_text(_markdown(report, checksum), encoding="utf-8")
    return json_path, markdown_path


def coverage_summary_lines(report: CoverageAudit, *, limit: int = 12) -> tuple[str, ...]:
    """Return compact, UI-safe lines without hiding unsupported groups."""

    lines = [
        f"Authority: {report.authority}",
        f"Observed adjusted-price universe: {report.observed_instrument_count}/{report.universe_count}",
        f"Supported instruments: {len(report.supported_universe)}",
        f"Unsupported zones: {len(report.unsupported_zones)}",
    ]
    lines.extend(
        f"{group.dimension}={group.bucket} | coverage={group.observation_coverage:.0%} | "
        f"status={group.status} | authority={group.authority} | "
        f"mase={_metric_text(group.mean_mase)} | direction={_metric_text(group.directional_accuracy)}"
        for group in report.groups[: max(0, int(limit))]
    )
    return tuple(lines)


def _universe_records(universe: Iterable[object]) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for item in universe:
        enabled = _value(item, "enabled")
        if enabled is False:
            continue
        instrument_id = str(_value(item, "id", "instrument_id") or "").strip()
        if not instrument_id:
            continue
        records[instrument_id] = {
            name: _value(item, *aliases)
            for name, aliases in _DIMENSION_COLUMNS.items()
        }
    return records


def _dimension_value(record: Mapping[str, object], dimension: str) -> str:
    value = record.get(dimension)
    text = str(value or "").strip()
    return text or _UNAVAILABLE


def _observed_price_ids(prices: pd.DataFrame | None) -> set[str]:
    if prices is None or prices.empty or not {"etf_id", "adjusted_close"}.issubset(prices.columns):
        return set()
    values = pd.to_numeric(prices["adjusted_close"], errors="coerce")
    return set(prices.loc[values.notna(), "etf_id"].astype(str).str.strip())


def _calibration_by_instrument(forecasts: pd.DataFrame | None, prices: pd.DataFrame | None) -> dict[str, dict[str, float | int | None]]:
    if forecasts is None or forecasts.empty or prices is None or prices.empty:
        return {}
    try:
        frame = forecasts.copy()
        if "etf_id" not in frame and "instrument_id" in frame:
            frame["etf_id"] = frame["instrument_id"]
        evaluated = evaluate_forecast_calibration(frame, prices)
    except (KeyError, TypeError, ValueError):
        return {}
    if evaluated.empty:
        return {}
    values: dict[str, dict[str, float | int | None]] = {}
    for instrument_id, group in evaluated.groupby("instrument_id", sort=False):
        values[str(instrument_id)] = {
            "matured_forecasts": int(pd.to_numeric(group["matured_forecasts"], errors="coerce").fillna(0).sum()),
            "mean_mase": _mean(group["oos_mase"]),
            "directional_accuracy": _mean(group["oos_directional_accuracy"]),
            "interval_coverage": _mean(group["q10_q90_coverage"]),
        }
    return values


def _group_metric(member_ids: Sequence[str], calibration: Mapping[str, Mapping[str, float | int | None]]) -> tuple[int, float | None, float | None, float | None]:
    rows = [calibration[instrument_id] for instrument_id in member_ids if instrument_id in calibration]
    return (
        sum(int(row.get("matured_forecasts") or 0) for row in rows),
        _mean_values(row.get("mean_mase") for row in rows),
        _mean_values(row.get("directional_accuracy") for row in rows),
        _mean_values(row.get("interval_coverage") for row in rows),
    )


def _forecast_counts(forecasts: pd.DataFrame | None) -> dict[str, int]:
    if forecasts is None or forecasts.empty:
        return {}
    column = "etf_id" if "etf_id" in forecasts.columns else "instrument_id" if "instrument_id" in forecasts.columns else None
    if column is None:
        return {}
    return forecasts.assign(_instrument=forecasts[column].astype(str)).groupby("_instrument").size().astype(int).to_dict()


def _selected_counts(signals: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for signal in signals:
        instrument_id = str(_value(signal, "etf_id", "instrument_id") or "").strip()
        action = str(_value(signal, "action", "research_state") or "").strip().casefold()
        if instrument_id and action not in {"", "hold", "no_trade", "manual_review", "unavailable", "blocked"}:
            counts[instrument_id] += 1
    return dict(counts)


def _value(item: object, *names: str) -> object:
    for name in names:
        if isinstance(item, Mapping) and name in item:
            return item[name]
        value = getattr(item, name, None)
        if value is not None:
            return value
    return None


def _mean(series: pd.Series) -> float | None:
    return _mean_values(series.tolist())


def _mean_values(values: Iterable[object]) -> float | None:
    clean = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce").dropna()
    return None if clean.empty else round(float(clean.mean()), 6)


def _date_text(value: date | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def _metric_text(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _markdown(report: CoverageAudit, checksum: str) -> str:
    lines = [
        "# Local data coverage and model monitoring audit",
        "",
        f"- Schema: `{report.schema_version}`",
        f"- As of: `{report.as_of_date or 'unavailable'}`",
        f"- Authority: `{report.authority}`",
        f"- Report SHA-256: `{checksum}`",
        "- Aggregate metrics never upgrade a low-coverage subgroup.",
        "",
        "## Coverage groups",
        "",
        "| Dimension | Bucket | Universe | Observed | Coverage | Forecasts | Matured | Status | Authority | Warnings |",
        "|---|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for group in report.groups:
        lines.append(
            f"| {group.dimension} | {group.bucket} | {group.universe_count} | {group.observed_count} | "
            f"{group.observation_coverage:.1%} | {group.forecast_count} | {group.matured_forecasts} | "
            f"{group.status} | {group.authority} | {', '.join(group.warnings) or 'none'} |"
        )
    lines.extend(
        [
            "",
            "## Supported universe",
            "",
            ", ".join(report.supported_universe) or "None",
            "",
            "## Unsupported zones",
            "",
            ", ".join(report.unsupported_zones) or "None",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "COVERAGE_SCHEMA_VERSION",
    "DIMENSIONS",
    "CoverageAudit",
    "CoverageGroup",
    "CoverageThresholds",
    "build_coverage_audit",
    "coverage_summary_lines",
    "write_coverage_audit",
]
