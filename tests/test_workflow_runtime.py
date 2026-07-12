from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.app.pages.dashboard import _action_bar, _activity_panel
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot
from etf_cockpit.core import session_log
from etf_cockpit.core import workflow as workflow_module
from etf_cockpit.core.workflow import (
    WorkflowController,
    WorkflowStatus,
    WorkflowStep,
    WorkflowTransitionError,
)


def _control_texts(control: object) -> list[str]:
    texts: list[str] = []
    value = getattr(control, "value", None)
    if value is not None:
        texts.append(str(value))
    for attribute in ("controls", "content"):
        child = getattr(control, attribute, None)
        children = child if isinstance(child, (list, tuple)) else (child,) if child is not None else ()
        for item in children:
            texts.extend(_control_texts(item))
    return texts


def _walk_controls(control: object):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)


def test_workflow_logs_start_before_steps_and_persists_result(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    controller = WorkflowController(tmp_path / "workflow.jsonl", event_logger=events.append)

    action_id = controller.start("refresh_yfinance", "Refresh yfinance data")
    controller.step(action_id, WorkflowStep("download", "Download prices", 1, 2))
    result = controller.finish(action_id, WorkflowStatus.SUCCESS, "Prices refreshed", [tmp_path / "prices.parquet"])

    assert result.status is WorkflowStatus.SUCCESS
    assert result.action_id == action_id
    assert events[0]["status"] == "running"
    assert events[0]["action_id"] == action_id
    records = [json.loads(line) for line in (tmp_path / "workflow.jsonl").read_text().splitlines()]
    assert [record["event"] for record in records] == ["start", "step", "finish"]
    assert records[-1]["status"] == "success"


def test_default_workflow_lifecycle_uses_session_trace_without_secondary_log(tmp_path: Path, monkeypatch) -> None:
    session_path = tmp_path / "logs" / "session.jsonl"
    secondary_path = tmp_path / "logs" / "workflow.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", session_path)
    monkeypatch.setattr(workflow_module, "LOG_DIR", tmp_path / "logs", raising=False)
    controller = WorkflowController()

    action_id = controller.start("refresh_yfinance", "Refresh yfinance data")
    controller.step(action_id, WorkflowStep("download", "Download prices", 1, 2))
    controller.finish(action_id, WorkflowStatus.SUCCESS, "Prices refreshed", ())

    events = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event_type"] for event in events] == ["workflow_start", "workflow_step", "workflow_finish"]
    assert [event["action_id"] for event in events] == [action_id, action_id, action_id]
    assert not secondary_path.exists()


def test_activity_panel_names_the_session_trace() -> None:
    state = type("ActivityState", (), {"current_activity": None, "last_message": "Ready", "recent_activity": []})()

    texts = _control_texts(_activity_panel(state))

    assert any("logs/session.jsonl" in text for text in texts)
    assert all("logs/activity_log.jsonl" not in text for text in texts)


def test_failed_workflow_cannot_be_marked_success(tmp_path: Path) -> None:
    controller = WorkflowController(tmp_path / "workflow.jsonl", event_logger=lambda _event: None)
    action_id = controller.start("import", "Import file")

    failed = controller.fail(action_id, RuntimeError("api_key=do-not-write-this"), retryable=False)

    assert failed.status is WorkflowStatus.FAILED
    assert failed.retryable is False
    assert failed.error_fingerprint
    assert "do-not-write-this" not in failed.message
    with pytest.raises(WorkflowTransitionError):
        controller.finish(action_id, WorkflowStatus.SUCCESS, "incorrect", ())


def test_workflow_redacts_json_string_secret_forms(tmp_path: Path) -> None:
    controller = WorkflowController(tmp_path / "workflow.jsonl", event_logger=lambda _event: None)
    action_id = controller.start("import", "Import file")

    controller.fail(
        action_id,
        RuntimeError('{"authorization":"Bearer raw-bearer","access_token":"raw-access"}'),
        retryable=False,
    )

    text = (tmp_path / "workflow.jsonl").read_text(encoding="utf-8")
    assert "raw-bearer" not in text
    assert "raw-access" not in text
    assert "Bearer ***redacted***" in text


def test_logging_failure_does_not_break_workflow(tmp_path: Path) -> None:
    def broken_logger(_event: dict[str, object]) -> None:
        raise OSError("log destination unavailable")

    controller = WorkflowController(tmp_path / "workflow.jsonl", event_logger=broken_logger)
    action_id = controller.start("models", "Run models")
    result = controller.finish(action_id, WorkflowStatus.UNAVAILABLE, "Models unavailable", ())

    assert action_id
    assert result.status is WorkflowStatus.UNAVAILABLE
    assert (tmp_path / "workflow.jsonl").exists()


def test_manual_review_and_retryable_failure_are_explicit(tmp_path: Path) -> None:
    controller = WorkflowController(tmp_path / "workflow.jsonl")
    manual_id = controller.start("filings", "Import filing")
    manual = controller.finish(manual_id, WorkflowStatus.MANUAL_REVIEW, "Identity needs review", ())
    retry_id = controller.start("provider", "Probe provider")
    retry = controller.fail(retry_id, TimeoutError("provider timeout"), retryable=True)

    assert manual.status is WorkflowStatus.MANUAL_REVIEW
    assert retry.status is WorkflowStatus.FAILED
    assert retry.retryable is True


def test_primary_dashboard_workflows_are_keyboard_operable_buttons() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {"route": "/", "width": 1400, "update": lambda _self: None})()
    controls = list(_walk_controls(_action_bar(page, state)))
    required = {
        "dashboard.refresh-yfinance",
        "dashboard.run-algorithms",
        "dashboard.run-forecasting-models",
        "dashboard.show-scores",
    }
    matched = {str(getattr(control, "key", "")): control for control in controls if getattr(control, "key", None)}
    assert required <= matched.keys()
    assert all(type(matched[key]).__name__ in {"FilledButton", "OutlinedButton", "TextButton", "ElevatedButton"} for key in required)
    assert all(callable(matched[key].on_click) for key in required)
