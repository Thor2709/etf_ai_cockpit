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


# --- plain-language text (one formatter for every page that shows an error, reason code, URL or timestamp) ---

import re as _re

_EXCEPTION_PREFIX = _re.compile(r"^\s*(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception|Warning|Failure)\s*:\s*")
_URL = _re.compile(r"https?://(?:www\.)?([^/\s)\]\"'<>]+)[^\s)\]\"'<>]*")
_ISO_STAMP = _re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_CODE_WORD = _re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b(?!=)")
# Whole messages and phrases that read as developer text, with what a user needs to know instead.
_PHRASES: tuple[tuple[_re.Pattern[str], str], ...] = tuple(
    (_re.compile(pattern, _re.IGNORECASE), text)
    for pattern, text in (
        (r"yfinance is not installed\.?(?: Run `pip install yfinance` in the project environment\.?)?",
         "The yfinance price provider is not installed, so prices cannot be refreshed. Install it with “pip install yfinance”."),
        (r"identity projection is unavailable or conflicted",
         "The instrument's listing identity is missing or conflicting, so its market hours cannot be confirmed."),
        (r"complete unambiguous snapshot frames are required",
         "the price and holdings data must be complete and unambiguous"),
        (r"Factor-risk binding unavailable",
         "Factor risk cannot be calculated yet"),
        (r"Yahoo Finance returned no usable price rows",
         "Yahoo Finance returned no usable prices for this instrument"),
    )
)
_REASON_TEXT = {
    "financial_decision_time_unavailable": "the decision date for the financial statements is not available",
    "portfolio_snapshot_not_sealed_or_reconciled": "the portfolio snapshot has not been sealed and reconciled yet",
    "score_numeric_evidence_unavailable": "no numeric score evidence is available",
    "scoreboard_row_missing_for_instrument": "no stored score exists for this instrument yet",
    "scoreboard_store_missing": "no stored scores exist yet",
    "tracking_difference_missing": "tracking difference needs fund and benchmark total-return history",
    "fund_total_return": "fund total return",
    "benchmark_total_return": "benchmark total return",
}


def _readable_code(match: _re.Match[str]) -> str:
    code = match.group(0)
    return _REASON_TEXT.get(code, code.replace("_", " "))


def plain_text(value: object, *, unavailable: str = "Unavailable") -> str:
    """Developer text to plain language: exception prefixes, reason codes, raw URLs and ISO timestamps.

    Display only and idempotent; the stored evidence is never changed. Text that is already plain is returned as is.
    """

    text = str(value if value is not None else "").strip()
    if not text or text.casefold() in {"none", "nan", "nat"}:
        return unavailable
    text = _EXCEPTION_PREFIX.sub("", text)
    for pattern, replacement in _PHRASES:
        text = pattern.sub(replacement, text)
    text = _URL.sub(lambda match: match.group(1), text)
    text = _ISO_STAMP.sub(lambda match: format_timestamp(match.group(0), unavailable=match.group(0)), text)
    text = _CODE_WORD.sub(_readable_code, text)
    return text[:1].upper() + text[1:] if text else text
