"""Top-bar search (spec 5.2): filters pages, instruments, glossary terms and commands; ``/`` focuses, Esc clears."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.command_palette import search_commands
from etf_cockpit.app.components.kit import Tag
from etf_cockpit.app.components.kit._base import ring, sym, txt
from etf_cockpit.app.components.kit.controls import field_input_style
from etf_cockpit.app.components.shell._glass import glass
from etf_cockpit.app.components.shell.overlay import Overlay
from etf_cockpit.core.ui_acceptance import UIInvocationResult, command_contract_from_metadata

SEARCH_WIDTH = 340
SEARCH_WIDTH_COMPACT = 220
ROW_HEIGHT = 44
MAX_RESULTS = 8
_GLOSSARY: list[str] | None = None


def _glossary_terms() -> list[str]:
    global _GLOSSARY
    if _GLOSSARY is None:
        try:
            from etf_cockpit.application.scope_facade import load_glossary

            loaded = load_glossary()
            _GLOSSARY = [] if loaded.policy is None or loaded.diagnostic_mode else [e.term for e in loaded.policy.entries]
        except Exception:
            return []  # a transient load error is not cached for the whole process
    return _GLOSSARY


def _slug(term: str) -> str:
    return term.casefold().replace(" ", "-").replace("/", "-")


@dataclass
class Search:
    box: ft.Container
    field: ft.TextField
    status: dict
    set_compact: Callable[[bool], None]
    focus: Callable[[], None]
    clear: Callable[[], None]


def build_search(
    page: ft.Page,
    state: object,
    pages: Mapping[str, tuple[str, object]],
    workspace_groups: Sequence[tuple[str, Sequence[str]]],
    *,
    navigate: Callable[[str], None],
    overlay: Overlay,
    anchor_left: Callable[[], float],
    anchor_top: float,
    compact: bool,
) -> Search:
    palette_commands: dict[str, object] = {}
    palette_invocations: dict[str, UIInvocationResult] = {}
    status = {"focused": False}

    def navigate_target(route: str) -> None:
        state.last_message = ""  # type: ignore[attr-defined]
        navigate(route)

    def navigate_palette_command(event: ft.ControlEvent) -> None:
        route = str(getattr(getattr(event, "control", None), "data", "") or "")
        if not route:
            raise ValueError("selected command has no registered route")
        navigate_target(route)

    def show_palette_message(message: str) -> None:
        state.last_message = message  # type: ignore[attr-defined]
        panel = glass(
            ft.Container(
                content=txt(message, 13.5, 500, theme.INK, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                padding=sym(16, 12),
            ),
            radius=22,
            width=SEARCH_WIDTH + 80,
            height=ROW_HEIGHT + 20,
        )
        overlay.show("search", panel, anchor_left(), anchor_top, catch_outside=False)

    def select_palette_command(event: ft.ControlEvent) -> UIInvocationResult | None:
        route = str(getattr(getattr(event, "control", None), "data", "") or "")
        command = palette_commands.get(route)
        if command is None:
            show_palette_message("Selected command has no registered route")
            return None
        contract = command_contract_from_metadata(command)
        result = contract.invoke(navigate_palette_command, event, invoked=palette_invocations, show_failure=lambda _message: None)
        if result.status == "failed":
            show_palette_message(f"{result.signal} · {result.visible_message}")
        return result

    def row_content(icon: str, name: str, kind: str) -> ft.Row:
        return ft.Row(
            [
                ft.Icon(icon, size=18, color=theme.INK3),
                ft.Container(content=txt(name, 14, 500, theme.INK, trunc=True), expand=True),
                Tag(kind, "mute", dense=True),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def plain_row(icon: str, name: str, kind: str, on_click: Callable) -> ft.Control:
        return ft.Container(
            content=row_content(icon, name, kind),
            height=ROW_HEIGHT,
            padding=sym(12, 0),
            border_radius=14,
            ink=True,
            ink_color=theme.HOVER_OVERLAY,
            on_click=on_click,
        )

    def render_palette_results(event: ft.ControlEvent) -> None:
        query = str(getattr(getattr(event, "control", None), "value", None) or "").strip()
        if not query:
            overlay.hide(update=True)
            return
        needle = query.casefold()
        rows: list[ft.Control] = []
        matches = search_commands(pages, workspace_groups, query, limit=MAX_RESULTS)
        palette_commands.update({command.route: command for command in matches})
        for command in matches:
            rows.append(
                ft.TextButton(
                    content=row_content(ft.Icons.ARTICLE_OUTLINED, command.title, command.workspace),
                    key=f"shell.command.{command.route.strip('/').replace('/', '-') or 'home'}",
                    tooltip=f"Open {command.title}",
                    data=command.route,
                    on_click=select_palette_command,
                    style=ft.ButtonStyle(
                        padding=sym(12, 0),
                        shape=ft.RoundedRectangleBorder(radius=14),
                        bgcolor="transparent",
                        overlay_color=theme.HOVER_OVERLAY,
                    ),
                    height=ROW_HEIGHT,
                )
            )
        universe = getattr(getattr(getattr(state, "snapshot", None), "config", None), "universe", None)
        for item in getattr(universe, "etfs", ()) or ():
            instrument_id, name = str(getattr(item, "id", "")), str(getattr(item, "name", "") or "")
            if len(rows) >= MAX_RESULTS:
                break
            if needle in f"{instrument_id} {name}".casefold():
                label = f"{instrument_id} · {name}" if name else instrument_id
                rows.append(
                    plain_row(ft.Icons.SHOW_CHART, label, "Instrument", lambda _e, i=instrument_id: navigate_target(f"/instrument/{i}"))
                )
        for term in _glossary_terms():
            if len(rows) >= MAX_RESULTS:
                break
            if needle in term.casefold():
                rows.append(plain_row(ft.Icons.MENU_BOOK_OUTLINED, term, "Glossary", lambda _e, t=term: navigate_target(f"/help#{_slug(t)}")))
        rows = rows[:MAX_RESULTS]
        if not rows:
            rows = [
                ft.Container(
                    content=txt("No matching page, instrument or term", 13.5, 500, theme.AMBER),
                    height=ROW_HEIGHT,
                    padding=sym(12, 0),
                    alignment=ft.Alignment(-1, 0),
                )
            ]
        panel = glass(
            ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO),
            radius=22,
            padding=8,
            width=SEARCH_WIDTH + 80,
            height=len(rows) * ROW_HEIGHT + 16,
            key="shell.search-results",
        )
        overlay.show("search", panel, anchor_left(), anchor_top, catch_outside=False)

    def submit_palette(event: ft.ControlEvent) -> None:
        query = str(getattr(getattr(event, "control", None), "value", None) or "")
        if not query.strip():
            show_palette_message("Enter a page or workspace to search")
            return
        matches = search_commands(pages, workspace_groups, query, limit=1)
        if matches:
            navigate_target(matches[0].route)
            return
        universe = getattr(getattr(getattr(state, "snapshot", None), "config", None), "universe", None)
        needle = query.strip().casefold()
        for item in getattr(universe, "etfs", ()) or ():
            instrument_id = str(getattr(item, "id", "") or "")
            name = str(getattr(item, "name", "") or "")
            if needle and needle in f"{instrument_id} {name}".casefold():
                navigate_target(f"/instrument/{instrument_id}")
                return
        for term in _glossary_terms():
            if needle and needle in term.casefold():
                navigate_target(f"/help#{_slug(term)}")
                return
        show_palette_message("No matching page, instrument or term")

    def on_focus(_event: object) -> None:
        status["focused"] = True

    def on_blur(_event: object) -> None:
        status["focused"] = False

    field = ft.TextField(
        key="shell.command-palette",
        on_change=render_palette_results,
        on_submit=submit_palette,
        on_focus=on_focus,
        on_blur=on_blur,
        expand=True,
        **field_input_style(placeholder="Search or jump to…"),
    )
    hint = ft.Container(
        content=txt("/", 11, 600, theme.INK2),
        padding=ft.Padding(7, 3, 7, 3),
        border_radius=6,
        bgcolor=theme.rgba(128, 128, 128, 0.2),
    )
    box = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.SEARCH, size=18, color=theme.INK3), field, hint],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=SEARCH_WIDTH_COMPACT if compact else SEARCH_WIDTH,
        height=44,
        padding=sym(14, 0),
        border_radius=14,
        bgcolor=theme.SEGMENT_TRACK_FILL,
        border=ring(theme.rgba(0, 0, 0, 0.20)),
    )

    def set_compact(value: bool) -> None:
        box.width = SEARCH_WIDTH_COMPACT if value else SEARCH_WIDTH

    def focus() -> None:
        runner = getattr(page, "run_task", None)
        if callable(runner):
            runner(field.focus)

    def clear() -> None:
        field.value = ""
        overlay.hide()

    return Search(box, field, status, set_compact, focus, clear)
