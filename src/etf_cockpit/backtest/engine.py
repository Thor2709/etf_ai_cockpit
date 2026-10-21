from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Callable, Iterator, Mapping
import functools
import hashlib
import json
import math
from itertools import combinations
from pathlib import Path
from statistics import NormalDist
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd
import yaml

from etf_cockpit.backtest.benchmarks import (
    assert_long_only,
    equal_weights,
    investable_comparator_summary,
    momentum_weights,
    target_weights,
    trend_weights,
)
from etf_cockpit.backtest.metrics import performance_metrics
from etf_cockpit.portfolio.benchmark_reference import (
    clip_to_decision_window,
    validate_benchmark_reference,
)
from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.core.values import finite_float_or_none
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.data.provenance import sha256_dataframe
from etf_cockpit.data.market_calendar import (
    ClockContext,
    ListingCalendarEvidence,
    MarketCalendarService,
    MarketClockError,
)
from etf_cockpit.data.etf_structure import structure_cap_scope, structure_confidence_caps, structure_input_checksum
from etf_cockpit.data.classification import classification_state_memo
from etf_cockpit.data.fx_data import EurRateBook, fx_cross_rate_memo, fx_rates_for_prices, major_currency
from etf_cockpit.features.feature_pipeline import (
    attach_eur_basis,
    compute_features,
    eur_basis_prices,
    latest_features,
)
from etf_cockpit.portfolio.costs import (
    COST_MODEL_ID,
    CostEstimate,
    average_daily_value_eur,
    estimate_rebalance_cost,
    fill_feasibility,
)
from etf_cockpit.portfolio.benchmark_reference_contract import (
    CanonicalBenchmarkRegistry,
    unavailable_reference_projection,
    validate_execution_disabled,
)
from etf_cockpit.signals.canonical_scoring import CanonicalScoreError, load_score_policy
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
        # Built once per rows list (callers ask once per instrument); each caller gets its own copy.
        cached = self.__dict__.get("_operational_evidence_cache")
        if cached is not None and cached[0] is rows and cached[1] == len(rows):
            return cached[2].copy()
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
        self.__dict__["_operational_evidence_cache"] = (rows, len(rows), frame.copy())
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


MIN_INSTRUMENT_HISTORY_SESSIONS = 260


def _exclude_late_listed_short_history(pivot: pd.DataFrame, columns: list[str]) -> tuple[list[str], tuple[str, ...]]:
    """Leave out instruments that started trading late and lack one year of sessions.

    Only late listings that are still trading at the window end are dropped.
    An instrument whose history stops early (a delisting) stays in, whether it
    started with the window or late, so the complete-session rule still fails
    closed instead of hiding a delisted loser (survivorship).
    """
    if not columns:
        return columns, ()
    observed = pivot[columns].notna()
    counts = observed.sum()
    first_seen = observed.idxmax()
    last_seen = observed.iloc[::-1].idxmax()
    window_start = first_seen.min()
    window_end = last_seen.max()
    short = [
        column
        for column in columns
        if int(counts[column]) < MIN_INSTRUMENT_HISTORY_SESSIONS
        and first_seen[column] > window_start
        and last_seen[column] >= window_end
    ]
    if len(short) == len(columns):
        return columns, ()
    kept = [column for column in columns if column not in short]
    return kept, tuple(short)


COST_REGIME_MODELLED = "modelled_default"
COST_REGIME_LEGACY = "legacy_flat_override"
COST_REGIME_STRESS = "conservative_stress"
_BACKTEST_DEFAULT_PATH = CONFIG_DIR / "backtest_default.yaml"
_FLAT_COST_NOT_EVIDENCE = (
    "A flat basis-point override is a legacy assumption, not execution evidence, and never qualifies a backtest."
)
SURVIVORSHIP_CONDITIONAL = "conditional_historical_simulation"
SURVIVORSHIP_FULL = "full_history_simulation"
SURVIVORSHIP_NO_PIT_REASON = "universe_is_current_listing_set_no_point_in_time_membership_evidence"
_PIT_MEMBERSHIP_STATUS = "point_in_time_verified"
_REMAINDER_POLICY = "cancelled_at_session_end"


@dataclass(frozen=True)
class CostRegimeReport:
    """The same strategy run under the modelled default, the legacy flat override and a stress."""

    reports: dict[str, BacktestReport]
    comparison: pd.DataFrame
    qualifying_regime: str = COST_REGIME_MODELLED
    execution_allowed: bool = False


def _point_in_time_membership_verified(evidence: Mapping[str, object] | None) -> bool:
    """Explicit point-in-time membership/delisting evidence: a verified status AND a named source."""

    return (
        isinstance(evidence, Mapping)
        and str(evidence.get("status") or "").strip() == _PIT_MEMBERSHIP_STATUS
        and bool(str(evidence.get("source_id") or "").strip())
    )


def _cost_model_identity(config: AppConfig) -> str:
    """The configured cost model version (the id the estimator itself reports), never a stale constant."""

    return str(getattr(config.costs.cost_model, "model_version", COST_MODEL_ID) or COST_MODEL_ID)


def ai_added_value_vs_baseline(signal_calmar: object, baseline_calmar: object) -> bool:
    """Signal beats the baseline by a 3 percent margin of the baseline's magnitude (sign-safe for negative Calmar)."""

    signal = finite_float_or_none(signal_calmar)
    baseline = finite_float_or_none(baseline_calmar)
    if signal is None or baseline is None:
        return False
    return signal > baseline + 0.03 * abs(baseline)


def _latest_feature_value(latest_by_id: pd.DataFrame, etf_id: object, column: str) -> float | None:
    """The instrument's latest feature value, or None when the feature is unavailable (never a zero)."""

    if latest_by_id.empty or column not in latest_by_id.columns or str(etf_id) not in latest_by_id.index:
        return None
    return finite_float_or_none(latest_by_id.at[str(etf_id), column])


def _v3_formula_identity(signal_rows: list[dict[str, object]]) -> dict[str, object]:
    """Repository score-engine-v3 formula identifier vs the formula versions the signals actually carried."""

    try:
        expected = load_score_policy("ETF").formula_version
    except (CanonicalScoreError, OSError):
        expected = ""
    observed = sorted(
        {
            str(row.get("formula_version") or "").strip()
            for row in signal_rows
            if str(row.get("formula_version") or "").strip() not in {"", "unavailable"}
        }
    )
    return {"expected": expected, "observed": observed}


def _fx_known_by(prices: pd.DataFrame, reference_identity: Mapping[str, object] | None) -> object:
    """FX knowledge cut-off for the backtest: the declared decision time, else the end of the last price day."""

    analysis = reference_identity.get("analysis") if isinstance(reference_identity, Mapping) else None
    declared = analysis.get("decision_time") if isinstance(analysis, Mapping) else None
    if declared:
        return declared
    dates = pd.to_datetime(prices["date"], errors="coerce").dropna() if "date" in prices.columns else pd.Series(dtype="datetime64[ns]")
    if dates.empty:
        return None
    return (pd.Timestamp(dates.max()).normalize() + pd.Timedelta(days=1)).tz_localize("UTC").to_pydatetime()


def _fx_rate_pivot(
    index: pd.DatetimeIndex,
    columns: list[str],
    currency_by_id: Mapping[str, str],
    fx_rates: pd.DataFrame | None,
    known_by: object,
) -> pd.DataFrame:
    """EUR per unit of listing currency by session and instrument (canonical ``EurRateBook``).

    EUR listings are 1; a session without a usable point-in-time rate stays NaN
    (fx_unavailable), never a defaulted 1.
    """

    rates = pd.DataFrame(np.nan, index=index, columns=columns, dtype=float)
    sessions = [stamp.date() for stamp in index]
    book: EurRateBook | None = None
    by_currency: dict[str, np.ndarray] = {}
    for column in columns:
        currency = major_currency(currency_by_id.get(column, "EUR"))
        if currency is None:
            continue
        if currency == "EUR":
            rates[column] = 1.0
            continue
        if currency not in by_currency:
            if book is None:
                book = EurRateBook(fx_rates, known_by=known_by)
            by_currency[currency] = book.series(currency, sessions).rates.reindex(sessions).to_numpy(dtype=float)
        rates[column] = by_currency[currency]
    return rates


def load_backtest_realism_settings(path: Path | None = None) -> dict[str, object]:
    """Read the additive cost-realism flags of ``configs/backtest_default.yaml`` with safe defaults."""

    try:
        payload = yaml.safe_load((path or _BACKTEST_DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        payload = {}
    if not isinstance(payload, Mapping):
        payload = {}
    legacy = finite_float_or_none(payload.get("transaction_cost_bps"))
    stress = finite_float_or_none(payload.get("stress_cost_multiplier"))
    return {
        "legacy_override_bps": 13.0 if legacy is None or legacy < 0 else legacy,
        "stress_cost_multiplier": 2.0 if stress is None or stress < 1.0 else stress,
        "enforce_capacity": payload.get("enforce_capacity") is not False,
        "legacy_override_qualifies": False,
    }


def _apply_capacity_limits(
    current: pd.Series,
    target: pd.Series,
    *,
    notional_eur: float,
    volume_row: pd.Series,
    price_row: pd.Series,
    adv_by_instrument: Mapping[str, float],
    participation: float,
    manual_quote_ids: set[str],
    checked_ids: set[str],
) -> tuple[pd.Series, dict[str, object]]:
    """Clip the executed weights to what the participation cap lets fill.

    Fails closed: an order in an instrument whose liquidity cannot be verified
    (non-EUR listing without an FX series, missing volume or price, thin
    certificate without a manual quote) does not fill.  Unfilled sells never
    fund buys (buys are scaled down by the sell shortfall), so the executed book
    can never exceed 100 percent.  An unfilled remainder is cancelled at the
    session end (``remainder_policy``); ``days_to_fill`` reports how many
    sessions it would have needed.
    """

    executed = target.copy()
    statuses: dict[str, str] = {}
    unfilled_eur = 0.0
    max_days = 1
    sell_shortfall = 0.0
    fx_unavailable: list[str] = []
    if notional_eur <= 0.0:
        return current.copy(), {
            "unfilled_eur": 0.0,
            "statuses": statuses,
            "max_days_to_fill": 0,
            "fx_unavailable": [],
            "remainder_policy": _REMAINDER_POLICY,
        }
    for instrument_id, delta in (target - current).items():
        if abs(float(delta)) <= 1e-12:
            continue
        key = str(instrument_id)
        order_eur = notional_eur * abs(float(delta))
        if key not in checked_ids:
            fx_unavailable.append(key)
            status, fillable_eur, days = "no_fill_fx_unavailable", 0.0, None
        else:
            feasibility = fill_feasibility(
                order_eur,
                day_volume_shares=volume_row.get(instrument_id),
                price_eur=price_row.get(instrument_id),
                adv_eur=adv_by_instrument.get(key),
                participation_rate=participation,
                manual_quote_required=key in manual_quote_ids,
            )
            if feasibility.status == "full_fill":
                continue
            status, fillable_eur, days = feasibility.status, feasibility.fillable_eur, feasibility.days_to_fill
        statuses[key] = status
        unfilled_eur += order_eur - fillable_eur
        if days is not None:
            max_days = max(max_days, days)
        filled_weight = fillable_eur / notional_eur
        executed[instrument_id] = float(current[instrument_id]) + math.copysign(filled_weight, float(delta))
        if delta < 0:
            sell_shortfall += abs(float(delta)) - filled_weight
    if sell_shortfall > 0.0:
        buys = (executed - current).clip(lower=0.0)
        total_buy = float(buys.sum())
        if total_buy > 0.0:
            keep = max(0.0, total_buy - sell_shortfall) / total_buy
            executed = executed - buys * (1.0 - keep)
    return executed, {
        "unfilled_eur": unfilled_eur,
        "statuses": statuses,
        "max_days_to_fill": max_days,
        "fx_unavailable": fx_unavailable,
        "remainder_policy": _REMAINDER_POLICY,
    }


def _apply_minimum_trade_band(
    current: pd.Series,
    target: pd.Series,
    *,
    notional_eur: float,
    min_trade_eur: float,
) -> pd.Series:
    """Drop rebalance orders worth less than the configured minimum trade (a no-trade band).

    The same ``risks.portfolio_limits.min_trade_value_eur`` the signal pipeline and the portfolio sandbox
    enforce.  A position leaving the target set (target 0) is always sold in full, as the paper bots do.  A
    skipped order keeps the held weight; skipped sells never fund buys (the remaining buys are scaled down so
    the executed book cannot exceed the intended one), so the book can never exceed 100 percent.
    """

    if min_trade_eur <= 0.0 or notional_eur <= 0.0:
        return target
    delta = target - current
    full_exit = (target.abs() <= 1e-12) & (current.abs() > 1e-12)
    skipped = (delta.abs() > 1e-12) & (delta.abs() * notional_eur < min_trade_eur) & ~full_exit
    if not bool(skipped.any()):
        return target
    executed = target
    # Scaling the buys down to fund skipped sells can push a buy below the minimum: skip it too and rescale the
    # rest until no order changes.  Every pass skips at least one more order, so the loop is bounded by the size.
    for _ in range(len(target) + 1):
        executed = target.where(~skipped, current)
        surplus = float(executed.sum() - target.sum())
        if surplus > 1e-12:
            buys = (executed - current).clip(lower=0.0)
            total_buy = float(buys.sum())
            if total_buy > 0.0:
                keep = max(0.0, total_buy - surplus) / total_buy
                executed = executed - buys * (1.0 - keep)
        executed_delta = (executed - current).abs()
        too_small = (executed_delta > 1e-12) & (executed_delta * notional_eur < min_trade_eur) & ~full_exit & ~skipped
        if not bool(too_small.any()):
            break
        skipped = skipped | too_small
    return executed


def _drift_to_execution(signal_weights: pd.Series, execution_returns: pd.Series) -> tuple[pd.Series, float]:
    """Value-weighted holdings after the execution session's returns, and that session's portfolio return.

    Orders fill at the execution close, so the target is compared with this
    drifted book, never with the signal-day weights.
    """

    execution_return = float((signal_weights * execution_returns).sum())
    if execution_return <= -1.0:
        return signal_weights.copy(), execution_return
    return signal_weights * (1.0 + execution_returns) / (1.0 + execution_return), execution_return


def _adv_by_instrument(
    volume_pivot: pd.DataFrame, raw_close_pivot: pd.DataFrame, checked_ids: set[str], upto: int
) -> dict[str, float]:
    """20-session EUR ADV per instrument from history up to position ``upto`` (point-in-time)."""

    result: dict[str, float] = {}
    for column in sorted(checked_ids):
        value = average_daily_value_eur(volume_pivot[column].iloc[: upto + 1], raw_close_pivot[column].iloc[: upto + 1])
        if value is not None:
            result[column] = value
    return result


def _volume_pivot(prices: pd.DataFrame, index: pd.DatetimeIndex, columns: list[str]) -> pd.DataFrame | None:
    """Share volume and unadjusted close by session, or None when the panel has no volume."""

    if not isinstance(prices, pd.DataFrame) or not {"date", "etf_id", "volume"}.issubset(prices.columns):
        return None
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date"]).drop_duplicates(["date", "etf_id"], keep="last")
    volume = frame.pivot(index="date", columns="etf_id", values="volume")
    return volume.reindex(index=index.normalize(), columns=columns).set_axis(index)


def _raw_close_pivot(prices: pd.DataFrame, index: pd.DatetimeIndex, columns: list[str], fallback: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(prices, pd.DataFrame) or "close" not in prices.columns:
        return fallback
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date"]).drop_duplicates(["date", "etf_id"], keep="last")
    close = frame.pivot(index="date", columns="etf_id", values="close")
    return close.reindex(index=index.normalize(), columns=columns).set_axis(index)


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
    invalid = ~np.isfinite(frame["adjusted_close"].to_numpy(dtype=float)) | frame["adjusted_close"].le(0).to_numpy()
    if invalid.any():
        row = frame.loc[invalid].iloc[0]
        raise BacktestDataUnavailableError(f"invalid_price_data: {row['etf_id']} {row['date']}")
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
    source_raw = row.get("source")
    provider_symbol_raw = row.get("provider_symbol")
    if type(source_raw) is not str or type(provider_symbol_raw) is not str:
        return None
    source = source_raw.strip()
    provider_symbol = provider_symbol_raw.strip()
    if not source or not provider_symbol or source.casefold() in {"nan", "none"} or provider_symbol.casefold() in {"nan", "none"}:
        return None
    return f"{source}|{provider_symbol}"


def _calendar_alias_value(
    fields: Mapping[str, object],
    aliases: tuple[str, ...],
    *,
    digest: bool = False,
    default: object = None,
) -> tuple[bool, object]:
    """Validate one persisted calendar alias set without truthiness fallback."""

    present = [fields[name] for name in aliases if name in fields]
    if not present:
        return True, default
    for value in present:
        if digest:
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value.casefold())
            ):
                return False, None
        elif type(value) is not str or not value.strip():
            return False, None
    normalised = [value.casefold() if digest else value for value in present]
    if len(set(normalised)) != 1:
        return False, None
    return True, normalised[0]


def _calendar_projection(identity: Mapping[str, object], instrument_id: str) -> dict[str, object]:
    """Normalise the existing identity-master listing projection shape."""

    if identity.get("status") != "available" or identity.get("instrument_id") != instrument_id:
        return {}
    if isinstance(identity.get("identity_objects"), list):
        if not _calendar_projection_is_well_typed(identity):
            return {}
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
    source_version_valid, source_version = _calendar_alias_value(
        fields,
        ("source_version", "calendar_source_version"),
        default="identity-master.v1",
    )
    source_checksum_valid, source_checksum = _calendar_alias_value(
        fields,
        ("source_checksum", "calendar_source_checksum"),
        digest=True,
    )
    lineage_valid, lineage_hash = _calendar_alias_value(
        fields,
        ("identity_lineage_hash", "calendar_identity_lineage_hash"),
        digest=True,
    )
    if not source_version_valid or not source_checksum_valid or not lineage_valid:
        return {}
    for field_name in ("opening_auction_minutes", "closing_auction_minutes"):
        if field_name in fields:
            value = fields[field_name]
            if type(value) is not int or value < 0:
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
                    "calendar_source_version": source_version,
                    "opening_auction_minutes": fields.get("opening_auction_minutes", 0),
                    "closing_auction_minutes": fields.get("closing_auction_minutes", 0),
                },
            }
        ],
        "identity_history": [{"source_id": source_id}],
        "_persisted_source_checksum": source_checksum,
        "_persisted_lineage_hash": lineage_hash,
    }


def _calendar_projection_is_well_typed(identity: Mapping[str, object]) -> bool:
    for aliases, digest in (
        (("source_version", "calendar_source_version"), False),
        (("source_checksum", "calendar_source_checksum"), True),
        (("identity_lineage_hash", "calendar_identity_lineage_hash"), True),
    ):
        valid, _ = _calendar_alias_value(identity, aliases, digest=digest)
        if not valid:
            return False
    for field_name in (
        "identity_decision_id",
        "identity_decision_time",
        "identity_effective_at",
    ):
        value = identity.get(field_name)
        if type(value) is not str or not value.strip():
            return False
    objects = identity.get("identity_objects")
    history = identity.get("identity_history")
    if not isinstance(objects, list) or not isinstance(history, list) or not history:
        return False
    candidates = []
    for item in objects:
        if not isinstance(item, Mapping):
            return False
        object_type = item.get("object_type")
        if type(object_type) is not str or object_type.casefold() not in {"listing", "quotation"}:
            continue
        object_id = item.get("object_id")
        fields = item.get("fields")
        if type(object_id) is not str or not object_id.strip() or not isinstance(fields, Mapping):
            return False
        if any(
            type(fields.get(key)) is not str or not fields[key].strip()
            for key in ("mic", "calendar_id", "timezone")
        ):
            return False
        for aliases, digest in (
            (("source_version", "calendar_source_version"), False),
            (("source_checksum", "calendar_source_checksum"), True),
            (("identity_lineage_hash", "calendar_identity_lineage_hash"), True),
        ):
            valid, _ = _calendar_alias_value(fields, aliases, digest=digest)
            if not valid:
                return False
        for field_name in ("opening_auction_minutes", "closing_auction_minutes"):
            if field_name in fields:
                value = fields[field_name]
                if type(value) is not int or value < 0:
                    return False
        candidates.append(item)
    if len(candidates) != 1:
        return False
    return all(
        isinstance(row, Mapping)
        and type(row.get("source_id")) is str
        and bool(row["source_id"].strip())
        for row in history
    )


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
        source_aliases_valid, source_alias = _calendar_alias_value(
            persisted,
            ("source_checksum", "calendar_source_checksum"),
            digest=True,
        )
        lineage_aliases_valid, lineage_alias = _calendar_alias_value(
            persisted,
            ("identity_lineage_hash", "calendar_identity_lineage_hash"),
            digest=True,
        )
        if not source_aliases_valid or not lineage_aliases_valid:
            return {}, "canonical_market_calendar_lineage_conflict"
        expected_source = persisted.get("_persisted_source_checksum", source_alias)
        if expected_source is not None and (
            type(expected_source) is not str
            or len(expected_source) != 64
            or any(character not in "0123456789abcdef" for character in expected_source.casefold())
        ):
            return {}, "canonical_market_calendar_lineage_conflict"
        if expected_source is not None and expected_source.casefold() != listing.source_checksum.casefold():
            return {}, "canonical_market_calendar_lineage_conflict"
        expected_lineage = persisted.get("_persisted_lineage_hash", lineage_alias)
        if expected_lineage is not None and (
            type(expected_lineage) is not str
            or len(expected_lineage) != 64
            or any(character not in "0123456789abcdef" for character in expected_lineage.casefold())
        ):
            return {}, "canonical_market_calendar_lineage_conflict"
        if expected_lineage is not None and expected_lineage.casefold() != listing.lineage_hash.casefold():
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
        cutoff = _explicit_utc_timestamp(knowledge_cutoff)
        if cutoff is None:
            return None
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
    open_gap_warning_threshold: float | None = None,
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
        "open_gap_warning": _open_gap_warning(close_to_next_open, open_gap_warning_threshold),
        "open_gap_warning_threshold": open_gap_warning_threshold,
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


_TRADE_LOG_BASE_COLUMNS = (
    "date",
    "signal_date",
    "execution_date",
    "strategy",
    "turnover",
    "cost_eur",
    "estimated_cost_bps",
    "cost_model_id",
    "cost_data_quality",
    "cost_estimated",
    "capacity_eur",
)
_TRADE_LOG_CAPACITY_COLUMNS = (
    "capacity_enforced",
    "unfilled_eur",
    "capacity_fill_status",
    "max_days_to_fill",
    "capacity_fx_unavailable",
    "remainder_policy",
)


def _trade_log_columns(capacity_active: bool) -> list[str]:
    """Fixed trade-log schema, so a run with no rows at all still serialises with its columns."""

    evidence = _execution_evidence(
        current_prices=pd.Series(dtype=float),
        next_adjusted_close=pd.Series(dtype=float),
        next_open=pd.Series(dtype=float),
        next_high=pd.Series(dtype=float),
        next_low=pd.Series(dtype=float),
        changed_weights=pd.Series(dtype=float),
    )
    return list(dict.fromkeys([*_TRADE_LOG_BASE_COLUMNS, *(_TRADE_LOG_CAPACITY_COLUMNS if capacity_active else ()), *evidence]))


def _open_gap_warning(gap: float | None, threshold: float | None) -> bool | None:
    """Flag a large close-to-next-open gap; unknown stays unknown."""

    if gap is None or threshold is None or not np.isfinite(gap):
        return None
    return bool(abs(gap) >= threshold)


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
    open_gap_warning_threshold: float | None = None,
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
        "open_gap_warning": _open_gap_warning(gap, open_gap_warning_threshold),
        "open_gap_warning_threshold": open_gap_warning_threshold,
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


SIGNAL_WEIGHT_STEP = 0.02


def _signal_weight_action(signal: object) -> str:
    """Map a published advisory action to the explicit backtest weight action.

    ``advisory_action`` publishes both ``trim`` and ``sell`` as ``trim_candidate``;
    the sell is the advisory whose suggested new weight is zero, so it exits the
    position instead of becoming a 2% trim.  Anything else is ``hold`` (no change).
    """

    action = str(getattr(signal, "action", ""))
    if action == "sell":
        return "sell"
    if action in {"trim", "trim_candidate"}:
        suggested = finite_float_or_none(getattr(signal, "suggested_new_weight", None))
        return "sell" if suggested is not None and suggested <= 0.0 else "trim"
    if action in {"buy", "add", "add_candidate"}:
        return "add"
    return "hold"


def _next_signal_weights(current: pd.Series, target: pd.Series, actions: Mapping[str, str]) -> pd.Series:
    """Apply per-instrument weight actions; weight not held stays implicit cash.

    Weights above 100% are scaled down; weights below 100% keep the remainder as
    cash (it is not redistributed over the other positions).
    """

    weights = current.copy()
    for etf_id, action in actions.items():
        if etf_id not in weights.index:
            continue
        if action == "add":
            weights[etf_id] = min(float(target.get(etf_id, 0.0)) * 1.20, weights[etf_id] + SIGNAL_WEIGHT_STEP)
        elif action == "trim":
            weights[etf_id] = max(0.0, weights[etf_id] - SIGNAL_WEIGHT_STEP)
        elif action == "sell":
            weights[etf_id] = 0.0
    total = float(weights.sum())
    return weights / total if total > 1.0 else weights


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


class _StageShare:
    """Results of cost-independent stages, shared by the runs of one cost-regime comparison.

    The three cost regimes differ only in the cost model, so everything derived from the same prices,
    configuration and evidence objects (FX, EUR-basis features, per-cutoff data-quality and quality-momentum
    evidence, price-source identities, ADV) is identical across them and is computed once.  A key names every input
    object by identity and the objects are pinned for the lifetime of the share, so an identity can never be reused
    by a different object.  Nothing here depends on cost parameters, and every cutoff keeps its own entry
    (point-in-time exactness is unchanged).
    """

    def __init__(self) -> None:
        self._values: dict[object, object] = {}
        self._pins: list[object] = []

    def memo(self, key: object, compute: Callable[[], object], *pins: object) -> object:
        if key not in self._values:
            self._values[key] = compute()
            self._pins.extend(pins)
        return self._values[key]


_STAGE_SHARE: ContextVar[_StageShare | None] = ContextVar("backtest_stage_share", default=None)


@contextmanager
def _shared_backtest_scope() -> Iterator[_StageShare]:
    """Share cost-independent stages (and per-instrument classification state) across the runs inside the scope."""

    share = _STAGE_SHARE.get()
    if share is not None:
        yield share
        return
    share = _StageShare()
    token = _STAGE_SHARE.set(share)
    try:
        with classification_state_memo(), fx_cross_rate_memo():
            yield share
    finally:
        _STAGE_SHARE.reset(token)


def _in_shared_backtest_scope(function: Callable[..., object]) -> Callable[..., object]:
    @functools.wraps(function)
    def wrapper(*args: object, **kwargs: object) -> object:
        with _shared_backtest_scope():
            return function(*args, **kwargs)

    return wrapper


@_in_shared_backtest_scope
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
    cost_stress_multiplier: float = 1.0,
    enforce_capacity: bool = False,
    fx_rates: pd.DataFrame | None = None,
    point_in_time_membership_evidence: Mapping[str, object] | None = None,
    min_trade_value_eur: float | None = None,
) -> BacktestReport:
    if isinstance(rebalance_frequency_days, bool) or not isinstance(rebalance_frequency_days, int) or rebalance_frequency_days < 1:
        raise ValueError("rebalance_frequency_days must be an integer of at least 1")
    initial_value = finite_float_or_none(initial_value_eur)
    if initial_value is None or initial_value <= 0:
        raise ValueError("initial_value_eur must be finite and greater than 0")
    transaction_cost = finite_float_or_none(transaction_cost_bps)
    if transaction_cost_bps is not None and (transaction_cost is None or transaction_cost < 0):
        raise ValueError("transaction_cost_bps must be finite and non-negative")
    stress_multiplier = finite_float_or_none(cost_stress_multiplier)
    if stress_multiplier is None or stress_multiplier < 1.0:
        raise ValueError("cost_stress_multiplier must be finite and at least 1")
    # No-trade band: None applies the configured minimum trade of the risk limits (one policy path with the signal
    # pipeline and the portfolio sandbox); an explicit 0 opts out and keeps every rebalance order.
    minimum_trade = (
        finite_float_or_none(config.risks.portfolio_limits.min_trade_value_eur)
        if min_trade_value_eur is None
        else finite_float_or_none(min_trade_value_eur)
    )
    if minimum_trade is None or minimum_trade < 0:
        raise ValueError("min_trade_value_eur must be finite and non-negative")
    validate_execution_disabled(benchmark_reference or unavailable_reference_projection())
    validate_execution_disabled(reference_identity or {})
    share = _STAGE_SHARE.get()
    assert share is not None  # run_backtest always executes inside _shared_backtest_scope
    # ``prices`` is re-bound to a clipped copy below; stage keys name the caller's object plus the clip window.
    source_prices = prices
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
    universe_without_history = [column for column in config.universe.enabled_ids if column not in pivot_raw.columns]
    panel_outside_universe = sorted(
        str(column) for column in pivot_raw.columns if column not in set(config.universe.enabled_ids)
    )
    columns, short_history_ids = _exclude_late_listed_short_history(pivot_raw, columns)
    selected_raw = pivot_raw.reindex(columns=columns)
    observed_flags = selected_raw.notna()
    panel_end = selected_raw.index.max()
    delisted_ids = sorted(
        column for column in columns if observed_flags[column].iloc[::-1].idxmax() < panel_end
    )
    column_set = set(columns)
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
    open_gap_warning_threshold = float(config.costs.cost_model.open_gap_warning_threshold)
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
    cost_model_id = _cost_model_identity(config)
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
        "cost_model_id": cost_model_id,
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
    metadata["excluded_short_history_instruments"] = list(short_history_ids)
    metadata["universe_ids"] = list(columns)
    # With no configured target weight for the universe every target-based strategy
    # allocates equally; that substitution is recorded, never silent.
    configured_targets = config.targets.positions
    targets_configured = any(
        column in configured_targets and float(configured_targets[column].target_weight) > 0.0 for column in columns
    )
    metadata["target_weight_source"] = "configured" if targets_configured else "equal_weight_fallback_no_targets"
    survivorship_reasons = []
    pit_membership_verified = _point_in_time_membership_verified(point_in_time_membership_evidence)
    if not pit_membership_verified:
        # The universe is today's listing set: delisted/removed members are absent unless membership is evidenced.
        survivorship_reasons.append(SURVIVORSHIP_NO_PIT_REASON)
    for excluded_id in panel_outside_universe:
        survivorship_reasons.append(f"panel_instrument_outside_enabled_universe_excluded: {excluded_id}")
    if universe_without_history:
        survivorship_reasons.append("universe_instruments_without_price_history: " + ", ".join(universe_without_history))
    if short_history_ids:
        survivorship_reasons.append("late_listed_short_history_excluded: " + ", ".join(short_history_ids))
    if missing_observation_rows:
        survivorship_reasons.append(
            f"incomplete_price_rows_excluded_never_zero_filled: {missing_observation_rows}"
        )
    metadata["delisted_instruments"] = delisted_ids
    metadata["survivorship_label"] = SURVIVORSHIP_CONDITIONAL if survivorship_reasons else SURVIVORSHIP_FULL
    metadata["survivorship_reasons"] = survivorship_reasons
    metadata["missing_prices_zero_filled"] = False
    if transaction_cost_bps is not None:
        cost_regime = COST_REGIME_LEGACY
    elif stress_multiplier > 1.0:
        cost_regime = COST_REGIME_STRESS
    else:
        cost_regime = COST_REGIME_MODELLED
    metadata["cost_regime"] = cost_regime
    metadata["cost_stress_multiplier"] = stress_multiplier
    metadata["is_execution_evidence"] = False
    metadata["cost_regime_note"] = (
        _FLAT_COST_NOT_EVIDENCE
        if cost_regime == COST_REGIME_LEGACY
        else "Detailed modelled costs are local research estimates, not execution evidence."
    )
    participation_cap = min(1.0, max(0.0, float(config.costs.cost_model.max_participation_rate)))
    volume_pivot = _volume_pivot(prices, pivot.index, columns) if enforce_capacity else None
    volume_evidence = volume_pivot is not None and bool(volume_pivot.notna().any().any())
    if enforce_capacity and volume_pivot is None:
        # No volume column at all: liquidity cannot be verified, so no order fills (fail closed).
        volume_pivot = pd.DataFrame(np.nan, index=pivot.index, columns=columns)
    raw_close_pivot = _raw_close_pivot(prices, pivot.index, columns, pivot) if enforce_capacity else None
    capacity_active = enforce_capacity and volume_pivot is not None and raw_close_pivot is not None
    instrument_currency = {item.id: str(item.currency or "EUR").upper() for item in config.universe.etfs}
    needs_fx = any(instrument_currency.get(column, "EUR") != "EUR" for column in columns)
    fx_known_by = _fx_known_by(prices, reference_identity)
    fx_frame = fx_rates if fx_rates is not None else pd.DataFrame()
    if fx_rates is None and needs_fx:
        try:
            fx_frame = share.memo(("fx_frame", id(source_prices), id(reference_identity), repr(calculation_window)), lambda: fx_rates_for_prices(prices), source_prices, reference_identity)  # type: ignore[assignment]
        except Exception:  # an unreadable FX store leaves every non-EUR session fx_unavailable
            fx_frame = pd.DataFrame()
    # Canonical FX by session: non-EUR listings fill whenever a point-in-time rate exists for the
    # session; only a missing rate (fx_unavailable) blocks, never a local-currency figure read as EUR.
    pivot_index_digest = hashlib.sha256(pivot.index.asi8.tobytes()).hexdigest()
    fx_pivot = (
        share.memo(
            ("fx_pivot", id(config), id(source_prices), id(reference_identity), id(fx_frame), tuple(columns), pivot_index_digest),
            lambda: _fx_rate_pivot(pivot.index, columns, instrument_currency, fx_frame, fx_known_by),
            config,
            source_prices,
            reference_identity,
            fx_frame,
        )
        if enforce_capacity
        else None
    )
    raw_close_eur_pivot = raw_close_pivot * fx_pivot if capacity_active and fx_pivot is not None else None
    fx_never_available_ids = (
        {column for column in columns if not bool(fx_pivot[column].notna().any())} if fx_pivot is not None else set()
    )
    fx_checked_ever_ids = set(columns) - fx_never_available_ids
    # Equity certificates have no quote source here: they fill at the most conservative documented
    # cost tier and are flagged cost_estimated, never held back as cash.
    cost_estimated_ids = {
        item.id
        for item in config.universe.etfs
        if item.id in column_set and str(item.instrument_type or "").casefold() == "equity_certificate"
    }
    if not enforce_capacity:
        metadata["capacity_enforcement"] = "not_enforced"
    elif not volume_evidence:
        metadata["capacity_enforcement"] = "unavailable_no_volume_data"
    else:
        metadata["capacity_enforcement"] = "enforced"
    metadata["participation_cap"] = participation_cap
    metadata["capacity_remainder_policy"] = _REMAINDER_POLICY
    metadata["capacity_fx_unavailable_instruments"] = sorted(fx_never_available_ids)
    metadata["cost_estimated_instruments"] = sorted(cost_estimated_ids)
    # A report qualifies only with the detailed cost model AND verified liquidity evidence.
    qualification_blockers = []
    if cost_regime != COST_REGIME_MODELLED:
        qualification_blockers.append(f"cost_regime_{cost_regime}_is_not_the_qualifying_regime")
    if not enforce_capacity:
        qualification_blockers.append("capacity_not_enforced")
    elif not volume_evidence or any(
        not bool(volume_pivot[column].notna().any()) for column in sorted(fx_checked_ever_ids)
    ):
        qualification_blockers.append("liquidity_evidence_unavailable")
    if enforce_capacity and metadata["capacity_fx_unavailable_instruments"]:
        # Instruments without any FX evidence can never fill: the universe would silently shrink to cash for them.
        qualification_blockers.append("fx_unavailable_instruments_unfillable")
    metadata["qualification_blockers"] = qualification_blockers
    metadata["qualifying_cost_regime"] = not qualification_blockers
    if short_history_ids:
        metadata["data_status"] = "warning"
        metadata["short_history_warning"] = (
            f"{len(short_history_ids)} instrument(s) listed later with fewer than {MIN_INSTRUMENT_HISTORY_SESSIONS} "
            "adjusted-price sessions were left out of this backtest: " + ", ".join(short_history_ids)
        )
    # The first complete price row is a zero-return warm-up placeholder; it is never traded, and pre-listing rows were excluded above.
    # Holdings accounting aggregates SIMPLE returns across instruments (log returns do not add across assets).
    simple_returns = (pivot / pivot.shift(1) - 1.0).fillna(0.0)
    start_index = 220
    rebalance_indexes = set(range(start_index, len(pivot), rebalance_frequency_days))
    # Signal features are causal, but computing the complete historical frame
    # for every rebalance repeats the same prefix work.  Hoist that pure work
    # only for the ordinary daily-price shape; intraday rows retain the exact
    # prefix path because ``compute_features`` deliberately normalises their
    # dates and would otherwise lose the timestamp cutoff.
    last_rebalance_index = max(
        (
            index
            for index in rebalance_indexes
            if start_index < index and index + 1 < len(pivot)
        ),
        default=None,
    )
    reusable_default_features: pd.DataFrame | None = None
    reusable_benchmark_features: pd.DataFrame | None = None
    reusable_benchmark_first_date: pd.Timestamp | None = None
    price_dates: pd.Series | None = None
    configured_currency = {item.id: str(item.currency or "EUR") for item in config.universe.etfs}
    if last_rebalance_index is not None:
        price_dates = pd.to_datetime(prices["date"])
        last_rebalance_cutoff = pivot.index[last_rebalance_index]
        feature_mask = price_dates <= last_rebalance_cutoff
        feature_mask &= price_dates.notna()
        if calculation_window is not None:
            feature_mask &= price_dates >= calculation_window[0]
            feature_mask &= price_dates <= calculation_window[1]
        feature_prices = prices.loc[feature_mask].copy()
        feature_dates = price_dates.loc[feature_mask]
        daily_feature_rows = bool(
            feature_dates.empty
            or (feature_dates == feature_dates.dt.normalize()).all()
        )
        if daily_feature_rows:

            def build_reusable_features() -> tuple[pd.DataFrame, pd.DataFrame | None, pd.Timestamp | None]:
                # Signal features use the same EUR basis as the live score (canonical FX path); a
                # session without a usable rate gives no feature (fx_unavailable), never a local price.
                eur_feature_prices = eur_basis_prices(
                    feature_prices,
                    fx_frame,
                    configured_currency=configured_currency,
                    known_by=fx_known_by,
                )
                default_features = compute_features(
                    eur_feature_prices.frame,
                    benchmark_etf_id=None,
                )
                attach_eur_basis(default_features, eur_feature_prices)
                if canonical_benchmark_id is None:
                    default_features.loc[:, ["relative_strength_60d", "relative_strength_120d"]] = np.nan
                benchmark_features: pd.DataFrame | None = None
                benchmark_first_date: pd.Timestamp | None = None
                if canonical_benchmark_id is not None:
                    benchmark_mask = feature_prices["etf_id"] == canonical_benchmark_id
                    benchmark_dates = feature_dates.loc[benchmark_mask]
                    if not benchmark_dates.empty:
                        benchmark_features = compute_features(
                            eur_feature_prices.frame,
                            benchmark_etf_id=canonical_benchmark_id,
                        )
                        attach_eur_basis(benchmark_features, eur_feature_prices)
                        benchmark_first_date = benchmark_dates.min()
                return default_features, benchmark_features, benchmark_first_date

            # Cost-independent: the other cost regimes of the same comparison reuse the result (read-only below).
            reusable_default_features, reusable_benchmark_features, reusable_benchmark_first_date = share.memo(  # type: ignore[misc]
                (
                    "reusable_features",
                    id(config),
                    id(source_prices),
                    id(reference_identity),
                    id(fx_frame),
                    repr(calculation_window),
                    last_rebalance_cutoff,
                    canonical_benchmark_id,
                ),
                build_reusable_features,
                config,
                source_prices,
                reference_identity,
                fx_frame,
            )
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
    # ``weights`` stays the intended allocation after the last fill (it feeds the
    # unchanged signal logic).  ``actual_weights`` is the value-weighted holding
    # mix, which drifts with prices between actual fills.
    actual_weights = {name: weight.copy() for name, weight in weights.items()}
    equity = {name: [initial_value_eur] for name in strategies}
    index_values = [pivot.index[start_index]]
    turnover = {name: 0.0 for name in strategies}
    cost_drag = {name: 0.0 for name in strategies}

    def trade_cost(
        notional: float, changes: pd.Series, adv: Mapping[str, float] | None
    ) -> tuple[float, float, str, float | None, dict[str, list[CostEstimate]]]:
        """One cost path for every fill: modelled execution cost, or the flat legacy override."""

        if transaction_cost_bps is None:
            estimate = estimate_rebalance_cost(
                config,
                notional,
                changes.to_dict(),
                stress_multiplier=stress_multiplier,
                adv_eur_by_instrument=adv,
                conservative_instruments=cost_estimated_ids,
            )
            by_instrument: dict[str, list[CostEstimate]] = {}
            for item in estimate.estimates:
                by_instrument.setdefault(item.instrument_id, []).append(item)
            quality = ", ".join(sorted({item.data_quality for item in estimate.estimates})) or "no_trade"
            return estimate.total_cost_eur, estimate.weighted_cost_bps, quality, estimate.capacity_eur, by_instrument
        flat = max(0.0, transaction_cost_bps)
        return notional * float(changes.sum()) * flat / 10_000, flat, "legacy_explicit_override", None, {}

    def capacity_limits(
        current: pd.Series, target: pd.Series, notional: float, session: pd.Timestamp, adv: Mapping[str, float]
    ) -> tuple[pd.Series, dict[str, object]]:
        fx_row = fx_pivot.loc[session]
        return _apply_capacity_limits(
            current,
            target,
            notional_eur=notional,
            volume_row=volume_pivot.loc[session],
            price_row=raw_close_eur_pivot.loc[session],
            adv_by_instrument=adv,
            participation=participation_cap,
            # A listing without a quote is priced at the conservative tier (cost_estimated), not blocked.
            manual_quote_ids=set(),
            # Only a session without a canonical FX rate is unverifiable (fx_unavailable).
            checked_ids={str(column) for column in fx_row.index[fx_row.notna()]},
        )

    # Initial holdings are a purchase like any other: with capacity enforced they
    # are checked against the first session's liquidity and costed, never assumed.
    initial_allocation: dict[str, dict[str, object]] = {}
    initial_purchase_cost: dict[str, float] = {}
    if capacity_active:
        start_session = pivot.index[start_index]
        start_adv = _adv_by_instrument(volume_pivot, raw_close_eur_pivot, set(columns), start_index)
        for name in strategies:
            held, info = capacity_limits(
                pd.Series(0.0, index=columns),
                actual_weights[name].reindex(columns).fillna(0.0),
                initial_value,
                start_session,
                start_adv,
            )
            purchase = held.abs()
            cost = trade_cost(initial_value, purchase, start_adv)[0]
            scale = initial_value / max(initial_value - cost, 1e-12)
            total_held = float(held.sum())
            if total_held * scale > 1.0:
                scale = 1.0 / total_held
            actual_weights[name] = held * scale
            equity[name] = [max(initial_value - cost, 0.0)]
            turnover[name] += float(purchase.sum())
            cost_drag[name] += cost
            initial_allocation[name] = {
                "cost_eur": float(cost),
                "unfilled_eur": float(info["unfilled_eur"]),
                "fill_status": ", ".join(f"{key}={value}" for key, value in sorted(info["statuses"].items()))
                or "full_fill",
                "remainder_policy": _REMAINDER_POLICY,
            }
    else:
        # Equal cost basis: the initial purchase is costed through the same trade_cost path for every
        # strategy (and the VWCE comparator), so "same universe, dates and costs" holds without capacity.
        for name in strategies:
            purchase = actual_weights[name].reindex(columns).fillna(0.0).abs()
            cost = trade_cost(initial_value, purchase, None)[0]
            scale = initial_value / max(initial_value - cost, 1e-12)
            total_held = float(purchase.sum())
            if total_held * scale > 1.0:
                scale = 1.0 / total_held
            actual_weights[name] = purchase * scale
            equity[name] = [max(initial_value - cost, 0.0)]
            turnover[name] += total_held
            cost_drag[name] += cost
            initial_purchase_cost[name] = float(cost)
    metadata["initial_allocation"] = initial_allocation
    metadata["initial_purchase_cost_eur"] = initial_purchase_cost
    pending_weights: dict[str, pd.Series] = {}
    pending_costs: dict[str, float] = {}
    pending_traded: set[str] = set()
    pending_execution_date: pd.Timestamp | None = None
    trade_rows: list[dict[str, object]] = []
    operational_evidence_rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    quality_evidence_rows: list[dict[str, object]] = []
    # Prices are fixed for the whole comparison, so these price-derived lookups are shared by its cost regimes.
    def build_price_lookups() -> tuple[
        dict[tuple[object, pd.Timestamp], str | None],
        dict[object, tuple[pd.DataFrame, pd.Series]],
        dict[object, Mapping[str, object] | None],
    ]:
        # Partition once so each exact-row lookup scans one instrument and one
        # day, not the whole price history; other rows can never match.
        partitions: dict[object, tuple[pd.DataFrame, pd.Series]] = {}
        if isinstance(prices, pd.DataFrame) and {"etf_id", "date"}.issubset(prices.columns):
            for key, frame in prices.groupby("etf_id", sort=False):
                partitions[key] = (
                    frame,
                    pd.to_datetime(frame["date"], errors="coerce").dt.normalize(),
                )
        return {}, partitions, {}

    price_source_identity_cache, prices_by_instrument, calendar_identity_cache = share.memo(  # type: ignore[misc]
        ("price_lookups", id(source_prices), id(reference_identity), repr(calculation_window)), build_price_lookups, source_prices, reference_identity
    )

    def cached_calendar_identity(instrument_id: object) -> Mapping[str, object] | None:
        # Prices are fixed for the whole run, so the persisted identity of one
        # instrument cannot change between rebalances.
        if instrument_id not in calendar_identity_cache:
            entry = prices_by_instrument.get(instrument_id)
            calendar_identity_cache[instrument_id] = _calendar_identity_from_price_rows(
                prices if entry is None else entry[0],
                instrument_id,
            )
        identity = calendar_identity_cache[instrument_id]
        return None if identity is None else deepcopy(identity)

    def cached_price_source_identity(
        instrument_id: object,
        observed_date: object,
    ) -> str | None:
        observed_timestamp = pd.Timestamp(observed_date).normalize()
        key = (instrument_id, observed_timestamp)
        if key not in price_source_identity_cache:
            entry = prices_by_instrument.get(instrument_id)
            price_source_identity_cache[key] = _price_source_identity(
                prices if entry is None else entry[0].loc[entry[1] == observed_timestamp],
                instrument_id,
                observed_date,
            )
        return price_source_identity_cache[key]

    for i in range(start_index + 1, len(pivot)):
        dt = pivot.index[i]
        execution_costs: dict[str, float] = {}
        if pending_execution_date is not None and dt == pending_execution_date:
            execution_costs = pending_costs

        day_return = simple_returns.loc[dt, columns]
        for name in strategies:
            previous_equity = equity[name][-1]
            held_weights = actual_weights[name].reindex(columns).fillna(0)
            portfolio_return = float((held_weights * day_return).sum())
            growth = 1.0 + portfolio_return
            new_equity = previous_equity * growth
            if growth > 0:
                # Value-weighted drift: holdings grow with their price, cash stays flat.
                actual_weights[name] = held_weights * (1.0 + day_return) / growth
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
                if name in pending_traded:
                    # A strategy that does not trade keeps its drifted holdings.
                    actual_weights[name] = weights[name].copy()
            pending_traded = set()
            pending_weights = {}
            pending_costs = {}
            pending_execution_date = None

        if i in rebalance_indexes and i + 1 < len(pivot):
            history = pivot.iloc[: i + 1]
            new_weights = {
                # Buy-and-hold never trades: it keeps the drifted holdings.
                "buy_and_hold": actual_weights["buy_and_hold"],
                "equal_weight": equal_weights(columns),
                "momentum_only": momentum_weights(history, columns),
                "trend_only": trend_weights(config, history, columns),
                "quality_only": pd.Series(0.0, index=columns, dtype=float),
                "quality_momentum": pd.Series(0.0, index=columns, dtype=float),
                "signal_strategy": weights["signal_strategy"],
            }
            def build_quality_evidence() -> pd.DataFrame:
                quality_prices = history.rename_axis("date").reset_index().melt(
                    id_vars=["date"], var_name="etf_id", value_name="adjusted_close"
                )
                sector_map = {
                    item.id: str(item.sector or "")
                    for item in config.universe.etfs
                    if item.id in columns and item.sector
                }
                return build_quality_momentum_frame(
                    quality_prices,
                    fundamentals if fundamentals is not None else pd.DataFrame(),
                    as_of_date=dt.date(),
                    sector_by_instrument=sector_map,
                )

            # Point-in-time per cutoff and independent of costs: computed once per cutoff for all cost regimes.
            quality_evidence = share.memo(  # type: ignore[attr-defined]
                (
                    "quality_evidence",
                    id(config),
                    id(source_prices),
                    id(fundamentals),
                    id(reference_identity),
                    repr(calculation_window),
                    tuple(columns),
                    dt,
                ),
                build_quality_evidence,
                config,
                source_prices,
                fundamentals,
                reference_identity,
            ).copy()
            quality_evidence_rows.extend(quality_evidence.to_dict("records"))
            new_weights["quality_only"] = quality_momentum_weights(quality_evidence, columns, mode="quality")
            new_weights["quality_momentum"] = quality_momentum_weights(quality_evidence, columns, mode="quality_momentum")
            if not quality_evidence.empty and (quality_evidence["status"] == "available").any():
                metadata["quality_momentum_evidence"] = "available"
            elif metadata.get("quality_momentum_evidence") != "available":
                metadata["quality_momentum_evidence"] = "unavailable"
            # The signal strategy uses the same live signal pipeline, then tilts around targets.
            assert price_dates is not None
            def prices_known_at_cutoff() -> pd.DataFrame:
                known = prices[price_dates <= dt].copy()
                if calculation_window is not None:
                    known_dates = pd.to_datetime(known["date"])
                    known = known.loc[
                        (known_dates >= calculation_window[0])
                        & (known_dates <= calculation_window[1])
                    ].copy()
                return known

            truncated_prices: pd.DataFrame | None = None
            if reusable_default_features is not None:
                features = reusable_default_features
                if (
                    reusable_benchmark_features is not None
                    and reusable_benchmark_first_date is not None
                    and dt >= reusable_benchmark_first_date
                ):
                    features = reusable_benchmark_features
            else:
                truncated_prices = prices_known_at_cutoff()
                eur_truncated = eur_basis_prices(
                    truncated_prices,
                    fx_frame,
                    configured_currency=configured_currency,
                    known_by=fx_known_by,
                )
                features = compute_features(eur_truncated.frame, benchmark_etf_id=canonical_benchmark_id)
                attach_eur_basis(features, eur_truncated)
                if canonical_benchmark_id is None:
                    features.loc[:, ["relative_strength_60d", "relative_strength_120d"]] = np.nan
            latest = latest_features(features, as_of_date=dt.date())
            latest_by_id = (
                latest.assign(etf_id=latest["etf_id"].astype(str)).drop_duplicates("etf_id", keep="last").set_index("etf_id")
                if not latest.empty and "etf_id" in latest.columns
                else pd.DataFrame()
            )
            # Signals see what is actually held (drifted with prices), not the stale target of the last fill.
            holdings = _holdings_from_weights(
                actual_weights["signal_strategy"].reindex(columns).fillna(0.0),
                pivot.iloc[i],
                equity["signal_strategy"][-1],
                dt.date(),
            )
            def validated_report() -> DataQualityReport:
                checked = validate_prices(
                    truncated_prices if truncated_prices is not None else prices_known_at_cutoff(),
                    as_of_date=dt.date(),
                    min_history_days=180,
                )
                if checked.status == "Blocked":
                    checked = DataQualityReport(
                        as_of_date=dt.date(),
                        issues=[issue for issue in checked.issues if issue.code != "insufficient_history"],
                    )
                return checked

            # The data-quality verdict at a cutoff depends only on the prices known then, never on costs.
            report = deepcopy(
                share.memo(
                    ("data_quality", id(source_prices), id(reference_identity), repr(calculation_window), dt),
                    validated_report,
                    source_prices,
                    reference_identity,
                )
            )
            decision_timestamp = pd.Timestamp(dt)
            decision_timestamp = (
                decision_timestamp.tz_localize(timezone.utc)
                if decision_timestamp.tzinfo is None
                else decision_timestamp.tz_convert(timezone.utc)
            )
            structure_caps = structure_confidence_caps(
                columns,
                document_registry=structure_document_registry,
                report_records=structure_report_records,
                supplemental_rows=structure_supplemental_rows,
                holdings=structure_holdings,
                decision_time=dt.date(),
                not_applicable_types=structure_cap_scope(config),
            )
            signals = generate_signals(
                config,
                latest,
                holdings,
                report,
                as_of_date=dt.date(),
                run_id=f"backtest_{dt:%Y%m%d}",
                decision_timestamp=decision_timestamp,
                publish=False,
                structure_confidence_caps=structure_caps,
            )
            signal_weight = weights["signal_strategy"].copy()
            target = target_weights(config, columns)
            signal_actions: dict[str, str] = {}
            for signal in signals:
                if signal.etf_id not in column_set:
                    continue  # disabled/unscorable instruments are outside the backtest universe (and the cache contract)
                canonical = signal.canonical_score
                structural_identity = structure_caps.provenance.get(signal.etf_id, {})
                signal_rows.append(
                    {
                        "date": dt.date(),
                        "signal_timestamp": pd.Timestamp(dt).isoformat(),
                        "etf_id": signal.etf_id,
                        "action": signal.action,
                        "score": signal.total_score,
                        "momentum_60d": _latest_feature_value(latest_by_id, signal.etf_id, "momentum_60d"),
                        "momentum_120d": _latest_feature_value(latest_by_id, signal.etf_id, "momentum_120d"),
                        "currency_basis": str(features.attrs.get("currency_basis", "local")),
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
                signal_actions[signal.etf_id] = _signal_weight_action(signal)
            new_weights["signal_strategy"] = _next_signal_weights(signal_weight, target, signal_actions)

            execution_dt = pivot.index[i + 1]
            pending_execution_date = execution_dt
            pending_weights = {}
            pending_costs = {}
            pending_traded = set()
            adv_by_instrument = (
                dict(
                    share.memo(
                        (
                            "adv",
                            id(config),
                            id(source_prices),
                            id(reference_identity),
                            id(fx_frame),
                            repr(calculation_window),
                            tuple(columns),
                            pivot_index_digest,
                            i,
                        ),
                        lambda: _adv_by_instrument(volume_pivot, raw_close_eur_pivot, set(columns), i),
                        config,
                        source_prices,
                        reference_identity,
                        fx_frame,
                    )
                )
                if capacity_active
                else {}
            )
            execution_returns = simple_returns.loc[execution_dt, columns]
            for name, new_weight in new_weights.items():
                signal_weight_row = actual_weights[name].reindex(columns).fillna(0)
                # Orders fill at the next close: the held weights first drift through the
                # execution session, and both the target difference and the notional use
                # that drifted book, not the signal-day weights.
                current_weight_row, execution_return = _drift_to_execution(signal_weight_row, execution_returns)
                trade_notional = equity[name][-1] * max(0.0, 1.0 + execution_return)
                # Buy-and-hold never trades: its target is whatever it holds at execution.
                target_weight_row = (
                    current_weight_row.copy() if name == "buy_and_hold" else new_weight.reindex(columns).fillna(0)
                )
                capacity_info: dict[str, object] | None = None
                if name != "buy_and_hold":
                    # A skipped order is never placed, so it is neither costed nor counted as unfilled.
                    target_weight_row = _apply_minimum_trade_band(
                        current_weight_row,
                        target_weight_row,
                        notional_eur=trade_notional,
                        min_trade_eur=minimum_trade,
                    )
                if capacity_active:
                    target_weight_row, capacity_info = capacity_limits(
                        current_weight_row, target_weight_row, trade_notional, execution_dt, adv_by_instrument
                    )
                new_weight = target_weight_row
                diff = (target_weight_row - current_weight_row).abs()
                step_turnover = float(diff.sum())
                step_cost, step_cost_bps, step_cost_quality, step_capacity_eur, instrument_costs = trade_cost(
                    trade_notional, diff, adv_by_instrument if capacity_active else None
                )
                turnover[name] += step_turnover
                cost_drag[name] += step_cost
                pending_weights[name] = new_weight.reindex(columns).fillna(0)
                pending_costs[name] = step_cost
                if step_turnover > 0:
                    pending_traded.add(name)
                # A fully blocked order has no turnover but still owns unfilled
                # accounting, so it is logged (turnover 0, no reference prices).
                order_blocked = capacity_info is not None and float(capacity_info["unfilled_eur"]) > 0.0
                if step_turnover > 0 or order_blocked:
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
                        changed_weights=diff if step_turnover > 0 else pd.Series(dtype=float),
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
                        open_gap_warning_threshold=open_gap_warning_threshold,
                    )
                    for instrument_id in diff.index[diff > 0]:
                        instrument_cost_matches = instrument_costs.get(str(instrument_id), [])
                        instrument_cost = instrument_cost_matches[0] if len(instrument_cost_matches) == 1 else None
                        initial_calendar_identity = cached_calendar_identity(instrument_id)
                        explicit_daily_cutoff = pd.Timestamp(dt)
                        explicit_daily_cutoff = (
                            explicit_daily_cutoff.tz_localize(timezone.utc)
                            if explicit_daily_cutoff.tzinfo is None
                            else explicit_daily_cutoff.tz_convert(timezone.utc)
                        )
                        signal_close = _canonical_session_close_timestamp(
                            initial_calendar_identity,
                            str(instrument_id),
                            dt,
                            service=calendar_service,
                            knowledge_cutoff=explicit_daily_cutoff,
                        )
                        calendar_identity = initial_calendar_identity
                        if calendar_identity_resolver is not None:
                            calendar_identity = (
                                calendar_identity_resolver(str(instrument_id), signal_close)
                                if signal_close is not None
                                else {
                                    "status": "unavailable",
                                    "instrument_id": str(instrument_id),
                                    "execution_allowed": False,
                                }
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
                            knowledge_cutoff=signal_close or explicit_daily_cutoff,
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
                                decision_price_source_identity=cached_price_source_identity(instrument_id, dt),
                                next_open_source_identity=cached_price_source_identity(instrument_id, execution_dt),
                                next_period_source_identity=cached_price_source_identity(
                                    instrument_id,
                                    pivot.index[i + 1],
                                ),
                                open_gap_warning_threshold=open_gap_warning_threshold,
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
                            "cost_model_id": cost_model_id if transaction_cost_bps is None else "explicit_transaction_cost_bps",
                            "cost_data_quality": step_cost_quality,
                            "cost_estimated": bool(set(map(str, diff.index[diff > 0])) & cost_estimated_ids),
                            "capacity_eur": step_capacity_eur,
                            **(
                                {
                                    "capacity_enforced": True,
                                    "unfilled_eur": float(capacity_info["unfilled_eur"]),
                                    "capacity_fill_status": ", ".join(
                                        f"{key}={value}" for key, value in sorted(capacity_info["statuses"].items())
                                    )
                                    or "full_fill",
                                    "max_days_to_fill": int(capacity_info["max_days_to_fill"]),
                                    "capacity_fx_unavailable": ", ".join(capacity_info["fx_unavailable"]),
                                    "remainder_policy": capacity_info["remainder_policy"],
                                }
                                if capacity_info is not None
                                else {}
                            ),
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
    # Only rebalances the execution loop can act on count: the next session must exist.
    rebalance_count = sum(1 for index in rebalance_indexes if start_index < index and index + 1 < len(pivot))
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
        assert_long_only(weights[name])
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
        filled_trades = [row for row in strategy_trades if float(row["turnover"]) > 0.0]
        metrics["trade_count"] = len(filled_trades)
        metrics["average_trade_eur"] = float(initial_value_eur * (sum(float(row["turnover"]) for row in filled_trades) / max(len(filled_trades), 1)))
        metrics["median_holding_period_days"] = float(rebalance_frequency_days)
        metrics["turnover_annualised"] = float(turnover[name] / years)
        # Fewer than 253 equity observations have no 12-month window: unavailable, never 0.
        worst_12m_available = bool(returns_252d.notna().any())
        metrics["worst_12m_return"] = float(returns_252d.min()) if worst_12m_available else None
        metrics["worst_12m_return_status"] = "available" if worst_12m_available else "unavailable"
        metrics["worst_12m_return_reason"] = (
            "" if worst_12m_available else f"at least 253 equity observations are required, got {len(equity_curves[name])}"
        )
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
    def vwce_comparator() -> dict[str, object]:
        """VWCE bought on the first session through the same capacity and cost path as the strategies."""

        if canonical_benchmark_id is None or benchmark is None:
            return {"status": "unavailable", "reason": "no canonical benchmark"}
        bench = benchmark.dropna()
        if len(bench) < 2 or float(bench.iloc[0]) <= 0.0:
            return {"status": "unavailable", "reason": "benchmark price history is missing"}
        weight = pd.Series({canonical_benchmark_id: 1.0})
        adv: dict[str, float] | None = None
        info: dict[str, object] = {"unfilled_eur": 0.0, "statuses": {}}
        if capacity_active:
            if canonical_benchmark_id not in columns:
                return {"status": "unavailable", "reason": "benchmark liquidity cannot be verified outside the universe"}
            adv = _adv_by_instrument(volume_pivot, raw_close_eur_pivot, set(columns), start_index)
            weight, info = capacity_limits(
                pd.Series(0.0, index=columns),
                pd.Series({column: float(column == canonical_benchmark_id) for column in columns}),
                initial_value,
                pivot.index[start_index],
                adv,
            )
        if float(weight.sum()) <= 0.0:
            return {
                "status": "unavailable",
                "reason": "no capacity-checked fill: the benchmark purchase did not fill",
            }
        cost, cost_bps, _, _, _ = trade_cost(initial_value, weight.abs(), adv)
        scale = initial_value / max(initial_value - cost, 1e-12)
        held = float(weight.sum())
        if held * scale > 1.0:
            scale = 1.0 / held if held > 0.0 else 1.0
        after_fee = max(initial_value - cost, 0.0)
        invested = held * scale * after_fee
        final_value = invested * float(bench.iloc[-1] / bench.iloc[0]) + (after_fee - invested)
        return {
            "status": "available",
            "instrument_id": canonical_benchmark_id,
            "final_value_eur": float(final_value),
            "cost_eur": float(cost),
            "cost_bps": float(cost_bps),
            "unfilled_eur": float(info["unfilled_eur"]),
            "fill_status": ", ".join(f"{key}={value}" for key, value in sorted(info["statuses"].items())) or "full_fill",
            "cost_regime": cost_regime,
        }

    unavailable_baselines: dict[str, str] = {}
    for name in strategies:
        if name in {"quality_only", "quality_momentum"} and metadata["quality_momentum_evidence_available_rows"] == 0:
            unavailable_baselines[name] = "no point-in-time quality evidence was available in the run"
        elif turnover[name] <= 0.0 and float(weights[name].abs().sum()) <= 0.0:
            unavailable_baselines[name] = "the strategy never held a position"
        elif (
            capacity_active
            and turnover[name] <= 0.0
            and float(initial_allocation.get(name, {}).get("unfilled_eur", 0.0)) > 0.0
        ):
            unavailable_baselines[name] = "no capacity-checked fill: the strategy never traded and its initial order was unfilled"
    metadata["investable_comparators"] = investable_comparator_summary(
        {
            name: {
                "final_value_eur": float(equity_curves[name].iloc[-1]),
                "cost_eur": float(cost_drag[name]),
                "turnover": float(turnover[name]),
            }
            for name in strategies
        },
        initial_value_eur=initial_value,
        vwce=vwce_comparator(),
        universe=columns,
        start=equity_curves.index.min().date(),
        end=equity_curves.index.max().date(),
        cost_regime=cost_regime,
        cost_model_id=cost_model_id if transaction_cost_bps is None else "explicit_transaction_cost_bps",
        unavailable_strategies=unavailable_baselines,
        v3_formula_identity=_v3_formula_identity(signal_rows),
    )
    no_ai = results.loc[results["strategy_name"] == "momentum_only", "calmar"].iloc[0]
    signal_calmar = results.loc[results["strategy_name"] == "signal_strategy", "calmar"].iloc[0]
    ai_added_value = ai_added_value_vs_baseline(signal_calmar, no_ai)
    return BacktestReport(
        results=results,
        equity_curves=equity_curves,
        trade_log=pd.DataFrame(trade_rows, columns=_trade_log_columns(capacity_active)),
        signal_log=pd.DataFrame(signal_rows),
        ai_added_value=ai_added_value,
        quality_label=overall_quality_label(results),
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


_REGIME_COMPARISON_COLUMNS = ("strategy_name", "final_value_eur", "cagr", "sharpe", "max_drawdown", "turnover", "cost_drag")


@_in_shared_backtest_scope
def run_backtest_cost_regimes(
    config: AppConfig,
    prices: pd.DataFrame,
    *,
    settings: Mapping[str, object] | None = None,
    runner: Callable[..., BacktestReport] | None = None,
    comparison_runner: Callable[..., BacktestReport] | None = None,
    **kwargs: object,
) -> CostRegimeReport:
    """Run the same strategy under three cost regimes and report them side by side.

    ``modelled_default`` (detailed cost model with capacity enforced) is the only
    regime that can qualify; ``legacy_flat_override`` (the flat basis-point
    override) and ``conservative_stress`` (modelled costs times the stress
    multiplier) are shown for comparison.  No regime is execution evidence.
    ``runner`` runs the modelled report and ``comparison_runner`` (default: the
    same callable) the two comparison regimes, so the application service keeps
    its compatibility seam.
    """

    run = runner or run_backtest
    compare = comparison_runner or run
    resolved = dict(settings if settings is not None else load_backtest_realism_settings())
    capacity = bool(resolved.get("enforce_capacity", True))
    legacy_bps = float(resolved.get("legacy_override_bps", 13.0))  # type: ignore[arg-type]
    stress = float(resolved.get("stress_cost_multiplier", 2.0))  # type: ignore[arg-type]
    for forbidden in ("transaction_cost_bps", "cost_stress_multiplier", "enforce_capacity"):
        kwargs.pop(forbidden, None)
    reports = {
        COST_REGIME_MODELLED: run(config, prices, enforce_capacity=capacity, **kwargs),
        COST_REGIME_LEGACY: compare(
            config, prices, transaction_cost_bps=legacy_bps, enforce_capacity=capacity, **kwargs
        ),
        COST_REGIME_STRESS: compare(
            config, prices, cost_stress_multiplier=max(stress, 1.0 + 1e-9), enforce_capacity=capacity, **kwargs
        ),
    }
    frames = []
    for regime, report in reports.items():
        columns = [name for name in _REGIME_COMPARISON_COLUMNS if name in report.results.columns]
        frame = report.results[columns].copy()
        frame.insert(0, "cost_regime", regime)
        frame["qualifying_cost_regime"] = bool(report.metadata.get("qualifying_cost_regime", False))
        frame["is_execution_evidence"] = False
        frames.append(frame)
    return CostRegimeReport(reports=reports, comparison=pd.concat(frames, ignore_index=True))


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
        strategy_trades = [row for row in trade_rows if row["strategy"] == strategy]
        doubled_cost_final = _doubled_cost_final_value(equity_curves[strategy], strategy_trades)
        start_value = float(equity_curves[strategy].dropna().iloc[0])
        survives_cost_stress = doubled_cost_final > start_value
        if positive_folds >= 3 and survives_cost_stress:
            statuses[strategy] = "stable"
        elif positive_folds >= 2 or survives_cost_stress:
            statuses[strategy] = "mixed"
        else:
            statuses[strategy] = "fragile"
    return statuses


def _doubled_cost_final_value(equity: pd.Series, trades: list[dict[str, object]]) -> float:
    """Final NAV if every trade had paid its cost twice, replayed at the trade dates.

    The extra cost taken on a trade date compounds with the growth (or loss) the book
    experienced after it, so an early cost weighs more than a late one; subtracting
    the summed costs from the final NAV would ignore that timing.
    """

    observed = pd.to_numeric(equity, errors="coerce").dropna()
    if observed.empty:
        return 0.0
    index = pd.DatetimeIndex(observed.index)
    values = observed.to_numpy(dtype=float)
    final_value = float(values[-1])
    stressed = final_value
    for row in trades:
        extra_cost = float(row["cost_eur"])
        if not np.isfinite(extra_cost) or extra_cost <= 0.0:
            continue
        position = int(index.searchsorted(pd.Timestamp(row["date"]), side="left"))
        if position >= len(values):
            continue  # the trade falls after the observed curve: it cannot touch this NAV
        at_trade = float(values[position])
        if at_trade <= 0.0:
            continue  # the book was already wiped out at that date
        stressed -= extra_cost * (final_value / at_trade)
    return max(stressed, 0.0)


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


def overall_quality_label(results: pd.DataFrame) -> str:
    """Report quality is that of the strategy under evaluation (``signal_strategy``); another strategy's MEDIUM never lifts it."""

    if results.empty or not {"backtest_quality", "strategy_name"}.issubset(results.columns):
        return "low"
    signal = results.loc[results["strategy_name"] == "signal_strategy", "backtest_quality"].dropna().astype(str)
    return "medium" if not signal.empty and (signal == "medium").all() else "low"
