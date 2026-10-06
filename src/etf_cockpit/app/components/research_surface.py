"""Research A surface helpers composed from the U0 kit (no kit changes).

These keep the legacy ``panel``/``metric_card`` call shapes so the research pages can
adopt the glass design system without changing any view-model or calculation code.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Mapping

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, section_header  # noqa: F401  (re-exported)
from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.components.kit import glass_panel, kpi_tile, status_tag

_PANEL_IDS = itertools.count(1)
_TILE_IDS = itertools.count(1)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "item"


def _first_heading(control: ft.Control) -> str:
    """Best-effort accessible label: the first Text found in the panel content."""
    stack = [control]
    while stack:
        item = stack.pop(0)
        if isinstance(item, ft.Text) and item.value:
            return str(item.value)
        inner = getattr(item, "controls", None)
        if inner:
            stack[0:0] = list(inner)
        elif getattr(item, "content", None) is not None:
            stack.insert(0, item.content)
    return "Research panel"


def panel(content: ft.Control, *, expand: bool | int = False, padding: int = 14) -> ft.Container:
    """Glass surface with the legacy ``panel`` signature."""
    label = _first_heading(content)
    return glass_panel(
        content,
        key=f"research.panel.{next(_PANEL_IDS)}.{_slug(label)[:40]}",
        label=label,
        expand=expand,
        padding=max(padding, 16),
    )


def metric_card(title: str, value: str, subtitle: str = "", status_colour: str = theme.BLUE_GREY) -> ft.Container:
    """Recessed KPI tile; a missing value always reads ``N/A`` (never zero)."""
    shown = "N/A" if value is None or str(value).strip().lower() in {"", "n/a", "none", "nan"} else str(value)
    tile = kpi_tile(title, shown, subtitle, key=f"research.kpi.{next(_TILE_IDS)}.{_slug(title)[:40]}")
    tile.expand = True
    return tile


def decision_tag(text: str, score_10: float | None, *, key: str) -> ft.Container:
    """Status tag whose text always carries the decision; colour is secondary."""
    if score_10 is None:
        tone = "w"
    elif score_10 >= 6.5:
        tone = "g"
    elif score_10 >= 4.0:
        tone = "w"
    else:
        tone = "b"
    return status_tag(text, tone, key=key)


def _titled(title: str, body: ft.Control, note: str, *, key: str) -> ft.Container:
    """Glass card that is safe inside scrolling columns (kit.card expands vertically)."""
    return glass_panel(
        ft.Column([section_header(title, note), body], spacing=8),
        key=key,
        label=title,
    )


def unavailable_card(title: str, reason: str, *, key: str) -> ft.Container:
    """Explicit Unavailable state with a reason (no zero-fill)."""
    body = ft.Column(
        [
            ft.Text("Unavailable", size=15, color=theme.AMBER, weight=ft.FontWeight.W_600),
            ft.Text(reason, size=12, color=theme.MUTED, selectable=True),
        ],
        spacing=4,
    )
    return _titled(title, body, "", key=key)


def _finite(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def distribution_range(distribution: Mapping[str, object], *, key: str) -> ft.Container:
    """Expected-return range (q10 / q50 / q90) at one horizon from an existing view model.

    A full multi-horizon fan needs a per-horizon quantile series that no view model
    supplies; this renders only the single stored horizon and says so. Any missing
    quantile makes the whole view Unavailable with a reason.
    """
    q10 = _finite(distribution.get("q10_expected_return"))
    q50 = _finite(distribution.get("q50_expected_return"))
    q90 = _finite(distribution.get("q90_expected_return"))
    horizon = _finite(distribution.get("expected_return_horizon_days"))
    if q10 is None or q50 is None or q90 is None or not q10 <= q50 <= q90:
        return unavailable_card(
            "Expected-return range",
            "No complete ordered q10/q50/q90 distribution is stored for this instrument; "
            "a fan chart is not drawn and missing quantiles are never filled.",
            key=key,
        )
    horizon_text = f"{int(horizon)}d" if horizon is not None else "N/A"
    span = max(q90 - q10, 1e-9)
    width = 260
    mid = int(width * (q50 - q10) / span)
    band = ft.Container(
        content=ft.Stack(
            [
                ft.Container(
                    left=0,
                    right=0,
                    top=0,
                    bottom=0,
                    gradient=ft.LinearGradient(
                        colors=list(theme.CYLINDER_BAR_COLORS),
                        stops=[0, 0.32, 1],
                        begin=ft.Alignment(-1, 0),
                        end=ft.Alignment(1, 0),
                    ),
                    border_radius=999,
                ),
                ft.Container(left=max(mid - 1, 0), width=3, top=0, bottom=0, bgcolor=theme.TEXT),
            ]
        ),
        width=width,
        height=16,
        border=border_all(1, "rgba(255,255,255,.16)"),
        border_radius=999,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    body = ft.Column(
        [
            ft.Text(f"Expected return, {horizon_text} horizon (single stored horizon, not a time fan)", size=12, color=theme.TEXT),
            band,
            ft.Row(
                [
                    ft.Text(f"q10 {q10:+.1%}", size=11, color=theme.BLUE_GREY),
                    ft.Text(f"q50 {q50:+.1%}", size=11, color=theme.TEXT),
                    ft.Text(f"q90 {q90:+.1%}", size=11, color=theme.BLUE_GREY),
                ],
                width=width,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        ],
        spacing=6,
    )
    return _titled("Expected-return range", body, "from stored forecast distribution", key=key)
