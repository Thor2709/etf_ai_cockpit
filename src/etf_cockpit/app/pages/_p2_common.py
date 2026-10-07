"""Small helpers shared by the Universe and Map pages (wave 2, packet P2).

Only what both pages need: the glass dialog frame (spec 5.5) and the labelled dialog inputs.
"""

from __future__ import annotations

from collections.abc import Sequence

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Field, Toggle
from etf_cockpit.app.components.kit._base import sym, txt
from etf_cockpit.app.components.shell._glass import glass
from etf_cockpit.app.pages import _p4_common as common

DIALOG_WIDTH = 600
_DIALOG_FRAME = {"bgcolor": "transparent", "shadow_color": "transparent", "content_padding": 0}


def input_field(name: str, label: str, value: object = "", *, multiline: bool = False, hint: str = "", prefix: str = "universe.field") -> tuple[ft.Control, ft.TextField]:
    """Kit ``Field`` around a borderless TextField keyed ``<prefix>.<name>``; returns (field, text input)."""
    control = common.text_input(key=f"{prefix}.{name}", value=str(value or ""), hint=hint, multiline=multiline)
    return Field(label, control=control), control


def switch_row(label: str, on: bool, *, key: str) -> tuple[ft.Control, ft.Container]:
    """A kit ``Toggle`` with its label; the toggle's ``data['on']`` holds the current value."""
    toggle = Toggle(on, key=key)
    row = ft.Row([toggle, txt(label, 13.5, 500, theme.INK, trunc=True, expand=True)], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return row, toggle


def toggle_on(toggle: ft.Control) -> bool:
    return bool((getattr(toggle, "data", None) or {}).get("on"))


def glass_dialog(page: object, title: str, body: Sequence[ft.Control], actions: Sequence[ft.Control], *, width: float = DIALOG_WIDTH) -> ft.AlertDialog:
    """Glass dialog (radius 30) with a title, a scrolling body and a right-aligned action row; not yet shown."""
    height = max(360.0, min(760.0, float(getattr(page, "height", 0) or 900) - 96))
    content = ft.Column(
        [
            txt(title, 18, 650, theme.INK, trunc=True),
            ft.Column(list(body), spacing=12, scroll=ft.ScrollMode.AUTO, expand=True),
            ft.Row(list(actions), spacing=12, alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ],
        spacing=16,
        expand=True,
    )
    panel = glass(content, radius=30, padding=sym(24, 24), width=width, height=height)
    return ft.AlertDialog(modal=True, content=panel, inset_padding=ft.Padding(24, 24, 24, 24), **_DIALOG_FRAME)


def show_dialog(page: object, dialog: ft.AlertDialog) -> None:
    page.overlay.append(dialog)
    dialog.open = True
    page.update()


def close_dialog(page: object, dialog: ft.AlertDialog) -> None:
    dialog.open = False
    page.update()
