"""Instant shell and skeleton body shown while the snapshot or a page is still loading.

This module deliberately imports only Flet, the theme and the shell kit: no pandas, numpy, snapshot or page
modules. The cold-start path paints :func:`build_loading_view` first and loads data in the background, and the
router uses :func:`skeleton_body` while a heavy page builds, so the window is never blank.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit._base import txt
from etf_cockpit.app.components.shell._glass import glass
from etf_cockpit.app.components.shell.dock import build_dock
from etf_cockpit.core.navigation import ROUTE_TITLES, WORKSPACE_GROUPS, WORKSPACE_ICONS

_ROUTE_TITLES = dict(ROUTE_TITLES)
_BAR_FILL = theme.rgba(255, 255, 255, 0.07)


def _bar(width: float | None, height: float = 14, *, expand: bool = False) -> ft.Container:
    return ft.Container(width=width, height=height, border_radius=7, bgcolor=_BAR_FILL, expand=expand or None)


def skeleton_body(message: str = "Loading…", *, key: str = "shell.skeleton") -> ft.Control:
    """Glass body with a progress ring and placeholder bars (the page body while a page builds)."""

    header = ft.Row(
        [
            ft.ProgressRing(width=18, height=18, stroke_width=2, color=theme.ACC),
            txt(message, 14, 600, theme.INK2),
        ],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    cards = ft.Row(
        [
            ft.Container(expand=True, height=150, border_radius=20, bgcolor=_BAR_FILL),
            ft.Container(expand=True, height=150, border_radius=20, bgcolor=_BAR_FILL),
            ft.Container(expand=True, height=150, border_radius=20, bgcolor=_BAR_FILL),
        ],
        spacing=theme.SPACE_3,
    )
    lines = ft.Column([_bar(None, expand=True), _bar(None, expand=True), _bar(320)], spacing=12)
    return glass(
        ft.Column([header, cards, lines], spacing=theme.SPACE_4),
        radius=24,
        padding=theme.SPACE_5,
        key=key,
        expand=True,
    )


def build_loading_view(
    route: str = "/",
    *,
    message: str = "Loading local data…",
    on_select: Callable[[str], None] | None = None,
    narrow: bool = False,
) -> ft.View:
    """Dock, top bar and skeleton body for ``route``; paints before any data is loaded."""

    route_path = (route or "/").split("?", 1)[0].split("#", 1)[0] or "/"
    title = _ROUTE_TITLES.get("/instrument" if route_path.startswith("/instrument/") else route_path, "ETF AI Evidence Cockpit")
    active = next((workspace for workspace, routes in WORKSPACE_GROUPS if route_path in routes), "Home")
    workspaces = [workspace for workspace, _routes in WORKSPACE_GROUPS]
    dock = build_dock(
        workspaces,
        active=active,
        narrow=narrow,
        icons=WORKSPACE_ICONS,
        tooltips={workspace: workspace for workspace in workspaces},
        badge_count=None,
        on_select=(lambda workspace: on_select(dict(WORKSPACE_GROUPS)[workspace][0])) if on_select else (lambda _workspace: None),
    )
    topbar = glass(
        ft.Column(
            [txt(title, 22, 700, theme.INK, trunc=True), txt(theme.APP_TAGLINE, 12.5, 400, theme.INK3, trunc=True)],
            spacing=2,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        radius=28,
        padding=ft.Padding(28, 0, 28, 0),
        height=80,
        key="shell.topbar",
    )
    footer = glass(
        ft.Row([txt("Loading", 12.5, 500, theme.INK3)], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        radius=24,
        padding=ft.Padding(20, 0, 20, 0),
        height=48,
        key="shell.footer",
    )
    column = ft.Column([topbar, ft.Column([skeleton_body(message)], expand=True), footer], expand=True, spacing=22)
    margin = 16 if narrow else 24
    shell = ft.Container(
        content=ft.Row([dock.control, column], expand=True, spacing=margin, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=margin,
        expand=True,
    )
    background = ft.Image(
        src="background/bg_3200.jpg",
        fit=ft.BoxFit.COVER,
        left=-12,
        top=-12,
        right=-12,
        bottom=-12,
        exclude_from_semantics=True,
    )
    root = ft.Stack(
        [background, ft.Container(content=shell, left=0, top=0, right=0, bottom=0)],
        expand=True,
        key="shell.loading",
    )
    return ft.View(route=route, controls=[root], bgcolor=theme.BG, padding=0)
