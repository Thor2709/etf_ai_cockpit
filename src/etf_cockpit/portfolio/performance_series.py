"""Build selectable portfolio performance series from saved daily snapshots.

Saved portfolio valuation amounts have no currency column, so this module
follows the valuation contract and treats them as EUR. Other output currencies
are translated at each snapshot date through the local point-in-time FX path.
Missing valuations and FX rates remain explicit; no value is interpolated.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import Literal

import pandas as pd

from etf_cockpit.data.fx_data import build_fx_rate_snapshot, fx_cross_rate
from etf_cockpit.portfolio.valuation import (
    SNAPSHOT_COLUMNS,
    calculate_money_weighted_return,
    link_time_weighted_return,
)

PerformanceMetric = Literal[
    "portfolio_value",
    "net_invested_capital",
    "investment_pnl",
    "twr_index",
    "twr_return",
    "mwr_return",
    "drawdown",
    "cash_value",
    "net_contributions",
    "income",
    "fees_tax",
    "fx",
    "benchmark",
]
DateRange = Literal["inception", "YTD", "1M", "3M", "6M", "1Y", "3Y", "5Y", "custom"]
Aggregation = Literal["day", "week", "month", "quarter", "year"]

PERFORMANCE_METRICS: tuple[str, ...] = (
    "portfolio_value",
    "net_invested_capital",
    "investment_pnl",
    "twr_index",
    "twr_return",
    "mwr_return",
    "drawdown",
    "cash_value",
    "net_contributions",
    "income",
    "fees_tax",
    "fx",
    "benchmark",
)
PERFORMANCE_RANGES: tuple[str, ...] = ("inception", "YTD", "1M", "3M", "6M", "1Y", "3Y", "5Y", "custom")
PERFORMANCE_AGGREGATIONS: tuple[str, ...] = ("day", "week", "month", "quarter", "year")

_CURRENCY_METRICS = frozenset(
    {
        "portfolio_value",
        "net_invested_capital",
        "investment_pnl",
        "cash_value",
        "net_contributions",
        "income",
        "fees_tax",
        "fx",
    }
)
_UNAVAILABLE_METRICS = {
    "benchmark": "Benchmark return observations are not stored in portfolio valuation snapshots.",
}
_FREQUENCIES = {"week": "W-SUN", "month": "M", "quarter": "Q-DEC", "year": "Y-DEC"}


@dataclass(frozen=True)
class PerformancePoint:
    """One value and its measurement quality and saved-snapshot lineage."""

    period_start: date
    period_end: date
    value: float | None
    partial: bool
    quality: str
    status: str
    reason: str | None
    source_snapshot: str | None


@dataclass(frozen=True)
class PerformanceSeries:
    """Typed output contract for one selected portfolio chart series."""

    metric: str
    unit: str
    currency: str
    period_start: date | None
    period_end: date | None
    partial: bool
    quality: str
    status: str
    reason: str | None
    date_range: str
    aggregation: str
    points: tuple[PerformancePoint, ...]
    execution_allowed: Literal[False] = False


def build_portfolio_performance_series(
    snapshots: pd.DataFrame | None,
    *,
    metric: str = "twr_index",
    date_range: str = "inception",
    aggregation: str = "day",
    currency: str = "EUR",
    custom_start: date | str | None = None,
    custom_end: date | str | None = None,
    fx_rates: pd.DataFrame | None = None,
) -> PerformanceSeries:
    """Build a view without modifying saved snapshots or reimplementing returns.

    TWR and MWR always pass through the canonical valuation functions. Period
    P&L uses the saved daily canonical ``investment_pnl`` values. Currency
    conversion adjusts saved daily return factors before canonical TWR linking.
    """
    selected_metric = str(metric or "").strip().lower()
    selected_range = str(date_range or "").strip()
    selected_aggregation = str(aggregation or "").strip().lower()
    selected_currency = str(currency or "EUR").strip().upper()

    if selected_metric not in PERFORMANCE_METRICS:
        return _unavailable(selected_metric or "unknown", selected_currency, selected_range, selected_aggregation, "The requested performance metric is unsupported.")
    if selected_aggregation not in PERFORMANCE_AGGREGATIONS:
        return _unavailable(selected_metric, selected_currency, selected_range, selected_aggregation, "The requested aggregation is unsupported.")
    if not _valid_currency(selected_currency):
        return _unavailable(selected_metric, selected_currency, selected_range, selected_aggregation, "Output currency must be a three-letter currency code.")
    if selected_metric in _UNAVAILABLE_METRICS:
        return _unavailable(selected_metric, selected_currency, selected_range, selected_aggregation, _UNAVAILABLE_METRICS[selected_metric])
    if snapshots is None or not isinstance(snapshots, pd.DataFrame) or snapshots.empty:
        return _unavailable(selected_metric, selected_currency, selected_range, selected_aggregation, "Saved daily portfolio valuation history is unavailable or empty.")
    if snapshots.columns.duplicated().any() or not set(SNAPSHOT_COLUMNS).issubset(snapshots.columns):
        return _unavailable(selected_metric, selected_currency, selected_range, selected_aggregation, "Saved daily portfolio valuation snapshot fields are incomplete.")

    normalized, reason = _normalise_snapshots(snapshots)
    if normalized is None:
        return _unavailable(selected_metric, selected_currency, selected_range, selected_aggregation, reason or "Saved valuation dates are invalid.")
    bounds, reason = _resolve_range(normalized, selected_range, custom_start, custom_end)
    if bounds is None:
        return _unavailable(selected_metric, selected_currency, selected_range, selected_aggregation, reason or "The requested period is unavailable.")
    range_start, range_end = bounds
    selected = normalized.loc[
        normalized["date"].ge(pd.Timestamp(range_start)) & normalized["date"].le(pd.Timestamp(range_end))
    ].copy().reset_index(drop=True)
    if selected.empty:
        return _unavailable(
            selected_metric,
            selected_currency,
            selected_range,
            selected_aggregation,
            "No saved valuations exist in the requested period.",
            period_start=range_start,
            period_end=range_end,
        )

    # The last saved valuation before the range start anchors the first in-range
    # day's flow-adjusted return and P&L. It is never part of the displayed range,
    # the rebased TWR index or drawdown baseline.
    anchor = normalized.loc[normalized["date"].lt(pd.Timestamp(range_start))].tail(1)
    extended = pd.concat([anchor, selected], ignore_index=True)
    rates = _conversion_rates(extended, selected_currency, fx_rates)
    converted_extended = _convert_snapshots(extended, rates)
    anchor_converted = converted_extended.iloc[: len(anchor)]
    converted = converted_extended.iloc[len(anchor) :].reset_index(drop=True)
    periods = _periods(range_start, range_end, selected_aggregation, selected["date"])
    points: list[PerformancePoint] = []
    daily_drawdowns: dict[int, tuple[float | None, str | None]] = {}
    if selected_metric == "drawdown":
        twr_peak: float | None = None
        for position, row_index in enumerate(converted.index):
            index_value, index_reason = _cumulative_twr_index(converted.iloc[: position + 1])
            if index_value is None:
                daily_drawdowns[row_index] = (None, index_reason)
                continue
            twr_peak = index_value if twr_peak is None else max(twr_peak, index_value)
            daily_drawdowns[row_index] = (index_value / twr_peak - 1.0, None)

    for period_start, period_end in periods:
        previous_source: pd.DataFrame | None = None
        period_rows = selected.loc[
            selected["date"].ge(pd.Timestamp(period_start)) & selected["date"].le(pd.Timestamp(period_end))
        ]
        converted_period = converted.loc[period_rows.index]
        if (
            not period_rows.empty
            and selected_aggregation in {"week", "month", "quarter", "year"}
            and selected_metric in {"twr_index", "twr_return", "investment_pnl", "fx"}
        ):
            previous_rows = selected.loc[selected["date"].lt(period_rows.iloc[0]["date"])].tail(1)
            if not previous_rows.empty:
                previous_source = previous_rows
                converted_period = pd.concat([converted.loc[previous_rows.index], converted_period])
            elif not anchor.empty:
                previous_source = anchor
                converted_period = pd.concat([anchor_converted, converted_period])
        elif not period_rows.empty and selected_metric == "fx":
            previous_rows = selected.loc[selected["date"].lt(period_rows.iloc[0]["date"])].tail(1)
            if not previous_rows.empty:
                previous_source = previous_rows
            elif not anchor.empty:
                previous_source = anchor
        lineage_rows = (
            selected.loc[selected["date"].le(pd.Timestamp(period_end))]
            if selected_metric in {"twr_index", "drawdown"}
            else period_rows
        )
        if previous_source is not None and selected_metric in {"twr_return", "investment_pnl", "fx"}:
            lineage_rows = pd.concat([previous_source, lineage_rows])
        source_identity = _source_identity(lineage_rows, rates)
        partial_reasons = _quality_reasons(period_rows, period_start, period_end, range_start, range_end)
        if period_rows.empty:
            missing_reason = "; ".join(partial_reasons) or "No saved valuation snapshot exists in this period."
            points.append(
                PerformancePoint(
                    period_start,
                    period_end,
                    None,
                    True,
                    "unavailable",
                    "unavailable",
                    missing_reason,
                    None,
                )
            )
            continue

        index_value, index_reason = _cumulative_twr_index(
            converted.loc[converted["date"].le(pd.Timestamp(period_end))]
        )
        if selected_metric == "twr_index":
            point_value, metric_reason = index_value, index_reason
        elif selected_metric == "drawdown":
            point_value, metric_reason = daily_drawdowns[period_rows.index[-1]]
        else:
            point_value, metric_reason = _metric_value(
                selected_metric,
                period_rows,
                converted_period,
                converted,
                rates,
                selected,
                selected_aggregation,
                previous_source,
            )
        reason_parts = list(partial_reasons)
        if metric_reason:
            reason_parts.append(metric_reason)
        point_reason = "; ".join(dict.fromkeys(reason_parts)) or None
        explicit_stale = _has_stale_marker(period_rows)
        if explicit_stale:
            point_value = None
            point_status = "stale"
            point_quality = "stale"
            point_reason = point_reason or "Saved valuation evidence is explicitly marked stale."
        elif point_value is None:
            point_status = "unavailable"
            point_quality = "unavailable"
            point_reason = point_reason or "The selected metric is unavailable for this period."
        elif point_reason:
            point_status = "partial"
            point_quality = "partial"
        else:
            point_status = "available"
            point_quality = "complete"
        points.append(
            PerformancePoint(
                period_start,
                period_end,
                point_value,
                point_status != "available",
                point_quality,
                point_status,
                point_reason,
                source_identity,
            )
        )

    return _series(selected_metric, selected_currency, selected_range, selected_aggregation, range_start, range_end, points)


def performance_series_frame(series: PerformanceSeries) -> pd.DataFrame:
    """Return the exact selected series rows for accessible tables and CSV."""
    columns = (
        "metric",
        "unit",
        "currency",
        "date_range",
        "aggregation",
        "period_start",
        "period_end",
        "value",
        "partial",
        "quality",
        "status",
        "reason",
        "source_snapshot",
    )
    records = [
        {
            "metric": series.metric,
            "unit": series.unit,
            "currency": series.currency,
            "date_range": series.date_range,
            "aggregation": series.aggregation,
            "period_start": point.period_start.isoformat(),
            "period_end": point.period_end.isoformat(),
            "value": point.value,
            "partial": point.partial,
            "quality": point.quality,
            "status": point.status,
            "reason": point.reason,
            "source_snapshot": point.source_snapshot,
        }
        for point in series.points
    ]
    return pd.DataFrame.from_records(records, columns=columns)


def performance_series_to_csv(series: PerformanceSeries) -> str:
    """Export the selected series values and provenance as CSV text."""
    output = StringIO()
    performance_series_frame(series).to_csv(output, index=False)
    return output.getvalue()


def _normalise_snapshots(snapshots: pd.DataFrame) -> tuple[pd.DataFrame | None, str | None]:
    result = snapshots.loc[:, list(SNAPSHOT_COLUMNS)].copy()
    dates = pd.to_datetime(result["date"], errors="coerce", utc=True)
    if dates.isna().any():
        return None, "Saved valuation dates are invalid."
    result["date"] = dates.dt.tz_convert(None).dt.normalize()
    if result["date"].duplicated().any():
        return None, "Duplicate saved valuation dates prevent precise performance."
    return result.sort_values("date", kind="stable").reset_index(drop=True), None


def _resolve_range(
    snapshots: pd.DataFrame,
    date_range: str,
    custom_start: date | str | None,
    custom_end: date | str | None,
) -> tuple[tuple[date, date] | None, str | None]:
    first = snapshots["date"].iloc[0]
    last = snapshots["date"].iloc[-1]
    end = last.date()
    if date_range == "inception":
        start = first.date()
    elif date_range == "YTD":
        start = date(end.year, 1, 1)
    elif date_range in {"1M", "3M", "6M"}:
        start = (last - pd.DateOffset(months=int(date_range[:-1]))).date()
    elif date_range in {"1Y", "3Y", "5Y"}:
        start = (last - pd.DateOffset(years=int(date_range[:-1]))).date()
    elif date_range == "custom":
        start = _parse_date(custom_start)
        custom_end_date = _parse_date(custom_end)
        if start is None or custom_end_date is None:
            return None, "Custom range requires valid start and end dates."
        if start > custom_end_date:
            return None, "Custom range start must not be after its end."
        end = custom_end_date
    else:
        return None, "The selected date range is unsupported."
    return (start, end), None


def _parse_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_convert(None).date()


def _periods(
    start: date,
    end: date,
    aggregation: str,
    dates: pd.Series,
) -> list[tuple[date, date]]:
    if aggregation == "day":
        present = {value.date() for value in dates}
        return [
            (value.date(), value.date())
            for value in pd.date_range(start, end, freq="D")
            if value.weekday() < 5 or value.date() in present
        ]
    frequency = _FREQUENCIES[aggregation]
    buckets = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq=frequency)
    periods: list[tuple[date, date]] = []
    for bucket in buckets:
        bucket_start = max(start, bucket.start_time.date())
        bucket_end = min(end, bucket.end_time.date())
        periods.append((bucket_start, bucket_end))
    return periods


def _conversion_rates(
    snapshots: pd.DataFrame,
    currency: str,
    fx_rates: pd.DataFrame | None,
) -> dict[date, tuple[float | None, str | None]]:
    result: dict[date, tuple[float | None, str | None, str | None]] = {}
    for observed in snapshots["date"]:
        day = observed.date()
        if currency == "EUR":
            result[day] = (1.0, None, None)
            continue
        if not isinstance(fx_rates, pd.DataFrame) or fx_rates.empty:
            result[day] = (None, "FX rates are missing; this currency conversion is unavailable.", None)
            continue
        try:
            fx_snapshot = build_fx_rate_snapshot(fx_rates, decision_time=day)
            cross_rate = fx_cross_rate(fx_snapshot, "EUR", currency)
        except (KeyError, TypeError, ValueError) as exc:
            result[day] = (None, f"FX snapshot is invalid: {exc}", None)
            continue
        if cross_rate is None:
            result[day] = (
                None,
                fx_snapshot.reason or f"No point-in-time FX rate is available from EUR to {currency}.",
                fx_snapshot.source_snapshot,
            )
        else:
            result[day] = (cross_rate.rate, None, cross_rate.source_snapshot)
    return result


def _convert_snapshots(
    snapshots: pd.DataFrame,
    rates: dict[date, tuple[float | None, str | None, str | None]],
) -> pd.DataFrame:
    converted = snapshots.copy()
    converted["_fx_rate"] = [rates.get(value.date(), (None, None, None))[0] for value in converted["date"]]
    for column in (
        "cash_value",
        "securities_value",
        "total_value",
        "external_flow",
        "invested_capital",
        "dividends",
        "coupons",
        "fees",
        "taxes",
        "investment_pnl",
    ):
        converted[column] = pd.to_numeric(converted[column], errors="coerce") * converted["_fx_rate"]
    converted["period_return"] = math.nan
    for index in range(1, len(converted)):
        current = converted.iloc[index]
        previous = converted.iloc[index - 1]
        source_return = _finite(snapshots.iloc[index]["period_return"])
        previous_rate = _finite(previous["_fx_rate"])
        current_rate = _finite(current["_fx_rate"])
        if source_return is None or previous_rate is None or current_rate is None or previous_rate == 0:
            continue
        converted.at[index, "period_return"] = (1.0 + source_return) * current_rate / previous_rate - 1.0
    return converted


def _metric_value(
    metric: str,
    period_rows: pd.DataFrame,
    converted_period: pd.DataFrame,
    converted_selected: pd.DataFrame,
    rates: dict[date, tuple[float | None, str | None, str | None]],
    selected: pd.DataFrame,
    aggregation: str,
    prior_rows: pd.DataFrame | None = None,
) -> tuple[float | None, str | None]:
    dates = [value.date() for value in period_rows["date"]]
    for day in dates:
        _, reason, _ = rates.get(day, (None, "FX conversion is unavailable.", None))
        if reason and (metric in _CURRENCY_METRICS or metric in {"twr_index", "twr_return", "mwr_return", "drawdown"}):
            return None, reason
    last = converted_period.iloc[-1]
    if metric in {"portfolio_value", "net_invested_capital", "cash_value"}:
        field = {"portfolio_value": "total_value", "net_invested_capital": "invested_capital", "cash_value": "cash_value"}[metric]
        return _finite(last[field]), None if _finite(last[field]) is not None else f"Saved {field} is unavailable for the period end."
    if metric == "twr_return" and aggregation == "day":
        daily_return = _finite(converted_period.iloc[-1]["period_return"])
        return (daily_return, None) if daily_return is not None else (None, "The saved daily flow-adjusted return is unavailable.")
    if metric == "twr_return":
        result = _canonical_twr(converted_period)
        return _return_value(result)
    if metric == "mwr_return":
        result = _canonical_mwr(converted_period)
        return _return_value(result)
    if metric == "twr_index":
        result = _canonical_twr(converted_period)
        value, reason = _return_value(result)
        if value is None:
            return None, reason
        return 100.0 * (1.0 + value), None
    if metric == "drawdown":
        return None, "Drawdown requires the selected range's cumulative TWR index."
    if metric == "investment_pnl":
        if aggregation == "day":
            daily_pnl = _finite(converted_period.iloc[-1]["investment_pnl"])
            return (daily_pnl, None) if daily_pnl is not None else (None, "The saved daily investment P&L is unavailable.")
        anchored_rows = period_rows if prior_rows is None else pd.concat([prior_rows, period_rows])
        if not _complete_period(anchored_rows):
            return None, "Missing valuations or flows prevent period investment P&L aggregation."
        return _sum_field(converted_period.iloc[1:], "investment_pnl", "Period investment P&L requires at least two complete snapshots.")
    if metric == "net_contributions":
        if not period_rows["flow_status"].eq("available").all():
            return None, "Unavailable flow classifications prevent net contribution aggregation."
        values = pd.to_numeric(converted_period["external_flow"], errors="coerce")
        if values.isna().any() or not math.isfinite(float(values.sum())):
            return None, "Saved net external flows are unavailable."
        return float(values.sum()), None
    if metric == "income":
        dividends = pd.to_numeric(converted_period["dividends"], errors="coerce")
        coupons = pd.to_numeric(converted_period["coupons"], errors="coerce")
        if dividends.isna().any() or coupons.isna().any():
            return None, "Income event values are unavailable for part of the period."
        value = float(dividends.sum() + coupons.sum())
        return (value, None) if math.isfinite(value) else (None, "Income total is invalid.")
    if metric == "fees_tax":
        fees = pd.to_numeric(converted_period["fees"], errors="coerce")
        taxes = pd.to_numeric(converted_period["taxes"], errors="coerce")
        if fees.isna().any() or taxes.isna().any():
            return None, "Fee or tax event values are unavailable for part of the period."
        value = float(fees.sum() + taxes.sum())
        return (value, None) if math.isfinite(value) else (None, "Fees and tax total is invalid.")
    if metric == "fx":
        if prior_rows is None:
            return None, "A prior saved valuation is required for FX attribution."
        return _fx_total(pd.concat([prior_rows, period_rows]), rates)
    return None, "The selected metric is unavailable in saved daily snapshots."


def _canonical_twr(snapshots: pd.DataFrame) -> dict[str, object]:
    if len(snapshots) < 2:
        return {"status": "unavailable", "value": None, "reason": "At least two complete daily snapshots are required."}
    return link_time_weighted_return(snapshots, start=snapshots.iloc[0]["date"], end=snapshots.iloc[-1]["date"])


def _canonical_mwr(snapshots: pd.DataFrame) -> dict[str, object]:
    if len(snapshots) < 2:
        return {"status": "unavailable", "value": None, "reason": "At least two complete daily snapshots are required."}
    return calculate_money_weighted_return(snapshots, start=snapshots.iloc[0]["date"], end=snapshots.iloc[-1]["date"])


def _return_value(result: dict[str, object]) -> tuple[float | None, str | None]:
    if result.get("status") != "available":
        return None, str(result.get("reason") or "Canonical return calculation is unavailable.")
    return _finite(result.get("value")), None


def _cumulative_twr_index(
    converted: pd.DataFrame,
) -> tuple[float | None, str | None]:
    if converted.empty:
        return None, "No saved valuation snapshot exists in this period."
    if len(converted) == 1:
        first = converted.iloc[0]
        if first["valuation_status"] == "available" and first["flow_status"] == "available" and _finite(first["total_value"]) is not None:
            return 100.0, None
        return None, "The TWR index baseline valuation is unavailable."
    result = _canonical_twr(converted)
    value, reason = _return_value(result)
    if value is None:
        return None, reason
    return 100.0 * (1.0 + value), None


def _fx_total(
    period_rows: pd.DataFrame,
    rates: dict[date, tuple[float | None, str | None, str | None]],
) -> tuple[float | None, str | None]:
    """Attribute FX as prior EUR value times the change in the dated FX rate."""
    if len(period_rows) < 2:
        return None, "Period FX effect requires at least two complete snapshots."
    if not _complete_period(period_rows):
        return None, "Missing valuations or flows prevent FX attribution across the period."
    total = 0.0
    for index in range(1, len(period_rows)):
        previous = period_rows.iloc[index - 1]
        current = period_rows.iloc[index]
        previous_rate, previous_reason, _ = rates.get(previous["date"].date(), (None, "FX rate unavailable.", None))
        current_rate, current_reason, _ = rates.get(current["date"].date(), (None, "FX rate unavailable.", None))
        if previous_reason or current_reason or previous_rate is None or current_rate is None:
            return None, previous_reason or current_reason or "FX effect is unavailable."
        previous_value = _finite(previous["total_value"])
        if previous_value is None:
            return None, "A prior valuation is unavailable for FX attribution."
        total += previous_value * (current_rate - previous_rate)
    return (total, None) if math.isfinite(total) else (None, "FX attribution is invalid.")


def _sum_field(frame: pd.DataFrame, column: str, missing_reason: str) -> tuple[float | None, str | None]:
    if frame.empty:
        return None, missing_reason
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.isna().any() or not math.isfinite(float(values.sum())):
        return None, missing_reason
    return float(values.sum()), None


def _complete_period(rows: pd.DataFrame) -> bool:
    if len(rows) < 2 or not rows["valuation_status"].eq("available").all() or not rows["flow_status"].eq("available").all():
        return False
    observed = pd.DatetimeIndex(rows["date"])
    return pd.bdate_range(observed[0], observed[-1]).difference(observed).empty


def _quality_reasons(
    rows: pd.DataFrame,
    period_start: date,
    period_end: date,
    range_start: date,
    range_end: date,
) -> list[str]:
    """Use the canonical return contract's weekday coverage rule; never fill gaps."""
    reasons: list[str] = []
    expected_start = max(period_start, range_start)
    expected_end = min(period_end, range_end)
    expected = pd.bdate_range(expected_start, expected_end)
    observed = pd.DatetimeIndex(rows["date"]) if not rows.empty else pd.DatetimeIndex([])
    missing = expected.difference(observed)
    if not missing.empty:
        dates = ", ".join(missing.strftime("%Y-%m-%d")[:5])
        suffix = " …" if len(missing) > 5 else ""
        reasons.append(f"Missing daily valuations or flows for expected dates: {dates}{suffix}.")
    if not rows.empty:
        if not rows["valuation_status"].eq("available").all():
            reasons.append("One or more saved valuations are unavailable.")
        if not rows["flow_status"].eq("available").all():
            reasons.append("One or more external-flow classifications are unavailable.")
        if not rows["availability_evidence"].eq("timestamped").all():
            reasons.append("Snapshot availability timestamps are absent; freshness cannot be verified.")
    return reasons


def _has_stale_marker(rows: pd.DataFrame) -> bool:
    if rows.empty:
        return False
    statuses = rows[["valuation_status", "flow_status", "availability_evidence"]].astype(str)
    if statuses.apply(lambda column: column.str.casefold().eq("stale")).any().any():
        return True
    missing = rows["missing_reasons"].fillna("").astype(str)
    return bool(missing.str.contains("stale", case=False, regex=False).any())


def _source_identity(
    rows: pd.DataFrame,
    rates: dict[date, tuple[float | None, str | None, str | None]],
) -> str | None:
    if rows.empty:
        return None
    payload = [_identity_row(row) for row in rows.loc[:, list(SNAPSHOT_COLUMNS)].to_dict(orient="records")]
    fx_sources = sorted(
        {
            source
            for observed in rows["date"]
            for source in (rates.get(observed.date(), (None, None, None))[2],)
            if source is not None
        }
    )
    encoded = json.dumps(
        {"valuation_snapshots": payload, "fx_snapshots": fx_sources},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _identity_row(row: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in row.items():
        if value is None or (not isinstance(value, (str, date)) and pd.isna(value)):
            result[key] = None
        elif isinstance(value, pd.Timestamp):
            result[key] = value.isoformat()
        elif isinstance(value, date):
            result[key] = value.isoformat()
        elif hasattr(value, "item"):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _valid_currency(currency: str) -> bool:
    return len(currency) == 3 and currency.isalpha() and currency.isascii()


def _series(
    metric: str,
    currency: str,
    date_range: str,
    aggregation: str,
    period_start: date,
    period_end: date,
    points: list[PerformancePoint],
) -> PerformanceSeries:
    statuses = {point.status for point in points}
    if not points or all(point.value is None for point in points):
        status = "unavailable"
    elif "stale" in statuses:
        status = "stale"
    elif any(value != "available" for value in statuses):
        status = "partial"
    else:
        status = "available"
    reasons = list(dict.fromkeys(point.reason for point in points if point.reason))
    quality = "stale" if status == "stale" else "partial" if status != "available" else "complete"
    unit = "currency" if metric in _CURRENCY_METRICS else "index" if metric == "twr_index" else "percent"
    return PerformanceSeries(
        metric,
        unit,
        currency,
        period_start,
        period_end,
        status != "available",
        quality,
        status,
        "; ".join(reasons) or None,
        date_range,
        aggregation,
        tuple(points),
    )


def _unavailable(
    metric: str,
    currency: str,
    date_range: str,
    aggregation: str,
    reason: str,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> PerformanceSeries:
    unit = "currency" if metric in _CURRENCY_METRICS else "index" if metric == "twr_index" else "percent"
    return PerformanceSeries(
        metric,
        unit,
        currency,
        period_start,
        period_end,
        True,
        "unavailable",
        "unavailable",
        reason,
        date_range,
        aggregation,
        (),
    )


__all__ = [
    "Aggregation",
    "DateRange",
    "PERFORMANCE_AGGREGATIONS",
    "PERFORMANCE_METRICS",
    "PERFORMANCE_RANGES",
    "PerformanceMetric",
    "PerformancePoint",
    "PerformanceSeries",
    "build_portfolio_performance_series",
    "performance_series_frame",
    "performance_series_to_csv",
]
