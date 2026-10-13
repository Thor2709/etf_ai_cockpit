"""Workflow components: GateCheck, Pipeline, Stepper (spec 3.17, 3.18, 3.28)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.components.kit._base import (
    drops,
    hairline,
    pad,
    ring,
    sym,
    tag_semantics,
    txt,
    vgradient,
)

_RAISED_DISC_SHADOWS = ((0, 2, 0, 0, theme.rgba(0, 0, 0, 0.35)), (0, 4, 8, 0, theme.rgba(0, 0, 0, 0.25)))


def GateCheck(  # noqa: N802
    passed: bool | None,
    title: str,
    reason: str = "",
    *,
    last: bool = False,
    key: str | None = None,
) -> ft.Column:
    """Gate row: 3D check (pass), cross (fail) or grey ring (not evaluated) with title and reason (spec 3.17)."""
    if passed is True:
        icon = ft.Container(
            content=ft.Icon(ft.Icons.CHECK, size=16, color="#ffffff"),
            gradient=vgradient(("#8bf45a", "#2f9e2f")),
            shadow=drops(((0, 2, 4, 0, theme.rgba(0, 0, 0, 0.40)),)),
        )
    elif passed is False:
        icon = ft.Container(
            content=ft.Icon(ft.Icons.CLOSE, size=16, color="#ffffff"),
            gradient=vgradient(("#ff8a7a", "#c0392b")),
            shadow=drops(((0, 2, 4, 0, theme.rgba(0, 0, 0, 0.40)),)),
        )
    else:
        icon = ft.Container(border=border_all(2, theme.rgba(255, 255, 255, 0.35)))
    icon.width = 26
    icon.height = 26
    icon.border_radius = 13
    icon.alignment = ft.Alignment(0, 0)
    text: list[ft.Control] = [txt(title, 13.5, 600)]
    if reason:
        text.append(txt(reason, 12.5, 400, theme.INK2, line_height=16.25))
    row = ft.Container(
        content=ft.Row(
            [icon, ft.Column(text, spacing=4, expand=True, tight=True)],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        padding=sym(4, 8),
    )
    parts: list[ft.Control] = [row]
    if not last:
        # Engraved separator: dark line with a light line directly below.
        parts += [hairline(theme.rgba(0, 0, 0, 0.28)), hairline(theme.rgba(255, 255, 255, 0.08))]
    column = ft.Column(parts, spacing=0)
    tag_semantics(column, key=key, label=None)
    column.data = {"kit": "GateCheck", "passed": passed, "title": title}
    return column


def Pipeline(  # noqa: N802
    steps: Sequence[str | tuple[str, str]],
    *,
    key: str | None = None,
) -> ft.Row:
    """Horizontal 93x51 steps separated by a chevron; the last step is quail green (spec 3.18).

    A step is a label (auto-numbered from 1) or a ``(number_text, label)`` tuple.
    """
    controls: list[ft.Control] = []
    last = len(steps) - 1
    for index, step in enumerate(steps):
        number, label = (str(index + 1), step) if isinstance(step, str) else step
        is_last = index == last
        controls.append(
            ft.Container(
                content=ft.Column(
                    [
                        txt(number, 15, 700, theme.SELECTED_INK if is_last else theme.INK),
                        txt(label, 10.5, 400, theme.SELECTED_INK if is_last else theme.INK2, trunc=True),
                    ],
                    spacing=4,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                width=93,
                height=51,
                border_radius=12,
                alignment=ft.Alignment(0, 0),
                gradient=vgradient(theme.PRIMARY_FILL if is_last else
                                   (theme.rgba(255, 255, 255, 0.17), theme.rgba(255, 255, 255, 0.05))),
                border=ring(theme.PRIMARY_RIM if is_last else theme.rgba(255, 255, 255, 0.20)),
                shadow=drops(
                    ((0, 3, 0, 0, theme.SELECTED_UNDER if is_last else theme.rgba(0, 0, 0, 0.35)),
                     (0, 7, 12, 0, theme.rgba(0, 0, 0, 0.30)))
                ),
            )
        )
        if not is_last:
            controls.append(txt("›", 12, 400, theme.INK3))
    row = ft.Row(controls, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=False)
    tag_semantics(row, key=key, label=None)
    row.data = {"kit": "Pipeline", "steps": len(steps)}
    return row


STEP_STATES = ("pending", "running", "done", "failed")


@dataclass(frozen=True)
class StepSpec:
    """One Stepper step. ``action`` is usually a Button.secondary placed at the right."""

    title: str
    status: str = ""
    state: str = "pending"
    action: ft.Control | None = None


def Stepper(  # noqa: N802
    steps: Sequence[StepSpec | tuple[str, str, str]],
    *,
    key: str | None = None,
) -> ft.Column:
    """Vertical numbered workflow steps: pending, running (spinning ring), done (check), failed (!) (spec 3.28)."""
    entries = [step if isinstance(step, StepSpec) else StepSpec(*step) for step in steps]
    rows: list[ft.Control] = []
    for index, entry in enumerate(entries):
        if entry.state not in STEP_STATES:
            raise ValueError(f"state must be one of {STEP_STATES}")
        number = str(index + 1)
        if entry.state == "done":
            disc = ft.Container(content=txt("✓", 14, 700, theme.SELECTED_INK),
                                gradient=vgradient(theme.SELECTED_BG, (0, 0.55, 1)),
                                border=ring(theme.SELECTED_RIM))
        elif entry.state == "failed":
            disc = ft.Container(content=txt("!", 15, 700, "#ffffff"),
                                gradient=vgradient(("#ff8a7a", "#c0392b")))
        elif entry.state == "running":
            disc = ft.Container(
                content=ft.Stack(
                    [
                        ft.ProgressRing(width=28, height=28, stroke_width=2, color=theme.ACC),
                        ft.Container(content=txt(number, 12, 700), alignment=ft.Alignment(0, 0), width=28, height=28),
                    ],
                    width=28,
                    height=28,
                )
            )
        else:
            disc = ft.Container(
                content=txt(number, 12, 700, theme.INK2),
                gradient=vgradient((theme.rgba(255, 255, 255, 0.20), theme.rgba(255, 255, 255, 0.07))),
                border=ring(theme.rgba(255, 255, 255, 0.22)),
            )
        disc.width = 28
        disc.height = 28
        disc.border_radius = 14
        disc.alignment = ft.Alignment(0, 0)
        if entry.state != "running":
            disc.shadow = drops(_RAISED_DISC_SHADOWS)
        text: list[ft.Control] = [txt(entry.title, 14.5, 650, trunc=True)]
        if entry.status:
            text.append(txt(entry.status, 12.5, 400, theme.INK2, trunc=True))
        cells: list[ft.Control] = [disc, ft.Column(text, spacing=4, expand=True, tight=True)]
        if entry.action is not None:
            cells.append(entry.action)
        item = ft.Container(
            content=ft.Row(cells, spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=pad(top=12, bottom=12),
        )
        item.data = {"kit": "StepperStep", "index": index, "state": entry.state}
        rows.append(item)
        if index < len(entries) - 1:
            rows.append(hairline(theme.rgba(255, 255, 255, 0.08)))
    column = ft.Column(rows, spacing=0)
    tag_semantics(column, key=key, label=None)
    column.data = {"kit": "Stepper", "states": [entry.state for entry in entries]}
    return column
