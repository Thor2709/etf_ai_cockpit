"""Left dock (spec 5.1): nine workspace items, selected pad + label + indicator bar, Changes badge."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Badge
from etf_cockpit.app.components.kit._base import drops, ring, txt, vgradient
from etf_cockpit.app.components.shell._glass import glass

DOCK_WIDTH = 84
DOCK_WIDTH_NARROW = 64
_PAD = 54
_PAD_NARROW = 44
_ICON = 50
_ICON_NARROW = 40
_LABEL_HEIGHT = 17
_HOVER_LIFT = ft.Offset(0, -0.04)
_PAD_SHADOWS = drops(
    (
        (0, 1, 0, 0, theme.rgba(255, 255, 255, 0.18)),
        (0, 0, 0, 1, theme.rgba(255, 255, 255, 0.12)),
        (0, 6, 5, 0, theme.rgba(0, 0, 0, 0.45)),
    )
)


@dataclass
class Dock:
    control: ft.Container
    set_narrow: Callable[[bool], None]


def _safe_update(control: ft.Control) -> None:
    try:
        control.update()
    except Exception:  # not mounted yet (tests, first build)
        pass


def build_dock(
    workspaces: Sequence[str],
    *,
    active: str,
    narrow: bool,
    icons: Mapping[str, str],
    tooltips: Mapping[str, str],
    badge_count: int | None,
    on_select: Callable[[str], None],
) -> Dock:
    """Build the dock. ``set_narrow`` re-sizes it in place on window resize (no page rebuild)."""
    refs: list[tuple] = []

    def item(workspace: str) -> ft.Container:
        selected = workspace == active
        image = ft.Image(
            src=f"icons/{icons[workspace]}.png",
            width=_ICON,
            height=_ICON,
            fit=ft.BoxFit.CONTAIN,
            semantics_label=f"{workspace} workspace icon",
            scale=1.06 if selected else 1.0,
        )
        pad_box = ft.Container(
            content=image,
            width=_PAD,
            height=_PAD,
            alignment=ft.Alignment(0, 0),
            gradient=vgradient(theme.SELECTED_BG) if selected else None,
            shadow=_PAD_SHADOWS if selected else None,
            border_radius=20,
            animate_offset=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        )
        label = txt(workspace, 10.5, 600, theme.INK, text_align=ft.TextAlign.CENTER, no_wrap=True, visible=selected and not narrow,
                    key=f"shell.dock.label.{workspace}")
        column = ft.Column([pad_box, ft.Container(content=label, margin=ft.Margin(0, 4, 0, 0))], spacing=0, tight=True,
                           horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        layers: list[ft.Control] = [ft.Container(content=column, left=0, right=0, top=0)]
        bar = None
        if selected:
            bar = ft.Container(
                width=5,
                height=26,
                left=3,
                top=14,
                border_radius=3,
                bgcolor=theme.ACC,
                shadow=drops(((0, 0, 12, 0, theme.ACC),)),
                visible=not narrow,
            )
            layers.append(bar)
        count = badge_count if workspace == "Changes" else None
        badge = None
        if count:
            badge = Badge(count, key="shell.dock.badge")
            badge.left = (DOCK_WIDTH - _PAD) / 2 + 37
            badge.top = -5
            layers.append(badge)
        stack = ft.Stack(layers, width=DOCK_WIDTH, height=_PAD + (_LABEL_HEIGHT if selected and not narrow else 0),
                         clip_behavior=ft.ClipBehavior.NONE)

        def hover(event: ft.ControlEvent) -> None:
            lifted = str(getattr(event, "data", "")).lower() == "true"
            pad_box.offset = _HOVER_LIFT if lifted else ft.Offset(0, 0)
            _safe_update(pad_box)

        holder = ft.Container(
            key=f"nav.workspace.{workspace}",
            data="active" if selected else "inactive",
            tooltip=tooltips[workspace],
            content=stack,
            width=DOCK_WIDTH,
            on_click=lambda _event, name=workspace: on_select(name),
            on_hover=hover,
        )
        refs.append((holder, pad_box, image, label, bar, stack, badge))
        return holder

    items = [item(name) for name in workspaces]
    help_item = items.pop()
    column = ft.Column(
        [*items, ft.Container(key="shell.dock.help-spacer", expand=True), help_item],
        spacing=16,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        expand=True,
    )
    control = glass(column, radius=theme.RADIUS_DOCK, padding=ft.Padding(0, 18, 0, 18), key="shell.dock",
                    width=DOCK_WIDTH_NARROW if narrow else DOCK_WIDTH)
    state = {"narrow": narrow}

    def set_narrow(value: bool) -> None:
        if state["narrow"] == value:
            return
        state["narrow"] = value
        width = DOCK_WIDTH_NARROW if value else DOCK_WIDTH
        pad_size, icon_size = (_PAD_NARROW, _ICON_NARROW) if value else (_PAD, _ICON)
        control.width = width
        for holder, pad_box, image, label, bar, stack, badge in refs:
            selected = holder.data == "active"
            holder.width = width
            stack.width = width
            pad_box.width = pad_box.height = pad_size
            image.width = image.height = icon_size
            label.visible = selected and not value
            if bar is not None:
                bar.visible = not value
            if badge is not None:
                badge.left = (width - pad_size) / 2 + 37
            stack.height = pad_size + (_LABEL_HEIGHT if selected and not value else 0)

    return Dock(control, set_narrow)
