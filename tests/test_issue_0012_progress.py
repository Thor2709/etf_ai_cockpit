from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from etf_cockpit.app import state as app_state_module
from etf_cockpit.app.pages.dashboard import _activity_panel
from etf_cockpit.app.pages.import_export import _record_export_terminal
from etf_cockpit.app.state import AppState, _read_recent_activity
from etf_cockpit.core.workflow import LONG_RUNNING_ACTIONS
from etf_cockpit.services import build_snapshot


def _texts(control: object) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if value is not None:
        values.append(str(value))
    for attribute in ("controls", "content"):
        child = getattr(control, attribute, None)
        children = child if isinstance(child, (list, tuple)) else (child,) if child is not None else ()
        for item in children:
            values.extend(_texts(item))
    return values


def _state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_issue_0012_contract_names_every_declared_long_running_action() -> None:
    assert tuple(LONG_RUNNING_ACTIONS) == (
        "yfinance_fetch",
        "validation",
        "algorithms",
        "baseline_forecast",
        "timesfm_forecast",
        "toto_forecast",
        "forecasts",
        "scoreboard_write",
        "audit_export",
        "cache_rebuild",
        "notes_news_import",
        "holdings_factsheet_import",
        "macro_news_refresh",
    )
    assert all(label for label in LONG_RUNNING_ACTIONS.values())


def test_direct_state_action_persists_terminal_fields_and_readable_error(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    state = _state()

    state.begin_activity("Import manual_news", "Reading selected notes",)
    state.update_activity("Validating notes", completed_units=1, total_units=2, output_path=tmp_path / "notes.csv")
    failed = state.fail_activity("Import manual_news", ValueError("notes schema is invalid"))

    assert failed.status == "failed"
    assert failed.started_at
    assert failed.finished_at
    assert failed.step == "Failed"
    assert "schema is invalid" in failed.message
    assert failed.error and "schema is invalid" in failed.error
    assert failed.output_path == str(tmp_path / "notes.csv")

    restored = _read_recent_activity()
    assert len(restored) == 1
    entry = restored[0]
    assert entry.action_id == failed.action_id
    assert entry.started_at == failed.started_at
    assert entry.finished_at == failed.finished_at
    assert entry.error == failed.error
    assert entry.output_path == failed.output_path
    assert entry.status == "failed"

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    terminal = next(row for row in rows if row["event_type"] == "activity_failed")
    assert terminal["output_summary"]["started_at"] == failed.started_at
    assert terminal["output_summary"]["finished_at"] == failed.finished_at
    assert terminal["output_summary"]["error"] == failed.error


@pytest.mark.parametrize(
    ("method_name", "expected_message"),
    (("refresh_sample_data", "Sample data regenerated and signals refreshed."), ("refresh_signals", "Signals refreshed from local data.")),
)
def test_void_state_actions_persist_meaningful_terminal_messages(tmp_path, monkeypatch, method_name, expected_message) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    snapshot = _state().snapshot
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False: snapshot)
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    assert getattr(state, method_name)() is None
    assert state.recent_activity[-1].message == expected_message
    assert state.recent_activity[-1].message != "None"
    assert _read_recent_activity()[-1].message == expected_message


def test_failed_export_result_records_unavailable_terminal_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    state.begin_activity("Export scoreboard", "Preparing export")

    _record_export_terminal(
        state,
        label="Export scoreboard",
        message="Export unavailable: permission denied.",
        destination=tmp_path / "scoreboard.csv",
        ok=False,
        error="permission denied",
        owns_activity=True,
    )

    assert state.current_activity is None
    assert state.recent_activity[-1].status == "failed"
    assert "permission denied" in state.recent_activity[-1].message


def test_forecast_steps_cover_baseline_timesfm_toto_and_scoreboard(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    observed: list[str] = []

    class FakeDataService:
        def __init__(self, _config) -> None:
            pass

        def run_yfinance_forecasts(self, **_kwargs) -> str:
            observed.append("forecasts")
            return "baseline ok; optional models unavailable"

    monkeypatch.setattr(app_state_module, "DataService", FakeDataService)
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False: snapshot)
    monkeypatch.setattr(state, "_write_current_scoreboard", lambda: tmp_path / "scoreboard.parquet")

    state.run_forecasting_models()

    assert observed == ["forecasts"]
    assert state.recent_activity[-1].status == "success"
    assert state.recent_activity[-1].output_path == str(tmp_path / "scoreboard.parquet")
    events = [json.loads(line) for line in (tmp_path / "session.jsonl").read_text(encoding="utf-8").splitlines()]
    steps = [row["output_summary"].get("step") for row in events if row["event_type"] == "activity_update"]
    assert {"Running baseline forecasts", "Checking cached TimesFM forecasts", "Checking cached Toto forecasts", "Forecasts and scoreboard complete"} <= set(steps)


def test_activity_panel_renders_spinner_step_progress_and_terminal_error() -> None:
    state = SimpleNamespace(
        current_activity=SimpleNamespace(
            label="Run forecasting models",
            step="Checking cached Toto forecasts",
            completed_units=3,
            total_units=4,
        ),
        last_message="Running",
        recent_activity=[],
    )

    control = _activity_panel(state)
    assert "Run forecasting models" in _texts(control)
    assert "Current step: Checking cached Toto forecasts" in _texts(control)
    progress_bars = [item for item in _walk(control) if type(item).__name__ == "ProgressBar"]
    assert progress_bars and progress_bars[0].value == 0.75


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
