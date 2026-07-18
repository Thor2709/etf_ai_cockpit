"""Deterministic, local ETF liquidity and premium/discount evidence.

The module deliberately consumes supplied price and quote frames only.  It
does not fetch market data and its capacity output is a research policy
signal, never an execution permission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from collections.abc import Mapping

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.portfolio.costs import estimate_execution_cost


ETF_ECONOMICS_MODEL_ID = "etf-economics-v1"
_QUOTE_ID_COLUMNS = ("instrument_id", "etf_id", "display_id")
_OFF_HOURS_SESSIONS = frozenset({"pre_market", "premarket", "after_hours", "post_market", "postmarket", "overnight", "off_hours", "closed"})


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _latest_timestamp(value: object) -> pd.Timestamp | None:
    if value is None or not pd.api.types.is_scalar(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True, format="mixed")
    return parsed if isinstance(parsed, pd.Timestamp) and not pd.isna(parsed) else None


def _as_of_timestamp(value: object, fallback: object) -> pd.Timestamp | None:
    parsed = _latest_timestamp(value)
    if parsed is None:
        parsed = _latest_timestamp(fallback)
    if parsed is None:
        return None
    # A date-only as-of value represents the end of that observed day for the
    # purpose of quote freshness, without inventing a timezone or exchange.
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return parsed + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return parsed


def _empty_report(instrument_id: str, message: str) -> "EtfLiquidityReport":
    return EtfLiquidityReport(
        instrument_id=instrument_id,
        status="unavailable",
        message=message,
        missing_evidence=("price_history", "bid_ask", "nav"),
        warnings=(message,),
    )


@dataclass(frozen=True)
class EtfLiquidityReport:
    """Read-only ETF economics evidence with explicit unavailable states."""

    instrument_id: str
    status: str
    message: str = ""
    model_id: str = ETF_ECONOMICS_MODEL_ID
    as_of: str = "unavailable"
    rows: int = 0
    rolling_turnover_eur_20d: float | None = None
    rolling_turnover_eur_60d: float | None = None
    median_daily_volume_20d: float | None = None
    zero_volume_days_60d: int | None = None
    zero_volume_rate_60d: float | None = None
    spread_proxy_bps: float | None = None
    spread_p95_bps: float | None = None
    quoted_spread_bps: float | None = None
    spread_source: str = "unavailable"
    gap_risk_p95_bps: float | None = None
    daily_volatility: float | None = None
    latest_price: float | None = None
    latest_volume: float | None = None
    exchange_capacity_eur: float | None = None
    order_value_eur: float = 0.0
    horizon_days: int = 1
    order_to_daily_turnover: float | None = None
    capacity_headroom_eur: float | None = None
    capacity_status: str = "unavailable"
    estimated_cost_bps: float | None = None
    stressed_cost_bps: float | None = None
    cost_data_quality: str = "unavailable"
    bid_eur: float | None = None
    ask_eur: float | None = None
    quote_mid_eur: float | None = None
    nav_eur: float | None = None
    premium_discount_bps: float | None = None
    underlying_liquidity_eur: float | None = None
    primary_market_capacity_eur: float | None = None
    primary_market_minimum_eur: float | None = None
    primary_market_status: str = "unavailable_not_exchange_volume"
    quote_status: str = "unavailable"
    quote_freshness: str = "unavailable"
    quote_age_hours: float | None = None
    stale_quote: bool | None = None
    off_hours_quote: bool | None = None
    missing_evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_id: str = "unavailable"
    source_authority: str = "derived_local_ohlcv"
    execution_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _scope_prices(price_history: pd.DataFrame, instrument_id: str) -> pd.DataFrame:
    frame = price_history.copy()
    for column in _QUOTE_ID_COLUMNS:
        if column in frame.columns:
            frame = frame[frame[column].astype(str).eq(str(instrument_id))]
            break
    if "date" not in frame.columns:
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed")
    frame = frame[frame["_date"].notna()].sort_values("_date", kind="stable")
    return frame.drop_duplicates("_date", keep="last")


def _scope_quote(quote_evidence: pd.DataFrame | Mapping[str, object] | None, instrument_id: str) -> pd.DataFrame:
    if isinstance(quote_evidence, Mapping):
        frame = pd.DataFrame([dict(quote_evidence)])
    elif isinstance(quote_evidence, pd.DataFrame):
        frame = quote_evidence.copy()
    else:
        return pd.DataFrame()
    for column in _QUOTE_ID_COLUMNS:
        if column in frame.columns:
            frame = frame[frame[column].astype(str).eq(str(instrument_id))]
            break
    timestamp_column = next((column for column in ("quote_timestamp", "timestamp", "as_of", "date") if column in frame.columns), None)
    if timestamp_column is None:
        return frame.reset_index(drop=True)
    frame["_timestamp"] = pd.to_datetime(frame[timestamp_column], errors="coerce", utc=True, format="mixed")
    return frame[frame["_timestamp"].notna()].sort_values("_timestamp", kind="stable").reset_index(drop=True)


def _quote_value(row: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = _positive(row.get(name))
        if value is not None:
            return value
    return None


def _quote_context(quote_evidence: pd.DataFrame | Mapping[str, object] | None, instrument_id: str, as_of: object, latest_price_date: object) -> dict[str, object]:
    frame = _scope_quote(quote_evidence, instrument_id)
    if frame.empty:
        return {
            "quote_status": "unavailable",
            "quote_freshness": "unavailable",
            "missing_evidence": {"bid_ask", "nav", "quote_timestamp"},
        }
    row = frame.iloc[-1].to_dict()
    bid = _quote_value(row, "bid", "bid_eur")
    ask = _quote_value(row, "ask", "ask_eur")
    mid = (bid + ask) / 2.0 if bid is not None and ask is not None and ask >= bid else None
    nav = _quote_value(row, "nav", "nav_eur", "indicative_nav", "indicative_nav_eur")
    timestamp = _latest_timestamp(row.get("_timestamp")) or _latest_timestamp(row.get("quote_timestamp")) or _latest_timestamp(row.get("timestamp")) or _latest_timestamp(row.get("as_of"))
    reference = _as_of_timestamp(as_of, latest_price_date)
    age_hours = None
    stale = None
    if timestamp is not None and reference is not None:
        age_hours = max(0.0, (reference - timestamp).total_seconds() / 3600.0)
        stale = age_hours > 24.0
    session = (_text(row.get("session")) or _text(row.get("quote_session")) or "").casefold().replace("-", "_").replace(" ", "_")
    off_hours = session in _OFF_HOURS_SESSIONS if session else None
    freshness = "unavailable"
    if timestamp is None:
        freshness = "missing_timestamp"
    elif stale:
        freshness = "stale"
    elif off_hours:
        freshness = "off_hours"
    else:
        freshness = "fresh"
    missing: set[str] = set()
    if bid is None or ask is None or ask < (bid or 0):
        missing.add("bid_ask")
    if nav is None:
        missing.add("nav")
    if timestamp is None:
        missing.add("quote_timestamp")
    return {
        "quote_status": "available",
        "quote_freshness": freshness,
        "quote_age_hours": None if age_hours is None else round(age_hours, 4),
        "stale_quote": stale,
        "off_hours_quote": off_hours,
        "bid_eur": bid,
        "ask_eur": ask,
        "quote_mid_eur": mid,
        "nav_eur": nav,
        "quoted_spread_bps": None if mid is None else round((ask - bid) / mid * 10_000.0, 8),
        "premium_discount_bps": None if mid is None or nav is None else round((mid / nav - 1.0) * 10_000.0, 8),
        "underlying_liquidity_eur": _quote_value(row, "underlying_adv_eur", "underlying_liquidity_eur", "underlying_turnover_eur"),
        "primary_market_capacity_eur": _quote_value(row, "primary_market_capacity_eur", "creation_redemption_capacity_eur"),
        "primary_market_minimum_eur": _quote_value(row, "primary_market_minimum_eur", "creation_redemption_minimum_eur"),
        "primary_market_status": "available" if _quote_value(row, "primary_market_capacity_eur", "creation_redemption_capacity_eur") is not None else "unavailable_not_exchange_volume",
        "source_id": _text(row.get("source_id")) or _text(row.get("source")) or "local_quote_import",
        "source_authority": _text(row.get("source_authority")) or "imported_quote_evidence",
        "missing_evidence": missing,
    }


def calculate_etf_liquidity(
    config: AppConfig,
    price_history: pd.DataFrame,
    instrument_id: str,
    *,
    order_value_eur: float = 0.0,
    horizon_days: int = 1,
    quote_evidence: pd.DataFrame | Mapping[str, object] | None = None,
    as_of: object = None,
    stress_multiplier: float = 1.0,
    primary_market_capacity_eur: float | None = None,
    primary_market_minimum_eur: float | None = None,
) -> EtfLiquidityReport:
    """Calculate local ETF liquidity, capacity and premium/discount evidence."""

    instrument = str(instrument_id or "").strip() or "unknown"
    frame = _scope_prices(price_history, instrument)
    if frame.empty:
        return _empty_report(instrument, "No dated local price history is available for ETF economics.")
    if "close" not in frame.columns or "volume" not in frame.columns:
        return _empty_report(instrument, "Price history lacks close or volume, so turnover capacity is unavailable.")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0).clip(lower=0.0)
    valid = close.gt(0) & frame["_date"].notna()
    frame = frame.loc[valid].copy()
    close = close.loc[valid]
    volume = volume.loc[valid]
    if frame.empty:
        return _empty_report(instrument, "No positive dated close values are available for ETF economics.")
    turnover = close * volume
    recent = frame.tail(60).copy()
    recent_close = close.loc[recent.index]
    recent_volume = volume.loc[recent.index]
    recent_turnover = turnover.loc[recent.index]
    turnover_20 = _finite(recent_turnover.tail(20).median())
    turnover_60 = _finite(recent_turnover.median())
    high = pd.to_numeric(recent.get("high"), errors="coerce") if "high" in recent.columns else pd.Series(dtype=float)
    low = pd.to_numeric(recent.get("low"), errors="coerce") if "low" in recent.columns else pd.Series(dtype=float)
    spread = ((high - low) / recent_close).where(recent_close.gt(0)).dropna()
    spread_bps = _finite(spread.median() * 10_000.0) if not spread.empty else None
    spread_p95 = _finite(spread.quantile(0.95) * 10_000.0) if not spread.empty else None
    opening = pd.to_numeric(recent.get("open"), errors="coerce") if "open" in recent.columns else pd.Series(dtype=float)
    previous_close = recent_close.shift(1)
    gaps = ((opening / previous_close) - 1.0).abs().where(previous_close.gt(0)).dropna()
    gap_risk = _finite(gaps.quantile(0.95) * 10_000.0) if not gaps.empty else None
    adjusted = pd.to_numeric(frame.get("adjusted_close", close), errors="coerce")
    returns = adjusted.pct_change().dropna()
    volatility = _finite(returns.tail(60).std()) if len(returns) >= 2 else None
    zero_days = int((recent_volume <= 0).sum())
    zero_rate = zero_days / len(recent_volume) if len(recent_volume) else None
    latest_date = frame["_date"].iloc[-1]
    quote = _quote_context(quote_evidence, instrument, as_of, latest_date)
    effective_spread = quote.get("quoted_spread_bps") if quote.get("quoted_spread_bps") is not None else spread_bps
    spread_source = "quoted_bid_ask" if quote.get("quoted_spread_bps") is not None else "high_low_proxy" if spread_bps is not None else "unavailable"
    order = max(0.0, _finite(order_value_eur) or 0.0)
    horizon = max(1, int(horizon_days))
    participation = min(1.0, max(0.0, _finite(getattr(config.costs.cost_model, "max_participation_rate", 0.1)) or 0.1))
    exchange_capacity = turnover_20 * participation * horizon if turnover_20 is not None else None
    order_ratio = order / turnover_20 if turnover_20 and order > 0 else None
    headroom = exchange_capacity - order if exchange_capacity is not None and order > 0 else None
    if order <= 0:
        capacity_status = "not_requested" if exchange_capacity is not None else "unavailable"
    elif exchange_capacity is None:
        capacity_status = "blocked_missing_liquidity"
    elif order > exchange_capacity:
        capacity_status = "blocked_liquidity_policy"
    else:
        capacity_status = "within_configured_participation"
    cost = estimate_execution_cost(
        config,
        instrument,
        order,
        adv_eur=turnover_20,
        daily_volatility=volatility,
        quoted_spread_bps=effective_spread,
        gap_bps=gap_risk,
        stress_multiplier=1.0,
    )
    stressed = estimate_execution_cost(
        config,
        instrument,
        order,
        adv_eur=turnover_20,
        daily_volatility=volatility,
        quoted_spread_bps=effective_spread,
        gap_bps=gap_risk,
        stress_multiplier=max(1.0, _finite(stress_multiplier) or 1.0),
    )
    missing = set(quote.get("missing_evidence", set()))
    if turnover_20 is None:
        missing.add("turnover")
    if spread_bps is None:
        missing.add("spread_proxy")
    if gap_risk is None:
        missing.add("gap_risk")
    warnings: list[str] = []
    if zero_rate and zero_rate > 0:
        warnings.append(f"{zero_days} of {len(recent_volume)} recent rows have zero or missing volume.")
    if quote.get("stale_quote"):
        warnings.append("Imported quote evidence is stale relative to the selected price as-of date.")
    if quote.get("off_hours_quote"):
        warnings.append("Imported quote evidence is marked off-hours; it is not represented as regular-session depth.")
    if order > 0 and capacity_status.startswith("blocked"):
        warnings.append("The order preview exceeds the configured local liquidity policy and is blocked for research review.")
    status = "available" if len(frame) >= 20 else "partial"
    if len(missing) >= 4:
        status = "partial"
    return EtfLiquidityReport(
        instrument_id=instrument,
        status=status,
        message="ETF liquidity evidence is calculated from local adjusted OHLCV and optional imported quote records.",
        as_of=str(latest_date),
        rows=len(frame),
        rolling_turnover_eur_20d=None if turnover_20 is None else round(turnover_20, 8),
        rolling_turnover_eur_60d=None if turnover_60 is None else round(turnover_60, 8),
        median_daily_volume_20d=_finite(recent_volume.tail(20).median()),
        zero_volume_days_60d=zero_days,
        zero_volume_rate_60d=None if zero_rate is None else round(zero_rate, 8),
        spread_proxy_bps=spread_bps,
        spread_p95_bps=spread_p95,
        quoted_spread_bps=quote.get("quoted_spread_bps"),
        spread_source=spread_source,
        gap_risk_p95_bps=gap_risk,
        daily_volatility=volatility,
        latest_price=_finite(close.iloc[-1]),
        latest_volume=_finite(volume.iloc[-1]),
        exchange_capacity_eur=None if exchange_capacity is None else round(exchange_capacity, 8),
        order_value_eur=round(order, 8),
        horizon_days=horizon,
        order_to_daily_turnover=None if order_ratio is None else round(order_ratio, 8),
        capacity_headroom_eur=None if headroom is None else round(headroom, 8),
        capacity_status=capacity_status,
        estimated_cost_bps=cost.total_cost_bps,
        stressed_cost_bps=stressed.total_cost_bps,
        cost_data_quality=cost.data_quality,
        bid_eur=quote.get("bid_eur"),
        ask_eur=quote.get("ask_eur"),
        quote_mid_eur=quote.get("quote_mid_eur"),
        nav_eur=quote.get("nav_eur"),
        premium_discount_bps=quote.get("premium_discount_bps"),
        underlying_liquidity_eur=quote.get("underlying_liquidity_eur"),
        primary_market_capacity_eur=primary_market_capacity_eur if primary_market_capacity_eur is not None else quote.get("primary_market_capacity_eur"),
        primary_market_minimum_eur=primary_market_minimum_eur if primary_market_minimum_eur is not None else quote.get("primary_market_minimum_eur"),
        primary_market_status="available" if (primary_market_capacity_eur is not None or quote.get("primary_market_capacity_eur") is not None) else str(quote.get("primary_market_status", "unavailable_not_exchange_volume")),
        quote_status=str(quote.get("quote_status", "unavailable")),
        quote_freshness=str(quote.get("quote_freshness", "unavailable")),
        quote_age_hours=quote.get("quote_age_hours"),
        stale_quote=quote.get("stale_quote"),
        off_hours_quote=quote.get("off_hours_quote"),
        missing_evidence=tuple(sorted(missing)),
        warnings=tuple(warnings),
        source_id=str(quote.get("source_id", "derived_local_ohlcv")),
        source_authority=str(quote.get("source_authority", "derived_local_ohlcv")),
    )


__all__ = ["ETF_ECONOMICS_MODEL_ID", "EtfLiquidityReport", "calculate_etf_liquidity"]
