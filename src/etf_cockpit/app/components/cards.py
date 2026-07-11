from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.theme import BORDER, MUTED, SURFACE, SURFACE_2, TEXT


def panel(content: ft.Control, *, expand: bool | int = False, padding: int = 14) -> ft.Container:
    return ft.Container(
        content=content,
        bgcolor=SURFACE,
        border=border_all(1, BORDER),
        border_radius=8,
        padding=padding,
        expand=expand,
    )


def metric_card(title: str, value: str, subtitle: str = "", status_colour: str = "#64748b") -> ft.Container:
    return panel(
        ft.Column(
            [
                ft.Text(title, size=12, color=MUTED),
                ft.Text(value, size=21, weight=ft.FontWeight.BOLD, color=TEXT, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(subtitle, size=11, color=status_colour, overflow=ft.TextOverflow.ELLIPSIS),
            ],
            spacing=5,
        ),
        expand=True,
    )


def section_header(title: str, subtitle: str = "") -> ft.Column:
    controls: list[ft.Control] = [ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color=TEXT)]
    if subtitle:
        controls.append(ft.Text(subtitle, size=12, color=MUTED))
    return ft.Column(controls, spacing=3)


def evidence_chip(label: str, value: str, colour: str) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(width=7, height=7, bgcolor=colour, border_radius=4),
                ft.Text(label, color=MUTED, size=11),
                ft.Text(value, color=TEXT, size=11, weight=ft.FontWeight.BOLD),
            ],
            spacing=6,
            tight=True,
        ),
        bgcolor=SURFACE_2,
        border_radius=6,
        padding=ft.Padding(left=9, top=6, right=9, bottom=6),
    )
