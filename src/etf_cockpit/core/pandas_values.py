"""Generic value-coercion helpers that need pandas (NaN-aware text, flags, UTC timestamps).

Kept apart from :mod:`etf_cockpit.core.values` so that pandas-free modules do not import pandas.
"""

from __future__ import annotations

import pandas as pd


def bool_like_or_none(value: object) -> bool | None:
    """Parse a scalar into True/False from bool or common true/false/1/0/yes/no text, else None."""

    if value is None or not pd.api.types.is_scalar(value):
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def stripped_text_or_none(value: object) -> str | None:
    """Return str(value).strip() or None for None, NA and blank input."""

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def source_text_or_empty(value: object) -> str:
    """Return stripped text, with the empty string for None and NA."""

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def clean_text_or_empty(value: object) -> str:
    """Return stripped text, with the empty string for None and non-string NA."""

    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return ""
    return str(value).strip()


def float_nan_text_or_empty(value: object) -> str:
    """Return stripped text, with the empty string for None and float NaN."""

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def aware_utc_timestamp_or_none(value: object) -> pd.Timestamp | None:
    """Return a timezone-aware value as a UTC pd.Timestamp; naive or unparsable input gives None."""

    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.tz_convert("UTC")
