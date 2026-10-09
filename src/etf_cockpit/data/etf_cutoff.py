"""Shared point-in-time cutoff policy for ETF observations."""

from datetime import date, datetime
import re

import pandas as pd


def etf_decision_cutoff(value: object) -> pd.Timestamp:
    """Preserve timestamps; a calendar date includes that entire UTC day."""
    cutoff = pd.to_datetime(value, utc=True, errors="coerce")
    date_only = isinstance(value, date) and not isinstance(value, datetime)
    date_only |= isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()) is not None
    if date_only and pd.notna(cutoff):
        cutoff += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return cutoff


def snapshot_etf_cutoff(snapshot: object, *, now: object = None) -> pd.Timestamp:
    """Knowledge cutoff for the live view of the current snapshot.

    The snapshot's market-data decision time is when its last prices became available; ETF facts
    (TER, holdings, ...) fetched later that day are still known when the owner looks at the page, so
    the live view uses the later of that time and now. Nothing after now can be known, so this is
    point-in-time correct; replays pass an explicit ``as_of`` and never use this."""
    report = getattr(snapshot, "data_report", None)
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.to_datetime(now, utc=True)
    for value in (
        getattr(snapshot, "decision_time", None),
        getattr(report, "decision_time", None),
        getattr(snapshot, "benchmark_reference_decision_time", None),
        getattr(report, "as_of_date", None),
    ):
        if value is not None:
            cutoff = etf_decision_cutoff(value)
            return max(cutoff, current) if pd.notna(cutoff) else current
    return current
