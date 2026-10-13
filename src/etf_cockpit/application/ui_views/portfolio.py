"""Read-only view model for the Portfolio Sandbox first screen (spec 6.4, section 8).

Pass-through and descriptive statistics over saved valuations, holdings and the risk evidence already attached to
the portfolio analysis. Nothing here changes a score, gate, forecast or portfolio decision; a missing input stays
``None`` with a reason, never zero.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

RANGE_DAYS = {"1M": 31, "3M": 92, "1Y": 366}
TRADING_DAYS = 252
# Conventional Herfindahl-Hirschman bands on invested weights (descriptive wording only).
HHI_MODERATE = 0.15
HHI_HIGH = 0.25
MAX_BARS = 8


@dataclass(frozen=True)
class SeriesStats:
    first: float | None
    last: float | None
    range_return: float | None
    volatility: float | None
    max_drawdown: float | None
    reason: str | None


@dataclass(frozen=True)
class HoldingLine:
    instrument_id: str
    name: str
    weight: float | None
    value: float | None
    range_return: float | None
    risk_share: float | None


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def series_stats(values: Sequence[float | None], *, reason: str | None = None) -> SeriesStats:
    """Return, annualised volatility of simple steps and the deepest drawdown of an index-like series."""
    clean = [v for v in (_finite(item) for item in values) if v is not None]
    if len(clean) < 2:
        return SeriesStats(None, None, None, None, None, reason or "Fewer than two saved valuation points.")
    first, last = clean[0], clean[-1]
    steps = [b / a - 1.0 for a, b in zip(clean, clean[1:], strict=False) if a]
    volatility = None
    if len(steps) >= 2:
        mean = sum(steps) / len(steps)
        variance = sum((s - mean) ** 2 for s in steps) / (len(steps) - 1)
        volatility = math.sqrt(variance) * math.sqrt(TRADING_DAYS)
    peak, depth = clean[0], 0.0
    for value in clean:
        peak = max(peak, value)
        if peak:
            depth = min(depth, value / peak - 1.0)
    return SeriesStats(first, last, last / first - 1.0 if first else None, volatility, depth, None)


def herfindahl(weights: Sequence[float | None]) -> float | None:
    """Sum of squared weights renormalised to the invested part; None without weights."""
    clean = [w for w in (_finite(item) for item in weights) if w is not None and w > 0]
    total = sum(clean)
    return sum((w / total) ** 2 for w in clean) if clean and total > 0 else None


def hhi_band(value: float | None) -> str | None:
    if value is None:
        return None
    return "high" if value >= HHI_HIGH else "moderate" if value >= HHI_MODERATE else "low"


def window_return(prices: pd.DataFrame, instrument_id: str, range_key: str, as_of: date | None) -> float | None:
    """Adjusted-close return over the range ending at ``as_of`` (never after it); None when history is short."""
    needed = {"etf_id", "date", "adjusted_close"}
    if prices is None or prices.empty or not needed <= set(prices.columns):
        return None
    frame = prices.loc[prices["etf_id"].astype(str) == str(instrument_id), ["date", "adjusted_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna().sort_values("date")
    if as_of is not None:
        frame = frame.loc[frame["date"] <= pd.Timestamp(as_of)]
    if frame.empty:
        return None
    end = frame.iloc[-1]
    start_day = end["date"] - timedelta(days=RANGE_DAYS.get(range_key, RANGE_DAYS["1Y"]))
    before = frame.loc[frame["date"] <= start_day]
    if before.empty or not before.iloc[-1]["adjusted_close"]:
        return None
    return float(end["adjusted_close"] / before.iloc[-1]["adjusted_close"] - 1.0)


def current_risk_shares(holdings: pd.DataFrame, prices: pd.DataFrame) -> tuple[dict[str, float], str | None]:
    """Variance share per held instrument from the canonical robust-risk report at the current weights.

    Read-only pass-through: the report is not altered and an unavailable report yields no shares and its reason.
    """
    from etf_cockpit.portfolio.robust_risk import build_robust_risk_report

    if holdings is None or holdings.empty or prices is None or prices.empty:
        return {}, "Holdings or adjusted prices are unavailable."
    ident = "etf_id" if "etf_id" in holdings.columns else "instrument_id" if "instrument_id" in holdings.columns else None
    if ident is None:
        return {}, "Holdings have no instrument identifiers."
    allocation = pd.DataFrame({"etf_id": holdings[ident].astype(str), "current_weight": pd.to_numeric(holdings.get("current_weight"), errors="coerce")})
    held = sorted(set(allocation["etf_id"]))
    subset = prices.loc[prices["etf_id"].astype(str).isin(held)] if "etf_id" in prices.columns else prices
    try:
        report = build_robust_risk_report(subset, allocation, bootstrap_reps=0)
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        return {}, f"Risk evidence unavailable: {exc}"
    table = report.get("portfolio_contributions")
    if report.get("status") == "unavailable" or not isinstance(table, pd.DataFrame) or table.empty:
        return {}, str(report.get("message") or report.get("reason") or "Risk evidence unavailable.")
    shares = {str(row.instrument_id): _finite(row.variance_share) for row in table.itertuples()}
    return {key: value for key, value in shares.items() if value is not None}, None


def risk_insight(lines: Sequence[HoldingLine]) -> str | None:
    """"X adds n pts more risk than its weight; Y adds m pts less." from weight and risk share, or None."""
    gaps = [(line.instrument_id, (line.risk_share - line.weight) * 100.0) for line in lines if line.risk_share is not None and line.weight is not None]
    if len(gaps) < 2:
        return None
    more = max(gaps, key=lambda item: item[1])
    less = min(gaps, key=lambda item: item[1])
    if more[1] <= 0 or less[1] >= 0:
        return None
    return f"{more[0]} adds {more[1]:.1f} pts more risk than its weight; {less[0]} adds {abs(less[1]):.1f} pts less."


def holding_lines(
    holdings: pd.DataFrame,
    prices: pd.DataFrame,
    shares: Mapping[str, float],
    range_key: str,
    as_of: date | None,
) -> list[HoldingLine]:
    """One line per instrument (value and weight summed over the selected holdings view), largest weight first."""
    if holdings is None or holdings.empty:
        return []
    frame = holdings.copy()
    ident = "etf_id" if "etf_id" in frame.columns else "instrument_id" if "instrument_id" in frame.columns else None
    if ident is None:
        return []
    frame["_id"] = frame[ident].astype(str)
    frame["_w"] = pd.to_numeric(frame.get("current_weight"), errors="coerce")
    frame["_v"] = pd.to_numeric(frame.get("market_value_eur"), errors="coerce")
    lines: list[HoldingLine] = []
    for instrument_id, group in frame.groupby("_id", sort=False):
        weight = group["_w"].sum(min_count=1)
        value = group["_v"].sum(min_count=1)
        name = str(group["name"].iloc[0]) if "name" in group.columns and pd.notna(group["name"].iloc[0]) else instrument_id
        lines.append(
            HoldingLine(
                str(instrument_id),
                name,
                _finite(weight),
                _finite(value),
                window_return(prices, str(instrument_id), range_key, as_of),
                shares.get(str(instrument_id)),
            )
        )
    return sorted(lines, key=lambda line: line.weight if line.weight is not None else -1.0, reverse=True)
