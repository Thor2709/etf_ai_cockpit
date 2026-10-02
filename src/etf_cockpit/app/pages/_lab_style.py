"""Lab workspace adapters that map the legacy card helpers onto the U0 kit.

Pages keep calling ``panel``, ``metric_card`` and ``section_header``; these
wrappers render them with kit primitives (glass panel, KPI tile, status tag).
They only change presentation and never compute values.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import kit

_COUNTER = itertools.count(1)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "item"


def _first_text(control: ft.Control | None, depth: int = 0) -> str:
    if control is None or depth > 4:
        return ""
    if isinstance(control, ft.Text):
        return str(control.value or "")
    children = getattr(control, "controls", None)
    if children is None and getattr(control, "content", None) is not None:
        children = [control.content]
    for child in children or []:
        found = _first_text(child, depth + 1)
        if found:
            return found
    return ""


def section_header(title: str, subtitle: str = "") -> ft.Column:
    controls: list[ft.Control] = [
        ft.Text(title, size=17, weight=ft.FontWeight.W_600, color=theme.TEXT)
    ]
    if subtitle:
        controls.append(ft.Text(subtitle, size=12, color=theme.MUTED))
    return ft.Column(controls, spacing=3)


def panel(content: ft.Control, *, expand: bool | int = False, padding: int = 14) -> ft.Container:
    title = _first_text(content) or "Lab panel"
    key = f"lab.panel.{next(_COUNTER)}.{_slug(title)}"
    return kit.glass_panel(content, key=key, label=title[:80], expand=expand, padding=max(padding, 16))


def metric_card(title: str, value: str, subtitle: str = "", status_colour: str = "#64748b") -> ft.Container:
    del status_colour
    tile = kit.kpi_tile(title, value or "Unavailable", subtitle, key=f"lab.metric.{_slug(title)}.{next(_COUNTER)}")
    tile.expand = True
    return tile


def model_status_row(
    model_status: Mapping[str, bool] | None,
    *,
    key_prefix: str,
    reasons: Mapping[str, str] | None = None,
) -> ft.Row:
    """Status tags per optional model; a disabled model reads Unavailable plus reason."""
    reasons = reasons or {}
    status = dict(model_status or {})
    tags: list[ft.Control] = [kit.status_tag("baseline: Available", "g", key=f"{key_prefix}.baseline")]
    for name in sorted(status):
        if status[name]:
            tags.append(kit.status_tag(f"{name}: Available", "g", key=f"{key_prefix}.{name}"))
            continue
        reason = reasons.get(name, "optional package or weights not installed; disabled-safe, baseline used")
        tag = kit.status_tag(f"{name}: Unavailable", "w", key=f"{key_prefix}.{name}")
        tag.tooltip = f"{name} Unavailable: {reason}"
        tags.append(tag)
        tags.append(ft.Text(reason, size=11, color=theme.MUTED))
    return ft.Row(tags, spacing=8, wrap=True, run_spacing=6)
