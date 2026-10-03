"""Page-local composition helpers over the U0 kit (workspace Universe and Map)."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import kit

UNAVAILABLE = "Unavailable"


def glass(key: str, label: str, content: ft.Control, *, expand: bool | int = False) -> ft.Container:
    """Place a page section on the kit glass surface with a stable key and accessible label."""
    return kit.glass_panel(content, key=key, label=label, expand=expand, padding=18)


def kpi_row(key: str, tiles: list[tuple[str, str | None, str]]) -> ft.Row:
    """Render KPI tiles; a missing value (None) shows Unavailable with its reason, never zero."""
    controls: list[ft.Control] = []
    for index, (label, value, detail) in enumerate(tiles):
        controls.append(
            ft.Container(
                kit.kpi_tile(label, UNAVAILABLE if value is None else value, detail, key=f"{key}.{index}"),
                width=210,
            )
        )
    return ft.Row(controls, spacing=12, run_spacing=12, wrap=True)


def tone_for(status: str) -> str:
    text = status.strip().lower()
    if text in {"available", "healthy", "ok", "pass"}:
        return "g"
    if text in {"failed", "corrupt", "block", "error"}:
        return "b"
    return "w"
