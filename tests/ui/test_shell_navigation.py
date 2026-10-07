"""Shell navigation: dock order, page menu, Alt+digit, slash search, one update per navigation, both page kinds."""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.components.shell.page_menu import build_page_menu, menu_routes
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS, build_shell
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _by_key(view, key):
    return next(c for c in _walk(view) if getattr(c, "key", None) == key)


def _page(width=1920, height=1200, route="/"):
    return SimpleNamespace(width=width, height=height, route=route)


def test_sectors_route_is_registered_in_map_workspace() -> None:
    assert "/sectors" in PAGES and PAGES["/sectors"][0] == "Sectors & Countries"
    assert dict(WORKSPACE_GROUPS)["Map"][0] == "/sectors"


def test_page_menu_lists_workspace_pages_once_and_marks_current() -> None:
    routes = dict(WORKSPACE_GROUPS)["Research"]
    menu = build_page_menu(routes, "/signals", PAGES, navigate_to=lambda _r: None)
    assert menu.routes == menu_routes(routes) and "/etf" not in menu.routes
    assert len(menu.rows) == len(menu.routes) == 5
    menu.highlight(99)
    assert menu.state["index"] == 4


def test_pageview_and_legacy_pages_both_render_in_the_shell(snapshot, monkeypatch) -> None:
    state = _state(snapshot)
    legacy = build_shell(_page(route="/comparison"), state, "/comparison")
    assert _by_key(legacy, "shell.topbar")

    chrome = PageChrome("Probe", "Probe subtitle", (SegmentGroup("view", ["A", "B"], "A"),))
    renderers = dict(router.PAGES)
    renderers["/probe"] = ("Probe", lambda _p, _s: PageView(chrome, ft.Container(key="probe.body")))
    monkeypatch.setattr(router, "PAGES", renderers)
    view = build_shell(_page(route="/probe"), state, "/probe")
    assert _by_key(view, "probe.body")
    assert _by_key(view, "shell.view.view")
    assert "Probe subtitle" in [c.value for c in _walk(view) if isinstance(c, ft.Text)]


def test_keyboard_path_alt_digits_open_dock_order_workspaces(snapshot) -> None:
    page = SimpleNamespace(width=1920, height=1200, route="/", views=[], update=lambda: None)
    view = build_shell(page, _state(snapshot), "/")
    # Alt+7 is Map in dock order; its default page is /sectors.
    assert view.data["on_key"](SimpleNamespace(key="7", alt=True, ctrl=False)) is True
    assert page.route == "/sectors"
    assert view.data["on_key"](SimpleNamespace(key="x", alt=False, ctrl=False)) is False


def test_navigation_does_one_page_update_for_shell_pages(snapshot) -> None:
    updates: list[int] = []
    page = SimpleNamespace(width=1920, height=1200, route="/", views=[], update=lambda: updates.append(1))
    router.render_shell(page, _state(snapshot), "/sectors")
    assert len(updates) == 1 and page.views[0].route == "/sectors"
