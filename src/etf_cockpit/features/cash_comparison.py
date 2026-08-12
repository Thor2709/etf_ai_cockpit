"""Currency- and vintage-matched descriptive cash comparisons.

This module is deliberately pure.  It consumes a canonical adjusted/total-
return price series and a then-known official spot-curve selection; it never
changes scores, rankings, gates, forecasts or execution authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from collections.abc import Mapping

import pandas as pd


_DAY_COUNTS = {"ACT/360", "ACT/365F", "ACT/ACT-ISDA"}
_COMPOUNDING = {"annual", "continuous", "simple"}
_FRESHNESS = {"fresh"}


def _as_date(value: object, field_name: str) -> date:
    parsed = pd.to_datetime(value, errors="coerce", utc=True, format="mixed")
    if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
        raise ValueError(f"{field_name} must be an ISO date")
    return parsed.date()


def period_start_knowledge_cutoff(start_date: object) -> str:
    """Represent a date-only comparison cutoff as UTC midnight, without session inference."""

    start = _as_date(start_date, "start_date")
    return f"{start.isoformat()}T00:00:00+00:00"


def _utc_timestamp(value: object, field_name: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be an explicit timezone-aware timestamp"
        ) from exc
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError(f"{field_name} must be an explicit timezone-aware timestamp")
    return parsed.tz_convert("UTC")


def year_fraction(start_date: object, end_date: object, day_count: str = "ACT/365F") -> float:
    """Return the exact positive year fraction for the declared convention."""

    start = _as_date(start_date, "start_date")
    end = _as_date(end_date, "end_date")
    if end <= start:
        raise ValueError("end_date must be after start_date")
    if day_count not in _DAY_COUNTS:
        raise ValueError(f"unsupported day count: {day_count}")
    if day_count == "ACT/360":
        return (end - start).days / 360.0
    if day_count == "ACT/365F":
        return (end - start).days / 365.0

    cursor = start
    result = 0.0
    while cursor < end:
        next_year = date(cursor.year + 1, 1, 1)
        boundary = min(end, next_year)
        days_in_year = 366 if _is_leap(cursor.year) else 365
        result += (boundary - cursor).days / days_in_year
        cursor = boundary
    return result


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def total_return_from_rate(
    annual_rate: float,
    years: float,
    *,
    compounding: str,
) -> float:
    """Convert an annual decimal rate into a total return for an exact period."""

    rate = float(annual_rate)
    horizon = float(years)
    if not math.isfinite(rate) or not math.isfinite(horizon) or horizon <= 0:
        raise ValueError("rate and horizon must be finite, with a positive horizon")
    if compounding not in _COMPOUNDING:
        raise ValueError(f"unsupported compounding: {compounding}")
    if compounding == "annual":
        if rate <= -1.0:
            raise ValueError("annual compounding requires annual_rate > -1")
        return float((1.0 + rate) ** horizon - 1.0)
    if compounding == "continuous":
        return float(math.exp(rate * horizon) - 1.0)
    return float(rate * horizon)


def exact_adjusted_total_return(
    adjusted_prices: pd.Series | pd.DataFrame,
    start_date: object,
    end_date: object,
) -> float:
    """Compound only exact endpoint observations from a canonical adjusted series."""

    start = _as_date(start_date, "start_date")
    end = _as_date(end_date, "end_date")
    if isinstance(adjusted_prices, pd.DataFrame):
        frame = adjusted_prices.copy()
        if "date" not in frame.columns:
            raise ValueError("adjusted price frame requires date")
        value_column = next(
            (name for name in ("total_return_index", "adjusted_close") if name in frame.columns),
            None,
        )
        if value_column is None:
            raise ValueError("adjusted price frame requires total_return_index or adjusted_close")
        dates = pd.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed")
        values = pd.to_numeric(frame[value_column], errors="coerce")
        frame = pd.DataFrame({"date": dates.dt.date, "value": values})
    elif isinstance(adjusted_prices, pd.Series):
        dates = pd.to_datetime(adjusted_prices.index, errors="coerce", utc=True, format="mixed")
        values = pd.to_numeric(adjusted_prices, errors="coerce")
        frame = pd.DataFrame({"date": dates.date, "value": values.to_numpy()})
    else:
        raise TypeError("adjusted_prices must be a Series or DataFrame")
    frame = frame.dropna(subset=["date", "value"])
    if frame.empty:
        raise ValueError("adjusted price evidence is unavailable")
    if frame["date"].duplicated().any():
        raise ValueError("adjusted price evidence has conflicting dates")
    selected = frame.set_index("date")["value"]
    if start not in selected.index or end not in selected.index:
        raise ValueError("exact adjusted-return period is unavailable")
    first = float(selected.loc[start])
    last = float(selected.loc[end])
    if not math.isfinite(first) or not math.isfinite(last) or first <= 0 or last <= 0:
        raise ValueError("adjusted prices must be finite and positive")
    return last / first - 1.0


@dataclass(frozen=True)
class CashComparisonResult:
    status: str
    instrument_return: float | None = None
    cash_return: float | None = None
    excess_over_cash: float | None = None
    currency: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    horizon_years: float | None = None
    rate: float | None = None
    compounding: str | None = None
    day_count: str | None = None
    reinvestment: str | None = None
    vintage: str | None = None
    effective_at: str | None = None
    available_at: str | None = None
    source_id: str | None = None
    source_checksum: str | None = None
    source_terms: str | None = None
    methodology: str | None = None
    mapping_methodology: str | None = None
    curve_id: str | None = None
    curve_version: str | None = None
    curve_type: str | None = None
    fallback: bool | None = None
    fallback_from: str | None = None
    interpolation: str | None = None
    freshness: str | None = None
    decision_time: str | None = None
    knowledge_cutoff: str | None = None
    inflation_context: object = None
    reason: str | None = None
    execution_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def build_cash_comparison(
    *,
    adjusted_prices: pd.Series | pd.DataFrame,
    start_date: object,
    end_date: object,
    instrument_currency: str,
    cash_evidence: Mapping[str, object],
    decision_time: object,
    knowledge_cutoff: object | None = None,
    inflation_context: Mapping[str, object] | None = None,
) -> CashComparisonResult:
    """Compare an exact adjusted-return period with eligible spot cash evidence."""

    start = _as_date(start_date, "start_date")
    end = _as_date(end_date, "end_date")
    start_cutoff = _utc_timestamp(period_start_knowledge_cutoff(start), "start_date")
    cutoff = _utc_timestamp(
        knowledge_cutoff if knowledge_cutoff is not None else start_cutoff,
        "knowledge_cutoff",
    )
    if cutoff > start_cutoff:
        return _unavailable(
            "cash knowledge cutoff cannot be after the comparison period start",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            knowledge_cutoff=cutoff.isoformat(),
        )
    currency = str(instrument_currency or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        return _unavailable("instrument currency is unavailable", currency=currency or None)
    if not isinstance(cash_evidence, Mapping) or cash_evidence.get("status") != "available":
        return _unavailable(str(cash_evidence.get("reason", "cash evidence is unavailable")) if isinstance(cash_evidence, Mapping) else "cash evidence is unavailable", currency=currency, start_date=start.isoformat(), end_date=end.isoformat())
    evidence_currency = str(cash_evidence.get("currency") or "").upper()
    day_count = cash_evidence.get("day_count")
    horizon = None
    try:
        if evidence_currency != currency:
            return _unavailable("cash currency does not match instrument currency", currency=currency)
        if cash_evidence.get("curve_type") != "spot":
            return _unavailable("cash comparison requires spot-curve evidence", currency=currency)
        freshness = cash_evidence.get("freshness_status") or cash_evidence.get("freshness")
        if freshness not in _FRESHNESS:
            return _unavailable("cash evidence freshness is unavailable or stale", currency=currency)
        required = (
            "rate",
            "tenor_years",
            "compounding",
            "day_count",
            "reinvestment",
            "vintage",
            "effective_at",
            "available_at",
            "source_id",
            "source_checksum",
            "source_terms",
            "methodology",
        )
        if any(cash_evidence.get(name) in (None, "") for name in required):
            return _unavailable("cash convention, reinvestment, freshness or lineage is unavailable", currency=currency)
        if day_count not in _DAY_COUNTS:
            return _unavailable("cash day-count convention is unsupported", currency=currency)
        horizon = year_fraction(start, end, str(day_count))
        observed_horizon = float(cash_evidence.get("tenor_years"))
        if not math.isclose(observed_horizon, horizon, rel_tol=0.0, abs_tol=1e-12):
            return _unavailable("cash horizon does not exactly match the comparison period", currency=currency)
        if cash_evidence.get("compounding") not in _COMPOUNDING:
            return _unavailable("cash compounding convention is unsupported", currency=currency)
        available_at = _utc_timestamp(cash_evidence.get("available_at"), "available_at")
        decision = _utc_timestamp(decision_time, "decision_time")
        effective_at = _utc_timestamp(cash_evidence.get("effective_at"), "effective_at")
        if decision < cutoff:
            return _unavailable("decision time precedes the cash knowledge cutoff", currency=currency)
        if available_at > cutoff or effective_at > start_cutoff:
            return _unavailable("cash evidence is not point-in-time eligible", currency=currency)
        checksum = str(cash_evidence["source_checksum"])
        if len(checksum) != 64 or any(character not in "0123456789abcdefABCDEF" for character in checksum):
            return _unavailable("cash evidence checksum is malformed", currency=currency)
        instrument_return = exact_adjusted_total_return(adjusted_prices, start, end)
        cash_return = total_return_from_rate(
            float(cash_evidence["rate"]),
            horizon,
            compounding=str(cash_evidence["compounding"]),
        )
    except (ArithmeticError, TypeError, ValueError, OverflowError) as exc:
        return _unavailable(f"cash comparison unavailable: {str(exc)}", currency=currency, start_date=start.isoformat(), end_date=end.isoformat())
    return CashComparisonResult(
        status="available",
        instrument_return=instrument_return,
        cash_return=cash_return,
        excess_over_cash=instrument_return - cash_return,
        currency=currency,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        horizon_years=horizon,
        rate=float(cash_evidence["rate"]),
        compounding=str(cash_evidence["compounding"]),
        day_count=str(day_count),
        reinvestment=str(cash_evidence["reinvestment"]),
        vintage=str(cash_evidence["vintage"]),
        effective_at=str(cash_evidence["effective_at"]),
        available_at=str(cash_evidence["available_at"]),
        source_id=str(cash_evidence["source_id"]),
        source_checksum=str(cash_evidence["source_checksum"]),
        source_terms=str(cash_evidence["source_terms"]),
        methodology=str(cash_evidence["methodology"]),
        mapping_methodology=str(cash_evidence["mapping_methodology"]) if cash_evidence.get("mapping_methodology") is not None else None,
        curve_id=str(cash_evidence["curve_id"]) if cash_evidence.get("curve_id") is not None else None,
        curve_version=str(cash_evidence["curve_version"]) if cash_evidence.get("curve_version") is not None else None,
        curve_type=str(cash_evidence["curve_type"]),
        fallback=bool(cash_evidence.get("fallback")) if cash_evidence.get("fallback") is not None else None,
        fallback_from=str(cash_evidence["fallback_from"]) if cash_evidence.get("fallback_from") is not None else None,
        interpolation=str(cash_evidence["interpolation"]) if cash_evidence.get("interpolation") is not None else None,
        freshness=str(cash_evidence.get("freshness_status") or cash_evidence.get("freshness")),
        decision_time=str(decision_time),
        knowledge_cutoff=cutoff.isoformat(),
        inflation_context=dict(inflation_context) if inflation_context is not None else None,
    )


def _unavailable(reason: str, **fields: object) -> CashComparisonResult:
    return CashComparisonResult(status="unavailable", reason=reason, **fields)


# The small aliases keep the pure financial vocabulary discoverable to callers.
calculate_cash_total_return = total_return_from_rate
cash_year_fraction = year_fraction


__all__ = [
    "CashComparisonResult",
    "build_cash_comparison",
    "calculate_cash_total_return",
    "cash_year_fraction",
    "exact_adjusted_total_return",
    "period_start_knowledge_cutoff",
    "total_return_from_rate",
    "year_fraction",
]
