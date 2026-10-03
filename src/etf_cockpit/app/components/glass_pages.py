from __future__ import annotations

import re

import flet as ft

from etf_cockpit.app.components.kit import glass_panel


def _first_text(control: object) -> str:
    if isinstance(control, ft.Text):
        return str(control.value or "")
    for child in (getattr(control, "controls", None) or ()):
        found = _first_text(child)
        if found:
            return found
    inner = getattr(control, "content", None)
    return _first_text(inner) if inner is not None else ""


def page_panel(prefix: str):
    """Return a ``panel``-compatible factory that renders on the U0 glass surface."""
    counter = {"n": 0}

    def panel(content: ft.Control, *, expand: bool | int = False, padding: int = 14) -> ft.Container:
        counter["n"] += 1
        title = _first_text(content).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "section"
        return glass_panel(
            content,
            key=f"{prefix}.panel.{slug}-{counter['n']}",
            label=title or f"{prefix} section",
            expand=expand,
            padding=max(padding, 14),
        )

    return panel
