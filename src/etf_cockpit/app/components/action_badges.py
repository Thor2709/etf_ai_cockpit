from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.flet_compat import padding_symmetric
from etf_cockpit.app.theme import ACTION_COLOURS, AMBER, BG, GREEN, MUTED, RED, TEXT


def action_badge(action: str) -> ft.Container:
    colour = ACTION_COLOURS.get(action, "#737373")
    return ft.Container(
        content=ft.Text(action.replace("_", " ").upper(), size=11, weight=ft.FontWeight.BOLD, color=BG),
        bgcolor=colour,
        border_radius=6,
        padding=padding_symmetric(horizontal=8, vertical=4),
    )


def rating_badge(score: float) -> ft.Container:
    if score >= 0.35:
        label = "STRONG POSITIVE"
        colour = GREEN
        text_colour = BG
    elif score >= 0.15:
        label = "POSITIVE"
        colour = "#1f6f4a"
        text_colour = TEXT
    elif score <= -0.35:
        label = "WEAK"
        colour = RED
        text_colour = BG
    elif score <= -0.15:
        label = "NEGATIVE"
        colour = "#7f3b3b"
        text_colour = TEXT
    else:
        label = "NEUTRAL"
        colour = AMBER
        text_colour = BG
    return ft.Container(
        content=ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=text_colour),
        bgcolor=colour if colour else MUTED,
        border_radius=6,
        padding=padding_symmetric(horizontal=8, vertical=4),
    )
