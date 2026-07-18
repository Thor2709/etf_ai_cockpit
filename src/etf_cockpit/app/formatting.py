from __future__ import annotations

from datetime import date, datetime
import math


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def format_number(value: object, *, decimals: int = 2, unavailable: str = "N/A") -> str:
    number = _number(value)
    if number is None:
        return unavailable
    return f"{number:,.{max(0, int(decimals))}f}"


def format_percent(value: object, *, decimals: int = 1, unavailable: str = "N/A") -> str:
    number = _number(value)
    if number is None:
        return unavailable
    return f"{number * 100:.{max(0, int(decimals))}f}%"


def format_currency(value: object, *, currency: str = "EUR", decimals: int = 2, unavailable: str = "N/A") -> str:
    number = _number(value)
    if number is None:
        return unavailable
    return f"{currency} {number:,.{max(0, int(decimals))}f}"


def format_date(value: object, *, unavailable: str = "N/A") -> str:
    if value is None or str(value).strip().casefold() in {"", "none", "nan", "nat"}:
        return unavailable
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip() or unavailable
