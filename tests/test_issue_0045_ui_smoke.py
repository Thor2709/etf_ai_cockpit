from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.pages.data_health import data_health_page
from etf_cockpit.app.router import PAGES, build_shell
from etf_cockpit.app.state import AppState
from etf_cockpit.core.ui_acceptance import build_main_ui_action_inventory
from etf_cockpit.services import build_snapshot


class _TestPage:
    width = 1400
    route = "/"

    def update(self) -> None:
        return None


def _walk(control: ft.Control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _render_state() -> tuple[_TestPage, AppState]:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    return _TestPage(), state


def _controls_by_key(view: ft.Control) -> dict[str, list[ft.Control]]:
    controls: dict[str, list[ft.Control]] = {}
    for control in _walk(view):
        key = getattr(control, "key", None)
        if key:
            controls.setdefault(str(key), []).append(control)
    return controls


def _details_sibling(view: ft.Control, target: ft.Control) -> ft.Container | None:
    def visit(control: ft.Control, ancestors: tuple[ft.Control, ...]) -> ft.Container | None:
        if control is target:
            for ancestor in reversed(ancestors):
                for child in getattr(ancestor, "controls", []) or []:
                    if isinstance(child, ft.Container) and child.visible is False:
                        return child
            return None
        for child in getattr(control, "controls", []) or []:
            found = visit(child, (*ancestors, control))
            if found is not None:
                return found
        content = getattr(control, "content", None)
        if content is not None:
            found = visit(content, (*ancestors, control))
            if found is not None:
                return found
        return None

    return visit(view, ())


def test_dashboard_smoke_exposes_semantic_shell_and_workflow_controls() -> None:
    page, state = _render_state()
    view = build_shell(page, state, "/")
    controls = _controls_by_key(view)

    assert {"dashboard.what-matters-today", "shell.evidence-mode", "shell.command-palette"} <= set(controls)
    workflow_keys = {
        "dashboard.refresh-yfinance",
        "dashboard.run-algorithms",
        "dashboard.run-forecasting-models",
        "dashboard.show-scores",
    }
    assert workflow_keys <= set(controls)
    assert all(callable(getattr(controls[key][0], "on_click", None)) for key in workflow_keys)


def test_navigation_smoke_exposes_every_registered_route() -> None:
    page, state = _render_state()
    view = build_shell(page, state, "/")
    controls = _controls_by_key(view)
    expected = {
        f"navigation.{route.strip('/').replace('/', '-') or 'home'}"
        for route in PAGES
    }

    assert expected <= set(controls)
    assert all(callable(getattr(controls[key][0], "on_click", None)) for key in expected)


def test_score_row_expand_callback_toggles_details_visibility() -> None:
    page, state = _render_state()
    view = build_shell(page, state, "/")
    arrow = next(
        control
        for control in _walk(view)
        if str(getattr(control, "key", "")).startswith("dashboard.score-row-expand.")
    )

    details = _details_sibling(view, arrow)

    assert callable(getattr(arrow, "on_click", None))
    assert details is not None
    assert details.visible is False
    arrow.on_click(SimpleNamespace(page=page))
    assert details.visible is True
    arrow.on_click(SimpleNamespace(page=page))
    assert details.visible is False


def test_export_controls_are_present_and_non_authoritative() -> None:
    page, state = _render_state()
    dashboard = build_shell(page, state, "/")
    data_health = data_health_page(page, state)
    controls = _controls_by_key(dashboard)
    controls.update({key: values for key, values in _controls_by_key(data_health).items()})

    assert {"dashboard.export-audit", "data-health.export"} <= set(controls)
    inventory = {
        item.key: item
        for item in build_main_ui_action_inventory()
        if item.key in {"dashboard.export-audit", "data-health.export"}
    }
    assert set(inventory) == {"dashboard.export-audit", "data-health.export"}
    assert all(item.execution_allowed is False for item in inventory.values())


def test_flet_canvas_locator_limitation_remains_recorded() -> None:
    issue_text = Path("issues/open.md").read_text(encoding="utf-8")
    assert "Flet web exposes minimal semantic DOM for this canvas-style UI" in issue_text
    assert "coordinate/screenshot verification remains necessary" in issue_text
