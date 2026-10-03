from __future__ import annotations

import inspect
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app import router
from etf_cockpit.app.components.depth_selector import (
    RUN_KEY,
    RUN_STATUS_KEY,
    ProfileRunController,
    depth_details_view,
)
from etf_cockpit.app.state import AppState
from etf_cockpit.application.analysis_depth import (
    ANALYSIS_TIMINGS_RELATIVE_PATH,
    load_analysis_depth_profiles,
)
from etf_cockpit.application.interactive_profile_run import interactive_profile_binder
from tests.test_interactive_profile_run import fixture_snapshot
from tests.ui.test_analysis_depth_run_ui import _by_key


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf="AAA")


def _click_run(controller, root):
    view = depth_details_view("quick", root=root, history_reader=lambda _r, _d: [], run_controller=controller)
    _by_key(view, RUN_KEY).on_click(SimpleNamespace())
    return view


def test_run_with_the_interactive_binder_starts_an_activity_and_reports_instrument_progress(tmp_path) -> None:
    snapshot = fixture_snapshot()
    state = _state(snapshot)
    seen: list[str] = []
    controller = ProfileRunController(
        state, root=tmp_path, binder=interactive_profile_binder(lambda: snapshot), background=False
    )
    original = state.update_activity

    def spy(*args, **kwargs):
        seen.append(args[1] if len(args) > 1 else str(kwargs.get("message")))
        return original(*args, **kwargs)

    state.update_activity = spy  # type: ignore[method-assign]
    view = _click_run(controller, tmp_path)
    total = len(load_analysis_depth_profiles()["quick"].stages)
    entry = state.recent_activity[-1]
    assert state.current_activity is None and entry.status == "success" and entry.total_units == 2 * total
    assert any(text.startswith("Instrument 2/2 BBB, stage 1/") for text in seen)
    assert f"completed {2 * total}/{2 * total} stages" in controller.status == _by_key(view, RUN_STATUS_KEY).value
    assert len(pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)) == 2 * total  # only real runs are stored


def test_run_without_local_prices_fails_the_activity_with_the_reason(tmp_path) -> None:
    snapshot = fixture_snapshot(with_prices=False)
    state = _state(snapshot)
    controller = ProfileRunController(
        state, root=tmp_path, binder=interactive_profile_binder(lambda: snapshot), background=False
    )
    _click_run(controller, tmp_path)
    assert state.recent_activity[-1].status == "failed"
    assert "no local prices for AAA" in controller.status and "failed" in controller.status


def test_binder_refusal_is_shown_as_the_run_unavailable_reason_and_router_registers_the_binder(tmp_path) -> None:
    state = _state(fixture_snapshot(ids=()))
    controller = ProfileRunController(
        state, root=tmp_path, binder=interactive_profile_binder(lambda: state.snapshot), background=False
    )
    view = _click_run(controller, tmp_path)
    assert not state.recent_activity and state.current_activity is None
    assert "no enabled instruments" in _by_key(view, RUN_STATUS_KEY).value
    assert "binder=interactive_profile_binder(" in inspect.getsource(router)
