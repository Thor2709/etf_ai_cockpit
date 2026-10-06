"""Canonical benchmark-reference context: no-trade current-portfolio reference, VWCE anchor inputs and backtest reference windows (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import (
    Mapping,
    Sequence,
)
from datetime import date
import math
from pathlib import Path
import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.features.cash_comparison import adjusted_endpoint_available_at
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    ReferencePortfolioDefinition,
    VWCE_CANONICAL_ISIN,
    VWCE_CANONICAL_SHARE_CLASS,
    load_canonical_benchmark_registry,
    resolve_vwce_anchor,
)
from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    clip_to_decision_window,
    resolve_canonical_reference,
)
from etf_cockpit.portfolio.sandbox import holdings_checksum


BENCHMARK_REFERENCE_REGISTRY_PATH: Path | None = None


_CANONICAL_REFERENCE_IDS = (
    "reference:equal_weight",
    "reference:maximum_diversification",
    "reference:no_trade",
)


# Holdings-derived portfolio totals are compared in EUR with a deliberately
# tight tolerance: one micro-euro absolute or one part per billion relative.
_NO_TRADE_TOTAL_REL_TOL = 1e-9


_NO_TRADE_TOTAL_ABS_TOL_EUR = 1e-6


def _holdings_imply_consistent_portfolio_total(
    weights: list[float], market_values: list[float],
) -> bool:
    """Require every positive-weight holding to imply one portfolio total."""

    implied_totals: list[float] = []
    for weight, market_value in zip(weights, market_values):
        if weight == 0.0:
            if market_value != 0.0:
                return False
            continue
        implied_total = market_value / weight
        if not math.isfinite(implied_total):
            return False
        implied_totals.append(implied_total)
    if not implied_totals:
        return True
    portfolio_total = implied_totals[0]
    if math.isclose(
        portfolio_total,
        0.0,
        rel_tol=0.0,
        abs_tol=_NO_TRADE_TOTAL_ABS_TOL_EUR,
    ):
        return False
    return all(
        math.isclose(
            implied_total,
            portfolio_total,
            rel_tol=_NO_TRADE_TOTAL_REL_TOL,
            abs_tol=_NO_TRADE_TOTAL_ABS_TOL_EUR,
        )
        for implied_total in implied_totals[1:]
    )


def _benchmark_reference_snapshot_inputs(
    config: AppConfig,
    as_of: object,
    holdings: pd.DataFrame | None = None,
) -> dict[str, object]:
    unavailable: dict[str, object] = {
        "registry": CanonicalBenchmarkRegistry(),
        "instrument": None,
        "currency": None,
        "horizon_years": None,
        "start_date": None,
        "end_date": None,
        "decision_time": None,
        "reference_ids": (),
        "anchor": None,
        "listing_id": None,
    }
    try:
        registry = load_canonical_benchmark_registry(BENCHMARK_REFERENCE_REGISTRY_PATH)
        if any(item.portfolio_id == "reference:no_trade" for item in registry.reference_portfolios):
            registry = CanonicalBenchmarkRegistry(
                benchmarks=registry.benchmarks,
                cash_proxies=registry.cash_proxies,
                peer_sets=registry.peer_sets,
                reference_portfolios=tuple(
                    item
                    for item in registry.reference_portfolios
                    if item.portfolio_id != "reference:no_trade"
                ),
                vwce_anchors=registry.vwce_anchors,
            )
        unavailable["reference_ids"] = _CANONICAL_REFERENCE_IDS
        as_of_timestamp = pd.Timestamp(as_of)
        if pd.isna(as_of_timestamp):
            return unavailable
        end_date = as_of_timestamp.date()
        start_date = (as_of_timestamp - pd.DateOffset(years=1)).date()
        base_currency = config.targets.base_currency.strip().upper()
        decision_time = adjusted_endpoint_available_at(end_date)
        no_trade = _current_portfolio_reference(
            config,
            holdings,
            as_of_date=end_date,
            start_date=start_date,
            decision_time=decision_time,
            currency=base_currency,
        )
        if no_trade is not None:
            registry = CanonicalBenchmarkRegistry(
                benchmarks=registry.benchmarks,
                cash_proxies=registry.cash_proxies,
                peer_sets=registry.peer_sets,
                reference_portfolios=(
                    registry.reference_portfolios + (no_trade,)
                ),
                vwce_anchors=registry.vwce_anchors,
            )
        configured = [
            item for item in config.universe.etfs
            if item.id == "VWCE" and item.isin == VWCE_CANONICAL_ISIN
        ]
        effective_cutoff = pd.Timestamp(start_date, tz="UTC")
        knowledge_cutoff = pd.Timestamp(decision_time)
        anchors = [
            item for item in registry.vwce_anchors
            if item.canonical_isin == VWCE_CANONICAL_ISIN
            and item.canonical_share_class_id == VWCE_CANONICAL_SHARE_CLASS
            and pd.Timestamp(item.effective_at) <= effective_cutoff
            and pd.Timestamp(item.known_at) <= knowledge_cutoff
        ]
        if len(configured) != 1 or not anchors:
            return {**unavailable, "registry": registry}
        vwce = configured[0]
        latest_effective = max(pd.Timestamp(item.effective_at) for item in anchors)
        anchors = [item for item in anchors if pd.Timestamp(item.effective_at) == latest_effective]
        latest_known = max(pd.Timestamp(item.known_at) for item in anchors)
        anchors = [item for item in anchors if pd.Timestamp(item.known_at) == latest_known]
        if len(anchors) != 1:
            return {**unavailable, "registry": registry}
        anchor = anchors[0]
        ticker = vwce.ticker.split(".", maxsplit=1)[0].upper()
        listing_ids = sorted({
            item.listing_id for item in anchor.listing_observations
            if item.ticker == ticker and item.currency == base_currency
        })
        if not listing_ids or start_date >= end_date:
            return {**unavailable, "registry": registry}
        resolutions = {
            listing_id: resolve_vwce_anchor(
                anchor,
                listing_id=listing_id,
                effective_date=start_date.isoformat(),
                decision_time=knowledge_cutoff.isoformat(),
                currency=base_currency,
                horizon_years=1.0,
            )
            for listing_id in listing_ids
        }
        available_listing_ids = [
            listing_id for listing_id, resolution in resolutions.items()
            if resolution.status == "available"
        ]
        if len(available_listing_ids) == 1:
            listing_id = available_listing_ids[0]
        elif len(available_listing_ids) > 1 or len(listing_ids) != 1:
            return {**unavailable, "registry": registry}
        else:
            listing_id = listing_ids[0]
        instrument = {
            "asset_class": vwce.asset_class,
            "country_region": vwce.region or "",
            "sector": vwce.sector or "",
            "currency": vwce.currency,
        }
        return {
            "registry": registry,
            "instrument": instrument,
            "currency": base_currency,
            "horizon_years": 1.0,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "decision_time": knowledge_cutoff.isoformat(),
            "reference_ids": _CANONICAL_REFERENCE_IDS,
            "anchor": anchor,
            "listing_id": listing_id,
        }
    except (BenchmarkReferenceError, OSError, TypeError, ValueError, AttributeError):
        return unavailable


def _reference_context_from_inputs(
    inputs: Mapping[str, object],
    *,
    purpose: str,
    analysis_id: str,
) -> CanonicalReferenceContext:
    registry = inputs.get("registry")
    if not isinstance(registry, CanonicalBenchmarkRegistry):
        registry = CanonicalBenchmarkRegistry()
    instrument_value = inputs.get("instrument")
    currency_value = inputs.get("currency")
    horizon_value = inputs.get("horizon_years")
    start_value = inputs.get("start_date")
    end_value = inputs.get("end_date")
    decision_value = inputs.get("decision_time")
    reference_ids_value = inputs.get("reference_ids", ())
    reference_ids: tuple[str, ...] = (
        tuple(reference_ids_value)
        if isinstance(reference_ids_value, Sequence)
        and not isinstance(reference_ids_value, (str, bytes))
        and all(isinstance(item, str) for item in reference_ids_value)
        else ()
    )
    return resolve_canonical_reference(
        registry,
        analysis_id=analysis_id,
        purpose=purpose,
        instrument_id="VWCE",
        instrument=instrument_value if isinstance(instrument_value, Mapping) else None,
        currency=currency_value if isinstance(currency_value, str) else None,
        horizon_years=horizon_value if isinstance(horizon_value, (int, float)) else None,
        start_date=start_value if isinstance(start_value, str) else None,
        end_date=end_value if isinstance(end_value, str) else None,
        decision_time=decision_value if isinstance(decision_value, str) else None,
        reference_portfolio_ids=reference_ids,
    )


def _backtest_calculation_context(
    config: AppConfig,
    base_context: CanonicalReferenceContext,
    prices: pd.DataFrame,
) -> CanonicalReferenceContext:
    """Resolve benchmark evidence against the complete backtest panel window."""

    resolution = base_context.resolution
    if resolution is None or not isinstance(prices, pd.DataFrame) or prices.empty:
        return base_context
    if not isinstance(base_context.instrument, Mapping):
        return CanonicalReferenceContext(
            base_context.registry,
            None,
            blocker="backtest_reference_inputs_unavailable",
        )
    required = {"date", "etf_id", "adjusted_close"}
    if not required.issubset(prices.columns):
        return base_context
    try:
        frame = prices.loc[:, ["date", "etf_id", "adjusted_close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
        columns = [item for item in config.universe.enabled_ids if item in set(frame["etf_id"].astype(str))]
        pivot = frame[frame["etf_id"].astype(str).isin(columns)].pivot(
            index="date", columns="etf_id", values="adjusted_close"
        ).sort_index()
        pivot = pivot.reindex(columns=columns)
        pivot = pivot.loc[pivot.notna().all(axis=1)]
        if pivot.empty:
            return base_context
        cutoff_date = pd.Timestamp(resolution.declaration.decision_time).date()
        pivot = pivot.loc[pivot.index.date <= cutoff_date]
        if pivot.empty:
            return base_context
        start = pivot.index.min().date()
        end = pivot.index.max().date()
        if start >= end:
            return base_context
        horizon_years = max(0.1, (end - start).days / 365.25)
        base_cutoff = pd.Timestamp(resolution.declaration.decision_time)
        # The original decision-time cutoff is authoritative.  Extending it to
        # cover a complete backtest panel would make later evidence visible.
        decision_time = base_cutoff.isoformat()
        return resolve_canonical_reference(
            base_context.registry,
            analysis_id=f"backtest:{start.isoformat()}:{end.isoformat()}",
            purpose=resolution.declaration.purpose,
            instrument_id=resolution.declaration.instrument_id,
            instrument=base_context.instrument,
            currency=resolution.declaration.currency,
            horizon_years=horizon_years,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            decision_time=decision_time,
            reference_portfolio_ids=resolution.declaration.reference_portfolio_ids,
        )
    except (BenchmarkReferenceError, OSError, TypeError, ValueError, KeyError, AttributeError):
        return CanonicalReferenceContext(base_context.registry, None, blocker="backtest_reference_resolution_unavailable")


def _backtest_prices_for_reference(
    prices: pd.DataFrame,
    reference_context: CanonicalReferenceContext,
) -> pd.DataFrame | None:
    """Replay the exact price snapshot consumed by the backtest checksum."""

    identity = reference_context.identity
    analysis = identity.get("analysis")
    if analysis is None and identity.get("status") == "unavailable":
        return prices
    if not isinstance(analysis, Mapping):
        return None
    clipped = clip_to_decision_window(
        prices,
        start_date=analysis.get("start_date"),
        end_date=analysis.get("end_date"),
        decision_time=analysis.get("decision_time"),
    )
    return None if clipped.empty else clipped


def _current_portfolio_reference(
    config: AppConfig,
    holdings: pd.DataFrame | None,
    *,
    as_of_date: date,
    start_date: date,
    decision_time: str,
    currency: str,
) -> ReferencePortfolioDefinition | None:
    """Build a point-in-time no-trade reference from exact holdings evidence."""

    if not isinstance(holdings, pd.DataFrame) or holdings.empty:
        return None
    instrument_column = "etf_id" if "etf_id" in holdings.columns else "instrument_id"
    required = {instrument_column, "current_weight", "market_value_eur", "as_of_date"}
    if not required.issubset(holdings.columns):
        return None
    try:
        dates = pd.to_datetime(holdings["as_of_date"], errors="coerce")
        if dates.isna().any() or set(dates.dt.date) != {as_of_date}:
            return None
        ids = [str(value).strip() for value in holdings[instrument_column].tolist()]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            return None
        configured_ids = set(config.universe.configured_enabled_ids)
        if any(value not in configured_ids for value in ids):
            return None
        raw_weights = holdings["current_weight"].tolist()
        if any(isinstance(value, bool) for value in raw_weights):
            return None
        weights = pd.to_numeric(holdings["current_weight"], errors="coerce").tolist()
        if any(
            not math.isfinite(float(value))
            or float(value) < 0
            or float(value) > 1
            for value in weights
        ):
            return None
        raw_market_values = holdings["market_value_eur"].tolist()
        if any(isinstance(value, bool) for value in raw_market_values):
            return None
        market_values = pd.to_numeric(holdings["market_value_eur"], errors="coerce").tolist()
        if any(
            not math.isfinite(float(value))
            or float(value) < 0
            for value in market_values
        ):
            return None
        total = math.fsum(float(value) for value in weights)
        if not math.isfinite(total) or total > 1.0:
            return None
        if not _holdings_imply_consistent_portfolio_total(
            [float(value) for value in weights],
            [float(value) for value in market_values],
        ):
            return None
        knowledge_columns = tuple(
            column
            for column in ("known_at", "imported_at", "available_at")
            if column in holdings.columns
        )
        if not knowledge_columns:
            return None
        effective_time = pd.Timestamp(as_of_date, tz="UTC")
        cutoff_time = pd.Timestamp(decision_time)
        source_knowledge_times: list[pd.Timestamp] = []
        for _, row in holdings.iterrows():
            row_knowledge_times: list[pd.Timestamp] = []
            for column in knowledge_columns:
                raw_value = row[column]
                if raw_value is None or pd.isna(raw_value):
                    continue
                parsed = pd.to_datetime(raw_value, errors="coerce")
                if pd.isna(parsed) or getattr(parsed, "tzinfo", None) is None:
                    return None
                parsed_utc = pd.to_datetime(parsed, errors="coerce", utc=True)
                if pd.isna(parsed_utc):
                    return None
                row_knowledge_times.append(pd.Timestamp(parsed_utc))
            if not row_knowledge_times:
                return None
            row_knowledge_time = max(row_knowledge_times)
            if row_knowledge_time < effective_time or row_knowledge_time > cutoff_time:
                return None
            source_knowledge_times.append(row_knowledge_time)
        cash_id = f"cash:{currency}"
        if cash_id in ids:
            return None
        current_weights = {
            instrument_id: float(weight)
            for instrument_id, weight in sorted(zip(ids, weights), key=lambda item: item[0])
        }
        current_weights[cash_id] = float(1.0 - total)
        source_hash = holdings_checksum(holdings)
        source_knowledge_time = max(source_knowledge_times).isoformat()
        return ReferencePortfolioDefinition(
            portfolio_id="reference:no_trade",
            version="1.0.0",
            method="no_trade",
            constituent_instrument_ids=tuple(current_weights),
            methodology="Hold the exact current positions and implied base-currency cash with zero proposed turnover.",
            effective_at=f"{as_of_date.isoformat()}T00:00:00+00:00",
            known_at=source_knowledge_time,
            current_weights=current_weights,
            currency=currency,
            minimum_horizon_years=0.1,
            maximum_horizon_years=50.0,
            start_date=start_date.isoformat(),
            end_date=as_of_date.isoformat(),
            source_hashes=(source_hash,),
        )
    except (ArithmeticError, TypeError, ValueError, KeyError):
        return None
