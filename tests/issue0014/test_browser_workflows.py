from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app import flet_app
from etf_cockpit.app.flet_app import initialise_page
from etf_cockpit.app.router import navigate_to
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot
from scripts import smoke_app


class _BrowserPage:
    def __init__(self) -> None:
        self.route = "/"
        self.views: list[object] = []
        self.width = 1400
        self.update_count = 0
        self.go_calls: list[str] = []
        self.window = SimpleNamespace()

    def update(self) -> None:
        self.update_count += 1

    def go(self, route: str) -> None:
        self.go_calls.append(route)
        self.route = route


def test_browser_journey_renders_local_shell_and_declared_routes() -> None:
    page = _BrowserPage()
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    initialise_page(page, state)
    for route in ("/", "/research", "/training", "/operations", "/diagnostics"):
        navigate_to(page, state, route)

    assert page.views
    assert page.route == "/diagnostics"
    assert page.go_calls == ["/", "/research", "/training", "/operations", "/diagnostics"]
    assert page.update_count >= 1


def test_browser_startup_is_loopback_only_and_actions_cannot_grant_execution(
    monkeypatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(flet_app, "_is_port_listening", lambda _host, _port: True)
    monkeypatch.setattr(flet_app, "_local_http_ready", lambda _url: True)
    monkeypatch.setattr(flet_app.webbrowser, "open", lambda url: opened.append(url) or True)

    assert flet_app._reuse_existing_web_server(8550, open_browser=True)
    smoke_app.verify_ui_action_inventory()

    assert opened == ["http://127.0.0.1:8550/"]
    assert all("127.0.0.1" in url for url in opened)
