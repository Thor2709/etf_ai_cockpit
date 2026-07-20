from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from etf_cockpit.core.job_scheduler import (
    DurableJobScheduler,
    JobGraphError,
    JobSpec,
    JobStateError,
    JobStatus,
)
from etf_cockpit.core.resource_profiles import HardwareSnapshot, ResourcePolicy
from etf_cockpit.data.local_storage import storage_layout


def _dag() -> tuple[JobSpec, ...]:
    return (
        JobSpec("download", "Download", {"source": "local"}),
        JobSpec("score", "Score", {"formula": "v3"}, dependencies=("download",), max_retries=1),
        JobSpec("publish", "Publish", dependencies=("score",)),
    )


def test_submit_persists_dag_and_duplicate_submission_is_idempotent(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    first = scheduler.submit("refresh", "Refresh", _dag(), input_payload={"date": "2026-07-17"}, dedupe_key="refresh:2026-07-17")
    second = scheduler.submit("refresh", "Refresh again", _dag(), input_payload={"date": "2026-07-17"}, dedupe_key="refresh:2026-07-17")

    assert second.workflow_id == first.workflow_id
    assert {job.job_key for job in scheduler.list_jobs(first.workflow_id)} == {"download", "score", "publish"}
    assert scheduler.dependency_graph(first.workflow_id) == {"download": (), "score": ("download",), "publish": ("score",)}
    assert scheduler.verify_event_chain(first.workflow_id)


def test_dag_execution_gates_dependencies_and_blocks_downstream_failure(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="worker")
    workflow = scheduler.submit("refresh", "Refresh", _dag())

    download = scheduler.claim_next()
    assert download is not None and download.job_key == "download"
    scheduler.complete(download.job_id, {"path": "prices.parquet"})
    score = scheduler.claim_next()
    assert score is not None and score.job_key == "score"
    scheduler.fail(score.job_id, RuntimeError("bad input"), retryable=False)

    publish = scheduler.get_job(f"{workflow.workflow_id}:publish")
    assert publish is not None and publish.status is JobStatus.BLOCKED
    assert scheduler.get_workflow(workflow.workflow_id).status is JobStatus.FAILED
    assert publish.outputs == []


def test_retry_checkpoint_and_restart_recovery(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="worker-a", lease_seconds=1)
    workflow = scheduler.submit("forecast", "Forecast", (JobSpec("run", "Run", max_retries=2),))
    job = scheduler.claim_next()
    assert job is not None
    scheduler.checkpoint(job.job_id, {"completed": 3, "total": 5})
    scheduler.fail(job.job_id, TimeoutError("temporary"), retryable=True)
    retried = scheduler.get_job(job.job_id)
    assert retried is not None and retried.status is JobStatus.QUEUED and retried.retry_count == 1

    restarted = DurableJobScheduler(tmp_path, worker_id="worker-b")
    claimed = restarted.claim_next()
    assert claimed is not None and claimed.job_id == job.job_id
    with sqlite3.connect(storage_layout(tmp_path).transactional_path) as connection:
        expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="milliseconds")
        connection.execute("UPDATE durable_jobs SET lease_expires_at = ? WHERE job_id = ?", (expired, job.job_id))
    recovered = restarted.recover_expired_leases()
    assert recovered[0].status is JobStatus.QUEUED
    assert restarted.get_job(job.job_id).checkpoint == {"completed": 3, "total": 5}
    assert restarted.get_workflow(workflow.workflow_id).status is JobStatus.QUEUED


def test_cancellation_is_terminal_and_running_worker_cannot_publish(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="worker")
    workflow = scheduler.submit("import", "Import", (JobSpec("load", "Load"),))
    job = scheduler.claim_next()
    assert job is not None
    cancelled = scheduler.cancel(workflow.workflow_id)
    assert cancelled[0].status is JobStatus.CANCELLED
    with pytest.raises(JobStateError):
        scheduler.complete(job.job_id, {"partial": True})


def test_invalid_graph_and_unbounded_payloads_fail_closed(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    with pytest.raises(JobGraphError):
        scheduler.submit("cycle", "Cycle", (JobSpec("a", "A", dependencies=("b",)), JobSpec("b", "B", dependencies=("a",))))
    with pytest.raises(ValueError, match="exceeds"):
        scheduler.submit("large", "Large", (JobSpec("a", "A", input_payload="x" * 20_000),))


def test_event_payloads_redact_secrets_and_bound_outputs(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="worker")
    workflow = scheduler.submit("secret", "Secret", (JobSpec("a", "A", {"token": "api_key=hidden"}),))
    job = scheduler.claim_next()
    assert job is not None
    scheduler.complete(job.job_id, ["api_key=hidden", "second"])
    events = scheduler.list_events(workflow.workflow_id)
    assert all("hidden" not in str(event.payload) for event in events)
    assert scheduler.get_job(job.job_id).outputs[0] == "api_key=***redacted***"


def test_resource_policy_blocks_oversized_job_before_handler_claim(tmp_path) -> None:
    snapshot = HardwareSnapshot("test", 1, 1_024, 512, 1_000, False, "cpu-only")
    policy = ResourcePolicy(snapshot=snapshot)
    scheduler = DurableJobScheduler(tmp_path, resource_policy=policy)
    workflow = scheduler.submit("training", "Training", (JobSpec("run", "Run", resources={"memory_mb": 2_048, "disk_mb": 2_000}),))

    assert scheduler.claim_next() is None
    job = scheduler.get_job(f"{workflow.workflow_id}:run")
    assert job is not None and job.status is JobStatus.BLOCKED
    assert "exceeds" in job.error_message
    assert scheduler.get_workflow(workflow.workflow_id).status is JobStatus.BLOCKED
    assert any(event.event_type == "job_blocked_resource_limit" for event in scheduler.list_events(workflow.workflow_id))


def test_corrupt_resource_declaration_is_durably_blocked(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    workflow = scheduler.submit("local_check", "Local check", (JobSpec("run", "Run"),))
    with sqlite3.connect(storage_layout(tmp_path).transactional_path) as connection:
        connection.execute("UPDATE durable_jobs SET resource_json = ? WHERE job_id = ?", ("{not-json", f"{workflow.workflow_id}:run"))

    assert scheduler.claim_next() is None
    job = scheduler.get_job(f"{workflow.workflow_id}:run")
    assert job is not None and job.status is JobStatus.BLOCKED
    assert "corrupt" in job.error_message
    assert any(event.event_type == "job_blocked_resource_limit" for event in scheduler.list_events(workflow.workflow_id))


def test_scheduler_adds_bounded_profile_defaults_to_undeclared_jobs(tmp_path) -> None:
    snapshot = HardwareSnapshot("test", 2, 4_096, 3_000, 20_000, False, "cpu-only")
    scheduler = DurableJobScheduler(
        tmp_path,
        resource_policy=ResourcePolicy(requested_profile="recommended", snapshot=snapshot),
    )

    workflow = scheduler.submit("local_check", "Local check", (JobSpec("run", "Run"),))
    job = scheduler.get_job(f"{workflow.workflow_id}:run")

    assert job is not None
    assert job.resources == {
        "cpu": 2.0,
        "disk_mb": 1_024,
        "memory_mb": 768,
        "profile": "recommended",
    }
    assert scheduler.claim_next() is not None


def test_scheduler_persists_near_limit_resource_warning(tmp_path) -> None:
    snapshot = HardwareSnapshot("test", 1, 2_048, 2_000, 10_000, False, "cpu-only")
    scheduler = DurableJobScheduler(
        tmp_path,
        resource_policy=ResourcePolicy(requested_profile="minimum", snapshot=snapshot),
    )
    workflow = scheduler.submit(
        "local_check",
        "Local check",
        (JobSpec("run", "Run", resources={"memory_mb": 700}),),
    )

    assert scheduler.claim_next() is not None
    warnings = [
        event
        for event in scheduler.list_events(workflow.workflow_id)
        if event.event_type == "job_resource_warning"
    ]
    assert len(warnings) == 1
    assert "80%" in str(warnings[0].payload)


def test_scheduler_rejects_concurrency_above_profile_budget(tmp_path) -> None:
    snapshot = HardwareSnapshot("test", 8, 32_768, 30_000, 100_000, False, "cpu-only")
    policy = ResourcePolicy(requested_profile="minimum", snapshot=snapshot)

    with pytest.raises(ValueError, match="max_concurrency 2 exceeds profile limit 1"):
        DurableJobScheduler(tmp_path, resource_policy=policy, max_concurrency=2)


def test_scheduler_reserves_aggregate_memory_until_running_job_finishes(tmp_path) -> None:
    snapshot = HardwareSnapshot("test", 8, 32_768, 30_000, 100_000, False, "cpu-only")
    policy = ResourcePolicy(requested_profile="high", snapshot=snapshot)
    scheduler = DurableJobScheduler(
        tmp_path,
        worker_id="worker",
        resource_policy=policy,
        max_concurrency=4,
    )
    workflow = scheduler.submit(
        "parallel",
        "Parallel jobs",
        (
            JobSpec("a", "A", resources={"cpu": 1, "memory_mb": 4_000, "disk_mb": 1_000}),
            JobSpec("b", "B", resources={"cpu": 1, "memory_mb": 4_000, "disk_mb": 1_000}),
        ),
    )

    first = scheduler.claim_next()
    assert first is not None and first.job_key == "a"
    assert scheduler.claim_next() is None
    assert scheduler.claim_next() is None
    waiting = scheduler.get_job(f"{workflow.workflow_id}:b")
    assert waiting is not None and waiting.status is JobStatus.QUEUED
    wait_events = [
        event
        for event in scheduler.list_events(workflow.workflow_id)
        if event.event_type == "job_resource_wait"
    ]
    assert len(wait_events) == 1
    assert "aggregate" in str(wait_events[0].payload).casefold()

    scheduler.complete(first.job_id, {"released": True})
    second = scheduler.claim_next()
    assert second is not None and second.job_key == "b"
