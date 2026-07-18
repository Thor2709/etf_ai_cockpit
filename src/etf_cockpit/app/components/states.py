from __future__ import annotations

from typing import Literal

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel

StateName = Literal["empty", "loading", "success", "warning", "error"]
STATE_NAMES: tuple[StateName, ...] = ("empty", "loading", "success", "warning", "error")


def state_panel(
    state: StateName,
    title: str,
    message: str,
    *,
    details: str = "",
    action: ft.Control | None = None,
) -> ft.Container:
    """Render a readable state that is not communicated by colour alone."""

    state_name = str(state).lower()
    colour = theme.STATE_COLOURS.get(state_name, theme.MUTED)
    controls: list[ft.Control] = [
        ft.Row(
            [
                ft.Container(width=8, height=8, bgcolor=colour, border_radius=4),
                ft.Text(f"State: {state_name}", color=theme.TEXT, size=theme.FONT_SM, weight=ft.FontWeight.BOLD),
            ],
            spacing=theme.SPACE_2,
        ),
        ft.Text(title, color=theme.TEXT, size=theme.FONT_LG, weight=ft.FontWeight.BOLD),
        ft.Text(message, color=theme.MUTED, size=theme.FONT_SM, selectable=True),
    ]
    if details:
        controls.append(ft.Text(details, color=theme.MUTED, size=theme.FONT_XS, selectable=True))
    if action is not None:
        controls.append(action)
    return panel(ft.Column(controls, spacing=theme.SPACE_2), padding=theme.SPACE_4)
