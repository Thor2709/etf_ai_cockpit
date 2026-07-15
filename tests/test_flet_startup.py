from __future__ import annotations

import time
from types import SimpleNamespace

import flet as ft

from etf_cockpit.app import flet_app
from etf_cockpit.app import state as app_state_module
from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.flet_app import initialise_page
from etf_cockpit.app.router import navigate_to
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


class FakePage:
    def __init__(self, route: str = "/") -> None:
        self.route = route
        self.views = []
        self.window = SimpleNamespace()
        self.update_count = 0
        self.go_calls: list[str] = []

    def update(self) -> None:
        self.update_count += 1

    def go(self, route: str) -> None:
        self.go_calls.append(route)
        self.route = route


def test_initialise_page_renders_default_route_without_route_change_event() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = FakePage()

    initialise_page(page, state)

    assert page.views
    assert page.views[0].route == "/"
    assert page.update_count >= 1


def test_frozen_runtime_resolves_callable_flet_app_when_namespace_is_module(monkeypatch) -> None:
    """PyInstaller can expose ``flet.app`` as its module rather than function."""
    module = object()
    monkeypatch.setattr(flet_app.ft, "app", module)

    resolved = flet_app._resolve_flet_app()

    assert callable(resolved)


def test_activity_entries_persist_to_local_run_log(tmp_path, monkeypatch) -> None:
    activity_path = tmp_path / "activity_log.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", activity_path)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    state.begin_activity("Test action", "Starting")
    state.update_activity("Running")
    entry = state.finish_activity("Test action complete", output_path=tmp_path / "out.txt")

    assert entry.status == "success"
    assert state.current_activity is None
    assert state.recent_activity[-1].message == "Test action complete"
    assert "Test action complete" in activity_path.read_text(encoding="utf-8")


def test_workflow_action_sets_visible_running_state_before_completion(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "activity_log.jsonl")
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = FakePage()

    _run_action(page, state, "Test workflow", lambda: "Workflow done.")
    deadline = time.time() + 5
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.05)

    assert page.update_count >= 2
    assert state.current_activity is None
    assert state.recent_activity[-1].label == "Test workflow"
    assert state.recent_activity[-1].status == "success"
    assert state.last_message == "Workflow done."


def test_main_forecast_workflow_disables_uncached_optional_models(monkeypatch) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    calls: list[dict[str, object]] = []

    class FakeDataService:
        def __init__(self, config) -> None:
            self.config = config

        def run_yfinance_forecasts(self, **kwargs) -> str:
            calls.append(kwargs)
            return "Configured ETF forecasts reused from cache as of 2026-07-07: baseline ok 7. Output: forecasts.csv."

    monkeypatch.setattr(app_state_module, "DataService", FakeDataService)
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False: snapshot)
    monkeypatch.setattr(state, "_write_current_scoreboard", lambda: SimpleNamespace(name="scoreboard.parquet"))

    message = state.run_forecasting_models()

    assert calls
    assert calls[0]["live_optional_models"] is False
    assert "Optional TimesFM/Toto live models" in message


def test_initialise_page_preserves_initial_non_default_route() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = FakePage("/backtests")

    initialise_page(page, state)

    assert page.views
    assert page.views[0].route == "/backtests"
    assert page.go_calls == []


def test_direct_navigation_renders_target_route() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = FakePage("/")

    navigate_to(page, state, "/signals")

    assert page.route == "/signals"
    assert page.views
    assert page.views[0].route == "/signals"
    assert page.go_calls == ["/signals"]


def test_file_picker_uses_current_async_api() -> None:
    picker = ft.FilePicker()
    assert hasattr(picker, "pick_files")


def test_flet_static_temp_dir_is_writable() -> None:
    temp_dir = flet_app._FletStaticTempfile.mkdtemp()
    index_path = f"{temp_dir}\\index.html"

    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write("ok")

    with open(index_path, encoding="utf-8") as handle:
        assert handle.read() == "ok"


def test_reuse_existing_web_server_opens_ready_local_app(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(flet_app, "_is_port_listening", lambda host, port: True)
    monkeypatch.setattr(flet_app, "_local_http_ready", lambda url: True)
    monkeypatch.setattr(flet_app.webbrowser, "open", lambda url: opened.append(url) or True)

    assert flet_app._reuse_existing_web_server(8550, open_browser=True)
    assert opened == ["http://127.0.0.1:8550/"]


def test_reuse_existing_web_server_allows_start_when_port_free(monkeypatch) -> None:
    monkeypatch.setattr(flet_app, "_is_port_listening", lambda host, port: False)

    assert not flet_app._reuse_existing_web_server(8550, open_browser=True)


def test_reuse_existing_web_server_allows_fallback_on_busy_non_http_port(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(flet_app, "_is_port_listening", lambda host, port: True)
    monkeypatch.setattr(flet_app, "_local_http_ready", lambda url: False)
    monkeypatch.setattr(flet_app.webbrowser, "open", lambda url: opened.append(url) or True)

    assert not flet_app._reuse_existing_web_server(8550, open_browser=True)
    assert opened == []


def test_fallback_port_skips_busy_port(monkeypatch) -> None:
    monkeypatch.setattr(flet_app, "_is_port_listening", lambda host, port: port == 8550)

    assert flet_app._fallback_port_if_busy(8550) == 8551
