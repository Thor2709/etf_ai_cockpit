from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import theme
from etf_cockpit.app import router
from etf_cockpit.app.components.states import STATE_NAMES, state_panel
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS, build_shell, uses_narrow_layout, workspace_for_route
from etf_cockpit.app.state import AppState
from etf_cockpit.core.ui_acceptance import build_main_ui_action_inventory, ui_command_contracts
from etf_cockpit.services import build_snapshot


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def test_state_panel_names_each_state_without_relying_on_colour() -> None:
    for state in STATE_NAMES:
        rendered = state_panel(state, "Test state", "A readable state message")
        text = " ".join(str(control.value) for control in _walk(rendered) if isinstance(control, ft.Text))
        assert f"State: {state}" in text
        assert "A readable state message" in text


def test_workspace_groups_cover_each_registered_route_once() -> None:
    grouped_routes = [route for _workspace, routes in WORKSPACE_GROUPS for route in routes]
    assert set(grouped_routes) == set(PAGES)
    assert len(grouped_routes) == len(set(grouped_routes))
    assert {workspace for workspace, _routes in WORKSPACE_GROUPS} == {
        "Home",
        "Discover",
        "Instrument",
        "Portfolio",
        "Models",
        "Backtest/Paper",
        "Data Health",
        "Audit",
        "Settings",
    }
    assert workspace_for_route("/instrument/VWCE") == "Instrument"


def test_evidence_mode_is_presentation_only_and_validated() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    for mode in theme.EVIDENCE_MODES:
        assert state.set_evidence_mode(mode) == mode
        assert state.evidence_mode == mode
        assert theme.EVIDENCE_MODE_LABELS[mode] in state.last_message
    with pytest.raises(ValueError, match="Unsupported evidence mode"):
        state.set_evidence_mode("execute")


@pytest.mark.parametrize("width", [640, 759, 760, 900, 1100, 1200])
def test_shell_has_grouped_navigation_and_evidence_mode_at_responsive_widths(width: int) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=width, route="/")

    view = build_shell(page, state, "/")
    controls = list(_walk(view))
    keys = {str(control.key) for control in controls if getattr(control, "key", None)}
    labels = {str(control.value) for control in controls if isinstance(control, ft.Text)}

    assert "shell.evidence-mode" in keys
    assert "shell.command-palette" in keys
    assert "Workspace: Home" in labels
    assert theme.APP_NAME in labels
    assert all(workspace in labels for workspace, _routes in WORKSPACE_GROUPS)
    assert uses_narrow_layout(page, state) is (width < 1100)


def test_shell_command_palette_exposes_search_and_enter_instructions() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/")

    view = build_shell(page, state, "/")
    text = " ".join(str(control.value) for control in _walk(view) if isinstance(control, ft.Text))
    fields = [control for control in _walk(view) if isinstance(control, ft.TextField)]

    assert any(field.label == "Command palette" and field.hint_text == "Search pages or commands" for field in fields)
    palette = next(field for field in fields if field.key == "shell.command-palette")
    assert palette.on_change.__name__ == "render_palette_results"
    assert palette.on_submit.__name__ == "submit_palette"
    assert "Workspace: Home" in text


def test_shell_command_palette_filters_and_navigates(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/", update=lambda: None)
    selected: list[str] = []
    monkeypatch.setattr(router, "navigate_to", lambda _page, _state, route: selected.append(route))

    view = build_shell(page, state, "/")
    palette = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command-palette")
    palette.value = "comparison"
    palette.on_change(SimpleNamespace(control=palette))

    result = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command.comparison")
    result.on_click(SimpleNamespace(control=result))
    assert selected == ["/comparison"]

    palette.value = "data"
    palette.on_change(SimpleNamespace(control=palette))
    later_result = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command.data-health")
    later_result.on_click(SimpleNamespace(control=later_result))
    assert selected == ["/comparison", "/data-health"]

    palette.value = "Backtest/Paper"
    palette.on_submit(SimpleNamespace(control=palette))
    assert selected == ["/comparison", "/data-health", "/backtests"]

    palette.value = "no such route"
    palette.on_change(SimpleNamespace(control=palette))
    palette.on_submit(SimpleNamespace(control=palette))
    assert any(
        isinstance(control, ft.Text) and control.value == "No matching workspace"
        for control in _walk(view)
    )
    assert selected == ["/comparison", "/data-health", "/backtests"]

    palette.value = ""
    palette.on_submit(SimpleNamespace(control=palette))
    assert any(
        isinstance(control, ft.Text) and control.value == "Enter a page or workspace to search"
        for control in _walk(view)
    )
    assert selected == ["/comparison", "/data-health", "/backtests"]


def test_palette_control_dispatch_preserves_terminal_result_and_prevents_reinvocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/", update=lambda: None)
    selected: list[str] = []
    monkeypatch.setattr(router, "navigate_to", lambda _page, _state, route: selected.append(route))

    view = build_shell(page, state, "/")
    palette = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command-palette")
    palette.value = "comparison"
    palette.on_change(SimpleNamespace(control=palette))
    result = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command.comparison")
    contract = next(
        item
        for item in ui_command_contracts(build_main_ui_action_inventory())
        if item.action_id == "command:palette:comparison"
    )
    assert result.on_click.__name__ == "select_palette_command"
    assert contract.callback == "navigate_palette_command"
    event = SimpleNamespace(control=result)
    completed = result.on_click(event)
    replayed = result.on_click(event)
    assert selected == ["/comparison"]
    assert completed.status == replayed.status == "completed"
    assert completed.replayed is False and replayed.replayed is True
    assert (replayed.signal, replayed.visible_message) == (completed.signal, completed.visible_message)

    attempts: list[str] = []

    def fail_navigation(_page: object, _state: object, route: str) -> None:
        attempts.append(route)
        raise RuntimeError("controlled palette failure")

    monkeypatch.setattr(router, "navigate_to", fail_navigation)
    failed_state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    failed_view = build_shell(page, failed_state, "/")
    failed_palette = next(
        control for control in _walk(failed_view) if getattr(control, "key", None) == "shell.command-palette"
    )
    failed_palette.value = "comparison"
    failed_palette.on_change(SimpleNamespace(control=failed_palette))
    failed_result = next(
        control for control in _walk(failed_view) if getattr(control, "key", None) == "shell.command.comparison"
    )
    failed_event = SimpleNamespace(control=failed_result)
    failed = failed_result.on_click(failed_event)
    first_failure = failed_state.last_message
    failed_replay = failed_result.on_click(failed_event)
    assert attempts == ["/comparison"]
    assert failed.status == failed_replay.status == "failed"
    assert failed.replayed is False and failed_replay.replayed is True
    assert (failed_replay.signal, failed_replay.visible_message) == (failed.signal, failed.visible_message)
    assert failed_state.last_message == first_failure
    assert contract.controlled_error_signal in first_failure
    assert "Action failed safely: RuntimeError: controlled palette failure" in first_failure
    visible = " ".join(
        str(control.value)
        for control in _walk(failed_view)
        if isinstance(control, ft.Text)
    )
    assert first_failure in visible

def test_unknown_and_failed_routes_render_a_visible_controlled_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/missing")
    monkeypatch.setattr(router, "log_event", lambda **_kwargs: None)

    unknown = build_shell(page, state, "/missing")
    unknown_controls = list(_walk(unknown))
    assert any(getattr(control, "key", None) == "router.route-error" for control in unknown_controls)
    assert any(isinstance(control, ft.Text) and "not registered" in str(control.value) for control in unknown_controls)

    def broken_page(_page: object, _state: object) -> ft.Control:
        raise RuntimeError("private detail")

    monkeypatch.setitem(PAGES, "/broken", ("Broken", broken_page))
    failed = build_shell(page, state, "/broken")
    failed_controls = list(_walk(failed))
    assert any(getattr(control, "key", None) == "router.route-error" for control in failed_controls)
    visible = " ".join(str(control.value) for control in failed_controls if isinstance(control, ft.Text))
    assert "could not be rendered safely (RuntimeError)" in visible
    assert "private detail" not in visible
