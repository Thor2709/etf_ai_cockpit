from __future__ import annotations

import base64
from dataclasses import replace
from importlib.resources import files
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.state import AppState
from etf_cockpit.app.router import NARROW_LAYOUT_BREAKPOINT, WORKSPACE_GROUPS, build_shell, uses_narrow_layout
from etf_cockpit.services import build_snapshot


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


EXPECTED_WORKSPACES = (
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
        (
            "/help",
            "/settings",
            "/diagnostics",
            "/errors",
            "/import-export",
            "/system-map",
            "/chatgpt",
            "/evidence",
            "/release-readiness",
            "/roadmap",
        ),
    ),
)

EXPECTED_ICONS = {
    "Home": "house",
    "Research": "telescope",
    "Compare": "abacus",
    "Map": "compass",
    "Universe": "globe",
    "Portfolio": "briefcase",
    "Lab": "alembic",
    "Changes": "newspaper",
    "Help": "bulb",
}

EXPECTED_GROUPS = EXPECTED_WORKSPACES


def _walk(control: ft.Control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        if isinstance(child, ft.Control):
            yield from _walk(child)


def _by_key(view: ft.View, key: str) -> ft.Control:
    return next(control for control in _walk(view) if getattr(control, "key", None) == key)


def _text_values(control: ft.Control) -> list[str]:
    return [item.value for item in _walk(control) if isinstance(item, ft.Text)]


def _texts(control: ft.Control) -> list[str]:
    return [str(item.value) for item in _walk(control) if isinstance(item, ft.Text)]


def test_workspaces_cover_every_route_once_in_dock_order() -> None:
    assert WORKSPACE_GROUPS == EXPECTED_WORKSPACES
    grouped_routes = [route for _workspace, routes in WORKSPACE_GROUPS for route in routes]
    assert len(grouped_routes) == 41
    assert len(grouped_routes) == len(router.PAGES) == len(set(grouped_routes))
    assert set(grouped_routes) == set(router.PAGES)
    assert router.workspace_for_route("/instrument/VWCE") == "Research"


def test_dock_keys_labels_order_and_package_icons(snapshot) -> None:
    view = build_shell(SimpleNamespace(width=1920, route="/"), _state(snapshot), "/")
    dock = _by_key(view, "shell.dock")
    items = [control for control in _walk(dock) if str(getattr(control, "key", "")).startswith("nav.workspace.")]
    workspaces = tuple(workspace for workspace, _routes in EXPECTED_WORKSPACES)

    assert router.WORKSPACE_ICONS == EXPECTED_ICONS
    assert [item.key for item in items] == [f"nav.workspace.{workspace}" for workspace in workspaces]
    assert [item.tooltip for item in items] == [f"Workspace: {workspace}" for workspace in workspaces]
    assert sum(item.data == "active" for item in items) == 1
    assert [item.key.removeprefix("nav.workspace.") for item in items if item.data == "active"] == ["Home"]
    assert sum(
        control.visible
        for control in _walk(dock)
        if getattr(control, "key", "") and str(control.key).startswith("shell.dock.label.")
    ) == 1

    active = next(item for item in items if item.data == "active")
    active_pad = next(
        control
        for control in _walk(active)
        if isinstance(control, ft.Container) and getattr(control, "width", None) == 54
    )
    assert active_pad.gradient.colors == list(router.theme.QUAIL_SELECTED_COLORS)
    assert [
        button.key
        for button in _walk(_by_key(view, "shell.workspace-navigation"))
        if str(getattr(button, "key", "")).startswith("navigation.")
    ] == ["navigation.home", "navigation.onboarding"]

    dock_column = dock.content
    assert dock_column.controls[-2].key == "shell.dock.help-spacer"
    assert dock_column.controls[-1].key == "nav.workspace.Help"

    images = [control for control in _walk(dock) if isinstance(control, ft.Image)]
    assert len(images) == 9
    for workspace, image_name in EXPECTED_ICONS.items():
        image = next(item for item in images if item.semantics_label == f"{workspace} workspace icon")
        packaged = files("etf_cockpit.app").joinpath("assets", "icons", f"{image_name}.png").read_bytes()
        assert packaged.startswith(b"\x89PNG\r\n\x1a\n")
        assert int.from_bytes(packaged[16:20], "big") == 160
        assert int.from_bytes(packaged[20:24], "big") == 160
        assert image.src.startswith("data:image/png;base64,")
        assert base64.b64decode(image.src.split(",", 1)[1]) == packaged


def test_as_of_bar_and_safety_rail_show_state_or_explained_unavailable(snapshot) -> None:
    state = _state(snapshot)
    view = build_shell(SimpleNamespace(width=1920, route="/"), state, "/")
    as_of_date = str(state.snapshot.data_report.as_of_date)

    assert as_of_date in _texts(_by_key(view, "shell.as-of.data-date"))
    for key in (
        "shell.as-of.horizon",
        "shell.as-of.currency",
        "shell.as-of.risk-profile",
        "shell.as-of.analysis-depth",
        "shell.safety.as-of-time",
    ):
        item = _by_key(view, key)
        assert any("Unavailable" in value for value in _texts(item))
        assert isinstance(item.tooltip, str) and item.tooltip
    assert "adjusted" in _texts(_by_key(view, "shell.as-of.price-basis"))
    assert any("adjusted" in value for value in _texts(_by_key(view, "shell.safety.price-basis")))
    assert any(str(state.snapshot.data_report.status) in value for value in _texts(_by_key(view, "shell.safety.data-quality")))
    assert "execution_allowed=false" in _texts(_by_key(view, "shell.safety.execution-authority"))
    assert "Execution locked" in _texts(_by_key(view, "shell.safety.execution"))

    missing_date_report = replace(state.snapshot.data_report, as_of_date=None)
    missing_date_snapshot = replace(state.snapshot, data_report=missing_date_report)
    missing_date_view = build_shell(
        SimpleNamespace(width=1920, route="/"),
        _state(missing_date_snapshot),
        "/",
    )
    date_pill = _by_key(missing_date_view, "shell.as-of.data-date")
    assert "Unavailable" in _texts(date_pill)
    assert isinstance(date_pill.tooltip, str) and date_pill.tooltip

    unavailable_snapshot = replace(
        state.snapshot,
        data_report=SimpleNamespace(status=None, as_of_date=None),
        forecasts=None,
    )
    unavailable_view = build_shell(
        SimpleNamespace(width=1920, route="/"),
        _state(unavailable_snapshot),
        "/",
    )
    for key in (
        "shell.as-of.data-date",
        "shell.as-of.horizon",
        "shell.as-of.currency",
        "shell.as-of.risk-profile",
        "shell.as-of.analysis-depth",
        "shell.safety.data-quality",
        "shell.safety.as-of-time",
        "shell.safety.forecast-source",
    ):
        item = _by_key(unavailable_view, key)
        assert any("Unavailable" in value for value in _texts(item))
        assert item.data == "unavailable"
        assert isinstance(item.tooltip, str) and item.tooltip
    assert any("adjusted" in value for value in _texts(_by_key(unavailable_view, "shell.safety.price-basis")))
    assert "execution_allowed=false" in _texts(_by_key(unavailable_view, "shell.safety.execution-authority"))


@pytest.mark.parametrize(("width", "narrow"), [(1920, False), (1000, True)])
def test_shell_layout_wraps_and_hides_dock_labels_when_narrow(
    snapshot,
    width: int,
    narrow: bool,
) -> None:
    page = SimpleNamespace(width=width, route="/")
    state = _state(snapshot)
    view = build_shell(page, state, "/")
    dock = _by_key(view, "shell.dock")
    label = _by_key(view, "shell.dock.label.Home")
    topbar = _by_key(view, "shell.topbar")

    assert uses_narrow_layout(page, state) is narrow
    assert NARROW_LAYOUT_BREAKPOINT == 1100
    assert dock.width == 84
    assert label.visible is not narrow
    assert _by_key(view, "shell.command-palette")
    assert _by_key(view, "shell.evidence-mode")
    assert _by_key(view, "shell.safety-rail").height == 48
    assert topbar.content.controls[0].wrap is True
    assert topbar.content.controls[1].wrap is True
    assert topbar.content.controls[2].wrap is True
    content_area = _by_key(view, "shell.content")
    assert any(
        control.key == "dashboard.refresh-yfinance"
        for control in _walk(content_area)
        if getattr(control, "key", None)
    )

    if not narrow:
        assert view.data["relayout"](1000) is True
        assert label.visible is False
        assert view.data["relayout"](1920) is True
        assert label.visible is True
