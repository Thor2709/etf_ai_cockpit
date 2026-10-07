"""Interactive controls: Segmented, Toggle, Button, Field, Disclosure (spec 3.8-3.12, 3.26)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit._base import (
    drops,
    pad,
    ring,
    sym,
    tag_semantics,
    txt,
    vgradient,
)

_RAISED_SHADOWS = (
    (0, 3, 0, 0, theme.RAISED_UNDER),
    (0, 8, 14, 0, theme.RAISED_DROP),
)
_PRIMARY_SHADOWS = (
    (0, 3, 0, 0, theme.SELECTED_UNDER),
    (0, 8, 14, 0, theme.rgba(0, 0, 0, 0.30)),
)
_PRESS_OFFSET = ft.Offset(0, 2 / 36)
_ANIMATION = ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT)


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------


def _button(
    text: str,
    kind: str,
    on_click: Callable[[object], object] | None,
    disabled: bool,
    disabled_reason: str | None,
    key: str | None,
    expand: bool | int,
) -> ft.Container:
    primary = kind == "primary"
    ink = theme.SELECTED_INK if primary else theme.INK
    shadows = _PRIMARY_SHADOWS if primary else _RAISED_SHADOWS
    pressed_shadows = (
        (0, 1, 0, 0, theme.SELECTED_UNDER if primary else theme.RAISED_UNDER),
        (0, 4, 8, 0, theme.rgba(0, 0, 0, 0.30)),
    )

    def press(_event: object) -> None:
        button.offset = _PRESS_OFFSET
        button.shadow = drops(pressed_shadows)
        _safe_update(button)

    def release() -> None:
        button.offset = ft.Offset(0, 0)
        button.shadow = drops(shadows)
        _safe_update(button)

    def click(event: object) -> None:
        release()
        if on_click is not None:
            on_click(event)

    button = ft.Container(
        content=txt(text, 13.5, 700, ink, text_align=ft.TextAlign.CENTER, trunc=True),
        height=36,
        padding=sym(20, 0),
        alignment=ft.Alignment(0, 0),
        border_radius=theme.RADIUS_CTA,
        gradient=vgradient(theme.PRIMARY_FILL) if primary else vgradient(theme.RAISED_FILL),
        # Uniform 1px rim in the highlight colour replaces the CSS inset top highlight.
        border=ring(theme.PRIMARY_RIM if primary else theme.rgba(255, 255, 255, 0.22)),
        shadow=None if disabled else drops(shadows),
        opacity=0.45 if disabled else 1.0,
        tooltip=disabled_reason if disabled else None,
        on_click=None if disabled else click,
        on_tap_down=None if disabled else press,
        ink=not disabled,
        ink_color=theme.HOVER_OVERLAY,
        animate_offset=ft.Animation(90, ft.AnimationCurve.EASE_OUT),
        expand=expand,
    )
    tag_semantics(button, key=key, label=None)
    button.data = {"kit": "Button", "kind": kind, "text": text, "disabled": disabled}
    return button


class Button:
    """``Button.primary(text)`` and ``Button.secondary(text)``: 36px raised CTA buttons (spec 3.11, 3.12)."""

    @staticmethod
    def primary(
        text: str,
        on_click: Callable[[object], object] | None = None,
        *,
        disabled: bool = False,
        disabled_reason: str | None = None,
        key: str | None = None,
        expand: bool | int = False,
    ) -> ft.Container:
        return _button(text, "primary", on_click, disabled, disabled_reason, key, expand)

    @staticmethod
    def secondary(
        text: str,
        on_click: Callable[[object], object] | None = None,
        *,
        disabled: bool = False,
        disabled_reason: str | None = None,
        key: str | None = None,
        expand: bool | int = False,
    ) -> ft.Container:
        return _button(text, "secondary", on_click, disabled, disabled_reason, key, expand)


def _safe_update(control: ft.Control) -> None:
    try:
        control.update()
    except RuntimeError:
        # Not attached to a page yet (unit tests, first build): the new state is applied on first render.
        pass


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------


def Toggle(  # noqa: N802
    on: bool = False,
    *,
    on_change: Callable[[bool], object] | None = None,
    disabled: bool = False,
    disabled_reason: str | None = None,
    key: str | None = None,
) -> ft.Container:
    """40x22 switch with a 200 ms knob slide (spec 3.9). The control keeps its own state."""
    state = {"on": bool(on)}
    knob = ft.Container(
        width=18,
        height=18,
        border_radius=9,
        gradient=vgradient(("#ffffff", "#c9d2e0")),
        shadow=drops(((0, 2, 4, 0, theme.rgba(0, 0, 0, 0.5)),)),
    )

    def paint() -> None:
        on_now = state["on"]
        track.alignment = ft.Alignment(1, 0) if on_now else ft.Alignment(-1, 0)
        track.gradient = vgradient(("#2a5645", "#47806b")) if on_now else None
        track.bgcolor = None if on_now else theme.rgba(0, 0, 0, 0.35)
        track.data = {"kit": "Toggle", "on": on_now}

    def click(_event: object) -> None:
        state["on"] = not state["on"]
        paint()
        _safe_update(track)
        if on_change is not None:
            on_change(state["on"])

    track = ft.Container(
        content=knob,
        width=40,
        height=22,
        padding=sym(2, 0),
        border_radius=11,  # nested: knob radius 9 = track 11 - padding 2
        border=ring(theme.rgba(0, 0, 0, 0.25)),
        animate=_ANIMATION,
        on_click=None if disabled else click,
        ink=not disabled,
        opacity=0.45 if disabled else 1.0,
        tooltip=disabled_reason if disabled else None,
    )
    paint()
    tag_semantics(track, key=key, label=None)
    return track


# ---------------------------------------------------------------------------
# Segmented
# ---------------------------------------------------------------------------


def Segmented(  # noqa: N802
    items: Sequence[str],
    selected: str,
    *,
    on_change: Callable[[str], object] | None = None,
    key: str | None = None,
) -> ft.Control:
    """Segmented control: 38px track, 30px segments, quail-green selection; left/right arrows move (spec 3.10)."""
    options = list(items)
    if not options or sum(option == selected for option in options) != 1:
        raise ValueError("selected must match exactly one item")
    state = {"selected": selected}
    segments: list[ft.Container] = []

    def style(segment: ft.Container, option: str) -> None:
        active = option == state["selected"]
        label = segment.content
        if isinstance(label, ft.Text):
            label.style = ft.TextStyle(
                size=13,
                weight=ft.FontWeight.W_500,
                color=theme.SELECTED_INK if active else theme.INK2,
                shadow=ft.BoxShadow(blur_radius=0, color=theme.rgba(0, 0, 0, 0.4), offset=ft.Offset(0, 1))
                if active
                else None,
                font_family=theme.FONT_FAMILY,
            )
        segment.gradient = vgradient(theme.SELECTED_BG, (0, 0.55, 1)) if active else None
        segment.shadow = drops(((0, 3, 6, 0, theme.rgba(0, 0, 0, 0.45)),)) if active else None
        segment.border = ring(theme.SELECTED_RIM) if active else None
        segment.data = {"kit": "Segment", "value": option, "selected": active}

    def select(option: str) -> None:
        if option == state["selected"]:
            return
        state["selected"] = option
        for segment, name in zip(segments, options, strict=True):
            style(segment, name)
        _safe_update(row)
        if on_change is not None:
            on_change(option)

    def key_down(event: ft.KeyDownEvent) -> None:
        pressed = str(event.key).replace(" ", "").lower()
        index = options.index(state["selected"])
        if pressed == "arrowright" and index < len(options) - 1:
            select(options[index + 1])
        elif pressed == "arrowleft" and index > 0:
            select(options[index - 1])

    for option in options:
        segment = ft.Container(
            content=txt(option, 13, 500, theme.INK2, trunc=True),
            height=30,
            padding=sym(16, 0),
            alignment=ft.Alignment(0, 0),
            border_radius=theme.RADIUS_SEGMENT,
            ink=True,
            ink_color=theme.HOVER_OVERLAY,
            on_click=lambda _event, value=option: select(value),
        )
        style(segment, option)
        segments.append(segment)
    row = ft.Row(segments, spacing=2, tight=True)
    track = ft.Container(
        content=ft.KeyboardListener(content=row, on_key_down=key_down),
        height=38,
        padding=4,
        border_radius=theme.RADIUS_SEGMENT_GROUP,
        bgcolor=theme.SEGMENT_TRACK_FILL,
        border=ring(theme.rgba(0, 0, 0, 0.20)),
    )
    tag_semantics(track, key=key, label=None)
    track.data = {"kit": "Segmented", "items": options, "state": state}
    return track


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------


def _field_surface(content: ft.Control, *, height: float, expand: bool | int, width: float | None) -> ft.Container:
    return ft.Container(
        content=content,
        height=height,
        width=width,
        expand=expand,
        padding=sym(16, 0),
        alignment=ft.Alignment(-1, 0) if height == 40 else ft.Alignment(-1, -1),
        bgcolor=theme.FIELD_FILL,
        border=ring(theme.rgba(0, 0, 0, 0.30)),
        border_radius=theme.RADIUS_FIELD,
    )


def field_input_style(*, multiline: bool = False, placeholder: str = "") -> dict[str, object]:
    """Borderless TextField kwargs for a ``Field`` input. Pages create (and register) the TextField themselves."""
    return {
        "hint_text": placeholder,
        "text_size": 14,
        "color": theme.INK,
        "hint_style": ft.TextStyle(size=14, color=theme.INK3, font_family=theme.FONT_FAMILY),
        "border": ft.InputBorder.NONE,
        "content_padding": pad(0, 12 if multiline else 0, 0, 0),
        "multiline": multiline,
        "min_lines": 4 if multiline else None,
        "dense": True,
        "text_vertical_align": ft.VerticalAlignment.START if multiline else ft.VerticalAlignment.CENTER,
        "cursor_color": theme.ACC,
        "text_style": ft.TextStyle(size=14, color=theme.INK, font_family=theme.FONT_FAMILY),
    }


def Field(  # noqa: N802
    label: str,
    control: ft.Control | None = None,
    *,
    value: str = "",
    placeholder: str = "",
    options: Sequence[str] | None = None,
    multiline: bool = False,
    on_change: Callable[[str], object] | None = None,
    width: float | None = None,
    expand: bool | int = False,
    key: str | None = None,
) -> ft.Column:
    """Uppercase label, 5px gap, 40px inset input (96px text area). Pass ``control`` or ``options``/``value`` (spec 3.8)."""
    height = 96.0 if multiline else 40.0
    if control is not None:
        surface = _field_surface(control, height=height, expand=expand, width=width)
    elif options is not None:
        surface = _dropdown(options, value, placeholder, on_change, width, expand)
    else:
        raise ValueError("Field needs a control (use field_input_style() for a TextField) or options")
    column = ft.Column(
        [txt(label, 11, 600, theme.INK3, tracking=0.08, upper=True, trunc=True), surface],
        spacing=4,
        tight=True,
        expand=expand,
        width=width,
    )
    tag_semantics(column, key=key, label=None)
    column.data = {"kit": "Field", "label": label}
    return column


def _dropdown(
    options: Sequence[str],
    value: str,
    placeholder: str,
    on_change: Callable[[str], object] | None,
    width: float | None,
    expand: bool | int,
) -> ft.Container:
    text = txt(value or placeholder, 14, 400, theme.INK if value else theme.INK3, trunc=True, expand=True)

    def choose(option: str) -> None:
        text.value = option
        text.style = ft.TextStyle(size=14, color=theme.INK, font_family=theme.FONT_FAMILY)
        _safe_update(text)
        if on_change is not None:
            on_change(option)

    row = ft.Row([text, ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=theme.INK3)], spacing=8)
    menu = ft.PopupMenuButton(
        content=ft.Container(content=row, height=40, alignment=ft.Alignment(-1, 0)),
        items=[
            ft.PopupMenuItem(content=txt(option, 13.5, 500), on_click=lambda _event, name=option: choose(name))
            for option in options
        ],
        bgcolor=theme.rgba(14, 24, 48, 0.96),
        shape=ft.RoundedRectangleBorder(radius=16),
        menu_padding=6,
    )
    return _field_surface(menu, height=40, expand=expand, width=width)


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------


def Disclosure(  # noqa: N802
    label: str,
    content: str | ft.Control | None = None,
    *,
    expanded: bool = False,
    key: str | None = None,
) -> ft.Column:
    """``Show <label> v`` / ``Hide <label> ^`` text button revealing technical lines in a mono well (spec 3.26)."""
    from etf_cockpit.app.components.kit.surfaces import Well

    body: ft.Control = (
        txt(content, 12, 400, theme.INK2, mono=True, selectable=True)
        if isinstance(content, str)
        else (content if content is not None else txt("", 12))
    )
    well = Well(body, padding=12)
    well.visible = expanded
    caption = txt("", 12.5, 600, theme.ACC)

    def refresh() -> None:
        caption.value = f"Hide {label} ▴" if well.visible else f"Show {label} ▾"

    def toggle(_event: object) -> None:
        well.visible = not well.visible
        refresh()
        _safe_update(column)

    refresh()
    header = ft.Container(content=caption, on_click=toggle, ink=True, ink_color=theme.HOVER_OVERLAY,
                          border_radius=8, padding=sym(4, 4), tooltip=None)
    column = ft.Column([header, well], spacing=8, tight=True)
    tag_semantics(column, key=key, label=None)
    column.data = {"kit": "Disclosure", "label": label}
    return column
