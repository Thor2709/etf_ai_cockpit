"""Regression tests for bughunt issue #975 (durable job scheduler)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from etf_cockpit.core.job_scheduler import (
    DurableJobScheduler,
    JobGraphError,
    JobSchedulerError,
    JobSpec,
    JobStateError,
    JobStatus,
)
from etf_cockpit.core.resource_profiles import HardwareSnapshot, ResourcePolicy
from etf_cockpit.data.local_storage import storage_layout


def _expire_lease(root, job_id: str) -> None:
    with sqlite3.connect(storage_layout(root).transactional_path) as connection:
        expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="milliseconds")
        connection.execute("UPDATE durable_jobs SET lease_expires_at = ? WHERE job_id = ?", (expired, job_id))


def _big_policy() -> ResourcePolicy:
    snapshot = HardwareSnapshot("test", 8, 32_768, 30_000, 100_000, False, "cpu-only")
    return ResourcePolicy(requested_profile="high", snapshot=snapshot)


# D020-N001 -----------------------------------------------------------------------------------------------------------
def test_different_workflow_spec_with_same_input_is_not_deduped(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    first = scheduler.submit("refresh", "Refresh", (JobSpec("a", "A", {"x": 1}),), input_payload={"d": 1})
    second = scheduler.submit("refresh", "Refresh", (JobSpec("a", "A", {"x": 2}),), input_payload={"d": 1})
    third = scheduler.submit("refresh", "Refresh", (JobSpec("a", "A", {"x": 1}), JobSpec("b", "B")), input_payload={"d": 1})
    again = scheduler.submit("refresh", "Refresh", (JobSpec("a", "A", {"x": 1}),), input_payload={"d": 1})

    assert len({first.workflow_id, second.workflow_id, third.workflow_id}) == 3
    assert again.workflow_id == first.workflow_id


def test_explicit_dedupe_key_reused_for_a_different_spec_or_input_conflicts(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    first = scheduler.submit("refresh", "R", (JobSpec("a", "A"),), input_payload={"d": 1}, dedupe_key="k")
    assert scheduler.submit("refresh", "R again", (JobSpec("a", "A"),), input_payload={"d": 1}, dedupe_key="k").workflow_id == first.workflow_id
    with pytest.raises(JobSchedulerError, match="dedupe_key"):
        scheduler.submit("refresh", "R", (JobSpec("a", "A"), JobSpec("b", "B")), input_payload={"d": 1}, dedupe_key="k")
    with pytest.raises(JobSchedulerError, match="dedupe_key"):
        scheduler.submit("refresh", "R", (JobSpec("a", "A"),), input_payload={"d": 2}, dedupe_key="k")


# D020-N002 -----------------------------------------------------------------------------------------------------------
def test_claim_next_skips_aggregate_wait_head_and_claims_smaller_job(tmp_path, monkeypatch) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="w", resource_policy=_big_policy(), max_concurrency=4)
    wf = scheduler.submit(
        "parallel",
        "P",
        (
            JobSpec("a", "A", resources={"cpu": 1, "memory_mb": 4_000, "disk_mb": 1_000}),
            JobSpec("b", "B", resources={"cpu": 1, "memory_mb": 4_000, "disk_mb": 1_000}),
            JobSpec("c", "C", resources={"cpu": 1, "memory_mb": 100, "disk_mb": 100}),
        ),
    )
    assert scheduler.claim_next().job_key == "a"
    original = scheduler.resource_policy.evaluate

    def evaluate(resources):
        # Aggregate checks (profile key present) are blocked when the candidate reserves 4 GB: only the small job fits.
        if resources.get("profile") and float(resources.get("memory_mb", 0)) >= 8_000:
            from etf_cockpit.core.resource_profiles import ResourceDecision

            return ResourceDecision("blocked", "high", ("aggregate too large",))
        return original(resources)

    monkeypatch.setattr(scheduler.resource_policy, "evaluate", evaluate)
    claimed = scheduler.claim_next()
    assert claimed is not None and claimed.job_key == "c"
    b = scheduler.get_job(f"{wf.workflow_id}:b")
    assert b is not None and b.status is JobStatus.QUEUED


# D020-N003 -----------------------------------------------------------------------------------------------------------
def test_expired_lease_completion_by_the_old_handler_is_rejected(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="same-worker", lease_seconds=1)
    scheduler.submit("w", "W", (JobSpec("run", "Run", max_retries=2),))
    old = scheduler.claim_next()
    assert old is not None
    _expire_lease(tmp_path, old.job_id)
    assert scheduler.recover_expired_leases()[0].status is JobStatus.QUEUED
    new = scheduler.claim_next()
    assert new is not None and new.job_id == old.job_id
    assert new.retry_count != old.retry_count

    with pytest.raises(JobStateError, match="lease"):
        scheduler.complete(old.job_id, {"stale": True}, lease_generation=old.retry_count)
    with pytest.raises(JobStateError, match="lease"):
        scheduler.fail(old.job_id, "stale", lease_generation=old.retry_count)
    with pytest.raises(JobStateError, match="lease"):
        scheduler.heartbeat(old.job_id, lease_generation=old.retry_count)
    assert scheduler.get_job(old.job_id).status is JobStatus.RUNNING
    done = scheduler.complete(new.job_id, {"fresh": True}, lease_generation=new.retry_count)
    assert done.status is JobStatus.SUCCEEDED and done.outputs == {"fresh": True}


def test_run_once_old_handler_result_is_discarded_after_lease_recovery(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="same-worker", lease_seconds=1)
    wf = scheduler.submit("w", "W", (JobSpec("run", "Run", max_retries=2),))
    seen: list[int] = []

    def handler(context):
        _expire_lease(tmp_path, context.job_id)
        scheduler.recover_expired_leases()
        reclaimed = scheduler.claim_next()
        assert reclaimed is not None
        seen.append(reclaimed.retry_count)
        return {"from": "old-handler"}

    result = scheduler.run_once(handler)  # must not raise or publish
    assert result is not None and result.status is JobStatus.RUNNING and result.outputs == []
    assert seen == [1]
    assert scheduler.get_workflow(wf.workflow_id).status is JobStatus.RUNNING


# D020-N004 -----------------------------------------------------------------------------------------------------------
def test_cancel_between_check_and_complete_does_not_escape(tmp_path, monkeypatch) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="w")
    wf = scheduler.submit("w", "W", (JobSpec("run", "Run"),))
    real_complete = scheduler.complete

    def complete_after_cancel(job_id, outputs=None, **kwargs):
        # The cancel commits after run_once's cancellation check but before complete().
        scheduler.cancel(wf.workflow_id)
        return real_complete(job_id, outputs, **kwargs)

    monkeypatch.setattr(scheduler, "complete", complete_after_cancel)
    result = scheduler.run_once(lambda _context: {"late": True})
    assert result is not None and result.status is JobStatus.CANCELLED and result.outputs == []
    assert scheduler.get_workflow(wf.workflow_id).status is JobStatus.CANCELLED


def test_handler_error_after_concurrent_cancel_does_not_escape(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="w")
    wf = scheduler.submit("w", "W", (JobSpec("run", "Run"),))

    def handler(context):
        scheduler.cancel(wf.workflow_id)
        raise RuntimeError("boom")

    result = scheduler.run_once(handler)
    assert result is not None and result.status is JobStatus.CANCELLED


# D120-N001 / E.C4.S16.N001 -----------------------------------------------------------------------------------------
def _portfolio(last: str) -> dict[str, object]:
    return {"positions": [{"id": f"P{i}"} for i in range(100)] + [{"id": last}]}


def test_inputs_differing_only_after_the_100th_element_hash_differently(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    a = scheduler.submit("p", "P", (JobSpec("a", "A"),), input_payload=_portfolio("X"))
    b = scheduler.submit("p", "P", (JobSpec("a", "A"),), input_payload=_portfolio("Y"))
    assert a.input_hash != b.input_hash
    assert a.workflow_id != b.workflow_id
    marker = a.inputs["positions"][-1]
    assert marker["__truncated__"]["limit"] == 100 and marker["__truncated__"]["total"] == 101
    assert len(a.inputs["positions"]) == 101
    job_a = scheduler.get_job(f"{a.workflow_id}:a")
    assert job_a is not None


def test_job_level_inputs_and_dict_keys_beyond_limit_are_digested(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    one = {f"k{i:03d}": i for i in range(101)}
    two = {**one, "k100": -1}
    a = scheduler.submit("p", "P", (JobSpec("a", "A", one),))
    b = scheduler.submit("p", "P", (JobSpec("a", "A", two),))
    ja = scheduler.get_job(f"{a.workflow_id}:a")
    jb = scheduler.get_job(f"{b.workflow_id}:a")
    assert ja.input_hash != jb.input_hash
    assert "__truncated__" in ja.inputs


def test_truncation_marker_is_stable_when_payload_is_rebounded(tmp_path) -> None:
    from etf_cockpit.core.job_scheduler import _bounded_json

    import json

    once = json.loads(_bounded_json(list(range(150))))
    twice = json.loads(_bounded_json(once))
    assert once == twice and len(once) == 101


def test_sensitive_field_names_are_redacted_regardless_of_value(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    wf = scheduler.submit(
        "p",
        "P",
        (JobSpec("a", "A", {"password": "hunter2", "api_key": "abc123", "tokens_used": 5, "nested": {"Authorization": "xyz"}}),),
    )
    job = scheduler.get_job(f"{wf.workflow_id}:a")
    text = str(job.inputs) + str([event.payload for event in scheduler.list_events(wf.workflow_id)])
    for secret in ("hunter2", "abc123", "xyz"):
        assert secret not in text
    assert job.inputs["tokens_used"] == 5


# D120-N002 -----------------------------------------------------------------------------------------------------------
def test_workflow_stays_active_while_an_independent_sibling_is_unfinished(tmp_path) -> None:
    small = {"cpu": 1, "memory_mb": 100, "disk_mb": 100}
    scheduler = DurableJobScheduler(tmp_path, worker_id="w", resource_policy=_big_policy(), max_concurrency=2)
    wf = scheduler.submit("w", "W", (JobSpec("a", "A", resources=small), JobSpec("b", "B", resources=small)))
    first = scheduler.claim_next()
    second = scheduler.claim_next()
    assert first is not None and second is not None
    scheduler.fail(first.job_id, RuntimeError("bad"))
    assert scheduler.get_workflow(wf.workflow_id).status is JobStatus.RUNNING
    scheduler.complete(second.job_id, {"ok": True})
    assert scheduler.get_workflow(wf.workflow_id).status is JobStatus.FAILED


# D120-N003 / D.C2.S20.N001 -----------------------------------------------------------------------------------------
def test_list_of_dict_outputs_stay_json_objects(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path, worker_id="w")
    scheduler.submit("w", "W", (JobSpec("a", "A"),))
    job = scheduler.claim_next()
    done = scheduler.complete(job.job_id, [{"id": 1, "token": "api_key=hidden"}, "plain"])
    assert done.outputs[0]["id"] == 1 and isinstance(done.outputs[0], dict)
    assert "hidden" not in str(done.outputs)
    assert done.outputs[1] == "plain"


def test_generator_outputs_are_consumed_lazily_up_to_the_cap(tmp_path) -> None:
    consumed = 0

    def endless():
        nonlocal consumed
        while True:
            consumed += 1
            yield f"item-{consumed}"

    from etf_cockpit.core.job_scheduler import _safe_outputs

    safe = _safe_outputs(endless())
    assert consumed <= 101
    assert len(safe) == 101 and "__truncated__" in safe[-1]


# D120-N004 -----------------------------------------------------------------------------------------------------------
def test_event_logger_is_called_after_commit_and_not_on_rollback(tmp_path, monkeypatch) -> None:
    logged: list[dict[str, object]] = []
    scheduler = DurableJobScheduler(tmp_path, worker_id="w", event_logger=logged.append)
    wf = scheduler.submit("w", "W", (JobSpec("a", "A"),))
    assert [item["event_type"] for item in logged] == ["workflow_queued", "job_queued"]
    job = scheduler.claim_next()
    assert job is not None
    logged.clear()

    def explode(*_args, **_kwargs):
        raise RuntimeError("rollback me")

    monkeypatch.setattr(scheduler, "_refresh_workflow", explode)
    with pytest.raises(RuntimeError):
        scheduler.complete(job.job_id, {"x": 1})  # job_succeeded is appended, then the transaction rolls back
    assert logged == []
    assert scheduler.get_job(job.job_id).status is JobStatus.RUNNING
    monkeypatch.undo()

    scheduler.complete(job.job_id, {"x": 1})
    assert [item["event_type"] for item in logged] == ["job_succeeded"]
    assert scheduler.verify_event_chain(wf.workflow_id)


def test_event_logger_failure_rolls_nothing_back(tmp_path) -> None:
    def broken(_payload):
        raise RuntimeError("logger down")

    scheduler = DurableJobScheduler(tmp_path, event_logger=broken)
    wf = scheduler.submit("w", "W", (JobSpec("a", "A"),))
    assert scheduler.get_workflow(wf.workflow_id) is not None


# E01-C2-N004 -----------------------------------------------------------------------------------------------------------
def test_composite_job_ids_cannot_collide_across_workflows(tmp_path) -> None:
    scheduler = DurableJobScheduler(tmp_path)
    scheduler.submit("w", "W", (JobSpec("b:c", "BC"),), workflow_id="a", dedupe_key="one")
    with pytest.raises(JobGraphError, match="collide"):
        scheduler.submit("w", "W", (JobSpec("c", "C"),), workflow_id="a:b", dedupe_key="two")
    assert scheduler.get_workflow("a:b") is None


# D020-N005 -----------------------------------------------------------------------------------------------------------
def test_jobs_page_self_check_uses_a_per_run_dedupe_key() -> None:
    import inspect

    from etf_cockpit.app.pages import jobs

    source = inspect.getsource(jobs)
    assert "uuid.uuid4()" in source and ".date().isoformat()" not in source.split("def run_self_check")[1].split("def worker")[0]
