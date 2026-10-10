from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import traceback
import urllib.request
import uuid
import webbrowser
from itertools import count
from datetime import datetime
from pathlib import Path

from etf_cockpit.application.runtime import atomic_write_json, pid_is_alive
from etf_cockpit.core.paths import WEB_INSTANCE_PATH
from etf_cockpit.core.runtime import configure_runtime_environment

_RUNTIME_TEMP = configure_runtime_environment()

import flet as ft  # noqa: E402

from etf_cockpit.app import theme  # noqa: E402
from etf_cockpit.app.components.shell.loading import build_loading_view  # noqa: E402
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


def _refresh_static_trust_artifacts(state: AppState) -> None:
    try:
        from etf_cockpit.application.scoreboard_publication import refresh_static_trust_artifacts
        from etf_cockpit.application.snapshot_builder import _STARTUP_WRITE_LOCK

        with _STARTUP_WRITE_LOCK:
            refresh_static_trust_artifacts(state.snapshot.config)
    except Exception:
        pass


def _configure_page_chrome(page: ft.Page) -> None:
    page.title = "ETF AI Evidence Cockpit"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.fonts = theme.font_map()
    page.theme = ft.Theme(font_family=theme.FONT_FAMILY)


def initialise_page(page: ft.Page, state: AppState | None = None) -> AppState | None:
    """Wire the page and render the first route.

    With a ready ``state`` the first route is rendered before returning (tests, embedding). Without one the
    shell with a skeleton body is painted at once, and the heavy modules plus the snapshot load on a
    background thread, after which the real first route replaces the skeleton; ``None`` is returned because
    the state does not exist yet.
    """

    _configure_page_chrome(page)
    if state is None:
        _paint_loading_then_load(page)
        return None
    _attach_state(page, state)
    return state


def _paint_loading_then_load(page: ft.Page) -> None:
    pending: dict[str, str | None] = {"route": None}

    def remember(route: str) -> None:
        pending["route"] = route  # a dock click while loading is honoured once the data is ready

    loading_route = page.route or "/"
    page.views[:] = [build_loading_view(loading_route, on_select=remember)]
    page.update()

    def load() -> None:
        try:
            router_ready = threading.Event()
            router_failure: list[Exception] = []

            def prepare_router() -> None:
                try:
                    from etf_cockpit.app import router  # noqa: F401
                except Exception as exc:
                    router_failure.append(exc)
                finally:
                    router_ready.set()

            threading.Thread(target=prepare_router, name="startup-router-import", daemon=True).start()

            from etf_cockpit.app.state import AppState

            loaded = AppState.load()
            router_ready.wait()
            if router_failure:
                raise router_failure[0]
            _attach_state(page, loaded, requested_route=pending["route"])
        except Exception:
            _startup_log("background startup failed\n" + traceback.format_exc())
            message = "The local data could not be loaded. See logs/startup.log; no data was changed."
            page.views[:] = [build_loading_view(loading_route, message=message)]
            page.update()
            log_event(
                event_type="startup",
                severity="error",
                route=loading_route,
                component="startup",
                operation="load_snapshot",
                status="failed",
                message=message,
            )

    threading.Thread(target=load, name="startup-load", daemon=True).start()


def _attach_state(page: ft.Page, state: AppState, *, requested_route: str | None = None) -> None:
    from etf_cockpit.app.router import relayout_shell, render_route_change, shell_key_event

    trust_refresh_started = threading.Event()
    trust_refresh_lock = threading.Lock()

    def after_first_paint() -> None:
        with trust_refresh_lock:
            if trust_refresh_started.is_set():
                return
            trust_refresh_started.set()
        threading.Thread(
            target=_refresh_static_trust_artifacts,
            args=(state,),
            name="startup-trust-refresh",
            daemon=True,
        ).start()

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
        render_route_change(
            page,
            state,
            page.route or state.snapshot.config.ui.default_page,
            on_done=after_first_paint,
        )

    def resize(event: ft.ControlEvent) -> None:
        relayout_shell(page, state, getattr(event, "width", None))

    page.on_route_change = route_change
    page.on_keyboard_event = lambda event: shell_key_event(page, event)
    page.on_resize = resize
    initial_route = requested_route or page.route or state.snapshot.config.ui.default_page
    if requested_route and callable(getattr(page, "go", None)) and getattr(page, "route", None) != requested_route:
        page.go(requested_route)  # the route-change handler renders it
        return
    render_route_change(page, state, initial_route, background=True, on_done=after_first_paint)


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


def _is_own_web_instance(port: int) -> bool:
    """Require a live process and its unique identity served by the recorded port."""

    try:
        record = json.loads(WEB_INSTANCE_PATH.read_text(encoding="utf-8"))
        identity = record["identity"]
        if not isinstance(identity, str) or len(identity) != 32 or any(char not in "0123456789abcdef" for char in identity):
            return False
        if int(record["port"]) != port or not pid_is_alive(int(record["pid"])):
            return False
        url = f"http://127.0.0.1:{port}/cockpit-instance-{identity}.txt"
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return response.status == 200 and response.geturl() == url and response.read(33) == identity.encode("ascii")
    except Exception:
        return False


def _prepare_web_assets() -> tuple[Path, str]:
    """Serve identity from an immutable per-instance asset directory."""
    identity = uuid.uuid4().hex
    assets_dir = _RUNTIME_TEMP / "web_assets" / identity
    shutil.copytree(theme.ASSETS_DIR, assets_dir)
    (assets_dir / f"cockpit-instance-{identity}.txt").write_text(identity, encoding="ascii")
    return assets_dir, identity


def _record_web_instance(port: int, identity: str) -> None:
    try:
        atomic_write_json(WEB_INSTANCE_PATH, {"port": port, "pid": os.getpid(), "identity": identity})
    except Exception as exc:  # the record is best-effort; without it a later start simply uses another port
        _startup_log(f"web instance record not written: {type(exc).__name__}: {exc}")


def _reuse_existing_web_server(port: int, open_browser: bool) -> bool:
    url = f"http://127.0.0.1:{port}/"
    if not _is_port_listening("127.0.0.1", port):
        return False
    if _is_own_web_instance(port) and _local_http_ready(url):
        _startup_log(f"existing local web server detected on {url}; reusing it")
        if open_browser:
            webbrowser.open(url)
        return True
    _startup_log(f"port {port} is in use by a server that is not this app's running instance; not reusing it")
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
    assets_dir = theme.ASSETS_DIR
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
        embedded_platform = os.environ.pop("FLET_PLATFORM", None)
        forced_web_server = os.environ.pop("FLET_FORCE_WEB_SERVER", None)
        _startup_log(
            "starting flet desktop view "
            f"cleared_FLET_PLATFORM={embedded_platform} "
            f"cleared_FLET_FORCE_WEB_SERVER={forced_web_server}"
        )
    else:
        _attach_windowed_stdio()
        if _reuse_existing_web_server(port, open_browser):
            return
        port = _fallback_port_if_busy(port)
        os.environ["ETF_COCKPIT_PORT"] = str(port)
        assets_dir, identity = _prepare_web_assets()
        _record_web_instance(port, identity)
        init_session_log(clear=False, build_mode="web", port=port, route="/")
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
            init_session_log(clear=False, build_mode="desktop", port=port, route="/")
        _resolve_flet_app()(target=main, view=view, host="127.0.0.1", port=port, assets_dir=str(assets_dir))
    except Exception:
        _startup_log("ft.app failed\n" + traceback.format_exc())
        raise
    finally:
        if assets_dir != theme.ASSETS_DIR:
            shutil.rmtree(assets_dir, ignore_errors=True)
