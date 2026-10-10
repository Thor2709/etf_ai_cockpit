"""Bug-hunt batch T-UIA: one focused test per fixed bug id."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest


def _walk(control):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for attr in ("content", "body", "control"):
        child = getattr(control, attr, None)
        if child is not None and not isinstance(child, (str, int, float)):
            yield from _walk(child)


@pytest.fixture(scope="module")
def shared_snapshot():
    from etf_cockpit.application.snapshot_builder import build_snapshot

    return build_snapshot()


@pytest.fixture
def snapshot_state(shared_snapshot):
    from etf_cockpit.app.state import AppState

    return AppState(snapshot=shared_snapshot, selected_etf=shared_snapshot.config.ui.default_etf)


# ---------------------------------------------------------------- operations / docs
def test_chat_p05_n002_paper_fill_ui_sends_unique_fill_id(monkeypatch, snapshot_state, tmp_path) -> None:
    from etf_cockpit.app.pages.operations import operations_page

    requests: list = []
    snapshot_state.application_api = type(snapshot_state.application_api)(lambda: snapshot_state.snapshot, root=tmp_path)
    monkeypatch.setattr(snapshot_state.application_api, "fill_paper_order", lambda request: requests.append(request) or "ok", raising=False)
    rendered = operations_page(None, snapshot_state)
    rendered.chrome.segment_groups[0].on_change("Paper ledger")
    controls = {getattr(item, "key", None): item for item in _walk(rendered)}
    for item in list(controls.values()):
        data = getattr(item, "data", None)
        if isinstance(data, dict) and isinstance(data.get("input"), ft.TextField):
            controls[data["input"].key] = data["input"]
    controls["operations.paper-order-id"].value = "O1"
    controls["operations.paper-fill-quantity"].value = "2"
    controls["operations.paper-fill-price"].value = "10"
    controls["operations.paper-fill"].on_click(None)
    controls["operations.paper-fill"].on_click(None)  # a second real, identical fill
    assert len(requests) == 2
    assert requests[0].fill_id and requests[0].fill_id.startswith("ui-")
    assert requests[0].fill_id != requests[1].fill_id


def test_p05_n003_rebalance_help_states_proceeds_assumption() -> None:
    from etf_cockpit.app.pages import portfolio

    text = open(portfolio.__file__, encoding="utf-8").read()
    assert "Sale proceeds are assumed available; set a settlement buffer for T+2." in text


# ---------------------------------------------------------------- app state
def test_p06_n001_universe_change_stays_in_its_session(monkeypatch, shared_snapshot) -> None:
    import etf_cockpit.app.state as state_module

    monkeypatch.setattr(state_module, "_shared_snapshot", lambda: shared_snapshot)
    monkeypatch.setattr(state_module, "run_startup_migrations", lambda: None)
    session_a, session_b = state_module.AppState.load(), state_module.AppState.load()
    assert session_a.snapshot is not session_b.snapshot
    original_config = shared_snapshot.config
    revision_before = shared_snapshot.universe_revision
    only = list(original_config.universe.enabled_ids)[:1]
    session_a.apply_universe_config(SimpleNamespace(universe=SimpleNamespace(enabled_ids=only)), "rev-a")
    assert session_a.snapshot.universe_revision == "rev-a"
    assert session_b.snapshot.config is original_config
    assert session_b.snapshot.universe_revision == revision_before
    assert shared_snapshot.config is original_config


def test_p06_n009_message_serial_counts_repeats_and_toast_dedups_on_it(monkeypatch, snapshot_state) -> None:
    from etf_cockpit.app import router

    state = snapshot_state
    before = state.message_serial
    state.last_message = "Provider failed"
    state.last_message = "Provider failed"
    assert state.message_serial == before + 2

    shown: list[str] = []
    monkeypatch.setattr(router.Toast, "show", lambda self, text, **kwargs: shown.append(text))
    page = SimpleNamespace(width=1600, height=1000, route="/")
    state.last_message = "Provider failed"
    router.build_shell(page, state, "/")
    router.build_shell(page, state, "/")  # re-render, same event: no new toast
    assert shown == ["Provider failed"]
    state.last_message = "Provider failed"  # same text, new event
    router.build_shell(page, state, "/")
    assert shown == ["Provider failed", "Provider failed"]


# ---------------------------------------------------------------- router
def test_p06_n002_body_scroll_flip_triggers_relayout(snapshot_state) -> None:
    from etf_cockpit.app import router

    assert router._body_scrolls(950, False) is True
    assert router._body_scrolls(970, False) is False
    page = SimpleNamespace(width=1920, height=950, route="/")
    view = router.build_shell(page, snapshot_state, "/")
    page.height = 970
    assert view.data["relayout"]() is True


def test_p06_n003_topbar_menu_follows_resize() -> None:
    from etf_cockpit.app.components.shell import topbar
    from etf_cockpit.app.components.shell.page_view import PageChrome, SegmentGroup

    shown: list[float] = []
    overlay = SimpleNamespace(show=lambda kind, panel, left, top, **kw: shown.append(left), hide=lambda **kw: None)
    search = SimpleNamespace(box=ft.Container(), set_compact=lambda value: None)
    width = {"value": 1800.0}
    chrome = PageChrome("T", "S", [SegmentGroup("g", ["a", "b"], "a", None)])
    bar = topbar.build_topbar(
        chrome, has_menu=False, on_open_menu=lambda: None, search=search, overlay=overlay,
        badge_count=None, on_what_changed=None, width=lambda: width["value"],
    )
    pill = next(c for c in _walk(bar.control) if getattr(c, "key", None) == "shell.view-menu")
    width["value"] = 900.0
    pill.on_click(None)
    assert shown == [24 + 84 + 24 + 900 - 48 - 320]


def test_p06_n012_chrome_refresh_uses_current_width() -> None:
    from etf_cockpit.app.components.shell import topbar
    from etf_cockpit.app.components.shell.page_view import PageChrome

    search = SimpleNamespace(box=ft.Container(), set_compact=lambda value: None)
    overlay = SimpleNamespace(show=lambda *a, **k: None, hide=lambda **k: None)
    width = {"value": 900.0}
    bar = topbar.build_topbar(
        PageChrome("T", "S", []), has_menu=False, on_open_menu=lambda: None, search=search, overlay=overlay,
        badge_count=None, on_what_changed=None, width=lambda: width["value"],
    )
    title = next(c for c in _walk(bar.control) if getattr(c, "key", None) == "shell.title-block")
    assert title.width == topbar.TITLE_WIDTH_TIGHT  # built compact because the getter, not a stale value, is read


def test_p06_n004_failed_section_filler_shows_notice_and_logs(monkeypatch) -> None:
    from etf_cockpit.app import router

    logged: list[dict] = []
    monkeypatch.setattr(router, "log_event", lambda **kwargs: logged.append(kwargs))

    def broken():
        raise ValueError("boom")

    target = ft.Container(content=ft.Text("Preparing…"))
    target.data = {router._DEFERRED_UPDATE_KEY: broken}
    page = SimpleNamespace(route="/dashboard")
    router._resolve_deferred_controls(page, target, "/dashboard")
    assert "ValueError" in target.content.value and "could not load" in target.content.value
    assert logged and logged[0]["severity"] == "error" and "boom" in logged[0]["message"]


def test_p06_n005_page_update_swap_is_serialised() -> None:
    from etf_cockpit.app import router

    def original(*args, **kwargs):
        return "real"

    page = SimpleNamespace(update=original)
    inside, started, release = threading.Event(), threading.Event(), threading.Event()

    def first():
        with router._deferred_page_update(page):
            inside.set()
            release.wait(5)

    def second():
        started.set()
        with router._deferred_page_update(page):
            pass

    a = threading.Thread(target=first)
    b = threading.Thread(target=second)
    a.start()
    assert inside.wait(5)
    b.start()
    assert started.wait(5)
    time.sleep(0.1)  # B is now waiting for A's block to finish
    release.set()
    a.join(5)
    b.join(5)
    assert page.__dict__["update"] is original


def test_p06_n006_route_parts_strip_query_and_hash() -> None:
    from etf_cockpit.app.router import _route_parts

    assert _route_parts("/instrument/ABC?view=x") == ("/instrument", "ABC")
    assert _route_parts("/instrument/ABC#top") == ("/instrument", "ABC")
    assert _route_parts("/data-health?x=1") == ("/data-health", None)


# ---------------------------------------------------------------- workspaces
def test_p06_n007_colliding_workspace_names_get_two_files(tmp_path) -> None:
    from etf_cockpit.app.workspaces import load_workspace, save_workspace

    one = save_workspace("A/B", {"v": 1}, directory=tmp_path)
    two = save_workspace("A?B", {"v": 2}, directory=tmp_path)
    plain = save_workspace("Plain_name-1", {"v": 3}, directory=tmp_path)
    assert one != two and one.exists() and two.exists()
    assert plain.name == "Plain_name-1.json"
    assert load_workspace("A/B", directory=tmp_path)["v"] == 1
    assert load_workspace("A?B", directory=tmp_path)["v"] == 2


def test_p06_n010_workspace_never_carries_execution_authority(tmp_path) -> None:
    from etf_cockpit.app.workspaces import load_workspace, save_workspace

    path = save_workspace("w", {"execution_allowed": True}, directory=tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["execution_allowed"] is False
    path.write_text(json.dumps({"execution_allowed": True, "schema_version": "1.0"}), encoding="utf-8")
    assert load_workspace("w", directory=tmp_path)["execution_allowed"] is False


# ---------------------------------------------------------------- web server reuse
def test_p06_n008_only_own_running_instance_is_reused(monkeypatch, tmp_path) -> None:
    from etf_cockpit.app import flet_app

    record = tmp_path / "web_instance.json"
    monkeypatch.setattr(flet_app, "WEB_INSTANCE_PATH", record)
    monkeypatch.setattr(flet_app, "_is_port_listening", lambda host, port: True)
    monkeypatch.setattr(flet_app, "_local_http_ready", lambda url: True)
    assert flet_app._reuse_existing_web_server(8550, False) is False  # foreign server, no record
    record.write_text(json.dumps({"port": 8550, "pid": os.getpid()}), encoding="utf-8")
    assert flet_app._reuse_existing_web_server(8550, False) is True
    record.write_text(json.dumps({"port": 8551, "pid": os.getpid()}), encoding="utf-8")
    assert flet_app._reuse_existing_web_server(8550, False) is False
    monkeypatch.setattr(flet_app, "pid_is_alive", lambda pid: False)
    record.write_text(json.dumps({"port": 8550, "pid": 1}), encoding="utf-8")
    assert flet_app._reuse_existing_web_server(8550, False) is False


# ---------------------------------------------------------------- topbar / search
def test_p06_n016_glossary_failure_is_not_cached(monkeypatch) -> None:
    import etf_cockpit.application.scope_facade as facade
    from etf_cockpit.app.components.shell import search

    calls = {"n": 0}

    def load_glossary():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return SimpleNamespace(policy=SimpleNamespace(entries=[SimpleNamespace(term="Drawdown")]), diagnostic_mode=False)

    monkeypatch.setattr(facade, "load_glossary", load_glossary)
    monkeypatch.setattr(search, "_GLOSSARY", None)
    assert search._glossary_terms() == []
    assert search._glossary_terms() == ["Drawdown"]


def test_p06_n017_choose_rebuilds_once(monkeypatch) -> None:
    from etf_cockpit.app.components.shell import topbar
    from etf_cockpit.app.components.shell.page_view import SegmentGroup

    built: list[object] = []
    captured: dict[str, object] = {}

    def fake_segmented(items, selected, *, on_change=None, key=None):
        built.append(selected)
        captured["on_change"] = on_change
        return ft.Container()

    class FakeOverlay:
        def __init__(self) -> None:
            self.on_hide = None
            self.panel = None

        def show(self, kind, panel, left, top, on_hide=None):
            self.panel, self.on_hide = panel, on_hide

        def hide(self, **kwargs):
            callback, self.on_hide = self.on_hide, None
            if callback is not None:
                callback()

    monkeypatch.setattr(topbar, "Segmented", fake_segmented)
    overlay = FakeOverlay()
    chosen: list[str] = []
    items = [f"v{i}" for i in range(8)]
    host = ft.Row([ft.Container()])
    host.controls[0] = topbar._group_control(SegmentGroup("k", items, "v0", chosen.append), overlay, host, 0, lambda: 100.0, 112)
    assert len(built) == 1
    captured["on_change"](topbar.MORE)
    row = next(c for c in _walk(overlay.panel) if getattr(c, "height", None) == 40 and callable(getattr(c, "on_click", None)))
    row.on_click(None)
    assert len(built) == 2  # exactly one rebuild for one selection
    assert len(chosen) == 1


# ---------------------------------------------------------------- charts
def test_p06_n013_no_line_segment_across_a_gap(monkeypatch) -> None:
    from etf_cockpit.app.components.chartkit import bars

    drawn: list[tuple] = []
    real_line = bars.line
    monkeypatch.setattr(bars, "line", lambda *a, **k: drawn.append(a) or real_line(*a, **k))
    bars.grouped_bar_chart(
        ["A", "B", "C"], [bars.BarSeries("bars", [1, 2, 3])],
        line_series=bars.LineSeries("rate", [12, None, 7]),
    )
    assert drawn == []
    drawn.clear()
    bars.grouped_bar_chart(
        ["A", "B", "C"], [bars.BarSeries("bars", [1, 2, 3])],
        line_series=bars.LineSeries("rate", [12, 9, 7]),
    )
    assert len(drawn) == 2


def test_p06_n014_negative_bar_is_visible(monkeypatch) -> None:
    from etf_cockpit.app.components.chartkit import bars

    rects: list[tuple] = []
    real_rect = bars.bar_rect
    monkeypatch.setattr(bars, "bar_rect", lambda *a, **k: rects.append(a) or real_rect(*a, **k))
    bars.grouped_bar_chart(["A"], [bars.BarSeries("loss", [-5])], height=300)
    assert len(rects) == 1
    _x, y_top, _w, height = rects[0][:4]
    assert height > 10 and y_top > 20  # drawn downward from the zero baseline inside the plot


def test_p06_n015_today_outside_data_is_not_drawn(monkeypatch) -> None:
    from etf_cockpit.app.components.chartkit import lines

    marks: list[float] = []
    monkeypatch.setattr(lines, "draw_today", lambda sc, plot, tx: marks.append(tx))
    days = [date(2026, 1, 1), date(2026, 1, 11), date(2026, 1, 21)]
    series = [lines.Series("s", [1.0, 2.0, 3.0])]
    lines.line_chart(days, series, today=date(2026, 3, 1))
    assert marks == []
    lines.line_chart(days, series, today=date(2026, 1, 11))
    assert len(marks) == 1
    chart = lines.line_chart(days, series)
    plot_mid = marks[0]
    assert 0 < plot_mid < 600 and chart is not None
