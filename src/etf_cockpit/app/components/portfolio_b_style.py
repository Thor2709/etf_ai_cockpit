"""Portfolio B page styling on the U0 kit.

Drop-in replacements for ``cards.panel`` and ``cards.metric_card`` that render
through the kit primitives (glass panel, KPI tile, status tag, table plate).
Elements are created with a ``pending.`` key and numbered deterministically by
``restyle`` (page slug plus tree-order index per build); no global counter.
"""

from __future__ import annotations

import re

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import glass_panel, kpi_tile, status_tag, table_style

_PENDING = "pending."
_TONES = {theme.GREEN: "g", theme.AMBER: "w", theme.RED: "b"}


def panel(content: ft.Control, *, expand: bool | int = False, padding: int = 14) -> ft.Container:
    return glass_panel(content, key=_PENDING + "panel", label="Panel", expand=expand, padding=max(padding, 16))


def metric_card(title: str, value: str, subtitle: str = "", status_colour: str = "#64748b") -> ft.Container:
    tone = _TONES.get(status_colour)
    parts: list[ft.Control] = [kpi_tile(title, value, "" if tone and subtitle else subtitle, key=_PENDING + "kpi")]
    if tone and subtitle:
        parts.append(status_tag(subtitle, tone, key=_PENDING + "tag"))
    return ft.Container(content=ft.Column(parts, spacing=6), expand=True)


def _children(control: ft.Control) -> list[ft.Control]:
    found = list(getattr(control, "controls", None) or [])
    content = getattr(control, "content", None)
    if content is not None:
        found.append(content)
    return found


def restyle(root: ft.Control, slug: str) -> ft.Control:
    """Number pending kit elements and put raw tables on the kit table plate."""
    pattern = re.compile(rf"^{re.escape(slug)}\.(?:panel|kpi|tag|table)-(\d+)$")
    counter = 0

    def used(node: ft.Control) -> None:
        nonlocal counter
        match = pattern.match(str(getattr(node, "key", "") or ""))
        if match:
            counter = max(counter, int(match.group(1)))
        for child in _children(node):
            used(child)

    def visit(node: ft.Control) -> None:
        nonlocal counter
        key = str(getattr(node, "key", "") or "")
        if key.startswith(_PENDING):
            counter += 1
            node.key = f"{slug}.{key[len(_PENDING):]}-{counter}"
        controls = getattr(node, "controls", None)
        if controls:
            for index, child in enumerate(list(controls)):
                if isinstance(child, ft.DataTable):
                    counter += 1
                    controls[index] = table_style(child, key=f"{slug}.table-{counter}", label="Data table")
                else:
                    visit(child)
        content = getattr(node, "content", None)
        if content is not None:
            if isinstance(content, ft.DataTable):
                counter += 1
                node.content = table_style(content, key=f"{slug}.table-{counter}", label="Data table")
            else:
                visit(content)

    used(root)
    visit(root)
    return root
