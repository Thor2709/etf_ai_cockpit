"""Headless data workflows and the shared local writer guard.

Defaults: the root is ``core.paths.ROOT``; the exclusive lock is
``<root>/data/.headless-writer.lock`` and owner metadata is its ``.owner.json``
sidecar; lock acquisition fails immediately when another writer holds it; stale
owner recovery is recorded in ``<root>/data/operations/headless_writer_audit.jsonl``.
Scoreboard publication defaults to ``<root>/data/derived/scoreboard.parquet``.
The snapshot builder defaults to ``build_snapshot`` and the data service to
``DataService``; UI publication scope defaults to a no-op for headless callers.
Action IDs default to ``headless_refresh`` and ``headless_rescore``. Missing
snapshots and failed data-quality gates refuse publication. Missing inputs may
publish unavailable score rows without granting analysis or execution authority.
Status uses ``row_count=None`` when inputs cannot be read or are unavailable.
Storage roots are process-scoped: set ``ETF_COCKPIT_ROOT`` before importing
the application, as required by the persistence services. A different runtime
root is refused before any workflow writes; run separate roots in separate
processes. This also scopes scoring's implicit reads and trust-artifact writes.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Callable, Iterator, Protocol

from etf_cockpit.application.activity_results import ActivityUnavailableError
from etf_cockpit.application.data_service import DataService
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.core.file_guard import PersistentFileGuard
from etf_cockpit.core.paths import ROOT
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.timing import timed_step


_LOCAL_LOCKS: dict[Path, threading.Lock] = {}
_LOCAL_LOCKS_LOCK = threading.Lock()
_WRITER_CONTEXT = threading.local()


class HeadlessWriterBusyError(TimeoutError):
    """Another app or headless process currently owns the data writer slot."""


class SnapshotSession(Protocol):
    snapshot: object
    score_history_warning: str | None

    def activity_publication(self, expected_action_id: str | None = None):
        ...

    def _record_score_history_failure(self, exc: Exception, scoreboard_path: Path) -> None:
        ...


def _paths(root: Path | None) -> tuple[Path, Path, Path]:
    data_root = Path(root or ROOT).resolve() / "data"
    return (
        data_root / ".headless-writer.lock",
        data_root / ".headless-writer.lock.owner.json",
        data_root / "operations" / "headless_writer_audit.jsonl",
    )


def _local_lock(path: Path) -> threading.Lock:
    with _LOCAL_LOCKS_LOCK:
        return _LOCAL_LOCKS.setdefault(path, threading.Lock())


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True  # An inconclusive probe must never authorize stale-owner recovery.
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    """Query process state without sending a Windows termination signal."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        # ERROR_INVALID_PARAMETER means no such PID. Access denied and other
        # query failures leave ownership uncertain, so retain the live lock.
        return ctypes.get_last_error() != 87
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def require_storage_root(root: Path | None = None) -> Path:
    """Keep the writer lock on the root used by import-scoped persistence."""

    selected = Path(root or ROOT).resolve()
    if selected != ROOT.resolve():
        raise ValueError(
            "Storage root differs from the imported application root; set "
            "ETF_COCKPIT_ROOT before importing etf_cockpit in a separate process."
        )
    return selected


def _read_owner(path: Path) -> dict[str, object] | None:
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        record = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Headless writer owner metadata is corrupt; refusing to publish.") from exc
    if not isinstance(record, dict) or not isinstance(record.get("active"), bool):
        raise RuntimeError("Headless writer owner metadata is invalid; refusing to publish.")
    if record["active"] and (not isinstance(record.get("pid"), int) or isinstance(record.get("pid"), bool)):
        raise RuntimeError("Headless writer owner PID is invalid; refusing to publish.")
    return record


def _write_owner(path: Path, *, active: bool, root: Path) -> None:
    record = {
        "active": active,
        "pid": os.getpid(),
        "acquired_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "root": str(root),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _audit_recovery(path: Path, *, root: Path, stale_pid: int) -> None:
    record = {
        "event": "headless_writer_stale_lock_recovered",
        "stale_pid": stale_pid,
        "recovered_by_pid": os.getpid(),
        "root": str(root),
        "recovered_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def cross_process_writer_guard(root: Path | None = None) -> Iterator[None]:
    """Serialize app and headless writes, recovering only metadata for a dead PID."""

    resolved_root = Path(root or ROOT).resolve()
    lock_path, owner_path, audit_path = _paths(resolved_root)
    current_path = getattr(_WRITER_CONTEXT, "path", None)
    if current_path is not None:
        if current_path != lock_path:
            raise RuntimeError("A nested writer guard cannot change data roots.")
        _WRITER_CONTEXT.depth += 1
        try:
            yield
        finally:
            _WRITER_CONTEXT.depth -= 1
        return

    local_lock = _local_lock(lock_path)
    if not local_lock.acquire(blocking=False):
        raise HeadlessWriterBusyError("Another writer currently owns the local data root.")
    try:
        try:
            os_guard = PersistentFileGuard(lock_path, timeout_seconds=0.0)
            os_guard.acquire()
        except TimeoutError as exc:
            raise HeadlessWriterBusyError("Another process currently owns the local data root.") from exc
        try:
            owner = _read_owner(owner_path)
            if owner is not None and owner["active"]:
                stale_pid = int(owner["pid"])
                if _pid_is_alive(stale_pid):
                    raise HeadlessWriterBusyError(
                        "Writer metadata identifies a live owner; refusing to recover the lock."
                    )
                _audit_recovery(audit_path, root=resolved_root, stale_pid=stale_pid)
            _write_owner(owner_path, active=True, root=resolved_root)
            _WRITER_CONTEXT.path = lock_path
            _WRITER_CONTEXT.depth = 1
            try:
                yield
            finally:
                _WRITER_CONTEXT.path = None
                _WRITER_CONTEXT.depth = 0
                _write_owner(owner_path, active=False, root=resolved_root)
        finally:
            os_guard.release()
    finally:
        local_lock.release()


def _default_publication_scope(_expected_action_id: str | None = None):
    return nullcontext()


class HeadlessSession:
    """Use the same refresh, scoring and publication services without Flet."""

    def __init__(
        self,
        snapshot: object,
        *,
        root: Path | None = None,
        snapshot_builder: Callable[..., object] = build_snapshot,
        data_service_factory: Callable[[object], object] | None = None,
        publication_scope: Callable[[str | None], object] | None = None,
        snapshot_sink: Callable[[object], None] | None = None,
        score_history_warning: str | None = None,
        score_history_warning_getter: Callable[[], str | None] | None = None,
        score_history_warning_setter: Callable[[str | None], None] | None = None,
        score_history_failure_handler: Callable[[Exception, Path], None] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.root = Path(root or ROOT).resolve()
        self.snapshot_builder = snapshot_builder
        self.data_service_factory = data_service_factory or DataService
        self._publication_scope = publication_scope or _default_publication_scope
        self._snapshot_sink = snapshot_sink
        self._score_history_warning = score_history_warning
        self._score_history_warning_getter = score_history_warning_getter
        self._score_history_warning_setter = score_history_warning_setter
        self._score_history_failure_handler = score_history_failure_handler
        self._job_scheduler = None

    @property
    def score_history_warning(self) -> str | None:
        if self._score_history_warning_getter is not None:
            return self._score_history_warning_getter()
        return self._score_history_warning

    @score_history_warning.setter
    def score_history_warning(self, value: str | None) -> None:
        self._score_history_warning = value
        if self._score_history_warning_setter is not None:
            self._score_history_warning_setter(value)

    @contextmanager
    def activity_publication(self, expected_action_id: str | None = None):
        require_storage_root(self.root)
        with cross_process_writer_guard(self.root):
            with self._publication_scope(expected_action_id):
                yield

    def _set_snapshot(self, snapshot: object) -> None:
        self.snapshot = snapshot
        if self._snapshot_sink is not None:
            self._snapshot_sink(snapshot)

    def _record_score_history_failure(self, exc: Exception, scoreboard_path: Path) -> None:
        if self._score_history_failure_handler is not None:
            self._score_history_failure_handler(exc, scoreboard_path)
            return
        from etf_cockpit.application.scoreboard_publication import ScoreboardPublicationBindingError

        reason = redact_text(" ".join(f"{type(exc).__name__}: {exc}".split()))[:240]
        if isinstance(exc, ScoreboardPublicationBindingError):
            self.score_history_warning = (
                f"Scoreboard {scoreboard_path.name} was written, but its score-history publication binding "
                f"was not recorded ({reason}). Paper bot decisions for this publication are unavailable. "
                "Scores and actions are unchanged."
            )
            return
        self.score_history_warning = (
            f"Score history was not persisted ({reason}). Scoreboard {scoreboard_path.name} was written; "
            "score history, components, evidence ledger and feature drivers for this run are unavailable, not empty."
        )

    def refresh(self, *, action_id: str | None = None) -> str:
        """Refresh validated local data, rebuild the snapshot and publish its scoreboard."""

        require_storage_root(self.root)
        resolved_action_id = action_id or "headless_refresh"
        with cross_process_writer_guard(self.root):
            with timed_step(resolved_action_id, "yfinance_refresh"):
                service = self.data_service_factory(self.snapshot.config)
                message = service.refresh_yfinance_data(publish_guard=self.activity_publication)
                if not getattr(service, "last_operation_succeeded", True):
                    raise ActivityUnavailableError(str(message))
                self._set_snapshot(self.snapshot_builder(force_sample=False, publish_guard=self.activity_publication))
                self.publish()
                return str(message)

    def rescore(self, *, action_id: str | None = None) -> tuple[str, Path]:
        """Run the deterministic candidate analysis, rebuild the snapshot and publish scores."""

        require_storage_root(self.root)
        resolved_action_id = action_id or "headless_rescore"
        with cross_process_writer_guard(self.root):
            with timed_step(resolved_action_id, "algorithm_scores"):
                message = self.data_service_factory(self.snapshot.config).run_yfinance_candidate_analysis(
                    publish_guard=self.activity_publication
                )
                self._set_snapshot(self.snapshot_builder(force_sample=False, publish_guard=self.activity_publication))
                scoreboard_path = self.publish()
                return str(message), scoreboard_path

    def refresh_snapshot(self) -> object:
        """Rebuild local signals without initiating a provider refresh or scoreboard publish."""

        require_storage_root(self.root)
        with cross_process_writer_guard(self.root):
            self._set_snapshot(self.snapshot_builder(force_sample=False, publish_guard=self.activity_publication))
        return self.snapshot

    def publish(self) -> Path:
        """Publish the fail-closed canonical scoreboard for the current snapshot."""

        from etf_cockpit.application.scoreboard_publication import publish_scoreboard

        return publish_scoreboard(self, root=self.root)

    def status(self) -> dict[str, object]:
        """Return scoreboard availability without replacing missing values with zero."""

        from etf_cockpit.application.scoreboard_publication import scoreboard_status

        return scoreboard_status(root=self.root)

    def _scheduler(self):
        if self._job_scheduler is None:
            from etf_cockpit.core.job_scheduler import DurableJobScheduler

            self._job_scheduler = DurableJobScheduler(self.root, max_concurrency=1)
        return self._job_scheduler

    def submit_workflow(
        self,
        workflow_type: str,
        *,
        label: str,
        input_payload: dict[str, object],
        dedupe_key: str,
    ) -> str:
        """Submit one durable headless workflow through the typed application boundary."""

        import hashlib

        from etf_cockpit.application.api import LocalApplicationApi
        from etf_cockpit.application.contracts import SubmitWorkflowCommand

        require_storage_root(self.root)
        command_key = hashlib.sha256(f"{workflow_type}\0{dedupe_key}".encode("utf-8")).hexdigest()
        api = LocalApplicationApi(lambda: self.snapshot, scheduler=self._scheduler(), root=self.root)
        with cross_process_writer_guard(self.root):
            result = api.execute(
                SubmitWorkflowCommand(
                    idempotency_key=f"mcp-{command_key}",
                    workflow_type=workflow_type,
                    label=label,
                    input_payload=input_payload,
                    dedupe_key=dedupe_key,
                )
            )
        if result.status.value not in {"accepted", "replayed"} or not result.resource_id:
            raise RuntimeError(result.error_message or "The workflow could not be submitted.")
        return result.resource_id

    def get_workflow(self, workflow_id: str):
        """Read a durable workflow by workflow id or one of its job ids."""

        scheduler = self._scheduler()
        record = scheduler.get_workflow(workflow_id)
        if record is not None:
            return record
        job = scheduler.get_job(workflow_id)
        return scheduler.get_workflow(job.workflow_id) if job is not None else None

    def list_workflows(self, *, status: str | None, offset: int, limit: int):
        """Return a bounded workflow page from the durable local scheduler."""

        requested = max(1, min(int(offset) + int(limit), 200))
        rows = self._scheduler().list_workflows(limit=requested)
        if status is not None:
            rows = tuple(row for row in rows if str(getattr(row.status, "value", row.status)) == status)
        return rows[offset : offset + limit]

    def find_active_workflow(self, workflow_type: str, dedupe_prefix: str):
        """Find an active workflow through the durable local scheduler."""

        return self._scheduler().find_active_workflow(workflow_type, dedupe_prefix)

    def cancel_workflow(self, workflow_id: str, reason: str):
        """Cancel one durable workflow without changing its recorded history."""

        require_storage_root(self.root)
        record = self.get_workflow(workflow_id)
        if record is None:
            raise KeyError(f"workflow unavailable: {workflow_id}")
        with cross_process_writer_guard(self.root):
            return self._scheduler().cancel(record.workflow_id, message=reason)

    def run_next_workflow(self, *, workflow_id: str | None = None):
        """Run one queued workflow using the bounded local handler mapping."""

        from etf_cockpit.application.workflow_handlers import headless_workflow_handlers

        handlers = headless_workflow_handlers(lambda: self, include_paper=True)

        def dispatch(context):
            record = self.get_workflow(context.workflow_id)
            if record is None or record.workflow_type not in handlers:
                raise ValueError("No headless handler is registered for this workflow.")
            return handlers[record.workflow_type](context)

        require_storage_root(self.root)
        with cross_process_writer_guard(self.root):
            return self._scheduler().run_once(dispatch, workflow_id=workflow_id)


def load_monthly_decision_pack(snapshot: object, month: str) -> dict[str, object]:
    """Compose canonical candidate evidence for a bound month, without backdating.

    The session snapshot must belong to the requested month and have an explicit
    knowledge timestamp within the month's cutoff (or now for the current month).
    Portfolio services expose partial optimiser/cost/concentration evidence;
    return distributions, replay and account outcomes lack a candidate binding.
    Those sections remain unavailable. No source or derived artifacts are written.
    """
    from etf_cockpit.application.monthly_decision_template import (
        build_monthly_decision_template, monthly_decision_template_lines,
        unavailable_monthly_evidence,
    )
    from etf_cockpit.application.portfolio_sandbox import (
        analyse_portfolio_candidate, draft_portfolio_candidate,
    )

    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    cutoff = min(end, datetime.now(timezone.utc))
    names = ("alternatives", "expected_returns", "optimiser", "costs", "events",
             "forward_evidence", "paper_outcomes", "concentration", "assumptions")
    sections = {name: unavailable_monthly_evidence(f"{name}_evidence_not_bound_to_requested_month") for name in names}
    benchmark = None
    analysis = None
    try:
        as_of = datetime.fromisoformat(str(getattr(getattr(snapshot, "data_report", None), "as_of_date", None)))
        as_of = as_of.replace(tzinfo=timezone.utc) if as_of.tzinfo is None else as_of.astimezone(timezone.utc)
        known_at = datetime.fromisoformat(str(getattr(snapshot, "facts_known_at", None)).replace("Z", "+00:00"))
        if known_at.tzinfo is None or not start <= as_of < end or not as_of <= known_at <= cutoff or known_at >= end:
            raise ValueError("snapshot_not_known_within_requested_month")
        candidate = draft_portfolio_candidate(snapshot)
        analysis = analyse_portfolio_candidate(snapshot, candidate)
        binding = analysis.snapshot_binding
        if binding is None or analysis.source_stale or not binding.source_checksum:
            raise ValueError("portfolio_snapshot_binding_unavailable")
        benchmark = analysis.service_evidence.get("benchmark_reference")
        optimiser = analysis.service_evidence.get("optimiser")
        if isinstance(optimiser, dict) and optimiser.get("status") not in {None, "unavailable"}:
            sections["optimiser"] = {
                "status": "partial", "reason": "solver_binding_diagnostics_unavailable",
                "source_id": candidate.candidate_id, "method": optimiser.get("method"),
                "solution": {key: optimiser[key] for key in ("status", "weights", "feasible", "warnings") if key in optimiser},
                "constraints": {"status": "partial", "rows": [
                    {"name": row.name, "current_value": row.current_value, "target_value": row.target_value,
                     "limit": row.limit, "status": row.status, "reason": row.reason}
                    for row in analysis.constraints
                ]},
            }
        cost = analysis.cost
        sections["costs"] = {
            "status": "partial", "reason": "portfolio_cost_projection_has_partial_source_provenance",
            "model_id": cost.model_id, "source_id": candidate.candidate_id,
            "components": [{"estimate_id": item.estimate_id, "instrument_id": item.instrument_id,
                            "order_value_eur": item.order_value_eur, "cost_eur": item.total_cost_eur,
                            "cost_bps": item.total_cost_bps} for item in cost.estimates],
            "total": {"order_value_eur": cost.total_order_value_eur, "cost_eur": cost.total_cost_eur,
                      "cost_bps": cost.weighted_cost_bps},
        }
        if analysis.sector_exposure:
            sections["concentration"] = {
                "status": "partial", "reason": "theme_exposure_unavailable",
                "sector": {"status": "partial", "source_id": candidate.candidate_id,
                           "exposures": [{"label": row.bucket, "weight": row.target_weight} for row in analysis.sector_exposure]},
                "theme": unavailable_monthly_evidence("theme_exposure_unavailable"),
            }
        sections["assumptions"] = {
            "status": "partial", "reason": "candidate_assumptions_have_partial_source_provenance",
            "source_id": candidate.candidate_id,
            "values": {"rebalance_cadence": "monthly", "execution_assumption": "next_session",
                       "candidate_id": candidate.candidate_id, "candidate_source_revision": candidate.source_revision},
        }
    except (AttributeError, OSError, TypeError, ValueError, KeyError):
        # A current snapshot cannot stand in for a missing historical snapshot.
        sections = {name: unavailable_monthly_evidence(f"{name}_evidence_not_bound_to_requested_month") for name in names}
        benchmark = None
    template = build_monthly_decision_template(
        benchmark_reference=benchmark,
        benchmark_registry=getattr(snapshot, "benchmark_reference_registry", None),
        **sections, source=f"mcp_local_evidence:{month}",
    )
    return {"month": month, **template.projection(), "lines": list(monthly_decision_template_lines(template))}


__all__ = [
    "HeadlessSession",
    "load_monthly_decision_pack",
    "HeadlessWriterBusyError",
    "cross_process_writer_guard",
]
