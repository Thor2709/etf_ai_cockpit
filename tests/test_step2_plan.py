from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot
from scripts.issue_registry_core import ready_records
from scripts import validate_app
from scripts.validate_app import run_validation
from etf_cockpit.core.workflow import (
    WorkflowController,
    WorkflowDuplicateError,
    WorkflowStatus,
)


ROOT = Path(__file__).resolve().parents[1]


def _registry() -> dict[str, object]:
    return json.loads((ROOT / "issues" / "issue_registry.json").read_text(encoding="utf-8"))


def _record(registry: dict[str, object], issue_id: str) -> dict[str, object]:
    return next(record for record in registry["records"] if record["canonical_id"] == issue_id)


def test_registry_separates_inputs_activation_and_reverse_downstream_links() -> None:
    registry = _registry()
    issue_0070 = _record(registry, "ISSUE-0070")
    issue_0106 = _record(registry, "ISSUE-0106")
    issue_0072 = _record(registry, "ISSUE-0072")
    issue_0073 = _record(registry, "ISSUE-0073")
    issue_0079 = _record(registry, "ISSUE-0079")

    assert issue_0070["blocking_dependencies"] == []
    assert _record(registry, "ISSUE-0070")["programme_status"] == "integrated"
    assert _record(registry, "ISSUE-0071")["programme_status"] == "integrated"
    assert issue_0072["programme_status"] == "integrated"
    assert issue_0073["programme_status"] == "integrated"
    assert "ISSUE-0072" not in {record["canonical_id"] for record in ready_records(registry)}
    assert "ISSUE-0073" not in {record["canonical_id"] for record in ready_records(registry)}
    assert "ISSUE-0071" not in {record["canonical_id"] for record in ready_records(registry)}
    assert issue_0070["required_inputs"] == ["ISSUE-0008", "ISSUE-0032", "ISSUE-0060", "ISSUE-0066"]
    assert "ISSUE-0071" in issue_0070["downstream_issues"]
    assert issue_0106["blocking_dependencies"] == ["ISSUE-0128"]
    assert "ISSUE-0038" in issue_0072["blocking_dependencies"]
    assert issue_0079["blocking_dependencies"] == ["ISSUE-0145", "ISSUE-0149"]


def test_ready_status_never_bypasses_unresolved_blockers() -> None:
    registry = _registry()
    records = {record["canonical_id"]: record for record in registry["records"]}
    records["ISSUE-0070"]["programme_status"] = "ready"
    records["ISSUE-0070"]["blocking_dependencies"] = ["ISSUE-0132"]

    ready_ids = {record["canonical_id"] for record in ready_records({"records": list(records.values())})}

    assert "ISSUE-0070" not in ready_ids


def test_validation_runner_writes_stable_json_and_markdown_reports(tmp_path: Path, monkeypatch) -> None:
    def passed_check(_root: Path, check: validate_app._Check) -> validate_app.CheckResult:
        return validate_app.CheckResult(
            name=check.name,
            command="test command",
            exit_code=0,
            duration_ms=1.0,
            status="passed",
            required=check.required,
            output="test output",
        )

    monkeypatch.setattr(validate_app, "_run_check", passed_check)
    result = run_validation(ROOT, mode="quick", report_root=tmp_path)

    assert result.exit_code == 0
    report_path = tmp_path / "latest" / "validation.json"
    markdown_path = tmp_path / "latest" / "validation.md"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert markdown_path.exists()
    assert payload["schema_version"] == "1.0"
    assert payload["mode"] == "quick"
    assert payload["checks"]
    assert {"name", "command", "exit_code", "duration_ms", "status"} <= set(payload["checks"][0])
    assert {"environment", "git", "failures", "unavailable_optional_components", "log_paths"} <= set(payload)
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "## Optional components unavailable" in markdown
    optional_section = markdown.split("## Optional components unavailable", 1)[1]
    if payload["unavailable_optional_components"]:
        assert "- None" not in optional_section
    else:
        assert "- None" in optional_section


def test_validation_runner_returns_nonzero_for_mandatory_failure(tmp_path: Path, monkeypatch) -> None:
    failure = validate_app._Check("mandatory_failure", (sys.executable, "-c", "raise SystemExit(3)"))
    monkeypatch.setattr(validate_app, "_checks_for_mode", lambda *_args: [failure])

    result = run_validation(ROOT, mode="quick", report_root=tmp_path)

    assert result.exit_code == 1
    assert result.report.failures == ["mandatory_failure: exit code 3"]
    assert result.report.checks[0]["status"] == "failed"


def test_app_state_cancellation_is_readable_and_durable(tmp_path: Path, monkeypatch) -> None:
    activity_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", activity_path)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    state.begin_activity("Cancellable workflow", "Starting")
    entry = state.cancel_activity()

    assert entry is not None
    assert entry.status == "cancelled"
    assert entry.step == "Cancelled"
    assert entry.message == "Cancelled by user"
    assert state.current_activity is None
    assert "activity_cancelled" in activity_path.read_text(encoding="utf-8")


def test_workflow_rejects_duplicate_active_commands_and_records_deduplication(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    controller = WorkflowController(tmp_path / "workflow.jsonl", event_logger=events.append)

    action_id = controller.start("refresh_yfinance", "Refresh yfinance", command_key="refresh", input_payload={"years": 5})
    with pytest.raises(WorkflowDuplicateError):
        controller.start("refresh_yfinance", "Refresh yfinance", command_key="refresh", input_payload={"years": 5})

    assert action_id
    assert events[0]["command_key"] == "refresh"
    assert events[0]["input_hash"]
    assert events[0]["deduplication_key"]


def test_workflow_cancellation_is_a_terminal_audited_state(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    controller = WorkflowController(tmp_path / "workflow.jsonl", event_logger=events.append)
    action_id = controller.start("forecast", "Run forecasts", command_key="forecast")

    result = controller.cancel(action_id, "Cancelled by user")

    assert result.status is WorkflowStatus.CANCELLED
    assert result.cancelled_at
    assert result.message == "Cancelled by user"
    assert events[-1]["status"] == "cancelled"
    assert events[-1]["cancel_requested"] is True
