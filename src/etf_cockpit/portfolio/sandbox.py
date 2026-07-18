"""Deterministic, non-executable portfolio candidate analysis."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Literal

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.portfolio.costs import PortfolioCostEstimate, estimate_rebalance_cost


PORTFOLIO_SANDBOX_SCHEMA = "portfolio_sandbox.v1"
WEIGHT_TOLERANCE = 0.000_001


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
    overlap_status: str = "unavailable_pending_issue_0022"
    execution_allowed: Literal[False] = False


def candidate_id(name: str) -> str:
    normalised = _candidate_name(name).casefold()
    return "portfolio_" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:24]


def holdings_checksum(holdings: pd.DataFrame) -> str:
    """Bind analysis to the exact current-weight/value snapshot."""

    grouped: dict[str, tuple[list[float], list[float]]] = {}
    if not holdings.empty:
        for _, row in holdings.iterrows():
            instrument_id = str(row.get("etf_id", row.get("instrument_id", ""))).strip()
            if not instrument_id:
                raise ValueError("holdings contain a blank instrument identifier")
            weights, values = grouped.setdefault(instrument_id, ([], []))
            weights.append(_finite_number(row.get("current_weight", 0.0), "current_weight"))
            values.append(_finite_number(row.get("market_value_eur", 0.0), "market_value_eur"))
    rows = [
        {
            "instrument_id": instrument_id,
            "current_weight": math.fsum(sorted(weights)),
            "market_value_eur": math.fsum(sorted(values)),
        }
        for instrument_id, (weights, values) in sorted(grouped.items())
    ]
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    clean_targets: dict[str, float] = {}
    for raw_id, raw_weight in target_weights.items():
        instrument_id = str(raw_id).strip()
        if not instrument_id or instrument_id not in enabled:
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
) -> PortfolioAnalysis:
    current_checksum = holdings_checksum(holdings)
    source_stale = (
        candidate.source_revision != str(current_revision or "unknown")
        or candidate.source_checksum != current_checksum
    )
    universe = config.universe.by_id()
    current: dict[str, tuple[float, float]] = {}
    for _, item in holdings.iterrows():
        instrument_id = str(item.get("etf_id", item.get("instrument_id", ""))).strip()
        weight = _finite_number(item.get("current_weight", 0.0), "current_weight")
        value = _finite_number(item.get("market_value_eur", 0.0), "market_value_eur")
        previous_weight, previous_value = current.get(instrument_id, (0.0, 0.0))
        current[instrument_id] = (previous_weight + weight, previous_value + value)

    rows: list[PortfolioAllocationRow] = []
    targets = candidate.targets
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
            )
        )

    warnings = _concentration_warnings(config, rows)
    if holdings.empty:
        warnings.insert(0, "No current holdings are available; current-versus-target values use zero current exposure.")
    if source_stale:
        warnings.insert(0, "Saved source binding changed; all derived values were re-evaluated from the current snapshot.")
    warnings.append("ETF overlap is unavailable until ISSUE-0022 provides complete/partial look-through coverage.")
    cost = estimate_rebalance_cost(config, candidate.analysis_notional_eur, {row.instrument_id: row.drift for row in rows})
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
    for field, limit, label in (
        ("sector", float(limits.max_sector_weight), "sector"),
        ("region", float(limits.max_region_weight), "region"),
        ("theme", float(limits.max_theme_weight), "theme"),
    ):
        totals: dict[str, float] = {}
        for row in rows:
            instrument = universe.get(row.instrument_id)
            value = getattr(instrument, field, None) if instrument else None
            if value is not None:
                totals[str(value)] = totals.get(str(value), 0.0) + row.target_weight
        for bucket, weight in sorted(totals.items()):
            if weight > limit:
                warnings.append(f"Target {label} cap exceeded: {bucket} at {weight:.1%} (cap {limit:.1%}).")
    return warnings


def _candidate_name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 80:
        raise ValueError("candidate name must contain 1 to 80 characters")
    return name


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


__all__ = [
    "PORTFOLIO_SANDBOX_SCHEMA",
    "PortfolioAllocationRow",
    "PortfolioAnalysis",
    "PortfolioCandidate",
    "PortfolioExposureRow",
    "analyse_candidate",
    "candidate_id",
    "create_candidate",
    "holdings_checksum",
]
