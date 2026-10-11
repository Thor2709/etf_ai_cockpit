from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app import router
from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control: ft.Control):
    yield control
    for child in getattr(control, "controls", ()) or ():
        if isinstance(child, ft.Control):
            yield from _walk(child)
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)


def _fingerprint(control: ft.Control) -> tuple[tuple[object, ...], ...]:
    fingerprint = []
    for item in _walk(control):
        def read(name: str) -> object:
            try:
                return getattr(item, name)
            except Exception:
                return None

        children = read("controls")
        content = read("content")
        fingerprint.append(
            (
                id(item),
                read("value"),
                read("visible"),
                read("disabled"),
                read("text"),
                id(content) if content is not None else None,
                tuple(id(child) for child in children or ()),
            )
        )
    return tuple(fingerprint)


def test_every_page_segment_updates_in_place_without_mutating_pageview() -> None:
    snapshot = build_snapshot()
    failures: list[str] = []
    changed = 0
    required_segment_routes = {"/", "/etf", "/instrument", "/portfolio", "/signals"}

    for route in router.PAGES:
        page = SimpleNamespace(width=1920, height=1200, route=route, update=lambda: None)
        state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
        built = router.build_page(page, state, route)
        if route in required_segment_routes and not isinstance(built, PageView):
            failures.append(f"{route}:not a PageView")
            continue
        if not isinstance(built, PageView):
            continue
        if route in required_segment_routes and not built.chrome.segment_groups:
            failures.append(f"{route}:missing segment groups")
            continue
        if not built.chrome.segment_groups:
            continue

        view = router.build_shell(page, state, route, built=built)
        shell_root = view.controls[0]
        original_body = built.body

        for group in built.chrome.segment_groups:
            if group.on_change is None:
                continue
            key = f"shell.view.{group.key}"
            track = next((control for control in _walk(view) if getattr(control, "key", None) == key), None)
            if track is None:
                failures.append(f"{route}:{group.key}:missing segment control")
                continue
            data = getattr(track, "data", None)
            if not isinstance(data, dict) or data.get("kit") != "Segmented":
                failures.append(f"{route}:{group.key}:missing selected state")
                continue
            selected = data["state"]["selected"]
            candidates = [item for item in data["items"] if item in group.items]
            next_value = next((item for item in candidates if item != selected), None)
            if next_value is None:
                continue
            body_before = _fingerprint(original_body)
            segment = next(
                (
                    control
                    for control in _walk(track)
                    if isinstance(getattr(control, "data", None), dict)
                    and control.data.get("kit") == "Segment"
                    and control.data.get("value") == next_value
                ),
                None,
            )
            if segment is None:
                failures.append(f"{route}:{group.key}:missing option {next_value}")
                continue

            try:
                segment.on_click(None)
            except Exception as exc:  # the frozen PageView crash must be reported with its route
                failures.append(f"{route}:{group.key}:{type(exc).__name__}")
                continue

            changed += 1
            assert track.data["state"]["selected"] == next_value
            assert view.controls[0] is shell_root
            assert built.body is original_body
            if route in required_segment_routes:
                assert _fingerprint(original_body) != body_before, f"{route}:{group.key}:affected body did not change"

    assert changed > 0
    assert not failures, "; ".join(failures)
