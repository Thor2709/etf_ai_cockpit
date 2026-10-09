"""Surface components: GlassCard, Well, FloatingPanel, CardMenu, SectionHeader, Note, EmptyState."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import flet as ft
import flet.canvas as cv

from etf_cockpit.app import theme
from etf_cockpit.app.components.chartkit.core import text_width
from etf_cockpit.app.components.kit._base import (
    diagonal_gradient,
    drops,
    pad,
    ring,
    sym,
    tag_semantics,
    txt,
    vgradient,
)

_RIM_COLORS = [colour for _, colour in theme.GLASS_RIM_STOPS]
_RIM_STOPS = [stop for stop, _ in theme.GLASS_RIM_STOPS]


def _rim_overlay(radius: float) -> cv.Canvas:
    """Draw the 1px gradient light edge over the card; redrawn when the card is resized."""
    canvas = cv.Canvas(left=0, top=0, right=0, bottom=0, shapes=[], resize_interval=80)

    def redraw(event: cv.CanvasResizeEvent) -> None:
        if hasattr(canvas, "_frozen") or getattr(canvas, "_parent", None) is None:
            return
        width, height = float(event.width), float(event.height)
        if width < 4 or height < 4:
            return
        canvas.shapes = [
            cv.Rect(
                0.5,
                0.5,
                width - 1,
                height - 1,
                border_radius=radius - 0.5,
                paint=ft.Paint(
                    style=ft.PaintingStyle.STROKE,
                    stroke_width=1,
                    gradient=ft.PaintLinearGradient((0, 0), (width * 0.42, height), _RIM_COLORS, _RIM_STOPS),
                ),
            )
        ]
        canvas.update()

    canvas.on_resize = redraw
    return canvas


def GlassCard(  # noqa: N802 - kit component names are CamelCase per spec 3
    title: str,
    note: str = "",
    insight: str | None = None,
    quiet: bool = False,
    *,
    body: ft.Control | Sequence[ft.Control] | None = None,
    menu: ft.Control | None = None,
    expand: bool | int = False,
    width: float | None = None,
    height: float | None = None,
    reduce_effects: bool = False,
    key: str | None = None,
) -> ft.Container:
    """Glass panel with h2 title left, note right, optional insight line, then the body (spec 3.1)."""
    # The title keeps its natural width unless it exceeds the whole row, when it is constrained and ellipsized.
    # The note then takes the remaining width, right-aligned, and keeps its full text in a tooltip.
    title_text = txt(title, 15, 600, shadow=True, tracking=0.005, trunc=True, expand=None if note else 1, expand_loose=bool(not note))
    side = theme.CARD_PADDING_QUIET[1] if quiet else theme.CARD_PADDING[1]
    menu_width = float(getattr(menu, "width", 0) or 0) + 8 if menu is not None else 0
    if note and width is not None and text_width(title, 15) > width - 2 * side - 8 - menu_width:
        title_text.width = max(width - 2 * side - 8 - menu_width, 0)
    heading: list[ft.Control] = [title_text]
    note_text = txt(note, 12, 500, theme.INK2, opacity=0.55, text_align=ft.TextAlign.RIGHT, trunc=True)
    if note:
        heading.append(ft.Container(content=note_text, expand=True, alignment=ft.Alignment(1, 0), tooltip=note))
    if menu is not None:
        heading.append(menu)
    rows: list[ft.Control] = []
    if title or note or menu is not None:
        rows.append(
            ft.Container(
                content=ft.Row(
                    heading,
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                height=28 if menu is not None else 20,
            )
        )
    if insight:
        rows.append(
            ft.Container(
                content=txt(
                    insight,
                    12.5,
                    400,
                    theme.INK,
                    opacity=0.60,
                    line_height=16.9,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                margin=pad(top=8),
            )
        )
    filled = bool(expand)
    if body is not None:
        children = [body] if isinstance(body, ft.Control) else list(body)
        rows.append(
            ft.Container(
                margin=pad(top=12 if rows else 0),
                content=ft.Column(children, spacing=12, expand=filled),
                expand=filled,
            )
        )
    top, side, bottom = theme.CARD_PADDING_QUIET if quiet else theme.CARD_PADDING
    radius = theme.CARD_RADIUS
    panel = ft.Container(
        content=ft.Column(rows, spacing=0, expand=filled),
        gradient=None if reduce_effects else diagonal_gradient(theme.GLASS_FILL),
        bgcolor=theme.GLASS_FILL_SOLID if reduce_effects else None,
        blur=None if reduce_effects else theme.GLASS_PANEL_BLUR,
        border=ring(theme.rgba(255, 255, 255, 0.10)),
        border_radius=radius,
        shadow=drops(theme.GLASS_DROP_SHADOWS),
        padding=pad(side, top, side, bottom),
        expand=filled,
    )
    sheen = ft.Container(
        left=0,
        top=0,
        right=0,
        bottom=0,
        border_radius=radius,
        ignore_interactions=True,
        gradient=ft.RadialGradient(
            center=ft.Alignment(-0.6, -1.16),
            radius=0.9,
            colors=[theme.rgba(255, 255, 255, theme.GLASS_SHEEN_ALPHA), theme.rgba(255, 255, 255, 0)],
            stops=[0, 0.55],
        ),
    )
    layers: list[ft.Control] = [panel, sheen]
    if not reduce_effects:
        layers.append(_rim_overlay(radius))
    holder = ft.Container(content=ft.Stack(layers, expand=filled), width=width, height=height, expand=expand)
    tag_semantics(holder, key=key, label=None)
    holder.data = {"kit": "GlassCard", "title": title, "quiet": quiet, "note_control": note_text}
    return holder


def Well(  # noqa: N802
    child: ft.Control | None = None,
    *,
    padding: float | ft.Padding = 0,
    expand: bool | int = False,
    width: float | None = None,
    height: float | None = None,
    alignment: ft.Alignment | None = None,
    key: str | None = None,
) -> ft.Container:
    """Recessed plate that holds every chart, table and the globe (spec 3.2)."""
    well = ft.Container(
        content=child,
        # Flutter has no inset shadow: a darker top edge fading into the fill emulates it.
        gradient=vgradient((theme.rgba(4, 8, 18, 0.88), theme.rgba(8, 15, 30, 0.82), theme.WELL_FILL), (0, 0.10, 1)),
        border=ring(theme.WELL_RING),
        border_radius=theme.RADIUS_WELL,
        padding=padding,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        expand=expand,
        width=width,
        height=height,
        alignment=alignment,
    )
    tag_semantics(well, key=key, label=None)
    well.data = {"kit": "Well"}
    return well


def Note(text: str, *, color: str = theme.INK2, key: str | None = None) -> ft.Text:  # noqa: N802
    """Footnote or safety sentence (spec 3.22)."""
    control = txt(text, 12.5, 400, color, line_height=18.75)
    tag_semantics(control, key=key, label=None)
    return control


def EmptyState(  # noqa: N802
    title: str,
    reason: str,
    action: ft.Control | None = None,
    *,
    expand: bool | int = True,
    height: float | None = None,
    key: str | None = None,
) -> ft.Container:
    """Well with a centred title and reason, used whenever a chart or table has no data (spec 3.23)."""
    column: list[ft.Control] = [
        txt(title, 14, 600, theme.INK2, text_align=ft.TextAlign.CENTER, max_lines=2),
        txt(reason, 12.5, 400, theme.INK3, text_align=ft.TextAlign.CENTER, max_lines=4),
    ]
    if action is not None:
        column.append(ft.Container(content=action, margin=pad(top=8)))
    inner = ft.Column(
        column,
        spacing=4,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
    )
    well = Well(inner, padding=sym(24, 16), expand=expand, height=height, alignment=ft.Alignment(0, 0), key=key)
    well.data = {"kit": "EmptyState", "title": title}
    return well


def FloatingPanel(  # noqa: N802
    heading: str,
    content: ft.Control,
    *,
    width: float | None = None,
    key: str | None = None,
) -> ft.Container:
    """Overlay legend panel: transparent glass mini panel with blur 10 (spec 3.20)."""
    panel = ft.Container(
        content=ft.Column(
            [txt(heading, 11.5, 700, "#d3dcf2", tracking=0.1, upper=True), content],
            spacing=8,
            tight=True,
        ),
        bgcolor=theme.rgba(255, 255, 255, 0.04),
        blur=10,
        border_radius=16,
        border=ring(theme.rgba(255, 255, 255, 0.14)),
        padding=12,
        shadow=drops(((0, 4, 16, 0, theme.rgba(0, 0, 0, 0.4)),)),
        width=width,
    )
    tag_semantics(panel, key=key, label=None)
    panel.data = {"kit": "FloatingPanel", "heading": heading}
    return panel


@dataclass(frozen=True)
class MenuItem:
    """One CardMenu row. ``selected`` marks the active option of a group with a check."""

    label: str
    on_click: Callable[[], object] | None = None
    selected: bool = False
    disabled: bool = False


def CardMenu(  # noqa: N802
    items: Sequence[MenuItem | tuple[str, Callable[[], object] | None]],
    *,
    key: str | None = None,
) -> ft.Control:
    """28x28 round "more" button at the right end of a card's title row that opens a glass menu (spec 3.24)."""
    entries = [item if isinstance(item, MenuItem) else MenuItem(item[0], item[1]) for item in items]

    def build(entry: MenuItem) -> ft.PopupMenuItem:
        def clicked(_event: object) -> None:
            if entry.on_click is not None:
                entry.on_click()

        return ft.PopupMenuItem(
            content=ft.Container(
                content=ft.Row(
                    [
                        txt(entry.label, 13.5, 500, theme.INK3 if entry.disabled else theme.INK, expand=True, trunc=True),
                        txt("✓" if entry.selected else "", 13, 700, theme.ACC),
                    ],
                    spacing=10,
                ),
                height=36,
                alignment=ft.Alignment(-1, 0),
            ),
            on_click=clicked,
            disabled=entry.disabled,
            height=36,
        )

    button = ft.Container(
        content=txt("⋯", 18, 600, theme.INK2),
        width=28,
        height=28,
        border_radius=14,
        alignment=ft.Alignment(0, 0),
    )
    menu = ft.PopupMenuButton(
        content=button,
        items=[build(entry) for entry in entries],
        tooltip="More options",
        menu_padding=6,
        bgcolor=theme.rgba(14, 24, 48, 0.96),
        shape=ft.RoundedRectangleBorder(radius=16),
    )
    tag_semantics(menu, key=key, label=None)
    menu.data = {"kit": "CardMenu", "items": [entry.label for entry in entries]}
    return menu


def SectionHeader(  # noqa: N802
    title: str,
    note: str = "",
    segmented: ft.Control | None = None,
    *,
    key: str | None = None,
) -> ft.Container:
    """Header for content below the first screen: no glass, 28px above and 12px below (spec 3.25)."""
    left: list[ft.Control] = [txt(title, 17, 650, shadow=True, trunc=True)]
    if note:
        # Sits directly on the photo: h2 shadow and full-strength ink keep contrast >= 4.5:1.
        left.append(txt(note, 12.5, 400, theme.INK2, shadow=True, trunc=True))
    row: list[ft.Control] = [ft.Column(left, spacing=4, expand=True)]
    if segmented is not None:
        row.append(segmented)
    header = ft.Container(
        content=ft.Row(row, vertical_alignment=ft.CrossAxisAlignment.END),
        margin=pad(top=28, bottom=12),
    )
    tag_semantics(header, key=key, label=None)
    header.data = {"kit": "SectionHeader", "title": title}
    return header
