"""Shared primitives for the kit: text, gradients, shadows, uniform borders (spec 2.2, 2.3, 9.3)."""

from __future__ import annotations

from collections.abc import Sequence

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.flet_compat import border_all

_WEIGHTS = {
    100: ft.FontWeight.W_100,
    200: ft.FontWeight.W_200,
    300: ft.FontWeight.W_300,
    400: ft.FontWeight.W_400,
    500: ft.FontWeight.W_500,
    600: ft.FontWeight.W_600,
    700: ft.FontWeight.W_700,
    800: ft.FontWeight.W_800,
    900: ft.FontWeight.W_900,
}

TEXT_SHADOW = ft.BoxShadow(blur_radius=8, color=theme.rgba(0, 0, 0, 0.55), offset=ft.Offset(0, 1))


def weight(value: int) -> ft.FontWeight:
    """Map a CSS weight (for example 650 or 720) to the nearest Flet weight, halves rounding up."""
    return _WEIGHTS[min(900, max(100, int((value + 50) // 100) * 100))]


def txt(
    value: str,
    size: float = 13.5,
    wt: int = 400,
    color: str = theme.INK,
    *,
    tracking: float | None = None,
    shadow: bool = False,
    mono: bool = False,
    line_height: float | None = None,
    opacity: float | None = None,
    upper: bool = False,
    trunc: bool = False,
    **kwargs: object,
) -> ft.Text:
    """Build a Text with the spec typography (Inter, tracking in em, optional h2 shadow)."""
    style = ft.TextStyle(
        size=size,
        weight=weight(wt),
        color=color,
        letter_spacing=None if tracking is None else round(tracking * size, 3),
        shadow=TEXT_SHADOW if shadow else None,
        height=None if line_height is None else line_height / size,
        font_family=theme.FONT_MONO if mono else theme.FONT_FAMILY,
        font_family_fallback=list(theme.FONT_MONO_FALLBACK if mono else theme.FONT_FAMILY_FALLBACK),
    )
    if opacity is not None:
        kwargs["opacity"] = opacity
    if trunc:
        # Text protection rule: truncate with an ellipsis and keep the full text in a tooltip.
        kwargs.setdefault("max_lines", 1)
        kwargs.setdefault("overflow", ft.TextOverflow.ELLIPSIS)
    if kwargs.get("overflow") == ft.TextOverflow.ELLIPSIS:
        kwargs.setdefault("tooltip", value)
    return ft.Text(value.upper() if upper else value, style=style, **kwargs)  # type: ignore[arg-type]


def drop(dx: float, dy: float, blur: float, color: str, spread: float = 0) -> ft.BoxShadow:
    return ft.BoxShadow(spread_radius=spread, blur_radius=blur, color=color, offset=ft.Offset(dx, dy))


def drops(shadows: Sequence[tuple[float, float, float, float, str]]) -> list[ft.BoxShadow]:
    return [drop(dx, dy, blur, colour, spread) for dx, dy, blur, spread, colour in shadows]


def vgradient(colors: Sequence[str], stops: Sequence[float] | None = None) -> ft.LinearGradient:
    return ft.LinearGradient(
        colors=list(colors),
        stops=None if stops is None else list(stops),
        begin=ft.Alignment(0, -1),
        end=ft.Alignment(0, 1),
    )


def hgradient(colors: Sequence[str], stops: Sequence[float] | None = None) -> ft.LinearGradient:
    return ft.LinearGradient(
        colors=list(colors),
        stops=None if stops is None else list(stops),
        begin=ft.Alignment(-1, 0),
        end=ft.Alignment(1, 0),
    )


def diagonal_gradient(colors: Sequence[str]) -> ft.LinearGradient:
    """CSS 165deg: top-left to bottom-right, steep."""
    return ft.LinearGradient(colors=list(colors), begin=ft.Alignment(-0.27, -1), end=ft.Alignment(0.27, 1))


def ring(color: str = theme.WELL_RING) -> ft.Border:
    """Uniform 1px border: the only border form allowed (spec 9.3)."""
    return border_all(1, color)


def hairline(color: str = theme.HAIRLINE, *, height: int = 1) -> ft.Container:
    """Separators are 1px Containers, never one-sided borders (spec 9.3)."""
    return ft.Container(height=height, bgcolor=color)


def pad(left: float = 0, top: float = 0, right: float = 0, bottom: float = 0) -> ft.Padding:
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


def sym(horizontal: float = 0, vertical: float = 0) -> ft.Padding:
    return ft.Padding(left=horizontal, top=vertical, right=horizontal, bottom=vertical)


def tag_semantics(control: ft.Control, *, key: str | None, label: str | None) -> ft.Control:
    """Attach the optional test key; the accessible label is the control tooltip only where it is a leaf."""
    if key is not None:
        control.key = key
    if label is not None and getattr(control, "tooltip", None) is None:
        control.tooltip = label
    return control


def dot_colour(kind: str) -> str:
    return theme.DOT_COLOURS.get(kind, kind)
