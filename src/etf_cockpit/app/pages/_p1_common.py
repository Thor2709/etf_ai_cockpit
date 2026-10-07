"""Small layout and wiring helpers shared by the Home/Changes/Help page group (P1)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Button
from etf_cockpit.app.components.kit._base import txt

# Semantic dot names used by the view models that the kit ListRow does not know itself.
DOT_TOKENS = {"mute": theme.INK3}
NARROW_WIDTH = 1100
MEDIUM_WIDTH = 1300
NOTE_MIN_CARD_WIDTH = 480
GAP = 22
MIN_ROW_HEIGHTS = (420, 300, 300, 300)
# Card chrome inside a GlassCard: padding 24/24/20, title row 20, insight 8 + 17, body gap 12.
_CARD_SIDE = 24
_CARD_TOP_BOTTOM = 24 + 20


def text(value: str, size: float = 13.5, weight: int = 400, color: str = theme.INK, **kwargs: object) -> ft.Text:
    """Typed text with the spec typography (thin wrapper over the kit helper)."""
    return txt(value, size, weight, color, **kwargs)


def workflow_button(
    label: str,
    *,
    key_name: str,
    on_click: Callable[[object], object],
    primary: bool = False,
    disabled: bool = False,
    disabled_reason: str | None = None,
    **_unused: object,
) -> ft.Control:
    """Kit button with a stable acceptance key (call it as ``_workflow_button`` so source discovery sees it)."""
    factory = Button.primary if primary else Button.secondary
    return factory(label, on_click, key=key_name, disabled=disabled, disabled_reason=disabled_reason)


def go(page: object, state: object, route: str) -> None:
    from etf_cockpit.app.router import navigate_to

    navigate_to(page, state, route)  # type: ignore[arg-type]


def refresh(control: ft.Control) -> None:
    """Update a control that may not be attached to a page yet (tests, first build)."""
    try:
        control.update()
    except RuntimeError:
        pass


@dataclass(frozen=True)
class GridLayout:
    """12-column grid sizes for a page (spec 1): rows scale with the window, never below their minimum."""

    width: float
    height: float
    row_heights: tuple[float, ...]
    narrow: bool

    @property
    def medium(self) -> bool:
        """Between the narrow breakpoint and 1300px of main area: cards share rows more sparingly."""
        return not self.narrow and self.width < MEDIUM_WIDTH

    def with_row(self, height: float) -> "GridLayout":
        return GridLayout(self.width, self.height, (*self.row_heights, height), self.narrow)

    def card_note(self, span: int, note: str) -> str:
        """Header notes need room next to the title (text protection): drop them from cards under 480px."""
        return note if self.span_width(span) >= NOTE_MIN_CARD_WIDTH else ""

    def span_width(self, span: int) -> float:
        if self.narrow:
            return self.width
        column = (self.width - 11 * GAP) / 12
        return span * column + (span - 1) * GAP

    def card_body(self, span: int, row: int, *, insight: bool = False, has_note: bool = True) -> tuple[float, float]:
        """Inner (width, height) available to a chart under the card header."""
        header = 20 + 12 + (25 if insight else 0)
        return (
            max(120.0, self.span_width(span) - 2 * _CARD_SIDE),
            max(120.0, self.row_heights[row] - _CARD_TOP_BOTTOM - header),
        )


def make_layout(page: object, *, reference_rows: Sequence[float] = (560, 398), chrome: float = 80 + 48 + 2 * GAP) -> GridLayout:
    """Compute sizes from the window (``page.width`` x ``page.height``; 1920x1200 when unknown)."""
    window_w = float(getattr(page, "width", None) or 1920)
    window_h = float(getattr(page, "height", None) or 1200)
    narrow = window_w < NARROW_WIDTH
    main_w = window_w - (24 + 64 + 24 + 24 if narrow else 24 + 84 + 24 + 24)
    available = window_h - 2 * 24 - chrome - GAP * (len(reference_rows) - 1)
    scale = available / sum(reference_rows)
    heights = tuple(max(float(MIN_ROW_HEIGHTS[i]), round(ref * scale)) for i, ref in enumerate(reference_rows))
    return GridLayout(main_w, window_h, heights, narrow)


def grid(
    layout: GridLayout,
    rows: Sequence[Sequence[tuple[ft.Control, int]]],
    *,
    below: Sequence[ft.Control] = (),
) -> ft.Column:
    """Rows of ``(card, column span)``; narrow layouts stack cards in reading order at full width."""
    out: list[ft.Control] = []
    for index, cells in enumerate(rows):
        height = layout.row_heights[index]
        if layout.narrow:
            out.extend(ft.Container(content=card, height=height) for card, _span in cells)
            continue
        out.append(
            ft.Container(
                content=ft.Row(
                    [ft.Container(content=card, expand=span) for card, span in cells],
                    spacing=GAP,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                height=height,
            )
        )
    out.extend(below)
    return ft.Column(out, spacing=GAP, scroll=ft.ScrollMode.AUTO, expand=True)


def with_edge_fade(scrolling: ft.Control, *, fade_height: int = 24) -> ft.Control:
    """Overlay a bottom edge fade on a scrolling list so clipped rows read as scrollable (rulebook V9)."""
    fade = ft.Container(
        left=0,
        right=0,
        bottom=0,
        height=fade_height,
        gradient=ft.LinearGradient(
            colors=[theme.rgba(9, 16, 32, 0), theme.rgba(9, 16, 32, 0.85)],
            begin=ft.Alignment(0, -1),
            end=ft.Alignment(0, 1),
        ),
        ignore_interactions=True,
    )
    return ft.Stack([scrolling, fade], expand=True)


def labelled(label: str, control: ft.Control, *, expand: bool | int = False) -> ft.Column:
    """Uppercase field label above a control that brings its own surface (Segmented, Toggle)."""
    return ft.Column(
        [text(label, 11, 600, theme.INK3, tracking=0.08, upper=True, trunc=True), control],
        spacing=4,
        tight=True,
        expand=expand,
    )


def field_pair(left: ft.Control, right: ft.Control | None = None) -> ft.Row:
    """Two-column form row (gap 12)."""
    cells = [ft.Container(content=left, expand=1)]
    cells.append(ft.Container(content=right, expand=1) if right is not None else ft.Container(expand=1))
    return ft.Row(cells, spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)
