"""Deterministic, non-executable portfolio candidate analysis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Literal

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.features.overlap import DirectOverlapReport, calculate_direct_overlap
from etf_cockpit.portfolio.costs import PortfolioCostEstimate, estimate_rebalance_cost


PORTFOLIO_SANDBOX_SCHEMA = "portfolio_sandbox.v1"
WEIGHT_TOLERANCE = 0.000_001

VALID_HOLDINGS_VIEWS = frozenset({"direct", "look_through", "combined"})


@dataclass(frozen=True)
class PortfolioCandidate:
    candidate_id: str
    name: str
    analysis_notional_eur: float
    target_weights: tuple[tuple[str, float], ...]
    cash_weight: float
    source_revision: str
    source_checksum: str
    source_as_of: str | None
    schema_version: str = PORTFOLIO_SANDBOX_SCHEMA
    execution_allowed: Literal[False] = False

    @property
    def targets(self) -> dict[str, float]:
        return dict(self.target_weights)


@dataclass(frozen=True)
class PortfolioAllocationRow:
    instrument_id: str
    name: str
    current_weight: float
    target_weight: float
    drift: float
    signed_notional_eur: float
    market_value_eur: float
    drift_status: str
    asset_type: str = "etf"
    capability_status: str = "supported"
    capability_reason: str = "plain_physical_etf"
    marginal_effect: str = "no_change"
    why_not: str = ""


@dataclass(frozen=True)
class PortfolioHoldingRow:
    """One immutable holding line, retaining direct/look-through lineage."""

    instrument_id: str
    name: str
    asset_type: str
    holding_view: str
    current_weight: float
    market_value_eur: float
    capability_status: str
    capability_reason: str
    source_id: str = ""


@dataclass(frozen=True)
class PortfolioConstraintResult:
    name: str
    current_value: float
    target_value: float
    limit: float | None
    status: str
    reason: str


@dataclass(frozen=True)
class PortfolioSnapshotBinding:
    """The source identity required to replay a sandbox result."""

    account_id: str
    portfolio_id: str
    snapshot_id: str
    source_revision: str
    source_checksum: str
    as_of: str | None
    holdings_view: str = "combined"
    execution_allowed: Literal[False] = False


@dataclass(frozen=True)
class PortfolioExposureRow:
    bucket: str
    current_weight: float
    target_weight: float


@dataclass(frozen=True)
class PortfolioAnalysis:
    candidate: PortfolioCandidate
    allocations: tuple[PortfolioAllocationRow, ...]
    sector_exposure: tuple[PortfolioExposureRow, ...]
    region_exposure: tuple[PortfolioExposureRow, ...]
    currency_exposure: tuple[PortfolioExposureRow, ...]
    warnings: tuple[str, ...]
    cost: PortfolioCostEstimate
    current_value_eur: float
    current_cash_weight: float
    source_stale: bool
    overlap: DirectOverlapReport
    execution_allowed: Literal[False] = False
    snapshot_binding: PortfolioSnapshotBinding | None = None
    holdings: tuple[PortfolioHoldingRow, ...] = ()
    constraints: tuple[PortfolioConstraintResult, ...] = ()
    marginal_effects: tuple[tuple[str, float], ...] = ()
    why_not: tuple[tuple[str, str], ...] = ()
    before_after: tuple[tuple[str, float, float], ...] = ()
    service_evidence: dict[str, object] = field(default_factory=dict)
    proposal_boundary: str = "ISSUE-0130:draft-only"

    @property
    def overlap_status(self) -> str:
        return self.overlap.status


def candidate_id(name: str) -> str:
    normalised = _candidate_name(name).casefold()
    return "portfolio_" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:24]


def holdings_checksum(holdings: pd.DataFrame) -> str:
    """Bind every selected source line to the inputs that can affect analysis."""

    rows: list[dict[str, object]] = []
    for _, raw in holdings.iterrows():
        values = raw.to_dict()
        instrument_id = str(values.get("etf_id", values.get("instrument_id", ""))).strip()
        if not instrument_id:
            raise ValueError("holdings contain a blank instrument identifier")
        rows.append(
            {
                "instrument_id": instrument_id,
                "name": _checksum_value(values.get("name")),
                "current_weight": _finite_number(values.get("current_weight", 0.0), "current_weight"),
                "market_value_eur": _finite_number(values.get("market_value_eur", 0.0), "market_value_eur"),
                "holding_view": classify_holding_view(values),
                "holding_view_raw": _checksum_value(values.get("holding_view")),
                "view_raw": _checksum_value(values.get("view")),
                "lineage_raw": _checksum_value(values.get("lineage")),
                "is_look_through": _checksum_value(values.get("is_look_through")),
                "source_id": _checksum_value(values.get("source_id")),
                "holdings_source": _checksum_value(values.get("holdings_source")),
                "asset_type": _checksum_value(values.get("asset_type")),
                "instrument_type": _checksum_value(values.get("instrument_type")),
                "asset_class": _checksum_value(values.get("asset_class")),
                "security_type": _checksum_value(values.get("security_type")),
                "cfi_code": _checksum_value(values.get("cfi_code")),
                "exchange": _checksum_value(values.get("exchange")),
                "leveraged": _checksum_value(values.get("leveraged")),
                "inverse": _checksum_value(values.get("inverse")),
                "derivative": _checksum_value(values.get("derivative")),
                "crypto": _checksum_value(values.get("crypto")),
                "otc": _checksum_value(values.get("otc")),
                "complex_structured": _checksum_value(values.get("complex_structured")),
                "market_cap_usd": _checksum_value(values.get("market_cap_usd")),
                "average_daily_value_usd": _checksum_value(values.get("average_daily_value_usd")),
                "dealing_frequency": _checksum_value(values.get("dealing_frequency")),
            }
        )
    rows.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def asset_capability(asset_type: object) -> tuple[str, str]:
    """Return an explicit unavailable state until the governed resolver runs."""

    _ = asset_type
    return "unavailable", "canonical_capability_resolution_required"


def classify_holding_view(row: object) -> str:
    """Validate and normalise one holding's direct/look-through lineage."""

    values = row if isinstance(row, Mapping) else {}
    raw = values.get("holding_view", values.get("view", values.get("lineage", "direct")))
    if raw is None or (not isinstance(raw, (list, tuple, dict)) and bool(pd.isna(raw))):
        raw = "direct"
    value = str(raw).strip().casefold()
    if value in {"indirect", "indirect_holding"}:
        value = "look_through"
    if value not in {"direct", "look_through"}:
        raise ValueError(f"holding lineage is invalid: {raw}")
    flag = _optional_lineage_flag(values.get("is_look_through"))
    if flag is not None:
        flagged = "look_through" if flag else "direct"
        explicit_lineage = any(
            key in values and values.get(key) is not None and not _is_missing(values.get(key))
            for key in ("holding_view", "view", "lineage")
        )
        if explicit_lineage and value != flagged:
            raise ValueError("holding lineage contradicts is_look_through")
        value = flagged
    return value


def select_holdings_view(holdings: pd.DataFrame, holdings_view: str) -> pd.DataFrame:
    """Select immutable direct/look-through evidence without resolving nesting."""

    view = str(holdings_view or "").strip().casefold()
    if view not in VALID_HOLDINGS_VIEWS:
        raise ValueError("holdings_view must be direct, look_through or combined")
    if not isinstance(holdings, pd.DataFrame):
        raise ValueError("holdings evidence is unavailable")
    if holdings.empty or view == "combined":
        for _, row in holdings.iterrows():
            classify_holding_view(row.to_dict())
        return holdings.copy(deep=True)
    selected = [
        row.to_dict()
        for _, row in holdings.iterrows()
        if classify_holding_view(row.to_dict()) == view
    ]
    return pd.DataFrame(selected, columns=holdings.columns)


def create_candidate(
    config: AppConfig,
    holdings: pd.DataFrame,
    *,
    name: str,
    analysis_notional_eur: object,
    target_weights: dict[str, object],
    cash_weight: object,
    source_revision: str,
    source_as_of: str | None = None,
) -> PortfolioCandidate:
    display_name = _candidate_name(name)
    notional = _finite_number(analysis_notional_eur, "analysis_notional_eur")
    if notional <= 0 or notional > 1_000_000_000_000:
        raise ValueError("analysis_notional_eur must be greater than zero and no more than EUR 1 trillion")
    enabled = {str(item.id) for item in config.universe.etfs if bool(item.enabled)}
    present = _holding_ids(holdings)
    clean_targets: dict[str, float] = {}
    for raw_id, raw_weight in target_weights.items():
        instrument_id = str(raw_id).strip()
        if not instrument_id or (instrument_id not in enabled and instrument_id not in present):
            raise ValueError(f"unknown or disabled instrument: {instrument_id or '<blank>'}")
        if instrument_id in clean_targets:
            raise ValueError(f"duplicate instrument: {instrument_id}")
        weight = _finite_number(raw_weight, f"target weight for {instrument_id}")
        if weight < 0 or weight > 1:
            raise ValueError(f"target weight for {instrument_id} must be between 0% and 100%")
        if weight > 0:
            clean_targets[instrument_id] = weight
    cash = _finite_number(cash_weight, "cash_weight")
    if cash < 0 or cash > 1:
        raise ValueError("cash_weight must be between 0% and 100%")
    total = sum(clean_targets.values()) + cash
    if not math.isclose(total, 1.0, abs_tol=WEIGHT_TOLERANCE):
        raise ValueError(f"target weights plus cash must equal 100%; received {total:.6%}")
    return PortfolioCandidate(
        candidate_id=candidate_id(display_name),
        name=display_name,
        analysis_notional_eur=round(notional, 8),
        target_weights=tuple(sorted((key, round(value, 10)) for key, value in clean_targets.items())),
        cash_weight=round(cash, 10),
        source_revision=str(source_revision or "unknown"),
        source_checksum=holdings_checksum(holdings),
        source_as_of=str(source_as_of).strip() if source_as_of else None,
    )


def analyse_candidate(
    config: AppConfig,
    holdings: pd.DataFrame,
    candidate: PortfolioCandidate,
    *,
    current_revision: str,
    overlap: DirectOverlapReport | None = None,
    target_capabilities: Mapping[str, tuple[str, str, str]] | None = None,
) -> PortfolioAnalysis:
    current_checksum = holdings_checksum(holdings)
    source_stale = (
        candidate.source_revision != str(current_revision or "unknown")
        or candidate.source_checksum != current_checksum
    )
    universe = config.universe.by_id()
    current_lines: dict[str, tuple[list[float], list[float]]] = {}
    holding_rows = _holding_rows(config, holdings)
    for _, item in holdings.iterrows():
        instrument_id = str(item.get("etf_id", item.get("instrument_id", ""))).strip()
        weight = _finite_number(item.get("current_weight", 0.0), "current_weight")
        value = _finite_number(item.get("market_value_eur", 0.0), "market_value_eur")
        weights, values = current_lines.setdefault(instrument_id, ([], []))
        weights.append(weight)
        values.append(value)
    current = {
        instrument_id: (math.fsum(sorted(weights)), math.fsum(sorted(values)))
        for instrument_id, (weights, values) in current_lines.items()
    }

    rows: list[PortfolioAllocationRow] = []
    targets = candidate.targets
    holding_by_id = _aggregate_holding_rows(holding_rows)
    target_capabilities = target_capabilities or {}
    for instrument_id in sorted(set(current) | set(targets)):
        current_weight, market_value = current.get(instrument_id, (0.0, 0.0))
        target_weight = targets.get(instrument_id, 0.0)
        drift = target_weight - current_weight
        configured = config.targets.positions.get(instrument_id)
        soft_band = float(configured.soft_band) if configured else 0.05
        hard_band = float(configured.hard_band) if configured else 0.10
        magnitude = abs(drift)
        status = "inside"
        if magnitude > hard_band:
            status = "above_hard_band"
        elif magnitude > soft_band:
            status = "above_soft_band"
        instrument = universe.get(instrument_id)
        holding = holding_by_id.get(instrument_id)
        target_capability = target_capabilities.get(instrument_id)
        if holding is not None:
            asset_type = holding.asset_type
            capability_status, capability_reason = holding.capability_status, holding.capability_reason
        elif target_capability is not None:
            capability_status, capability_reason, asset_type = target_capability
        else:
            asset_type = _asset_type({}, instrument)
            capability_status, capability_reason = asset_capability(asset_type)
        if capability_status != "supported":
            marginal_effect = "inapplicable"
            why_not = capability_reason
        elif abs(drift) <= WEIGHT_TOLERANCE:
            marginal_effect = "no_change"
            why_not = "no target change requested"
        elif magnitude <= soft_band:
            marginal_effect = "inside_no_trade_band"
            why_not = f"drift {magnitude:.1%} is inside soft band {soft_band:.1%}"
        else:
            marginal_effect = "increase" if drift > 0 else "decrease"
            why_not = ""
        rows.append(
            PortfolioAllocationRow(
                instrument_id=instrument_id,
                name=str(instrument.name) if instrument else instrument_id,
                current_weight=round(current_weight, 10),
                target_weight=round(target_weight, 10),
                drift=round(drift, 10),
                signed_notional_eur=round(drift * candidate.analysis_notional_eur, 8),
                market_value_eur=round(market_value, 8),
                drift_status=status,
                asset_type=asset_type,
                capability_status=capability_status,
                capability_reason=capability_reason,
                marginal_effect=marginal_effect,
                why_not=why_not,
            )
        )

    warnings = _concentration_warnings(config, rows)
    if holdings.empty:
        warnings.insert(0, "No current holdings are available; current-versus-target values use zero current exposure.")
    if source_stale:
        warnings.insert(0, "Saved source binding changed; all derived values were re-evaluated from the current snapshot.")
    overlap_report = overlap or calculate_direct_overlap(
        pd.DataFrame(),
        [row.instrument_id for row in rows],
        current_weights={row.instrument_id: row.current_weight for row in rows},
        target_weights={row.instrument_id: row.target_weight for row in rows},
    )
    warnings.extend(overlap_report.warnings)
    if overlap_report.status == "missing":
        warnings.append("ETF overlap is unavailable because canonical direct holdings evidence is missing.")
    cost = estimate_rebalance_cost(config, candidate.analysis_notional_eur, {row.instrument_id: row.drift for row in rows})
    constraints = _constraint_results(config, rows)
    why_not = tuple((row.instrument_id, row.why_not) for row in rows if row.why_not)
    marginal_effects = tuple((row.instrument_id, row.drift) for row in rows)
    before_after = tuple((row.instrument_id, row.current_weight, row.target_weight) for row in rows)
    return PortfolioAnalysis(
        candidate=candidate,
        allocations=tuple(rows),
        sector_exposure=_exposure(rows, universe, "sector"),
        region_exposure=_exposure(rows, universe, "region"),
        currency_exposure=_exposure(rows, universe, "currency"),
        warnings=tuple(warnings),
        cost=cost,
        current_value_eur=round(sum(value for _, value in current.values()), 8),
        current_cash_weight=round(max(0.0, 1.0 - sum(weight for weight, _ in current.values())), 10),
        source_stale=source_stale,
        overlap=overlap_report,
        holdings=holding_rows,
        constraints=constraints,
        marginal_effects=marginal_effects,
        why_not=why_not,
        before_after=before_after,
    )


def _exposure(rows: list[PortfolioAllocationRow], universe: dict[str, object], field: str) -> tuple[PortfolioExposureRow, ...]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        instrument = universe.get(row.instrument_id)
        value = getattr(instrument, field, None) if instrument else None
        bucket = str(value).strip() if value is not None else "Unavailable"
        current_weight, target_weight = buckets.setdefault(bucket or "Unavailable", [0.0, 0.0])
        buckets[bucket or "Unavailable"] = [current_weight + row.current_weight, target_weight + row.target_weight]
    return tuple(
        PortfolioExposureRow(bucket, round(values[0], 10), round(values[1], 10))
        for bucket, values in sorted(buckets.items(), key=lambda item: (-item[1][1], item[0]))
    )


def _concentration_warnings(config: AppConfig, rows: list[PortfolioAllocationRow]) -> list[str]:
    warnings: list[str] = []
    universe = config.universe.by_id()
    limits = config.risks.portfolio_limits
    for row in rows:
        instrument = universe.get(row.instrument_id)
        cap = min(float(getattr(instrument, "max_weight", 1.0)), float(limits.max_single_etf_weight))
        if row.target_weight > cap:
            warnings.append(f"Target cap exceeded: {row.instrument_id} at {row.target_weight:.1%} (cap {cap:.1%}).")
    for dimension, limit, label in (
        ("sector", float(limits.max_sector_weight), "sector"),
        ("region", float(limits.max_region_weight), "region"),
        ("theme", float(limits.max_theme_weight), "theme"),
    ):
        totals: dict[str, float] = {}
        for row in rows:
            instrument = universe.get(row.instrument_id)
            value = getattr(instrument, dimension, None) if instrument else None
            if value is not None:
                totals[str(value)] = totals.get(str(value), 0.0) + row.target_weight
        for bucket, weight in sorted(totals.items()):
            if weight > limit:
                warnings.append(f"Target {label} cap exceeded: {bucket} at {weight:.1%} (cap {limit:.1%}).")
    return warnings


def _holding_ids(holdings: pd.DataFrame) -> set[str]:
    if holdings.empty:
        return set()
    return {
        str(row.get("etf_id", row.get("instrument_id", ""))).strip()
        for _, row in holdings.iterrows()
        if str(row.get("etf_id", row.get("instrument_id", ""))).strip()
    }


def _asset_type(row: object, configured: object | None = None) -> str:
    values = row if isinstance(row, dict) else {}
    raw = values.get("asset_type") or values.get("instrument_type") or values.get("asset_class")
    if not raw and configured is not None:
        raw = getattr(configured, "instrument_type", None) or getattr(configured, "asset_class", None)
    value = str(raw or "").strip().casefold().replace(" ", "_")
    if not value:
        identifier = str(values.get("etf_id", values.get("instrument_id", ""))).casefold()
        value = "cash" if identifier.startswith("cash") else "fx" if identifier.startswith("fx") else "unknown"
    return value


def _holding_rows(config: AppConfig, holdings: pd.DataFrame) -> tuple[PortfolioHoldingRow, ...]:
    universe = config.universe.by_id()
    rows: list[PortfolioHoldingRow] = []
    for _, raw in holdings.iterrows():
        values = raw.to_dict()
        instrument_id = str(values.get("etf_id", values.get("instrument_id", ""))).strip()
        if not instrument_id:
            continue
        configured = universe.get(instrument_id)
        asset_type = _asset_type(values, configured)
        status = str(values.get("capability_status") or "") or asset_capability(asset_type)[0]
        reason = str(values.get("capability_reason") or "") or asset_capability(asset_type)[1]
        rows.append(
            PortfolioHoldingRow(
                instrument_id=instrument_id,
                name=str(values.get("name") or getattr(configured, "name", instrument_id)),
                asset_type=asset_type,
                holding_view=classify_holding_view(values),
                current_weight=round(_finite_number(values.get("current_weight", 0.0), "current_weight"), 10),
                market_value_eur=round(_finite_number(values.get("market_value_eur", 0.0), "market_value_eur"), 8),
                capability_status=status,
                capability_reason=reason,
                source_id=str(values.get("source_id", values.get("holdings_source", "")) or ""),
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.instrument_id,
                row.holding_view,
                row.source_id,
                row.asset_type,
                row.capability_status,
                row.capability_reason,
                row.current_weight,
                row.market_value_eur,
                row.name,
            ),
        )
    )


def _aggregate_holding_rows(rows: tuple[PortfolioHoldingRow, ...]) -> dict[str, PortfolioHoldingRow]:
    """Select one deterministic fail-closed capability outcome per instrument."""

    precedence = {"unsupported": 0, "unavailable": 1, "partial": 2, "supported": 3}
    grouped: dict[str, list[PortfolioHoldingRow]] = {}
    for row in rows:
        grouped.setdefault(row.instrument_id, []).append(row)
    return {
        instrument_id: min(
            items,
            key=lambda row: (
                precedence.get(row.capability_status, 1),
                row.capability_status,
                row.capability_reason,
                row.asset_type,
                row.holding_view,
                row.source_id,
                row.name,
            ),
        )
        for instrument_id, items in grouped.items()
    }


def _constraint_results(config: AppConfig, rows: list[PortfolioAllocationRow]) -> tuple[PortfolioConstraintResult, ...]:
    limits = config.risks.portfolio_limits
    results: list[PortfolioConstraintResult] = []
    for row in rows:
        instrument = config.universe.by_id().get(row.instrument_id)
        limit = min(float(getattr(instrument, "max_weight", 1.0)), float(limits.max_single_etf_weight)) if instrument else None
        if row.capability_status != "supported":
            status, reason = "inapplicable", row.capability_reason
        elif limit is not None and row.target_weight > limit + WEIGHT_TOLERANCE:
            status, reason = "violated", "target exceeds single-instrument cap"
        else:
            status, reason = "pass", "within applicable instrument constraints"
        results.append(PortfolioConstraintResult(f"instrument:{row.instrument_id}", row.current_weight, row.target_weight, limit, status, reason))
    for field_name, limit, label in (
        ("sector", float(limits.max_sector_weight), "sector"),
        ("region", float(limits.max_region_weight), "region"),
        ("theme", float(limits.max_theme_weight), "theme"),
    ):
        totals: dict[str, float] = {}
        for row in rows:
            instrument = config.universe.by_id().get(row.instrument_id)
            bucket = getattr(instrument, field_name, None) if instrument else None
            if bucket is not None and row.capability_status == "supported":
                totals[str(bucket)] = totals.get(str(bucket), 0.0) + row.target_weight
        for bucket, target in sorted(totals.items()):
            status = "violated" if target > limit + WEIGHT_TOLERANCE else "pass"
            results.append(PortfolioConstraintResult(f"{label}:{bucket}", 0.0, target, limit, status, f"target {target:.1%} vs cap {limit:.1%}"))
    return tuple(results)


def _candidate_name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 80:
        raise ValueError("candidate name must contain 1 to 80 characters")
    return name


def _finite_number(value: object, label: str) -> float:
    if pd.api.types.is_bool(value):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _checksum_value(value: object) -> object:
    """Return a deterministic JSON scalar for source evidence fields."""

    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    return str(value)


def _is_missing(value: object) -> bool:
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if pd.api.types.is_bool(missing) else False


def _optional_lineage_flag(value: object) -> bool | None:
    if value is None or _is_missing(value):
        return None
    if not isinstance(value, bool):
        raise ValueError("is_look_through must be a boolean when provided")
    return value


__all__ = [
    "PORTFOLIO_SANDBOX_SCHEMA",
    "VALID_HOLDINGS_VIEWS",
    "PortfolioAllocationRow",
    "PortfolioAnalysis",
    "PortfolioCandidate",
    "PortfolioExposureRow",
    "PortfolioConstraintResult",
    "PortfolioHoldingRow",
    "PortfolioSnapshotBinding",
    "analyse_candidate",
    "asset_capability",
    "classify_holding_view",
    "candidate_id",
    "create_candidate",
    "holdings_checksum",
    "select_holdings_view",
]
