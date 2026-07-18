from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import theme
from etf_cockpit.app.components.states import STATE_NAMES, state_panel
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS, build_shell, workspace_for_route
from etf_cockpit.app.state import AppState
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


@pytest.mark.parametrize("width", [640, 1200])
def test_shell_has_grouped_navigation_and_evidence_mode_at_responsive_widths(width: int) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=width, route="/")

    view = build_shell(page, state, "/")
    controls = list(_walk(view))
    keys = {str(control.key) for control in controls if getattr(control, "key", None)}
    labels = {str(control.value) for control in controls if isinstance(control, ft.Text)}

    assert "shell.evidence-mode" in keys
    assert "Workspace: Home" in labels
    assert theme.APP_NAME in labels
    assert all(workspace in labels for workspace, _routes in WORKSPACE_GROUPS)
