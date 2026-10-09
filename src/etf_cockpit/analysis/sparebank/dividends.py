"""EC cash-distribution history and yield from the price source (SB2, book p. 114, eq. 5.45).

The distributions are the per-certificate cash dividends recorded with the daily prices (ex-date). Only rows
dated on or before the decision time are passed in, so the history is point in time. Whether the source records
no dividends or the bank paid none cannot be told apart, so an empty history is reported as unavailable with
that reason, never as zero.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

import pandas as pd

from .book_calcs import dividend_yield

SOURCE = "price provider dividends column (cash per certificate on the ex-date)"


def dividend_history(price_rows: pd.DataFrame | None, price: float | None = None, *, keep_events: int = 12) -> dict[str, object]:
    """Distribution events, calendar-year totals and the trailing-12-month yield at ``price``."""

    unavailable = {"status": "unavailable", "source": SOURCE, "events": [], "by_year": [], "execution_allowed": False}
    if price_rows is None or price_rows.empty or "dividends" not in price_rows.columns or "_price_date" not in price_rows.columns:
        return {**unavailable, "reason_code": "PRICE_SOURCE_HAS_NO_DIVIDENDS_COLUMN"}
    amounts = pd.to_numeric(price_rows["dividends"], errors="coerce")
    frame = pd.DataFrame({"date": price_rows["_price_date"], "amount": amounts})
    frame = frame.loc[frame["amount"].notna() & frame["amount"].gt(0) & frame["amount"].map(math.isfinite)]
    if frame.empty:
        return {**unavailable, "reason_code": "NO_DIVIDEND_EVENTS_IN_PRICE_SOURCE"}
    frame = frame.sort_values("date", kind="stable")
    last_date = pd.Timestamp(price_rows["_price_date"].max())
    events = [{"ex_date": row.date.date().isoformat(), "amount": float(row.amount)} for row in frame.itertuples()]
    by_year: dict[int, dict[str, float]] = {}
    for row in frame.itertuples():
        entry = by_year.setdefault(int(row.date.year), {"amount": 0.0, "count": 0})
        entry["amount"] += float(row.amount)
        entry["count"] += 1
    window_start = last_date - pd.DateOffset(years=1)
    ttm = float(frame.loc[frame["date"].gt(window_start), "amount"].sum())
    ttm_amount: float | None = ttm if ttm > 0 else None
    years = sorted(by_year)
    return {
        "status": "available",
        "source": SOURCE,
        "as_of": last_date.date().isoformat(),
        "events": events[-keep_events:],
        "by_year": [
            {"year": year, "amount": by_year[year]["amount"], "count": int(by_year[year]["count"]), "complete": year < last_date.year}
            for year in years
        ],
        "ttm_amount": ttm_amount,
        "ttm_yield": dividend_yield(ttm_amount, price) if ttm_amount is not None and price else None,
        "last_ex_date": events[-1]["ex_date"],
        "years_with_dividend": len(years),
        "execution_allowed": False,
    }


__all__ = ["dividend_history"]
