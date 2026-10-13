from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Field, field_input_style


def text_field(label: str, key: str, *, multiline: bool = False, value: str = "") -> Field:
    style = field_input_style(multiline=multiline)
    style.pop("multiline", None)
    control = ft.TextField(
        key=key,
        value=value,
        multiline=multiline,
        **style,
    )
    field = Field(label, control=control)
    field.data = {"kit": "Field", "input": control}
    return field


def input_of(field: ft.Control) -> ft.TextField:
    return field.data["input"]


def page_body(controls: list[ft.Control]) -> ft.Column:
    return ft.Column(controls, expand=True, scroll=ft.ScrollMode.AUTO, spacing=theme.SPACE_3)
