from __future__ import annotations

import os
import socket
import sys
import traceback
import urllib.request
import webbrowser
from itertools import count
from datetime import datetime
from pathlib import Path

from etf_cockpit.core.runtime import configure_runtime_environment

_RUNTIME_TEMP = configure_runtime_environment()

import flet as ft  # noqa: E402

from etf_cockpit.app.router import render_shell  # noqa: E402
from etf_cockpit.app.state import AppState  # noqa: E402
from etf_cockpit.app.theme import BG  # noqa: E402
from etf_cockpit.core.session_log import init_session_log, log_event  # noqa: E402


_STDIO_HANDLES = []
_FLET_STATIC_TEMP_COUNTER = count()


def _resolve_flet_app():
    """Return Flet's callable app entry point in source and frozen runtimes."""
    app = getattr(ft, "app", None)
    if callable(app):
        return app
    from flet.app import app as frozen_app

    return frozen_app


class _FletStaticTempfile:
    @staticmethod
    def mkdtemp(*_args: object, **_kwargs: object) -> str:
        base = _RUNTIME_TEMP / "flet_web_static"
        path = base / f"static_{os.getpid()}_{next(_FLET_STATIC_TEMP_COUNTER)}"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)


def _log_dir() -> Path:
    return Path.cwd() / "logs"


def _startup_log(message: str) -> None:
    try:
        path = _log_dir() / "startup.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except Exception:
        pass


def _patch_flet_static_temp_dir() -> None:
    try:
        import flet_web.fastapi.flet_static_files as static_files

        static_files.tempfile = _FletStaticTempfile
        _startup_log(f"patched Flet static temp dir under {_RUNTIME_TEMP}")
    except Exception:
        _startup_log("could not patch Flet static temp dir\n" + traceback.format_exc())


def _attach_windowed_stdio() -> None:
    if not getattr(sys, "frozen", False):
        return
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        stdout_handle = (log_dir / "stdout.log").open("a", encoding="utf-8")
        sys.stdout = stdout_handle
        _STDIO_HANDLES.append(stdout_handle)
    if sys.stderr is None:
        stderr_handle = (log_dir / "stderr.log").open("a", encoding="utf-8")
        sys.stderr = stderr_handle
        _STDIO_HANDLES.append(stderr_handle)


def _render_route(page: ft.Page, state: AppState, route: str) -> None:
    render_shell(page, state, route)


def initialise_page(page: ft.Page, state: AppState | None = None) -> AppState:
    state = state or AppState.load()
    page.title = "ETF AI Evidence Cockpit"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    try:
        page.window.width = state.snapshot.config.ui.window_width
        page.window.height = state.snapshot.config.ui.window_height
        page.window.min_width = state.snapshot.config.ui.window_min_width
        page.window.min_height = state.snapshot.config.ui.window_min_height
    except Exception:
        page.window_width = state.snapshot.config.ui.window_width
        page.window_height = state.snapshot.config.ui.window_height
        page.window_min_width = state.snapshot.config.ui.window_min_width
        page.window_min_height = state.snapshot.config.ui.window_min_height

    def route_change(_event: ft.RouteChangeEvent) -> None:
        log_event(
            event_type="navigation",
            severity="info",
            route=page.route or state.snapshot.config.ui.default_page,
            component="router",
            operation="route_change",
            status="render",
        )
        _render_route(page, state, page.route or state.snapshot.config.ui.default_page)

    page.on_route_change = route_change
    initial_route = page.route or state.snapshot.config.ui.default_page
    _render_route(page, state, initial_route)
    return state


def main(page: ft.Page) -> None:
    initialise_page(page)


def _is_port_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _local_http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return 200 <= int(response.status) < 400
    except Exception:
        return False


def _reuse_existing_web_server(port: int, open_browser: bool) -> bool:
    url = f"http://127.0.0.1:{port}/"
    if not _is_port_listening("127.0.0.1", port):
        return False
    if _local_http_ready(url):
        _startup_log(f"existing local web server detected on {url}; reusing it")
        if open_browser:
            webbrowser.open(url)
        return True
    _startup_log(f"port {port} is already in use, but {url} did not return HTTP readiness; not starting duplicate server")
    return False


def _fallback_port_if_busy(port: int) -> int:
    if not _is_port_listening("127.0.0.1", port):
        return port
    for candidate in range(port + 1, 65536):
        if not _is_port_listening("127.0.0.1", candidate):
            _startup_log(f"port {port} is busy but not reusable; falling back to {candidate}")
            return candidate
    raise RuntimeError("No free local TCP port was found for the Flet web server.")


def _normalise_port(value: str) -> int:
    try:
        port = int(value)
    except Exception as exc:
        raise ValueError(f"ETF_COCKPIT_PORT must be an integer between 1024 and 65535, got {value!r}.") from exc
    if port < 1024 or port > 65535:
        raise ValueError(f"ETF_COCKPIT_PORT must be between 1024 and 65535, got {port}.")
    return port


def run() -> None:
    _patch_flet_static_temp_dir()
    view_setting = os.getenv("ETF_COCKPIT_VIEW", "web").strip().lower()
    port = _normalise_port(os.getenv("ETF_COCKPIT_PORT", "8550"))
    open_browser = os.getenv("ETF_COCKPIT_OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no"}
    _startup_log(
        "run entered "
        f"frozen={getattr(sys, 'frozen', False)} "
        f"cwd={Path.cwd()} "
        f"ETF_COCKPIT_VIEW={view_setting} "
        f"ETF_COCKPIT_PORT={port} "
        f"ETF_COCKPIT_OPEN_BROWSER={open_browser} "
        f"FLET_PLATFORM={os.getenv('FLET_PLATFORM')} "
        f"FLET_FORCE_WEB_SERVER={os.getenv('FLET_FORCE_WEB_SERVER')}"
    )
    if view_setting in {"desktop", "flet_app"}:
        view = ft.AppView.FLET_APP
        _startup_log("starting flet desktop view")
    else:
        _attach_windowed_stdio()
        if _reuse_existing_web_server(port, open_browser):
            return
        port = _fallback_port_if_busy(port)
        os.environ["ETF_COCKPIT_PORT"] = str(port)
        init_session_log(clear=True, build_mode="web", port=port, route="/")
        view = ft.AppView.WEB_BROWSER
        embedded_platform = os.environ.pop("FLET_PLATFORM", None)
        if open_browser:
            os.environ.pop("FLET_FORCE_WEB_SERVER", None)
        else:
            os.environ["FLET_FORCE_WEB_SERVER"] = "true"
        _startup_log(
            "starting flet web view "
            f"url=http://127.0.0.1:{port}/ "
            f"open_browser={open_browser} "
            f"cleared_FLET_PLATFORM={embedded_platform} "
            f"FLET_FORCE_WEB_SERVER={os.getenv('FLET_FORCE_WEB_SERVER')}"
        )
    try:
        if view_setting in {"desktop", "flet_app"}:
            init_session_log(clear=True, build_mode="desktop", port=port, route="/")
        _resolve_flet_app()(target=main, view=view, host="127.0.0.1", port=port)
    except Exception:
        _startup_log("ft.app failed\n" + traceback.format_exc())
        raise
