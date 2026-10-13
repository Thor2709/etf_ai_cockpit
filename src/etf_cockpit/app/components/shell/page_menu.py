"""Page menu (spec 5.3): glass dropdown listing the pages of the active workspace with one-line descriptions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit._base import sym, vgradient
from etf_cockpit.app.components.shell._glass import glass, menu_row_text
from etf_cockpit.app.components.shell.page_descriptions import PAGE_DESCRIPTIONS

MENU_WIDTH = 360
ROW_HEIGHT = 56
MAX_HEIGHT = 520
HIDDEN_ALIASES = frozenset({"/etf"})  # same page as /instrument; listed once


@dataclass
class PageMenu:
    panel: ft.Container
    routes: list[str]
    rows: list[ft.Container]
    highlight: Callable[[int], None]
    state: dict


def menu_routes(workspace_routes: Sequence[str]) -> list[str]:
    return [route for route in workspace_routes if route not in HIDDEN_ALIASES]


def build_page_menu(
    routes: Sequence[str],
    current: str,
    pages: Mapping[str, tuple[str, object]],
    *,
    navigate_to: Callable[[str], None],
) -> PageMenu:
    """Rows are ``navigation.<route>`` buttons; ↑/↓ move ``state['index']``, Enter opens that row."""
    ordered = menu_routes(routes)
    rows: list[ft.Container] = []
    state = {"index": ordered.index(current) if current in ordered else 0}

    def style(row: ft.Container, route: str, index: int) -> None:
        selected = route == current
        hot = index == state["index"]
        row.gradient = vgradient(theme.SELECTED_BG) if selected else None
        row.bgcolor = theme.rgba(255, 255, 255, 0.10) if hot and not selected else None
        row.content.content = menu_row_text(pages[route][0], PAGE_DESCRIPTIONS.get(route, ""), selected=selected)

    for index, path in enumerate(ordered):
        button = ft.TextButton(
            content=menu_row_text(pages[path][0], PAGE_DESCRIPTIONS.get(path, ""), selected=path == current),
            key=f"navigation.{path.strip('/').replace('/', '-') or 'home'}",
            tooltip=PAGE_DESCRIPTIONS.get(path) or pages[path][0],
            on_click=lambda _event, p=path: navigate_to(p),
            style=ft.ButtonStyle(padding=sym(16, 0), shape=ft.RoundedRectangleBorder(radius=14), bgcolor="transparent",
                                 overlay_color=theme.HOVER_OVERLAY, alignment=ft.Alignment(-1, 0)),
            height=ROW_HEIGHT,
        )
        row = ft.Container(content=button, height=ROW_HEIGHT, border_radius=14)
        rows.append(row)
        style(row, path, index)

    def highlight(index: int) -> None:
        state["index"] = max(0, min(len(ordered) - 1, index))
        for position, (row, route) in enumerate(zip(rows, ordered, strict=True)):
            selected = route == current
            row.bgcolor = theme.rgba(255, 255, 255, 0.10) if position == state["index"] and not selected else None

    height = min(MAX_HEIGHT, len(ordered) * ROW_HEIGHT + 16)
    panel = glass(
        ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO),
        radius=22,
        padding=8,
        width=MENU_WIDTH,
        height=height,
        key="shell.page-menu",
    )
    return PageMenu(panel, ordered, rows, highlight, state)
