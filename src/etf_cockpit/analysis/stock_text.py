"""Deterministic number formatting and plain-language text for the stock pages (templates, no LLM).

Every sentence is assembled from numbers that are already computed; a missing number produces
the stored reason, never an invented value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def num(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def pct(value: object, digits: int = 1) -> str:
    number = num(value)
    return "—" if number is None else f"{number * 100:.{digits}f}%"


def times(value: object, digits: int = 1) -> str:
    number = num(value)
    return "—" if number is None else f"{number:.{digits}f}x"


def money(value: object, currency: str | None = None) -> str:
    number = num(value)
    if number is None:
        return "—"
    magnitude = abs(number)
    for limit, suffix in ((1e12, "tn"), (1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if magnitude >= limit:
            text = f"{number / limit:,.2f}{suffix}"
            break
    else:
        text = f"{number:,.0f}"
    return f"{text} {currency}".strip() if currency else text


def score(value: object) -> str:
    number = num(value)
    return "—" if number is None else f"{number:.1f}"


def ordinal(value: int) -> str:
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def join_list(items: Sequence[str]) -> str:
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def percentile_sentence(label: str, percentile: object, points: int, window_years: int, cheap: float, dear: float) -> str:
    value = num(percentile)
    if value is None:
        return ""
    rank = int(round(value * 100))
    where = "in the cheaper part" if value <= cheap else "in the dearer part" if value >= dear else "around the middle"
    return f"{label} is {where} of its own {window_years}-year range ({ordinal(rank)} percentile of {points} month-end readings)."


def peer_sentence(label: str, own: object, median: object, count: int, premium_pct: float) -> str:
    own_n, med_n = num(own), num(median)
    if own_n is None or med_n is None or med_n == 0 or count <= 0:
        return ""
    gap = own_n / med_n - 1.0
    if abs(gap) < premium_pct:
        relation = "in line with"
    else:
        relation = f"{abs(gap) * 100:.0f}% {'above' if gap > 0 else 'below'}"
    return f"{label} {times(own_n)} is {relation} the peer median {times(med_n)} ({count} peers, instrument excluded)."


def unavailable_line(label: str, reason: object) -> str:
    return f"{label}: unavailable — {reason}"


def score_headline(
    score_10: object,
    coverage: object,
    used: int,
    total: int,
    missing: Mapping[str, str],
    strong: float,
    weak: float,
) -> str:
    value = num(score_10)
    cov = num(coverage)
    if value is None:
        return "No score: " + (join_list([f"{name} ({reason})" for name, reason in missing.items()]) or "no scoring input is available") + "."
    verdict = "strong" if value >= strong else "weak" if value <= weak else "mixed"
    text = f"Evidence score {value:.1f} of 10 ({verdict}), built from {used} of {total} components"
    if cov is not None:
        text += f" ({cov * 100:.0f}% of the configured weight)"
    text += "."
    if missing:
        text += " Not included: " + join_list([f"{name} ({reason})" for name, reason in missing.items()]) + "."
    return text
