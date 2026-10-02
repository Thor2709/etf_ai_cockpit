from __future__ import annotations

import base64
from dataclasses import replace
from importlib.resources import files
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _walk(control):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)


def _texts(control) -> list[str]:
    return [str(item.value) for item in _walk(control) if isinstance(item, ft.Text)]


def _control(view, key: str):
    return next(control for control in _walk(view) if getattr(control, "key", None) == key)


EXPECTED_GROUPS = (
    ("Home", ("/", "/onboarding")),
    ("Research", ("/stock-research", "/etf", "/instrument", "/signals", "/screener", "/strategy-builder")),
    ("Compare", ("/comparison",)),
    ("Map", ("/macro",)),
    (
        "Universe",
        ("/universe", "/catalogue", "/providers", "/filings", "/etf-disclosures", "/news-context", "/data-health"),
    ),
    (
        "Portfolio",
        ("/portfolio", "/portfolio-optimiser", "/risk", "/stress-lab", "/decision-journal", "/forward-evidence", "/operations"),
    ),
    ("Lab", ("/forecasts", "/training-centre", "/feature-catalogue", "/data-models", "/backtests")),
    ("Changes", ("/what-changed", "/jobs")),
    (
        "Help",
        ("/help", "/settings", "/diagnostics", "/errors", "/import-export", "/system-map", "/chatgpt", "/evidence", "/release-readiness", "/roadmap"),
    ),
)


def test_nine_workspaces_cover_every_registered_route_once_in_dock_order() -> None:
    grouped_routes = [route for _workspace, routes in router.WORKSPACE_GROUPS for route in routes]

    assert router.WORKSPACE_GROUPS == EXPECTED_GROUPS
    assert len(grouped_routes) == len(router.PAGES) == len(set(grouped_routes))
    assert set(grouped_routes) == set(router.PAGES)
    assert router.workspace_for_route("/instrument/VWCE") == "Research"


def test_dock_has_accessible_workspace_icons_active_pad_and_bottom_help(snapshot) -> None:
    view = router.build_shell(SimpleNamespace(width=1920, route="/"), _state(snapshot), "/")
    dock = _control(view, "shell.dock")
    items = [
        control
        for control in _walk(dock)
        if str(getattr(control, "key", "")).startswith("nav.workspace.")
    ]

    assert len(items) == 9
    assert [item.key for item in items] == [f"nav.workspace.{name}" for name, _routes in EXPECTED_GROUPS]
    assert [item.tooltip for item in items] == [f"Workspace: {name}" for name, _routes in EXPECTED_GROUPS]
    assert sum(item.data == "active" for item in items) == 1
    assert items[-1].key == "nav.workspace.Help"
    active = next(item for item in items if item.data == "active")
    assert active.gradient.colors == list(router.theme.QUAIL_SELECTED_COLORS)
    assert [
        button.key
        for button in _walk(_control(view, "shell.workspace-navigation"))
        if str(getattr(button, "key", "")).startswith("navigation.")
    ] == [
        "navigation.home",
        "navigation.onboarding",
    ]

    for (workspace, _routes), item in zip(EXPECTED_GROUPS, items):
        icon_name = router.WORKSPACE_ICONS[workspace]
        asset = files("etf_cockpit.app").joinpath("assets", "icons", f"{icon_name}.png").read_bytes()
        image = next(control for control in _walk(item) if isinstance(control, ft.Image))
        assert image.src.startswith("data:image/png;base64,")
        assert base64.b64decode(image.src.partition(",")[2]) == asset

    dock_children = dock.content.controls
    assert dock_children[-1].key == "nav.workspace.Help"
    assert dock_children[-2].key == "shell.dock.help-spacer"


def test_as_of_bar_and_safety_rail_show_state_or_explained_unavailable(snapshot) -> None:
    state = _state(snapshot)
    view = router.build_shell(SimpleNamespace(width=1920, route="/"), state, "/")
    as_of_date = str(state.snapshot.data_report.as_of_date)

    assert as_of_date in _texts(_control(view, "shell.as-of.data-date"))
    for key in (
        "shell.as-of.horizon",
        "shell.as-of.currency",
        "shell.as-of.risk-profile",
        "shell.as-of.analysis-depth",
        "shell.safety.as-of-time",
    ):
        item = _control(view, key)
        assert any("Unavailable" in value for value in _texts(item))
        assert isinstance(item.tooltip, str) and item.tooltip
    assert "adjusted" in _texts(_control(view, "shell.as-of.price-basis"))
    assert any("adjusted" in value for value in _texts(_control(view, "shell.safety.price-basis")))
    assert any(
        str(state.snapshot.data_report.status) in value
        for value in _texts(_control(view, "shell.safety.data-quality"))
    )
    assert "execution_allowed=false" in _texts(_control(view, "shell.safety.execution-authority"))
    assert "Execution locked" in _texts(_control(view, "shell.safety.execution"))

    missing_date_report = replace(state.snapshot.data_report, as_of_date=None)
    missing_date_snapshot = replace(state.snapshot, data_report=missing_date_report)
    missing_date_view = router.build_shell(
        SimpleNamespace(width=1920, route="/"),
        _state(missing_date_snapshot),
        "/",
    )
    date_pill = _control(missing_date_view, "shell.as-of.data-date")
    assert "Unavailable" in _texts(date_pill)
    assert isinstance(date_pill.tooltip, str) and date_pill.tooltip


@pytest.mark.parametrize(("width", "narrow"), ((1920, False), (1000, True)))
def test_shell_builds_at_desktop_and_narrow_widths_with_collapsed_dock_labels(snapshot, width: int, narrow: bool) -> None:
    page = SimpleNamespace(width=width, route="/")
    view = router.build_shell(page, _state(snapshot), "/")
    dock_label = _control(view, "shell.dock.label.Home")

    assert router.uses_narrow_layout(page, _state(snapshot)) is narrow
    assert dock_label.visible is not narrow
    assert len([item for item in _walk(view) if str(getattr(item, "key", "")).startswith("nav.workspace.")]) == 9
    assert _control(view, "shell.content") is not None
    assert _control(view, "shell.safety-rail").height == 48
