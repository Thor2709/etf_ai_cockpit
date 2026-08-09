from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from datetime import date
from functools import lru_cache
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
import yaml

from etf_cockpit.app import state as app_state_module
from etf_cockpit.app.pages.dashboard import _activity_panel
from etf_cockpit.app.pages.dashboard import _export_pack, _run_action, _run_dialog_action
from etf_cockpit.app.pages import dashboard as dashboard_page_module
from etf_cockpit.app.pages.import_export import _record_export_terminal
from etf_cockpit.app.pages import jobs as jobs_page_module
from etf_cockpit.app.pages import chatgpt_audit as chatgpt_audit_module
from etf_cockpit.app.pages import import_export as import_export_page_module
from etf_cockpit.app.pages import trust_evidence as trust_evidence_module
from etf_cockpit.app.pages import errors_recovery as errors_recovery_module
from etf_cockpit.app import router as router_module
from etf_cockpit.app.state import ActivityEntry, ActivityUnavailableError, AppState, _read_recent_activity
from etf_cockpit.core.errors import ErrorStore
from etf_cockpit.core import session_log
from etf_cockpit.core.workflow import (
    LONG_RUNNING_ACTIONS,
    LONG_RUNNING_ACTION_CONTROL_KEYS,
    LONG_RUNNING_ACTION_SPECS,
    WorkflowController,
    WorkflowStatus,
    WorkflowStep,
    WorkflowTransitionError,
)
from etf_cockpit import services as services_module
from etf_cockpit.data import duckdb_store as duckdb_store_module
from etf_cockpit.data import fund_holdings as fund_holdings_module
from etf_cockpit.data import import_pipeline as import_pipeline_module
from etf_cockpit.data import sample_data as sample_data_module
from etf_cockpit.data import trade_candidate_analysis as candidate_analysis_module
from etf_cockpit.data.esef_provider import FilingsXbrlOrgProvider
from etf_cockpit.data.oam_adapters import (
    FranceDilaOamAdapter,
    OAMDiscoveryRequest,
    archive_manual_official_filing,
)
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.parsers.contracts import ParseResult, ParseWarning
from etf_cockpit.operations.event_store import load_events_with_tail_recovery
from etf_cockpit.services import ForecastService
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


@lru_cache(maxsize=1)
def _snapshot():
    return build_snapshot()


def _state() -> AppState:
    snapshot = _snapshot()
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
        "sec_companyfacts_fetch",
        "sec_companyfacts_import",
        "esef_discovery",
        "esef_download",
        "esef_import",
        "oam_discovery",
        "manual_official_filing_import",
    )
    assert all(label for label in LONG_RUNNING_ACTIONS.values())


def test_direct_state_action_persists_terminal_fields_and_readable_error(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    state = _state()

    action_id = state.begin_activity("Import manual_news", "Reading selected notes").action_id
    state.update_activity(
        "Validating notes",
        completed_units=1,
        total_units=2,
        output_path=tmp_path / "notes.csv",
        expected_action_id=action_id,
    )
    failed = state.fail_activity(
        "Import manual_news",
        ValueError("notes schema is invalid"),
        expected_action_id=action_id,
    )

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
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False, **_kwargs: snapshot)
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    assert getattr(state, method_name)() is None
    assert state.recent_activity[-1].message == expected_message
    assert state.recent_activity[-1].message != "None"
    assert _read_recent_activity()[-1].message == expected_message


def test_failed_export_result_records_unavailable_terminal_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Export scoreboard", "Preparing export").action_id

    _record_export_terminal(
        state,
        label="Export scoreboard",
        message="Export unavailable: permission denied.",
        destination=tmp_path / "scoreboard.csv",
        ok=False,
        error="permission denied",
        action_id=action_id,
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
            callback = _kwargs["progress_callback"]
            callback("Running baseline forecasts", 1, 4)
            callback("Checking cached TimesFM forecasts", 2, 4)
            callback("Checking cached Toto forecasts", 3, 4)
            observed.append("forecasts")
            return "baseline ok; optional models unavailable"

    monkeypatch.setattr(app_state_module, "DataService", FakeDataService)
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False, **_kwargs: snapshot)
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
            started_at="2026-08-09T01:02:03+00:00",
        ),
        last_message="Running",
        recent_activity=[
            ActivityEntry(
                label="Export audit packet",
                status="failed",
                step="Failed",
                started_at="2026-08-09T00:00:00+00:00",
                finished_at="2026-08-09T00:01:00+00:00",
                message="Export failed safely.",
                output_path="C:/exports/audit.zip",
                error="permission denied",
            )
        ],
    )

    control = _activity_panel(state)
    assert "Run forecasting models" in _texts(control)
    assert "Current step: Checking cached Toto forecasts" in _texts(control)
    assert "Started: 2026-08-09T01:02:03+00:00" in _texts(control)
    assert any("output: audit.zip" in text and "error: permission denied" in text for text in _texts(control))
    progress_bars = [item for item in _walk(control) if type(item).__name__ == "ProgressBar"]
    assert progress_bars and progress_bars[0].value == 0.75


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_startup_retains_terminal_history_and_recovers_interrupted_activity(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    state = _state()
    completed_id = state.begin_activity("Completed action", "Working").action_id
    state.finish_activity("Completed safely", expected_action_id=completed_id)
    interrupted_id = state.begin_activity("Interrupted action", "Publishing").action_id

    session_log.init_session_log(clear=False, build_mode="desktop", route="/")
    restored = _read_recent_activity()

    assert [(entry.action_id, entry.status) for entry in restored] == [
        (completed_id, "success"),
        (interrupted_id, "interrupted"),
    ]
    assert restored[-1].error == "Application restarted before this action reached a terminal state."
    assert _read_recent_activity()[-1].status == "interrupted"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert sum(row["event_type"] == "activity_interrupted" for row in rows) == 1
    assert len(log_path.read_text(encoding="utf-8").splitlines()) < session_log.SESSION_LOG_MAX_EVENTS


def test_session_history_retention_is_bounded_and_rehashed_in_place(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    monkeypatch.setattr(session_log, "SESSION_LOG_MAX_EVENTS", 5)
    for index in range(8):
        session_log.log_event(event_type="test_event", operation=str(index), path=log_path)

    session_log.init_session_log(clear=False, route="/")

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5
    assert rows[0]["prior_event_hash"] is None
    assert all(row["prior_event_hash"] == rows[index - 1]["event_hash"] for index, row in enumerate(rows[1:], 1))


def test_session_log_compaction_replace_failure_preserves_canonical_bytes(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "session.jsonl"
    for index in range(6):
        session_log.log_event(event_type="test_event", operation=str(index), path=log_path)
    original = log_path.read_bytes()

    def fail_replace(_source, _destination) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("etf_cockpit.core.atomic_io._replace_single_destination_with_retry", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        session_log._compact_session_log(log_path, max_events=3)

    assert log_path.read_bytes() == original


@pytest.mark.parametrize("event_count,max_events", [(2, 10), (5, 5)])
def test_startup_recovers_truncated_tail_before_append_and_compaction(
    event_count, max_events, tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    monkeypatch.setattr(session_log, "SESSION_LOG_MAX_EVENTS", max_events)
    session_log._EVENT_COUNTS.pop(log_path, None)
    for index in range(event_count):
        session_log.log_event(event_type="valid_prefix", operation=str(index), path=log_path)
    valid_prefix = log_path.read_bytes()
    with log_path.open("ab") as handle:
        handle.write(b'{"incomplete":')

    session_log.init_session_log(clear=False, route="/")
    events, recovery = load_events_with_tail_recovery(log_path)
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert recovery.quarantined_tail is False
    assert list(tmp_path.glob("session.jsonl.tail-*.quarantine"))
    assert any(row["event_type"] == "session_start" for row in rows)
    assert len(rows) <= max_events
    if event_count < max_events:
        assert log_path.read_bytes().startswith(valid_prefix)
    controller = WorkflowController()
    action_id = controller.start("tail recovery", "Tail recovery")
    controller.finish(action_id, WorkflowStatus.SUCCESS, "Recovered", ())
    event_types = [event.event_type for event in load_events_with_tail_recovery(log_path)[0]]
    assert "workflow_start" in event_types
    assert "workflow_finish" in event_types


def test_activity_ownership_and_cancellation_do_not_adopt_or_replace_actions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Owner", "Working").action_id

    with pytest.raises(WorkflowTransitionError):
        state.begin_activity("Unrelated", "Starting")
    with pytest.raises(WorkflowTransitionError):
        state.update_activity("Wrong owner", expected_action_id="not-the-owner")
    assert state.current_activity and state.current_activity.action_id == action_id

    state.cancel_activity(expected_action_id=action_id)
    with pytest.raises(WorkflowTransitionError):
        state.update_activity("Late update", expected_action_id=action_id)
    with pytest.raises(WorkflowTransitionError):
        state.finish_activity("Late success", expected_action_id=action_id)
    assert state.current_activity is not None
    with pytest.raises(WorkflowTransitionError):
        state.begin_activity("Replacement", "Starting")
    state.release_activity(action_id)
    assert state.current_activity is None
    assert [(entry.action_id, entry.status) for entry in state.recent_activity] == [(action_id, "cancelled")]


def test_concurrent_begin_activity_creates_exactly_one_controller_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    barrier = threading.Barrier(3)
    started: list[str] = []
    rejected: list[Exception] = []

    def begin(label: str) -> None:
        barrier.wait()
        try:
            started.append(state.begin_activity(label, "Starting").action_id)
        except Exception as exc:
            rejected.append(exc)

    workers = [threading.Thread(target=begin, args=(f"Action {index}",)) for index in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=2)

    assert len(started) == 1
    assert len(rejected) == 1 and isinstance(rejected[0], WorkflowTransitionError)
    assert [result.action_id for result in state.workflow_controller.active()] == started


def test_update_activity_cancellation_race_leaves_cancelled_terminal_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Owner", "Initial step").action_id
    cancel_entered = threading.Event()
    release_cancel = threading.Event()
    update_errors: list[Exception] = []
    real_cancel = state.workflow_controller.cancel

    def blocking_cancel(*args, **kwargs):
        cancel_entered.set()
        assert release_cancel.wait(2)
        return real_cancel(*args, **kwargs)

    monkeypatch.setattr(state.workflow_controller, "cancel", blocking_cancel)
    canceller = threading.Thread(target=lambda: state.cancel_activity(expected_action_id=action_id))
    canceller.start()
    assert cancel_entered.wait(2)

    def late_update() -> None:
        try:
            state.update_activity(
                "Late step",
                "late message",
                completed_units=9,
                total_units=10,
                expected_action_id=action_id,
            )
        except Exception as exc:
            update_errors.append(exc)

    updater = threading.Thread(target=late_update)
    updater.start()
    release_cancel.set()
    canceller.join(timeout=2)
    updater.join(timeout=2)

    entry = state.current_activity
    assert entry is not None
    terminal = (entry.status, entry.step, entry.message, entry.completed_units, entry.total_units)
    assert terminal == ("cancelled", "Cancelled", "Cancelled by user", 0, None)
    assert len(update_errors) == 1 and isinstance(update_errors[0], WorkflowTransitionError)
    assert (entry.status, entry.step, entry.message, entry.completed_units, entry.total_units) == terminal
    assert state.last_message == "Cancelled by user"


def test_update_activity_controller_failure_does_not_partially_mutate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Owner", "Initial step").action_id
    entry = state.current_activity
    before = (entry.step, entry.message, entry.completed_units, entry.total_units, entry.output_path, state.last_message)
    monkeypatch.setattr(state.workflow_controller, "step", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("step failed")))

    with pytest.raises(RuntimeError, match="step failed"):
        state.update_activity(
            "Rejected step",
            "rejected message",
            completed_units=2,
            total_units=3,
            output_path=tmp_path / "out.csv",
            expected_action_id=action_id,
        )

    assert (entry.step, entry.message, entry.completed_units, entry.total_units, entry.output_path, state.last_message) == before


def test_cancelled_dashboard_action_cannot_publish_or_create_orphan(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    page = SimpleNamespace(update=lambda: None)
    started = threading.Event()
    release = threading.Event()
    worker_rebuilt = threading.Event()
    rebuild_count = 0
    destination = tmp_path / "published.txt"

    def action() -> str:
        started.set()
        release.wait(2)
        state.assert_activity_publishable()
        destination.write_text("should not publish", encoding="utf-8")
        return "published"

    def record_rebuild(*_args) -> None:
        nonlocal rebuild_count
        rebuild_count += 1
        if rebuild_count >= 2:
            worker_rebuilt.set()

    monkeypatch.setattr("etf_cockpit.app.pages.dashboard._rebuild", record_rebuild)
    _run_action(page, state, "Cancellable action", action)
    assert started.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    assert worker_rebuilt.wait(2)

    assert not destination.exists()
    assert state.current_activity is None
    assert [(entry.action_id, entry.status) for entry in state.recent_activity] == [(action_id, "cancelled")]


def test_dashboard_action_restores_cancelled_message_after_late_success(monkeypatch) -> None:
    state = _state()
    running_refresh = threading.Event()
    finalized = threading.Event()

    def record_rebuild(*_args) -> None:
        (running_refresh if state.current_activity is not None else finalized).set()

    monkeypatch.setattr("etf_cockpit.app.pages.dashboard._rebuild", record_rebuild)
    started = threading.Event()
    release = threading.Event()

    def action() -> str:
        started.set()
        assert release.wait(2)
        state.last_message = "late dashboard success"
        return "late dashboard success"

    _run_action(SimpleNamespace(update=lambda: None), state, "Late dashboard action", action)
    assert running_refresh.wait(2)
    assert started.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    assert finalized.wait(2)

    assert state.last_message == "Cancelled by user"
    assert state.recent_activity[-1].message == "Cancelled by user"


def test_dialog_action_restores_cancelled_message_after_late_success(monkeypatch) -> None:
    state = _state()
    running_refresh = threading.Event()
    finalized = threading.Event()

    def record_rebuild(*_args) -> None:
        (running_refresh if state.current_activity is not None else finalized).set()

    monkeypatch.setattr("etf_cockpit.app.pages.dashboard._rebuild", record_rebuild)
    result = SimpleNamespace(value="")
    started = threading.Event()
    release = threading.Event()

    def action() -> str:
        started.set()
        assert release.wait(2)
        state.last_message = "late dialog success"
        return "late dialog success"

    _run_dialog_action(
        SimpleNamespace(update=lambda: None),
        state,
        result,
        "Late dialog action",
        "Working",
        action,
    )
    assert running_refresh.wait(2)
    assert started.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    assert finalized.wait(2)

    assert state.last_message == "Cancelled by user"
    assert result.value == "Cancelled by user"


def test_export_pack_restores_cancelled_message_after_late_success(monkeypatch, tmp_path) -> None:
    state = _state()
    running_refresh = threading.Event()
    finalized = threading.Event()

    def record_rebuild(*_args) -> None:
        (running_refresh if state.current_activity is not None else finalized).set()

    monkeypatch.setattr("etf_cockpit.app.pages.dashboard._rebuild", record_rebuild)
    started = threading.Event()
    release = threading.Event()
    destination = tmp_path / "audit.zip"

    def export() -> Path:
        started.set()
        assert release.wait(2)
        state.last_message = "late export success"
        return destination

    state.export_audit_packet = export
    _export_pack(SimpleNamespace(update=lambda: None), state)
    assert running_refresh.wait(2)
    assert started.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    assert finalized.wait(2)

    assert state.last_message == "Cancelled by user"
    assert state.recent_activity[-1].message == "Cancelled by user"


def test_chatgpt_audit_control_is_cancellable_and_retry_revalidates_archive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "chatgpt.jsonl")
    monkeypatch.setattr(router_module, "render_shell", lambda *_args, **_kwargs: None)
    state = _state()
    state.error_store = ErrorStore(tmp_path / "errors.jsonl")
    entered = threading.Event()
    release = threading.Event()
    running_refreshes = 0
    terminal_refreshes = 0
    calls = 0
    validated: list[Path] = []
    destination = tmp_path / "audit.zip"

    def update() -> None:
        nonlocal running_refreshes, terminal_refreshes
        if state.current_activity is None:
            terminal_refreshes += 1
        else:
            running_refreshes += 1

    def export() -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(2)
            state.last_message = "late chatgpt export success"
            return destination
        if calls == 2:
            raise TimeoutError("audit export timeout")
        return destination

    def validate(path: Path, _destination: Path):
        validated.append(path)
        return SimpleNamespace(
            valid=True,
            included=("manifest.json",),
            missing=(),
            checksum_errors=(),
            secret_findings=(),
        )

    monkeypatch.setattr(state, "export_audit_packet", export)
    monkeypatch.setattr(chatgpt_audit_module, "extract_and_validate_audit_archive", validate)
    page = SimpleNamespace(route="/chatgpt", update=update)
    control = chatgpt_audit_module.chatgpt_audit_page(page, state)
    button = next(item for item in _walk(control) if getattr(item, "key", None) == "chatgpt.export-audit")

    button.on_click(SimpleNamespace())
    assert entered.wait(2)
    assert running_refreshes >= 1
    assert state.current_activity is not None
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    deadline = time.time() + 2
    while terminal_refreshes < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert state.last_message == "Cancelled by user"
    assert "Cancelled by user" in " ".join(_texts(control))

    button.on_click(SimpleNamespace())
    deadline = time.time() + 2
    while terminal_refreshes < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert state.recent_activity[-1].status == "failed"
    error = state.error_store.recent()[0]
    errors_recovery_module._retry(SimpleNamespace(), state, error.error_id)
    deadline = time.time() + 2
    while (
        state.current_activity is not None
        or state.recent_activity[-1].status != "success"
        or terminal_refreshes < 3
    ) and time.time() < deadline:
        time.sleep(0.01)

    assert calls == 3
    assert validated == [destination]
    assert state.recent_activity[-1].status == "success"
    assert "checksums validated" in state.recent_activity[-1].message


def test_import_export_audit_control_is_cancellable_and_retryable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "import-export.jsonl")
    monkeypatch.setattr(router_module, "render_shell", lambda *_args, **_kwargs: None)
    state = _state()
    state.error_store = ErrorStore(tmp_path / "errors.jsonl")
    entered = threading.Event()
    release = threading.Event()
    running_refreshes = 0
    terminal_refreshes = 0
    calls = 0
    destination = tmp_path / "audit.zip"

    def update() -> None:
        nonlocal running_refreshes, terminal_refreshes
        if state.current_activity is None:
            terminal_refreshes += 1
        else:
            running_refreshes += 1

    def export() -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(2)
            state.last_message = "late import-export success"
            return destination
        if calls == 2:
            raise TimeoutError("audit packet timeout")
        return destination

    monkeypatch.setattr(state, "export_audit_packet", export)
    page = SimpleNamespace(services=[], overlay=[], route="/import-export", update=update)
    control = import_export_page_module.import_export_page(page, state)
    button = next(
        item
        for item in _walk(control)
        if getattr(item, "key", None) == "import-export.export-audit-packet"
    )

    button.on_click(SimpleNamespace())
    assert entered.wait(2)
    assert running_refreshes >= 1
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    deadline = time.time() + 2
    while terminal_refreshes < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert state.last_message == "Cancelled by user"
    assert "Cancelled by user" in " ".join(_texts(control))

    button.on_click(SimpleNamespace())
    deadline = time.time() + 2
    while terminal_refreshes < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert state.recent_activity[-1].status == "failed"
    error = state.error_store.recent()[0]
    errors_recovery_module._retry(SimpleNamespace(), state, error.error_id)
    deadline = time.time() + 2
    while (
        state.current_activity is not None
        or state.recent_activity[-1].status != "success"
        or terminal_refreshes < 3
    ) and time.time() < deadline:
        time.sleep(0.01)

    assert calls == 3
    assert state.recent_activity[-1].status == "success"
    assert state.last_export_path == destination


def test_long_running_contract_points_to_real_handlers_and_registered_controls() -> None:
    acceptance_path = Path("configs/ui_acceptance.yaml")
    acceptance = acceptance_path.read_text(encoding="utf-8")
    accepted_controls = yaml.safe_load(acceptance)["controls"]
    assert tuple(LONG_RUNNING_ACTION_SPECS) == tuple(LONG_RUNNING_ACTIONS)
    for key, spec in LONG_RUNNING_ACTION_SPECS.items():
        assert spec.handler and spec.control_key, key
        assert LONG_RUNNING_ACTION_CONTROL_KEYS[key], key
        assert spec.control_key == LONG_RUNNING_ACTION_CONTROL_KEYS[key][0], key
        for control_key in LONG_RUNNING_ACTION_CONTROL_KEYS[key]:
            assert control_key in acceptance, (key, control_key)
        if spec.handler.startswith("AppState."):
            assert callable(getattr(AppState, spec.handler.split(".", 1)[1]))
    assert LONG_RUNNING_ACTION_CONTROL_KEYS["audit_export"] == (
        "dashboard.export-audit",
        "import-export.export-audit-packet",
        "chatgpt.export-audit",
    )
    reverse_catalog: dict[str, set[str]] = {}
    for action_key, control_keys in LONG_RUNNING_ACTION_CONTROL_KEYS.items():
        for control_key in control_keys:
            reverse_catalog.setdefault(control_key, set()).add(action_key)
    accepted_holdings_factsheet_imports = {
        control["key"]
        for control in accepted_controls
        if control["route"] in {"/", "/etf-disclosures"}
        and control["control_type"] == "button"
        and (
            control["key"].startswith("etf-disclosures.import-")
            or control["key"].startswith("dashboard.import-etf-")
        )
    }
    assert len(accepted_holdings_factsheet_imports) == 7
    assert accepted_holdings_factsheet_imports == set(LONG_RUNNING_ACTION_CONTROL_KEYS["holdings_factsheet_import"])
    assert accepted_holdings_factsheet_imports == {
        control_key
        for control_key, action_keys in reverse_catalog.items()
        if "holdings_factsheet_import" in action_keys
    }
    assert reverse_catalog["dashboard.run-forecasting-models"] == {
        "baseline_forecast",
        "timesfm_forecast",
        "toto_forecast",
        "forecasts",
    }


@pytest.mark.parametrize("action_kind", ["yfinance", "local_import", "dashboard_result"])
def test_normal_return_unavailable_results_are_failed_activities(action_kind, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / f"{action_kind}.jsonl")
    state = _state()

    class UnavailableService:
        def __init__(self, _config) -> None:
            self.last_operation_succeeded = False

        def refresh_yfinance_data(self, **_kwargs) -> str:
            return "Provider unavailable without changing local data."

        def import_local_file(self, *_args, **_kwargs):
            return SimpleNamespace(ok=False, message="Import validation unavailable.")

    monkeypatch.setattr(app_state_module, "DataService", UnavailableService)
    if action_kind == "yfinance":
        with pytest.raises(ActivityUnavailableError):
            state.refresh_yfinance_data()
    elif action_kind == "local_import":
        with pytest.raises(ActivityUnavailableError):
            state.validate_local_import(str(tmp_path / "input.csv"), "prices")
    else:
        worker_rebuilt = threading.Event()
        rebuild_count = 0

        def record_rebuild(*_args) -> None:
            nonlocal rebuild_count
            rebuild_count += 1
            if rebuild_count >= 2:
                worker_rebuilt.set()

        monkeypatch.setattr("etf_cockpit.app.pages.dashboard._rebuild", record_rebuild)
        _run_action(
            SimpleNamespace(update=lambda: None),
            state,
            "Unavailable callback",
            lambda: SimpleNamespace(status="unavailable", message="Forecast unavailable."),
        )
        deadline = time.time() + 2
        while not state.recent_activity and time.time() < deadline:
            time.sleep(0.02)
        assert worker_rebuilt.wait(2)

    assert state.current_activity is None
    assert state.recent_activity[-1].status == "failed"
    assert "unavailable" in state.recent_activity[-1].message.lower()


def test_cache_cleanup_unavailable_is_failed_and_ui_uses_redacted_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "cache.jsonl")
    monkeypatch.setattr(
        jobs_page_module,
        "generated_cache_cleanup",
        lambda *_args, **_kwargs: {
            "status": "unavailable",
            "removed": [],
            "cache_path": tmp_path / "cache",
            "error": "api_key=raw-cache-secret",
        },
    )
    state = _state()
    control = jobs_page_module.jobs_page(SimpleNamespace(update=lambda: None), state)
    button = next(item for item in _walk(control) if getattr(item, "key", None) == "jobs.resource-cache-cleanup")

    button.on_click(SimpleNamespace())
    deadline = time.time() + 2
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.01)

    assert state.recent_activity[-1].status == "failed"
    assert "raw-cache-secret" not in " ".join(_texts(control))
    assert "***redacted***" in " ".join(_texts(control))


def test_cache_rebuild_cancellation_and_retry_use_background_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "cache.jsonl")
    monkeypatch.setattr(router_module, "render_shell", lambda *_args, **_kwargs: None)
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def cleanup(_root, *, maximum_bytes, apply=False, publish_guard=None):
        nonlocal calls
        if not apply:
            return {"status": "ready", "removed": [], "cache_path": tmp_path / "cache"}
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(2)
            with publish_guard():
                pass
            return {"status": "ok", "removed": [], "cache_path": tmp_path / "cache"}
        if calls == 2:
            return {"status": "unavailable", "removed": [], "cache_path": tmp_path / "cache", "error": "retry unavailable"}
        return {"status": "ok", "removed": ["cache.bin"], "cache_path": tmp_path / "cache"}

    monkeypatch.setattr(jobs_page_module, "generated_cache_cleanup", cleanup)
    state = _state()
    refreshes: list[str] = []

    def record_refresh(*_args) -> None:
        refreshes.append("running" if state.current_activity is not None else "terminal")

    monkeypatch.setattr(jobs_page_module, "_refresh_activity_shell", record_refresh)
    control = jobs_page_module.jobs_page(SimpleNamespace(update=lambda: None), state)
    button = next(item for item in _walk(control) if getattr(item, "key", None) == "jobs.resource-cache-cleanup")

    button.on_click(SimpleNamespace())
    assert refreshes == ["running"]
    assert entered.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    deadline = time.time() + 2
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.01)
    deadline = time.time() + 2
    while refreshes.count("terminal") < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert state.recent_activity[-1].status == "cancelled"
    assert "Cancelled by user" in " ".join(_texts(control))

    # The first call was cancelled; a later explicit failure exposes a retry
    # callback that starts a fresh background activity.
    button.on_click(SimpleNamespace())
    deadline = time.time() + 2
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.01)
    deadline = time.time() + 2
    while refreshes.count("terminal") < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert state.recent_activity[-1].status == "failed"
    error = state.error_store.recent()[0]
    errors_recovery_module._retry(SimpleNamespace(), state, error.error_id)
    deadline = time.time() + 2
    while (state.current_activity is not None or state.recent_activity[-1].status != "success") and time.time() < deadline:
        time.sleep(0.01)
    deadline = time.time() + 2
    while refreshes.count("terminal") < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert calls == 3
    assert state.recent_activity[-1].status == "success"
    assert refreshes == ["running", "terminal", "running", "terminal", "running", "terminal"]


def test_notes_native_import_cancellation_restores_result_after_late_success(tmp_path, monkeypatch) -> None:
    state = _state()
    running_refresh = threading.Event()
    finalized = threading.Event()

    def record_rebuild(*_args) -> None:
        (running_refresh if state.current_activity is not None else finalized).set()

    monkeypatch.setattr(dashboard_page_module, "_rebuild", record_rebuild)
    started = threading.Event()
    release = threading.Event()
    source = tmp_path / "notes.csv"
    source.write_text("headline\nlocal note\n", encoding="utf-8")

    def validate(path, dataset_type):
        assert path == str(source)
        assert dataset_type == "manual_news"
        started.set()
        assert release.wait(2)
        state.last_message = "late notes success"
        return "late notes success"

    monkeypatch.setattr(state, "validate_local_import", validate)
    page = SimpleNamespace(services=[], route="/", update=lambda: None)
    dashboard_page_module._open_renew_dialog(page, state)
    picker = page.services[0]
    monkeypatch.setattr(
        picker,
        "pick_files",
        lambda **_kwargs: asyncio.sleep(0, result=[SimpleNamespace(path=str(source), bytes=None, name=source.name)]),
    )
    button = next(item for item in _walk(page.dialog) if getattr(item, "key", None) == "dashboard.import-manual-notes")
    asyncio.run(button.on_click(SimpleNamespace()))
    assert running_refresh.wait(2)
    assert started.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    assert finalized.wait(2)

    assert state.last_message == "Cancelled by user"
    assert state.recent_activity[-1].status == "cancelled"
    assert "Cancelled by user" in " ".join(_texts(page.dialog))


def test_notes_browser_import_retry_reenters_background_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "render_shell", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "notes.jsonl")
    state = _state()
    state.error_store = ErrorStore(tmp_path / "errors.jsonl")
    running_refreshes = 0
    terminal_refreshes = 0

    def record_rebuild(*_args) -> None:
        nonlocal running_refreshes, terminal_refreshes
        if state.current_activity is None:
            terminal_refreshes += 1
        else:
            running_refreshes += 1

    monkeypatch.setattr(dashboard_page_module, "_rebuild", record_rebuild)
    attempts = 0

    def import_upload(name, content, dataset_type):
        nonlocal attempts
        assert (name, content, dataset_type) == ("notes.csv", b"browser notes", "manual_news")
        attempts += 1
        if attempts == 1:
            raise TimeoutError("notes provider timeout")
        return "Browser notes imported."

    monkeypatch.setattr(state, "import_local_upload", import_upload)
    page = SimpleNamespace(services=[], route="/", update=lambda: None)
    dashboard_page_module._open_renew_dialog(page, state)
    picker = page.services[0]
    monkeypatch.setattr(
        picker,
        "pick_files",
        lambda **_kwargs: asyncio.sleep(0, result=[SimpleNamespace(path=None, bytes=b"browser notes", name="notes.csv")]),
    )
    button = next(item for item in _walk(page.dialog) if getattr(item, "key", None) == "dashboard.import-manual-notes")
    asyncio.run(button.on_click(SimpleNamespace()))
    deadline = time.time() + 2
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.01)
    deadline = time.time() + 2
    while terminal_refreshes < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert state.recent_activity[-1].status == "failed"
    error = state.error_store.recent()[0]
    errors_recovery_module._retry(SimpleNamespace(), state, error.error_id)
    deadline = time.time() + 2
    while (state.current_activity is not None or state.recent_activity[-1].status != "success") and time.time() < deadline:
        time.sleep(0.01)
    deadline = time.time() + 2
    while terminal_refreshes < 2 and time.time() < deadline:
        time.sleep(0.01)

    assert attempts == 2
    assert running_refreshes == 2
    assert terminal_refreshes == 2
    assert state.recent_activity[-1].status == "success"
    assert state.recent_activity[-1].message == "Browser notes imported."


def test_empty_renew_picker_rerenders_terminal_shell(monkeypatch) -> None:
    state = _state()
    rebuild_states: list[str] = []

    def rebuild(_page, current_state) -> None:
        rebuild_states.append("running" if current_state.current_activity is not None else "terminal")

    monkeypatch.setattr(dashboard_page_module, "_rebuild", rebuild)
    page = SimpleNamespace(services=[], route="/", update=lambda: None)
    dashboard_page_module._open_renew_dialog(page, state)
    picker = page.services[0]
    monkeypatch.setattr(
        picker,
        "pick_files",
        lambda **_kwargs: asyncio.sleep(0, result=[]),
    )
    button = next(
        item
        for item in _walk(page.dialog)
        if getattr(item, "key", None) == "dashboard.import-manual-notes"
    )

    asyncio.run(button.on_click(SimpleNamespace()))

    assert rebuild_states == ["running", "terminal"]
    assert state.current_activity is None
    assert state.recent_activity[-1].status == "success"
    assert "No local file selected." in " ".join(_texts(page.dialog))


def test_jobs_refresh_does_not_render_secret_bearing_exception(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "jobs.jsonl")
    state = _state()

    def fail_refresh():
        raise RuntimeError("password=raw-jobs-secret")

    monkeypatch.setattr(state.application_api, "recover_expired_leases", fail_refresh)
    control = jobs_page_module.jobs_page(SimpleNamespace(update=lambda: None), state)
    visible = " ".join(_texts(control))

    assert "raw-jobs-secret" not in visible
    assert "RuntimeError" in visible


def test_forecast_service_emits_model_steps_at_execution_boundaries(monkeypatch) -> None:
    snapshot = _snapshot()
    prices = snapshot.prices.copy()
    prices["date"] = services_module.pd.to_datetime(prices["date"])
    as_of = prices["date"].max().date()
    etf_id = str(prices.iloc[0]["etf_id"])
    observed: list[str] = []
    service = ForecastService(snapshot.config)

    monkeypatch.setattr(services_module, "baseline_forecast", lambda *_args, **_kwargs: observed.append("baseline-call") or [])
    monkeypatch.setattr(service, "_run_timesfm_forecasts", lambda *_args: observed.append("timesfm-call") or [])
    monkeypatch.setattr(service, "_run_toto_forecasts", lambda *_args: observed.append("toto-call") or [])
    monkeypatch.setattr(services_module, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_write_forecasts", lambda *_args, **_kwargs: None)

    service.run_forecasts(
        as_of,
        [etf_id],
        prices,
        progress_callback=lambda stage, _completed, _total: observed.append(stage),
    )

    assert observed == [
        "Running baseline forecasts",
        "baseline-call",
        "Checking cached TimesFM forecasts",
        "timesfm-call",
        "Checking cached Toto forecasts",
        "toto-call",
        "Writing forecast outputs",
    ]


def test_cancel_guard_blocks_real_price_and_forecast_write_boundaries(tmp_path, monkeypatch) -> None:
    snapshot = _snapshot()
    service = services_module.DataService(snapshot.config)
    provider_result = SimpleNamespace(ok=True, data=snapshot.prices.copy(), message="prices fetched")
    provider = SimpleNamespace(fetch_prices=lambda *_args: provider_result)
    monkeypatch.setattr(services_module.YFinanceProvider, "from_config", staticmethod(lambda _config: provider))
    monkeypatch.setattr(services_module, "validate_prices", lambda *_args, **_kwargs: SimpleNamespace(issues=[]))
    price_commit_called = False

    def commit_prices(_result):
        nonlocal price_commit_called
        price_commit_called = True

    monkeypatch.setattr(services_module, "commit_price_import", commit_prices)

    def cancelled() -> None:
        raise WorkflowTransitionError("cancelled before publication")

    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        service.refresh_yfinance_data(include_reference_data=False, publish_guard=cancelled)
    assert price_commit_called is False

    output = tmp_path / "forecast.csv"
    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        ForecastService(snapshot.config)._write_forecasts([], date(2026, 8, 9), output_path=output, publish_guard=cancelled)
    assert not output.exists()


def test_cancellation_after_service_commit_blocks_snapshot_derived_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    derived_writes: list[int] = []
    snapshot = state.snapshot

    class CancellingService:
        last_operation_succeeded = True

        def __init__(self, _config) -> None:
            pass

        def refresh_yfinance_data(self, **_kwargs) -> str:
            action_id = state.current_activity.action_id
            state.cancel_activity(expected_action_id=action_id)
            return "Prices committed before cancellation."

    def guarded_snapshot(*, force_sample=False, publish_guard=None):
        monkeypatch.setattr(services_module, "ensure_run_manifest", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(services_module, "write_features", lambda _features: derived_writes.append(1))
        services_module.FeatureService(snapshot.config).compute_features(
            snapshot.data_report.as_of_date,
            snapshot.prices,
            publish_guard=publish_guard,
        )
        return snapshot

    monkeypatch.setattr(app_state_module, "DataService", CancellingService)
    monkeypatch.setattr(app_state_module, "build_snapshot", guarded_snapshot)

    with pytest.raises(WorkflowTransitionError):
        state.refresh_yfinance_data()

    assert derived_writes == []
    assert state.recent_activity[-1].status == "cancelled"


def test_cancel_guard_blocks_real_candidate_report_and_holdings_atomic_group(tmp_path, monkeypatch) -> None:
    snapshot = _snapshot()
    candidates = services_module.pd.DataFrame({"instrument_id": ["VWCE"], "yahoo_symbol": ["VWCE.DE"]})
    prices = services_module.pd.DataFrame({"date": ["2026-08-08"], "etf_id": ["VWCE"], "adjusted_close": [100.0]})
    candidate_data = candidate_analysis_module.CandidatePriceData(candidates, prices, date(2026, 8, 8), "fixture")
    monkeypatch.setattr(candidate_analysis_module, "fetch_candidate_prices", lambda *_args, **_kwargs: candidate_data)
    monkeypatch.setattr(candidate_analysis_module, "fetch_candidate_fundamentals", lambda *_args: services_module.pd.DataFrame())
    monkeypatch.setattr(candidate_analysis_module, "analyse_candidate_prices", lambda *_args, **_kwargs: services_module.pd.DataFrame({"instrument_id": ["VWCE"]}))
    monkeypatch.setattr(candidate_analysis_module, "REPORTS_DIR", tmp_path / "reports")

    def cancelled() -> None:
        raise WorkflowTransitionError("cancelled before publication")

    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        candidate_analysis_module.refresh_candidate_analysis(snapshot.config, publish_guard=cancelled)
    assert not (tmp_path / "reports").exists()

    source = tmp_path / "holdings.csv"
    services_module.pd.DataFrame({"security": ["Issuer"], "ticker": ["ISS"], "weight": [1.0]}).to_csv(source, index=False)
    holdings_destination = tmp_path / "holdings.parquet"
    registry_destination = tmp_path / "documents.parquet"
    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        fund_holdings_module.import_etf_holdings_with_document(
            source,
            "VWCE",
            "2026-08-08",
            holdings_destination=holdings_destination,
            registry_destination=registry_destination,
            today="2026-08-09",
            publish_guard=cancelled,
        )
    assert not holdings_destination.exists()
    assert not registry_destination.exists()

    disclosure_source = tmp_path / "factsheet.pdf"
    disclosure_source.write_bytes(b"issuer disclosure")
    monkeypatch.setattr(trust_evidence_module, "RAW_DIR", tmp_path / "raw")
    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        trust_evidence_module._retain_picker_source(disclosure_source, "factsheets", publish_guard=cancelled)
    assert not (tmp_path / "raw").exists()


def test_holdings_publication_scope_serialises_cancellation_and_rejects_later_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Import ETF holdings", "Publishing holdings").action_id
    source = tmp_path / "holdings.csv"
    services_module.pd.DataFrame({"security": ["Issuer"], "ticker": ["ISS"], "weight": [1.0]}).to_csv(source, index=False)
    write_entered = threading.Event()
    release_write = threading.Event()
    cancellation_returned = threading.Event()
    writes: list[int] = []
    worker_errors: list[Exception] = []

    def blocking_atomic_write(_requests) -> None:
        writes.append(1)
        write_entered.set()
        assert release_write.wait(2)

    monkeypatch.setattr(fund_holdings_module, "atomic_write_group", blocking_atomic_write)

    def publish_holdings(capture_error: bool = True) -> None:
        try:
            fund_holdings_module.import_etf_holdings_with_document(
                source,
                "VWCE",
                "2026-08-08",
                holdings_destination=tmp_path / "holdings.parquet",
                registry_destination=tmp_path / "documents.parquet",
                today="2026-08-09",
                publish_guard=lambda: state.activity_publication(action_id),
            )
        except Exception as exc:
            if not capture_error:
                raise
            worker_errors.append(exc)

    worker = threading.Thread(target=publish_holdings)
    worker.start()
    assert write_entered.wait(2)

    def cancel() -> None:
        state.cancel_activity(expected_action_id=action_id)
        cancellation_returned.set()

    canceller = threading.Thread(target=cancel)
    canceller.start()
    assert not cancellation_returned.wait(0.1)
    release_write.set()
    worker.join(timeout=2)
    assert cancellation_returned.wait(2)
    canceller.join(timeout=2)
    assert not worker_errors
    assert writes == [1]

    with pytest.raises(WorkflowTransitionError):
        publish_holdings(False)
    assert writes == [1]
    state.release_activity(action_id)


def test_esef_normal_unavailable_result_is_failed_terminal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    source = tmp_path / "report.zip"
    source.write_bytes(b"not an ESEF package")
    monkeypatch.setattr(app_state_module, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(
        app_state_module,
        "parse_esef_package",
        lambda _path: ParseResult((), (ParseWarning("invalid_package", "invalid", "error"),), "esef", "1", "unused", False),
    )
    state = _state()
    action_id = state.begin_activity("Import ESEF package", "Reading package").action_id
    with state.share_activity(action_id), pytest.raises(ActivityUnavailableError) as raised:
        state.import_esef_package(source)
    state.fail_activity("Import ESEF package", raised.value, expected_action_id=action_id)

    assert state.recent_activity[-1].status == "failed"
    assert "unavailable" in state.recent_activity[-1].message.lower()


@pytest.mark.parametrize(
    ("label", "result"),
    [
        ("ETF report import", SimpleNamespace(extraction_status="parse_failed")),
        ("PRIIPs KID import", SimpleNamespace(success=False)),
        ("Methodology import", SimpleNamespace(status="unavailable")),
    ],
)
def test_disclosure_unavailable_results_raise_before_success_terminal(label, result, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity(label, "Persisting retained unavailable evidence").action_id
    with pytest.raises(ActivityUnavailableError, match="unavailable") as raised:
        trust_evidence_module._require_disclosure_available(label, result)
    state.fail_activity(label, raised.value, expected_action_id=action_id)

    assert state.recent_activity[-1].status == "failed"
    assert state.recent_activity[-1].step == "Failed"
    assert not any(entry.status == "success" for entry in state.recent_activity)


def test_yfinance_reference_failure_redacts_secret_and_cancellation_is_not_swallowed(monkeypatch) -> None:
    snapshot = _snapshot()
    price_result = SimpleNamespace(ok=True, data=snapshot.prices.copy(), message="prices fetched")
    reference_result = SimpleNamespace(ok=True, data=services_module.pd.DataFrame({"instrument_id": ["VWCE"]}), message="reference fetched")
    provider = SimpleNamespace(
        fetch_prices=lambda *_args: price_result,
        fetch_etf_metadata=lambda *_args: reference_result,
        fetch_etf_holdings=lambda *_args: SimpleNamespace(ok=False, data=None, message="api_key=raw-reference-secret"),
    )
    monkeypatch.setattr(services_module.YFinanceProvider, "from_config", staticmethod(lambda _config: provider))
    monkeypatch.setattr(services_module, "validate_prices", lambda *_args, **_kwargs: SimpleNamespace(issues=[]))
    monkeypatch.setattr(services_module, "commit_price_import", lambda _result: SimpleNamespace(rows=1, clean_path="prices", previous_snapshot_path=None))
    monkeypatch.setattr(services_module.DataService, "_reference_context", lambda _self: {"known_etfs": [], "isin_to_etf_id": {}, "ticker_to_etf_id": {}})
    monkeypatch.setattr(services_module, "commit_reference_import", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("token=raw-provider-secret")))

    message = services_module.DataService(snapshot.config).refresh_yfinance_data()
    assert "raw-provider-secret" not in message
    assert "raw-reference-secret" not in message
    assert "***redacted***" in message
    assert "ValueError" in message

    scope_calls = 0

    def cancelled_scope():
        nonlocal scope_calls
        scope_calls += 1
        if scope_calls == 1:
            return nullcontext()
        raise WorkflowTransitionError("cancelled")

    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        services_module.DataService(snapshot.config).refresh_yfinance_data(publish_guard=cancelled_scope)


@pytest.mark.parametrize("page_kind", ["import_export", "chatgpt_audit"])
def test_non_dashboard_terminal_rebuilds_shell_and_redacts_secret(page_kind, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / f"{page_kind}.jsonl")
    state = _state()
    page = SimpleNamespace(route="/", views=[], services=[], overlay=[], update=lambda: None)
    rebuilt: list[str] = []
    monkeypatch.setattr("etf_cockpit.app.router.render_shell", lambda _page, _state, route: rebuilt.append(route))

    if page_kind == "import_export":
        monkeypatch.setattr(
            import_export_page_module,
            "export_table",
            lambda category, frame, destination: SimpleNamespace(
                ok=False,
                destination=destination,
                error="api_key=raw-export-secret",
                rows=0,
            ),
        )
        control = import_export_page_module.import_export_page(page, state)
        button = next(item for item in _walk(control) if getattr(item, "key", None) == "import-export.export-scoreboard")
    else:
        class FailingBridge:
            def __init__(self, _config) -> None:
                pass

            def import_audit_json(self, _path):
                raise ValueError("token=raw-audit-secret")

        monkeypatch.setattr(chatgpt_audit_module, "ChatGPTBridge", FailingBridge)
        monkeypatch.setattr(chatgpt_audit_module, "_thesis_diary_text", lambda: "No persisted diary entries.")
        control = chatgpt_audit_module.chatgpt_audit_page(page, state)
        button = next(item for item in _walk(control) if getattr(item, "key", None) == "chatgpt.import-audit")

    button.on_click(SimpleNamespace())

    visible = " ".join(_texts(control))
    assert "raw-export-secret" not in visible
    assert "raw-audit-secret" not in visible
    assert "***redacted***" in visible
    assert state.recent_activity[-1].status == "failed"
    assert rebuilt == ["/"]


def test_restart_recovers_interrupted_workflow_step_without_activity_events(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    controller = WorkflowController()
    action_id = controller.start("Refresh sample data", "Refresh sample data")
    controller.step(action_id, WorkflowStep("sample_prices", "Writing sample prices", 1, 3))

    recovered = _read_recent_activity()

    assert len(recovered) == 1
    assert recovered[0].action_id == action_id
    assert recovered[0].status == "interrupted"
    assert recovered[0].step == "sample_prices"
    assert recovered[0].completed_units == 1
    assert recovered[0].total_units == 3
    assert recovered[0].started_at
    assert _read_recent_activity()[0].action_id == action_id
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert sum(row["event_type"] == "activity_interrupted" for row in rows) == 1


@pytest.mark.parametrize("terminal", ["success", "failed", "cancelled"])
def test_restart_recovers_canonical_workflow_terminal_without_activity_terminal(
    terminal, tmp_path, monkeypatch
) -> None:
    log_path = tmp_path / f"{terminal}.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    controller = WorkflowController()
    action_id = controller.start("Canonical action", "Canonical action")
    controller.step(action_id, WorkflowStep("publish", "Publishing output", 2, 2))
    if terminal == "success":
        controller.finish(action_id, WorkflowStatus.SUCCESS, "Output ready.", (tmp_path / "output.csv",))
    elif terminal == "failed":
        controller.fail(action_id, ValueError("token=restart-secret"), retryable=False)
    else:
        controller.cancel(action_id, "Cancelled at publication boundary.")

    recovered = _read_recent_activity()

    assert len(recovered) == 1
    assert recovered[0].action_id == action_id
    assert recovered[0].status == terminal
    assert recovered[0].started_at
    assert recovered[0].finished_at
    assert recovered[0].completed_units == 2
    assert recovered[0].total_units == 2
    if terminal == "success":
        assert recovered[0].message == "Output ready."
        assert recovered[0].output_path == str(tmp_path / "output.csv")
    elif terminal == "failed":
        assert "restart-secret" not in recovered[0].message
        assert recovered[0].error == recovered[0].message
    else:
        assert recovered[0].message == "Cancelled at publication boundary."
        assert recovered[0].error is None


def test_sample_publication_scope_serialises_cancel_and_rejects_clean_store_write(tmp_path, monkeypatch) -> None:
    state = _state()
    action_id = state.begin_activity("Refresh sample data", "Publishing sample files").action_id
    raw_dir = tmp_path / "raw"
    portfolios_dir = tmp_path / "portfolios"
    raw_dir.joinpath("prices").mkdir(parents=True)
    portfolios_dir.mkdir(parents=True)
    monkeypatch.setattr(sample_data_module, "RAW_DIR", raw_dir)
    monkeypatch.setattr(sample_data_module, "PORTFOLIOS_DIR", portfolios_dir)
    monkeypatch.setattr(duckdb_store_module, "PRICE_PARQUET", tmp_path / "clean" / "prices.parquet")
    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    worker_errors: list[Exception] = []
    writes: list[str] = []
    original_to_csv = services_module.pd.DataFrame.to_csv
    original_initialise = services_module.initialise_store

    def blocking_to_csv(frame, path, *args, **kwargs):
        writes.append(Path(path).name)
        if len(writes) == 1:
            entered.set()
            assert release.wait(2)
        return original_to_csv(frame, path, *args, **kwargs)

    def initialise_after_cancel(*args, **kwargs):
        assert cancelled.wait(2)
        return original_initialise(*args, **kwargs)

    monkeypatch.setattr(services_module.pd.DataFrame, "to_csv", blocking_to_csv)
    monkeypatch.setattr(services_module, "initialise_store", initialise_after_cancel)

    def run_update() -> None:
        try:
            services_module.DataService(state.snapshot.config).update_prices(
                force_sample=True,
                publish_guard=lambda: state.activity_publication(action_id),
            )
        except Exception as exc:
            worker_errors.append(exc)

    worker = threading.Thread(target=run_update)
    worker.start()
    assert entered.wait(2)
    canceller = threading.Thread(
        target=lambda: (state.cancel_activity(expected_action_id=action_id), cancelled.set())
    )
    canceller.start()
    assert not cancelled.wait(0.1)
    release.set()
    assert cancelled.wait(2)
    worker.join(timeout=2)
    canceller.join(timeout=2)

    assert writes == ["sample_prices.csv", "current_holdings.csv"]
    assert not (tmp_path / "clean" / "prices.parquet").exists()
    assert any(isinstance(exc, WorkflowTransitionError) for exc in worker_errors)
    state.release_activity(action_id)


def test_rollback_publication_scope_serialises_cancel_and_rejects_later_restore(tmp_path, monkeypatch) -> None:
    state = _state()
    action_id = state.begin_activity("Rollback prices", "Restoring prices").action_id
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    frame = services_module.pd.DataFrame({"date": ["2026-08-08"], "etf_id": ["VWCE"], "adjusted_close": [100.0]})
    snapshot_path = snapshots / "001_previous_prices.parquet"
    frame.to_parquet(snapshot_path, index=False)
    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    writes = 0
    original_write = import_pipeline_module._write_price_stores_atomically

    def blocking_write(*args, **kwargs):
        nonlocal writes
        writes += 1
        entered.set()
        assert release.wait(2)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(import_pipeline_module, "_write_price_stores_atomically", blocking_write)

    def restore() -> None:
        import_pipeline_module.rollback_latest_price_import(
            clean_path=tmp_path / "clean" / "prices.parquet",
            compatibility_path=tmp_path / "validated" / "prices.parquet",
            snapshots_dir=snapshots,
            publish_guard=lambda: state.activity_publication(action_id),
        )

    worker = threading.Thread(target=restore)
    worker.start()
    assert entered.wait(2)
    canceller = threading.Thread(
        target=lambda: (state.cancel_activity(expected_action_id=action_id), cancelled.set())
    )
    canceller.start()
    assert not cancelled.wait(0.1)
    release.set()
    worker.join(timeout=2)
    assert cancelled.wait(2)
    canceller.join(timeout=2)
    assert writes == 1
    with pytest.raises(WorkflowTransitionError):
        restore()
    assert writes == 1
    state.release_activity(action_id)


def test_api_status_publication_scope_serialises_cancel_and_redacts_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    section = state.snapshot.config.data_providers.section("prices")
    monkeypatch.setattr(section, "active_provider", "yfinance")
    price_result = SimpleNamespace(ok=True, data=state.snapshot.prices.copy(), message="prices fetched")
    unavailable = SimpleNamespace(ok=False, data=None, message="unavailable")
    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    worker_errors: list[Exception] = []

    def fetch_reference_after_cancel(*_args):
        assert cancelled.wait(2)
        return unavailable

    provider = SimpleNamespace(
        fetch_prices=lambda *_args: price_result,
        fetch_etf_metadata=fetch_reference_after_cancel,
        fetch_etf_holdings=lambda *_args: unavailable,
    )
    monkeypatch.setattr(services_module.YFinanceProvider, "from_config", staticmethod(lambda _config: provider))
    monkeypatch.setattr(services_module, "validate_prices", lambda *_args, **_kwargs: SimpleNamespace(issues=[]))

    def guarded_snapshot(*, force_sample=False, publish_guard=None):
        with publish_guard():
            return state.snapshot

    monkeypatch.setattr(app_state_module, "build_snapshot", guarded_snapshot)

    def blocking_commit(_result):
        entered.set()
        assert release.wait(2)
        return SimpleNamespace(rows=1, clean_path="prices", previous_snapshot_path=None)

    monkeypatch.setattr(services_module, "commit_price_import", blocking_commit)

    def run_status() -> None:
        try:
            state.renew_data_api_status()
        except Exception as exc:
            worker_errors.append(exc)

    worker = threading.Thread(target=run_status)
    worker.start()
    assert entered.wait(2)
    action_id = state.current_activity.action_id
    canceller = threading.Thread(
        target=lambda: (state.cancel_activity(expected_action_id=action_id), cancelled.set())
    )
    canceller.start()
    assert not cancelled.wait(0.1)
    release.set()
    assert cancelled.wait(2)
    worker.join(timeout=2)
    canceller.join(timeout=2)
    assert any(isinstance(exc, WorkflowTransitionError) for exc in worker_errors)
    assert state.recent_activity[-1].status == "cancelled"

    failed_provider = SimpleNamespace(
        fetch_prices=lambda *_args: SimpleNamespace(
            ok=False,
            data=None,
            message="Yahoo unavailable: api_key=raw-api-status-secret",
        )
    )
    monkeypatch.setattr(services_module.YFinanceProvider, "from_config", staticmethod(lambda _config: failed_provider))
    with pytest.raises(ActivityUnavailableError):
        state.renew_data_api_status()
    assert state.recent_activity[-1].status == "failed"
    assert "raw-api-status-secret" not in state.recent_activity[-1].message
    assert "***redacted***" in state.recent_activity[-1].message


def test_official_filing_catalog_maps_every_reachable_control() -> None:
    expected = {
        "sec_companyfacts_fetch": ("AppState.fetch_sec_companyfacts", "filings.fetch-sec"),
        "sec_companyfacts_import": ("AppState.import_sec_companyfacts", "filings.import-sec"),
        "esef_discovery": ("AppState.discover_esef_filings", "filings.discover-esef"),
        "esef_download": ("AppState.download_esef_package", "filings.download-esef"),
        "esef_import": ("AppState.import_esef_package", "filings.import-esef"),
        "oam_discovery": ("AppState.discover_oam", "filings.discover-oam"),
        "manual_official_filing_import": (
            "AppState.import_manual_official_filing",
            "filings.import-manual-official",
        ),
    }

    assert {
        key: (LONG_RUNNING_ACTION_SPECS[key].handler, LONG_RUNNING_ACTION_SPECS[key].control_key)
        for key in expected
    } == expected
    assert all(hasattr(AppState, handler.removeprefix("AppState.")) for handler, _key in expected.values())


def test_official_filing_helper_shares_owner_and_redacts_failed_terminal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "filings.jsonl")
    rebuilds: list[str] = []
    monkeypatch.setattr(
        trust_evidence_module,
        "_refresh_activity_shell",
        lambda _page, state: rebuilds.append(state.current_activity.status if state.current_activity else "terminal"),
    )
    page = SimpleNamespace(update=lambda: None)
    result = SimpleNamespace(value="")
    state = _state()
    observed: list[str] = []

    def successful_action(action_id):
        observed.append(state.assert_activity_publishable(action_id))
        state._record_activity_output("Official filing output published", tmp_path / "filing.parquet")
        return "Discovery complete."

    worker = trust_evidence_module._run_official_filing_action(
        page,
        state,
        result,
        "Discover official filings",
        "Querying official structured export",
        successful_action,
    )
    assert worker is not None
    worker.join(timeout=2)

    assert observed == [state.recent_activity[-1].action_id]
    assert state.recent_activity[-1].status == "success"
    assert state.recent_activity[-1].output_path == str(tmp_path / "filing.parquet")
    assert rebuilds == ["running", "running", "terminal"]

    failed_state = _state()
    failed_result = SimpleNamespace(value="")
    worker = trust_evidence_module._run_official_filing_action(
        page,
        failed_state,
        failed_result,
        "Fetch SEC companyfacts",
        "Fetching official company facts",
        lambda _action_id: (_ for _ in ()).throw(RuntimeError("api_key=raw-filing-secret")),
    )
    assert worker is not None
    worker.join(timeout=2)

    assert failed_state.recent_activity[-1].status == "failed"
    assert "raw-filing-secret" not in failed_result.value
    assert "***redacted***" in failed_result.value


def test_official_filing_visible_cancel_stops_late_publication(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "filing-cancel.jsonl")
    state = _state()
    page = SimpleNamespace(views=[], route="/missing", width=1200, update=lambda: None)
    result = SimpleNamespace(value="")
    fetched = threading.Event()
    release = threading.Event()
    writes: list[str] = []

    def blocking_action(action_id: str) -> str:
        fetched.set()
        assert release.wait(2)
        with state.activity_publication(action_id):
            writes.append("published")
        return "Published."

    worker = trust_evidence_module._run_official_filing_action(
        page,
        state,
        result,
        "Download official filing",
        "Fetching filing",
        blocking_action,
    )
    assert worker is not None and fetched.wait(2)
    shell = router_module.build_shell(page, state, "/missing")
    cancel = next(control for control in _walk(shell) if getattr(control, "key", None) == "activity.cancel")
    cancel.on_click(SimpleNamespace(control=cancel))
    release.set()
    worker.join(timeout=2)

    assert not writes
    assert state.recent_activity[-1].status == "cancelled"
    assert state.current_activity is None


@pytest.mark.parametrize(
    "control_key,method_name,file_name,payload",
    [
        ("filings.import-sec", "import_sec_companyfacts", "facts.json", b'{"cik": "1", "facts": {}}'),
        ("filings.import-esef", "import_esef_package", "filing.zip", b"PK-web-esef"),
        ("filings.import-manual-official", "import_manual_official_filing", "filing.pdf", b"web-manual"),
    ],
)
def test_official_picker_bytes_survive_delayed_background_worker(
    control_key, method_name, file_name, payload, monkeypatch
) -> None:
    selected = SimpleNamespace(path=None, bytes=payload, name=file_name)

    class Picker:
        async def pick_files(self, **_kwargs):
            return [selected]

    monkeypatch.setattr(trust_evidence_module, "_attach_picker", lambda *_args: Picker())
    monkeypatch.setattr(trust_evidence_module, "_refresh_activity_shell", lambda *_args: None)
    state = _state()
    entered = threading.Event()
    release = threading.Event()

    def delayed_import(path, **_kwargs):
        entered.set()
        assert release.wait(2)
        assert path.read_bytes() == payload
        return "Web upload imported."

    monkeypatch.setattr(state, method_name, delayed_import)
    page = SimpleNamespace(overlay=[], update=lambda: None)
    controls = trust_evidence_module._filing_import_controls(page, state)
    button = next(control for control in _walk(controls) if getattr(control, "key", None) == control_key)

    asyncio.run(button.on_click(SimpleNamespace(control=button)))
    assert entered.wait(2)
    release.set()
    for _ in range(100):
        if state.current_activity is None:
            break
        time.sleep(0.01)

    assert state.recent_activity[-1].status == "success"


@pytest.mark.parametrize(
    ("control_key", "file_name", "payload"),
    (
        ("etf-disclosures.import-document", "factsheet.pdf", b"browser factsheet"),
        (
            "etf-disclosures.import-holdings",
            "holdings.csv",
            b"security,ticker,weight,as_of\nIssuer,ISS,1.0,2026-08-09\n",
        ),
    ),
)
def test_disclosure_browser_picker_bytes_retain_registry_source_after_worker(
    control_key, file_name, payload, tmp_path, monkeypatch
) -> None:
    selected = SimpleNamespace(path=None, bytes=payload, name=file_name)

    class Picker:
        async def pick_files(self, **_kwargs):
            return [selected]

    monkeypatch.setattr(trust_evidence_module, "_attach_picker", lambda *_args: Picker())
    monkeypatch.setattr(trust_evidence_module, "_refresh_activity_shell", lambda *_args: None)
    monkeypatch.setattr(trust_evidence_module, "RAW_DIR", tmp_path / "raw")
    registry_path = tmp_path / "fund_documents.parquet"
    holdings_path = tmp_path / "fund_holdings.parquet"

    if control_key.endswith("document"):
        import_document = trust_evidence_module.import_etf_document

        def import_document_with_destination(path, **kwargs):
            return import_document(path, destination=registry_path, **kwargs)

        monkeypatch.setattr(trust_evidence_module, "import_etf_document", import_document_with_destination)
        document_type = "factsheet"
    else:
        import_holdings = trust_evidence_module.import_etf_holdings_with_document

        def import_holdings_with_destinations(path, *args, **kwargs):
            valid_args = (*args[:2], "issuer", *args[3:])
            return import_holdings(
                path,
                *valid_args,
                holdings_destination=holdings_path,
                registry_destination=registry_path,
                **kwargs,
            )

        monkeypatch.setattr(trust_evidence_module, "import_etf_holdings_with_document", import_holdings_with_destinations)
        document_type = "holdings"

    state = _state()
    page = SimpleNamespace(overlay=[], update=lambda: None)
    controls = trust_evidence_module._disclosure_import_controls(page, state)
    button = next(control for control in _walk(controls) if getattr(control, "key", None) == control_key)

    asyncio.run(button.on_click(SimpleNamespace(control=button)))
    deadline = time.time() + 2
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.01)

    assert state.recent_activity[-1].status == "success", state.last_message
    registry = trust_evidence_module.read_document_registry(path=registry_path)
    registered = registry.loc[
        registry["document_type"].astype(str).eq(document_type)
        & registry["coverage_status"].astype(str).eq("available")
    ]
    assert len(registered) == 1
    source_path = Path(str(registered.iloc[0]["path"]))
    assert source_path.is_file()
    assert source_path.read_bytes() == payload

    if document_type == "holdings":
        stored = services_module.pd.read_parquet(holdings_path)
        bound = stored.loc[stored["document_source_id"].astype(str).eq(str(registered.iloc[0]["source_id"]))]
        assert not bound.empty


@pytest.mark.parametrize("category", ["holdings", "kid"])
def test_disclosure_picker_cancel_before_publication_is_terminal(category, monkeypatch) -> None:
    selected = SimpleNamespace(path=None, bytes=b"browser upload", name="upload.pdf" if category == "kid" else "upload.csv")

    class Picker:
        async def pick_files(self, **_kwargs):
            return [selected]

    monkeypatch.setattr(trust_evidence_module, "_attach_picker", lambda *_args: Picker())
    monkeypatch.setattr(trust_evidence_module, "_refresh_activity_shell", lambda *_args: None)
    state = _state()
    page = SimpleNamespace(overlay=[], update=lambda: None)
    entered = threading.Event()
    release = threading.Event()
    writes: list[str] = []

    if category == "holdings":
        def import_holdings(_path, *_args, **kwargs):
            entered.set()
            assert release.wait(2)
            with kwargs["publish_guard"]():
                writes.append("holdings")
            return SimpleNamespace(completeness="complete", freshness="current", confidence=1.0)

        monkeypatch.setattr(trust_evidence_module, "import_etf_holdings_with_document", import_holdings)
        control_key = "etf-disclosures.import-holdings"
    else:
        def retain(_path, _subdirectory, *, publish_guard):
            entered.set()
            assert release.wait(2)
            with publish_guard():
                writes.append("kid")
            return _path

        monkeypatch.setattr(trust_evidence_module, "_retain_picker_source", retain)
        control_key = "etf-disclosures.import-kid"

    controls = trust_evidence_module._disclosure_import_controls(page, state)
    button = next(control for control in _walk(controls) if getattr(control, "key", None) == control_key)
    asyncio.run(button.on_click(SimpleNamespace(control=button)))
    assert entered.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    for _ in range(100):
        if state.current_activity is None:
            break
        time.sleep(0.01)

    assert not writes
    assert state.recent_activity[-1].status == "cancelled"
    assert state.last_message == state.recent_activity[-1].message


def test_cancel_after_final_publication_restores_canonical_message(monkeypatch) -> None:
    monkeypatch.setattr(trust_evidence_module, "_refresh_activity_shell", lambda *_args: None)
    state = _state()
    page = SimpleNamespace(update=lambda: None)
    result = SimpleNamespace(value="")
    published = threading.Event()
    release = threading.Event()

    def action(action_id):
        with state.activity_publication(action_id):
            published.set()
        assert release.wait(2)
        state.last_message = "late success must not remain visible"
        return "late success must not remain visible"

    worker = trust_evidence_module._run_official_filing_action(
        page, state, result, "Fetch SEC companyfacts", "Publishing", action
    )
    assert worker is not None and published.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    worker.join(timeout=2)

    assert state.last_message == "Cancelled by user"
    assert result.value == "Cancelled by user"
    assert state.recent_activity[-1].status == "cancelled"


def test_official_filing_retry_reenters_background_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust_evidence_module, "_refresh_activity_shell", lambda *_args: None)
    monkeypatch.setattr(router_module, "render_shell", lambda *_args, **_kwargs: None)
    state = _state()
    state.error_store = ErrorStore(tmp_path / "errors.jsonl")
    page = SimpleNamespace(update=lambda: None)
    result = SimpleNamespace(value="")
    attempts = 0

    def action(_action_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("SEC provider timeout")
        return "SEC retry complete."

    worker = trust_evidence_module._run_official_filing_action(
        page, state, result, "Fetch SEC companyfacts", "Fetching", action
    )
    assert worker is not None
    worker.join(timeout=2)
    error = state.error_store.recent()[0]
    errors_recovery_module._retry(SimpleNamespace(), state, error.error_id)
    for _ in range(100):
        if attempts == 2 and state.current_activity is None and result.value == "SEC retry complete.":
            break
        time.sleep(0.01)

    assert attempts == 2
    assert [entry.status for entry in state.recent_activity[-2:]] == ["failed", "success"]
    assert result.value == "SEC retry complete."


def test_esef_discovery_cancel_does_not_publish_in_memory_success(tmp_path, monkeypatch) -> None:
    state = _state()
    state._esef_provider = "existing-provider"
    state._esef_filings = ("existing-filing",)
    entered = threading.Event()
    release = threading.Event()

    class Provider:
        def __init__(self, **_kwargs):
            pass

        def list_filings(self, _country, _limit):
            entered.set()
            assert release.wait(2)
            return SimpleNamespace(status="ok", message="ok", data=("new-filing",))

    monkeypatch.setattr(app_state_module, "FilingsXbrlOrgProvider", Provider)
    action_id = state.begin_activity("Discover ESEF filings", "Fetching").action_id
    errors: list[Exception] = []

    def discover():
        try:
            with state.share_activity(action_id):
                state.discover_esef_filings("NL", expected_action_id=action_id, cache_dir=tmp_path)
        except Exception as exc:
            errors.append(exc)
        finally:
            state.restore_cancelled_activity_message(action_id)
            state.release_activity(action_id)

    worker = threading.Thread(target=discover)
    worker.start()
    assert entered.wait(2)
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    worker.join(timeout=2)

    assert any(isinstance(exc, WorkflowTransitionError) for exc in errors)
    assert state._esef_provider == "existing-provider"
    assert state._esef_filings == ("existing-filing",)
    assert state.last_message == "Cancelled by user"


@pytest.mark.parametrize("label", ["Import PRIIPs KID", "Import index methodology"])
def test_disclosure_import_concurrent_loser_is_readably_blocked(label) -> None:
    state = _state()
    barrier = threading.Barrier(2)
    results = [SimpleNamespace(value=""), SimpleNamespace(value="")]
    action_ids: list[str | None] = []

    def start(result) -> None:
        barrier.wait()
        action_ids.append(trust_evidence_module._start_disclosure_import(state, result, label))

    workers = [threading.Thread(target=start, args=(result,)) for result in results]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)

    assert sum(action_id is not None for action_id in action_ids) == 1
    assert any("blocked:" in result.value and "already running" in result.value for result in results)
    state.cancel_activity(expected_action_id=state.current_activity.action_id)
    state.release_activity(state.current_activity.action_id)


def test_tracked_retry_reenters_canonical_wrapper(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    attempts = 0

    class RetryService:
        def __init__(self, _config):
            self.last_operation_succeeded = True

        def refresh_yfinance_data(self, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("provider timeout")
            return "Provider refresh complete."

    state = _state()
    state.error_store = ErrorStore(tmp_path / "errors.jsonl")
    monkeypatch.setattr(app_state_module, "DataService", RetryService)
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda **_kwargs: state.snapshot)
    monkeypatch.setattr(state, "_write_current_scoreboard", lambda: tmp_path / "scores.parquet")
    monkeypatch.setattr(router_module, "render_shell", lambda *_args, **_kwargs: None)

    with pytest.raises(TimeoutError):
        state.refresh_yfinance_data()
    first = state.error_store.recent()[0]
    errors_recovery_module._retry(SimpleNamespace(), state, first.error_id)

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert attempts == 2
    assert sum(row.get("event_type") == "workflow_start" for row in rows) == 2
    assert [entry.status for entry in state.recent_activity[-2:]] == ["failed", "success"]


@pytest.mark.parametrize("category", ["esef", "oam"])
def test_official_filing_normal_unavailable_result_is_failed_and_redacted(
    category, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / f"{category}.jsonl")
    monkeypatch.setattr(trust_evidence_module, "_refresh_activity_shell", lambda *_args: None)
    state = _state()
    page = SimpleNamespace(update=lambda: None)
    result_control = SimpleNamespace(value="")

    if category == "esef":
        class UnavailableProvider:
            def __init__(self, **_kwargs):
                pass

            def list_filings(self, _country, _limit):
                return SimpleNamespace(
                    status="unavailable",
                    message="token=raw-esef-secret",
                    data=None,
                )

        monkeypatch.setattr(app_state_module, "FilingsXbrlOrgProvider", UnavailableProvider)

        def action(_action_id):
            return state.discover_esef_filings("NL")

        label = "Discover ESEF filings"
    else:
        class UnavailableAdapter:
            def __init__(self, **_kwargs):
                pass

            def discover(self, _request):
                return SimpleNamespace(
                    status="unavailable",
                    message="api_key=raw-oam-secret",
                    provider_id="fixture",
                    records=(),
                    snapshot=None,
                    manual_fallback=True,
                    warnings=(),
                    coverage={},
                )

        observed_guards: list[object] = []
        monkeypatch.setattr(app_state_module, "oam_adapter_for_country", lambda _country: UnavailableAdapter)
        monkeypatch.setattr(
            app_state_module,
            "write_filing_coverage",
            lambda *_args, **kwargs: (
                observed_guards.append(kwargs.get("publish_guard"))
                or tmp_path / "coverage.parquet"
            ),
        )
        def action(action_id):
            return state.discover_oam(
                "FR",
                publish_guard=lambda: state.activity_publication(action_id),
            )

        label = "Discover official filings"

    worker = trust_evidence_module._run_official_filing_action(
        page,
        state,
        result_control,
        label,
        "Querying official filing source",
        action,
    )
    assert worker is not None
    worker.join(timeout=2)

    assert state.recent_activity[-1].status == "failed"
    assert "raw-esef-secret" not in result_control.value
    assert "raw-oam-secret" not in result_control.value
    assert "***redacted***" in result_control.value
    if category == "oam":
        assert observed_guards and observed_guards[0] is not None


def test_sec_companyfacts_publication_scope_serialises_cancellation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    monkeypatch.setattr(app_state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(app_state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    payload = tmp_path / "facts.json"
    payload.write_text(
        json.dumps({"cik": 1, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 1}]}}}}}),
        encoding="utf-8",
    )
    state = _state()
    action_id = state.begin_activity("Import SEC companyfacts", "Publishing statement evidence").action_id
    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    writes = 0
    worker_errors: list[Exception] = []

    def blocking_write(*_args, **_kwargs):
        nonlocal writes
        writes += 1
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(app_state_module, "write_statement_evidence", blocking_write)
    original_record_output = state._record_activity_output

    def record_after_cancel(step, path):
        assert cancelled.wait(2)
        return original_record_output(step, path)

    monkeypatch.setattr(state, "_record_activity_output", record_after_cancel)

    def import_facts() -> None:
        try:
            with state.share_activity(action_id):
                state.import_sec_companyfacts(
                    payload,
                    publish_guard=lambda: state.activity_publication(action_id),
                )
        except Exception as exc:
            worker_errors.append(exc)

    worker = threading.Thread(target=import_facts)
    worker.start()
    assert entered.wait(2)
    canceller = threading.Thread(
        target=lambda: (state.cancel_activity(expected_action_id=action_id), cancelled.set())
    )
    canceller.start()
    assert not cancelled.wait(0.1)
    release.set()
    worker.join(timeout=2)
    assert cancelled.wait(2)
    canceller.join(timeout=2)

    assert writes == 1
    assert any(isinstance(exc, WorkflowTransitionError) for exc in worker_errors)
    assert state.recent_activity[-1].status == "cancelled"
    state.release_activity(action_id)


@pytest.mark.parametrize("category", ["sec_fetch", "esef_download", "oam_discovery", "manual_import"])
def test_official_filing_provider_write_rejects_cancellation_before_publication(
    category, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / f"{category}.jsonl")
    state = _state()
    action_id = state.begin_activity(category, "Waiting to publish official filing").action_id

    if category == "sec_fetch":
        payload = json.dumps({"cik": "0000789019", "facts": {}}).encode()

        def transport(_url, _headers):
            state.cancel_activity(expected_action_id=action_id)
            return payload

        def operation():
            return SecEdgarProvider(
                "ETF AI Cockpit research research@company.org",
                cache_dir=tmp_path / "sec",
                transport=transport,
            ).fetch_companyfacts(
                "789019",
                publish_guard=lambda: state.activity_publication(action_id),
            )

        output_root = tmp_path / "sec"
    elif category == "esef_download":
        def transport(_url, _headers):
            state.cancel_activity(expected_action_id=action_id)
            return b"PK-official"

        def operation():
            return FilingsXbrlOrgProvider(
                cache_dir=tmp_path / "esef",
                transport=transport,
            ).download_report_package(
                "filing-1",
                "https://filings.xbrl.org/filing-1.xbri",
                publish_guard=lambda: state.activity_publication(action_id),
            )

        output_root = tmp_path / "esef"
    elif category == "oam_discovery":
        payload = b'{"records": []}'

        def transport(_url, _headers):
            state.cancel_activity(expected_action_id=action_id)
            return payload, 200, {"content-type": "application/json"}

        def operation():
            return FranceDilaOamAdapter(
                cache_dir=tmp_path / "oam",
                endpoint="https://www.data.gouv.fr/api/financial-information",
                transport=transport,
                enabled=True,
                publish_guard=lambda: state.activity_publication(action_id),
            ).discover(OAMDiscoveryRequest(isin="FR0000000001"))

        output_root = tmp_path / "oam"
    else:
        source = tmp_path / "filing.pdf"
        source.write_bytes(b"official filing")
        state.cancel_activity(expected_action_id=action_id)
        def operation():
            return archive_manual_official_filing(
                source,
                jurisdiction="GB",
                instrument_id="VWCE",
                source_url="https://find-and-update.company-information.service.gov.uk/company/1",
                raw_dir=tmp_path / "manual",
                queue_path=tmp_path / "manual.parquet",
                publish_guard=lambda: state.activity_publication(action_id),
            )

        output_root = tmp_path / "manual"

    with pytest.raises(WorkflowTransitionError):
        operation()
    assert not output_root.exists()
    state.release_activity(action_id)
