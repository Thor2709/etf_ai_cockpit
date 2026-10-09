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


def snapshot_etf_cutoff(snapshot: object) -> pd.Timestamp:
    """Use the snapshot decision, falling back to its report's calendar date."""
    report = getattr(snapshot, "data_report", None)
    for value in (
        getattr(snapshot, "decision_time", None),
        getattr(report, "decision_time", None),
        getattr(snapshot, "benchmark_reference_decision_time", None),
        getattr(report, "as_of_date", None),
    ):
        if value is not None:
            return etf_decision_cutoff(value)
    return pd.NaT
