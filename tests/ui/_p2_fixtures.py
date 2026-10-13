"""Illustrative Sectors & Countries data for tests and render checks (the reference screen's shape; not real values)."""

from __future__ import annotations

import math

from etf_cockpit.application.ui_views import sectors as view

_COUNTRIES = (
    ("United States of America", 62.0, 12.0), ("Japan", 5.5, 9.0), ("United Kingdom", 3.6, 6.0), ("Canada", 2.9, 11.0),
    ("China", 2.8, 22.0), ("France", 2.5, 7.0), ("Switzerland", 2.2, 4.0), ("Germany", 2.1, 8.0),
    ("Australia", 1.8, 5.0), ("Netherlands", 1.5, 10.0), ("India", 1.3, 14.0), ("Taiwan", 1.2, 18.0),
)
_SECTORS = (
    ("Technology", 25.4, 21.0, None), ("Financials", 16.1, 9.0, None), ("Industrials", 11.2, 12.0, None), ("Health Care", 10.8, -3.0, None),
    ("Consumer Discretionary", 10.3, 6.0, "Cons. Disc."), ("Communication Services", 7.4, 5.0, "Comm."), ("Consumer Staples", 6.1, -4.0, "Staples"),
    ("Energy", 4.2, -6.0, None), ("Materials", 3.6, 2.0, None), ("Real Estate", 2.2, -2.0, "RE"), ("Utilities", 2.7, 1.0, None),
)
_GROUPS = ("Tech", "Financials", "Health", "Industrials", "Energy", "Other")


def _countries() -> list[view.Weight]:
    items = []
    for name, weight, ret in _COUNTRIES:
        code = view.iso3_of(name)
        items.append(view.Weight(view.display_name(code, name), weight, ret, code, view.country_short(code, name)))
    return items


def _sectors() -> list[view.Weight]:
    return [view.Weight(name, weight, ret, None, short or name, (("VWCE", weight * 0.6), ("SPYK", weight * 0.4))) for name, weight, ret, short in _SECTORS]


def _bubbles() -> list[view.Bubble]:
    points = []
    for index in range(70):
        angle = index * 2.399963
        pe = 8 + (index * 7919 % 4400) / 100.0
        roe = 4 + 20 * (1 + math.sin(angle)) + (index % 7)
        group = _GROUPS[index % len(_GROUPS)]
        ret = -30 + (index * 37 % 90) + 5 * math.cos(angle)
        points.append(view.Bubble(f"Company {index + 1}", pe, 1 + pe / 6, roe, 5e9 + (index * 104729 % 90) * 1e9, group, ret))
    points.append(view.Bubble("ASML", 36.0, 12.0, 48.0, 250e9, "Tech", 18.0, True))
    points.append(view.Bubble("Sparebank 1", 9.5, 1.1, 12.0, 20e9, "Financials", 7.0, True))
    return points


def reference_view(window: str = "1Y") -> view.SectorsView:
    return view.SectorsView(countries=_countries(), sectors=_sectors(), companies=[], benchmark_top_country=58.9, bubbles=_bubbles(), window=window)


def install(_snapshot: object) -> None:
    """Render-harness hook: make the page load the illustrative view."""
    view.load = lambda _snapshot, window="1Y", **_kw: reference_view(window)  # type: ignore[assignment]
