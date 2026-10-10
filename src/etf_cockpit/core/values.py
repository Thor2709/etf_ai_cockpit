"""Generic value-coercion helpers shared by every layer (finite numbers, mappings, checksums); no pandas import.

Helpers that need pandas live in :mod:`etf_cockpit.core.pandas_values`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date
from numbers import Real



def years_before(value: date, years: int) -> date:
    """Return the same calendar day ``years`` earlier, clamping leap day to February 28."""

    target_year = value.year - years
    try:
        return value.replace(year=target_year)
    except ValueError:
        return value.replace(month=2, day=28, year=target_year)


def finite_float_or_none(value: object) -> float | None:
    """Return float(value) when it is finite, else None; bool coerces like int."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def all_finite_or_none(values: Iterable[object]) -> tuple[float, ...] | None:
    """Return every item as a finite float, or None when any single item is missing or not finite."""

    numbers = tuple(finite_float_or_none(value) for value in values)
    return None if any(number is None for number in numbers) else numbers  # type: ignore[return-value]


def finite_non_bool_float_or_none(value: object) -> float | None:
    """Return float(value) when finite; bool, non-numeric and overflowing input give None."""

    if isinstance(value, bool):
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


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
