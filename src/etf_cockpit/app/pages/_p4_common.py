"""Small layout and wiring helpers shared by the Portfolio/Lab page group (P4)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Button, KpiTile, Tag
from etf_cockpit.app.components.kit._base import txt
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup

NARROW_WIDTH = 1300  # below this the dock leaves < 1000 px: cards stack in reading order (spec: < 1100 stacks)
GAP = 22
MIN_ROW_HEIGHTS = (420, 300, 300, 300)
NARROW_ROW_HEIGHTS = (580, 400, 400, 400)
# Card chrome inside a GlassCard: padding 24/24/20, title row 20, insight 8 + 17, body gap 12.
_CARD_SIDE = 24
_CARD_TOP_BOTTOM = 24 + 20
STRIP_HEIGHT = 100


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


def refresh(control: ft.Control) -> None:
    """Update a control that may not be attached to a page yet (tests, first build)."""
    try:
        control.update()
    except RuntimeError:
        pass


def tag_kind(status: object) -> str:
    """Fixed tag colour mapping (spec 3.4): pass = ok, attention = warn, failed/missing = bad, else mute."""
    word = str(status or "").strip().lower()
    if word in {"ok", "pass", "passed", "available", "fresh", "clean", "ready", "good", "success", "true", "yes", "healthy"}:
        return "ok"
    if word in {"warn", "warning", "stale", "review", "fair", "shadow", "shadow_only", "partial", "pending", "running", "queued"}:
        return "warn"
    if word in {"fail", "failed", "missing", "weak", "none", "unavailable", "poor", "error", "blocked", "false", "no", "disabled", "conflicted"}:
        return "bad"
    return "mute"


def status_tag(status: object, *, dense: bool = False) -> ft.Control:
    label = str(status) if status not in (None, "") else "—"
    return Tag(label, tag_kind(status), dense=dense)


def tile_grid(tiles: Sequence[tuple[str, object, str, str | None]], *, columns: int = 2) -> ft.Control:
    """Rows of ``KpiTile`` (label, value or None, sub, tone); a missing value reads Unavailable + the sub as reason."""
    rows: list[ft.Control] = []
    for start in range(0, len(tiles), columns):
        chunk = tiles[start : start + columns]
        cells: list[ft.Control] = [
            KpiTile(label, None if value in (None, "") else str(value), sub, tone=tone, expand=True)
            for label, value, sub, tone in chunk
        ]
        rows.append(ft.Row(cells, spacing=12))
    return ft.Column(rows, spacing=12)


@dataclass(frozen=True)
class GridLayout:
    """12-column grid sizes for a page (spec 1): rows scale with the window, never below their minimum."""

    width: float
    height: float
    row_heights: tuple[float, ...]
    narrow: bool
    strip: bool = False

    def span_width(self, span: int) -> float:
        if self.narrow:
            return self.width
        column = (self.width - 11 * GAP) / 12
        return span * column + (span - 1) * GAP

    def card_body(self, span: int, row: int, *, insight: bool = False) -> tuple[float, float]:
        """Inner (width, height) available to a chart under the card header."""
        header = 20 + 12 + (25 if insight else 0)
        return (
            max(120.0, self.span_width(span) - 2 * _CARD_SIDE),
            max(120.0, self.row_heights[row] - _CARD_TOP_BOTTOM - header),
        )


def make_layout(page: object, *, strip: bool = False) -> GridLayout:
    """Compute sizes from the window (``page.width`` x ``page.height``; 1920x1200 when unknown).

    Standard rows 560:398; the KPI-strip variant (100, 440, 396) puts the strip in row 0.
    """
    window_w = float(getattr(page, "width", None) or 1920)
    window_h = float(getattr(page, "height", None) or 1200)
    narrow = window_w < NARROW_WIDTH
    main_w = window_w - (24 + 84 + 24 + 24)
    reference = (STRIP_HEIGHT, 440, 396) if strip else (560, 398)
    chrome = 80 + 48 + 2 * GAP
    available = window_h - 2 * 24 - chrome - GAP * (len(reference) - 1)
    scale = available / sum(reference)
    mins = (STRIP_HEIGHT, 420, 300) if strip else MIN_ROW_HEIGHTS
    if narrow:  # stacked cards keep their content height instead of sharing the window height
        mins = (STRIP_HEIGHT, *NARROW_ROW_HEIGHTS[:2]) if strip else NARROW_ROW_HEIGHTS
    heights = tuple(
        float(STRIP_HEIGHT) if strip and index == 0 else max(float(mins[index]), round(ref * scale))
        for index, ref in enumerate(reference)
    )
    return GridLayout(main_w, window_h, heights, narrow, strip)


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
    return ft.Column(out, spacing=GAP, scroll=ft.ScrollMode.HIDDEN, expand=True)


def page_view(
    title: str,
    subtitle: str,
    body: ft.Control,
    groups: Sequence[SegmentGroup] = (),
) -> PageView:
    return PageView(chrome=PageChrome(title, subtitle, tuple(groups)), body=body)


class ViewHost:
    """A container whose content is swapped in place by a segment change (never navigates)."""

    def __init__(self, builders: dict[str, Callable[[], ft.Control]], selected: str) -> None:
        self.builders = builders
        self.selected = selected
        self.control = ft.Column([builders[selected]()], spacing=GAP)

    def select(self, name: str) -> None:
        if name not in self.builders:
            return
        self.selected = name
        self.control.controls = [self.builders[name]()]
        refresh(self.control)


def unavailable_card_text(reason: str) -> str:
    return f"Unavailable: {reason}"


def dropdown(*, key: str, options: Sequence[str | tuple[str, str]], value: str | None, on_select: Callable[[object], object] | None = None, width: float | None = None, disabled: bool = False) -> ft.Dropdown:
    """Borderless dropdown for a kit ``Field(control=...)``; options are ``value`` or ``(value, label)``."""
    items = [ft.dropdown.Option(key=item[0], text=item[1]) if isinstance(item, tuple) else ft.dropdown.Option(item) for item in options]
    return ft.Dropdown(
        key=key,
        value=value,
        options=items,
        on_select=on_select,
        disabled=disabled,
        width=width,
        dense=True,
        border=ft.InputBorder.NONE,
        text_size=14,
        color=theme.INK,
        content_padding=ft.Padding(left=0, top=0, right=0, bottom=0),
        text_style=ft.TextStyle(size=theme.FONT_MD, color=theme.INK, font_family=theme.FONT_FAMILY),
    )


def text_input(*, key: str, value: str = "", hint: str = "", on_change: Callable[[object], object] | None = None, multiline: bool = False, mono: bool = False, tooltip: str | None = None, max_lines: int | None = None) -> ft.TextField:
    """Borderless TextField for a kit ``Field(control=...)``."""
    from etf_cockpit.app.components.kit import field_input_style

    style = field_input_style(multiline=multiline, placeholder=hint)
    if mono:
        style["text_style"] = ft.TextStyle(size=theme.FONT_SM, color=theme.INK, font_family=theme.FONT_MONO)
    field = ft.TextField(key=key, value=value, on_change=on_change, tooltip=tooltip, **style)
    if max_lines is not None:
        field.max_lines = max_lines
    return field


class Popover:
    """A glass panel over a card, opened by a small text button (never navigates, never starts a workflow)."""

    def __init__(self, heading: str, content: ft.Control, *, width: float = 320, top: float = 52, right: float = 24) -> None:
        from etf_cockpit.app.components.kit import Well

        panel = Well(ft.Column([text(heading, theme.FONT_XS, 700, theme.INK2), content], spacing=8, tight=True), padding=12, width=width)
        self.control = ft.Container(content=panel, top=top, right=right, visible=False)

    def toggle(self, _event: object = None) -> None:
        self.control.visible = not self.control.visible
        refresh(self.control)


def menu_button(label: str, on_click: Callable[[object], object], *, key: str | None = None) -> ft.Container:
    """Small text button with a caret, used in a card's note slot to open a popover."""
    return ft.Container(
        content=text(f"{label} ▾", 12, 600, theme.ACC, trunc=True),
        on_click=on_click,
        ink=True,
        ink_color=theme.HOVER_OVERLAY,
        padding=ft.Padding(left=8, top=4, right=8, bottom=4),
        key=key,
    )


def with_popovers(card: ft.Control, width: float, height: float | None, *popovers: Popover) -> ft.Control:
    """Stack the popover panels over a fixed-size card."""
    return ft.Stack([card, *[p.control for p in popovers]], width=width, height=height)
