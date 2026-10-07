from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.kit import GlassCard
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup


def page_view(
    title: str,
    subtitle: str,
    body: ft.Control,
    segments: tuple[SegmentGroup, ...] = (),
) -> PageView:
    """Give a page its shared shell contract and one kit-owned outer surface."""
    return PageView(
        chrome=PageChrome(title=title, subtitle=subtitle, segment_groups=segments),
        body=ft.Column(
            [GlassCard(title=title, note=subtitle, body=body, expand=True)],
            spacing=0,
            expand=True,
        ),
    )
