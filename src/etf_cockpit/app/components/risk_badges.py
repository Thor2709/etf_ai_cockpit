from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.flet_compat import padding_symmetric
from etf_cockpit.app.theme import SEVERITY_COLOURS, TEXT


def risk_badge(text: str, severity: str = "warning") -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, color=TEXT),
        bgcolor=SEVERITY_COLOURS.get(severity, "#64748b"),
        border_radius=6,
        padding=padding_symmetric(horizontal=8, vertical=4),
    )
