"""Durable, local-first job DAG execution primitives.

The scheduler persists intent, state transitions, checkpoints and outputs in
the transactional SQLite store.  A worker may therefore disappear between
heartbeats without losing the DAG or publishing a partial result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
from itertools import islice
import json
import math
import os
from pathlib import Path
import re
import socket
import threading
import uuid

from etf_cockpit.core.resource_profiles import (
    ResourceDecision,
    ResourcePolicy,
    estimate_workflow_resources,
)
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.data.local_storage import TransactionalStore


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.BLOCKED}
)


class JobSchedulerError(RuntimeError):
    """Base error for invalid or unsafe durable scheduler operations."""


class JobGraphError(JobSchedulerError):
    """Raised when a submitted DAG is malformed or cyclic."""


class JobStateError(JobSchedulerError):
    """Raised when a transition does not match the durable state."""


@dataclass(frozen=True)
class JobSpec:
    key: str
    label: str
    input_payload: object = None
    dependencies: tuple[str, ...] = ()
    max_retries: int = 0
    resources: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    workflow_id: str
    job_key: str
    label: str
    status: JobStatus
    input_hash: str
    inputs: object
    outputs: object
    resources: Mapping[str, object]
    max_retries: int
    retry_count: int
    lease_owner: str
    lease_expires_at: str | None
    heartbeat_at: str | None
    checkpoint: Mapping[str, object]
    cancel_requested: bool
    error_message: str
    error_fingerprint: str | None
    retryable: bool
    created_at: str
    started_at: str | None
    finished_at: str | None
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowRecord:
    workflow_id: str
    workflow_type: str
    label: str
    status: JobStatus
    dedupe_key: str
    input_hash: str
    inputs: object
    outputs: object
    created_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str
    error_fingerprint: str | None
    resources: Mapping[str, object]


@dataclass(frozen=True)
class JobEvent:
    event_id: int
    workflow_id: str
    job_id: str | None
    event_type: str
    status: JobStatus
    occurred_at: str
    payload: Mapping[str, object]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True)
class JobContext:
    job_id: str
    workflow_id: str
    checkpoint: Callable[[Mapping[str, object]], None]
    heartbeat: Callable[[], None]
    is_cancel_requested: Callable[[], bool]
    lease_generation: int = 0


_MAX_CLAIM_CANDIDATES = 500
_TRUNCATION_KEY = "__truncated__"
_ITEM_LIMIT = 100
_REDACTED = "***redacted***"
_SENSITIVE_KEY_WORDS = frozenset(
    {"password", "passwd", "passphrase", "secret", "token", "apikey", "credential", "credentials", "authorization", "cookie", "bearer"}
)


class DurableJobScheduler:
    """Persist and execute bounded local job DAGs.

    ``run_once`` deliberately executes one claimed job in the caller's
    bounded worker.  Applications can provide a thread or process pool around
    it without introducing a second state store or allowing untracked work.
    """

    def __init__(
        self,
        root: Path,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 60,
        max_concurrency: int = 1,
        event_logger: Callable[[Mapping[str, object]], None] | None = None,
        resource_policy: ResourcePolicy | None = None,
        resource_profile: str = "auto",
    ) -> None:
        if lease_seconds <= 0 or max_concurrency <= 0:
            raise ValueError("lease_seconds and max_concurrency must be positive")
        self.root = Path(root).resolve()
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.lease_seconds = int(lease_seconds)
        self.event_logger = event_logger
        self._local = threading.local()
        self.resource_policy = resource_policy or ResourcePolicy(self.root, requested_profile=resource_profile)
        concurrency_limit = min(
            self.resource_policy.profile.job_cpu_limit,
            self.resource_policy.snapshot.cpu_cores,
        )
        if max_concurrency > concurrency_limit:
            raise ValueError(
                f"max_concurrency {max_concurrency} exceeds profile limit {concurrency_limit}"
            )
        self.max_concurrency = int(max_concurrency)

    def submit(
        self,
        workflow_type: str,
        label: str,
        jobs: Iterable[JobSpec],
        *,
        input_payload: object = None,
        dedupe_key: str | None = None,
        workflow_id: str | None = None,
    ) -> WorkflowRecord:
        specs = _normalise_specs(jobs)
        workflow_type = _safe_name(workflow_type, "workflow_type")
        declared_specs = specs  # machine-estimated default resources must not change workflow identity
        specs = _with_default_resources(
            specs,
            estimate_workflow_resources(
                workflow_type,
                requested_profile=self.resource_policy.requested_profile,
                snapshot=self.resource_policy.snapshot,
            ),
        )
        label = _redact(str(label))
        encoded_inputs = _bounded_json(input_payload)
        input_hash = _hash_text(encoded_inputs)
        spec_hash = _spec_hash(declared_specs)
        resolved_dedupe = _safe_name(
            dedupe_key or _hash_text(json.dumps([workflow_type, spec_hash, input_hash], separators=(",", ":"))),
            "dedupe_key",
        )
        resolved_workflow_id = _safe_name(workflow_id or f"wf_{uuid.uuid4().hex}", "workflow_id")
        created_at = _utc_now()
        resources = _resource_summary(specs)

        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                existing = connection.execute(
                    "SELECT workflow_id, workflow_type, input_hash FROM workflow_runs WHERE dedupe_key = ? ORDER BY created_at DESC LIMIT 1",
                    (resolved_dedupe,),
                ).fetchone()
                if existing is not None:
                    self._require_same_workflow(connection, existing, workflow_type, input_hash, spec_hash, resolved_dedupe)
                    return self.get_workflow(str(existing[0]))  # type: ignore[return-value]
                new_job_ids = [f"{resolved_workflow_id}:{spec.key}" for spec in specs]
                marks = ",".join("?" for _ in new_job_ids)
                if connection.execute(
                    f"SELECT 1 FROM durable_jobs WHERE job_id IN ({marks}) LIMIT 1", new_job_ids
                ).fetchone() is not None:
                    raise JobGraphError("Composite job identifiers would collide with an existing workflow's jobs")
                connection.execute(
                    """
                    INSERT INTO workflow_runs
                        (workflow_id, workflow_type, label, status, dedupe_key, input_hash,
                         inputs_json, outputs_json, created_at, resource_json)
                    VALUES (?, ?, ?, 'queued', ?, ?, ?, '[]', ?, ?)
                    """,
                    (
                        resolved_workflow_id,
                        workflow_type,
                        label,
                        resolved_dedupe,
                        input_hash,
                        encoded_inputs,
                        created_at,
                        _bounded_json(resources),
                    ),
                )
                for spec in specs:
                    job_id = f"{resolved_workflow_id}:{spec.key}"
                    connection.execute(
                        """
                        INSERT INTO durable_jobs
                            (job_id, workflow_id, job_key, label, status, input_hash, inputs_json,
                             outputs_json, resource_json, max_retries, retry_count, checkpoint_json,
                             created_at)
                        VALUES (?, ?, ?, ?, 'queued', ?, ?, '[]', ?, ?, 0, '{}', ?)
                        """,
                        (
                            job_id,
                            resolved_workflow_id,
                            spec.key,
                            _redact(spec.label),
                            _hash_text(_bounded_json(spec.input_payload)),
                            _bounded_json(spec.input_payload),
                            _bounded_json(_validate_resources(spec.resources)),
                            _validate_retries(spec.max_retries),
                            created_at,
                        ),
                    )
                for spec in specs:
                    for dependency in spec.dependencies:
                        connection.execute(
                            "INSERT INTO durable_job_dependencies(job_id, dependency_job_id) VALUES (?, ?)",
                            (f"{resolved_workflow_id}:{spec.key}", f"{resolved_workflow_id}:{dependency}"),
                        )
                self._append_event(
                    connection,
                    resolved_workflow_id,
                    None,
                    "workflow_queued",
                    JobStatus.QUEUED,
                    {
                        "workflow_type": workflow_type,
                        "job_count": len(specs),
                        "dedupe_key": resolved_dedupe,
                        "spec_hash": spec_hash,
                    },
                    created_at,
                )
                for spec in specs:
                    self._append_event(
                        connection,
                        resolved_workflow_id,
                        f"{resolved_workflow_id}:{spec.key}",
                        "job_queued",
                        JobStatus.QUEUED,
                        {"job_key": spec.key, "dependencies": list(spec.dependencies), "resources": dict(spec.resources)},
                        created_at,
                    )
        return self.get_workflow(resolved_workflow_id)  # type: ignore[return-value]

    def claim_next(self, workflow_id: str | None = None) -> JobRecord | None:
        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                self._block_unrunnable(connection)
                running = int(
                    connection.execute("SELECT COUNT(*) FROM durable_jobs WHERE status = 'running'").fetchone()[0]
                )
                if running >= self.max_concurrency:
                    return None
                workflow_filter = "" if workflow_id is None else "AND job.workflow_id = ?"
                workflow_parameters = () if workflow_id is None else (workflow_id,)
                # A job waiting for aggregate resources must not starve smaller queued jobs behind it.
                skipped: list[str] = []
                while True:
                    if len(skipped) >= _MAX_CLAIM_CANDIDATES:
                        return None
                    exclusion = f"AND job.job_id NOT IN ({','.join('?' for _ in skipped)})" if skipped else ""
                    row = connection.execute(
                        f"""
                        SELECT job_id, workflow_id FROM durable_jobs AS job
                        WHERE job.status = 'queued'
                          {workflow_filter}
                          {exclusion}
                          AND NOT EXISTS (
                              SELECT 1 FROM durable_job_dependencies AS dependency
                              JOIN durable_jobs AS prerequisite ON prerequisite.job_id = dependency.dependency_job_id
                              WHERE dependency.job_id = job.job_id AND prerequisite.status <> 'succeeded'
                          )
                        ORDER BY job.created_at, job.job_id
                        LIMIT 1
                        """,
                        (*workflow_parameters, *skipped),
                    ).fetchone()
                    if row is None:
                        return None
                    skipped.append(str(row["job_id"]))
                    resource_row = connection.execute("SELECT resource_json FROM durable_jobs WHERE job_id = ?", (str(row["job_id"]),)).fetchone()
                    try:
                        resources = json.loads(str(resource_row[0])) if resource_row else {}
                        if not isinstance(resources, dict):
                            raise ValueError("resource declaration must be an object")
                        resource_decision = self.resource_policy.evaluate(resources)
                    except (TypeError, ValueError):
                        resources = {}
                        resource_decision = ResourceDecision(
                            "blocked",
                            "unknown",
                            ("resource declaration is corrupt or not an object",),
                        )
                    if resource_decision.status == "blocked":
                        now = _utc_now()
                        message = "; ".join(resource_decision.reasons) or "Local resource policy blocked this job."
                        fingerprint = _hash_text(message)[:16]
                        connection.execute(
                            "UPDATE durable_jobs SET status = 'blocked', finished_at = ?, error_message = ?, error_fingerprint = ? WHERE job_id = ? AND status = 'queued'",
                            (now, message, fingerprint, str(row["job_id"])),
                        )
                        self._append_event(
                            connection,
                            str(row["workflow_id"]),
                            str(row["job_id"]),
                            "job_blocked_resource_limit",
                            JobStatus.BLOCKED,
                            {"resources": resources, "decision": resource_decision.to_dict()},
                            now,
                        )
                        self._block_unrunnable(connection)
                        self._refresh_workflow(connection, str(row["workflow_id"]), now)
                        continue
                    try:
                        aggregate_resources = _aggregate_resource_reservation(
                            connection,
                            resources,
                            profile_id=self.resource_policy.profile_id,
                        )
                        aggregate_decision = self.resource_policy.evaluate(aggregate_resources)
                    except (TypeError, ValueError):
                        # A running reservation can only become malformed through
                        # external database corruption. Fail closed until lease
                        # recovery or an operator repair makes the state readable.
                        return None
                    if aggregate_decision.status == "blocked":
                        now = _utc_now()
                        already_recorded = connection.execute(
                            "SELECT 1 FROM durable_job_events WHERE job_id = ? AND event_type = 'job_resource_wait' LIMIT 1",
                            (str(row["job_id"]),),
                        ).fetchone()
                        if already_recorded is None:
                            self._append_event(
                                connection,
                                str(row["workflow_id"]),
                                str(row["job_id"]),
                                "job_resource_wait",
                                JobStatus.QUEUED,
                                {
                                    "reason": "aggregate running-job reservation exceeds the safe profile limit",
                                    "resources": resources,
                                    "aggregate_resources": aggregate_resources,
                                    "decision": aggregate_decision.to_dict(),
                                },
                                now,
                            )
                        continue
                    break
                now = _utc_now()
                if resource_decision.status == "warning" or aggregate_decision.status == "warning":
                    self._append_event(
                        connection,
                        str(row["workflow_id"]),
                        str(row["job_id"]),
                        "job_resource_warning",
                        JobStatus.QUEUED,
                        {
                            "resources": resources,
                            "decision": resource_decision.to_dict(),
                            "aggregate_resources": aggregate_resources,
                            "aggregate_decision": aggregate_decision.to_dict(),
                        },
                        now,
                    )
                lease_expires = _utc_after(self.lease_seconds)
                connection.execute(
                    """
                    UPDATE durable_jobs
                    SET status = 'running', lease_owner = ?, lease_expires_at = ?, heartbeat_at = ?,
                        started_at = COALESCE(started_at, ?), error_message = '', retryable = 0
                    WHERE job_id = ? AND status = 'queued'
                    """,
                    (self.worker_id, lease_expires, now, now, str(row[0])),
                )
                self._refresh_workflow(connection, str(row[1]), now)
                self._append_event(
                    connection,
                    str(row[1]),
                    str(row[0]),
                    "job_started",
                    JobStatus.RUNNING,
                    {"worker_id": self.worker_id, "lease_expires_at": lease_expires},
                    now,
                )
                job_id = str(row[0])
            return self.get_job(job_id)

    def heartbeat(self, job_id: str, *, lease_generation: int | None = None) -> JobRecord:
        now = _utc_now()
        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                row = self._running_owned(connection, job_id, lease_generation)
                lease_expires = _utc_after(self.lease_seconds)
                connection.execute(
                    "UPDATE durable_jobs SET heartbeat_at = ?, lease_expires_at = ? WHERE job_id = ?",
                    (now, lease_expires, job_id),
                )
                self._append_event(
                    connection,
                    str(row["workflow_id"]),
                    job_id,
                    "job_heartbeat",
                    JobStatus.RUNNING,
                    {"worker_id": self.worker_id, "lease_expires_at": lease_expires},
                    now,
                )
            return self.get_job(job_id)  # type: ignore[return-value]

    def checkpoint(self, job_id: str, checkpoint: Mapping[str, object], *, lease_generation: int | None = None) -> JobRecord:
        payload = _bounded_json(checkpoint)
        now = _utc_now()
        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                row = self._running_owned(connection, job_id, lease_generation)
                connection.execute("UPDATE durable_jobs SET checkpoint_json = ? WHERE job_id = ?", (payload, job_id))
                self._append_event(
                    connection,
                    str(row["workflow_id"]),
                    job_id,
                    "job_checkpoint",
                    JobStatus.RUNNING,
                    {"checkpoint": json.loads(payload)},
                    now,
                )
            return self.get_job(job_id)  # type: ignore[return-value]

    def complete(self, job_id: str, outputs: object = None, *, lease_generation: int | None = None) -> JobRecord:
        safe_outputs = _safe_outputs(outputs)
        now = _utc_now()
        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                row = self._running_owned(connection, job_id, lease_generation)
                if int(row["cancel_requested"]):
                    raise JobStateError("cancelled jobs cannot publish outputs")
                connection.execute(
                    """
                    UPDATE durable_jobs
                    SET status = 'succeeded', outputs_json = ?, finished_at = ?, lease_owner = '',
                        lease_expires_at = NULL, heartbeat_at = NULL, error_message = ''
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (_bounded_json(safe_outputs), now, job_id),
                )
                workflow_id = str(row["workflow_id"])
                self._append_event(
                    connection,
                    workflow_id,
                    job_id,
                    "job_succeeded",
                    JobStatus.SUCCEEDED,
                    {"outputs": safe_outputs},
                    now,
                )
                self._block_unrunnable(connection)
                self._refresh_workflow(connection, workflow_id, now)
            return self.get_job(job_id)  # type: ignore[return-value]

    def fail(
        self,
        job_id: str,
        error: BaseException | str,
        *,
        retryable: bool = False,
        lease_generation: int | None = None,
    ) -> JobRecord:
        message = _redact(f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error))
        fingerprint = _hash_text(message)[:16]
        now = _utc_now()
        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                row = self._running_owned(connection, job_id, lease_generation)
                workflow_id = str(row["workflow_id"])
                next_retry = int(row["retry_count"]) + 1
                should_retry = bool(retryable) and next_retry <= int(row["max_retries"])
                status = JobStatus.QUEUED if should_retry else JobStatus.FAILED
                connection.execute(
                    """
                    UPDATE durable_jobs
                    SET status = ?, retry_count = ?, error_message = ?, error_fingerprint = ?, retryable = ?,
                        finished_at = CASE WHEN ? = 'failed' THEN ? ELSE NULL END,
                        lease_owner = '', lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE job_id = ?
                    """,
                    (status.value, next_retry, message, fingerprint, int(bool(retryable)), status.value, now, job_id),
                )
                self._append_event(
                    connection,
                    workflow_id,
                    job_id,
                    "job_retry_scheduled" if should_retry else "job_failed",
                    status,
                    {"message": message, "error_fingerprint": fingerprint, "retry_count": next_retry, "retryable": bool(retryable)},
                    now,
                )
                self._block_unrunnable(connection)
                self._refresh_workflow(connection, workflow_id, now)
            return self.get_job(job_id)  # type: ignore[return-value]

    def cancel(self, workflow_id: str, *, job_id: str | None = None, message: str = "Cancelled by user") -> tuple[JobRecord, ...]:
        safe_message = _redact(message)
        now = _utc_now()
        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                query = "SELECT * FROM durable_jobs WHERE workflow_id = ? AND status IN ('queued', 'running')"
                params: tuple[object, ...] = (workflow_id,)
                if job_id is not None:
                    query += " AND job_id = ?"
                    params += (job_id,)
                rows = connection.execute(query, params).fetchall()
                for row in rows:
                    current_job_id = str(row["job_id"])
                    connection.execute(
                        """
                        UPDATE durable_jobs
                        SET status = 'cancelled', cancel_requested = 1, finished_at = ?, error_message = ?,
                            lease_owner = '', lease_expires_at = NULL, heartbeat_at = NULL
                        WHERE job_id = ?
                        """,
                        (now, safe_message, current_job_id),
                    )
                    self._append_event(
                        connection,
                        workflow_id,
                        current_job_id,
                        "job_cancelled",
                        JobStatus.CANCELLED,
                        {"message": safe_message},
                        now,
                    )
                self._block_unrunnable(connection)
                self._refresh_workflow(connection, workflow_id, now)
            return self.list_jobs(workflow_id)

    def recover_expired_leases(self) -> tuple[JobRecord, ...]:
        now = _utc_now()
        recovered: list[str] = []
        with TransactionalStore(self.root) as store:
            with self._transaction(store) as connection:
                rows = connection.execute(
                    "SELECT * FROM durable_jobs WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
                    (now,),
                ).fetchall()
                for row in rows:
                    job_id = str(row["job_id"])
                    workflow_id = str(row["workflow_id"])
                    next_retry = int(row["retry_count"]) + 1
                    can_resume = next_retry <= int(row["max_retries"])
                    status = JobStatus.QUEUED if can_resume else JobStatus.FAILED
                    connection.execute(
                        """
                        UPDATE durable_jobs
                        SET status = ?, retry_count = ?, lease_owner = '', lease_expires_at = NULL,
                            heartbeat_at = NULL, finished_at = CASE WHEN ? = 'failed' THEN ? ELSE NULL END,
                            error_message = ?
                        WHERE job_id = ?
                        """,
                        (status.value, next_retry, status.value, now, "Lease expired; job resumed safely." if can_resume else "Lease expired; retry budget exhausted.", job_id),
                    )
                    self._append_event(
                        connection,
                        workflow_id,
                        job_id,
                        "job_lease_recovered" if can_resume else "job_failed",
                        status,
                        {"retry_count": next_retry, "worker_id": str(row["lease_owner"])},
                        now,
                    )
                    recovered.append(job_id)
                self._block_unrunnable(connection)
                for workflow_id in {str(row["workflow_id"]) for row in rows}:
                    self._refresh_workflow(connection, workflow_id, now)
            return tuple(self.get_job(job_id) for job_id in recovered if self.get_job(job_id) is not None)  # type: ignore[misc]

    def run_once(
        self,
        handler: Callable[[JobContext], object],
        *,
        workflow_id: str | None = None,
    ) -> JobRecord | None:
        # Unscoped callers keep the original claim_next() call shape.
        job = self.claim_next() if workflow_id is None else self.claim_next(workflow_id=workflow_id)
        if job is None:
            return None
        generation = job.retry_count
        context = JobContext(
            job_id=job.job_id,
            workflow_id=job.workflow_id,
            checkpoint=lambda value: self.checkpoint(job.job_id, value, lease_generation=generation),
            heartbeat=lambda: self.heartbeat(job.job_id, lease_generation=generation),
            is_cancel_requested=lambda: bool(self.get_job(job.job_id) and self.get_job(job.job_id).cancel_requested),
            lease_generation=generation,
        )
        try:
            self.resource_policy.require_allowed(dict(job.resources))
            output = handler(context)
            failure: BaseException | None = None
        except Exception as exc:
            output, failure = None, exc
        # A cancel or lease recovery may commit while the handler runs.  The durable state is authoritative then:
        # the handler's result is discarded instead of raising or overriding the newer transition.
        try:
            if failure is None:
                try:
                    if context.is_cancel_requested():
                        self.cancel(job.workflow_id, job_id=job.job_id)
                    else:
                        self.complete(job.job_id, output, lease_generation=generation)
                except JobStateError:
                    raise
                except Exception as exc:
                    failure = exc
            if failure is not None:
                self.fail(
                    job.job_id,
                    failure,
                    retryable=isinstance(failure, (TimeoutError, OSError, ConnectionError)),
                    lease_generation=generation,
                )
        except JobStateError:
            pass
        return self.get_job(job.job_id)

    def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        with TransactionalStore(self.root) as store:
            row = store.connection.execute("SELECT * FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)).fetchone()
            return _workflow_record(row) if row else None

    def get_job(self, job_id: str) -> JobRecord | None:
        with TransactionalStore(self.root) as store:
            row = store.connection.execute("SELECT * FROM durable_jobs WHERE job_id = ?", (job_id,)).fetchone()
            return _job_record(store.connection, row) if row else None

    def list_jobs(self, workflow_id: str | None = None) -> tuple[JobRecord, ...]:
        with TransactionalStore(self.root) as store:
            if workflow_id:
                rows = store.connection.execute("SELECT * FROM durable_jobs WHERE workflow_id = ? ORDER BY created_at, job_id", (workflow_id,)).fetchall()
            else:
                rows = store.connection.execute("SELECT * FROM durable_jobs ORDER BY created_at DESC, job_id").fetchall()
            return tuple(_job_record(store.connection, row) for row in rows)

    def list_workflows(self, limit: int = 50) -> tuple[WorkflowRecord, ...]:
        limit = max(1, min(int(limit), 200))
        with TransactionalStore(self.root) as store:
            rows = store.connection.execute("SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return tuple(_workflow_record(row) for row in rows)

    def list_events(self, workflow_id: str | None = None, limit: int = 200) -> tuple[JobEvent, ...]:
        limit = max(1, min(int(limit), 1000))
        with TransactionalStore(self.root) as store:
            if workflow_id:
                rows = store.connection.execute("SELECT * FROM durable_job_events WHERE workflow_id = ? ORDER BY event_id DESC LIMIT ?", (workflow_id, limit)).fetchall()
            else:
                rows = store.connection.execute("SELECT * FROM durable_job_events ORDER BY event_id DESC LIMIT ?", (limit,)).fetchall()
            return tuple(_event_record(row) for row in reversed(rows))

    def dependency_graph(self, workflow_id: str) -> dict[str, tuple[str, ...]]:
        jobs = self.list_jobs(workflow_id)
        return {job.job_key: job.dependencies for job in jobs}

    def verify_event_chain(self, workflow_id: str | None = None) -> bool:
        # Hashes form one global append-only stream.  Verify every event even
        # when the caller only wants the result for one workflow; filtering
        # first would make a valid cross-workflow predecessor look broken.
        with TransactionalStore(self.root) as store:
            rows = store.connection.execute(
                "SELECT * FROM durable_job_events ORDER BY event_id ASC"
            ).fetchall()
        events = tuple(_event_record(row) for row in rows)
        previous = ""
        for event in events:
            if event.previous_hash != previous:
                return False
            payload = {
                "workflow_id": event.workflow_id,
                "job_id": event.job_id,
                "event_type": event.event_type,
                "status": event.status.value,
                "occurred_at": event.occurred_at,
                "payload": dict(event.payload),
                "previous_hash": event.previous_hash,
            }
            if _hash_text(json.dumps(payload, sort_keys=True, separators=(",", ":"))) != event.event_hash:
                return False
            previous = event.event_hash
        return True

    def _running_owned(self, connection, job_id: str, lease_generation: int | None = None):
        row = connection.execute("SELECT * FROM durable_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobStateError(f"Unknown job: {job_id}")
        if row["status"] != JobStatus.RUNNING.value:
            raise JobStateError(f"Job {job_id} is not running")
        if row["lease_owner"] != self.worker_id:
            raise JobStateError(f"Job {job_id} is leased by another worker")
        # retry_count increases on every lease recovery or retry, so it fences a stale handler that
        # still holds an older claim of the same job (even when the same worker id re-claimed it).
        if lease_generation is not None and int(row["retry_count"]) != int(lease_generation):
            raise JobStateError(f"Job {job_id} lease generation changed; the stale handler result is rejected")
        return row

    @contextmanager
    def _transaction(self, store: TransactionalStore) -> Iterator[object]:
        """Run one transaction; external event callbacks fire only after it commits."""

        previous = getattr(self._local, "pending", None)
        pending: list[dict[str, object]] = []
        self._local.pending = pending
        try:
            with store.transaction() as connection:
                yield connection
        finally:
            self._local.pending = previous
        if self.event_logger is not None:
            for payload in pending:
                try:
                    self.event_logger(payload)
                except Exception:
                    pass

    def _require_same_workflow(self, connection, existing, workflow_type: str, input_hash: str, spec_hash: str, dedupe_key: str) -> None:
        """Fail closed when a reused dedupe key names a different workflow type, input or job specification."""

        stored_spec = None
        queued = connection.execute(
            "SELECT payload_json FROM durable_job_events WHERE workflow_id = ? AND event_type = 'workflow_queued' ORDER BY event_id LIMIT 1",
            (str(existing[0]),),
        ).fetchone()
        if queued is not None:
            try:
                stored_spec = json.loads(str(queued[0])).get("spec_hash")
            except (TypeError, ValueError, AttributeError):
                stored_spec = None
        # Workflows queued before spec hashes were recorded keep the legacy type+input comparison.
        if (
            str(existing[1]) != workflow_type
            or str(existing[2]) != input_hash
            or (stored_spec is not None and stored_spec != spec_hash)
        ):
            raise JobSchedulerError(
                f"dedupe_key {dedupe_key!r} is already used by a workflow with a different type, input or job specification"
            )

    def _block_unrunnable(self, connection) -> None:
        changed = True
        while changed:
            changed = False
            rows = connection.execute(
                """
                SELECT job.job_id, job.workflow_id
                FROM durable_jobs AS job
                WHERE job.status = 'queued'
                  AND EXISTS (
                    SELECT 1 FROM durable_job_dependencies AS dependency
                    JOIN durable_jobs AS prerequisite ON prerequisite.job_id = dependency.dependency_job_id
                    WHERE dependency.job_id = job.job_id AND prerequisite.status IN ('failed', 'cancelled', 'blocked')
                  )
                """
            ).fetchall()
            now = _utc_now()
            for row in rows:
                connection.execute(
                    "UPDATE durable_jobs SET status = 'blocked', finished_at = ?, error_message = 'Blocked by failed or cancelled dependency.' WHERE job_id = ? AND status = 'queued'",
                    (now, str(row["job_id"])),
                )
                self._append_event(
                    connection,
                    str(row["workflow_id"]),
                    str(row["job_id"]),
                    "job_blocked",
                    JobStatus.BLOCKED,
                    {"reason": "dependency_not_succeeded"},
                    now,
                )
                changed = True

    def _refresh_workflow(self, connection, workflow_id: str, now: str) -> None:
        rows = connection.execute("SELECT status, outputs_json, error_message, error_fingerprint FROM durable_jobs WHERE workflow_id = ?", (workflow_id,)).fetchall()
        if not rows:
            return
        statuses = [JobStatus(str(row["status"])) for row in rows]
        if any(status in {JobStatus.QUEUED, JobStatus.RUNNING} for status in statuses):
            # Unfinished independent siblings keep the workflow active (and cancellable) even after a failure.
            status = JobStatus.RUNNING if any(item is JobStatus.RUNNING for item in statuses) else JobStatus.QUEUED
        elif any(status is JobStatus.FAILED for status in statuses):
            status = JobStatus.FAILED
        elif all(status is JobStatus.SUCCEEDED for status in statuses):
            status = JobStatus.SUCCEEDED
        elif all(status is JobStatus.CANCELLED for status in statuses):
            status = JobStatus.CANCELLED
        else:
            status = JobStatus.BLOCKED
        outputs = [json.loads(str(row["outputs_json"])) for row in rows if json.loads(str(row["outputs_json"]))]
        error_row = next((row for row in rows if row["error_message"]), None)
        connection.execute(
            """
            UPDATE workflow_runs
            SET status = ?, started_at = COALESCE(started_at, CASE WHEN ? IN ('running', 'succeeded', 'failed', 'cancelled', 'blocked') THEN ? ELSE started_at END),
                finished_at = CASE WHEN ? IN ('succeeded', 'failed', 'cancelled', 'blocked') THEN COALESCE(finished_at, ?) ELSE NULL END,
                outputs_json = ?, error_message = ?, error_fingerprint = ?
            WHERE workflow_id = ?
            """,
            (
                status.value,
                status.value,
                now,
                status.value,
                now,
                _bounded_json(outputs),
                str(error_row["error_message"]) if error_row else "",
                str(error_row["error_fingerprint"]) if error_row and error_row["error_fingerprint"] else None,
                workflow_id,
            ),
        )

    def _append_event(self, connection, workflow_id: str, job_id: str | None, event_type: str, status: JobStatus, payload: Mapping[str, object], occurred_at: str) -> None:
        previous_row = connection.execute("SELECT event_hash FROM durable_job_events ORDER BY event_id DESC LIMIT 1").fetchone()
        previous_hash = str(previous_row[0]) if previous_row else ""
        safe_payload = json.loads(_bounded_json(payload))
        unsigned = {
            "workflow_id": workflow_id,
            "job_id": job_id,
            "event_type": event_type,
            "status": status.value,
            "occurred_at": occurred_at,
            "payload": safe_payload,
            "previous_hash": previous_hash,
        }
        event_hash = _hash_text(json.dumps(unsigned, sort_keys=True, separators=(",", ":")))
        connection.execute(
            """
            INSERT INTO durable_job_events
                (workflow_id, job_id, event_type, status, occurred_at, payload_json, previous_hash, event_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (workflow_id, job_id, event_type, status.value, occurred_at, _bounded_json(safe_payload), previous_hash, event_hash),
        )
        if self.event_logger is not None:
            pending = getattr(self._local, "pending", None)
            if pending is None:
                raise JobStateError("scheduler events must be appended inside a transaction")
            pending.append({**unsigned, "event_hash": event_hash})


def _normalise_specs(jobs: Iterable[JobSpec]) -> tuple[JobSpec, ...]:
    specs = tuple(jobs)
    if not specs:
        raise JobGraphError("A workflow must contain at least one job")
    keys = {spec.key for spec in specs}
    if len(keys) != len(specs) or any(not _valid_key(key) for key in keys):
        raise JobGraphError("Job keys must be unique safe identifiers")
    for spec in specs:
        if any(dependency not in keys for dependency in spec.dependencies):
            raise JobGraphError(f"Job {spec.key!r} has an unknown dependency")
        _validate_retries(spec.max_retries)
        _validate_resources(spec.resources)
    indegree = {spec.key: len(spec.dependencies) for spec in specs}
    dependants = {spec.key: [] for spec in specs}
    for spec in specs:
        for dependency in spec.dependencies:
            dependants[dependency].append(spec.key)
    pending = [key for key, degree in indegree.items() if degree == 0]
    visited = 0
    while pending:
        key = pending.pop()
        visited += 1
        for dependant in dependants[key]:
            indegree[dependant] -= 1
            if indegree[dependant] == 0:
                pending.append(dependant)
    if visited != len(specs):
        raise JobGraphError("Workflow job dependencies contain a cycle")
    return tuple(
        JobSpec(
            key=str(spec.key),
            label=_redact(str(spec.label)),
            input_payload=spec.input_payload,
            dependencies=tuple(sorted(set(str(item) for item in spec.dependencies))),
            max_retries=int(spec.max_retries),
            resources=dict(spec.resources),
        )
        for spec in specs
    )


def _with_default_resources(
    specs: tuple[JobSpec, ...], estimate: Mapping[str, object]
) -> tuple[JobSpec, ...]:
    defaults = {
        "profile": estimate["profile"],
        "cpu": estimate["cpu"],
        "memory_mb": estimate["memory_mb"],
        "disk_mb": estimate["disk_mb"],
    }
    return tuple(
        JobSpec(
            key=spec.key,
            label=spec.label,
            input_payload=spec.input_payload,
            dependencies=spec.dependencies,
            max_retries=spec.max_retries,
            resources=_validate_resources(defaults | dict(spec.resources)),
        )
        for spec in specs
    )


def _resource_payload(value: object) -> dict[str, object]:
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _aggregate_resource_reservation(
    connection,
    candidate: Mapping[str, object],
    *,
    profile_id: str,
) -> dict[str, object]:
    """Return candidate plus running reservations for one atomic claim."""

    totals = {"cpu": 0.0, "memory_mb": 0.0, "disk_mb": 0.0}
    rows = connection.execute(
        "SELECT resource_json FROM durable_jobs WHERE status = 'running'"
    ).fetchall()
    for row in rows:
        resources = json.loads(str(row[0]))
        if not isinstance(resources, dict):
            raise ValueError("running resource declaration must be an object")
        validated = _validate_resources(resources)
        for key in totals:
            totals[key] += float(validated.get(key, 0.0))
    validated_candidate = _validate_resources(candidate)
    for key in totals:
        totals[key] += float(validated_candidate.get(key, 0.0))
    return {"profile": profile_id, **totals}


def _job_record(connection, row) -> JobRecord:
    dependency_rows = connection.execute(
        "SELECT dependency_job_id FROM durable_job_dependencies WHERE job_id = ? ORDER BY dependency_job_id",
        (str(row["job_id"]),),
    ).fetchall()
    workflow_prefix = f"{row['workflow_id']}:"
    return JobRecord(
        job_id=str(row["job_id"]),
        workflow_id=str(row["workflow_id"]),
        job_key=str(row["job_key"]),
        label=str(row["label"]),
        status=JobStatus(str(row["status"])),
        input_hash=str(row["input_hash"]),
        inputs=json.loads(str(row["inputs_json"])),
        outputs=json.loads(str(row["outputs_json"])),
        resources=_resource_payload(row["resource_json"]),
        max_retries=int(row["max_retries"]),
        retry_count=int(row["retry_count"]),
        lease_owner=str(row["lease_owner"]),
        lease_expires_at=str(row["lease_expires_at"]) if row["lease_expires_at"] else None,
        heartbeat_at=str(row["heartbeat_at"]) if row["heartbeat_at"] else None,
        checkpoint=json.loads(str(row["checkpoint_json"])),
        cancel_requested=bool(row["cancel_requested"]),
        error_message=str(row["error_message"]),
        error_fingerprint=str(row["error_fingerprint"]) if row["error_fingerprint"] else None,
        retryable=bool(row["retryable"]),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"]) if row["started_at"] else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
        dependencies=tuple(str(item[0]).removeprefix(workflow_prefix) for item in dependency_rows),
    )


def _workflow_record(row) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=str(row["workflow_id"]),
        workflow_type=str(row["workflow_type"]),
        label=str(row["label"]),
        status=JobStatus(str(row["status"])),
        dedupe_key=str(row["dedupe_key"]),
        input_hash=str(row["input_hash"]),
        inputs=json.loads(str(row["inputs_json"])),
        outputs=json.loads(str(row["outputs_json"])),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"]) if row["started_at"] else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
        error_message=str(row["error_message"]),
        error_fingerprint=str(row["error_fingerprint"]) if row["error_fingerprint"] else None,
        resources=json.loads(str(row["resource_json"])),
    )


def _event_record(row) -> JobEvent:
    return JobEvent(
        event_id=int(row["event_id"]),
        workflow_id=str(row["workflow_id"]),
        job_id=str(row["job_id"]) if row["job_id"] else None,
        event_type=str(row["event_type"]),
        status=JobStatus(str(row["status"])),
        occurred_at=str(row["occurred_at"]),
        payload=json.loads(str(row["payload_json"])),
        previous_hash=str(row["previous_hash"]),
        event_hash=str(row["event_hash"]),
    )


def _validate_retries(value: int) -> int:
    value = int(value)
    if value < 0 or value > 10:
        raise ValueError("max_retries must be between 0 and 10")
    return value


def _validate_resources(resources: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(resources, Mapping):
        raise ValueError("resources must be a mapping")
    result = {str(key): value for key, value in resources.items()}
    for key in ("cpu", "memory_mb", "disk_mb"):
        if key in result and (isinstance(result[key], bool) or not isinstance(result[key], (int, float)) or not math.isfinite(float(result[key])) or float(result[key]) <= 0):
            raise ValueError(f"resource {key} must be positive")
    if "profile" in result and (not isinstance(result["profile"], str) or str(result["profile"]).strip().casefold() not in {"auto", "minimum", "recommended", "high"}):
        raise ValueError("resource profile must be auto, minimum, recommended or high")
    if "gpu" in result and not isinstance(result["gpu"], (bool, str, int)):
        raise ValueError("resource gpu must be a boolean or device label")
    return result


def _resource_summary(specs: Iterable[JobSpec]) -> dict[str, object]:
    return {"max_concurrency": 1, "jobs": {spec.key: _validate_resources(spec.resources) for spec in specs}}


def _safe_outputs(outputs: object) -> object:
    if outputs is None:
        return []
    if isinstance(outputs, Mapping):
        return _redact_value(outputs)
    if isinstance(outputs, (str, Path)):
        return [_redact(str(outputs))[:512]]
    if isinstance(outputs, Iterable):
        # Never materialise more than one element past the cap: generators may be unbounded.
        items = list(islice(iter(outputs), _ITEM_LIMIT + 1))
        safe = [
            _redact_value(value) if isinstance(value, (Mapping, list, tuple, set)) else _redact(str(value))[:512]
            for value in items[:_ITEM_LIMIT]
        ]
        if len(items) > _ITEM_LIMIT:
            safe.append({_TRUNCATION_KEY: {"limit": _ITEM_LIMIT, "total": "unknown", "sha256": "unavailable"}})
        return safe
    return _redact_value(outputs)


def _bounded_json(value: object, limit: int = 16_384) -> str:
    encoded = json.dumps(_redact_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError(f"job payload exceeds {limit} bytes")
    return encoded


def _spec_hash(specs: Iterable[JobSpec]) -> str:
    """Hash the job DAG (keys, dependencies, retries, declared resources and per-job inputs)."""

    canonical = sorted(
        (
            spec.key,
            sorted(spec.dependencies),
            int(spec.max_retries),
            _validate_resources(spec.resources),
            _hash_text(_bounded_json(spec.input_payload)),
        )
        for spec in specs
    )
    return _hash_text(json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str))


def _sensitive_key(key: object) -> bool:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)).casefold()
    words = [word for word in re.split(r"[^a-z0-9]+", spaced) if word]
    if any(word in _SENSITIVE_KEY_WORDS for word in words):
        return True
    return any(pair in {("api", "key"), ("private", "key"), ("access", "key"), ("secret", "key")} for pair in zip(words, words[1:]))


def _truncation_marker(total: int, digest_source: object) -> dict[str, object]:
    encoded = json.dumps(digest_source, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return {"limit": _ITEM_LIMIT, "total": total, "sha256": _hash_text(encoded)}


def _redact_entry(key: str, item: object) -> object:
    if _sensitive_key(key) and item not in (None, "", [], {}):
        return _REDACTED
    return _redact_value(item)


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        entries = [(str(key), item) for key, item in value.items()]
        marker = None
        for index, (key, item) in enumerate(entries):  # already bounded once (key order is not stable): keep the digest
            if key == _TRUNCATION_KEY:
                marker = item
                del entries[index]
                break
        result = {key: _redact_entry(key, item) for key, item in entries[:_ITEM_LIMIT]}
        if len(entries) > _ITEM_LIMIT:
            full = {key: _redact_entry(key, item) for key, item in entries}
            result[_TRUNCATION_KEY] = _truncation_marker(len(entries), full)
        elif marker is not None:
            result[_TRUNCATION_KEY] = marker
        return result
    if isinstance(value, (list, tuple, set)):
        items = sorted(value, key=str) if isinstance(value, set) else list(value)
        marker_item = None
        if items and isinstance(items[-1], Mapping) and set(items[-1]) == {_TRUNCATION_KEY}:
            marker_item = items.pop()
        result_list = [_redact_value(item) for item in items[:_ITEM_LIMIT]]
        if len(items) > _ITEM_LIMIT:
            result_list.append({_TRUNCATION_KEY: _truncation_marker(len(items), [_redact_value(item) for item in items])})
        elif marker_item is not None:
            result_list.append(dict(marker_item))
        return result_list
    if isinstance(value, str):
        return _redact(value)
    return value


def _redact(value: str) -> str:
    return redact_text(value)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_name(value: str, field_name: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 160 or any(char in value for char in "\r\n"):
        raise ValueError(f"{field_name} must be a bounded single-line identifier")
    return value


def _valid_key(value: str) -> bool:
    return bool(value and len(value) <= 100 and all(char.isalnum() or char in "._:-" for char in value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


__all__ = [
    "DurableJobScheduler",
    "JobContext",
    "JobEvent",
    "JobGraphError",
    "JobRecord",
    "JobSchedulerError",
    "JobSpec",
    "JobStateError",
    "JobStatus",
    "TERMINAL_JOB_STATUSES",
    "WorkflowRecord",
]
