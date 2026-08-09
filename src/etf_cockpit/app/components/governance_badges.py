"""Reusable, semantic authority and lifecycle badges for governance views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header


def status_badge(label: str, state: str, *, colour: str = theme.MUTED) -> ft.Container:
    """Render text and an icon-like marker; colour is supplementary only."""

    return ft.Container(
        key=f"governance-badge.{label.casefold().replace(' ', '-')}",
        tooltip=f"{label}: {state}",
        content=ft.Row(
            [
                ft.Text("●", color=colour, size=11, semantics_label=f"{label} status marker"),
                ft.Text(label, color=theme.MUTED, size=11),
                ft.Text(state, color=theme.TEXT, size=11, weight=ft.FontWeight.BOLD),
            ],
            spacing=6,
            tight=True,
        ),
        bgcolor=theme.SURFACE_2,
        border_radius=6,
        padding=ft.Padding(left=8, right=8, top=6, bottom=6),
    )


def build_gate_summary(
    authority_decision: Any,
    *,
    open_help: Callable[[ft.ControlEvent], None],
) -> ft.Container:
    """Build a keyboard-addressable, text-first gate summary."""

    gates = tuple(getattr(authority_decision, "gates", ()) or ())
    rows: list[ft.Control] = []
    if not gates:
        rows.append(ft.Text("Gate evidence unavailable; manual review required.", color=theme.AMBER))
    for gate in sorted(gates, key=lambda item: (getattr(item, "order", 0), getattr(item, "gate_id", ""))):
        passed = bool(getattr(gate, "passed", False))
        state = "Passed" if passed else "Blocked"
        colour = theme.GREEN if passed else theme.RED
        rows.append(
            ft.Row(
                [
                    ft.Text("✓" if passed else "!", color=colour, width=18, semantics_label=f"Gate {state.lower()}"),
                    ft.Text(str(getattr(gate, "gate_id", "unknown")), color=theme.TEXT, expand=True),
                    ft.Text(str(getattr(gate, "severity", "notice")), color=theme.MUTED),
                    ft.Text(state, color=colour),
                ],
                spacing=8,
            )
        )
    button = ft.TextButton(
        "View all gates",
        key="authority-gates.view-all",
        tooltip="View all gate evidence",
        on_click=open_help,
    )
    return panel(
        ft.Column(
            [section_header("Authority gates", "Ordered evidence is descriptive; no gate grants execution authority."), *rows, button],
            spacing=8,
        )
    )


__all__ = ["build_gate_summary", "status_badge"]
