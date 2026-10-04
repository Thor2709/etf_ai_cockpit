"""Generic value-coercion helpers shared by every layer (finite numbers, text, flags, UTC timestamps).

Several functions behave identically and differ only in local variable names or in how finiteness is
tested; they stay separate objects so the P9d proof can show bytecode equality per original group.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from math import isfinite
from numbers import Real

import numpy as np
import pandas as pd


def finite_float_or_none(value: object) -> float | None:
    """Return float(value) when it is finite, else None; bool coerces like int."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_finite_float(value: object) -> float | None:
    """Return float(value) when it is finite, else None (same behaviour as finite_float_or_none)."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def finite_float_isfinite(value: object) -> float | None:
    """Return float(value) when math.isfinite accepts it, else None (same behaviour as finite_float_or_none)."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def finite_float_numpy(value: object) -> float | None:
    """Return float(value) when np.isfinite accepts it, else None (same behaviour as finite_float_or_none)."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def finite_non_bool_float_or_none(value: object) -> float | None:
    """Return float(value) when finite; bool, non-numeric and overflowing input give None."""

    if isinstance(value, bool):
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def finite_non_bool_number_or_none(value: object) -> float | None:
    """Return float(value) when finite; bool, non-numeric and overflowing input give None (same behaviour as finite_non_bool_float_or_none)."""

    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def is_finite_number(value: object) -> bool:
    """Return True when float(value) succeeds and is finite."""

    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def finite_real_or_none(value: object) -> float | None:
    """Return float(value) for a finite non-bool numbers.Real, else None."""

    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


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


def mapping_or_attribute(value: object, name: str, default: object = None) -> object:
    """Read name from a Mapping by key or from any other object by attribute."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def dict_or_empty(value: object) -> dict[str, object]:
    """Coerce a mapping or pair sequence to a dict, returning {} on any failure."""

    try:
        if value is None:
            return {}
        if hasattr(value, "items"):
            return dict(value.items())
        return dict(value)  # type: ignore[arg-type]
    except Exception:
        return {}


def string_dict_or_empty(value: object) -> dict[str, str]:
    """Coerce a mapping-like value to a dict of str to str, returning {} when it has no usable keys."""

    if isinstance(value, Mapping):
        return {str(key): str(item) for key, item in value.items()}
    try:
        return {str(key): str(value[key]) for key in value.keys()}  # type: ignore[union-attr]
    except (AttributeError, KeyError, TypeError):
        return {}


def aware_utc_timestamp_or_none(value: object) -> pd.Timestamp | None:
    """Return a timezone-aware value as a UTC pd.Timestamp; naive or unparsable input gives None."""

    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.tz_convert("UTC")


def positive_int_or_none(value: object) -> int | None:
    """Return value when it is a non-bool int of at least 1, else None."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def is_lowercase_sha256_hex(value: object) -> bool:
    """Return True for a 64-character lowercase hexadecimal SHA-256 digest string."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
