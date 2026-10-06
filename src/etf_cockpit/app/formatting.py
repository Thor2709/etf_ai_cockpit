from __future__ import annotations

from datetime import date, datetime
from etf_cockpit.core.values import finite_float_or_none as _number


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


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_count(value: object, *, unavailable: str = "N/A") -> str:
    """Whole-number display with thousands separators; never zero-fills missing values."""
    number = _number(value)
    if number is None:
        return unavailable
    return f"{round(number):,}"


def format_timestamp(value: object, *, unavailable: str = "N/A") -> str:
    """Render an ISO timestamp as British day-month-year text (e.g. 2 Oct 2026, 14:05 UTC).

    Display only. Unparseable text is returned unchanged so no evidence is hidden.
    """
    if value is None or str(value).strip().casefold() in {"", "none", "nan", "nat"}:
        return unavailable
    parsed: datetime | None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError:
            return text
    stamp = f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}, {parsed:%H:%M}"
    offset = parsed.utcoffset()
    if parsed.tzinfo is None:
        return stamp
    if offset is not None and offset.total_seconds() == 0:
        return f"{stamp} UTC"
    return f"{stamp} {parsed:%z}"
