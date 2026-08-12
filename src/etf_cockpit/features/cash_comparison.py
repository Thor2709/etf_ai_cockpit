"""Currency- and vintage-matched descriptive cash comparisons.

This module is deliberately pure.  It consumes a canonical adjusted/total-
return price series and a then-known official spot-curve selection; it never
changes scores, rankings, gates, forecasts or execution authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import math
from numbers import Integral, Real
from collections.abc import Mapping

import pandas as pd


_DAY_COUNTS = {"ACT/360", "ACT/365F", "ACT/ACT-ISDA"}
_COMPOUNDING = {"annual", "continuous", "simple"}
_FRESHNESS = {"fresh"}
_REINVESTMENT = {"reinvested_income"}


def _positive_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError("cash curve revision is invalid")
    return int(value)


def _has_nonblank_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_date(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date or strict YYYY-MM-DD string")
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError(f"{field_name} must be a date or strict YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a date or strict YYYY-MM-DD string") from exc


def period_start_knowledge_cutoff(start_date: object) -> str:
    """Represent a date-only comparison cutoff as UTC midnight, without session inference."""

    start = _as_date(start_date, "start_date")
    return f"{start.isoformat()}T00:00:00+00:00"


def adjusted_endpoint_available_at(end_date: object) -> str:
    """Return the conservative availability time for a date-only adjusted endpoint."""

    end = _as_date(end_date, "end_date")
    return f"{(end + timedelta(days=1)).isoformat()}T00:00:00+00:00"


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


def validated_adjusted_price_frame(
    adjusted_prices: pd.Series | pd.DataFrame,
) -> pd.DataFrame:
    """Validate every raw adjusted-price row before normalising its fields."""

    if isinstance(adjusted_prices, pd.DataFrame):
        if "date" not in adjusted_prices.columns:
            raise ValueError("adjusted price frame requires date")
        value_column = next(
            (name for name in ("total_return_index", "adjusted_close") if name in adjusted_prices.columns),
            None,
        )
        if value_column is None:
            raise ValueError("adjusted price frame requires total_return_index or adjusted_close")
        raw_dates = adjusted_prices["date"].tolist()
        raw_values = adjusted_prices[value_column].tolist()
    elif isinstance(adjusted_prices, pd.Series):
        raw_dates = list(adjusted_prices.index)
        raw_values = adjusted_prices.tolist()
    else:
        raise TypeError("adjusted_prices must be a Series or DataFrame")

    dates: list[date] = []
    values: list[float] = []
    for raw_date, raw_value in zip(raw_dates, raw_values, strict=True):
        if isinstance(raw_date, bool) or not isinstance(raw_date, (date, datetime, pd.Timestamp, str)):
            raise ValueError("adjusted price date is invalid")
        try:
            parsed_date = pd.Timestamp(raw_date)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("adjusted price date is invalid") from exc
        if pd.isna(parsed_date):
            raise ValueError("adjusted price date is invalid")
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise ValueError("adjusted price value must be numeric")
        try:
            parsed_value = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("adjusted price value must be numeric") from exc
        if not math.isfinite(parsed_value):
            raise ValueError("adjusted price value must be finite")
        dates.append(parsed_date.date())
        values.append(parsed_value)

    if not dates:
        raise ValueError("adjusted price evidence is unavailable")
    if len(set(dates)) != len(dates):
        raise ValueError("adjusted price evidence has conflicting dates")
    if any(value <= 0 for value in values):
        raise ValueError("adjusted prices must be finite and positive")
    return pd.DataFrame({"date": dates, "value": values})


def total_return_from_rate(
    annual_rate: float,
    years: float,
    *,
    compounding: str,
) -> float:
    """Convert an annual decimal rate into a total return for an exact period."""

    rate = _finite_float(annual_rate, "annual_rate")
    horizon = _finite_float(years, "years")
    if horizon <= 0:
        raise ValueError("rate and horizon must be finite, with a positive horizon")
    if compounding not in _COMPOUNDING:
        raise ValueError(f"unsupported compounding: {compounding}")
    if compounding == "annual":
        if rate <= -1.0:
            raise ValueError("annual compounding requires annual_rate > -1")
        result = float((1.0 + rate) ** horizon - 1.0)
    elif compounding == "continuous":
        result = float(math.exp(rate * horizon) - 1.0)
    else:
        if 1.0 + rate * horizon <= 0.0:
            raise ValueError("simple compounding requires 1 + annual_rate * horizon > 0")
        result = float(rate * horizon)
    if not math.isfinite(result) or result <= -1.0:
        raise ValueError("cash total return must be finite and greater than -1")
    return result


def exact_adjusted_total_return(
    adjusted_prices: pd.Series | pd.DataFrame,
    start_date: object,
    end_date: object,
) -> float:
    """Compound only exact endpoint observations from a canonical adjusted series."""

    start = _as_date(start_date, "start_date")
    end = _as_date(end_date, "end_date")
    frame = validated_adjusted_price_frame(adjusted_prices)
    selected = frame.set_index("date")["value"]
    if start not in selected.index or end not in selected.index:
        raise ValueError("exact adjusted-return period is unavailable")
    first = float(selected.loc[start])
    last = float(selected.loc[end])
    result = last / first - 1.0
    if not math.isfinite(result) or result <= -1.0:
        raise ValueError("instrument total return must be finite and greater than -1")
    return result


@dataclass(frozen=True)
class CashComparisonResult:
    status: str
    instrument_return: float | None = None
    cash_return: float | None = None
    excess_over_cash: float | None = None
    currency: str | None = None
    unit: str | None = None
    dataset_kind: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    horizon_years: float | None = None
    rate: float | None = None
    compounding: str | None = None
    day_count: str | None = None
    reinvestment: str | None = None
    vintage: str | None = None
    effective_at: str | None = None
    published_at: str | None = None
    available_at: str | None = None
    source_id: str | None = None
    source_authority: str | None = None
    source_checksum: str | None = None
    source_terms: str | None = None
    methodology: str | None = None
    mapping_methodology: str | None = None
    curve_id: str | None = None
    curve_version: str | None = None
    curve_revision: int | None = None
    curve_type: str | None = None
    extrapolation_allowed: bool | None = None
    fallback: bool | None = None
    fallback_from: str | None = None
    interpolation: str | None = None
    freshness: str | None = None
    freshness_status: str | None = None
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
    if cutoff != start_cutoff:
        return _unavailable(
            "cash knowledge cutoff must equal the comparison period start",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            knowledge_cutoff=cutoff.isoformat(),
        )
    currency = str(instrument_currency or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        return _unavailable("instrument currency is unavailable", currency=currency or None)
    if (
        not isinstance(cash_evidence, Mapping)
        or not isinstance(cash_evidence.get("status"), str)
        or cash_evidence.get("status") != "available"
    ):
        return _unavailable(str(cash_evidence.get("reason", "cash evidence is unavailable")) if isinstance(cash_evidence, Mapping) else "cash evidence is unavailable", currency=currency, start_date=start.isoformat(), end_date=end.isoformat())
    evidence_currency = str(cash_evidence.get("currency") or "").upper()
    day_count = cash_evidence.get("day_count")
    horizon = None
    try:
        if cash_evidence.get("execution_allowed") is not False:
            return _unavailable("cash evidence cannot grant execution authority", currency=currency)
        if evidence_currency != currency:
            return _unavailable("cash currency does not match instrument currency", currency=currency)
        if cash_evidence.get("dataset_kind") != "risk_free":
            return _unavailable("cash comparison requires risk_free curve evidence", currency=currency)
        if cash_evidence.get("unit") != "decimal":
            return _unavailable("cash comparison requires decimal rate evidence", currency=currency)
        if cash_evidence.get("curve_type") != "spot":
            return _unavailable("cash comparison requires spot-curve evidence", currency=currency)
        if cash_evidence.get("source_authority") not in {
            "official_regulator",
            "official_public_file",
        }:
            return _unavailable("cash evidence provenance is not official", currency=currency)
        freshness = cash_evidence.get("freshness")
        freshness_status = cash_evidence.get("freshness_status")
        if (
            freshness not in _FRESHNESS
            or freshness_status not in _FRESHNESS
            or freshness != freshness_status
        ):
            return _unavailable("cash evidence freshness is unavailable or stale", currency=currency)
        required = (
            "rate",
            "tenor_years",
            "compounding",
            "day_count",
            "reinvestment",
            "vintage",
            "effective_at",
            "published_at",
            "available_at",
            "source_id",
            "source_authority",
            "source_checksum",
            "dataset_kind",
            "unit",
            "execution_allowed",
            "source_terms",
            "methodology",
            "mapping_methodology",
            "curve_id",
            "curve_version",
            "curve_revision",
            "interpolation",
            "extrapolation_allowed",
            "fallback",
        )
        if any(cash_evidence.get(name) in (None, "") for name in required):
            return _unavailable("cash convention, reinvestment, freshness or lineage is unavailable", currency=currency)
        required_lineage_text = (
            "compounding",
            "day_count",
            "reinvestment",
            "vintage",
            "effective_at",
            "published_at",
            "available_at",
            "source_id",
            "source_authority",
            "source_checksum",
            "source_terms",
            "methodology",
            "mapping_methodology",
            "curve_id",
            "curve_version",
            "interpolation",
        )
        if any(
            not _has_nonblank_text(cash_evidence.get(name))
            for name in required_lineage_text
        ):
            return _unavailable(
                "cash convention, reinvestment, freshness or lineage is unavailable",
                currency=currency,
            )
        if day_count not in _DAY_COUNTS:
            return _unavailable("cash day-count convention is unsupported", currency=currency)
        horizon = year_fraction(start, end, str(day_count))
        observed_horizon = _finite_float(
            cash_evidence.get("tenor_years"), "tenor_years"
        )
        if not math.isclose(observed_horizon, horizon, rel_tol=0.0, abs_tol=1e-12):
            return _unavailable("cash horizon does not exactly match the comparison period", currency=currency)
        if cash_evidence.get("compounding") not in _COMPOUNDING:
            return _unavailable("cash compounding convention is unsupported", currency=currency)
        if cash_evidence.get("reinvestment") not in _REINVESTMENT:
            return _unavailable("cash reinvestment convention is unsupported", currency=currency)
        available_at = _utc_timestamp(cash_evidence.get("available_at"), "available_at")
        published_at = _utc_timestamp(
            cash_evidence.get("published_at"), "published_at"
        )
        vintage = _utc_timestamp(cash_evidence.get("vintage"), "vintage")
        decision = _utc_timestamp(decision_time, "decision_time")
        effective_at = _utc_timestamp(cash_evidence.get("effective_at"), "effective_at")
        endpoint_available = _utc_timestamp(
            adjusted_endpoint_available_at(end), "adjusted endpoint availability"
        )
        if decision < cutoff:
            return _unavailable("decision time precedes the cash knowledge cutoff", currency=currency)
        if decision < endpoint_available:
            return _unavailable("adjusted end-price evidence is not yet available", currency=currency)
        if vintage != available_at:
            return _unavailable("cash vintage contradicts available_at", currency=currency)
        if effective_at > available_at:
            return _unavailable("cash evidence effective_at is after available_at", currency=currency)
        if published_at > available_at:
            return _unavailable("cash evidence published_at is after available_at", currency=currency)
        if vintage > cutoff or available_at > cutoff or published_at > cutoff or effective_at > start_cutoff:
            return _unavailable("cash evidence is not point-in-time eligible", currency=currency)
        if cash_evidence.get("extrapolation_allowed") is not False:
            return _unavailable("cash curve extrapolation policy is unavailable or unsupported", currency=currency)
        if cash_evidence.get("interpolation") not in {"linear", "none"}:
            return _unavailable("cash curve interpolation policy is unsupported", currency=currency)
        if not isinstance(cash_evidence.get("fallback"), bool):
            return _unavailable("cash curve fallback identity is unavailable", currency=currency)
        if cash_evidence.get("fallback") and not _has_nonblank_text(
            cash_evidence.get("fallback_from")
        ):
            return _unavailable("cash curve fallback reason is unavailable", currency=currency)
        curve_revision = _positive_revision(cash_evidence.get("curve_revision"))
        checksum = str(cash_evidence["source_checksum"])
        if len(checksum) != 64 or any(character not in "0123456789abcdefABCDEF" for character in checksum):
            return _unavailable("cash evidence checksum is malformed", currency=currency)
        instrument_return = exact_adjusted_total_return(adjusted_prices, start, end)
        cash_rate = _finite_float(cash_evidence.get("rate"), "rate")
        cash_return = total_return_from_rate(
            cash_rate,
            horizon,
            compounding=str(cash_evidence["compounding"]),
        )
    except (ArithmeticError, TypeError, ValueError, OverflowError) as exc:
        return _unavailable(f"cash comparison unavailable: {str(exc)}", currency=currency, start_date=start.isoformat(), end_date=end.isoformat())
    result = CashComparisonResult(
        status="available",
        instrument_return=instrument_return,
        cash_return=cash_return,
        excess_over_cash=instrument_return - cash_return,
        currency=currency,
        unit="decimal",
        dataset_kind="risk_free",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        horizon_years=horizon,
        rate=cash_rate,
        compounding=str(cash_evidence["compounding"]),
        day_count=str(day_count),
        reinvestment=str(cash_evidence["reinvestment"]),
        vintage=vintage.isoformat(),
        effective_at=effective_at.isoformat(),
        published_at=published_at.isoformat(),
        available_at=available_at.isoformat(),
        source_id=str(cash_evidence["source_id"]),
        source_authority=str(cash_evidence["source_authority"]),
        source_checksum=str(cash_evidence["source_checksum"]),
        source_terms=str(cash_evidence["source_terms"]),
        methodology=str(cash_evidence["methodology"]),
        mapping_methodology=str(cash_evidence["mapping_methodology"]) if cash_evidence.get("mapping_methodology") is not None else None,
        curve_id=str(cash_evidence["curve_id"]) if cash_evidence.get("curve_id") is not None else None,
        curve_version=str(cash_evidence["curve_version"]) if cash_evidence.get("curve_version") is not None else None,
        curve_revision=curve_revision,
        curve_type=str(cash_evidence["curve_type"]),
        extrapolation_allowed=False,
        fallback=bool(cash_evidence.get("fallback")) if cash_evidence.get("fallback") is not None else None,
        fallback_from=str(cash_evidence["fallback_from"]) if cash_evidence.get("fallback_from") is not None else None,
        interpolation=str(cash_evidence["interpolation"]) if cash_evidence.get("interpolation") is not None else None,
        freshness=str(freshness),
        freshness_status=str(freshness_status),
        decision_time=decision.isoformat(),
        knowledge_cutoff=cutoff.isoformat(),
        inflation_context=dict(inflation_context) if inflation_context is not None else None,
    )
    return validate_cash_comparison_result(result, expected_currency=currency)


def _unavailable(reason: str, **fields: object) -> CashComparisonResult:
    return CashComparisonResult(status="unavailable", reason=reason, **fields)


def validate_cash_comparison_result(
    value: Mapping[str, object] | CashComparisonResult | None,
    *,
    expected_currency: str | None = None,
) -> CashComparisonResult:
    """Validate and sanitize serialized descriptive cash evidence for generic consumers."""

    raw: Mapping[str, object]
    if isinstance(value, CashComparisonResult):
        raw = value.as_dict()
    elif isinstance(value, Mapping):
        raw = value
    else:
        return _unavailable("Cash comparison unavailable; no result was supplied.")
    status = raw.get("status")
    if not isinstance(status, str) or status != "available":
        reason = raw.get("reason")
        return _unavailable(
            reason if isinstance(reason, str) and reason.strip() else "Cash comparison is unavailable."
        )
    try:
        if raw.get("execution_allowed") is not False:
            raise ValueError("cash comparison cannot grant execution authority")
        if raw.get("dataset_kind") != "risk_free":
            raise ValueError("cash comparison requires risk_free curve evidence")
        if raw.get("unit") != "decimal":
            raise ValueError("cash comparison requires decimal rate evidence")
        required_text = (
            "currency",
            "start_date",
            "end_date",
            "compounding",
            "day_count",
            "reinvestment",
            "vintage",
            "effective_at",
            "published_at",
            "available_at",
            "source_id",
            "source_authority",
            "source_checksum",
            "source_terms",
            "methodology",
            "mapping_methodology",
            "curve_id",
            "curve_version",
            "curve_type",
            "interpolation",
            "freshness",
            "freshness_status",
            "decision_time",
            "knowledge_cutoff",
        )
        if any(not _has_nonblank_text(raw.get(name)) for name in required_text):
            raise ValueError("cash comparison lineage or convention is incomplete")
        currency = str(raw["currency"]).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("cash comparison currency is invalid")
        if expected_currency is not None and currency != str(expected_currency).strip().upper():
            raise ValueError("cash currency does not match instrument currency")
        start = _as_date(raw["start_date"], "start_date")
        end = _as_date(raw["end_date"], "end_date")
        day_count = str(raw["day_count"])
        compounding = str(raw["compounding"])
        if day_count not in _DAY_COUNTS or compounding not in _COMPOUNDING:
            raise ValueError("cash comparison convention is unsupported")
        if raw.get("reinvestment") not in _REINVESTMENT:
            raise ValueError("cash reinvestment convention is unsupported")
        horizon = year_fraction(start, end, day_count)
        observed_horizon = _finite_float(raw.get("horizon_years"), "horizon_years")
        if not math.isclose(observed_horizon, horizon, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("cash comparison horizon is inconsistent")
        instrument_return = _finite_float(raw.get("instrument_return"), "instrument_return")
        if instrument_return <= -1.0:
            raise ValueError("instrument total return must be greater than -1")
        rate = _finite_float(raw.get("rate"), "rate")
        observed_cash_return = _finite_float(raw.get("cash_return"), "cash_return")
        observed_excess = _finite_float(raw.get("excess_over_cash"), "excess_over_cash")
        cash_return = total_return_from_rate(rate, horizon, compounding=compounding)
        excess = instrument_return - cash_return
        if not math.isclose(observed_cash_return, cash_return, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("cash return is inconsistent with rate and horizon")
        if not math.isclose(observed_excess, excess, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("excess over cash is inconsistent")
        vintage = _utc_timestamp(raw["vintage"], "vintage")
        effective = _utc_timestamp(raw["effective_at"], "effective_at")
        published = _utc_timestamp(raw["published_at"], "published_at")
        available = _utc_timestamp(raw["available_at"], "available_at")
        decision = _utc_timestamp(raw["decision_time"], "decision_time")
        cutoff = _utc_timestamp(raw["knowledge_cutoff"], "knowledge_cutoff")
        expected_cutoff = _utc_timestamp(period_start_knowledge_cutoff(start), "period start")
        endpoint_available = _utc_timestamp(
            adjusted_endpoint_available_at(end), "adjusted endpoint availability"
        )
        if cutoff != expected_cutoff:
            raise ValueError("cash knowledge cutoff is inconsistent with period start")
        if vintage != available:
            raise ValueError("cash vintage contradicts available_at")
        if effective > available:
            raise ValueError("cash evidence effective_at is after available_at")
        if published > available:
            raise ValueError("cash evidence published_at is after available_at")
        if vintage > cutoff or available > cutoff or published > cutoff or effective > cutoff:
            raise ValueError("cash evidence is not point-in-time eligible")
        if decision < endpoint_available or decision < cutoff:
            raise ValueError("comparison decision precedes required evidence")
        freshness = str(raw["freshness"])
        freshness_status = str(raw["freshness_status"])
        if freshness != "fresh" or freshness_status != "fresh" or freshness != freshness_status:
            raise ValueError("cash comparison freshness is stale or conflicted")
        if raw["curve_type"] != "spot":
            raise ValueError("cash comparison requires spot-curve evidence")
        if raw["source_authority"] not in {
            "official_regulator",
            "official_public_file",
        }:
            raise ValueError("cash comparison provenance is not official")
        if raw.get("interpolation") not in {"linear", "none"}:
            raise ValueError("cash curve interpolation policy is unsupported")
        if raw.get("extrapolation_allowed") is not False:
            raise ValueError("cash curve extrapolation is unsupported")
        if not isinstance(raw.get("fallback"), bool):
            raise ValueError("cash curve fallback identity is unavailable")
        if raw.get("fallback") and not _has_nonblank_text(raw.get("fallback_from")):
            raise ValueError("cash curve fallback reason is unavailable")
        revision = _positive_revision(raw.get("curve_revision"))
        checksum = str(raw["source_checksum"])
        if len(checksum) != 64 or any(character not in "0123456789abcdefABCDEF" for character in checksum):
            raise ValueError("cash evidence checksum is malformed")
    except (ArithmeticError, TypeError, ValueError, OverflowError) as exc:
        return _unavailable(f"Cash comparison unavailable; {exc}.")
    return CashComparisonResult(
        status="available",
        instrument_return=instrument_return,
        cash_return=cash_return,
        excess_over_cash=excess,
        currency=currency,
        unit="decimal",
        dataset_kind="risk_free",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        horizon_years=horizon,
        rate=rate,
        compounding=compounding,
        day_count=day_count,
        reinvestment=str(raw["reinvestment"]),
        vintage=vintage.isoformat(),
        effective_at=effective.isoformat(),
        published_at=published.isoformat(),
        available_at=available.isoformat(),
        source_id=str(raw["source_id"]),
        source_authority=str(raw["source_authority"]),
        source_checksum=checksum.lower(),
        source_terms=str(raw["source_terms"]),
        methodology=str(raw["methodology"]),
        mapping_methodology=str(raw["mapping_methodology"]),
        curve_id=str(raw["curve_id"]),
        curve_version=str(raw["curve_version"]),
        curve_revision=revision,
        curve_type="spot",
        extrapolation_allowed=False,
        fallback=bool(raw["fallback"]),
        fallback_from=str(raw["fallback_from"]) if raw.get("fallback_from") is not None else None,
        interpolation=str(raw["interpolation"]),
        freshness="fresh",
        freshness_status="fresh",
        decision_time=decision.isoformat(),
        knowledge_cutoff=cutoff.isoformat(),
        inflation_context=raw.get("inflation_context"),
        execution_allowed=False,
    )


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def cash_comparison_from_projection(value: Mapping[str, object]) -> dict[str, object]:
    """Restore a serialized result from canonical scoreboard/attribution field names."""

    keys = {
        "status": "cash_comparison_status",
        "reason": "cash_comparison_reason",
        "instrument_return": "cash_instrument_return",
        "cash_return": "cash_return",
        "excess_over_cash": "excess_over_cash",
        "currency": "cash_currency",
        "unit": "cash_unit",
        "dataset_kind": "cash_dataset_kind",
        "start_date": "cash_start_date",
        "end_date": "cash_end_date",
        "horizon_years": "cash_horizon_years",
        "rate": "cash_rate",
        "vintage": "cash_vintage",
        "source_id": "cash_source_id",
        "source_authority": "cash_source_authority",
        "source_checksum": "cash_source_checksum",
        "source_terms": "cash_source_terms",
        "methodology": "cash_methodology",
        "mapping_methodology": "cash_mapping_methodology",
        "day_count": "cash_day_count",
        "compounding": "cash_compounding",
        "reinvestment": "cash_reinvestment",
        "effective_at": "cash_effective_at",
        "published_at": "cash_published_at",
        "available_at": "cash_available_at",
        "curve_id": "cash_curve_id",
        "curve_version": "cash_curve_version",
        "curve_revision": "cash_curve_revision",
        "curve_type": "cash_curve_type",
        "extrapolation_allowed": "cash_extrapolation_allowed",
        "fallback": "cash_fallback",
        "fallback_from": "cash_fallback_from",
        "interpolation": "cash_interpolation",
        "freshness": "cash_freshness",
        "freshness_status": "cash_freshness_status",
        "decision_time": "cash_decision_time",
        "knowledge_cutoff": "cash_knowledge_cutoff",
        "inflation_context": "inflation_context",
        "execution_allowed": "execution_allowed",
    }
    return {field: value.get(projected) for field, projected in keys.items()}


def cash_comparison_to_projection(
    value: Mapping[str, object] | CashComparisonResult | None,
    *,
    expected_currency: str | None = None,
) -> dict[str, object]:
    """Return only validated cash fields under canonical projection names."""

    cash = validate_cash_comparison_result(
        value, expected_currency=expected_currency
    ).as_dict()
    projected = {
        "cash_comparison_status": cash["status"],
        "cash_comparison_reason": cash.get("reason"),
        "cash_instrument_return": cash.get("instrument_return"),
        "cash_return": cash.get("cash_return"),
        "excess_over_cash": cash.get("excess_over_cash"),
        "cash_currency": cash.get("currency"),
        "cash_unit": cash.get("unit"),
        "cash_dataset_kind": cash.get("dataset_kind"),
        "cash_start_date": cash.get("start_date"),
        "cash_end_date": cash.get("end_date"),
        "cash_horizon_years": cash.get("horizon_years"),
        "cash_rate": cash.get("rate"),
        "cash_vintage": cash.get("vintage"),
        "cash_source_id": cash.get("source_id"),
        "cash_source_authority": cash.get("source_authority"),
        "cash_source_checksum": cash.get("source_checksum"),
        "cash_source_terms": cash.get("source_terms"),
        "cash_methodology": cash.get("methodology"),
        "cash_mapping_methodology": cash.get("mapping_methodology"),
        "cash_day_count": cash.get("day_count"),
        "cash_compounding": cash.get("compounding"),
        "cash_reinvestment": cash.get("reinvestment"),
        "cash_effective_at": cash.get("effective_at"),
        "cash_published_at": cash.get("published_at"),
        "cash_available_at": cash.get("available_at"),
        "cash_curve_id": cash.get("curve_id"),
        "cash_curve_version": cash.get("curve_version"),
        "cash_curve_revision": cash.get("curve_revision"),
        "cash_curve_type": cash.get("curve_type"),
        "cash_extrapolation_allowed": cash.get("extrapolation_allowed"),
        "cash_fallback": cash.get("fallback"),
        "cash_fallback_from": cash.get("fallback_from"),
        "cash_interpolation": cash.get("interpolation"),
        "cash_freshness": cash.get("freshness"),
        "cash_freshness_status": cash.get("freshness_status"),
        "cash_decision_time": cash.get("decision_time"),
        "cash_knowledge_cutoff": cash.get("knowledge_cutoff"),
        "inflation_context": cash.get("inflation_context"),
        "execution_allowed": False,
    }
    return projected


# The small aliases keep the pure financial vocabulary discoverable to callers.
calculate_cash_total_return = total_return_from_rate
cash_year_fraction = year_fraction


__all__ = [
    "CashComparisonResult",
    "adjusted_endpoint_available_at",
    "build_cash_comparison",
    "calculate_cash_total_return",
    "cash_comparison_from_projection",
    "cash_comparison_to_projection",
    "cash_year_fraction",
    "exact_adjusted_total_return",
    "period_start_knowledge_cutoff",
    "total_return_from_rate",
    "year_fraction",
    "validate_cash_comparison_result",
]
