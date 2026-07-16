from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import pytest


def _records_module():
    from etf_cockpit.release import verification_records

    return verification_records


def _key(module, *, commit: str = "commit-a", executable_hash: str = "exe-a", command: str = "pytest tests -q"):
    return module.ReleaseRecordKey(
        commit=commit,
        executable_hash=executable_hash,
        environment_hash="env-a",
        command=command,
    )


def test_document_edits_do_not_change_executable_hash(tmp_path: Path) -> None:
    module = _records_module()
    executable = tmp_path / "ETF_AI_Cockpit.exe"
    executable.write_bytes(b"portable-executable")
    before = module.compute_executable_hash(executable)
    (tmp_path / "plan.md").write_text("first", encoding="utf-8")
    (tmp_path / "plan.md").write_text("edited evidence narrative", encoding="utf-8")
    assert module.compute_executable_hash(executable) == before


def test_evidence_only_edits_reuse_the_implementation_record(tmp_path: Path) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    calls: list[str] = []

    def run() -> dict[str, object]:
        calls.append("run")
        return {"status": "pass", "evidence_state": "final"}

    (tmp_path / "plan.md").write_text("first", encoding="utf-8")
    first = ledger.get_or_run(_key(module), gate="tests", issue_id="ISSUE-A", runner=run)
    (tmp_path / "plan.md").write_text("edited evidence narrative", encoding="utf-8")
    second = ledger.get_or_run(_key(module), gate="tests", issue_id="ISSUE-B", runner=run)

    assert calls == ["run"]
    assert first.record_id == second.record_id


def test_two_issues_reuse_one_passing_shared_full_suite(tmp_path: Path) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    calls = 0

    def run() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"status": "pass", "evidence_hash": "e" * 64}

    first = ledger.get_or_run(_key(module), gate="tests", issue_id="ISSUE-A", runner=run)
    second = ledger.get_or_run(_key(module), gate="tests", issue_id="ISSUE-B", runner=run)
    assert calls == 1
    assert first.record_id == second.record_id
    assert set(second.issue_ids) == {"ISSUE-A", "ISSUE-B"}


def test_concurrent_controllers_execute_one_shared_command(tmp_path: Path) -> None:
    module = _records_module()
    ledger_path = tmp_path / "records.json"
    calls: list[str] = []

    def run() -> dict[str, object]:
        calls.append("run")
        return {"status": "pass", "evidence_state": "final"}

    def worker(issue_id: str):
        ledger = module.VerificationRecordLedger(ledger_path)
        return ledger.get_or_run(_key(module), gate="tests", issue_id=issue_id, runner=run)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(worker, ("ISSUE-A", "ISSUE-B"))

    assert calls == ["run"]
    assert first.record_id == second.record_id
    saved = module.VerificationRecordLedger(ledger_path).record(first.record_id)
    assert set(saved.issue_ids) == {"ISSUE-A", "ISSUE-B"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process-liveness regression")
def test_windows_pid_liveness_probe_does_not_terminate_child() -> None:
    module = _records_module()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert module._pid_is_alive(child.pid) is True
        assert child.poll() is None
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


def test_runner_exception_is_durable_and_never_retried(tmp_path: Path) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    calls: list[str] = []

    def run() -> dict[str, object]:
        calls.append("run")
        raise RuntimeError("simulated command interruption")

    first = ledger.get_or_run(_key(module), gate="tests", issue_id="ISSUE-A", runner=run)
    second = ledger.get_or_run(_key(module), gate="tests", issue_id="ISSUE-B", runner=run)

    assert calls == ["run"]
    assert first.status == "blocked"
    assert second.status == "blocked"
    assert "runner_exception" in str(second.metadata)


def test_dead_lock_is_recovered_without_redispatch(tmp_path: Path) -> None:
    module = _records_module()
    ledger_path = tmp_path / "records.json"
    initial = module.VerificationRecordLedger(ledger_path)
    initial.get_or_run(
        _key(module),
        gate="tests",
        issue_id="ISSUE-A",
        runner=lambda: {"status": "pass", "evidence_state": "final"},
    )
    lock_path = ledger_path.with_name(".records.json.lock")
    lock_path.write_text("pid=2147483647\n", encoding="ascii")
    resumed = module.VerificationRecordLedger(ledger_path)
    reused = resumed.get_or_run(
        _key(module),
        gate="tests",
        issue_id="ISSUE-B",
        runner=lambda: pytest.fail("stale lock recovery must not rerun"),
    )
    assert reused.status == "pass"


def test_two_issues_reuse_one_build_package_record(tmp_path: Path) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    calls = 0

    def build() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"status": "pass", "executable_hash": "x" * 64}

    first = ledger.get_or_run(_key(module, command="cmd.exe /d /c scripts\\build_windows.bat"), gate="build", issue_id="ISSUE-A", runner=build)
    second = ledger.get_or_run(_key(module, command="cmd.exe /d /c scripts\\build_windows.bat"), gate="build", issue_id="ISSUE-B", runner=build)
    assert calls == 1
    assert first.record_id == second.record_id


def test_identical_build_command_executes_once(tmp_path: Path) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    calls = []
    def runner() -> dict[str, object]:
        calls.append("build")
        return {"status": "pass"}
    ledger.get_or_run(_key(module, command="cmd.exe /d /c scripts\\build_windows.bat"), gate="build", issue_id="ISSUE-A", runner=runner)
    ledger.get_or_run(_key(module, command="cmd.exe /d /c scripts\\build_windows.bat"), gate="build", issue_id="ISSUE-A", runner=runner)
    assert calls == ["build"]


def test_verifier_reuses_shared_full_suite_without_rerunning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    ledger.get_or_run(_key(module), gate="tests", issue_id="ISSUE-A", runner=lambda: {"status": "pass"})
    monkeypatch.setattr(module, "run_verification_command", lambda *_args, **_kwargs: pytest.fail("duplicate full suite"))
    reused = module.reuse_gate_record(ledger, _key(module), gate="tests", issue_id="ISSUE-B")
    assert reused is not None
    assert reused.status == "pass"


def test_staged_evidence_cannot_satisfy_final_closure() -> None:
    module = _records_module()
    assert module.evidence_state_allows_closure("staged") is False
    assert module.evidence_state_allows_closure("final") is True


def test_source_change_invalidates_focused_shared_record(tmp_path: Path) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    first = ledger.get_or_run(_key(module, commit="commit-a"), gate="tests", issue_id="ISSUE-A", runner=lambda: {"status": "pass"})
    second = ledger.get_or_run(_key(module, commit="commit-b"), gate="tests", issue_id="ISSUE-B", runner=lambda: {"status": "pass"})
    assert first.record_id != second.record_id


def test_manifest_plan_worklog_issue_edits_do_not_invalidate_executable_verification(tmp_path: Path) -> None:
    module = _records_module()
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"same-binary")
    before = module.compute_executable_hash(executable)
    for name in ("manifest.json", "plan.md", "worklog.md", "issues.md"):
        (tmp_path / name).write_text(json.dumps({"edited": True}), encoding="utf-8")
    assert module.compute_executable_hash(executable) == before


def test_one_review_approval_is_referenced_by_both_issues(tmp_path: Path) -> None:
    module = _records_module()
    ledger = module.VerificationRecordLedger(tmp_path / "records.json")
    record = ledger.get_or_run(_key(module), gate="review", issue_id="ISSUE-A", runner=lambda: {"status": "pass"})
    ledger.attach_review(record.record_id, "review-123")
    ledger.attach_issue(record.record_id, "ISSUE-B")
    saved = ledger.record(record.record_id)
    assert saved.review_id == "review-123"
    assert set(saved.issue_ids) == {"ISSUE-A", "ISSUE-B"}


def test_resumed_controller_uses_committed_checkpoint_without_redispatch(tmp_path: Path) -> None:
    module = _records_module()
    checkpoint = tmp_path / "RUN_STATE.json"
    checkpoint.write_text(json.dumps({"status": "committed", "next_task": "Task 16", "dispatch_id": "dispatch-1"}), encoding="utf-8")
    state = module.load_resume_checkpoint(checkpoint)
    assert state.status == "committed"
    assert state.next_action == "Task 16"
    assert state.redispatch_required is False


def test_resumed_controller_reads_repository_run_state_checkpoint() -> None:
    module = _records_module()
    state = module.load_resume_checkpoint(Path(__file__).parents[2] / "RUN_STATE.json")
    assert state.status == "committed"
    assert state.next_action
    assert state.redispatch_required is False


def test_issue_verifier_rejects_staged_manifest(tmp_path: Path) -> None:
    from scripts.verify_issue import verify_issue

    manifest = {
        "schema_version": "1.0",
        "issue_id": "DATA-05",
        "requirement_version": "2",
        "source_hash": "a" * 64,
        "environment_hash": "b" * 64,
        "generated_at": "2026-07-16T00:00:00Z",
        "evidence_state": "staged",
        "runs": [],
        "review": {"builder": "builder", "independent_reviewer": "reviewer", "review_result": "approved"},
    }
    target = tmp_path / "DATA-05" / "verification_manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_issue(
        "DATA-05",
        source_hash="a" * 64,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
    )

    assert result.status == "blocked"
    assert any("staged" in limitation.lower() for limitation in result.limitations)
