"""Router-level page-help integration checks for ISSUE-0043."""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.content.user_guidance import get_page_guidance
from etf_cockpit.app.router import PAGES, build_shell
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


@pytest.mark.parametrize("route", tuple(PAGES))
def test_every_registered_route_has_page_help_topic(route: str) -> None:
    assert get_page_guidance(route)


@pytest.mark.parametrize("width", (800, 1200))
@pytest.mark.parametrize("route", ("/", "/instrument/VWCE"))
def test_shell_renders_page_help_and_targets_first_topic(
    monkeypatch: pytest.MonkeyPatch,
    width: int,
    route: str,
) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=width, route=route)
    selected: list[str] = []
    monkeypatch.setattr(router, "navigate_to", lambda _page, _state, target: selected.append(target))

    view = build_shell(page, state, route)
    control = next(item for item in _walk(view) if getattr(item, "key", None) == "shell.page-help")
    assert isinstance(control, ft.TextButton)
    assert callable(control.on_click)
    assert control.disabled is False
    assert control.tooltip == f"Open help: {get_page_guidance(route)[0].title}"

    control.on_click(SimpleNamespace(control=control))
    assert selected == [f"/help#{get_page_guidance(route)[0].slug}"]


def test_unknown_route_page_help_fails_closed() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/missing")

    view = build_shell(page, state, "/missing")
    control = next(item for item in _walk(view) if getattr(item, "key", None) == "shell.page-help")
    assert isinstance(control, ft.TextButton)
    assert control.on_click is None
    assert control.disabled is True
