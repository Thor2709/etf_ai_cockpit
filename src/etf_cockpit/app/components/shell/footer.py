"""Footer rail (spec 5.4): lock pill, data quality, as-of, prices, forecast sources, depth, profile, authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit._base import drops, sym, txt, vgradient
from etf_cockpit.app.components.shell._glass import divider, glass
from etf_cockpit.app.components.shell.status import UNAVAILABLE, FooterValues

FOOTER_HEIGHT = 48
COMPACT_BELOW = 1500
LOCK_TOOLTIP = "execution_allowed=false · no order, broker or provider-write authority"
_LOCK_FILL = (theme.rgba(255, 199, 102, 0.6), theme.rgba(214, 140, 30, 0.5))
_FADE_OFF = ("#ffffffff", "#ffffffff", "#ffffffff")
_FADE_ON = ("#ffffffff", "#ffffffff", "#00ffffff")
_DOT_GLOW = {"ok": theme.rgba(111, 207, 166, 0.6), "warn": theme.rgba(230, 194, 122, 0.5), "bad": theme.rgba(232, 137, 124, 0.5)}


@dataclass
class Footer:
    control: ft.Container
    set_compact: Callable[[bool], None]
    set_width: Callable[[float | None], None] = lambda _width: None


def _pair(label: str, value: str, *, key: str, tooltip: str | None = None, unavailable: bool = False,
          on_click: Callable | None = None, chevron: bool = False) -> ft.Container:
    """``label <b>value</b>`` text pair; unavailable values keep their reason as tooltip."""
    parts: list[ft.Control] = []
    if label:
        parts.append(txt(label, 12, 400, theme.INK2, no_wrap=True))
    parts.append(txt(value, 12, 650, theme.AMBER if unavailable else theme.INK, no_wrap=True))
    if chevron:
        parts.append(txt("▸", 12, 400, theme.INK2, no_wrap=True))
    return ft.Container(
        key=key,
        data="unavailable" if unavailable else "available",
        tooltip=tooltip,
        content=ft.Row(parts, spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        on_click=on_click,
        ink=on_click is not None,
        ink_color=theme.HOVER_OVERLAY,
        border_radius=8,
        padding=sym(4, 4),
    )


def build_footer(
    values: FooterValues,
    *,
    depth_label: str | None,
    profile_text: str | None,
    on_data_health: Callable[[], None],
    on_depth: Callable[[], None],
    on_settings: Callable[[], None],
    compact: bool,
    width: float | None = None,
) -> Footer:
    lock = ft.Container(
        key="shell.safety.execution",
        data="available",
        tooltip=LOCK_TOOLTIP,
        content=ft.Row(
            [ft.Icon(ft.Icons.LOCK_OUTLINE, size=14, color="#ffffff"), txt("Execution locked", 12, 700, "#ffffff", no_wrap=True)],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(8, 5, 12, 5),
        border_radius=theme.RADIUS_PILL,
        gradient=vgradient(_LOCK_FILL),
    )
    dot = ft.Container(
        width=9,
        height=9,
        border_radius=5,
        bgcolor=theme.DOT_COLOURS[values.quality_kind],
        shadow=drops(((0, 0, 9, 0, _DOT_GLOW[values.quality_kind]),)),
    )
    quality = ft.Container(
        key="shell.safety.data-quality",
        data="unavailable" if values.quality_reason else "available",
        tooltip=values.quality_reason or "Open Data Health",
        content=ft.Row(
            [dot, txt("Data quality", 12, 400, theme.INK2, no_wrap=True),
             txt(values.quality_text, 12, 700, theme.AMBER if values.quality_reason else theme.INK, no_wrap=True)],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        on_click=lambda _e: on_data_health(),
        ink=True,
        ink_color=theme.HOVER_OVERLAY,
        border_radius=8,
        padding=sym(4, 4),
    )
    depth_value = depth_label or UNAVAILABLE
    depth = _pair(
        "Depth:",
        depth_value,
        key="shell.as-of.analysis-depth",
        tooltip="Open analysis depth and evidence mode"
        if depth_label
        else "No analysis depth has been selected; choose Quick, Medium, High or Full.",
        unavailable=depth_label is None,
        on_click=lambda _e: on_depth(),
        chevron=True,
    )
    profile = _pair(
        "",
        profile_text or UNAVAILABLE,
        key="shell.as-of.profile",
        tooltip="Open Settings (currency, horizon, risk profile)"
        if profile_text
        else "No saved currency, horizon or risk profile is available in Settings.",
        unavailable=profile_text is None,
        on_click=lambda _e: on_settings(),
        chevron=True,
    )
    authority_text = "execution_allowed=false" + (" · sample data" if values.sample_data else "")
    spacer = ft.Container(expand=True, visible=not compact)
    forecast_pair = _pair("Forecast:", values.forecast, key="shell.safety.forecast-source", tooltip=values.forecast_reason,
                          unavailable=values.forecast == UNAVAILABLE)
    as_of_pair = _pair("As of", values.as_of, key="shell.safety.as-of-time", tooltip=values.as_of_reason,
                       unavailable=values.as_of_reason is not None and values.as_of == UNAVAILABLE)
    prices_pair = _pair("Prices:", "adjusted", key="shell.safety.price-basis", tooltip="Adjusted, corporate-action-aware prices")
    authority = _pair("", authority_text, key="shell.safety.execution-authority", tooltip=LOCK_TOOLTIP)
    # (priority, estimated width, controls). Lower priority numbers survive narrow windows; items hide whole.
    groups: list[tuple[int, float, list[ft.Control]]] = [
        (0, 150.0, [lock]),
        (2, 150.0, [quality]),
        (3, 130.0, [divider(), as_of_pair]),
        (7, 130.0, [divider(), prices_pair]),
        (5, 120.0 + 6.8 * len(values.forecast), [divider(), forecast_pair]),
        (4, 110.0 + 6.8 * len(depth_value), [divider(), depth]),
        (6, 40.0 + 6.8 * len(profile_text or UNAVAILABLE), [divider(), profile]),
        (1, 40.0 + 6.8 * len(authority_text), [spacer, authority]),
    ]
    items: list[ft.Control] = [control for _p, _w, controls in groups for control in controls]
    row = ft.Row(items, spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    # Overflow scrolls inside the rail; a right-edge fade shows that more content follows (rulebook V9).
    fade = ft.ShaderMask(
        content=row,
        shader=ft.LinearGradient(colors=list(_FADE_OFF), stops=[0, 0.94, 1], begin=ft.Alignment(-1, 0), end=ft.Alignment(1, 0)),
        blend_mode=ft.BlendMode.DST_IN,
    )
    control = glass(fade, radius=theme.RADIUS_FOOTER, padding=sym(20, 0), height=FOOTER_HEIGHT, key="shell.safety-rail")

    state = {"compact": compact}

    def set_width(window_width: float | None) -> None:
        """Drop the lowest-priority items whole when the rail would not fit (never cut an item mid-word)."""
        if window_width is None:
            for _p, _w, controls in groups:
                for item in controls:
                    item.visible = True
            spacer.visible = not state["compact"]
            return
        available = window_width - 84 - 24 * 3 - 40  # dock, page margins, rail padding
        used = 0.0
        shown: set[int] = set()
        for priority, estimate, _controls in sorted(groups, key=lambda group: group[0]):
            if used + estimate + 16 <= available or priority == 0:
                used += estimate + 16
                shown.add(priority)
        for priority, _w, controls in groups:
            for item in controls:
                item.visible = priority in shown
        spacer.visible = (not state["compact"]) and 1 in shown

    def set_compact(value: bool) -> None:
        state["compact"] = value
        row.scroll = ft.ScrollMode.AUTO if value else None
        spacer.visible = not value
        fade.shader.colors = list(_FADE_ON if value else _FADE_OFF)

    set_compact(compact)
    set_width(width)

    return Footer(control, set_compact, set_width)
