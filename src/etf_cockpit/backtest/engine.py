from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Callable, Mapping
import hashlib
import json
from itertools import combinations
from statistics import NormalDist
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from etf_cockpit.backtest.benchmarks import equal_weights, momentum_weights, target_weights, trend_weights
from etf_cockpit.backtest.metrics import performance_metrics
from etf_cockpit.application.benchmark_reference import (
    clip_to_decision_window,
    validate_benchmark_reference,
)
from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.data.provenance import sha256_dataframe
from etf_cockpit.data.market_calendar import (
    ClockContext,
    ListingCalendarEvidence,
    MarketCalendarService,
    MarketClockError,
)
from etf_cockpit.data.etf_structure import structure_confidence_caps, structure_input_checksum
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.portfolio.costs import COST_MODEL_ID, CostEstimate, estimate_rebalance_cost
from etf_cockpit.portfolio.benchmark_reference_contract import (
    CanonicalBenchmarkRegistry,
    unavailable_reference_projection,
    validate_execution_disabled,
)
from etf_cockpit.signals.quality_momentum import FRAME_COLUMNS, QUALITY_MOMENTUM_VERSION, build_quality_momentum_frame, quality_momentum_weights
from etf_cockpit.signals.signal_pipeline import generate_signals


CANONICAL_OPERATIONAL_EVIDENCE_REASON = "canonical_local_backtest_evidence"
CANONICAL_PRICE_PROVENANCE = "row_bound_corporate_action_consistent"
_CALENDAR_COLUMNS = (
    "calendar_listing_id",
    "calendar_mic",
    "calendar_id",
    "calendar_timezone",
    "calendar_source_id",
    "calendar_source_checksum",
    "calendar_source_version",
    "calendar_opening_auction_minutes",
    "calendar_closing_auction_minutes",
    "calendar_identity_decision_id",
    "calendar_valid_from",
    "calendar_known_at",
    "calendar_identity_lineage_hash",
)


@dataclass(frozen=True)
class BacktestReport:
    results: pd.DataFrame
    equity_curves: pd.DataFrame
    trade_log: pd.DataFrame
    signal_log: pd.DataFrame
    ai_added_value: bool
    quality_label: str = "low"
    quality_notes: list[str] | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    quality_momentum_evidence: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def operational_evidence(self) -> pd.DataFrame:
        """Return the persisted, exact-instrument operational projection."""

        rows = self.metadata.get("operational_evidence_rows", [])
        if not isinstance(rows, list):
            return pd.DataFrame()
        if any(not isinstance(row, Mapping) for row in rows):
            return pd.DataFrame()
        frame = pd.DataFrame([dict(row) for row in rows])
        for field_name in (
            "execution_delay_sessions",
            "calendar_opening_auction_minutes",
            "calendar_closing_auction_minutes",
        ):
            if field_name in frame:
                frame[field_name] = pd.Series(
                    [row.get(field_name) for row in rows],
                    dtype=object,
                )
        return frame


class BacktestDataUnavailableError(ValueError):
    """Raised when a backtest cannot be evaluated from a complete price panel."""


def backtest_input_checksum(
    config: AppConfig,
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame | None,
    *,
    structure_document_registry: object = None,
    structure_report_records: object = None,
    structure_supplemental_rows: object = None,
    structure_holdings: object = None,
) -> str:
    """Fingerprint every local input that can change a cached backtest."""

    def _stable(frame: pd.DataFrame | None, preferred_sort: tuple[str, ...]) -> str:
        if not isinstance(frame, pd.DataFrame):
            return sha256_dataframe(pd.DataFrame())
        result = frame.copy()
        sort_columns = [column for column in preferred_sort if column in result.columns]
        if sort_columns and not result.empty:
            result = result.sort_values(sort_columns, kind="stable").reset_index(drop=True)
        return sha256_dataframe(result)

    universe_payload = {
        "enabled_ids": list(config.universe.enabled_ids),
        "sectors": {
            item.id: item.sector
            for item in config.universe.etfs
            if item.id in config.universe.enabled_ids
        },
        "costs": config.costs.model_dump(mode="json"),
    }
    payload = {
        "prices": _stable(prices, ("date", "etf_id", "instrument_id")),
        "fundamentals": _stable(fundamentals, ("instrument_id", "as_of_date", "available_at", "evidence_checksum")),
        "structure": structure_input_checksum(
            document_registry=structure_document_registry,
            report_records=structure_report_records,
            supplemental_rows=structure_supplemental_rows,
            holdings=structure_holdings,
        ),
        "universe": universe_payload,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def quality_momentum_evidence_checksum(evidence: pd.DataFrame | bytes) -> str:
    """Checksum quality-momentum evidence before or after CSV persistence."""

    payload = evidence if isinstance(evidence, bytes) else evidence.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _price_pivot(prices: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        raise BacktestDataUnavailableError("not_enough_data: no price rows were supplied")
    required = {"date", "etf_id", "adjusted_close"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise BacktestDataUnavailableError(f"invalid_price_data: missing required columns {', '.join(missing)}")
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    return frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().dropna(how="all")


def _declared_calculation_window(
    reference_identity: Mapping[str, object] | None,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    if reference_identity is None:
        return None
    analysis = reference_identity.get("analysis") if isinstance(reference_identity, Mapping) else None
    if analysis is None and reference_identity.get("status") == "unavailable":
        return None
    if not isinstance(analysis, Mapping):
        raise BacktestDataUnavailableError("invalid_reference_window: calculation window is missing")
    try:
        start = _naive_utc_timestamp(analysis["start_date"])
        end = _naive_utc_timestamp(analysis["end_date"])
        decision_time = _naive_utc_timestamp(analysis["decision_time"])
    except (KeyError, TypeError, ValueError):
        raise BacktestDataUnavailableError("invalid_reference_window: calculation window is malformed")
    if (
        pd.isna(start)
        or pd.isna(end)
        or pd.isna(decision_time)
        or start > end
        or end.normalize() > decision_time.normalize()
    ):
        raise BacktestDataUnavailableError("invalid_reference_window: calculation window is outside decision time")
    return start.normalize(), end.normalize()


def _naive_utc_timestamp(value: object) -> pd.Timestamp:
    parsed = pd.Timestamp(str(value))
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC").tz_localize(None)
    return parsed


def _validated_benchmark_data_id(
    benchmark_data_id: str | None,
    benchmark_reference: Mapping[str, object] | None,
    reference_identity: Mapping[str, object] | None,
    benchmark_registry: CanonicalBenchmarkRegistry | None,
    available_columns: pd.Index,
) -> str | None:
    """Use a benchmark only when its projection and identity agree exactly."""

    if (
        benchmark_reference is None
        or reference_identity is None
        or validate_benchmark_reference(
            benchmark_reference,
            benchmark_data_id,
            registry=benchmark_registry,
        )
        is None
    ):
        return None
    validate_execution_disabled(benchmark_reference)
    validate_execution_disabled(reference_identity)
    if benchmark_reference.get("status") != "available" or reference_identity.get("status") != "available":
        return None
    benchmark = benchmark_reference.get("benchmark")
    cash = benchmark_reference.get("cash")
    if not isinstance(benchmark, Mapping) or not isinstance(cash, Mapping):
        return None
    if benchmark.get("status") != "available" or cash.get("status") != "available":
        return None
    selected_id = str(benchmark_data_id).strip() if benchmark_data_id is not None else ""
    if not selected_id or selected_id not in available_columns:
        return None
    if benchmark_reference.get("benchmark_data_id") != selected_id:
        return None
    if reference_identity.get("benchmark_data_id") != selected_id:
        return None
    if reference_identity.get("registry_hash") != benchmark_reference.get("registry_hash"):
        return None
    if reference_identity.get("selected_records") != benchmark_reference.get("selected_records"):
        return None
    return selected_id


def _optional_price_pivot(prices: pd.DataFrame, value: str, columns: list[str]) -> pd.DataFrame:
    if value not in prices.columns:
        return pd.DataFrame(index=pd.to_datetime(prices["date"]).drop_duplicates().sort_values(), columns=columns, dtype=float)
    frame = prices.loc[:, ["date", "etf_id", value]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame[value] = pd.to_numeric(frame[value], errors="coerce")
    return frame.pivot(index="date", columns="etf_id", values=value).sort_index().reindex(columns=columns)


def _corporate_action_adjusted_pivot(
    prices: pd.DataFrame, value: str, columns: list[str]
) -> pd.DataFrame:
    """Scale raw OHLC values with the same row's adjusted-close factor.

    The vector backtest is calculated on adjusted closes.  Raw OHLC values are
    only suitable for the operational range proxy after they have been bound
    to that same row's corporate-action factor.  A missing close or adjustment
    factor therefore remains missing instead of being guessed.
    """

    dates = pd.to_datetime(prices["date"], errors="coerce")
    index = dates.dropna().drop_duplicates().sort_values()
    if value not in prices.columns or "close" not in prices.columns:
        return pd.DataFrame(index=index, columns=columns, dtype=float)
    frame = prices.loc[:, ["date", "etf_id", value, "close", "adjusted_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in (value, "close", "adjusted_close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    factor = frame["adjusted_close"].div(frame["close"])
    valid_factor = frame["close"].gt(0) & frame["adjusted_close"].gt(0) & np.isfinite(factor)
    frame[value] = frame[value].where(valid_factor) * factor.where(valid_factor)
    return frame.pivot(index="date", columns="etf_id", values=value).sort_index().reindex(columns=columns)


def _price_source_identity(prices: pd.DataFrame, instrument_id: object, observed_date: object) -> str | None:
    """Return one source identity for one exact instrument/date row."""

    if not isinstance(prices, pd.DataFrame) or "etf_id" not in prices.columns:
        return None
    day = pd.Timestamp(observed_date).normalize()
    dates = pd.to_datetime(prices.get("date"), errors="coerce")
    rows = prices.loc[(prices["etf_id"] == instrument_id) & (dates.dt.normalize() == day)]
    if len(rows) != 1:
        return None
    row = rows.iloc[0]
    source = str(row.get("source", "")).strip()
    provider_symbol = str(row.get("provider_symbol", "")).strip()
    if not source or not provider_symbol or source.casefold() in {"nan", "none"} or provider_symbol.casefold() in {"nan", "none"}:
        return None
    return f"{source}|{provider_symbol}"


def _calendar_projection(identity: Mapping[str, object], instrument_id: str) -> dict[str, object]:
    """Normalise the existing identity-master listing projection shape."""

    if identity.get("status") != "available" or identity.get("instrument_id") != instrument_id:
        return {}
    if isinstance(identity.get("identity_objects"), list):
        return dict(identity)
    fields = identity.get("fields")
    if not isinstance(fields, Mapping):
        fields = identity
    required = ("mic", "calendar_id", "timezone")
    if not all(type(fields.get(key)) is str and fields.get(key).strip() for key in required):
        return {}
    listing_id = fields.get("listing_id") or fields.get("listing")
    source_id = fields.get("source_id") or fields.get("calendar_source_id")
    known_at = fields.get("known_at") or fields.get("calendar_known_at")
    valid_from = fields.get("valid_from") or fields.get("calendar_valid_from")
    if not all(isinstance(value, str) and value.strip() for value in (listing_id, source_id, known_at, valid_from)):
        return {}
    return {
        "status": "available",
        "instrument_id": instrument_id,
        "identity_decision_id": fields.get("decision_id") or source_id,
        "identity_decision_time": known_at,
        "identity_effective_at": valid_from,
        "identity_objects": [
            {
                "object_type": "listing",
                "object_id": listing_id,
                "fields": {
                    "mic": fields["mic"],
                    "calendar_id": fields["calendar_id"],
                    "timezone": fields["timezone"],
                    "calendar_source_version": fields.get("source_version") or fields.get("calendar_source_version") or "identity-master.v1",
                    "opening_auction_minutes": fields.get("opening_auction_minutes", 0),
                    "closing_auction_minutes": fields.get("closing_auction_minutes", 0),
                },
            }
        ],
        "identity_history": [{"source_id": source_id}],
        "_persisted_source_checksum": fields.get("source_checksum") or fields.get("calendar_source_checksum"),
        "_persisted_lineage_hash": fields.get("identity_lineage_hash") or fields.get("calendar_identity_lineage_hash"),
    }


def _explicit_utc_timestamp(value: object) -> pd.Timestamp | None:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert(timezone.utc)


def _canonical_calendar_contract(
    identity: object,
    instrument_id: str,
    signal_timestamp: object,
    execution_timestamp: object,
    *,
    service: MarketCalendarService | None = None,
) -> tuple[dict[str, object], str | None]:
    """Revalidate one exact next-session pair through the calendar service."""

    if isinstance(identity, ListingCalendarEvidence):
        listing = identity
        if listing.instrument_id != instrument_id:
            return {}, "canonical_market_calendar_identity_unavailable"
        persisted: Mapping[str, object] = {}
        decision_id = listing.source_id
    elif isinstance(identity, Mapping):
        projection = _calendar_projection(identity, instrument_id)
        if not projection:
            return {}, "canonical_market_calendar_identity_unavailable"
        try:
            listing = MarketCalendarService.listing_from_identity_projection(projection)
        except (MarketClockError, TypeError, ValueError):
            return {}, "canonical_market_calendar_identity_unavailable"
        persisted = identity
        decision_id = projection.get("identity_decision_id")
        expected_source = persisted.get("_persisted_source_checksum") or persisted.get("calendar_source_checksum")
        if expected_source not in {None, listing.source_checksum}:
            return {}, "canonical_market_calendar_lineage_conflict"
        expected_lineage = persisted.get("_persisted_lineage_hash") or persisted.get("calendar_identity_lineage_hash")
        if expected_lineage not in {None, listing.lineage_hash}:
            return {}, "canonical_market_calendar_lineage_conflict"
    else:
        return {}, "canonical_market_calendar_identity_unavailable"

    def instant(value: object) -> datetime | None:
        parsed = _explicit_utc_timestamp(value)
        return None if parsed is None else parsed.to_pydatetime()

    signal_instant = instant(signal_timestamp)
    execution_instant = instant(execution_timestamp)
    if signal_instant is None or execution_instant is None or execution_instant <= signal_instant:
        return {}, "canonical_market_session_timestamp_unavailable"
    calendar_service = service or MarketCalendarService()
    try:
        zone = ZoneInfo(listing.timezone)
        signal_day = signal_instant.astimezone(zone).date()
        execution_day = execution_instant.astimezone(zone).date()
        cutoff = signal_instant
        if not calendar_service.is_business_day(listing, signal_day, knowledge_cutoff=cutoff):
            return {}, "canonical_signal_session_unavailable"
        if not calendar_service.is_business_day(listing, execution_day, knowledge_cutoff=cutoff):
            return {}, "canonical_execution_session_unavailable"
        candidate = signal_day + timedelta(days=1)
        for _ in range(370):
            if calendar_service.is_business_day(listing, candidate, knowledge_cutoff=cutoff):
                break
            candidate += timedelta(days=1)
        else:
            return {}, "canonical_next_session_unavailable"
        if candidate != execution_day:
            return {}, "execution_not_next_canonical_market_session"
        signal_state = calendar_service.market_state(
            listing, ClockContext.at(signal_instant, knowledge_cutoff=cutoff)
        )
        execution_state = calendar_service.market_state(
            listing, ClockContext.at(execution_instant, knowledge_cutoff=cutoff)
        )
        if signal_state.certification != "certified" or execution_state.certification != "certified":
            return {}, "canonical_market_session_unavailable"
        if signal_state.session_close is None or signal_instant < signal_state.session_close:
            return {}, "decision_price_not_available_at_signal_timestamp"
        if execution_state.session_close is None or execution_instant < execution_state.session_close:
            return {}, "next_period_reference_not_available_at_execution_timestamp"
    except (MarketClockError, ZoneInfoNotFoundError, TypeError, ValueError, OverflowError):
        return {}, "canonical_market_session_unavailable"
    lineage_payload = {
        "listing": listing.lineage_hash,
        "signal_state": signal_state.lineage_hash,
        "execution_state": execution_state.lineage_hash,
        "signal_date": signal_day.isoformat(),
        "execution_date": execution_day.isoformat(),
    }
    lineage = hashlib.sha256(json.dumps(lineage_payload, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "calendar_listing_id": listing.listing_id,
        "calendar_mic": listing.mic,
        "calendar_id": listing.calendar_id,
        "calendar_timezone": listing.timezone,
        "calendar_source_id": listing.source_id,
        "calendar_source_checksum": listing.source_checksum,
        "calendar_source_version": listing.source_version,
        "calendar_opening_auction_minutes": listing.opening_auction_minutes,
        "calendar_closing_auction_minutes": listing.closing_auction_minutes,
        "calendar_identity_decision_id": str(decision_id),
        "calendar_valid_from": listing.valid_from.isoformat(),
        "calendar_known_at": listing.known_at.astimezone(timezone.utc).isoformat(),
        "calendar_identity_lineage_hash": listing.lineage_hash,
        "calendar_session_lineage_hash": lineage,
        "signal_date": signal_day,
        "execution_date": execution_day,
    }, None


def _canonical_session_close_timestamp(
    identity: object,
    instrument_id: str,
    session_date: object,
    *,
    service: MarketCalendarService,
    knowledge_cutoff: object,
) -> datetime | None:
    """Return a certified close instant using only knowledge available at the cutoff."""

    if not isinstance(identity, Mapping):
        return None
    projection = _calendar_projection(identity, instrument_id)
    if not projection:
        return None
    try:
        listing = service.listing_from_identity_projection(projection)
        day = pd.Timestamp(session_date).date()
        cutoff = pd.Timestamp(knowledge_cutoff)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize(timezone.utc)
        else:
            cutoff = cutoff.tz_convert(timezone.utc)
        probe = datetime.combine(day, time(23, 59), ZoneInfo(listing.timezone)).astimezone(
            timezone.utc
        )
        state = service.market_state(
            listing,
            ClockContext.at(probe, knowledge_cutoff=cutoff.to_pydatetime()),
        )
    except (MarketClockError, ZoneInfoNotFoundError, TypeError, ValueError, OverflowError):
        return None
    if state.certification != "certified" or not state.is_session:
        return None
    return state.session_close


def _calendar_identity_from_price_rows(prices: pd.DataFrame, instrument_id: object) -> Mapping[str, object] | None:
    """Read only explicit persisted calendar identity from price rows."""

    if not isinstance(prices, pd.DataFrame) or "etf_id" not in prices.columns:
        return None
    rows = prices.loc[prices["etf_id"] == instrument_id]
    if rows.empty:
        return None
    if "calendar_identity" in rows.columns:
        values = rows["calendar_identity"].tolist()
        if not values or any(not isinstance(value, Mapping) for value in values):
            return None
        try:
            encoded = [
                json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
                for value in values
            ]
        except (TypeError, ValueError):
            return None
        if len(set(encoded)) == 1:
            return json.loads(encoded[0])
        return None
    if not set(_CALENDAR_COLUMNS).issubset(rows.columns):
        return None
    values: dict[str, object] = {}
    for column in _CALENDAR_COLUMNS:
        unique = [value for value in rows[column].tolist() if value is not None and not pd.isna(value)]
        if not unique or len({str(value) for value in unique}) != 1:
            return None
        values[column] = unique[0]
    return {
        "instrument_id": str(instrument_id),
        "listing_id": values["calendar_listing_id"],
        "mic": values["calendar_mic"],
        "calendar_id": values["calendar_id"],
        "timezone": values["calendar_timezone"],
        "source_id": values["calendar_source_id"],
        "source_checksum": values["calendar_source_checksum"],
        "source_version": values["calendar_source_version"],
        "opening_auction_minutes": values["calendar_opening_auction_minutes"],
        "closing_auction_minutes": values["calendar_closing_auction_minutes"],
        "decision_id": values["calendar_identity_decision_id"],
        "valid_from": values["calendar_valid_from"],
        "known_at": values["calendar_known_at"],
        "identity_lineage_hash": values["calendar_identity_lineage_hash"],
    }


def _weighted_reference_price(values: pd.Series, weights: pd.Series) -> float | None:
    observed = pd.to_numeric(values, errors="coerce").reindex(weights.index)
    usable = observed.notna() & np.isfinite(observed)
    if not usable.any():
        return None
    allocation = pd.to_numeric(weights, errors="coerce").abs().reindex(weights.index).fillna(0.0)
    allocation = allocation.where(usable, 0.0)
    if float(allocation.sum()) <= 0:
        allocation = usable.astype(float)
    allocation = allocation / allocation.sum()
    return float((observed.fillna(0.0) * allocation).sum())


def _execution_evidence(
    *,
    current_prices: pd.Series,
    next_adjusted_close: pd.Series,
    next_open: pd.Series,
    next_high: pd.Series,
    next_low: pd.Series,
    changed_weights: pd.Series,
    signal_timestamp: object = None,
    execution_timestamp: object = None,
    cost_spread_assumption_bps: float | None = None,
    cost_spread_assumption_source: str | None = None,
    estimated_cost_bps: float | None = None,
    estimated_cost_bps_source: str | None = None,
) -> dict[str, object]:
    decision_price = _weighted_reference_price(current_prices, changed_weights)
    next_open_reference = _weighted_reference_price(next_open, changed_weights)
    next_close_reference = _weighted_reference_price(next_adjusted_close, changed_weights)
    spread_values = (
        pd.to_numeric(next_high, errors="coerce") - pd.to_numeric(next_low, errors="coerce")
    ) / pd.to_numeric(next_open, errors="coerce")
    spread_proxy = _weighted_reference_price(spread_values, changed_weights)
    arrival_assumption = "next_adjusted_close" if next_close_reference is not None else "unavailable"
    close_to_next_open = None
    if decision_price is not None and next_open_reference is not None and decision_price != 0:
        close_to_next_open = float(next_open_reference / decision_price - 1.0)
    return {
        "decision_price": decision_price,
        "next_open_reference_price": next_open_reference,
        "next_period_reference_price": next_close_reference,
        "decision_price_basis": "adjusted_close" if decision_price is not None else "unavailable",
        "next_open_reference_basis": "adjusted_ohlc_from_same_row_adjustment" if next_open_reference is not None else "unavailable",
        "next_period_reference_basis": "adjusted_close" if next_close_reference is not None else "unavailable",
        "price_provenance": "row_bound_corporate_action_consistent" if all(
            value is not None for value in (decision_price, next_open_reference, next_close_reference)
        ) else "unavailable",
        "close_to_next_open_gap": close_to_next_open,
        "arrival_price_assumption": arrival_assumption,
        "spread_proxy": spread_proxy,
        "observed_range_spread_proxy": spread_proxy,
        "cost_spread_assumption_bps": cost_spread_assumption_bps,
        "cost_spread_assumption_source": cost_spread_assumption_source,
        "estimated_cost_bps": estimated_cost_bps,
        "estimated_cost_bps_source": estimated_cost_bps_source,
        "execution_delay_sessions": 1,
        "same_bar_execution_avoided": True,
        "signal_timestamp": signal_timestamp,
        "execution_timestamp": execution_timestamp,
        "fill_source": "simulated_backtest",
        "session_state": None,
        "auction_state": None,
        "expiry_state": None,
        "order_lifecycle": None,
        "execution_allowed": False,
    }


def _instrument_operational_evidence(
    *,
    instrument_id: object,
    strategy: str,
    signal_timestamp: object,
    execution_timestamp: object,
    signal_date: object,
    execution_date: object,
    decision_price: object,
    next_open: object,
    next_period_close: object,
    high: object,
    low: object,
    open_price: object,
    cost_spread_assumption_bps: object,
    cost_spread_assumption_source: object,
    estimated_cost_bps: object = None,
    estimated_cost_bps_source: object = None,
    canonical_session_dates: object = None,
    calendar_identity: object = None,
    calendar_service: MarketCalendarService | None = None,
    decision_price_basis: object = "adjusted_close",
    next_open_reference_basis: object = "adjusted_ohlc_from_same_row_adjustment",
    next_period_reference_basis: object = "adjusted_close",
    price_provenance: object = "row_bound_corporate_action_consistent",
    decision_price_source_identity: object = None,
    next_open_source_identity: object = None,
    next_period_source_identity: object = None,
) -> dict[str, object]:
    """Build one strict, instrument-scoped operational evidence record.

    This is descriptive evidence only.  Missing OHLC, session/order lifecycle,
    or contradictory timestamps never become a positive execution claim.
    """

    def finite(value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if np.isfinite(result) else None

    identity = str(instrument_id).strip() if instrument_id is not None else ""
    signal_ts = _explicit_utc_timestamp(signal_timestamp)
    execution_ts = _explicit_utc_timestamp(execution_timestamp)
    reasons: list[str] = []
    if not identity:
        reasons.append("exact_instrument_identity_unavailable")
    if signal_ts is None or execution_ts is None:
        reasons.append("signal_or_execution_timestamp_unavailable")
    elif execution_ts <= signal_ts:
        reasons.append("same_session_or_non_forward_execution")

    calendar_fields: dict[str, object] = {}
    valid_next_session = False
    canonical_signal_day: date | None = None
    canonical_execution_day: date | None = None
    if calendar_identity is not None:
        calendar_fields, calendar_reason = _canonical_calendar_contract(
            calendar_identity,
            identity,
            signal_timestamp,
            execution_timestamp,
            service=calendar_service,
        )
        if calendar_reason is not None:
            reasons.append(calendar_reason)
        else:
            valid_next_session = True
            signal_day_value = calendar_fields.get("signal_date")
            execution_day_value = calendar_fields.get("execution_date")
            canonical_signal_day = signal_day_value if isinstance(signal_day_value, date) else None
            canonical_execution_day = (
                execution_day_value if isinstance(execution_day_value, date) else None
            )
    elif canonical_session_dates is None:
        reasons.append("canonical_market_session_unavailable")
    else:
        # Kept for the narrow unit-test seam.  The production backtest never
        # supplies this value; it must use the identity-bound service above.
        canonical_dates: list[date] = []
        try:
            canonical_dates = sorted(
                {
                    pd.Timestamp(value).date()
                    for value in canonical_session_dates
                    if not pd.isna(pd.Timestamp(value))
                }
            )
        except (TypeError, ValueError, OverflowError):
            canonical_dates = []
        if not canonical_dates:
            reasons.append("canonical_market_session_unavailable")
        elif signal_ts is not None and execution_ts is not None:
            signal_day = signal_ts.date()
            execution_day = execution_ts.date()
            if signal_day not in canonical_dates or execution_day not in canonical_dates:
                reasons.append("observed_business_date_unavailable")
            elif canonical_dates.index(execution_day) != canonical_dates.index(signal_day) + 1:
                reasons.append("execution_not_next_canonical_market_session")
            elif signal_day.weekday() >= 5 or execution_day.weekday() >= 5:
                reasons.append("non_business_session_date")
            elif any(
                day.date() not in canonical_dates
                for day in pd.bdate_range(signal_day, execution_day)[1:-1]
            ):
                reasons.append("observed_business_date_unavailable")
            else:
                valid_next_session = True
                canonical_signal_day = signal_day
                canonical_execution_day = execution_day

    decision = finite(decision_price)
    next_open_value = finite(next_open)
    next_close = finite(next_period_close)
    observed_open = finite(open_price)
    observed_high = finite(high)
    observed_low = finite(low)
    if decision is None or decision <= 0:
        reasons.append("decision_price_unavailable")
    if next_open_value is None or next_open_value <= 0:
        reasons.append("next_open_reference_unavailable")
    if next_close is None or next_close <= 0:
        reasons.append("next_period_reference_unavailable")
    if observed_open is None or observed_high is None or observed_low is None:
        reasons.append("observed_ohlc_incomplete")
    if any(value is not None and value < 0 for value in (observed_open, observed_high, observed_low)):
        reasons.append("observed_ohlc_invalid")
    if (
        observed_open is not None
        and observed_high is not None
        and observed_low is not None
        and (observed_open <= 0 or observed_high < observed_low)
    ):
        reasons.append("observed_ohlc_contradictory")
    if (
        observed_open is not None
        and observed_high is not None
        and observed_low is not None
        and next_close is not None
        and (
            observed_high < max(observed_open, next_close)
            or observed_low > min(observed_open, next_close)
        )
    ):
        reasons.append("observed_ohlc_does_not_contain_adjusted_close")

    source_identities = (
        decision_price_source_identity,
        next_open_source_identity,
        next_period_source_identity,
    )
    if any(type(value) is not str or not value.strip() for value in source_identities):
        reasons.append("price_source_identity_unavailable")
    elif len(set(source_identities)) != 1:
        reasons.append("price_source_identity_conflict")
    if decision_price_basis != "adjusted_close":
        reasons.append("decision_price_basis_unavailable")
    if next_open_reference_basis != "adjusted_ohlc_from_same_row_adjustment":
        reasons.append("next_open_reference_basis_unavailable")
    if next_period_reference_basis != "adjusted_close":
        reasons.append("next_period_reference_basis_unavailable")
    if type(price_provenance) is not str or not price_provenance.strip():
        reasons.append("price_provenance_unavailable")
    elif price_provenance != CANONICAL_PRICE_PROVENANCE:
        reasons.append("noncanonical_price_provenance")
    def cost_pair(value: object, source: object, label: str) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            if source is not None and not (isinstance(source, float) and pd.isna(source)):
                reasons.append(f"{label}_source_without_value")
            return None
        parsed = finite(value)
        if parsed is None or parsed < 0:
            reasons.append(f"{label}_invalid")
            return None
        if type(source) is not str or not source.strip():
            reasons.append(f"{label}_source_unavailable")
        return parsed

    cost_spread = cost_pair(cost_spread_assumption_bps, cost_spread_assumption_source, "cost_spread_assumption")
    estimated_cost = cost_pair(estimated_cost_bps, estimated_cost_bps_source, "estimated_cost")

    observed_spread = None
    if "observed_ohlc_incomplete" not in reasons:
        if (
            observed_open is not None
            and observed_open > 0
            and observed_high is not None
            and observed_low is not None
            and observed_high >= observed_low
        ):
            observed_spread = float((observed_high - observed_low) / observed_open)
        else:
            reasons.append("observed_range_spread_unavailable")
    gap = None
    if decision is not None and next_open_value is not None and decision != 0:
        gap = float(next_open_value / decision - 1.0)

    status = "available" if not reasons else "unavailable"
    valid_next_session = valid_next_session and not any(
        reason in reasons
        for reason in (
            "execution_not_next_canonical_market_session",
            "observed_business_date_unavailable",
            "canonical_market_session_unavailable",
        )
    )
    return {
        "evidence_status": status,
        "evidence_reason": ";".join(dict.fromkeys(reasons)) or CANONICAL_OPERATIONAL_EVIDENCE_REASON,
        "instrument_id": identity or None,
        "strategy": strategy,
        "signal_date": signal_date,
        "signal_timestamp": None if signal_ts is None else signal_ts.isoformat(),
        "execution_date": execution_date,
        "execution_timestamp": None if execution_ts is None else execution_ts.isoformat(),
        "decision_price": decision,
        "decision_price_basis": decision_price_basis if decision is not None else None,
        "next_open_reference_price": next_open_value,
        "next_open_reference_basis": next_open_reference_basis if next_open_value is not None else None,
        "next_period_reference_price": next_close,
        "next_period_reference_basis": next_period_reference_basis if next_close is not None else None,
        "price_provenance": price_provenance if price_provenance else None,
        "decision_price_source_identity": decision_price_source_identity,
        "next_open_source_identity": next_open_source_identity,
        "next_period_source_identity": next_period_source_identity,
        "close_to_next_open_gap": gap,
        "observed_range_spread_proxy": observed_spread,
        "spread_proxy": observed_spread,
        "cost_spread_assumption_bps": cost_spread,
        "cost_spread_assumption_source": str(cost_spread_assumption_source).strip() if cost_spread_assumption_source else None,
        "estimated_cost_bps": estimated_cost,
        "estimated_cost_bps_source": str(estimated_cost_bps_source).strip() if estimated_cost_bps_source else None,
        "arrival_price_assumption": "next_adjusted_close" if next_close is not None else "unavailable",
        "execution_delay_sessions": 1 if status == "available" and valid_next_session else None,
        "same_bar_execution_avoided": bool(
            signal_ts is not None
            and execution_ts is not None
            and execution_ts > signal_ts
            and canonical_signal_day is not None
            and canonical_execution_day is not None
            and canonical_execution_day > canonical_signal_day
            and valid_next_session
        ),
        "session_state": None,
        "auction_state": None,
        "expiry_state": None,
        "order_lifecycle": None,
        "fill_source": "simulated_backtest",
        "paper_fill_source": None,
        "reconciled_fill_source": None,
        "execution_allowed": False,
        **calendar_fields,
    }


def _holdings_from_weights(weights: pd.Series, price_row: pd.Series, portfolio_value: float, as_of: date) -> pd.DataFrame:
    rows = []
    for etf_id, weight in weights.items():
        price = float(price_row.get(etf_id, 0) or 0)
        value = portfolio_value * float(weight)
        rows.append(
            {
                "as_of_date": as_of,
                "etf_id": etf_id,
                "units": value / price if price else 0.0,
                "market_price": price,
                "market_value_eur": value,
                "current_weight": float(weight),
                "average_cost_eur": price,
                "unrealised_gain_eur": 0.0,
                "unrealised_gain_pct": 0.0,
                "source": "backtest",
            }
        )
    return pd.DataFrame(rows)


def run_backtest(
    config: AppConfig,
    prices: pd.DataFrame,
    *,
    fundamentals: pd.DataFrame | None = None,
    initial_value_eur: float = 10000,
    rebalance_frequency_days: int = 21,
    transaction_cost_bps: float | None = None,
    structure_document_registry: object = None,
    structure_report_records: object = None,
    structure_supplemental_rows: object = None,
    structure_holdings: object = None,
    benchmark_data_id: str | None = None,
    benchmark_reference: Mapping[str, object] | None = None,
    reference_identity: Mapping[str, object] | None = None,
    benchmark_registry: CanonicalBenchmarkRegistry | None = None,
    calendar_identity_resolver: Callable[[str, object], Mapping[str, object] | None] | None = None,
) -> BacktestReport:
    validate_execution_disabled(benchmark_reference or unavailable_reference_projection())
    validate_execution_disabled(reference_identity or {})
    calculation_window = _declared_calculation_window(reference_identity)
    if calculation_window is not None:
        if not isinstance(reference_identity, Mapping):
            raise BacktestDataUnavailableError("invalid_reference_window: calculation window is missing")
        analysis = reference_identity.get("analysis")
        if not isinstance(analysis, Mapping):
            raise BacktestDataUnavailableError("invalid_reference_window: calculation window is missing")
        prices = clip_to_decision_window(
            prices,
            start_date=analysis.get("start_date"),
            end_date=analysis.get("end_date"),
            decision_time=analysis.get("decision_time"),
        )
        if prices.empty:
            raise BacktestDataUnavailableError("invalid_reference_window: no prices are available at the decision cutoff")
    pivot_raw = _price_pivot(prices)
    if calculation_window is not None:
        start, end = calculation_window
        pivot_raw = pivot_raw.loc[(pivot_raw.index >= start) & (pivot_raw.index <= end)]
    columns = [column for column in config.universe.enabled_ids if column in pivot_raw.columns]
    if not columns:
        raise BacktestDataUnavailableError("not_enough_data: no configured instruments have adjusted-close history")
    selected_raw = pivot_raw.reindex(columns=columns)
    complete_mask = selected_raw.notna().all(axis=1)
    missing_observation_rows = int((~complete_mask).sum())
    pivot = selected_raw.loc[complete_mask].copy()
    if len(pivot) < 260:
        raise BacktestDataUnavailableError(
            "not_enough_data: backtest requires at least 260 complete adjusted-price sessions; "
            f"available={len(pivot)}, missing_observation_rows={missing_observation_rows}"
        )
    adjusted_open_pivot = _corporate_action_adjusted_pivot(prices, "open", columns)
    adjusted_high_pivot = _corporate_action_adjusted_pivot(prices, "high", columns)
    adjusted_low_pivot = _corporate_action_adjusted_pivot(prices, "low", columns)
    calendar_service = MarketCalendarService.from_correction_ledger(
        CONFIG_DIR / "market_calendar_corrections.yaml"
    )
    canonical_benchmark_id = _validated_benchmark_data_id(
        benchmark_data_id,
        benchmark_reference,
        reference_identity,
        benchmark_registry,
        pivot.columns,
    )
    canonical_reference = dict(benchmark_reference or unavailable_reference_projection())
    metadata: dict[str, object] = {
        "strategy": "signal_strategy",
        "benchmark_strategy": "canonical_price_series" if canonical_benchmark_id else "unavailable",
        "benchmark_data_id": canonical_benchmark_id,
        "benchmark_reference": canonical_reference,
        "reference_identity": dict(reference_identity or {
            "schema": "benchmark-reference-cache.v1",
            "status": "unavailable",
            "registry_hash": canonical_reference.get("registry_hash", "unavailable"),
            "benchmark_data_id": canonical_benchmark_id,
            "selected_records": canonical_reference.get("selected_records", {}),
            "calculation_schema": "canonical-benchmark-cash.v1",
            "execution_allowed": False,
        }),
        "price_field": "adjusted_close",
        "raw_price_rows": int(len(selected_raw)),
        "complete_price_rows": int(len(pivot)),
        "missing_observation_rows": missing_observation_rows,
        "data_status": "warning" if missing_observation_rows else "clean",
        "forward_fill_used": False,
        "lookahead_protection": "history_truncated_at_signal_date",
        "execution_delay_sessions": 1,
        "same_bar_execution_avoided": True,
        "cost_model_id": COST_MODEL_ID,
        "cost_model_execution_allowed": False,
        "cost_model_mode": "consistent_local_research_estimates",
        "date_range_start": pivot.index.min().date(),
        "date_range_end": pivot.index.max().date(),
        "not_enough_data_policy": "fail_closed",
        "quality_momentum_strategy_version": QUALITY_MOMENTUM_VERSION,
        "quality_momentum_evidence": "pending",
        "input_checksum": backtest_input_checksum(
            config,
            prices,
            fundamentals,
            structure_document_registry=structure_document_registry,
            structure_report_records=structure_report_records,
            structure_supplemental_rows=structure_supplemental_rows,
            structure_holdings=structure_holdings,
        ),
    }
    if missing_observation_rows:
        metadata["data_warning"] = "Incomplete adjusted-price rows were excluded; no forward-fill was applied."
    log_returns = np.log(pivot / pivot.shift(1)).fillna(0.0)
    start_index = 220
    rebalance_indexes = set(range(start_index, len(pivot), rebalance_frequency_days))
    strategies = [
        "buy_and_hold",
        "equal_weight",
        "momentum_only",
        "trend_only",
        "quality_only",
        "quality_momentum",
        "signal_strategy",
    ]
    weights = {name: target_weights(config, columns) for name in strategies}
    if "equal_weight" in weights:
        weights["equal_weight"] = equal_weights(columns)
    weights["quality_only"] = pd.Series(0.0, index=columns, dtype=float)
    weights["quality_momentum"] = pd.Series(0.0, index=columns, dtype=float)
    equity = {name: [initial_value_eur] for name in strategies}
    index_values = [pivot.index[start_index]]
    turnover = {name: 0.0 for name in strategies}
    cost_drag = {name: 0.0 for name in strategies}
    pending_weights: dict[str, pd.Series] = {}
    pending_costs: dict[str, float] = {}
    pending_execution_date: pd.Timestamp | None = None
    trade_rows: list[dict[str, object]] = []
    operational_evidence_rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    quality_evidence_rows: list[dict[str, object]] = []

    for i in range(start_index + 1, len(pivot)):
        dt = pivot.index[i]
        execution_costs: dict[str, float] = {}
        if pending_execution_date is not None and dt == pending_execution_date:
            execution_costs = pending_costs

        day_return = log_returns.loc[dt, columns]
        for name in strategies:
            previous_equity = equity[name][-1]
            portfolio_return = float((weights[name].reindex(columns).fillna(0) * day_return).sum())
            new_equity = previous_equity * np.exp(portfolio_return)
            if execution_costs.get(name, 0.0):
                new_equity = max(new_equity - execution_costs[name], 0.0)
            equity[name].append(max(new_equity, 0.0))
        index_values.append(dt)

        # Orders are filled at the next session's adjusted close.  The
        # signal-day return therefore remains attributed to the old weights;
        # the new weights affect the following session only.
        if pending_execution_date is not None and dt == pending_execution_date:
            for name, new_weight in pending_weights.items():
                weights[name] = new_weight.reindex(columns).fillna(0)
            pending_weights = {}
            pending_costs = {}
            pending_execution_date = None

        if i in rebalance_indexes and i + 1 < len(pivot):
            history = pivot.iloc[: i + 1]
            new_weights = {
                "buy_and_hold": weights["buy_and_hold"],
                "equal_weight": equal_weights(columns),
                "momentum_only": momentum_weights(history, columns),
                "trend_only": trend_weights(config, history, columns),
                "quality_only": pd.Series(0.0, index=columns, dtype=float),
                "quality_momentum": pd.Series(0.0, index=columns, dtype=float),
                "signal_strategy": weights["signal_strategy"],
            }
            quality_prices = history.rename_axis("date").reset_index().melt(
                id_vars=["date"], var_name="etf_id", value_name="adjusted_close"
            )
            sector_map = {
                item.id: str(item.sector or "")
                for item in config.universe.etfs
                if item.id in columns and item.sector
            }
            quality_evidence = build_quality_momentum_frame(
                quality_prices,
                fundamentals if fundamentals is not None else pd.DataFrame(),
                as_of_date=dt.date(),
                sector_by_instrument=sector_map,
            )
            quality_evidence_rows.extend(quality_evidence.to_dict("records"))
            new_weights["quality_only"] = quality_momentum_weights(quality_evidence, columns, mode="quality")
            new_weights["quality_momentum"] = quality_momentum_weights(quality_evidence, columns, mode="quality_momentum")
            if not quality_evidence.empty and (quality_evidence["status"] == "available").any():
                metadata["quality_momentum_evidence"] = "available"
            elif metadata.get("quality_momentum_evidence") != "available":
                metadata["quality_momentum_evidence"] = "unavailable"
            # The signal strategy uses the same live signal pipeline, then tilts around targets.
            truncated_prices = prices[pd.to_datetime(prices["date"]) <= dt].copy()
            if calculation_window is not None:
                truncated_dates = pd.to_datetime(truncated_prices["date"])
                truncated_prices = truncated_prices.loc[
                    (truncated_dates >= calculation_window[0])
                    & (truncated_dates <= calculation_window[1])
                ].copy()
            features = compute_features(truncated_prices, benchmark_etf_id=canonical_benchmark_id)
            if canonical_benchmark_id is None:
                features.loc[:, ["relative_strength_60d", "relative_strength_120d"]] = np.nan
            latest = latest_features(features, as_of_date=dt.date())
            holdings = _holdings_from_weights(weights["signal_strategy"], pivot.iloc[i], equity["signal_strategy"][-1], dt.date())
            report = validate_prices(truncated_prices, as_of_date=dt.date(), min_history_days=180)
            if report.status == "Blocked":
                report = DataQualityReport(as_of_date=dt.date(), issues=[issue for issue in report.issues if issue.code != "insufficient_history"])
            structure_caps = structure_confidence_caps(
                columns,
                document_registry=structure_document_registry,
                report_records=structure_report_records,
                supplemental_rows=structure_supplemental_rows,
                holdings=structure_holdings,
                decision_time=dt.date(),
            )
            signals = generate_signals(
                config,
                latest,
                holdings,
                report,
                as_of_date=dt.date(),
                run_id=f"backtest_{dt:%Y%m%d}",
                structure_confidence_caps=structure_caps,
            )
            signal_weight = weights["signal_strategy"].copy()
            target = target_weights(config, columns)
            for signal in signals:
                canonical = signal.canonical_score
                structural_identity = structure_caps.provenance.get(signal.etf_id, {})
                signal_rows.append(
                    {
                        "date": dt.date(),
                        "signal_timestamp": pd.Timestamp(dt).isoformat(),
                        "etf_id": signal.etf_id,
                        "action": signal.action,
                        "score": signal.total_score,
                        "canonical_attractiveness_10": canonical.attractiveness_10 if canonical else None,
                        "canonical_expected_return_10": canonical.expected_return_10 if canonical else None,
                        "canonical_risk_implementation_10": canonical.risk_implementation_10 if canonical else None,
                        "canonical_evidence_confidence_10": canonical.evidence_confidence_10 if canonical else None,
                        "canonical_coverage": canonical.coverage if canonical else 0.0,
                        "formula_version": canonical.formula_version if canonical else "unavailable",
                        "formula_checksum": canonical.formula_checksum if canonical else "unavailable",
                        "source_vintage_hash": canonical.source_vintage_hash if canonical else "unavailable",
                        "structural_confidence_cap": float(structure_caps.get(signal.etf_id, 0.0)),
                        "structural_provenance_hash": str(
                            structural_identity.get("structure_provenance_hash", "unavailable")
                        ),
                    }
                )
                if signal.etf_id not in signal_weight:
                    continue
                if signal.action in {"buy", "add", "add_candidate"}:
                    signal_weight[signal.etf_id] = min(target[signal.etf_id] * 1.20, signal_weight[signal.etf_id] + 0.02)
                elif signal.action in {"trim", "trim_candidate"}:
                    signal_weight[signal.etf_id] = max(0.0, signal_weight[signal.etf_id] - 0.02)
                elif signal.action == "sell":
                    signal_weight[signal.etf_id] = 0.0
            total_signal = signal_weight.sum()
            new_weights["signal_strategy"] = signal_weight / total_signal if total_signal > 0 else signal_weight

            execution_dt = pivot.index[i + 1]
            pending_execution_date = execution_dt
            pending_weights = {}
            pending_costs = {}
            for name, new_weight in new_weights.items():
                diff = (new_weight.reindex(columns).fillna(0) - weights[name].reindex(columns).fillna(0)).abs()
                step_turnover = float(diff.sum())
                if transaction_cost_bps is None:
                    portfolio_cost = estimate_rebalance_cost(config, equity[name][-1], diff.to_dict())
                    step_cost = portfolio_cost.total_cost_eur
                    step_cost_bps = portfolio_cost.weighted_cost_bps
                    step_cost_quality = ", ".join(sorted({item.data_quality for item in portfolio_cost.estimates})) or "no_trade"
                    step_capacity_eur = portfolio_cost.capacity_eur
                    instrument_costs: dict[str, list[CostEstimate]] = {}
                    for item in portfolio_cost.estimates:
                        instrument_costs.setdefault(item.instrument_id, []).append(item)
                else:
                    step_cost = equity[name][-1] * step_turnover * max(0.0, transaction_cost_bps) / 10_000
                    step_cost_bps = max(0.0, transaction_cost_bps)
                    step_cost_quality = "legacy_explicit_override"
                    step_capacity_eur = None
                    instrument_costs = {}
                turnover[name] += step_turnover
                cost_drag[name] += step_cost
                pending_weights[name] = new_weight.reindex(columns).fillna(0)
                pending_costs[name] = step_cost
                if step_turnover > 0:
                    empty_reference = pd.Series(index=columns, dtype=float)
                    execution_evidence = _execution_evidence(
                        current_prices=pivot.iloc[i].reindex(columns),
                        next_adjusted_close=pivot.iloc[i + 1].reindex(columns),
                        next_open=adjusted_open_pivot.loc[execution_dt].reindex(columns)
                        if execution_dt in adjusted_open_pivot.index
                        else empty_reference,
                        next_high=adjusted_high_pivot.loc[execution_dt].reindex(columns)
                        if execution_dt in adjusted_high_pivot.index
                        else empty_reference,
                        next_low=adjusted_low_pivot.loc[execution_dt].reindex(columns)
                        if execution_dt in adjusted_low_pivot.index
                        else empty_reference,
                        changed_weights=diff,
                        signal_timestamp=pd.Timestamp(dt).isoformat(),
                        execution_timestamp=pd.Timestamp(execution_dt).isoformat(),
                        cost_spread_assumption_bps=None,
                        cost_spread_assumption_source=None,
                        estimated_cost_bps=step_cost_bps,
                        estimated_cost_bps_source=(
                            "PortfolioCostEstimate.weighted_cost_bps"
                            if transaction_cost_bps is None
                            else "explicit_transaction_cost_bps"
                        ),
                    )
                    for instrument_id in diff.index[diff > 0]:
                        instrument_cost_matches = instrument_costs.get(str(instrument_id), [])
                        instrument_cost = instrument_cost_matches[0] if len(instrument_cost_matches) == 1 else None
                        initial_calendar_identity = (
                            calendar_identity_resolver(str(instrument_id), dt)
                            if calendar_identity_resolver is not None
                            else None
                        )
                        if initial_calendar_identity is None:
                            initial_calendar_identity = _calendar_identity_from_price_rows(
                                prices, instrument_id
                            )
                        signal_close = _canonical_session_close_timestamp(
                            initial_calendar_identity,
                            str(instrument_id),
                            dt,
                            service=calendar_service,
                            knowledge_cutoff=dt,
                        )
                        calendar_identity = initial_calendar_identity
                        if calendar_identity_resolver is not None and signal_close is not None:
                            calendar_identity = calendar_identity_resolver(
                                str(instrument_id), signal_close
                            )
                            signal_close = _canonical_session_close_timestamp(
                                calendar_identity,
                                str(instrument_id),
                                dt,
                                service=calendar_service,
                                knowledge_cutoff=signal_close,
                            )
                        execution_close = _canonical_session_close_timestamp(
                            calendar_identity,
                            str(instrument_id),
                            execution_dt,
                            service=calendar_service,
                            knowledge_cutoff=signal_close or dt,
                        )
                        operational_evidence_rows.append(
                            _instrument_operational_evidence(
                                instrument_id=instrument_id,
                                strategy=name,
                                signal_timestamp=(signal_close or pd.Timestamp(dt)).isoformat(),
                                execution_timestamp=(execution_close or pd.Timestamp(execution_dt)).isoformat(),
                                signal_date=dt.date(),
                                execution_date=execution_dt.date(),
                                decision_price=pivot.iloc[i].get(instrument_id),
                                next_open=(
                                    adjusted_open_pivot.loc[execution_dt].get(instrument_id)
                                    if execution_dt in adjusted_open_pivot.index
                                    else None
                                ),
                                next_period_close=pivot.iloc[i + 1].get(instrument_id),
                                high=(
                                    adjusted_high_pivot.loc[execution_dt].get(instrument_id)
                                    if execution_dt in adjusted_high_pivot.index
                                    else None
                                ),
                                low=(
                                    adjusted_low_pivot.loc[execution_dt].get(instrument_id)
                                    if execution_dt in adjusted_low_pivot.index
                                    else None
                                ),
                                open_price=(
                                    adjusted_open_pivot.loc[execution_dt].get(instrument_id)
                                    if execution_dt in adjusted_open_pivot.index
                                    else None
                                ),
                                cost_spread_assumption_bps=(
                                    instrument_cost.spread_bps
                                    if instrument_cost is not None
                                    else None
                                ),
                                cost_spread_assumption_source=(
                                    f"{instrument_cost.model_id}:CostEstimate.spread_bps"
                                    if instrument_cost is not None
                                    else None
                                ),
                                estimated_cost_bps=(
                                    instrument_cost.total_cost_bps
                                    if instrument_cost is not None
                                    else step_cost_bps
                                ),
                                estimated_cost_bps_source=(
                                    f"{instrument_cost.model_id}:CostEstimate.total_cost_bps"
                                    if instrument_cost is not None
                                    else (
                                        "PortfolioCostEstimate.weighted_cost_bps"
                                        if transaction_cost_bps is None
                                        else "explicit_transaction_cost_bps"
                                    )
                                ),
                                calendar_identity=calendar_identity,
                                calendar_service=calendar_service,
                                decision_price_source_identity=_price_source_identity(prices, instrument_id, dt),
                                next_open_source_identity=_price_source_identity(prices, instrument_id, execution_dt),
                                next_period_source_identity=_price_source_identity(prices, instrument_id, pivot.index[i + 1]),
                            )
                        )
                    trade_rows.append(
                        {
                            "date": execution_dt.date(),
                            "signal_date": dt.date(),
                            "execution_date": execution_dt.date(),
                            "strategy": name,
                            "turnover": step_turnover,
                            "cost_eur": step_cost,
                            "estimated_cost_bps": step_cost_bps,
                            "cost_model_id": COST_MODEL_ID if transaction_cost_bps is None else "explicit_transaction_cost_bps",
                            "cost_data_quality": step_cost_quality,
                            "capacity_eur": step_capacity_eur,
                            **execution_evidence,
                        }
                    )

    calculation_equity_curves = pd.DataFrame({name: values for name, values in equity.items()}, index=index_values)
    diagnostic_index = selected_raw.loc[
        calculation_equity_curves.index.min() : calculation_equity_curves.index.max()
    ].index
    equity_curves = calculation_equity_curves.reindex(diagnostic_index)
    benchmark = (
        pivot[canonical_benchmark_id].reindex(equity_curves.index)
        if canonical_benchmark_id is not None
        else None
    )
    pbo_probability = _pbo_probability_proxy(equity_curves, strategies)
    parameter_sensitivity = _parameter_sensitivity_status(equity_curves, trade_rows, strategies)
    result_rows = []
    years = max((len(equity_curves) - 1) / TRADING_DAYS_PER_YEAR, 1e-9)
    rebalance_count = sum(1 for index in rebalance_indexes if start_index < index < len(pivot))
    metadata["walk_forward_periods"] = rebalance_count
    metadata["strategies"] = strategies
    metadata["same_bar_execution_count"] = 0
    metadata["quality_momentum_evidence_rows"] = len(quality_evidence_rows)
    metadata["quality_momentum_evidence_available_rows"] = sum(
        row.get("status") == "available" for row in quality_evidence_rows
    )
    quality_evidence_frame = pd.DataFrame(quality_evidence_rows, columns=FRAME_COLUMNS)
    metadata["quality_momentum_evidence_checksum"] = quality_momentum_evidence_checksum(quality_evidence_frame)
    metadata["operational_evidence_rows"] = operational_evidence_rows
    for name in strategies:
        metrics = performance_metrics(equity_curves[name], benchmark=benchmark, turnover=turnover[name], cost_drag=cost_drag[name])
        metrics["benchmark_id"] = canonical_benchmark_id
        metrics["benchmark_status"] = "available" if canonical_benchmark_id else "unavailable"
        if canonical_benchmark_id is None:
            metrics["information_ratio"] = None
        strategy_trades = [row for row in trade_rows if row["strategy"] == name]
        returns_252d = equity_curves[name].pct_change(252, fill_method=None)
        metrics["n_walk_forward_periods"] = rebalance_count
        metrics["train_periods"] = start_index
        metrics["validation_periods"] = 0
        metrics["test_periods"] = max(0, len(pivot) - start_index)
        metrics["trade_count"] = len(strategy_trades)
        metrics["average_trade_eur"] = float(initial_value_eur * (sum(float(row["turnover"]) for row in strategy_trades) / max(len(strategy_trades), 1)))
        metrics["median_holding_period_days"] = float(rebalance_frequency_days)
        metrics["turnover_annualised"] = float(turnover[name] / years)
        metrics["worst_12m_return"] = float(returns_252d.min()) if returns_252d.notna().any() else 0.0
        strategy_returns = _log_equity_returns(equity_curves[name])
        metrics["probabilistic_sharpe"] = _probabilistic_sharpe(strategy_returns)
        metrics["deflated_sharpe"] = _deflated_sharpe(metrics["sharpe"], len(strategies), len(strategy_returns))
        metrics["pbo_probability_backtest_overfitting"] = pbo_probability
        metrics["parameter_sensitivity_status"] = parameter_sensitivity.get(name, "not_available")
        metrics["overfitting_warning"] = _overfitting_warning(
            pbo_probability,
            parameter_sensitivity.get(name, "not_available"),
        )
        metrics["data_quality_status"] = metadata["data_status"]
        metrics["benchmark_strategy"] = metadata["benchmark_strategy"]
        metrics["backtest_quality"] = _backtest_quality_label(
            pbo_probability,
            parameter_sensitivity.get(name, "not_available"),
            rebalance_count,
        )
        metrics["strategy_name"] = name
        metrics["start_date"] = equity_curves.index.min().date()
        metrics["end_date"] = equity_curves.index.max().date()
        metrics["final_value_eur"] = float(equity_curves[name].iloc[-1])
        result_rows.append(metrics)
    results = pd.DataFrame(result_rows)
    no_ai = results.loc[results["strategy_name"] == "momentum_only", "calmar"].iloc[0]
    signal_calmar = results.loc[results["strategy_name"] == "signal_strategy", "calmar"].iloc[0]
    ai_added_value = bool(signal_calmar > no_ai * 1.03)
    return BacktestReport(
        results=results,
        equity_curves=equity_curves,
        trade_log=pd.DataFrame(trade_rows),
        signal_log=pd.DataFrame(signal_rows),
        ai_added_value=ai_added_value,
        quality_label=_overall_quality_label(results),
        quality_notes=[
            "Uses adjusted-close sample/local series without silent forward-fill.",
            "Advanced diagnostics are deterministic local estimates: probabilistic Sharpe, deflated Sharpe and a CSCV-style PBO proxy.",
            "Parameter sensitivity status reflects period stability plus a 2x transaction-cost stress on realised trade logs.",
            "Signals are evaluated only with history available at the signal date and executed on the next complete session.",
            "Next-open and spread evidence is unavailable when the source panel does not provide OHLC fields.",
        ],
        metadata=metadata,
        quality_momentum_evidence=quality_evidence_frame,
    )


def _log_equity_returns(equity: pd.Series) -> pd.Series:
    observed = pd.to_numeric(equity, errors="coerce")
    return np.log(observed / observed.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()


def _probabilistic_sharpe(returns: pd.Series, *, benchmark_sharpe: float = 0.0) -> float:
    returns = returns.dropna()
    if len(returns) < 4 or float(returns.std()) <= 0:
        return 0.5
    sharpe_daily = float(returns.mean() / returns.std())
    benchmark_daily = benchmark_sharpe / np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(returns.skew()) if len(returns) > 2 else 0.0
    kurtosis = float(returns.kurt()) + 3.0 if len(returns) > 3 else 3.0
    denominator = np.sqrt(max(1.0 - skew * sharpe_daily + ((kurtosis - 1.0) / 4.0) * sharpe_daily**2, 1e-9))
    z_score = (sharpe_daily - benchmark_daily) * np.sqrt(len(returns) - 1) / denominator
    return float(np.clip(NormalDist().cdf(z_score), 0.0, 1.0))


def _deflated_sharpe(annualised_sharpe: float, n_trials: int, n_observations: int) -> float:
    if n_observations < 4:
        return 0.0
    trials = max(int(n_trials), 1)
    # Conservative expected best noise Sharpe across tested strategies.
    trial_probability = 1.0 - 1.0 / max(trials + 1, 2)
    expected_noise_daily = NormalDist().inv_cdf(trial_probability) / np.sqrt(max(n_observations - 1, 1))
    expected_noise_annual = expected_noise_daily * np.sqrt(TRADING_DAYS_PER_YEAR)
    return float(annualised_sharpe - expected_noise_annual)


def _pbo_probability_proxy(equity_curves: pd.DataFrame, strategies: list[str], *, folds: int = 4) -> float:
    returns = np.log(equity_curves[strategies] / equity_curves[strategies].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < folds * 5:
        return 1.0
    fold_indexes = np.array_split(np.arange(len(returns)), folds)
    failures = 0
    total = 0
    for in_sample_folds in combinations(range(folds), folds // 2):
        in_index = np.concatenate([fold_indexes[index] for index in in_sample_folds])
        out_index = np.concatenate([fold_indexes[index] for index in range(folds) if index not in in_sample_folds])
        in_scores = _fold_sharpe(returns.iloc[in_index])
        out_scores = _fold_sharpe(returns.iloc[out_index])
        if in_scores.empty or out_scores.empty:
            continue
        selected = str(in_scores.idxmax())
        out_rank = out_scores.rank(ascending=False, method="min").get(selected)
        if out_rank is None:
            continue
        total += 1
        if float(out_rank) > (len(strategies) + 1) / 2:
            failures += 1
    return float(failures / total) if total else 1.0


def _parameter_sensitivity_status(equity_curves: pd.DataFrame, trade_rows: list[dict[str, object]], strategies: list[str]) -> dict[str, str]:
    returns = np.log(equity_curves[strategies] / equity_curves[strategies].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 40:
        return {strategy: "insufficient_history" for strategy in strategies}
    fold_indexes = np.array_split(np.arange(len(returns)), 4)
    statuses: dict[str, str] = {}
    for strategy in strategies:
        fold_scores = [_single_series_sharpe(returns[strategy].iloc[index]) for index in fold_indexes if len(index) > 1]
        positive_folds = sum(1 for score in fold_scores if score > 0)
        cost_drag = sum(float(row["cost_eur"]) for row in trade_rows if row["strategy"] == strategy)
        final_value = float(equity_curves[strategy].iloc[-1])
        doubled_cost_final = final_value - cost_drag
        start_value = float(equity_curves[strategy].iloc[0])
        survives_cost_stress = doubled_cost_final > start_value
        if positive_folds >= 3 and survives_cost_stress:
            statuses[strategy] = "stable"
        elif positive_folds >= 2 or survives_cost_stress:
            statuses[strategy] = "mixed"
        else:
            statuses[strategy] = "fragile"
    return statuses


def _overfitting_warning(pbo_probability: float, parameter_sensitivity_status: str) -> str:
    if pbo_probability >= 0.66:
        return "high_overfitting_risk: selected results often fail out-of-sample rank checks"
    if pbo_probability >= 0.33 or parameter_sensitivity_status in {"fragile", "mixed"}:
        return "review_required: performance is sensitive to folds or transaction-cost stress"
    return "no_material_warning_in_local_proxy: out-of-sample evidence remains limited"


def _fold_sharpe(returns: pd.DataFrame) -> pd.Series:
    scores = {}
    for column in returns.columns:
        scores[column] = _single_series_sharpe(returns[column])
    return pd.Series(scores)


def _single_series_sharpe(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    std = float(clean.std())
    if len(clean) < 2 or std <= 0:
        return 0.0
    return float((clean.mean() / std) * np.sqrt(TRADING_DAYS_PER_YEAR))


def _backtest_quality_label(pbo_probability: float, parameter_sensitivity_status: str, rebalance_count: int) -> str:
    if rebalance_count < 3:
        return "low"
    if parameter_sensitivity_status == "stable" and pbo_probability <= 0.33:
        return "medium"
    if parameter_sensitivity_status in {"stable", "mixed"} and pbo_probability <= 0.66:
        return "medium"
    return "low"


def _overall_quality_label(results: pd.DataFrame) -> str:
    if results.empty or "backtest_quality" not in results:
        return "low"
    return "medium" if (results["backtest_quality"] == "medium").any() else "low"
