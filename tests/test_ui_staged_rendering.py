"""Cold start paints the shell at once; slow pages build off the event thread behind a skeleton."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import flet_app, router
from etf_cockpit.app import state as state_module
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot

WAIT = 30  # seconds; Event.wait returns as soon as the event is set, this is only a failure bound


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


class FakePage:
    def __init__(self, route: str = "/") -> None:
        self.route = route
        self.views: list[ft.View] = []
        self.window = SimpleNamespace()
        self.width = 1920
        self.height = 1200
        self.updates: list[str | None] = []
        self.go_calls: list[str] = []
        self.changed = threading.Event()
        self.went = threading.Event()
        self.failed = threading.Event()

    def update(self, *_args: object) -> None:
        self.updates.append(self.views[0].controls[0].key if self.views else None)
        if self.views and any("could not be loaded" in text for text in _texts(self.views[0])):
            self.failed.set()
        self.changed.set()

    def go(self, route: str) -> None:
        self.go_calls.append(route)
        self.route = route
        self.went.set()


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        if isinstance(child, ft.Control):
            yield from _walk(child)


def _has_key(view: ft.View, key: str) -> bool:
    return any(getattr(control, "key", None) == key for control in _walk(view))


def _texts(view: ft.View) -> list[str]:
    return [str(item.value) for item in _walk(view) if isinstance(item, ft.Text)]


def test_cold_start_paints_the_loading_shell_before_the_snapshot_is_loaded(snapshot, monkeypatch) -> None:
    release = threading.Event()
    loaded = _state(snapshot)

    def slow_load(cls):
        assert release.wait(WAIT)
        return loaded

    monkeypatch.setattr(AppState, "load", classmethod(slow_load))
    page = FakePage()
    assert flet_app.initialise_page(page) is None  # state does not exist yet
    # Painted synchronously: dock + top bar + skeleton, while the loader is still blocked.
    assert page.views and page.views[0].controls[0].key == "shell.loading"
    assert _has_key(page.views[0], "shell.dock") and _has_key(page.views[0], "shell.skeleton")
    assert not hasattr(page, "on_route_change")  # handlers are wired only once the state exists
    page.changed.clear()
    release.set()
    assert page.changed.wait(WAIT)
    assert page.views[0].controls[0].key == "shell.backdrop"  # the real shell replaced the skeleton
    assert callable(page.on_route_change) and callable(page.on_resize)


def test_loading_shell_needs_no_heavy_modules() -> None:
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys; sys.path.insert(0, 'src');"
        "import etf_cockpit.app.flet_app as f; f.build_loading_view('/');"
        "heavy = [m for m in ('pandas', 'numpy', 'scipy', 'etf_cockpit.app.router', 'etf_cockpit.app.state') if m in sys.modules];"
        "print(heavy)"
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=120)
    assert result.stdout.strip().endswith("[]"), result.stdout + result.stderr


def test_dock_click_while_loading_is_applied_after_the_load(snapshot, monkeypatch) -> None:
    release = threading.Event()
    loaded = _state(snapshot)
    monkeypatch.setattr(AppState, "load", classmethod(lambda cls: (release.wait(WAIT), loaded)[1]))
    page = FakePage()
    flet_app.initialise_page(page)
    target = next(c for c in _walk(page.views[0]) if getattr(c, "key", None) == "nav.workspace.Universe")
    target.on_click(None)
    release.set()
    assert page.went.wait(WAIT)
    assert page.go_calls == ["/universe"]  # requested once through page.go; its handler renders the route


def test_failed_load_shows_an_explicit_unavailable_message_not_a_blank_window(monkeypatch) -> None:
    def broken(cls):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(AppState, "load", classmethod(broken))
    page = FakePage()
    flet_app.initialise_page(page)
    assert page.failed.wait(WAIT)
    assert any("could not be loaded" in text for text in _texts(page.views[0]))
    assert page.views[0].controls[0].key == "shell.loading"


def _slow_route(monkeypatch, release: threading.Event, started: threading.Event | None = None) -> str:
    def slow_page(_page, _state):
        if started is not None:
            started.set()
        assert release.wait(WAIT)
        return PageView(PageChrome("Slow page", "built"), ft.Text("slow page body", key="slow.body"))

    monkeypatch.setitem(router.PAGES, "/slow-test", ("Slow page", slow_page))
    return "/slow-test"


def test_slow_page_shows_a_skeleton_then_the_real_page(snapshot, monkeypatch) -> None:
    release = threading.Event()
    route = _slow_route(monkeypatch, release)
    page, state, done = FakePage(), _state(snapshot), threading.Event()
    router.render_route_change(page, state, route, background=True, patience_s=0.01, on_done=done.set)
    # Returned without waiting for the page: the shell is already painted with a skeleton body.
    assert page.views and _has_key(page.views[0], "shell.skeleton") and _has_key(page.views[0], "shell.dock")
    assert not _has_key(page.views[0], "slow.body")
    release.set()
    assert done.wait(WAIT)
    assert _has_key(page.views[0], "slow.body") and not _has_key(page.views[0], "shell.skeleton")
    assert "Slow page" in _texts(page.views[0])


def test_fast_page_is_painted_once_without_a_skeleton_frame(snapshot) -> None:
    page, state, done = FakePage(), _state(snapshot), threading.Event()
    router.render_route_change(page, state, "/decision-journal", background=True, patience_s=30, on_done=done.set)
    assert done.wait(WAIT)
    assert len(page.updates) == 1 and not _has_key(page.views[0], "shell.skeleton")
    reference = FakePage()
    router.render_shell(reference, state, "/decision-journal")
    assert _texts(page.views[0]) == _texts(reference.views[0])  # same output as the synchronous path


def test_a_newer_render_supersedes_an_unfinished_background_build(snapshot, monkeypatch) -> None:
    release, started = threading.Event(), threading.Event()
    route = _slow_route(monkeypatch, release, started)
    page, state = FakePage(), _state(snapshot)
    router.render_route_change(page, state, route, background=True, patience_s=0.01)
    assert started.wait(WAIT)
    router.render_shell(page, state, "/decision-journal")  # the user moved on
    final_before = _texts(page.views[0])
    release.set()
    for thread in threading.enumerate():
        if thread.name == f"page-build:{route}":
            thread.join(WAIT)
    assert _texts(page.views[0]) == final_before  # the stale slow page did not repaint
    assert not _has_key(page.views[0], "slow.body")


def test_plain_pages_render_synchronously_like_before(snapshot) -> None:
    page, state = FakePage(), _state(snapshot)
    router.render_route_change(page, state, "/decision-journal")  # FakePage is not an ft.Page
    assert page.views and page.views[0].route == "/decision-journal"
    assert len(page.updates) == 1


def test_updates_from_other_threads_are_not_swallowed_while_a_page_builds(snapshot, monkeypatch) -> None:
    release, started = threading.Event(), threading.Event()
    page, state = FakePage(), _state(snapshot)

    def slow_page(build_page, _state):
        build_page.update()  # called by the building thread: deferred
        started.set()
        assert release.wait(WAIT)
        return ft.Text("body")

    monkeypatch.setitem(router.PAGES, "/slow-test", ("Slow page", slow_page))
    worker = threading.Thread(target=router.build_page, args=(page, state, "/slow-test"))
    worker.start()
    assert started.wait(WAIT)
    page.update()  # the UI thread's own update goes through
    assert len(page.updates) == 1  # the UI thread's call; the builder's own call was deferred
    release.set()
    worker.join(WAIT)
    assert len(page.updates) == 1
    assert "update" not in page.__dict__  # the patch is removed after the build


def test_pages_without_an_update_method_still_build_without_a_route_failure(snapshot) -> None:
    page = SimpleNamespace(width=1920, height=1200, route="/")  # embedded/test pages have no update()
    built = router.build_page(page, _state(snapshot), "/decision-journal")
    assert getattr(built, "key", None) != "router.route-error"
    assert not hasattr(page, "update")
