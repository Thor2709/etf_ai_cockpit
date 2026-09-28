"""Dated portfolio valuation and performance calculations.

All monetary amounts must already use the portfolio's reporting currency.
Daily positions, prices, cash and event records are exact-date observations;
the module never fills a missing mark or carries a stale price forward.
"""

from __future__ import annotations

from datetime import date, datetime
import math

import numpy as np
import pandas as pd

VALUATION_MODEL_VERSION = "portfolio-valuation.v1"
SNAPSHOT_COLUMNS = (
    "date",
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
    "period_return",
    "valuation_status",
    "flow_status",
    "availability_evidence",
    "missing_reasons",
    "execution_allowed",
)

_FLOW_CLASS = {
    "contribution": "external_inflow",
    "deposit": "external_inflow",
    "transfer_in": "external_inflow",
    "external_inflow": "external_inflow",
    "withdrawal": "external_outflow",
    "transfer_out": "external_outflow",
    "external_outflow": "external_outflow",
    "dividend": "dividend",
    "distribution": "dividend",
    "coupon": "coupon",
    "interest": "coupon",
    "fee": "fee",
    "commission": "fee",
    "tax": "tax",
    "purchase": "internal_trade",
    "buy": "internal_trade",
    "sale": "internal_trade",
    "sell": "internal_trade",
    "internal_transfer": "internal_trade",
    "trade": "internal_trade",
}


class PortfolioValuationError(ValueError):
    """Raised when required local valuation inputs cannot be interpreted."""


def classify_portfolio_flow(event_type: object) -> str:
    """Return the accounting class for a supported portfolio event."""
    if not isinstance(event_type, str):
        return "unknown"
    return _FLOW_CLASS.get(event_type.strip().lower().replace("-", "_").replace(" ", "_"), "unknown")


def build_daily_portfolio_snapshots(
    holdings: pd.DataFrame | None,
    prices: pd.DataFrame | None,
    cash_balances: pd.DataFrame | None,
    events: pd.DataFrame | None,
    *,
    decision_time: date | datetime | pd.Timestamp | str | None,
) -> pd.DataFrame:
    """Value exact-date position and cash snapshots and classify ledger events.

    Holdings require ``date``, ``instrument_id`` and ``quantity``; prices
    require ``date``, ``instrument_id`` and ``price``; cash requires ``date``
    and ``cash_value``; events require ``date``, ``event_type`` and ``amount``.
    Event amounts are non-negative magnitudes; their type supplies the sign.
    An empty, correctly shaped holdings or event frame is explicit evidence of
    no positions or events. ``None`` means unavailable evidence.
    """
    cutoff = _decision_cutoff(decision_time)
    position_rows = _dated_frame(holdings, "holdings", {"instrument_id", "quantity"}, cutoff)
    price_rows = _dated_frame(prices, "prices", {"instrument_id", "price"}, cutoff)
    cash_rows = _dated_frame(cash_balances, "cash_balances", {"cash_value"}, cutoff)
    event_rows = _dated_frame(events, "events", {"event_type", "amount"}, cutoff)

    dates = sorted(set(position_rows["_date"]) | set(price_rows["_date"]) | set(cash_rows["_date"]) | set(event_rows["_date"]))
    if not dates:
        raise PortfolioValuationError("No dated valuation observations are available by the decision time.")

    availability_evidence = (
        "timestamped"
        if all("available_at" in frame.columns for frame in (holdings, prices, cash_balances, events))
        else "observation_date_assumed"
    )
    records: list[dict[str, object]] = []
    empty_holdings = bool(holdings.empty)
    for observed_date in dates:
        raw_holdings = position_rows.loc[position_rows["_date"] == observed_date]
        raw_prices = price_rows.loc[price_rows["_date"] == observed_date]
        raw_cash = cash_rows.loc[cash_rows["_date"] == observed_date]
        raw_events = event_rows.loc[event_rows["_date"] == observed_date]
        day_holdings = raw_holdings.loc[~raw_holdings["_excluded_after_cutoff"]]
        day_prices = raw_prices.loc[~raw_prices["_excluded_after_cutoff"]]
        day_cash = raw_cash.loc[~raw_cash["_excluded_after_cutoff"]]
        day_events = raw_events.loc[~raw_events["_excluded_after_cutoff"]]
        reasons: list[str] = []
        if raw_holdings["_excluded_after_cutoff"].any():
            reasons.append("holdings_not_available_by_decision_time")
        if raw_prices["_excluded_after_cutoff"].any():
            reasons.append("prices_not_available_by_decision_time")
        if raw_cash["_excluded_after_cutoff"].any():
            reasons.append("cash_not_available_by_decision_time")

        cash_value = _sum_amounts(day_cash, "cash_value")
        if raw_cash["_excluded_after_cutoff"].any():
            cash_value = None
        if cash_value is None:
            reasons.append("cash_balance_missing_or_invalid")

        securities_value: float | None = 0.0 if empty_holdings else None
        if not empty_holdings and day_holdings.empty:
            reasons.append("holdings_snapshot_missing")
        elif not day_holdings.empty:
            holding_reasons_before = len(reasons)
            quantities = pd.to_numeric(day_holdings["quantity"], errors="coerce")
            if quantities.isna().any() or not np.isfinite(quantities.to_numpy(dtype=float)).all():
                reasons.append("holding_quantity_invalid")
            elif day_holdings["instrument_id"].isna().any() or not day_holdings["instrument_id"].map(lambda value: isinstance(value, str) and bool(value.strip())).all():
                reasons.append("holding_identity_invalid")
            else:
                held_ids = set(day_holdings["instrument_id"])
                relevant_prices = day_prices.loc[day_prices["instrument_id"].isin(held_ids)]
                excluded_held_prices = raw_prices.loc[
                    raw_prices["_excluded_after_cutoff"] & raw_prices["instrument_id"].isin(held_ids)
                ]
                if not excluded_held_prices.empty:
                    reasons.extend(f"price_not_available_by_decision_time:{item}" for item in sorted(set(excluded_held_prices["instrument_id"])))
                elif relevant_prices.duplicated("instrument_id").any():
                    reasons.append("duplicate_price_observation")
                else:
                    price_by_id = relevant_prices.set_index("instrument_id")["price"]
                    values: list[float] = []
                    for instrument_id, quantity in zip(day_holdings["instrument_id"], quantities, strict=True):
                        if float(quantity) == 0.0:
                            continue
                        raw_price = price_by_id.get(instrument_id)
                        price = pd.to_numeric(pd.Series([raw_price]), errors="coerce").iloc[0]
                        if pd.isna(price) or not math.isfinite(float(price)) or float(price) <= 0:
                            reasons.append(f"price_missing_or_invalid:{instrument_id}")
                            break
                        position_value = float(quantity) * float(price)
                        if not math.isfinite(position_value):
                            reasons.append(f"position_value_invalid:{instrument_id}")
                            break
                        values.append(position_value)
                    if len(reasons) == holding_reasons_before:
                        position_total = float(sum(values))
                        if math.isfinite(position_total):
                            securities_value = position_total
                        else:
                            reasons.append("securities_value_invalid")
            if raw_holdings["_excluded_after_cutoff"].any():
                securities_value = None

        event_totals, flow_status, event_reasons = _event_totals(day_events)
        reasons.extend(event_reasons)
        if raw_events["_excluded_after_cutoff"].any():
            flow_status = "unavailable"
            reasons.append("events_not_available_by_decision_time")
        valuation_status = "available" if cash_value is not None and securities_value is not None else "unavailable"
        if flow_status != "available":
            external_flow = math.nan
        else:
            external_flow = event_totals["external_inflow"] - event_totals["external_outflow"]
        total_value = math.nan
        if valuation_status == "available":
            candidate_total = float(cash_value + securities_value)
            if math.isfinite(candidate_total):
                total_value = candidate_total
            else:
                valuation_status = "unavailable"
                reasons.append("total_portfolio_value_invalid")
        records.append(
            {
                "date": observed_date,
                "cash_value": cash_value if cash_value is not None else math.nan,
                "securities_value": securities_value if securities_value is not None else math.nan,
                "total_value": total_value,
                "external_flow": external_flow,
                "invested_capital": math.nan,
                "dividends": event_totals["dividend"],
                "coupons": event_totals["coupon"],
                "fees": event_totals["fee"],
                "taxes": event_totals["tax"],
                "investment_pnl": math.nan,
                "period_return": math.nan,
                "valuation_status": valuation_status,
                "flow_status": flow_status,
                "availability_evidence": availability_evidence,
                "missing_reasons": ";".join(dict.fromkeys(reasons)),
                "execution_allowed": False,
            }
        )

    snapshots = pd.DataFrame.from_records(records, columns=SNAPSHOT_COLUMNS)
    for index in range(len(snapshots)):
        current = snapshots.iloc[index]
        current_complete = current["valuation_status"] == "available" and current["flow_status"] == "available"
        if not current_complete:
            continue
        if index == 0:
            initial_capital = float(current["total_value"] - current["external_flow"])
            if math.isfinite(initial_capital):
                snapshots.at[index, "invested_capital"] = initial_capital
            continue
        previous = snapshots.iloc[index - 1]
        previous_complete = previous["valuation_status"] == "available" and previous["flow_status"] == "available"
        if not previous_complete or float(previous["total_value"]) == 0.0:
            continue
        daily_pnl = float(current["total_value"] - previous["total_value"] - current["external_flow"])
        daily_return = float((current["total_value"] - current["external_flow"]) / previous["total_value"] - 1.0)
        if math.isfinite(daily_pnl) and math.isfinite(daily_return):
            snapshots.at[index, "investment_pnl"] = daily_pnl
            snapshots.at[index, "period_return"] = daily_return
        prior_capital = previous["invested_capital"]
        if pd.notna(prior_capital):
            next_capital = float(prior_capital + current["external_flow"])
            if math.isfinite(next_capital):
                snapshots.at[index, "invested_capital"] = next_capital
    return snapshots


def link_time_weighted_return(
    snapshots: pd.DataFrame | None,
    *,
    start: date | datetime | pd.Timestamp | str | None = None,
    end: date | datetime | pd.Timestamp | str | None = None,
) -> dict[str, object]:
    """Geometrically link daily end-of-day-flow-adjusted returns."""
    selected, reason = _select_period(snapshots, start, end)
    if selected is None:
        return _unavailable_result(reason or "Daily valuation snapshots are unavailable.")
    if len(selected) < 2:
        return _unavailable_result("At least two valid daily snapshots are required.")
    if not _complete(selected):
        return _unavailable_result("Missing, stale, or unclassified daily evidence prevents precise TWR.")
    returns = pd.to_numeric(selected["period_return"], errors="coerce").iloc[1:]
    if returns.isna().any() or not np.isfinite(returns.to_numpy(dtype=float)).all() or (returns < -1.0).any():
        return _unavailable_result("A daily flow-adjusted return is unavailable or invalid.")
    value = float(np.prod(1.0 + returns.to_numpy(dtype=float)) - 1.0)
    if not math.isfinite(value):
        return _unavailable_result("The linked TWR overflowed and is unavailable.")
    return {"status": "available", "value": value, "method": "geometrically_linked_daily_twr", "periods": int(len(returns)), "reason": None}


def calculate_money_weighted_return(
    snapshots: pd.DataFrame | None,
    *,
    start: date | datetime | pd.Timestamp | str | None = None,
    end: date | datetime | pd.Timestamp | str | None = None,
) -> dict[str, object]:
    """Calculate a de-annualised XIRR period return, with Modified Dietz fallback."""
    selected, reason = _select_period(snapshots, start, end)
    if selected is None:
        return _unavailable_result(reason or "Daily valuation snapshots are unavailable.")
    if len(selected) < 2 or not _complete(selected):
        return _unavailable_result("At least two complete daily snapshots are required for MWR.")
    start_date = pd.Timestamp(selected.iloc[0]["date"])
    end_date = pd.Timestamp(selected.iloc[-1]["date"])
    elapsed_days = int((end_date - start_date).days)
    if elapsed_days <= 0:
        return _unavailable_result("A positive measurement period is required for MWR.")
    start_value = float(selected.iloc[0]["total_value"])
    end_value = float(selected.iloc[-1]["total_value"])
    if start_value <= 0 or not math.isfinite(start_value) or not math.isfinite(end_value):
        return _unavailable_result("Positive starting value and finite ending value are required for MWR.")

    cashflows: dict[pd.Timestamp, float] = {start_date: -start_value, end_date: end_value}
    external = pd.to_numeric(selected["external_flow"], errors="coerce")
    for row_index in range(1, len(selected)):
        when = pd.Timestamp(selected.iloc[row_index]["date"])
        cashflows[when] = cashflows.get(when, 0.0) - float(external.iloc[row_index])
    ordered = sorted(cashflows.items())
    signs = [1 if amount > 0 else -1 for _, amount in ordered if amount != 0]
    changes = sum(left != right for left, right in zip(signs, signs[1:]))
    annualized = _xirr(ordered, elapsed_days) if changes == 1 else None
    if annualized is not None:
        try:
            period_value = float(math.expm1(math.log1p(annualized) * elapsed_days / 365.0))
        except OverflowError:
            annualized = None
        else:
            if math.isfinite(period_value):
                return {
                    "status": "available",
                    "value": period_value,
                    "method": "xirr_deannualized_period_return",
                    "annualized_xirr": annualized,
                    "label": "de-annualised period money-weighted return",
                    "period_days": elapsed_days,
                    "reason": None,
                }

    dietz, dietz_reason = _modified_dietz(selected, start_value, end_value, elapsed_days)
    if dietz is None:
        return _unavailable_result(dietz_reason or "XIRR was unsolveable and Modified Dietz was unavailable.")
    return {
        "status": "available",
        "value": dietz,
        "method": "modified_dietz_fallback",
        "annualized_xirr": None,
        "label": "Modified Dietz period return (not annualised)",
        "period_days": elapsed_days,
        "reason": "XIRR was unsolveable or had multiple roots.",
    }


def summarise_portfolio_valuation_history(snapshots: pd.DataFrame) -> dict[str, object]:
    """Expose persisted daily snapshots with reproducible inception results."""
    twr = link_time_weighted_return(snapshots)
    mwr = calculate_money_weighted_return(snapshots)
    if snapshots.empty:
        status = "unavailable"
    elif twr["status"] != "available":
        status = "unavailable"
    elif mwr["status"] != "available" or (snapshots["availability_evidence"] != "timestamped").any():
        status = "partial"
    else:
        status = "available"
    return {
        "status": status,
        "model_version": VALUATION_MODEL_VERSION,
        "execution_allowed": False,
        "snapshots": snapshots.copy(),
        "time_weighted_return": twr.get("value"),
        "time_weighted_status": twr["status"],
        "money_weighted_return": mwr.get("value"),
        "money_weighted_status": mwr["status"],
        "money_weighted_method": mwr.get("method"),
        "money_weighted_label": mwr.get("label"),
        "reason": (
            twr.get("reason")
            if twr["status"] != "available"
            else mwr.get("reason")
            if mwr["status"] != "available"
            else "Availability timestamps are absent; observation dates are assumed."
            if (snapshots["availability_evidence"] != "timestamped").any()
            else None
        ),
    }


def _decision_cutoff(decision_time: date | datetime | pd.Timestamp | str | None) -> pd.Timestamp:
    if decision_time is None:
        raise PortfolioValuationError("Decision time is unavailable; point-in-time valuation cannot be established.")
    try:
        cutoff = pd.Timestamp(decision_time)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PortfolioValuationError("Decision time is invalid; valuation unavailable.") from exc
    if pd.isna(cutoff):
        raise PortfolioValuationError("Decision time is invalid; valuation unavailable.")
    is_date_only = isinstance(decision_time, date) and not isinstance(decision_time, datetime)
    if isinstance(decision_time, str) and len(decision_time.strip()) == 10:
        is_date_only = True
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    if is_date_only:
        cutoff = cutoff.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return cutoff


def _dated_frame(
    frame: pd.DataFrame | None,
    name: str,
    required: set[str],
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    if frame is None:
        raise PortfolioValuationError(f"{name} evidence is unavailable; valuation unavailable.")
    if not isinstance(frame, pd.DataFrame) or frame.columns.duplicated().any():
        raise PortfolioValuationError(f"{name} evidence is malformed; valuation unavailable.")
    required_columns = {"date", *required}
    if not required_columns.issubset(frame.columns):
        raise PortfolioValuationError(f"{name} is missing required fields; valuation unavailable.")
    result = frame.copy()
    parsed = pd.to_datetime(result["date"], errors="coerce", utc=True)
    if parsed.isna().any():
        raise PortfolioValuationError(f"{name} contains an invalid observation date; valuation unavailable.")
    result["_date"] = parsed.dt.tz_convert(None).dt.normalize()
    result["_excluded_after_cutoff"] = False
    if "available_at" in result.columns:
        available = pd.to_datetime(result["available_at"], errors="coerce", utc=True)
        if available.isna().any():
            raise PortfolioValuationError(f"{name} contains invalid availability evidence; valuation unavailable.")
        result["_excluded_after_cutoff"] = (available > cutoff).to_numpy()
    latest_date = cutoff.tz_convert(None).normalize()
    return result.loc[result["_date"] <= latest_date].copy()


def _sum_amounts(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        return None
    total = float(values.sum())
    return total if math.isfinite(total) else None


def _event_totals(frame: pd.DataFrame) -> tuple[dict[str, float], str, list[str]]:
    totals = {"external_inflow": 0.0, "external_outflow": 0.0, "dividend": 0.0, "coupon": 0.0, "fee": 0.0, "tax": 0.0}
    if frame.empty:
        return totals, "available", []
    reasons: list[str] = []
    for event_type, amount in zip(frame["event_type"], frame["amount"], strict=True):
        category = classify_portfolio_flow(event_type)
        parsed_amount = pd.to_numeric(pd.Series([amount]), errors="coerce").iloc[0]
        if category == "unknown":
            reasons.append(f"event_type_unclassified:{event_type}")
            continue
        if pd.isna(parsed_amount) or not math.isfinite(float(parsed_amount)) or float(parsed_amount) < 0:
            reasons.append("event_amount_invalid")
            continue
        if category == "external_inflow":
            totals[category] += float(parsed_amount)
        elif category == "external_outflow":
            totals[category] += float(parsed_amount)
        elif category in totals:
            totals[category] += float(parsed_amount)
    if any(not math.isfinite(value) for value in totals.values()):
        reasons.append("event_amount_total_invalid")
    if reasons:
        return totals, "unavailable", reasons
    return totals, "available", []


def _select_period(
    snapshots: pd.DataFrame | None,
    start: date | datetime | pd.Timestamp | str | None,
    end: date | datetime | pd.Timestamp | str | None,
) -> tuple[pd.DataFrame | None, str | None]:
    if snapshots is None or not isinstance(snapshots, pd.DataFrame) or snapshots.empty:
        return None, "Daily valuation snapshots are unavailable."
    if snapshots.columns.duplicated().any() or not set(SNAPSHOT_COLUMNS).issubset(snapshots.columns):
        return None, "Daily valuation snapshot schema is invalid."
    selected = snapshots.copy()
    dates = pd.to_datetime(selected["date"], errors="coerce", utc=True)
    if dates.isna().any():
        return None, "Daily valuation dates are invalid."
    selected["date"] = dates.dt.tz_convert(None).dt.normalize()
    if selected["date"].duplicated().any():
        return None, "Duplicate daily valuation dates prevent precise performance."
    selected = selected.sort_values("date").reset_index(drop=True)
    if start is not None:
        start_date = _period_date(start)
        if start_date is None or start_date not in set(selected["date"]):
            return None, "The requested period start has no saved daily snapshot."
        selected = selected.loc[selected["date"] >= start_date]
    if end is not None:
        end_date = _period_date(end)
        if end_date is None or end_date not in set(selected["date"]):
            return None, "The requested period end has no saved daily snapshot."
        selected = selected.loc[selected["date"] <= end_date]
    if selected.empty or (start is not None and end is not None and selected.iloc[0]["date"] >= selected.iloc[-1]["date"]):
        return None, "The requested performance period is empty or has no elapsed time."
    return selected.reset_index(drop=True), None


def _period_date(value: date | datetime | pd.Timestamp | str) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_convert(None).normalize()


def _complete(snapshots: pd.DataFrame) -> bool:
    return bool(
        snapshots["valuation_status"].eq("available").all()
        and snapshots["flow_status"].eq("available").all()
        and pd.to_numeric(snapshots["total_value"], errors="coerce").notna().all()
        and pd.to_numeric(snapshots["external_flow"], errors="coerce").notna().all()
    )


def _xirr(cashflows: list[tuple[pd.Timestamp, float]], elapsed_days: int) -> float | None:
    origin = cashflows[0][0]
    dated = [(amount, (when - origin).days / 365.0) for when, amount in cashflows]

    def npv(rate: float) -> float:
        log_base = math.log1p(rate)
        try:
            return sum(amount * math.exp(-years * log_base) for amount, years in dated)
        except OverflowError:
            return math.inf

    lower = -0.999999
    f_lower = npv(lower)
    upper = 1.0
    f_upper = npv(upper)
    while math.copysign(1.0, f_lower) == math.copysign(1.0, f_upper) and upper < 1_000_000.0:
        upper = min(upper * 2.0 + 1.0, 1_000_000.0)
        f_upper = npv(upper)
    if not math.isfinite(f_lower) or not math.isfinite(f_upper) or math.copysign(1.0, f_lower) == math.copysign(1.0, f_upper):
        return None
    for _ in range(200):
        middle = (lower + upper) / 2.0
        f_middle = npv(middle)
        if abs(f_middle) <= 1e-10 or upper - lower <= 1e-12:
            return middle
        if math.copysign(1.0, f_middle) == math.copysign(1.0, f_lower):
            lower, f_lower = middle, f_middle
        else:
            upper, f_upper = middle, f_middle
    return (lower + upper) / 2.0


def _modified_dietz(
    snapshots: pd.DataFrame,
    start_value: float,
    end_value: float,
    elapsed_days: int,
) -> tuple[float | None, str | None]:
    external = pd.to_numeric(snapshots["external_flow"], errors="coerce")
    weighted_flows = 0.0
    total_flows = 0.0
    for index in range(1, len(snapshots)):
        flow = float(external.iloc[index])
        days_remaining = int((snapshots.iloc[-1]["date"] - snapshots.iloc[index]["date"]).days)
        total_flows += flow
        weighted_flows += flow * days_remaining / elapsed_days
    denominator = start_value + weighted_flows
    if not math.isfinite(denominator) or denominator <= 0:
        return None, "Modified Dietz capital denominator is non-positive or unavailable."
    value = (end_value - start_value - total_flows) / denominator
    if not math.isfinite(value) or value < -1.0:
        return None, "Modified Dietz return is invalid."
    return float(value), None


def _unavailable_result(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "value": None, "method": None, "reason": reason}
