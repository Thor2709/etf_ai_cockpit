from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.components.depth_selector import (
    DETAILS_KEY,
    RUN_CANCEL_KEY,
    RUN_KEY,
    RUN_STATUS_KEY,
    ProfileRunController,
    depth_details_view,
    depth_selector,
)
from etf_cockpit.app.state import AppState
from etf_cockpit.application.analysis_depth import (
    ANALYSIS_TIMINGS_RELATIVE_PATH,
    AnalysisTimingRecord,
    ProfileRunBinding,
    certify_and_record_benchmark,
    load_analysis_depth_profiles,
)
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for name in ("content", "controls", "title", "leading", "trailing", "actions"):
        child = getattr(control, name, None)
        if isinstance(child, (list, tuple)):
            for item in child:
                if item is not None:
                    yield from _walk(item)
        elif child is not None and hasattr(child, "__dict__"):
            yield from _walk(child)


def _by_key(root, key):
    return next(c for c in _walk(root) if getattr(c, "key", None) == key)


def _state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _binder(calls: list[str], hook=None):
    def binder(depth: str) -> ProfileRunBinding:
        def runner(instrument_id, _input, stage, _plan):
            calls.append(stage.stage_id)
            if hook is not None:
                hook(stage.stage_id)
            return {"stage_id": stage.stage_id, "value": 1}

        return ProfileRunBinding("ETF-A", {"value": 1}, "ui-run-test.v1", runner)

    return binder


def _view(controller, root=None):
    return depth_details_view("quick", root=root, history_reader=lambda _r, _d: [], run_controller=controller)


def test_run_button_reports_step_progress_and_finishes_the_activity(tmp_path) -> None:
    state, calls = _state(), []
    controller = ProfileRunController(state, root=tmp_path, binder=_binder(calls), background=False)
    view = _view(controller, tmp_path)
    _by_key(view, RUN_KEY).on_click(SimpleNamespace())
    total = len(load_analysis_depth_profiles()["quick"].stages)
    assert len(calls) == total and state.current_activity is None
    entry = state.recent_activity[-1]
    assert entry.status == "success" and entry.total_units == total and entry.label.startswith("Run Quick")
    assert f"completed {total}/{total}" in controller.status
    assert len(pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)) == total


def test_cancel_button_stops_between_stages_and_a_stage_failure_fails_the_activity(tmp_path) -> None:
    state, calls = _state(), []
    holder: dict[str, object] = {}

    def click_cancel_in_stage_two(stage_id: str) -> None:
        if len(calls) == 2:
            _by_key(holder["view"], RUN_CANCEL_KEY).on_click(SimpleNamespace())

    controller = ProfileRunController(
        state, root=tmp_path, binder=_binder(calls, click_cancel_in_stage_two), background=False
    )
    holder["view"] = _view(controller, tmp_path)
    _by_key(holder["view"], RUN_KEY).on_click(SimpleNamespace())
    assert len(calls) == 2  # stopped between stages: stage 3 never started
    assert state.current_activity is None and state.recent_activity[-1].status == "cancelled"
    assert "cancelled" in controller.status and not controller.running
    assert "cancelled" in set(pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)["outcome"])
    # resume: running again reuses the stage completed before the cancel
    calls.clear()
    holder["view"] = _view(controller, tmp_path)
    controller.binder = _binder(calls)
    controller.start("quick")
    assert state.recent_activity[-1].status == "success" and calls[0] != load_analysis_depth_profiles()["quick"].stages[0].stage_id

    failing = ProfileRunController(
        _state(), root=tmp_path, binder=_binder([], lambda _stage: (_ for _ in ()).throw(RuntimeError("boom"))),
        background=False,
    )
    assert failing.start("quick")
    assert failing.state.recent_activity[-1].status == "failed" and "boom" in failing.status


def test_run_is_unavailable_without_a_stage_runner_and_starts_no_activity(tmp_path) -> None:
    state = _state()
    controller = ProfileRunController(state, root=tmp_path, background=False)  # no binder registered
    view = _view(controller, tmp_path)
    _by_key(view, RUN_KEY).on_click(SimpleNamespace())
    assert state.current_activity is None and not state.recent_activity
    assert "Run unavailable" in _by_key(view, RUN_STATUS_KEY).value
    assert not (tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH).exists()
    bare = _view(None, tmp_path)
    assert _by_key(bare, RUN_KEY).disabled and "Unavailable" in _by_key(bare, RUN_STATUS_KEY).value
    assert controller.start("nonsense") is False and "select a depth first" in controller.status
    opened: list[ft.AlertDialog] = []
    group = depth_selector(
        "quick", on_selected=lambda _d: None, open_dialog=opened.append, root=tmp_path,
        history_reader=lambda _r, _d: [], run_controller=controller,
    )
    _by_key(group, DETAILS_KEY).on_click(SimpleNamespace())
    assert _by_key(opened[0].content, RUN_KEY) is not None


def test_details_dialog_shows_the_stored_certification_verdict_or_not_available(tmp_path) -> None:
    def cert_text(root) -> str:
        view = depth_details_view("quick", root=root, history_reader=lambda _r, _d: [])
        return " ".join(str(c.value) for c in _walk(_by_key(view, f"{DETAILS_KEY}.certification")) if isinstance(c, ft.Text))

    assert "not available" in cert_text(tmp_path)  # nothing stored
    profile = load_analysis_depth_profiles()["quick"]
    records = [AnalysisTimingRecord("r1", "quick", "stage", "benchmark_instrument", 1.5, "warm")]
    certify_and_record_benchmark(
        tmp_path, profile, run_id="r1", records=records, fixture_id="synthetic_test_fixture",
        fixture_content_digest="0" * 64, instrument_count=1, cache_state="warm", cache_hits=1, machine=None,
    )
    text = cert_text(tmp_path)
    assert "not certified" in text and "p95" in text and "run r1" in text  # measured, but a synthetic fixture
    assert "Certification: certified" not in text
