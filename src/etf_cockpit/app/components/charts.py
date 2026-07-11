from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.theme import AMBER, BORDER, CYAN, GREEN, MUTED, RED, SURFACE_2, TEXT


def drift_bar(current: float, target: float, soft_band: float, hard_band: float, width: int = 180) -> ft.Column:
    drift = current - target
    colour = GREEN if abs(drift) <= soft_band else AMBER if abs(drift) <= hard_band else RED
    fill_width = max(4, min(width, int(width * min(abs(drift) / max(hard_band, 0.001), 1.0))))
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(f"{current:.1%}", size=11, color=TEXT),
                    ft.Text(f"target {target:.1%}", size=11, color=MUTED),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Container(
                content=ft.Container(width=fill_width, height=6, bgcolor=colour, border_radius=4),
                width=width,
                height=6,
                bgcolor=SURFACE_2,
                border_radius=4,
                border=border_all(1, BORDER),
            ),
        ],
        spacing=4,
    )


def score_bar(value: float, width: int = 90) -> ft.Container:
    colour = GREEN if value > 0.2 else RED if value < -0.2 else AMBER
    fill_width = max(3, int(width * min(abs(value), 1.0)))
    alignment = ft.Alignment(x=-1, y=0) if value >= 0 else ft.Alignment(x=1, y=0)
    return ft.Container(
        content=ft.Container(width=fill_width, height=7, bgcolor=colour, border_radius=4),
        width=width,
        height=7,
        bgcolor=SURFACE_2,
        border_radius=4,
        alignment=alignment,
    )


def score_meter(value: float, width: int = 132) -> ft.Row:
    colour = GREEN if value > 0.25 else RED if value < -0.25 else AMBER
    label = f"{value:+.2f}"
    return ft.Row(
        [
            ft.Container(
                content=ft.Container(
                    width=max(4, int(width * min(abs(value), 1.0))),
                    height=8,
                    bgcolor=colour,
                    border_radius=4,
                ),
                width=width,
                height=8,
                bgcolor=SURFACE_2,
                border_radius=4,
                alignment=ft.Alignment(x=-1, y=0) if value >= 0 else ft.Alignment(x=1, y=0),
                border=border_all(1, BORDER),
            ),
            ft.Text(label, color=TEXT if abs(value) >= 0.25 else MUTED, size=12, width=44),
        ],
        spacing=7,
        tight=True,
    )


def model_status_dot(available: bool) -> ft.Container:
    return ft.Container(width=8, height=8, bgcolor=CYAN if available else MUTED, border_radius=4)
