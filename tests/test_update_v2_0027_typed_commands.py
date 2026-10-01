from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
import time
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import state as state_module
from etf_cockpit.app.router import build_shell
from etf_cockpit.app.state import AppState
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import (
    ApiStatus,
    DashboardActionCommand,
    SubmitWorkflowCommand,
)
from etf_cockpit.services import build_snapshot


@lru_cache(maxsize=1)
def _snapshot():
    return build_snapshot()


class _Page:
    route = "/"
    width = 1400

    def __init__(self) -> None:
        self.services: list[object] = []
        self.overlay: list[object] = []
        self.views: list[object] = []
        self.dialog = None

    def update(self) -> None:
        return None


def _walk(control: ft.Control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    for child in getattr(control, "actions", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _controls_by_key(view: ft.Control) -> dict[str, list[ft.Control]]:
    controls: dict[str, list[ft.Control]] = {}
    for control in _walk(view):
        key = getattr(control, "key", None)
        if key:
            controls.setdefault(str(key), []).append(control)
    return controls


def _new_state(monkeypatch, tmp_path: Path) -> AppState:
    monkeypatch.setattr(state_module, "ROOT", tmp_path)
    monkeypatch.setattr(state_module, "ACTIVITY_LOG_PATH", tmp_path / "activity.jsonl")
    snapshot = _snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.error_store.path = tmp_path / "errors.jsonl"
    return state


def _wait_for_activity(state: AppState) -> None:
    deadline = time.monotonic() + 10
    while state.current_activity is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state.current_activity is None


_ACTION_CASES = [
    pytest.param("dashboard.refresh-yfinance", "refresh_yfinance_data", "main", None, "path", id="refresh-yfinance"),
    pytest.param("dashboard.run-algorithms", "run_algorithm_scores", "main", None, "path", id="run-algorithms"),
    pytest.param("dashboard.run-forecasting-models", "run_forecasting_models", "main", None, "path", id="run-forecasts"),
    pytest.param("dashboard.renew-api-status", "renew_data_api_status", "dialog", None, "path", id="provider-status"),
    pytest.param("dashboard.renew-dry-run", "renew_data_dry_run", "dialog", None, "path", id="renew-dry-run"),
    pytest.param("dashboard.renew-rollback", "rollback_latest_prices", "dialog", None, "path", id="rollback-prices"),
    pytest.param("dashboard.export-audit", "export_audit_packet", "main", None, "path", id="export-audit"),
    pytest.param("dashboard.import-prices", "validate_local_import", "dialog", "prices", "path", id="import-prices"),
    pytest.param("dashboard.import-manual-notes", "import_local_upload", "dialog", "manual_news", "upload", id="import-notes"),
    pytest.param("dashboard.import-etf-factsheets", "validate_local_import", "dialog", "etf_metadata", "path", id="import-factsheets"),
    pytest.param("dashboard.import-etf-holdings", "validate_local_import", "dialog", "etf_holdings", "path", id="import-holdings"),
    pytest.param("dashboard.import-fx-rates", "validate_local_import", "dialog", "fx", "path", id="import-fx"),
]


def _click_action(page, state, control_key, location, monkeypatch, tmp_path, file_mode):
    event = SimpleNamespace(page=page)
    dashboard = build_shell(page, state, "/")
    controls = _controls_by_key(dashboard)
    if location == "dialog":
        controls["dashboard.renew-import"][0].on_click(event)
        controls = _controls_by_key(page.dialog)
    if file_mode == "upload":
        async def pick_files(_picker, **_kwargs):
            return [SimpleNamespace(path=None, bytes=b"selected bytes", name="manual.csv")]

        monkeypatch.setattr(ft.FilePicker, "pick_files", pick_files)
    elif control_key.startswith("dashboard.import-"):
        async def pick_files(_picker, **_kwargs):
            return [
                SimpleNamespace(
                    path=str(tmp_path / "selected.csv"),
                    bytes=b"unused bytes",
                    name="selected.csv",
                )
            ]

        monkeypatch.setattr(ft.FilePicker, "pick_files", pick_files)
    callback = controls[control_key][0].on_click
    result = callback(event)
    if asyncio.iscoroutine(result):
        asyncio.run(result)


@pytest.mark.parametrize("control_key,action,location,dataset_type,file_mode", _ACTION_CASES)
def test_dashboard_actions_execute_typed_commands_and_finish_with_handler_message(
    monkeypatch,
    tmp_path,
    control_key,
    action,
    location,
    dataset_type,
    file_mode,
) -> None:
    state = _new_state(monkeypatch, tmp_path)
    page = _Page()
    method_calls: list[tuple[object, ...]] = []
    commands: list[DashboardActionCommand] = []
    results = []
    message = f"{action} completed successfully."
    output_path = tmp_path / "audit-packet.zip"

    def method(*args):
        method_calls.append(args)
        return output_path if action == "export_audit_packet" else message

    monkeypatch.setattr(state, action, method)
    execute = state.application_api.execute

    def capture(command):
        assert isinstance(command, DashboardActionCommand)
        commands.append(command)
        result = execute(command)
        results.append(result)
        return result

    monkeypatch.setattr(state.application_api, "execute", capture)
    _click_action(page, state, control_key, location, monkeypatch, tmp_path, file_mode)
    _wait_for_activity(state)

    assert len(commands) == 1
    assert commands[0].action == action
    assert commands[0].idempotency_key.startswith("dashboard-")
    assert results[0].status is ApiStatus.ACCEPTED
    assert len(method_calls) == 1
    if dataset_type is not None:
        assert commands[0].dataset_type == dataset_type
    if action == "validate_local_import":
        assert commands[0].selected_path == str(tmp_path / "selected.csv")
        assert method_calls[0] == (str(tmp_path / "selected.csv"), dataset_type)
    elif action == "import_local_upload":
        assert commands[0].file_name == "manual.csv"
        assert commands[0].content == b"selected bytes"
        assert method_calls[0] == ("manual.csv", b"selected bytes", dataset_type)
    assert state.recent_activity[-1].status == "success"
    expected_message = f"Audit packet exported: {output_path}" if action == "export_audit_packet" else message
    assert state.recent_activity[-1].message == expected_message


@pytest.mark.parametrize("control_key,action,location,dataset_type,file_mode", _ACTION_CASES)
def test_dashboard_action_failures_return_command_errors_and_visible_failed_activity(
    monkeypatch,
    tmp_path,
    control_key,
    action,
    location,
    dataset_type,
    file_mode,
) -> None:
    state = _new_state(monkeypatch, tmp_path)
    page = _Page()
    commands: list[DashboardActionCommand] = []
    results = []
    error_message = f"RuntimeError: {action} failed in its AppState method"

    def fail(*_args):
        raise RuntimeError(f"{action} failed in its AppState method")

    monkeypatch.setattr(state, action, fail)
    execute = state.application_api.execute

    def capture(command):
        assert isinstance(command, DashboardActionCommand)
        commands.append(command)
        result = execute(command)
        results.append(result)
        return result

    monkeypatch.setattr(state.application_api, "execute", capture)
    _click_action(page, state, control_key, location, monkeypatch, tmp_path, file_mode)
    _wait_for_activity(state)

    assert len(commands) == 1
    assert commands[0].action == action
    assert results[0].status is ApiStatus.FAILED
    assert error_message in (results[0].error_message or "")
    assert state.recent_activity[-1].status == "failed"
    assert error_message in state.recent_activity[-1].message


def test_replayed_dashboard_action_returns_stored_result_without_running_handler_twice(
    monkeypatch, tmp_path
) -> None:
    state = _new_state(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(state, "run_algorithm_scores", lambda: calls.append("called") or "Scores complete.")
    command = DashboardActionCommand(
        idempotency_key="dashboard-replay-key",
        action="run_algorithm_scores",
    )

    first = state.application_api.execute(command)
    second = state.application_api.execute(command)

    assert first.status is ApiStatus.ACCEPTED
    assert second.status is ApiStatus.REPLAYED
    assert second.replayed is True
    assert second.command_id == first.command_id
    assert dict(second.details)["message"] == "Scores complete."
    assert calls == ["called"]


def test_retry_click_uses_a_fresh_dashboard_idempotency_key(monkeypatch, tmp_path) -> None:
    state = _new_state(monkeypatch, tmp_path)
    page = _Page()
    dashboard = build_shell(page, state, "/")
    controls = _controls_by_key(dashboard)
    commands: list[DashboardActionCommand] = []
    execute = state.application_api.execute
    attempts = 0

    def capture(command):
        assert isinstance(command, DashboardActionCommand)
        commands.append(command)
        return execute(command)

    def run_algorithms():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary algorithm timeout")
        return "Retry completed."

    monkeypatch.setattr(state, "run_algorithm_scores", run_algorithms)
    monkeypatch.setattr(state.application_api, "execute", capture)
    controls["dashboard.run-algorithms"][0].on_click(SimpleNamespace(page=page))
    _wait_for_activity(state)
    first_activity = state.recent_activity[-1]
    assert first_activity.status == "failed"

    errors = state.error_store.recent(100)
    assert errors
    assert state.error_store.retry_request(errors[0].error_id) == "Retry started."
    _wait_for_activity(state)

    assert attempts == 2
    assert len(commands) == 2
    assert commands[0].idempotency_key != commands[1].idempotency_key
    assert state.recent_activity[-1].status == "success"
    assert state.recent_activity[-1].message == "Retry completed."


def test_submit_workflow_still_uses_scheduler_not_dashboard_handler(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.operations import build_operation_preview

    dashboard_handler_calls: list[object] = []
    api = LocalApplicationApi(
        lambda: SimpleNamespace(universe_revision="revision-1"),
        root=tmp_path,
        command_handlers={
            "dashboard_action": lambda command: dashboard_handler_calls.append(command)
            or {"message": "unexpected dashboard dispatch"}
        },
    )
    submit = api._scheduler.submit
    scheduled = []

    def capture_submit(*args, **kwargs):
        workflow = submit(*args, **kwargs)
        scheduled.append(workflow)
        return workflow

    monkeypatch.setattr(api._scheduler, "submit", capture_submit)
    preview = build_operation_preview(environment="paper", instrument_id="ETF1", quantity=1)
    result = api.execute(
        SubmitWorkflowCommand(
            idempotency_key="paper-preview-scheduler",
            workflow_type="paper_proposal_preview",
            label="Preview",
            input_payload=preview.to_payload(),
            job_keys=("preview",),
        )
    )

    assert result.status is ApiStatus.ACCEPTED
    assert scheduled
    assert dashboard_handler_calls == []
