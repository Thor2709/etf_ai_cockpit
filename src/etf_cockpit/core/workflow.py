from __future__ import annotations

import hashlib
import json
import threading
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable

from etf_cockpit.core.session_log import log_event, new_action_id, redact_text


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    MANUAL_REVIEW = "manual_review"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkflowStep:
    key: str
    label: str
    completed_units: int
    total_units: int | None


@dataclass(frozen=True)
class WorkflowResult:
    action_id: str
    workflow: str
    status: WorkflowStatus
    started_at: str
    finished_at: str
    message: str
    output_paths: tuple[str, ...]
    error_fingerprint: str | None
    retryable: bool
    steps: tuple[WorkflowStep, ...] = ()
    command_key: str = ""
    input_hash: str = ""
    deduplication_key: str = ""
    cancel_requested: bool = False
    cancelled_at: str = ""
    progress: float | None = None


class WorkflowTransitionError(RuntimeError):
    """Raised when a workflow is used after it reached a terminal state."""


class WorkflowDuplicateError(WorkflowTransitionError):
    """Raised when an equivalent command is already active."""


EventLogger = Callable[[dict[str, object]], None]

@dataclass
class _WorkflowRecord:
    action_id: str
    workflow: str
    label: str
    started_at: str
    status: WorkflowStatus = WorkflowStatus.RUNNING
    steps: list[WorkflowStep] = field(default_factory=list)
    finished_at: str = ""
    message: str = ""
    output_paths: tuple[str, ...] = ()
    error_fingerprint: str | None = None
    retryable: bool = False
    command_key: str = ""
    input_hash: str = ""
    deduplication_key: str = ""
    cancel_requested: bool = False
    cancelled_at: str = ""
    progress: float | None = None


class WorkflowController:
    """Small state machine shared by UI workflows and the session trace.

    Default lifecycle events are persisted through the session trace. An
    explicitly injected ``log_path`` retains the narrow adapter/test seam for
    callers that need a separate append-only record.
    """

    def __init__(self, log_path: Path | None = None, *, event_logger: EventLogger | None = None) -> None:
        self.log_path = log_path
        self.event_logger = event_logger or self._session_event_logger
        self._records: dict[str, _WorkflowRecord] = {}
        self._lock = threading.RLock()

    def start(
        self,
        workflow: str,
        label: str,
        *,
        command_key: str | None = None,
        input_payload: object | None = None,
        input_hash: str | None = None,
    ) -> str:
        action_id = new_action_id(workflow)
        safe_workflow = str(workflow)
        safe_command_key = str(command_key or safe_workflow)
        resolved_input_hash = input_hash or _input_hash(input_payload)
        deduplication_key = hashlib.sha256(
            f"{safe_workflow}:{safe_command_key}:{resolved_input_hash}".encode("utf-8")
        ).hexdigest()[:24]
        record = _WorkflowRecord(
            action_id=action_id,
            workflow=safe_workflow,
            label=str(label),
            started_at=_utc_now(),
            message=f"{label} started.",
            command_key=safe_command_key,
            input_hash=resolved_input_hash,
            deduplication_key=deduplication_key,
        )
        with self._lock:
            if any(
                existing.status is WorkflowStatus.RUNNING
                and existing.deduplication_key == deduplication_key
                for existing in self._records.values()
            ):
                raise WorkflowDuplicateError(
                    f"An equivalent active workflow already exists for {safe_command_key!r}."
                )
            self._records[action_id] = record
            self._emit(record, "start")
        return action_id

    def step(self, action_id: str, step: WorkflowStep) -> None:
        with self._lock:
            record = self._running(action_id)
            safe_step = WorkflowStep(
                key=str(step.key),
                label=str(step.label),
                completed_units=max(0, int(step.completed_units)),
                total_units=None if step.total_units is None else max(0, int(step.total_units)),
            )
            record.steps.append(safe_step)
            record.message = safe_step.label
            record.progress = (
                None
                if safe_step.total_units in (None, 0)
                else min(1.0, safe_step.completed_units / safe_step.total_units)
            )
            self._emit(record, "step", step=safe_step)

    def finish(
        self,
        action_id: str,
        status: WorkflowStatus,
        message: str,
        output_paths: Iterable[Path | str],
        *,
        retryable: bool = False,
    ) -> WorkflowResult:
        if status in {WorkflowStatus.RUNNING}:
            raise WorkflowTransitionError("A workflow cannot finish in running status")
        with self._lock:
            record = self._running(action_id)
            record.status = WorkflowStatus(status)
            record.finished_at = _utc_now()
            record.message = _redact(str(message))
            record.output_paths = tuple(str(path) for path in output_paths)
            record.retryable = bool(retryable)
            self._emit(record, "finish")
            return _result(record)

    def cancel(self, action_id: str, message: str = "Cancelled by user") -> WorkflowResult:
        with self._lock:
            record = self._running(action_id)
            record.cancel_requested = True
            record.status = WorkflowStatus.CANCELLED
            record.finished_at = _utc_now()
            record.cancelled_at = record.finished_at
            record.message = _redact(str(message))
            record.progress = record.progress
            self._emit(record, "finish")
            return _result(record)

    def is_cancel_requested(self, action_id: str) -> bool:
        with self._lock:
            record = self._records.get(action_id)
            return bool(record and record.cancel_requested)

    def fail(self, action_id: str, exc: BaseException, *, retryable: bool) -> WorkflowResult:
        with self._lock:
            record = self._running(action_id)
            traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            record.status = WorkflowStatus.FAILED
            record.finished_at = _utc_now()
            record.error_fingerprint = hashlib.sha256(traceback_text.encode("utf-8", errors="replace")).hexdigest()[:16]
            record.message = _redact(f"{type(exc).__name__}: {exc}")
            record.retryable = bool(retryable)
            self._emit(record, "finish")
            return _result(record)

    def get(self, action_id: str) -> WorkflowResult | None:
        with self._lock:
            record = self._records.get(action_id)
            return None if record is None else _result(record)

    def active(self) -> tuple[WorkflowResult, ...]:
        with self._lock:
            return tuple(_result(record) for record in self._records.values() if record.status is WorkflowStatus.RUNNING)

    def _running(self, action_id: str) -> _WorkflowRecord:
        record = self._records.get(action_id)
        if record is None:
            raise WorkflowTransitionError(f"Unknown workflow action: {action_id}")
        if record.status is not WorkflowStatus.RUNNING:
            raise WorkflowTransitionError(f"Workflow {action_id} already finished as {record.status.value}")
        return record

    def _emit(self, record: _WorkflowRecord, event: str, *, step: WorkflowStep | None = None) -> None:
        payload: dict[str, object] = {
            "event": event,
            "action_id": record.action_id,
            "workflow": record.workflow,
            "label": record.label,
            "status": record.status.value,
            "timestamp": _utc_now(),
            "message": record.message,
        }
        if step is not None:
            payload["step"] = asdict(step)
        if event == "finish":
            payload.update(
                {
                    "finished_at": record.finished_at,
                    "output_paths": list(record.output_paths),
                    "outputs": list(record.output_paths),
                    "error_fingerprint": record.error_fingerprint,
                    "retryable": record.retryable,
                    "cancel_requested": record.cancel_requested,
                    "cancelled_at": record.cancelled_at,
                }
            )
        payload.update(
            {
                "started_at": record.started_at,
                "finished_at": record.finished_at,
                "command_key": record.command_key,
                "input_hash": record.input_hash,
                "deduplication_key": record.deduplication_key,
                "cancel_requested": record.cancel_requested,
                "progress": record.progress,
                "outputs": list(record.output_paths),
            }
        )
        if self.log_path is not None:
            self._append(payload)
        try:
            self.event_logger(payload)
        except Exception:
            # Diagnostics must not turn a working action into a failed action.
            pass

    def _append(self, payload: dict[str, object]) -> None:
        if self.log_path is None:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_redact_value(payload), ensure_ascii=True, sort_keys=True) + "\n")
                handle.flush()
        except Exception:
            pass

    @staticmethod
    def _session_event_logger(payload: dict[str, object]) -> None:
        log_event(
            event_type=f"workflow_{payload.get('event', 'update')}",
            severity="error" if payload.get("status") == WorkflowStatus.FAILED.value else "info",
            action_id=str(payload.get("action_id") or ""),
            component="workflow",
            feature=str(payload.get("workflow") or ""),
            operation=str(payload.get("event") or ""),
            status=str(payload.get("status") or ""),
            user_message=str(payload.get("message") or ""),
            file_paths=payload.get("output_paths") or [],
            traceback_fingerprint=str(payload.get("error_fingerprint") or "") or None,
            input_summary={
                "command_key": payload.get("command_key"),
                "input_hash": payload.get("input_hash"),
                "deduplication_key": payload.get("deduplication_key"),
            },
            output_summary={
                "step": payload.get("step") or {},
                "progress": payload.get("progress"),
                "outputs": payload.get("outputs") or [],
                "cancel_requested": payload.get("cancel_requested", False),
            },
        )


def _result(record: _WorkflowRecord) -> WorkflowResult:
    return WorkflowResult(
        action_id=record.action_id,
        workflow=record.workflow,
        status=record.status,
        started_at=record.started_at,
        finished_at=record.finished_at,
        message=record.message,
        output_paths=record.output_paths,
        error_fingerprint=record.error_fingerprint,
        retryable=record.retryable,
        steps=tuple(record.steps),
        command_key=record.command_key,
        input_hash=record.input_hash,
        deduplication_key=record.deduplication_key,
        cancel_requested=record.cancel_requested,
        cancelled_at=record.cancelled_at,
        progress=record.progress,
    )


def _redact(value: str) -> str:
    return redact_text(value)


def _redact_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _input_hash(value: object | None) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
