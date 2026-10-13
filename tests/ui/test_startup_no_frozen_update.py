from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import flet as ft

from etf_cockpit.app import flet_app, router
from etf_cockpit.app.components.kit.surfaces import _rim_overlay
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.application import scoreboard_publication, snapshot_builder


class _Page:
    def __init__(self) -> None:
        self.route = "/"
        self.views: list[ft.View] = []
        self._render_generation = 7
        self.updated = threading.Event()

    def update(self, *_args: object) -> None:
        self.updated.set()


def _walk(control: object):
    if isinstance(control, ft.Control):
        yield control
        content = getattr(control, "content", None)
        if isinstance(content, ft.Control):
            yield from _walk(content)
        for child in getattr(control, "controls", ()) or ():
            yield from _walk(child)


def test_post_paint_refresh_rebuilds_instead_of_touching_frozen_controls(monkeypatch) -> None:
    old_callback_called = threading.Event()
    stale = ft.Container()
    stale.data = {router._DEFERRED_UPDATE_KEY: lambda: old_callback_called.set()}
    stale._frozen = True
    page = _Page()
    state = SimpleNamespace()
    fresh_targets: list[ft.Container] = []

    def build_page(_page, _state, _route):
        target = ft.Container()
        target.data = {
            router._DEFERRED_UPDATE_KEY: lambda: setattr(target, "content", ft.Text("Home ready"))
        }
        fresh_targets.append(target)
        return PageView(PageChrome("Home", "ready"), target)

    def build_shell(_page, _state, route, *, built, show_toast=True):
        return ft.View(route=route, controls=[ft.Container(content=built.body)])

    monkeypatch.setattr(router, "build_page", build_page)
    monkeypatch.setattr(router, "build_shell", build_shell)
    router._schedule_deferred_updates(page, ft.View(route="/", controls=[stale]), 7, state, "/")

    assert page.updated.wait(5)
    assert not old_callback_called.is_set()
    assert len(fresh_targets) == 1
    assert fresh_targets[0].content.value == "Home ready"
    assert any(
        getattr(control, "value", None) == "Home ready"
        for control in _walk(page.views[0])
    )


def test_kit_redraw_is_a_noop_for_frozen_or_unmounted_canvas() -> None:
    frozen = _rim_overlay(12).content  # canvas sits inside a pointer-transparent wrapper
    before = list(frozen.shapes)
    frozen._frozen = True
    frozen.on_resize(SimpleNamespace(width=120, height=80))
    assert frozen.shapes == before

    unmounted = _rim_overlay(12).content
    before = list(unmounted.shapes)
    unmounted.on_resize(SimpleNamespace(width=120, height=80))
    assert unmounted.shapes == before


def test_concurrent_startup_refresh_writers_share_the_features_write_lock(monkeypatch) -> None:
    active = 0
    max_active = 0
    calls: list[str] = []
    overlap = threading.Event()
    guard = threading.Lock()

    def enter(name: str) -> None:
        nonlocal active, max_active
        with guard:
            if active:
                overlap.set()
                raise TimeoutError("simulated features atomic-write-group guard timeout")
            active += 1
            max_active = max(max_active, active)
            calls.append(name)
        try:
            time.sleep(0.05)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(scoreboard_publication, "refresh_static_trust_artifacts", lambda _config: enter("trust"))
    monkeypatch.setattr(snapshot_builder, "_build_snapshot", lambda **_kwargs: enter("snapshot"))
    state = SimpleNamespace(snapshot=SimpleNamespace(config=object()))
    start = threading.Barrier(3)
    errors: list[BaseException] = []

    def run(callback) -> None:
        try:
            start.wait(5)
            callback()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(lambda: flet_app._refresh_static_trust_artifacts(state),)),
        threading.Thread(target=run, args=(snapshot_builder.build_snapshot,)),
    ]
    for thread in threads:
        thread.start()
    start.wait(5)
    for thread in threads:
        thread.join(5)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert not overlap.is_set()
    assert max_active == 1
    assert set(calls) == {"trust", "snapshot"}
