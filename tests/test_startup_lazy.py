from __future__ import annotations

from datetime import date
import threading

import flet as ft
import pandas as pd

from etf_cockpit.app import router
from etf_cockpit.app.state import AppState
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.application import backtest_service
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.backtest.engine import BacktestReport


def _report(service: backtest_service.BacktestService, as_of_date: date | None) -> BacktestReport:
    marker = f"{service.universe_revision}:{as_of_date}"
    return BacktestReport(
        results=pd.DataFrame([{"strategy_name": "signal_strategy", "input_marker": marker}]),
        equity_curves=pd.DataFrame({"signal_strategy": [1.0]}, index=pd.DatetimeIndex(["2026-01-02"])),
        trade_log=pd.DataFrame([{"input_marker": marker}]),
        signal_log=pd.DataFrame([{"input_marker": marker}]),
        ai_added_value=False,
        quality_label="fixture",
        quality_notes=[marker],
        metadata={"input_marker": marker},
    )


def test_snapshot_defers_backtest_and_lazy_result_matches_eager_result(monkeypatch) -> None:
    calls: list[tuple[backtest_service.BacktestService, date | None, object | None]] = []

    def eager_like(service, as_of_date=None, *, publish_guard=None):
        calls.append((service, as_of_date, publish_guard))
        return _report(service, as_of_date)

    monkeypatch.setattr(backtest_service.BacktestService, "load_or_run_backtest", eager_like)
    snapshot = build_snapshot()

    assert snapshot.backtest is None
    assert calls == []
    lazy = snapshot.ensure_backtest()
    assert lazy is not None
    assert len(calls) == 1

    service, as_of_date, publish_guard = calls[0]
    eager = eager_like(service, as_of_date, publish_guard=publish_guard)
    pd.testing.assert_frame_equal(lazy.results, eager.results)
    pd.testing.assert_frame_equal(lazy.equity_curves, eager.equity_curves)
    pd.testing.assert_frame_equal(lazy.trade_log, eager.trade_log)
    pd.testing.assert_frame_equal(lazy.signal_log, eager.signal_log)
    assert lazy.metadata == eager.metadata
    assert snapshot.ensure_backtest() is lazy


class _FakePage:
    def __init__(self) -> None:
        self.route = "/backtests"
        self.views: list[ft.View] = []
        self.window = type("Window", (), {})()
        self.width = 1920
        self.height = 1200
        self.updates = 0

    def update(self, *_args: object) -> None:
        self.updates += 1


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        if isinstance(child, ft.Control):
            yield from _walk(child)


def test_backtest_route_loads_on_worker_behind_loading_shell(monkeypatch) -> None:
    started, release, done = threading.Event(), threading.Event(), threading.Event()
    loader_threads: list[str] = []

    def blocked_load(service, as_of_date=None, *, publish_guard=None):
        loader_threads.append(threading.current_thread().name)
        started.set()
        assert release.wait(10)
        return _report(service, as_of_date)

    monkeypatch.setattr(backtest_service.BacktestService, "load_or_run_backtest", blocked_load)
    snapshot = build_snapshot()
    assert snapshot.backtest is None
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    def consume_backtest(_page, app_state):
        assert app_state.ensure_backtest() is not None
        return PageView(PageChrome("Backtests", "ready"), ft.Text("Backtest ready", key="backtests.ready"))

    monkeypatch.setitem(router.PAGES, "/backtests", ("Backtests", consume_backtest))
    page = _FakePage()
    router.render_route_change(page, state, "/backtests", background=True, patience_s=0.01, on_done=done.set)

    assert started.wait(5)
    assert page.views and any(getattr(control, "key", None) == "shell.skeleton" for control in _walk(page.views[0]))
    release.set()
    assert done.wait(10)
    assert loader_threads == ["page-build:/backtests"]
    assert any(getattr(control, "key", None) == "backtests.ready" for control in _walk(page.views[0]))
