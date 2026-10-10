"""Shared layout and formatting helpers of the Research pages (wave 2, packet P3).

Only what two or more P3 pages need: the 12-column grid maths (spec section 1), card inner sizes for the
fixed-size charts, the evidence tag mapping (spec 6.1), signed number text and the cached score list.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Well
from etf_cockpit.app.components.kit._base import txt
from etf_cockpit.app.formatting import format_number, format_percent
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.ui_facade import build_simple_instrument_scores

GAP = 22
COLUMNS = 12
NARROW_WIDTH = 1300  # below this the dock leaves < 1000 px: cards stack in reading order (spec: < 1100 stacks)
MINUS = "−"
# Dock (24 + 84 + 24) on the left and the 24px outer margin on the right.
_SIDE_RESERVED = 156
# Margins and gaps above, between and below the two content rows (top bar 80, footer 48, outer 24, gaps 22).
_VERTICAL_RESERVED = 24 + 80 + GAP + GAP + GAP + 48 + 24
_ROW_A_SHARE = 560 / 958


@dataclass(frozen=True)
class Grid:
    width: float
    row_a: float
    row_b: float
    narrow: bool

    def span(self, columns: int) -> float:
        column = (self.width - GAP * (COLUMNS - 1)) / COLUMNS
        return column * columns + GAP * (columns - 1)


def grid(page: object) -> Grid:
    total_width = float(getattr(page, "width", None) or 1920)
    total_height = float(getattr(page, "height", None) or 1200)
    available = max(total_height - _VERTICAL_RESERVED, 0.0)
    row_a = max(420.0, round(available * _ROW_A_SHARE))
    row_b = max(300.0, available - row_a)
    if total_width < NARROW_WIDTH:  # stacked cards keep their content height instead of sharing the window height
        row_a, row_b = max(row_a, 580.0), max(row_b, 400.0)
    return Grid(width=max(total_width - _SIDE_RESERVED, 320.0), row_a=row_a, row_b=row_b, narrow=total_width < NARROW_WIDTH)


Slot = tuple[int, Callable[[float, float], ft.Control]]


def place(g: Grid, height: float, slots: Sequence[Slot]) -> ft.Control:
    """One grid row: each slot is (columns, builder(width, height)); narrow windows stack the cards."""
    if g.narrow:
        return ft.Column([build(g.width, height) for _, build in slots], spacing=GAP)
    return ft.Row([build(g.span(columns), height) for columns, build in slots], spacing=GAP, vertical_alignment=ft.CrossAxisAlignment.START)


def inner_size(width: float, height: float, *, quiet: bool = False, insight: bool = True, title: bool = True) -> tuple[float, float]:
    """Pixel size left for a body inside a GlassCard of the given outer size."""
    top, side, bottom = theme.CARD_PADDING_QUIET if quiet else theme.CARD_PADDING
    used = top + bottom + (20 + 12 if title else 0) + (25 if insight else 0)
    return max(width - 2 * side, 120.0), max(height - used, 120.0)


def chart_well(chart_builder: Callable[[float, float], ft.Control], width: float, height: float, *, reserve: float = 0.0, **options: bool) -> ft.Control:
    """A chart inside a Well sized to the card body; ``reserve`` leaves room for controls above the well."""
    inner_w, inner_h = inner_size(width, height, **options)
    inner_h = max(inner_h - reserve, 120.0)
    return Well(chart_builder(inner_w, inner_h), width=inner_w, height=inner_h)


def fit(child: ft.Control, width: float, height: float, **options: bool) -> ft.Container:
    """Give a card body exactly the inner size of its card; overflow scrolls inside ``child``."""
    inner_w, inner_h = inner_size(width, height, **options)
    return ft.Container(content=child, width=inner_w, height=inner_h)


def link(label: str, on_click: Callable[[object], object], *, key: str | None = None) -> ft.Container:
    """Text button in the accent colour (spec: "View all gates")."""
    return ft.Container(
        content=txt(label, 13, 600, theme.ACC, trunc=True),
        on_click=on_click,
        ink=True,
        ink_color=theme.HOVER_OVERLAY,
        border_radius=theme.RADIUS_SM,
        padding=ft.Padding(left=0, top=0, right=0, bottom=0),
        key=key,
    )


def open_route(page: object, state: object, route: str, instrument_id: str | None = None) -> None:
    """Navigate to a route, optionally selecting an instrument first; never starts any workflow."""
    if instrument_id:
        state.selected_etf = instrument_id
    go = getattr(page, "go", None)
    if callable(go):
        go(route)
    else:
        page.route = route


def text(value: str, size: float = theme.FONT_MD, wt: int = 400, color: str = theme.INK, **kwargs: object) -> ft.Text:
    return txt(value, size, wt, color, trunc=True, **kwargs)


def below_fold(g: Grid, rows: Sequence[ft.Control]) -> ft.Control:
    """Page body: the first screen rows, then the below-the-fold sections, scrolling as one column."""
    return ft.Column(list(rows), spacing=GAP, scroll=ft.ScrollMode.AUTO, expand=True, width=g.width)


def signed(value: float | None, decimals: int = 1, unit: str = "%", *, ratio: bool = False) -> str | None:
    """Signed text with the true minus; ``ratio=True`` multiplies by 100 first. None stays None."""
    if value is None or pd.isna(value):
        return None
    number = float(value) * (100.0 if ratio else 1.0)
    body = format_number(abs(number), decimals=decimals)
    return f"{'+' if number > 0 else MINUS if number < 0 else ''}{body}{unit}"


def percent(value: float | None, decimals: int = 1) -> str | None:
    """Plain percent of a ratio (12.3%), None when missing."""
    if value is None or pd.isna(value):
        return None
    return format_percent(value, decimals=decimals).replace("-", MINUS)


def tone_of(value: float | None) -> str | None:
    if value is None or pd.isna(value) or value == 0:
        return None
    return "pos" if value > 0 else "neg"


_TAGS = (
    (("strong_evidence_candidate",), ("Strong", "ok")),
    (("positive_evidence_candidate", "research_candidate", "add_candidate"), ("Good", "ok")),
    (("watchlist",), ("Watchlist", "ok")),
    (("hold_context", "mixed_evidence_review", "maintain_review", "increase_exposure_review"), ("Mixed", "warn")),
    (("weak_evidence_review", "low_quality_manual_review"), ("Review", "warn")),
    (("not_backtested_candidate",), ("Untested", "warn")),
    (("reduce_exposure_review", "trim_candidate"), ("Weak", "bad")),
    (("pending_refresh",), ("Pending", "mute")),
)


def is_scorecard_owned(score: object) -> bool:
    """True for a Sparebank row whose score comes from the native scorecard, not the generic gates."""

    return str(getattr(score, "final_label", "") or "").casefold() == "scorecard_owned"


def evidence_tag(score: object) -> tuple[str, str]:
    """Canonical final_label to (tag text, kind), spec 6.1 mapping; a failed hard gate is Blocked."""
    gates = getattr(getattr(score, "authority_decision", None), "gates", ()) or ()
    if any(not getattr(gate, "passed", True) and str(getattr(gate, "severity", "")).casefold() in {"blocking", "block", "error"} for gate in gates):
        return "Blocked", "bad"
    label = str(getattr(score, "final_label", "") or "")
    if is_scorecard_owned(score):
        # Banks are scored by the native Sparebank scorecard; the generic evidence label does not apply.
        return ("Scorecard", "ok") if getattr(score, "final_score_10", None) is not None else ("No composite", "mute")
    for names, result in _TAGS:
        if label in names:
            return result
    if str(getattr(score, "final_action", "")) == "manual_review":
        return "Review", "warn"
    return (label.replace("_", " ").capitalize() or "Unavailable"), "mute"


def verdict_word(tag: str) -> str:
    return "Qualifies" if tag in {"Strong", "Good"} else tag


_SCORE_CACHE: dict[str, object] = {}


def instrument_meta(state: object, key: str) -> dict[str, str]:
    """Display facts of one configured instrument (name, currency, venue, type, TER text); missing stays explicit."""
    etfs = getattr(getattr(getattr(getattr(state, "snapshot", None), "config", None), "universe", None), "etfs", ()) or ()
    for etf in etfs:
        if etf.id == key:
            return {
                "name": etf.name,
                "currency": etf.currency or "—",
                "venue": etf.exchange or "listing venue unavailable",
                "type": etf.instrument_type,
                "ter": "" if etf.ter is None else f"{etf.ter * 100:.2f}%",
            }
    return {"name": key, "currency": "—", "venue": "listing venue unavailable", "type": "", "ter": ""}


def scores_for(state: object) -> list[object]:
    """Canonical score rows for the current snapshot (shared cache in application.score_views)."""
    from etf_cockpit.application.score_views import snapshot_scores

    return snapshot_scores(state.snapshot, str(getattr(state, "universe_cache_revision", "") or ""))


def remember_instrument(state: object, instrument_id: str) -> list[str]:
    """Most recently viewed instruments, newest first (kept on the app state, never persisted)."""
    recent = [item for item in getattr(state, "recent_instruments", []) if item != instrument_id]
    recent.insert(0, instrument_id)
    try:
        state.recent_instruments = recent[:5]
    except AttributeError:
        pass
    return recent[:5]


def segment_ids(state: object, current: str, known: Sequence[str]) -> list[str]:
    """Current instrument plus recently viewed ones, topped up from the list so there is always a choice."""
    others = [item for item in getattr(state, "recent_instruments", []) if item != current and item in known]
    for item in known:
        if len(others) >= 3:
            break
        if item != current and item not in others:
            others.append(item)
    return [current, *others[:3]]


def update(page: object) -> None:
    refresh = getattr(page, "update", None)
    if callable(refresh):
        refresh()
