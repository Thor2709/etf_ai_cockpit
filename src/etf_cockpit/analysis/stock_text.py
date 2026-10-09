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
    return f"{label} {times(own_n)} is {relation} the peer median {times(med_n)} ({count} peer{'' if count == 1 else 's'}, instrument excluded)."


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


def _metric_phrase(metric: object, formatter, label: str) -> tuple[str, str | None]:
    """(phrase, reason): the formatted value, or the label with the stored reason."""

    value = getattr(metric, "value", None)
    if value is not None and getattr(metric, "status", "") == "ok":
        return f"{label} {formatter(value)}", None
    return label, str(getattr(metric, "reason", None) or "unavailable")


def _group(label: str, parts: Sequence[tuple[str, str | None]]) -> str:
    have = [phrase for phrase, reason in parts if reason is None]
    missing = [f"{phrase} ({reason})" for phrase, reason in parts if reason is not None]
    text = ""
    if have:
        text = f"{label}: " + join_list(have) + "."
    if missing:
        text += (" " if text else f"{label}: ") + "Unavailable: " + "; ".join(missing) + "."
    return text


def describe_stock(evidence: object, text_config: Mapping[str, object], history_years: int = 5) -> list[str]:
    """Plain-language paragraphs from the evidence numbers (templates only; every gap keeps its reason)."""

    m = evidence.metrics  # type: ignore[attr-defined]
    ccy = getattr(evidence, "reporting_currency", None)
    out: list[str] = []
    basis = m["revenue"].basis or m["ebit_margin"].basis
    as_of = m["revenue"].as_of or m["ebit_margin"].as_of
    period = f" ({basis} to {as_of})" if basis and as_of else ""
    out.append(
        _group(
            "Profitability" + period,
            [_metric_phrase(m["ebit_margin"], pct, "EBIT margin"), _metric_phrase(m["net_margin"], pct, "net margin"), _metric_phrase(m["roe"], pct, "ROE"), _metric_phrase(m["roic"], pct, "ROIC")],
        )
    )
    out.append(
        _group(
            "Balance sheet and cash",
            [_metric_phrase(m["net_debt_to_ebitda"], times, "net debt / EBITDA"), _metric_phrase(m["debt_to_equity"], times, "debt / equity"), _metric_phrase(m["fcf_conversion"], pct, "FCF / net income")],
        )
    )
    out.append(_group("Growth", [_metric_phrase(m["revenue_cagr"], pct, "revenue CAGR"), _metric_phrase(m["net_income_cagr"], pct, "net income CAGR")]))
    cap = m["market_cap"]
    cap_text = f"at a market cap of {money(cap.value, ccy)}" if cap.value is not None else "market cap unavailable (" + str(cap.reason) + ")"
    out.append(
        _group(
            f"Valuation {cap_text}",
            [_metric_phrase(m["pe"], times, "P/E"), _metric_phrase(m["ev_ebit"], times, "EV/EBIT"), _metric_phrase(m["fcf_yield"], pct, "FCF yield"), _metric_phrase(m["dividend_yield"], pct, "dividend yield")],
        )
    )
    percentile = m["pe_percentile"]
    cheap, dear = float(text_config.get("percentile_cheap", 0.25)), float(text_config.get("percentile_expensive", 0.75))
    if percentile.value is not None:
        out.append(percentile_sentence("P/E", percentile.value, int(getattr(evidence, "history_points", 0)), history_years, cheap, dear))
    else:
        out.append(unavailable_line("P/E versus its own history", percentile.reason))
    stat = evidence.peer_stats.get("pe")  # type: ignore[attr-defined]
    if stat is not None and stat.median is not None and stat.own is not None and stat.count and m["pe_vs_peers"].status == "ok":
        out.append(peer_sentence("P/E", stat.own, stat.median, stat.count, float(text_config.get("peer_premium_pct", 0.10))))
    else:
        out.append(unavailable_line("P/E versus peers", m["pe_vs_peers"].reason))
    growth = m["implied_growth_pe"]
    if growth.value is not None:
        out.append(f"Reverse valuation: the P/E implies about {pct(growth.value)} growth at the configured cost of equity.")
    else:
        out.append(unavailable_line("Reverse valuation", growth.reason))
    out.extend(str(note) for note in getattr(evidence, "notes", ()))
    return [line for line in out if line]
