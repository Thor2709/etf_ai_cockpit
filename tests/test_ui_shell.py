from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.state import AppState
from etf_cockpit.app.router import NARROW_LAYOUT_BREAKPOINT, WORKSPACE_GROUPS, build_shell, uses_narrow_layout
from etf_cockpit.application.snapshot_builder import build_snapshot


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


EXPECTED_WORKSPACES = (
    ("Home", ("/", "/onboarding")),
    ("Universe", ("/universe", "/data-health", "/providers", "/catalogue", "/filings", "/etf-disclosures", "/news-context")),
    ("Research", ("/stock-research", "/instrument", "/etf", "/signals", "/screener", "/strategy-builder")),
    (
        "Portfolio",
        ("/portfolio", "/risk", "/portfolio-optimiser", "/stress-lab", "/decision-journal", "/forward-evidence", "/operations"),
    ),
    ("Compare", ("/comparison",)),
    ("Lab", ("/forecasts", "/backtests", "/training-centre", "/feature-catalogue", "/data-models")),
    ("Map", ("/sectors", "/macro")),
    ("Changes", ("/what-changed", "/jobs")),
    (
        "Help",
        (
            "/help",
            "/settings",
            "/import-export",
            "/diagnostics",
            "/errors",
            "/evidence",
            "/chatgpt",
            "/system-map",
            "/release-readiness",
            "/roadmap",
        ),
    ),
)

EXPECTED_ICONS = {
    "Home": "house",
    "Universe": "globe",
    "Research": "telescope",
    "Portfolio": "briefcase",
    "Compare": "abacus",
    "Lab": "alembic",
    "Map": "compass",
    "Changes": "newspaper",
    "Help": "bulb",
}


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


def _texts(control: ft.Control) -> list[str]:
    values = [str(item.value) for item in _walk(control) if isinstance(item, ft.Text)]
    return values


def test_workspaces_cover_every_route_once_in_dock_order() -> None:
    assert WORKSPACE_GROUPS == EXPECTED_WORKSPACES
    grouped_routes = [route for _workspace, routes in WORKSPACE_GROUPS for route in routes]
    assert len(grouped_routes) == 42
    assert len(grouped_routes) == len(router.PAGES) == len(set(grouped_routes))
    assert set(grouped_routes) == set(router.PAGES)
    assert router.workspace_for_route("/instrument/VWCE") == "Research"
    assert router.workspace_for_route("/sectors") == "Map"


def test_dock_keys_labels_order_tooltips_and_package_icons(snapshot) -> None:
    view = build_shell(SimpleNamespace(width=1920, height=1200, route="/"), _state(snapshot), "/")
    dock = _by_key(view, "shell.dock")
    items = [control for control in _walk(dock) if str(getattr(control, "key", "")).startswith("nav.workspace.")]
    workspaces = tuple(workspace for workspace, _routes in EXPECTED_WORKSPACES)

    assert router.WORKSPACE_ICONS == EXPECTED_ICONS
    assert [item.key for item in items] == [f"nav.workspace.{workspace}" for workspace in workspaces]
    assert [item.data for item in items].count("active") == 1 and items[0].data == "active"
    research = next(item for item in items if item.key == "nav.workspace.Research")
    assert research.tooltip.startswith("Research — Stock Research, Instrument Detail, Scores")
    assert research.tooltip.count("Instrument Detail") == 1  # /etf alias is not listed twice
    assert dock.width == 84
    visible_labels = [
        c for c in _walk(dock) if str(getattr(c, "key", "") or "").startswith("shell.dock.label.") and c.visible
    ]
    assert [label.key for label in visible_labels] == ["shell.dock.label.Home"]

    dock_column = dock.content.controls[0].content
    assert dock_column.controls[-2].key == "shell.dock.help-spacer"
    assert dock_column.controls[-1].key == "nav.workspace.Help"

    app = Path(router.__file__).parent
    images = [control for control in _walk(dock) if isinstance(control, ft.Image)]
    assert len(images) == 9
    for workspace, image_name in EXPECTED_ICONS.items():
        image = next(item for item in images if item.semantics_label == f"{workspace} workspace icon")
        assert image.src == f"icons/{image_name}.png"
        assert (app / "assets" / image.src).read_bytes()[1:4] == b"PNG"


def test_footer_rail_shows_state_or_explained_unavailable(snapshot) -> None:
    state = _state(snapshot)
    view = build_shell(SimpleNamespace(width=1920, height=1200, route="/"), state, "/")
    rail = _by_key(view, "shell.safety-rail")
    assert rail.height == 48
    assert "Execution locked" in _texts(_by_key(view, "shell.safety.execution"))
    assert any(str(state.snapshot.data_report.status) in v or v in {"OK", "Review", "Failed"} for v in _texts(_by_key(view, "shell.safety.data-quality")))
    assert "adjusted" in _texts(_by_key(view, "shell.safety.price-basis"))
    assert any("execution_allowed=false" in v for v in _texts(_by_key(view, "shell.safety.execution-authority")))
    depth = _by_key(view, "shell.as-of.analysis-depth")
    assert "Depth:" in _texts(depth) and depth.on_click is not None
    assert _by_key(view, "shell.as-of.profile").on_click is not None

    unavailable_snapshot = replace(
        state.snapshot,
        data_report=SimpleNamespace(status=None, as_of_date=None),
        forecasts=None,
    )
    unavailable_view = build_shell(SimpleNamespace(width=1920, height=1200, route="/"), _state(unavailable_snapshot), "/")
    for key in ("shell.safety.data-quality", "shell.safety.as-of-time", "shell.safety.forecast-source"):
        item = _by_key(unavailable_view, key)
        assert any("Unavailable" in value for value in _texts(item))
        assert item.data == "unavailable"
        assert isinstance(item.tooltip, str) and item.tooltip
    assert any("execution_allowed=false" in v for v in _texts(_by_key(unavailable_view, "shell.safety.execution-authority")))


@pytest.mark.parametrize(("width", "narrow"), [(1920, False), (1000, True)])
def test_shell_layout_resizes_in_place(snapshot, width: int, narrow: bool) -> None:
    page = SimpleNamespace(width=width, height=1000, route="/")
    state = _state(snapshot)
    view = build_shell(page, state, "/")
    dock = _by_key(view, "shell.dock")
    label = _by_key(view, "shell.dock.label.Home")
    topbar = _by_key(view, "shell.topbar")

    assert uses_narrow_layout(page, state) is narrow
    assert NARROW_LAYOUT_BREAKPOINT == 1100
    assert dock.width == (64 if narrow else 84)
    assert label.visible is not narrow
    assert _by_key(view, "shell.command-palette")
    assert topbar.height == 80
    row = topbar.content.controls[0].content
    assert row.wrap is False  # the top bar never wraps
    content_area = _by_key(view, "shell.content")
    assert any(
        control.key == "dashboard.refresh-yfinance"
        for control in _walk(content_area)
        if getattr(control, "key", None)
    )
    assert _by_key(view, "dashboard.open-what-changed").on_click is not None

    flipped = 1920 if narrow else 1000
    assert view.data["relayout"](flipped) is True
    assert dock.width == (84 if narrow else 64)
    assert label.visible is narrow
    assert view.data["relayout"](width) is True
    assert label.visible is not narrow
