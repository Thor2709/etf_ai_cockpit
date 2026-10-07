"""Shell-only glass surface: the GlassCard material without a title row (spec 2.3, 5.1-5.5)."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit._base import diagonal_gradient, drops, ring, tag_semantics, txt
from etf_cockpit.app.components.kit.surfaces import _rim_overlay


def glass(
    content: ft.Control,
    *,
    radius: float,
    padding: ft.Padding | float = 0,
    key: str | None = None,
    width: float | None = None,
    height: float | None = None,
    expand: bool | int = False,
) -> ft.Container:
    """Glass panel with blur, rim and sheen. The holder must have a bounded size (fixed or expanded)."""
    panel = ft.Container(
        content=content,
        gradient=diagonal_gradient(theme.GLASS_FILL),
        blur=theme.GLASS_PANEL_BLUR,
        border=ring(theme.rgba(255, 255, 255, 0.10)),
        border_radius=radius,
        shadow=drops(theme.GLASS_DROP_SHADOWS),
        padding=padding,
    )
    sheen = ft.Container(
        left=0,
        top=0,
        right=0,
        bottom=0,
        border_radius=radius,
        ignore_interactions=True,
        gradient=ft.RadialGradient(
            center=ft.Alignment(-0.6, -1.16),
            radius=0.9,
            colors=[theme.rgba(255, 255, 255, theme.GLASS_SHEEN_ALPHA), theme.rgba(255, 255, 255, 0)],
            stops=[0, 0.55],
        ),
    )
    rim = _rim_overlay(radius)
    rim.ignore_interactions = True
    holder = ft.Container(
        content=ft.Stack([panel, sheen, rim], fit=ft.StackFit.EXPAND, clip_behavior=ft.ClipBehavior.NONE),
        width=width,
        height=height,
        expand=expand,
    )
    tag_semantics(holder, key=key, label=None)
    holder.data = {"kit": "ShellGlass"}
    return holder


def divider(height: int = 22) -> ft.Container:
    """1 x 22 vertical separator (ink2 at 25%) used in the footer rail."""
    return ft.Container(width=1, height=height, bgcolor=theme.rgba(195, 205, 226, 0.25))


def menu_row_text(title: str, sub: str, *, selected: bool) -> ft.Column:
    """Two-line menu row text (14.5/650 title, 12.5 ink2 description), truncated with a tooltip."""
    ink = theme.SELECTED_INK if selected else theme.INK
    return ft.Column(
        [
            txt(title, 14.5, 650, ink, trunc=True),
            txt(sub, 12.5, 400, theme.SELECTED_INK if selected else theme.INK2, trunc=True),
        ],
        spacing=2,
        tight=True,
    )


