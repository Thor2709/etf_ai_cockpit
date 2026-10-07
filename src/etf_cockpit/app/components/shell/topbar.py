"""Top bar (spec 5.2): title block with page menu, search, view segments, What changed button."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Badge, Segmented
from etf_cockpit.app.components.kit._base import drops, ring, sym, txt, vgradient
from etf_cockpit.app.components.shell._glass import glass
from etf_cockpit.app.components.shell.overlay import Overlay
from etf_cockpit.app.components.shell.page_view import PageChrome, SegmentGroup
from etf_cockpit.app.components.shell.search import Search

TOPBAR_HEIGHT = 80
MORE = "More ▾"
MAX_SEGMENT_ITEMS = 6
TITLE_WIDTH = 340
TITLE_WIDTH_COMPACT = 260
COMPACT_BELOW = 1500  # search shrinks, title narrows
TIGHT_BELOW = 1100  # narrow layout: title and search shrink so the What changed button stays inside the bar
TITLE_WIDTH_TIGHT = 200
SEARCH_WIDTH_TIGHT = 160
VIEW_MENU_BELOW = 1300  # segment groups collapse into one "View" pill
_WC_SHADOWS = drops(
    (
        (0, 3, 0, 0, theme.rgba(0, 0, 0, 0.30)),
        (0, 8, 14, 0, theme.rgba(0, 0, 0, 0.30)),
    )
)
_WC_PRESSED = drops(((0, 1, 0, 0, theme.rgba(0, 0, 0, 0.30)),))


@dataclass
class TopBar:
    control: ft.Container
    title_left: float  # x of the title block inside the window (for the page-menu anchor)
    set_width: Callable[[float], None]


def _group_control(
    group: SegmentGroup,
    overlay: Overlay,
    host: ft.Row,
    index: int,
    anchor_left: Callable[[], float],
    top: float,
) -> ft.Control:
    """Segmented for one group; > 6 items show the first five plus ``More ▾`` (opens a glass menu)."""
    items = list(group.items)
    current = {"value": group.selected}

    def rebuild() -> None:
        host.controls[index] = _group_control(
            SegmentGroup(group.key, items, current["value"], group.on_change), overlay, host, index, anchor_left, top
        )
        try:
            host.update()
        except Exception:
            pass

    def choose(option: str) -> None:
        overlay.hide()
        current["value"] = option
        rebuild()
        if group.on_change is not None:
            group.on_change(option)

    if len(items) <= MAX_SEGMENT_ITEMS:
        return Segmented(items, group.selected, on_change=group.on_change, key=f"shell.view.{group.key}")

    visible = items[:5]
    if group.selected not in visible:
        visible[4] = group.selected

    def on_change(option: str) -> None:
        if option != MORE:
            current["value"] = option
            if group.on_change is not None:
                group.on_change(option)
            return
        rows = [
            ft.Container(
                content=txt(item, 13.5, 500, theme.SELECTED_INK if item == current["value"] else theme.INK, trunc=True),
                height=40,
                padding=sym(16, 0),
                alignment=ft.Alignment(-1, 0),
                border_radius=12,
                gradient=vgradient(theme.SELECTED_BG) if item == current["value"] else None,
                ink=True,
                ink_color=theme.HOVER_OVERLAY,
                on_click=lambda _e, value=item: choose(value),
            )
            for item in items
        ]
        panel = glass(ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO), radius=22, padding=8, width=240,
                      height=min(420, len(rows) * 40 + 16))
        overlay.show("more", panel, anchor_left() - 120, top, on_hide=rebuild)

    return Segmented([*visible, MORE], group.selected, on_change=on_change, key=f"shell.view.{group.key}")


def build_topbar(
    chrome: PageChrome,
    *,
    has_menu: bool,
    on_open_menu: Callable[[], None],
    search: Search,
    overlay: Overlay,
    badge_count: int | None,
    on_what_changed: Callable | None,
    width: float,
) -> TopBar:
    compact = width < COMPACT_BELOW
    title_width = TITLE_WIDTH_COMPACT if compact else TITLE_WIDTH

    # The text column always fills the title block (expand) so a long subtitle ellipsizes (with tooltip) instead of clipping.
    title_row: list[ft.Control] = [
        ft.Container(
            content=ft.Column(
                [
                    txt(chrome.title, 27, 720, theme.INK, tracking=-0.022, line_height=30, trunc=True),
                    txt(chrome.subtitle, 12.5, 600, theme.INK2, line_height=16, trunc=True),
                ],
                spacing=2,
                tight=True,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            expand=True,
        )
    ]
    if has_menu:
        title_row.append(ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=16, color=theme.INK2))
    title_block = ft.Container(
        content=ft.Row(title_row, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        width=title_width,
        height=64,
        border_radius=14,
        ink=has_menu,
        ink_color=theme.HOVER_OVERLAY,
        on_click=(lambda _e: on_open_menu()) if has_menu else None,
        key="shell.title-block",
        tooltip="Pages in this workspace" if has_menu else None,
    )

    groups = list(chrome.segment_groups)[:3]
    segments = ft.Row([], spacing=10, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    segments_left = lambda: 1200.0  # noqa: E731 - replaced below once the width is known
    for index, group in enumerate(groups):
        segments.controls.append(
            _group_control(group, overlay, segments, index, lambda: segments_left(), TOPBAR_HEIGHT + 32)
        )

    view_pill = ft.Container(
        content=ft.Row([txt("View", 13, 500, theme.INK2), ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=16, color=theme.INK2)],
                       spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=38,
        padding=sym(16, 0),
        border_radius=theme.RADIUS_SEGMENT_GROUP,
        bgcolor=theme.SEGMENT_TRACK_FILL,
        border=ring(theme.rgba(0, 0, 0, 0.20)),
        ink=True,
        ink_color=theme.HOVER_OVERLAY,
        key="shell.view-menu",
        visible=False,
    )

    def open_view_menu(_event: object) -> None:
        sections: list[ft.Control] = []
        for group in groups:
            sections.append(txt(group.key.replace("_", " ").upper(), 11, 600, theme.INK3, tracking=0.08, trunc=True))
            for item in group.items:
                sections.append(
                    ft.Container(
                        content=txt(item, 13.5, 500, theme.SELECTED_INK if item == group.selected else theme.INK, trunc=True),
                        height=40,
                        padding=sym(16, 0),
                        alignment=ft.Alignment(-1, 0),
                        border_radius=12,
                        gradient=vgradient(theme.SELECTED_BG) if item == group.selected else None,
                        ink=True,
                        ink_color=theme.HOVER_OVERLAY,
                        on_click=lambda _e, g=group, value=item: (overlay.hide(), g.on_change and g.on_change(value)),
                    )
                )
        panel = glass(ft.Column(sections, spacing=0, scroll=ft.ScrollMode.AUTO), radius=22, padding=8, width=260,
                      height=min(480, 48 * max(1, len(sections)) + 16))
        overlay.show("view", panel, 24 + 84 + 24 + width - 48 - 320, TOPBAR_HEIGHT + 32)

    view_pill.on_click = open_view_menu

    def _go_to(_event: ft.ControlEvent) -> None:
        if on_what_changed is not None:
            on_what_changed()

    inert = on_what_changed is None
    wc_label: list[ft.Control] = [txt("What changed", 13.5, 650, theme.INK, no_wrap=True)]
    badge = Badge(badge_count or 0, key="shell.what-changed.badge")
    if badge_count:
        wc_label.append(badge)
    wc_visual = ft.Container(
        content=ft.TextButton(
            content=ft.Row(wc_label, spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            key="dashboard.open-what-changed",
            tooltip="You are on What Changed" if inert else "Open What Changed",
            on_click=None if inert else _go_to,
            style=ft.ButtonStyle(padding=sym(16, 0), shape=ft.RoundedRectangleBorder(radius=14), bgcolor="transparent",
                                 overlay_color=theme.HOVER_OVERLAY),
            height=44,
        ),
        height=44,
        border_radius=14,
        gradient=vgradient(theme.RAISED_FILL),
        border=ring(theme.rgba(255, 255, 255, 0.22)),
        shadow=_WC_PRESSED if inert else _WC_SHADOWS,
        offset=ft.Offset(0, 0.04) if inert else ft.Offset(0, 0),
    )

    spacer = ft.Container(expand=True)
    row = ft.Row(
        [title_block, search.box, spacer, segments, view_pill, wc_visual],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    control = glass(row, radius=theme.RADIUS_TOPBAR, padding=ft.Padding(28, 0, 20, 0), height=TOPBAR_HEIGHT, key="shell.topbar")

    def set_width(value: float) -> None:
        small = value < COMPACT_BELOW
        tight = value < TIGHT_BELOW
        title_block.width = TITLE_WIDTH_TIGHT if tight else TITLE_WIDTH_COMPACT if small else TITLE_WIDTH
        search.set_compact(small)
        if tight:
            search.box.width = SEARCH_WIDTH_TIGHT
        use_view = value < VIEW_MENU_BELOW and bool(groups)
        segments.visible = not use_view
        view_pill.visible = use_view

    set_width(width)
    segments_left = lambda: width - 20 - 150 - 24 - 40  # noqa: E731
    return TopBar(control, 24 + 84 + 24 + 28, set_width)

