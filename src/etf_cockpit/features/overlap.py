"""Deterministic direct ETF holdings overlap with explicit evidence limits."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import hmac
import json
import math
import re
from typing import Literal, Mapping, Sequence

import pandas as pd


_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_TOLERANCE = 1e-9
_STALE_AFTER = timedelta(days=90)


@dataclass(frozen=True)
class DirectHolding:
    identity: str
    display_name: str
    weight: float
    issuer: str | None = None
    company: str | None = None
    sector: str | None = None
    country: str | None = None
    region: str | None = None
    currency: str | None = None
    factor: str | None = None
    cap_bucket: str | None = None
    index_family: str | None = None
    exposure_type: Literal["security", "fund", "cash", "derivative", "unknown"] = "security"
    nested_instrument_id: str | None = None
    derivative_underlying_identity: str | None = None


@dataclass(frozen=True)
class HoldingsCoverage:
    instrument_id: str
    status: Literal["full", "partial", "missing"]
    freshness: Literal["fresh", "stale", "invalid", "unknown"]
    as_of: str | None
    source_id: str | None
    source_checksum: str | None
    resolved_weight: float
    unresolved_weight: float
    holdings: tuple[DirectHolding, ...]
    warnings: tuple[str, ...] = ()
    known_at: str | None = None
    authority: str | None = None


@dataclass(frozen=True)
class OverlappingHolding:
    identity: str
    display_name: str
    left_weight: float
    right_weight: float
    shared_weight: float


@dataclass(frozen=True)
class PairwiseOverlap:
    left_instrument_id: str
    right_instrument_id: str
    status: Literal["full", "dated_lower_bound", "missing"]
    observed_overlap_weight: float | None
    current_overlap_weight: float | None
    left_coverage: HoldingsCoverage
    right_coverage: HoldingsCoverage
    top_holdings: tuple[OverlappingHolding, ...]


@dataclass(frozen=True)
class OverlapConcentration:
    dimension: str
    bucket: str
    current_weight: float
    target_weight: float


@dataclass(frozen=True)
class ExposureContributor:
    root_instrument_id: str
    path: tuple[str, ...]
    ownership: Literal["direct", "indirect", "unknown"]
    weight: float


@dataclass(frozen=True)
class LookThroughExposure:
    dimension: str
    bucket: str
    direct_weight: float
    indirect_weight: float
    combined_weight: float
    contributors: tuple[ExposureContributor, ...]


@dataclass(frozen=True)
class DirectOverlapReport:
    status: Literal["full", "dated_lower_bound", "missing"]
    pairs: tuple[PairwiseOverlap, ...]
    concentrations: tuple[OverlapConcentration, ...]
    coverage: tuple[HoldingsCoverage, ...]
    current_resolved_weight: float
    target_resolved_weight: float
    warnings: tuple[str, ...]
    methodology: str = "direct_exact_identity_weighted_min_v1"
    execution_allowed: Literal[False] = False
    exposures: tuple[LookThroughExposure, ...] = ()
    input_weight: float = 0.0
    mapped_weight: float = 0.0
    unknown_weight: float = 0.0
    report_hash: str = ""


def overlap_warning() -> str:
    return "Direct overlap is evidence-only; unresolved holdings are never renormalised away."


def calculate_direct_overlap(
    holdings: pd.DataFrame,
    instrument_ids: Sequence[str],
    *,
    current_weights: Mapping[str, float] | None = None,
    target_weights: Mapping[str, float] | None = None,
    focus_instrument_id: str | None = None,
    today: date | None = None,
    known_at: datetime | None = None,
    max_depth: int = 8,
) -> DirectOverlapReport:
    """Calculate direct exact-identity overlap from canonical decimal holdings.

    Partial evidence is reported as an observed dated lower bound. Stale
    evidence never produces a claim about current overlap.
    """

    ids = tuple(sorted({str(item).strip() for item in instrument_ids if str(item).strip()}))
    current = _portfolio_weights(current_weights or {}, "current_weights")
    target = _portfolio_weights(target_weights or {}, "target_weights")
    cutoff = _normalise_cutoff(known_at, today)
    effective_today = today or cutoff.date()
    coverage = tuple(_select_snapshot(holdings, item, effective_today, cutoff) for item in ids)
    by_id = {item.instrument_id: item for item in coverage}

    pairs: list[PairwiseOverlap] = []
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1 :]:
            if focus_instrument_id and focus_instrument_id not in {left_id, right_id}:
                continue
            pairs.append(_pair_overlap(by_id[left_id], by_id[right_id]))

    concentrations = _concentrations(coverage, current, target)
    computable = [pair for pair in pairs if pair.status != "missing"]
    status: Literal["full", "dated_lower_bound", "missing"]
    if not computable:
        status = "missing"
    elif len(computable) == len(pairs) and all(pair.status == "full" for pair in pairs):
        status = "full"
    else:
        status = "dated_lower_bound"
    warnings = sorted({warning for item in coverage for warning in item.warnings})
    if status == "dated_lower_bound":
        warnings.append("Observed overlap is a dated lower bound; unresolved exposure is not renormalised.")
    if any(item.freshness == "stale" for item in coverage):
        warnings.append("At least one selected snapshot is stale; current overlap is unavailable.")
    exposures, input_weight, mapped_weight, unknown_weight, lookthrough_warnings = _lookthrough_exposures(
        holdings, ids, current, coverage, effective_today, cutoff, max_depth
    )
    warnings.extend(lookthrough_warnings)
    report = DirectOverlapReport(
        status=status,
        pairs=tuple(pairs),
        concentrations=concentrations,
        coverage=coverage,
        current_resolved_weight=_resolved_portfolio_weight(coverage, current),
        target_resolved_weight=_resolved_portfolio_weight(coverage, target),
        warnings=tuple(dict.fromkeys(warnings)),
        exposures=exposures,
        input_weight=input_weight,
        mapped_weight=mapped_weight,
        unknown_weight=unknown_weight,
    )
    return _bind_report_hash(report)


def _portfolio_weights(values: Mapping[str, float], label: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key).strip()
        value = _decimal_weight(raw_value, label)
        if not key:
            raise ValueError(f"{label} contains a blank instrument identifier")
        result[key] = value
    if math.fsum(result.values()) > 1 + _TOLERANCE:
        raise ValueError(f"{label} total exceeds 100%")
    return result


def _select_snapshot(
    frame: pd.DataFrame, instrument_id: str, today: date, known_at: datetime | None = None
) -> HoldingsCoverage:
    if frame is None or frame.empty:
        return _missing(instrument_id, "No holdings evidence is available.")
    parent_column = next((name for name in ("instrument_id", "etf_id") if name in frame.columns), None)
    date_column = next((name for name in ("as_of", "as_of_date") if name in frame.columns), None)
    if parent_column is None or date_column is None or "weight" not in frame.columns:
        return _missing(instrument_id, "Holdings evidence is missing required canonical fields.")
    rows = frame.loc[frame[parent_column].astype(str).str.strip().eq(instrument_id)].copy()
    if rows.empty:
        return _missing(instrument_id, "No holdings snapshot is available for this instrument.")
    dates = pd.to_datetime(rows[date_column], errors="coerce", utc=True)
    cutoff = known_at or datetime.combine(today, time.max, tzinfo=timezone.utc)
    known_column = next((name for name in ("known_at", "available_at") if name in rows.columns), None)
    availability = (
        pd.to_datetime(rows[known_column], errors="coerce", utc=True)
        if known_column
        else dates
    )
    valid = dates.notna() & availability.notna() & dates.dt.date.le(today) & availability.le(cutoff)
    rows = rows.loc[valid].copy()
    dates = dates.loc[valid]
    availability = availability.loc[valid]
    if rows.empty:
        return _missing(instrument_id, "All holdings dates are invalid or in the future.")
    latest = dates.max()
    latest_known = availability.loc[dates.eq(latest)].max()
    selected_mask = dates.eq(latest) & availability.eq(latest_known)
    rows = rows.loc[selected_mask].copy()
    source_groups = _source_groups(rows)
    selected, warning = _choose_source_group(source_groups)
    if selected is None:
        return _missing(instrument_id, warning or "Conflicting holdings snapshots are unavailable.")
    source_id, selected_rows = selected
    return _normalise_snapshot(
        instrument_id,
        latest.date().isoformat(),
        source_id,
        selected_rows,
        warning,
        today,
        known_at=latest_known.isoformat(),
    )


def _source_groups(rows: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    if "source_id" not in rows.columns:
        return [("", rows)]
    values = rows["source_id"].fillna("").astype(str).str.strip()
    return [(key, rows.loc[values.eq(key)].copy()) for key in sorted(values.unique())]


def _choose_source_group(
    groups: list[tuple[str, pd.DataFrame]],
) -> tuple[tuple[str, pd.DataFrame] | None, str | None]:
    if len(groups) == 1:
        return groups[0], None
    ranked: list[tuple[int, str, pd.DataFrame]] = []
    for source_id, rows in groups:
        authority = _single_text(rows, "authority")
        rank = {"issuer": 2, "vendor": 1, "manual_unverified": 0, "unknown": 0}.get(authority or "unknown", 0)
        ranked.append((rank, source_id, rows))
    best_rank = max(item[0] for item in ranked)
    best = [item for item in ranked if item[0] == best_rank]
    if len(best) != 1:
        return None, "Equal-authority holdings snapshots conflict for the selected date."
    _, source_id, rows = best[0]
    return (source_id, rows), "A lower-authority same-date holdings snapshot was excluded."


def _normalise_snapshot(
    instrument_id: str,
    as_of: str,
    source_id: str,
    rows: pd.DataFrame,
    selection_warning: str | None,
    today: date,
    *,
    known_at: str | None = None,
) -> HoldingsCoverage:
    warnings: list[str] = [selection_warning] if selection_warning else []
    grouped: dict[str, list[tuple[float, pd.Series]]] = {}
    unresolved: list[tuple[float, dict[str, str]]] = []
    try:
        for _, row in rows.iterrows():
            weight = _decimal_weight(row.get("weight"), "holding weight")
            identity = _typed_identity(row)
            if identity is None:
                unresolved.append((weight, _unresolved_fields(row)))
                continue
            grouped.setdefault(identity, []).append((weight, row))
    except ValueError as exc:
        return _missing(instrument_id, str(exc), as_of=as_of, source_id=source_id or None)
    direct: list[DirectHolding] = []
    for identity, values in sorted(grouped.items()):
        weight = math.fsum(sorted(item[0] for item in values))
        if weight > 1 + _TOLERANCE:
            return _missing(instrument_id, "Duplicate identity weights exceed 100%.", as_of=as_of, source_id=source_id or None)
        rows_for_id = [item[1] for item in values]
        direct.append(
            DirectHolding(
                identity=identity,
                display_name=_display_name(rows_for_id, identity),
                weight=round(weight, 12),
                issuer=_consistent_dimension(rows_for_id, "issuer", warnings, identity),
                company=_consistent_dimension(rows_for_id, "company", warnings, identity),
                sector=_consistent_dimension(rows_for_id, "sector", warnings, identity),
                country=_consistent_dimension(rows_for_id, "country", warnings, identity),
                region=_consistent_dimension(rows_for_id, "region", warnings, identity),
                currency=_consistent_dimension(rows_for_id, "currency", warnings, identity),
                factor=_consistent_dimension(rows_for_id, "factor", warnings, identity),
                cap_bucket=_consistent_dimension(rows_for_id, "cap_bucket", warnings, identity),
                index_family=_consistent_dimension(rows_for_id, "index_family", warnings, identity),
                exposure_type=_exposure_type(rows_for_id),
                nested_instrument_id=_consistent_dimension(
                    rows_for_id, "nested_instrument_id", warnings, identity
                )
                or _consistent_dimension(rows_for_id, "holding_instrument_id", warnings, identity),
                derivative_underlying_identity=_derivative_underlying(rows_for_id),
            )
        )
    resolved_weight = math.fsum(item.weight for item in direct)
    disclosed_weight = resolved_weight + math.fsum(item[0] for item in unresolved)
    if disclosed_weight > 1.01 + _TOLERANCE:
        return _missing(instrument_id, "Snapshot weights exceed the canonical tolerance.", as_of=as_of, source_id=source_id or None)
    completeness = _single_text(rows, "completeness") or "partial"
    freshness: Literal["fresh", "stale", "invalid", "unknown"] = (
        "fresh" if today - date.fromisoformat(as_of) <= _STALE_AFTER else "stale"
    )
    authority = _single_text(rows, "authority")
    provenance_complete = bool(source_id.strip()) and authority in {"issuer", "vendor", "manual_unverified"}
    if not provenance_complete:
        warnings.append("Snapshot provenance is incomplete; current/full overlap is unavailable.")
    full = completeness == "full" and resolved_weight >= 0.99 - _TOLERANCE and provenance_complete
    status: Literal["full", "partial", "missing"] = "full" if full else "partial" if direct else "missing"
    if unresolved:
        warnings.append("Some holdings lack a safe typed identity and remain unresolved.")
    payload = {
        "instrument_id": instrument_id,
        "as_of": as_of,
        "source_id": source_id,
        "completeness": completeness,
        "freshness": freshness,
        "authority": authority,
        "holdings": [
            {
                "identity": item.identity,
                "display_name": item.display_name,
                "weight": item.weight,
                "issuer": item.issuer,
                "company": item.company,
                "sector": item.sector,
                "country": item.country,
                "region": item.region,
                "currency": item.currency,
                "factor": item.factor,
                "cap_bucket": item.cap_bucket,
                "index_family": item.index_family,
                "exposure_type": item.exposure_type,
                "nested_instrument_id": item.nested_instrument_id,
                "derivative_underlying_identity": item.derivative_underlying_identity,
            }
            for item in direct
        ],
        "unresolved_holdings": sorted(
            ({"weight": round(weight, 12), **fields} for weight, fields in unresolved),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False),
        ),
    }
    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    supplied_checksums = (
        sorted({_text(value).lower() for value in rows["source_checksum"] if _text(value)})
        if "source_checksum" in rows.columns
        else []
    )
    if supplied_checksums and (len(supplied_checksums) != 1 or supplied_checksums[0] != checksum):
        return _missing(
            instrument_id,
            "Snapshot checksum verification failed.",
            as_of=as_of,
            source_id=source_id or None,
        )
    return HoldingsCoverage(
        instrument_id=instrument_id,
        status=status,
        freshness=freshness,
        as_of=as_of,
        source_id=source_id or None,
        source_checksum=checksum,
        resolved_weight=round(resolved_weight, 12),
        unresolved_weight=round(max(0.0, 1.0 - resolved_weight), 12),
        holdings=tuple(direct),
        warnings=tuple(dict.fromkeys(warnings)),
        known_at=known_at,
        authority=authority,
    )


def _typed_identity(row: pd.Series) -> str | None:
    exposure_type = _text(row.get("exposure_type", row.get("asset_type"))).lower()
    if exposure_type == "cash":
        currency = _text(row.get("currency")).upper()
        return f"cash:{currency}" if currency else None
    isin = _text(row.get("isin")).upper()
    if isin:
        return f"isin:{isin}" if _valid_isin(isin) else None
    explicit_type = _text(row.get("identity_type")).lower()
    explicit_value = _text(row.get("identity_value"))
    explicit_namespace = _text(row.get("identity_namespace")).lower()
    if explicit_type and explicit_value and explicit_namespace:
        return f"{explicit_type}:{explicit_namespace}:{explicit_value.casefold()}"
    for column, namespace_column, kind in (
        ("security_id", "security_id_namespace", "security_id"),
        ("holding_id", "holding_id_namespace", "holding_id"),
        ("ticker", "exchange", "ticker"),
        ("ticker", "venue", "ticker"),
    ):
        value = _text(row.get(column))
        namespace = _text(row.get(namespace_column)).lower()
        if value and namespace:
            return f"{kind}:{namespace}:{value.casefold()}"
    return None


def _exposure_type(rows: list[pd.Series]) -> Literal["security", "fund", "cash", "derivative", "unknown"]:
    values = {
        _text(row.get("exposure_type", row.get("asset_type"))).lower()
        for row in rows
        if _text(row.get("exposure_type", row.get("asset_type")))
    }
    aliases = {"etf": "fund", "mutual_fund": "fund", "stock": "security", "equity": "security"}
    value = aliases.get(next(iter(values)), next(iter(values))) if len(values) == 1 else "unknown"
    return value if value in {"security", "fund", "cash", "derivative"} else "unknown"


def _derivative_underlying(rows: list[pd.Series]) -> str | None:
    values = {
        _text(row.get("underlying_identity"))
        for row in rows
        if _text(row.get("underlying_identity"))
    }
    return next(iter(values)) if len(values) == 1 else None


def _unresolved_fields(row: pd.Series) -> dict[str, str]:
    fields: dict[str, str] = {}
    for column in (
        "security",
        "holding_name",
        "isin",
        "identity_type",
        "identity_namespace",
        "identity_value",
        "security_id",
        "security_id_namespace",
        "holding_id",
        "holding_id_namespace",
        "ticker",
        "exchange",
        "venue",
        "issuer",
        "company",
        "sector",
        "country",
        "region",
        "currency",
    ):
        value = _text(row.get(column))
        if value:
            fields[column] = value
    return fields


def _pair_overlap(left: HoldingsCoverage, right: HoldingsCoverage) -> PairwiseOverlap:
    left_by_id = {item.identity: item for item in left.holdings}
    right_by_id = {item.identity: item for item in right.holdings}
    shared: list[OverlappingHolding] = []
    for identity in sorted(set(left_by_id) & set(right_by_id)):
        left_item = left_by_id[identity]
        right_item = right_by_id[identity]
        weight = min(left_item.weight, right_item.weight)
        shared.append(
            OverlappingHolding(
                identity=identity,
                display_name=min(left_item.display_name, right_item.display_name),
                left_weight=left_item.weight,
                right_weight=right_item.weight,
                shared_weight=round(weight, 12),
            )
        )
    shared.sort(key=lambda item: (-item.shared_weight, item.identity))
    if left.status == "missing" or right.status == "missing":
        status: Literal["full", "dated_lower_bound", "missing"] = "missing"
        observed = None
    else:
        observed = round(math.fsum(item.shared_weight for item in shared), 12)
        status = "full" if left.status == right.status == "full" and left.freshness == right.freshness == "fresh" else "dated_lower_bound"
    current = observed if status == "full" else None
    return PairwiseOverlap(
        left.instrument_id,
        right.instrument_id,
        status,
        observed,
        current,
        left,
        right,
        tuple(shared[:10]),
    )


def _concentrations(
    coverage: tuple[HoldingsCoverage, ...],
    current: Mapping[str, float],
    target: Mapping[str, float],
) -> tuple[OverlapConcentration, ...]:
    buckets: dict[tuple[str, str], list[float]] = {}
    for snapshot in coverage:
        if snapshot.freshness != "fresh":
            continue
        for holding in snapshot.holdings:
            for dimension in ("issuer", "company", "sector", "country", "region", "currency"):
                bucket = getattr(holding, dimension)
                if not bucket:
                    continue
                values = buckets.setdefault((dimension, bucket), [0.0, 0.0])
                values[0] += current.get(snapshot.instrument_id, 0.0) * holding.weight
                values[1] += target.get(snapshot.instrument_id, 0.0) * holding.weight
    result = [
        OverlapConcentration(dimension, bucket, round(values[0], 12), round(values[1], 12))
        for (dimension, bucket), values in buckets.items()
    ]
    return tuple(sorted(result, key=lambda item: (item.dimension, -item.target_weight, -item.current_weight, item.bucket)))


def _resolved_portfolio_weight(coverage: tuple[HoldingsCoverage, ...], weights: Mapping[str, float]) -> float:
    return round(
        math.fsum(
            weights.get(item.instrument_id, 0.0) * item.resolved_weight
            for item in coverage
            if item.freshness == "fresh"
        ),
        12,
    )


def _normalise_cutoff(known_at: datetime | None, today: date | None) -> datetime:
    if known_at is None:
        return datetime.combine(today or date.today(), time.max, tzinfo=timezone.utc)
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("known_at must be timezone-aware")
    return known_at.astimezone(timezone.utc)


def _lookthrough_exposures(
    frame: pd.DataFrame,
    instrument_ids: tuple[str, ...],
    weights: Mapping[str, float],
    root_coverage: tuple[HoldingsCoverage, ...],
    today: date,
    cutoff: datetime,
    max_depth: int,
) -> tuple[tuple[LookThroughExposure, ...], float, float, float, list[str]]:
    if max_depth < 1 or max_depth > 32:
        raise ValueError("max_depth must be between 1 and 32")
    input_weight = round(math.fsum(weights.get(item, 0.0) for item in instrument_ids), 12)
    if input_weight == 0:
        return (), 0.0, 0.0, 0.0, []
    snapshots = {item.instrument_id: item for item in root_coverage}
    values: dict[tuple[str, str], list[object]] = {}
    mapped_security = 0.0
    unknown_security = 0.0
    warnings: list[str] = []
    dimensions = (
        "security",
        "issuer",
        "company",
        "sector",
        "country",
        "region",
        "currency",
        "factor",
        "cap_bucket",
        "index_family",
        "exposure_type",
        "fund",
    )

    def add(
        dimension: str,
        bucket: str,
        amount: float,
        ownership: Literal["direct", "indirect", "unknown"],
        root: str,
        path: tuple[str, ...],
    ) -> None:
        key = (dimension, bucket)
        entry = values.setdefault(key, [0.0, 0.0, []])
        if ownership == "direct":
            entry[0] = float(entry[0]) + amount
        elif ownership == "indirect":
            entry[1] = float(entry[1]) + amount
        entry[2].append(ExposureContributor(root, path, ownership, round(amount, 12)))

    def combined(entry: list[object]) -> float:
        return float(entry[0]) + float(entry[1]) + math.fsum(
            contributor.weight
            for contributor in entry[2]
            if contributor.ownership == "unknown"
        )

    def snapshot(instrument_id: str) -> HoldingsCoverage:
        if instrument_id not in snapshots:
            snapshots[instrument_id] = _select_snapshot(frame, instrument_id, today, cutoff)
        return snapshots[instrument_id]

    def expand(root: str, fund: str, amount: float, depth: int, path: tuple[str, ...]) -> None:
        nonlocal mapped_security, unknown_security
        selected = snapshot(fund)
        if (
            selected.status == "missing"
            or selected.freshness != "fresh"
            or not selected.source_id
            or not selected.source_checksum
            or selected.authority not in {"issuer", "vendor", "manual_unverified"}
        ):
            unknown_security += amount
            add("security", "Unknown/Unmapped", amount, "unknown", root, path)
            warnings.append(f"Nested holdings for {fund} are unavailable or stale; exposure remains unknown.")
            return
        unresolved = amount * selected.unresolved_weight
        if unresolved > _TOLERANCE:
            unknown_security += unresolved
            add("security", "Unknown/Unmapped", unresolved, "unknown", root, path)
        for holding in selected.holdings:
            child_amount = amount * holding.weight
            child_path = (*path, holding.nested_instrument_id or holding.identity)
            ownership: Literal["direct", "indirect"] = "direct" if depth == 0 else "indirect"
            if depth == 0 and holding.exposure_type == "fund":
                add("fund", holding.identity, child_amount, "direct", root, child_path)
            if holding.exposure_type == "fund":
                nested = holding.nested_instrument_id
                if not nested or nested in path or depth + 1 >= max_depth:
                    unknown_security += child_amount
                    add("security", "Unknown/Unmapped", child_amount, "unknown", root, child_path)
                    reason = "cycle" if nested in path else "depth/missing link"
                    warnings.append(f"Nested fund {holding.display_name} stopped at {reason}; value was conserved as unknown.")
                else:
                    expand(root, nested, child_amount, depth + 1, (*path, nested))
                continue
            if holding.exposure_type == "derivative" and not holding.derivative_underlying_identity:
                unknown_security += child_amount
                add("security", "Unknown/Unmapped", child_amount, "unknown", root, child_path)
                add("exposure_type", "derivative", child_amount, ownership, root, child_path)
                warnings.append("A derivative lacked explicit underlying evidence and remains unresolved.")
                continue
            mapped_security += child_amount
            dimensions_for_holding = _holding_dimensions(holding)
            if holding.derivative_underlying_identity:
                dimensions_for_holding["security"] = holding.derivative_underlying_identity
            for dimension, bucket in dimensions_for_holding.items():
                add(dimension, bucket, child_amount, ownership, root, child_path)

    for root in instrument_ids:
        amount = weights.get(root, 0.0)
        if amount > 0:
            expand(root, root, amount, 0, (root,))

    # Every combined dimension conserves the same input value without proportional filling.
    for dimension in dimensions:
        known = math.fsum(
            combined(entry)
            for (entry_dimension, bucket), entry in values.items()
            if entry_dimension == dimension and bucket != "Unknown/Unmapped"
        )
        missing = max(0.0, input_weight - known)
        existing_unknown = math.fsum(
            combined(entry)
            for (entry_dimension, bucket), entry in values.items()
            if entry_dimension == dimension and bucket == "Unknown/Unmapped"
        )
        if missing > existing_unknown + _TOLERANCE:
            add(dimension, "Unknown/Unmapped", missing - existing_unknown, "unknown", "portfolio", ("portfolio",))
    result = tuple(
        LookThroughExposure(
            dimension=dimension,
            bucket=bucket,
            direct_weight=round(float(entry[0]), 12),
            indirect_weight=round(float(entry[1]), 12),
            combined_weight=round(combined(entry), 12),
            contributors=tuple(
                sorted(entry[2], key=lambda item: (item.root_instrument_id, item.path, item.ownership, item.weight))
            ),
        )
        for (dimension, bucket), entry in sorted(values.items())
    )
    mapped = round(min(input_weight, mapped_security), 12)
    unknown = round(max(0.0, input_weight - mapped), 12)
    if abs(input_weight - mapped - unknown) > _TOLERANCE:
        raise ValueError("Look-through exposure failed conservation")
    return result, input_weight, mapped, unknown, warnings


def _holding_dimensions(holding: DirectHolding) -> dict[str, str]:
    result = {
        "security": holding.identity,
        "exposure_type": holding.exposure_type,
    }
    for dimension in (
        "issuer",
        "company",
        "sector",
        "country",
        "region",
        "currency",
        "factor",
        "cap_bucket",
        "index_family",
    ):
        value = getattr(holding, dimension)
        if value:
            result[dimension] = value
    return result


def _bind_report_hash(report: DirectOverlapReport) -> DirectOverlapReport:
    payload = asdict(report)
    payload["report_hash"] = ""
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return replace(report, report_hash=digest)


def verify_overlap_report(report: DirectOverlapReport) -> bool:
    """Strictly verify the deterministic identity of an in-memory report."""

    if not report.report_hash or report.execution_allowed is not False:
        return False
    expected = _bind_report_hash(replace(report, report_hash="")).report_hash
    return hmac.compare_digest(report.report_hash, expected)


def _valid_isin(value: str) -> bool:
    if not _ISIN.fullmatch(value):
        return False
    digits = "".join(str(ord(character) - ord("A") + 10) if character.isalpha() else character for character in value)
    total = 0
    for index, character in enumerate(reversed(digits)):
        number = int(character) * (1 if index % 2 == 0 else 2)
        total += number // 10 + number % 10
    return total % 10 == 0


def _decimal_weight(value: object, label: str) -> float:
    if pd.api.types.is_bool(value):
        raise ValueError(f"{label} must be a canonical decimal number, not a boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a canonical decimal number") from exc
    if not math.isfinite(result) or result < 0 or result > 1:
        raise ValueError(f"{label} must be finite and between 0 and 1")
    return result


def _single_text(rows: pd.DataFrame, column: str) -> str | None:
    if column not in rows.columns:
        return None
    values = sorted({_text(value).lower() for value in rows[column] if _text(value)})
    return values[0] if len(values) == 1 else None


def _display_name(rows: list[pd.Series], fallback: str) -> str:
    values = sorted({_text(row.get("security", row.get("holding_name"))) for row in rows if _text(row.get("security", row.get("holding_name")))})
    return values[0] if values else fallback


def _consistent_dimension(rows: list[pd.Series], column: str, warnings: list[str], identity: str) -> str | None:
    values = sorted({_text(row.get(column)) for row in rows if _text(row.get(column))})
    if len(values) > 1:
        warnings.append(f"Conflicting {column} values were omitted for {identity}.")
        return None
    return values[0] if values else None


def _text(value: object) -> str:
    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return ""
    return str(value).strip()


def _missing(
    instrument_id: str,
    warning: str,
    *,
    as_of: str | None = None,
    source_id: str | None = None,
) -> HoldingsCoverage:
    return HoldingsCoverage(instrument_id, "missing", "unknown", as_of, source_id, None, 0.0, 1.0, (), (warning,))
