"""One floating layer above the page for menus and search results (spec 5.2, 5.3), plus toasts (spec 5.5)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Button
from etf_cockpit.app.components.kit._base import txt
from etf_cockpit.app.components.shell._glass import glass

TOAST_SECONDS = 4


class Overlay:
    """Absolute-positioned layer: ``show`` places a panel at (left, top); a click outside hides it."""

    def __init__(self, update: Callable[[], None]) -> None:
        self._update = update
        self.layer = ft.Stack([], expand=True, visible=False, key="shell.overlay")
        self.on_hide: Callable[[], None] | None = None
        self.kind: str | None = None

    @property
    def is_open(self) -> bool:
        return bool(self.layer.visible)

    def show(self, kind: str, panel: ft.Control, left: float, top: float, *, catch_outside: bool = True,
             on_hide: Callable[[], None] | None = None) -> None:
        panel.left, panel.top = left, top
        children: list[ft.Control] = []
        if catch_outside:
            children.append(ft.Container(left=0, top=0, right=0, bottom=0, bgcolor="transparent",
                                         on_click=lambda _e: self.hide(update=True)))
        children.append(panel)
        self.layer.controls = children
        self.layer.visible = True
        self.kind = kind
        self.on_hide = on_hide
        self._update()

    def hide(self, *, update: bool = False) -> bool:
        if not self.layer.visible:
            return False
        self.layer.visible = False
        self.layer.controls = []
        self.kind = None
        callback, self.on_hide = self.on_hide, None
        if callback is not None:
            callback()
        if update:
            self._update()
        return True


class Toast:
    """Glass pill above the footer; auto-hides after 4 s, errors persist with a Close button."""

    def __init__(self, page: object, update: Callable[[], None]) -> None:
        self._page = page
        self._update = update
        self._serial = 0
        self.holder = ft.Container(visible=False, left=0, right=0, bottom=88, alignment=ft.Alignment(0, 0),
                                   ignore_interactions=False, key="shell.toast")

    def show(self, message: str, *, error: bool = False, update: bool = True) -> None:
        self._serial += 1
        serial = self._serial
        ink = theme.NEG if error else theme.INK
        row: list[ft.Control] = [txt(message, 13.5, 500, ink, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, tooltip=message)]
        if error:
            row.append(Button.secondary("Close", lambda _e: self.hide(), key="shell.toast.close"))
        pill = glass(ft.Row(row, spacing=16, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                     radius=theme.RADIUS_PILL, padding=ft.Padding(24, 8, 24, 8), height=52)
        pill.width = min(640, 80 + 8 * len(message)) + (96 if error else 0)
        self.holder.content = pill
        self.holder.visible = True
        if update:
            self._update()
        if not error:
            runner = getattr(self._page, "run_task", None)
            if callable(runner):
                runner(self._expire, serial)

    async def _expire(self, serial: int) -> None:
        await asyncio.sleep(TOAST_SECONDS)
        if serial == self._serial and self.holder.visible:
            self.hide()

    def hide(self) -> None:
        self.holder.visible = False
        self._update()


