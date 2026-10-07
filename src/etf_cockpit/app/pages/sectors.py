"""Sectors & Countries placeholder (replaced by the full page in the next wave)."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.kit import EmptyState, GlassCard
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.state import AppState


def sectors_page(page: ft.Page | None, state: AppState) -> PageView:
    card = GlassCard(
        "Sectors & Countries",
        body=EmptyState("Not built yet", "This page is built in the next wave."),
        expand=True,
        key="sectors.placeholder",
    )
    return PageView(
        chrome=PageChrome("Sectors & Countries", "Globe and map of sector and country returns"),
        body=card,
    )
