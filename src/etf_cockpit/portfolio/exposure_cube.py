"""Coverage-aware portfolio exposure views built on canonical holdings services."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import math
from numbers import Real
from typing import Literal, Mapping

import pandas as pd

from etf_cockpit.analysis.look_through import LookThroughSummary, calculate_look_through
from etf_cockpit.data.event_calendar import normalise_event_decision_time
from etf_cockpit.features.overlap import (
    DirectOverlapReport,
    ExposureContributor,
    LookThroughExposure,
    calculate_direct_overlap,
)

_TOLERANCE = 1e-9
_UNKNOWN = "Unknown/Unmapped"
_MAX_DEPTH = 8
_DIMENSIONS = (
    "asset_class",
    "sector",
    "industry",
    "economic_country",
    "region",
    "listing_country",
    "trading_currency",
    "reporting_currency",
    "economic_currency",
    "issuer",
    "entity",
    "market_cap",
    "liquidity",
    "factor",
    "systematic_risk",
    "specific_risk",
    "bond_issuer_type",
    "rating",
    "maturity",
    "duration",
    "seniority",
    "security",
)
_METADATA_FIELDS: Mapping[str, tuple[str, ...]] = {
    "asset_class": ("asset_class",),
    "industry": ("industry",),
    "listing_country": ("listing_country", "legal_country"),
    "liquidity": ("liquidity", "liquidity_bucket"),
    "systematic_risk": ("systematic_risk",),
    "specific_risk": ("specific_risk",),
    "bond_issuer_type": ("bond_issuer_type",),
    "rating": ("rating",),
    "maturity": ("maturity",),
    "duration": ("duration",),
    "seniority": ("seniority",),
}
_CANONICAL_DIMENSIONS: Mapping[str, str] = {
    "sector": "sector",
    "country": "economic_country",
    "region": "region",
    "currency": "economic_currency",
    "issuer": "issuer",
    "company": "entity",
    "cap_bucket": "market_cap",
    "factor": "factor",
    "security": "security",
}


@dataclass(frozen=True)
class ExposureSource:
    instrument_id: str
    as_of: str | None
    known_at: str | None
    source_id: str | None
    source_checksum: str | None
    freshness: str
    status: str


@dataclass(frozen=True)
class ExposureSegment:
    dimension: str
    bucket: str
    amount: float
    percentage: float
    direct_weight: float
    indirect_weight: float
    sources: tuple[ExposureSource, ...]
    contributors: tuple[ExposureContributor, ...]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExposureDimension:
    dimension: str
    input_weight: float
    mapped_weight: float
    stale_weight: float
    unmapped_weight: float
    coverage_fraction: float
    segments: tuple[ExposureSegment, ...]


@dataclass(frozen=True)
class PortfolioExposureCube:
    portfolio_id: str | None
    snapshot_id: str | None
    as_of: str
    known_at: str
    view_mode: Literal["combined"]
    total_weight: float
    dimensions: tuple[ExposureDimension, ...]
    sources: tuple[ExposureSource, ...]
    aggregation_policy: tuple[str, ...]
    warnings: tuple[str, ...]
    max_depth: int
    execution_allowed: Literal[False] = False

    def to_projection(self) -> dict[str, object]:
        """Return all buckets and contributor links in a chart-friendly shape."""

        return {
            "status": "available" if self.total_weight > 0 else "unavailable",
            "portfolio_id": self.portfolio_id,
            "snapshot_id": self.snapshot_id,
            "as_of": self.as_of,
            "known_at": self.known_at,
            "view_mode": self.view_mode,
            "total_weight": self.total_weight,
            "dimensions": {
                item.dimension: [
                    {
                        "name": segment.bucket,
                        "value": segment.amount,
                        "percentage": segment.percentage,
                        "direct_weight": segment.direct_weight,
                        "indirect_weight": segment.indirect_weight,
                        "sources": [asdict(source) for source in segment.sources],
                        "contributors": [asdict(item) for item in segment.contributors],
                        "reasons": list(segment.reasons),
                    }
                    for segment in item.segments
                ]
                for item in self.dimensions
            },
            "coverage": {
                item.dimension: {
                    "input_weight": item.input_weight,
                    "mapped_weight": item.mapped_weight,
                    "stale_weight": item.stale_weight,
                    "unmapped_weight": item.unmapped_weight,
                    "coverage_fraction": item.coverage_fraction,
                }
                for item in self.dimensions
            },
            "sources": [asdict(item) for item in self.sources],
            "aggregation_policy": list(self.aggregation_policy),
            "warnings": list(self.warnings),
            "execution_allowed": False,
        }


def build_portfolio_exposure_cube(
    holdings: pd.DataFrame,
    position_weights: Mapping[str, float],
    *,
    decision_time: str | datetime,
    analysis_date: str | date | datetime | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    position_metadata: Mapping[str, Mapping[str, object]] | None = None,
    holding_metadata: Mapping[str, Mapping[str, object]] | None = None,
    reporting_currency: str | None = None,
    max_depth: int = _MAX_DEPTH,
) -> PortfolioExposureCube:
    """Build a conserved, dated exposure cube from ledger-derived weights.

    ``position_weights`` must already be valued decimal weights from the selected
    ledger snapshot.  Direct non-fund positions are identified by their
    ``position_metadata[*]["exposure_type"]`` value.  Optional metadata only
    fills declared dimensions; it never fills weight or coverage gaps.
    """

    cutoff = normalise_event_decision_time(decision_time)
    if cutoff is None:
        raise ValueError("decision_time must be timezone-aware")
    analysis = _as_date(analysis_date) if analysis_date is not None else cutoff.date()
    if analysis is None or analysis > cutoff.date():
        raise ValueError("analysis_date must be valid and no later than decision_time")
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= 32:
        raise ValueError("max_depth must be between 1 and 32")

    weights = _weights(position_weights)
    total_weight = math.fsum(weights.values())
    metadata = _normalise_metadata(position_metadata)
    holding_facts = _normalise_metadata(holding_metadata)
    direct_positions = {
        instrument_id: metadata[instrument_id]
        for instrument_id in weights
        if _text(metadata.get(instrument_id, {}).get("exposure_type")).lower()
        in {"security", "cash", "derivative"}
    }
    fund_weights = {key: value for key, value in weights.items() if key not in direct_positions}
    frame = holdings.copy() if isinstance(holdings, pd.DataFrame) else pd.DataFrame()

    root_summaries: dict[str, LookThroughSummary] = {}
    for instrument_id in fund_weights:
        root_summaries[instrument_id] = calculate_look_through(
            frame,
            instrument_id=instrument_id,
            decision_time=cutoff,
            analysis_date=analysis,
            max_holdings_age_days=90,
        )

    report = _overlap_report(frame, fund_weights, cutoff, analysis, max_depth)
    source_rows = _sources(report, root_summaries)
    source_by_id = {item.instrument_id: item for item in source_rows}
    stale_ids = {item.instrument_id for item in source_rows if item.freshness == "stale"}
    stale_security_weight = _stale_security_weight(report, stale_ids)

    accumulators = {dimension: {} for dimension in _DIMENSIONS}
    reasons = {dimension: set() for dimension in _DIMENSIONS}
    _add_canonical_dimensions(report, accumulators, reasons, source_by_id)
    _add_metadata_dimensions(
        report,
        accumulators,
        reasons,
        holding_facts,
        source_by_id,
    )
    _add_direct_positions(
        direct_positions,
        {key: weights[key] for key in direct_positions},
        metadata,
        accumulators,
        reasons,
    )
    _add_position_currency(
        weights,
        metadata,
        accumulators,
        reasons,
        dimension="trading_currency",
        fields=("trading_currency",),
        absent_reason="Trading currency is unavailable for this position.",
    )
    _add_reporting_currency(total_weight, reporting_currency, accumulators, reasons)

    dimensions = tuple(
        _dimension_view(
            name,
            accumulators[name],
            reasons[name],
            total_weight,
            stale_security_weight if name not in {"trading_currency", "reporting_currency"} else 0.0,
            source_rows,
        )
        for name in _DIMENSIONS
    )
    warnings = list(report.warnings)
    warnings.extend(
        limitation
        for summary in root_summaries.values()
        for limitation in summary.limitations
    )
    policy = (
        "Weights come from the caller's selected ledger snapshot and are not renormalised.",
        "ETF holdings use the canonical look-through and overlap identity mapping with known_at bounded by decision_time.",
        f"Nested funds expand once per path up to max_depth={max_depth}; cycles, missing links, stale data and unresolved weights remain unknown.",
        "Unknown values are never redistributed; every registered dimension conserves total portfolio weight to 1e-9.",
        "Currency dimensions mean trading currency of the portfolio instrument, reporting currency of the portfolio, and economic currency of underlying exposure.",
        "Optional metadata fills labels only; absent metadata remains Unknown/Unmapped.",
    )
    return PortfolioExposureCube(
        portfolio_id=_optional_text(portfolio_id),
        snapshot_id=_optional_text(snapshot_id),
        as_of=analysis.isoformat(),
        known_at=cutoff.isoformat(),
        view_mode="combined",
        total_weight=round(total_weight, 12),
        dimensions=dimensions,
        sources=source_rows,
        aggregation_policy=policy,
        warnings=tuple(dict.fromkeys(warnings)),
        max_depth=max_depth,
    )


def _overlap_report(
    holdings: pd.DataFrame,
    weights: Mapping[str, float],
    cutoff: datetime,
    analysis: date,
    max_depth: int,
) -> DirectOverlapReport:
    nested_ids: set[str] = set()
    for column in ("nested_instrument_id", "holding_instrument_id"):
        if column in holdings.columns:
            nested_ids.update(
                value
                for value in (_text(item) for item in holdings[column])
                if value
            )
    instrument_ids = tuple(sorted(set(weights) | nested_ids))
    return calculate_direct_overlap(
        holdings,
        instrument_ids,
        current_weights=weights,
        today=analysis,
        known_at=cutoff,
        max_depth=max_depth,
    )


def _sources(
    report: DirectOverlapReport,
    root_summaries: Mapping[str, LookThroughSummary],
) -> tuple[ExposureSource, ...]:
    result: list[ExposureSource] = []
    for coverage in report.coverage:
        summary = root_summaries.get(coverage.instrument_id)
        lineage = summary.lineage if summary is not None else {}
        result.append(
            ExposureSource(
                instrument_id=coverage.instrument_id,
                as_of=(summary.holdings_date if summary is not None else coverage.as_of),
                known_at=(
                    _optional_text(lineage.get("known_at"))
                    if summary is not None
                    else coverage.known_at
                ),
                source_id=(summary.source_id if summary is not None else coverage.source_id),
                source_checksum=coverage.source_checksum,
                freshness=(summary.freshness if summary is not None else coverage.freshness),
                status=(summary.status if summary is not None else coverage.status),
            )
        )
    return tuple(sorted(result, key=lambda item: item.instrument_id))


def _add_canonical_dimensions(report, accumulators, reasons, source_by_id) -> None:
    canonical_by_dimension: dict[str, dict[str, LookThroughExposure]] = {}
    for exposure in report.exposures:
        target = _CANONICAL_DIMENSIONS.get(exposure.dimension)
        if target is None:
            continue
        canonical_by_dimension.setdefault(target, {})[exposure.bucket] = exposure
    for target, entries in canonical_by_dimension.items():
        for bucket, exposure in entries.items():
            key = _UNKNOWN if bucket == _UNKNOWN else bucket
            _add_exposure(
                accumulators[target],
                key,
                exposure,
                _exposure_sources(exposure.contributors, source_by_id),
            )
            if key == _UNKNOWN:
                reasons[target].update(_unknown_reasons(exposure, report.warnings))


def _add_metadata_dimensions(report, accumulators, reasons, facts, source_by_id) -> None:
    security = [item for item in report.exposures if item.dimension == "security"]
    exposure_types = {
        item.bucket: item
        for item in report.exposures
        if item.dimension == "exposure_type"
    }
    for exposure in security:
        identity = exposure.bucket
        if identity == _UNKNOWN:
            for dimension in _METADATA_FIELDS:
                _add_exposure(
                    accumulators[dimension],
                    _UNKNOWN,
                    exposure,
                    _exposure_sources(exposure.contributors, source_by_id),
                )
                reasons[dimension].update(_unknown_reasons(exposure, report.warnings))
            continue
        attributes = facts.get(identity, {})
        for dimension, fields in _METADATA_FIELDS.items():
            value = _first_text(attributes, fields)
            if not value and dimension == "asset_class":
                value = _asset_class_from_exposure(identity, exposure_types)
            bucket = value or _UNKNOWN
            _add_exposure(
                accumulators[dimension],
                bucket,
                exposure,
                _exposure_sources(exposure.contributors, source_by_id),
            )
            if bucket == _UNKNOWN:
                reasons[dimension].add(f"{dimension.replace('_', ' ').capitalize()} data is unavailable for {identity}.")


def _asset_class_from_exposure(identity, exposure_types) -> str | None:
    for label in ("cash", "derivative"):
        exposure = exposure_types.get(label)
        if exposure is None:
            continue
        if any(contributor.path and contributor.path[-1] == identity for contributor in exposure.contributors):
            return label
    return None


def _add_direct_positions(direct_positions, weights, metadata, accumulators, reasons) -> None:
    for instrument_id, attributes in direct_positions.items():
        amount = weights[instrument_id]
        identity = _first_text(attributes, ("identity", "security_identity", "security")) or instrument_id
        contributor = ExposureContributor(instrument_id, (instrument_id,), "direct", round(amount, 12))
        for dimension in _DIMENSIONS:
            if dimension in {"trading_currency", "reporting_currency"}:
                continue
            if dimension == "security":
                value = identity
            elif dimension == "asset_class":
                value = _first_text(attributes, ("asset_class",))
            elif dimension == "economic_country":
                value = _first_text(attributes, ("economic_country", "country"))
            elif dimension == "economic_currency":
                value = _first_text(attributes, ("economic_currency", "currency"))
            elif dimension == "issuer":
                value = _first_text(attributes, ("issuer",))
            elif dimension == "entity":
                value = _first_text(attributes, ("entity", "company", "issuer"))
            elif dimension == "market_cap":
                value = _first_text(attributes, ("market_cap", "cap_bucket"))
            else:
                value = _first_text(attributes, _METADATA_FIELDS.get(dimension, (dimension,)))
                if dimension == "sector" and not value:
                    value = _first_text(attributes, ("sector",))
                elif dimension == "region" and not value:
                    value = _first_text(attributes, ("region",))
                elif dimension == "factor" and not value:
                    value = _first_text(attributes, ("factor",))
            bucket = value or _UNKNOWN
            _add_values(
                accumulators[dimension],
                bucket,
                amount,
                0.0,
                (contributor,),
                (),
            )
            if bucket == _UNKNOWN:
                reasons[dimension].add(f"{dimension.replace('_', ' ').capitalize()} data is unavailable for direct position {instrument_id}.")


def _add_position_currency(weights, metadata, accumulators, reasons, *, dimension, fields, absent_reason) -> None:
    for instrument_id, amount in weights.items():
        value = _first_text(metadata.get(instrument_id, {}), fields)
        bucket = value or _UNKNOWN
        contributor = ExposureContributor(instrument_id, (instrument_id,), "direct", round(amount, 12))
        _add_values(accumulators[dimension], bucket, amount, 0.0, (contributor,), ())
        if not value:
            reasons[dimension].add(f"{absent_reason} ({instrument_id})")


def _add_reporting_currency(total_weight, reporting_currency, accumulators, reasons) -> None:
    bucket = _optional_text(reporting_currency)
    if bucket:
        _add_values(
            accumulators["reporting_currency"],
            bucket.upper(),
            total_weight,
            0.0,
            (ExposureContributor("portfolio", ("portfolio",), "direct", round(total_weight, 12)),),
            (),
        )
    else:
        _add_values(
            accumulators["reporting_currency"],
            _UNKNOWN,
            total_weight,
            0.0,
            (ExposureContributor("portfolio", ("portfolio",), "unknown", round(total_weight, 12)),),
            (),
        )
        reasons["reporting_currency"].add("Portfolio reporting currency is unavailable.")


def _add_exposure(target, bucket, exposure, sources) -> None:
    unknown = max(0.0, exposure.combined_weight - exposure.direct_weight - exposure.indirect_weight)
    _add_values(
        target,
        bucket,
        exposure.direct_weight,
        exposure.indirect_weight,
        exposure.contributors,
        sources,
        unknown_amount=unknown,
    )


def _add_values(target, bucket, direct, indirect, contributors, sources, *, unknown_amount=0.0) -> None:
    entry = target.setdefault(
        bucket,
        {"direct": 0.0, "indirect": 0.0, "unknown": 0.0, "contributors": [], "sources": set()},
    )
    entry["direct"] += direct
    entry["indirect"] += indirect
    entry["unknown"] += unknown_amount
    entry["contributors"].extend(contributors)
    entry["sources"].update(sources)


def _dimension_view(name, entries, reasons, total_weight, stale_security_weight, source_rows):
    unknown_entry = entries.get(_UNKNOWN, {"direct": 0.0, "indirect": 0.0, "unknown": 0.0})
    unknown_amount = math.fsum(
        (float(unknown_entry["direct"]), float(unknown_entry["indirect"]), float(unknown_entry["unknown"]))
    )
    all_amount = math.fsum(
        math.fsum((float(entry["direct"]), float(entry["indirect"]), float(entry["unknown"])))
        for entry in entries.values()
    )
    delta = total_weight - all_amount
    if delta < -_TOLERANCE:
        raise ValueError(f"{name} exposure exceeds the portfolio input weight")
    if delta > 0:
        _add_values(
            entries,
            _UNKNOWN,
            0.0,
            0.0,
            (ExposureContributor("portfolio", ("portfolio",), "unknown", round(delta, 12)),),
            (),
            unknown_amount=delta,
        )
        reasons.add("Exposure not represented by mapped evidence remains unknown.")
        unknown_amount += delta
    if _UNKNOWN not in entries:
        entries[_UNKNOWN] = {"direct": 0.0, "indirect": 0.0, "unknown": 0.0, "contributors": [], "sources": set()}

    segments = []
    for bucket, entry in sorted(entries.items(), key=lambda item: (item[0] == _UNKNOWN, item[0])):
        amount = math.fsum((float(entry["direct"]), float(entry["indirect"]), float(entry["unknown"])))
        if bucket == _UNKNOWN:
            stale = min(amount, max(0.0, stale_security_weight))
            if stale > _TOLERANCE:
                reasons.add("Holdings evidence was stale as of the decision time.")
            segment_reasons = tuple(sorted(reasons))
        else:
            stale = 0.0
            segment_reasons = ()
        source_ids = set(entry["sources"])
        segments.append(
            ExposureSegment(
                dimension=name,
                bucket=bucket,
                amount=round(amount, 12),
                percentage=round(100.0 * amount / total_weight, 12) if total_weight > 0 else 0.0,
                direct_weight=round(float(entry["direct"]), 12),
                indirect_weight=round(float(entry["indirect"]), 12),
                sources=tuple(item for item in source_rows if item.instrument_id in source_ids),
                contributors=tuple(
                    sorted(
                        set(entry["contributors"]),
                        key=lambda item: (item.root_instrument_id, item.path, item.ownership, item.weight),
                    )
                ),
                reasons=segment_reasons,
            )
        )

    mapped_weight = math.fsum(item.amount for item in segments if item.bucket != _UNKNOWN)
    unknown_weight = math.fsum(item.amount for item in segments if item.bucket == _UNKNOWN)
    stale_weight = min(unknown_weight, max(0.0, stale_security_weight))
    unmapped_weight = max(0.0, unknown_weight - stale_weight)
    if abs(mapped_weight + stale_weight + unmapped_weight - total_weight) > _TOLERANCE:
        raise ValueError(f"{name} exposure coverage failed conservation")
    if total_weight > 0 and abs(math.fsum(item.percentage for item in segments) - 100.0) > _TOLERANCE * 100:
        raise ValueError(f"{name} percentages failed conservation")
    return ExposureDimension(
        dimension=name,
        input_weight=round(total_weight, 12),
        mapped_weight=round(mapped_weight, 12),
        stale_weight=round(stale_weight, 12),
        unmapped_weight=round(unmapped_weight, 12),
        coverage_fraction=round(mapped_weight / total_weight, 12) if total_weight > 0 else 0.0,
        segments=tuple(segments),
    )


def _stale_security_weight(report, stale_ids) -> float:
    return math.fsum(
        contributor.weight
        for exposure in report.exposures
        if exposure.dimension == "security" and exposure.bucket == _UNKNOWN
        for contributor in exposure.contributors
        if any(instrument_id in stale_ids for instrument_id in contributor.path)
    )


def _exposure_sources(contributors, source_by_id):
    return {
        instrument_id
        for contributor in contributors
        for instrument_id in contributor.path
        if instrument_id in source_by_id
    }


def _unknown_reasons(exposure, warnings):
    result = set(warnings)
    if not result:
        result.add("Holdings or dimension data is unavailable.")
    return result


def _weights(values: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(values, Mapping):
        raise ValueError("position_weights must be a mapping from ledger instrument ids to decimal weights")
    result: dict[str, float] = {}
    for raw_key, raw_value in values.items():
        key = _text(raw_key)
        if not key:
            raise ValueError("position_weights contains a blank instrument identifier")
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise ValueError(f"weight for {key} must be a finite decimal number")
        weight = float(raw_value)
        if not math.isfinite(weight) or weight < 0 or weight > 1 + _TOLERANCE:
            raise ValueError(f"weight for {key} must be between zero and one")
        result[key] = result.get(key, 0.0) + weight
    total = math.fsum(result.values())
    if total > 1 + _TOLERANCE:
        raise ValueError("position_weights total exceeds 100%")
    return {key: value for key, value in sorted(result.items()) if value > 0}


def _normalise_metadata(values):
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ValueError("metadata must be a mapping")
    result = {}
    for key, attributes in values.items():
        label = _text(key)
        if not label:
            continue
        if isinstance(attributes, Mapping):
            result[label] = dict(attributes)
    return result


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _first_text(values: Mapping[str, object], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = _optional_text(values.get(field))
        if value:
            return value
    return None


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _text(value: object) -> str:
    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return ""
    return str(value).strip()


__all__ = [
    "ExposureDimension",
    "ExposureSegment",
    "ExposureSource",
    "PortfolioExposureCube",
    "build_portfolio_exposure_cube",
]
