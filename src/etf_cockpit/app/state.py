from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable, TypeVar, cast

from etf_cockpit.core.config import AppConfig, save_provider_settings
from etf_cockpit.core.atomic_io import atomic_write_bytes, sha256_file
from etf_cockpit.core.migrations import run_startup_migrations
from etf_cockpit.core.paths import CLEAN_DIR, FILINGS_STATEMENTS_PATH, RAW_DIR, ROOT, STATEMENT_FACTS_PATH
from etf_cockpit.core.session_log import SESSION_LOG_PATH, log_event, redact_text
from etf_cockpit.core.errors import ErrorStore, classify_exception
from etf_cockpit.core.timing import timed_step
from etf_cockpit.core.workflow import PublicationScopeFactory, WorkflowController, WorkflowStatus, WorkflowStep, WorkflowTransitionError, publication_scope
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.core.job_scheduler import DurableJobScheduler
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH, refresh_static_trust_artifacts, write_trust_artifacts_for_scores
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.data.esef_provider import EsefProviderUnavailable, FilingsXbrlOrgProvider
from etf_cockpit.data.oam_adapters import (
    CompaniesHouseFilingAdapter,
    OAMDiscoveryRequest,
    archive_manual_official_filing,
    oam_adapter_for_country,
    write_filing_coverage,
    write_oam_discovery_registry,
)
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.data.classification import classification_score_state
from etf_cockpit.parsers.contracts import RawDocument, load_fixture_manifest
from etf_cockpit.parsers.esef_ixbrl import parse_esef_package
from etf_cockpit.parsers.sec_facts import parse_companyfacts, statement_facts_from_esef, write_statement_evidence
from etf_cockpit.features.regime import build_market_regime, write_market_regime
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.models.calibration import evaluate_forecast_calibration, load_forecast_history, write_forecast_calibration
from etf_cockpit.operations.event_store import current_activity_view, load_events_with_tail_recovery
from etf_cockpit.portfolio.review_reports import create_portfolio_review_report
from etf_cockpit.services import ChatGPTBridge, CockpitSnapshot, DataService, build_snapshot
from etf_cockpit.signals.simple_scores import SimpleInstrumentScore, build_simple_instrument_scores, load_latest_candidate_report, simple_scoreboard_frame, write_simple_scoreboard
from etf_cockpit.app import theme


# Compatibility seam for existing callers and tests. This is the session trace,
# not a second mutable activity store.
ACTIVITY_LOG_PATH = SESSION_LOG_PATH

_TrackedResult = TypeVar("_TrackedResult")


class ActivityUnavailableError(RuntimeError):
    """A local action returned a readable unavailable result without raising."""


def _legacy_unavailable(state: "AppState", message: str, cause: BaseException | None = None) -> str:
    """Keep lightweight direct callers on the historical string-return contract."""

    if not hasattr(state, "_activity_lock"):
        return message
    if cause is None:
        raise ActivityUnavailableError(message)
    raise ActivityUnavailableError(message) from cause


def activity_result_error(result: object) -> str | None:
    """Return a bounded typed failure message for normal-return result objects."""

    ok = getattr(result, "ok", None)
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", status)
    failed = ok is False or status_value in {"failed", "unavailable", "error", "blocked"}
    if not failed:
        return None
    message = getattr(result, "error", None) or getattr(result, "message", None) or status_value
    return str(message or "Action was unavailable.").strip()


def _tracked_activity(label: str, step: str) -> Callable[[Callable[..., _TrackedResult]], Callable[..., _TrackedResult]]:
    """Give direct callers the same lifecycle as callbacks using the dashboard helper.

    Page callbacks may already own an activity.  In that case this decorator only
    publishes the nested step and output; the outer callback remains responsible
    for the terminal result.
    """

    def decorate(function: Callable[..., _TrackedResult]) -> Callable[..., _TrackedResult]:
        @wraps(function)
        def wrapped(self: "AppState", *args: Any, **kwargs: Any) -> _TrackedResult:
            shared_action_id = self.shared_activity_id
            owns_activity = shared_action_id is None and self.current_activity is None
            if shared_action_id is not None:
                entry = self.require_activity(shared_action_id)
                self.update_activity(step, expected_action_id=entry.action_id)
            elif owns_activity:
                entry = self.begin_activity(label, step)
            else:
                raise WorkflowTransitionError(
                    f"{self.current_activity.label if self.current_activity else 'Another action'} owns the activity slot."
                )
            action_id = entry.action_id
            try:
                with self.share_activity(action_id):
                    result = function(self, *args, **kwargs)
                failure = activity_result_error(result)
                if failure:
                    raise ActivityUnavailableError(failure)
                output_path = result if isinstance(result, Path) else None
                if self.current_activity is not None and output_path is not None:
                    self.update_activity("Writing output", output_path=output_path, expected_action_id=action_id)
                if owns_activity:
                    message = str(result).strip() if result is not None else str(self.last_message or "").strip()
                    if not message:
                        raise RuntimeError("Tracked action completed without a readable result message.")
                    self.finish_activity(message, output_path=output_path, label=label, expected_action_id=action_id)
                return result
            except Exception as exc:
                if owns_activity and not self.activity_was_cancelled(action_id):
                    self.fail_activity(
                        label,
                        exc,
                        retry_callback=lambda: wrapped(self, *args, **kwargs),
                        expected_action_id=action_id,
                    )
                raise
            finally:
                if self.activity_was_cancelled(action_id):
                    self.restore_cancelled_activity_message(action_id)
                if owns_activity and self.activity_was_cancelled(action_id):
                    self.release_activity(action_id)

        return cast(Callable[..., _TrackedResult], wrapped)

    return decorate


def _signal_classification_is_current(signal: object, *, root: Path) -> bool:
    instrument_id = str(getattr(signal, "etf_id", "") or "").strip()
    if not instrument_id:
        return False
    metrics = getattr(signal, "supporting_metrics", {})
    stored_token = (
        str(metrics.get("classification_invalidation_hash") or "unavailable")
        if isinstance(metrics, dict)
        else "unavailable"
    )
    state = classification_score_state(root, instrument_id)
    if str(state.get("status")) == "unavailable":
        return False
    current_token = str(state.get("invalidation_token") or "unavailable")
    token_is_bound = stored_token not in {"", "none", "nan", "unavailable"}
    return not (
        (token_is_bound and stored_token != current_token)
        or (bool(state.get("invalidated_score_keys")) and stored_token != current_token)
    )


@dataclass
class ActivityEntry:
    label: str
    status: str
    step: str
    started_at: str
    action_id: str = ""
    parent_action_id: str | None = None
    finished_at: str | None = None
    message: str = ""
    output_path: str | None = None
    completed_units: int = 0
    total_units: int | None = None
    error: str | None = None

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status,
            "step": self.step,
            "started_at": self.started_at,
            "action_id": self.action_id,
            "parent_action_id": self.parent_action_id,
            "finished_at": self.finished_at,
            "message": self.message,
            "output_path": self.output_path,
            "completed_units": self.completed_units,
            "total_units": self.total_units,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActivityEntry":
        return cls(
            label=str(data.get("label") or "Unknown action"),
            status=str(data.get("status") or "unknown"),
            step=str(data.get("step") or ""),
            started_at=str(data.get("started_at") or ""),
            action_id=str(data.get("action_id") or ""),
            parent_action_id=data.get("parent_action_id"),
            finished_at=data.get("finished_at"),
            message=str(data.get("message") or ""),
            output_path=data.get("output_path"),
            completed_units=int(data.get("completed_units") or 0),
            total_units=None if data.get("total_units") is None else int(data.get("total_units")),
            error=None if data.get("error") is None else str(data.get("error")),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_recent_activity(limit: int = 8) -> list[ActivityEntry]:
    try:
        events, _ = load_events_with_tail_recovery(ACTIVITY_LOG_PATH)
    except Exception:
        return []
    activity_terminal_events = {"activity_complete", "activity_failed", "activity_cancelled", "activity_interrupted"}
    relevant_events = {
        "workflow_start",
        "workflow_step",
        "workflow_finish",
        "activity_update",
        *activity_terminal_events,
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if not event.action_id:
            continue
        data = event.model_dump(mode="json")
        if event.event_type in relevant_events:
            grouped.setdefault(str(event.action_id), []).append(data)

    entries: list[ActivityEntry] = []
    for action_events in grouped.values():
        workflow_start = next((item for item in action_events if item.get("event_type") == "workflow_start"), None)
        workflow_finish = next((item for item in reversed(action_events) if item.get("event_type") == "workflow_finish"), None)
        workflow_step = next((item for item in reversed(action_events) if item.get("event_type") == "workflow_step"), None)
        activity_terminals = [item for item in action_events if item.get("event_type") in activity_terminal_events]
        if workflow_finish is not None:
            workflow_status = str(workflow_finish.get("status") or "unknown")
            compatible_statuses = {workflow_status}
            if workflow_status in {"unavailable", "manual_review"}:
                compatible_statuses.add("failed")
            activity_terminal = next(
                (item for item in reversed(activity_terminals) if item.get("status") in compatible_statuses),
                None,
            )
        elif workflow_start is not None:
            activity_terminal = next(
                (item for item in reversed(activity_terminals) if item.get("event_type") == "activity_interrupted"),
                None,
            )
        else:
            activity_terminal = activity_terminals[-1] if activity_terminals else None
        latest_update = next((item for item in reversed(action_events) if item.get("event_type") == "activity_update"), {})
        latest_summary = latest_update.get("output_summary") or {}
        terminal_summary = (activity_terminal or {}).get("output_summary") or {}
        workflow_step_summary = (workflow_step or {}).get("output_summary") or {}
        workflow_step_data = workflow_step_summary.get("step") or {}
        lifecycle_start = workflow_start or action_events[0]
        lifecycle_terminal = workflow_finish or activity_terminal
        interrupted = workflow_start is not None and workflow_finish is None
        if workflow_finish is not None:
            status = str(workflow_finish.get("status") or "unknown")
        elif interrupted:
            status = "interrupted"
        elif activity_terminal is not None:
            status = str(activity_terminal.get("status") or "unknown")
        else:
            status = "interrupted"
            interrupted = True
        file_paths = (workflow_finish or activity_terminal or {}).get("file_paths") or []
        workflow_outputs = ((workflow_finish or {}).get("output_summary") or {}).get("outputs") or []
        output_path = terminal_summary.get("output_path") or (file_paths[0] if file_paths else None)
        if output_path is None and workflow_outputs:
            output_path = workflow_outputs[0]
        interruption_message = "Application restarted before this action reached a terminal state."
        terminal_message = str(
            (activity_terminal or {}).get("user_message")
            or terminal_summary.get("message")
            or (workflow_finish or {}).get("user_message")
            or latest_summary.get("message")
            or (workflow_step or {}).get("user_message")
            or ""
        )
        default_step = "Interrupted" if interrupted else "Cancelled" if status == "cancelled" else "Failed" if status in {"failed", "unavailable"} else "Complete"
        step = str(terminal_summary.get("step") or latest_summary.get("step") or workflow_step_data.get("key") or workflow_step_data.get("label") or default_step)
        completed_units = int(terminal_summary.get("completed_units", latest_summary.get("completed_units", workflow_step_data.get("completed_units", 0))) or 0)
        total_value = terminal_summary.get("total_units", latest_summary.get("total_units", workflow_step_data.get("total_units")))
        entries.append(
            ActivityEntry(
                label=str((activity_terminal or {}).get("button_label") or latest_update.get("button_label") or lifecycle_start.get("feature") or "Workflow action"),
                status=status,
                step=step,
                started_at=str(terminal_summary.get("started_at") or latest_summary.get("started_at") or lifecycle_start.get("timestamp_local") or lifecycle_start.get("timestamp_utc") or ""),
                action_id=str(lifecycle_start.get("action_id") or ""),
                finished_at=None if interrupted else str(terminal_summary.get("finished_at") or (lifecycle_terminal or {}).get("timestamp_local") or (lifecycle_terminal or {}).get("timestamp_utc") or ""),
                message=interruption_message if interrupted else terminal_message,
                output_path=None if output_path is None else str(output_path),
                completed_units=completed_units,
                total_units=None if total_value is None else int(total_value),
                error=interruption_message if interrupted else str(terminal_summary.get("error") or terminal_message) if status in {"failed", "unavailable"} else None,
            )
        )
        if interrupted and not any(item.get("event_type") == "activity_interrupted" for item in action_events):
            recovered = entries[-1]
            log_event(
                event_type="activity_interrupted",
                severity="warning",
                action_id=recovered.action_id,
                component="app_state",
                button_label=recovered.label,
                feature=recovered.label,
                operation="recover_interrupted_activity",
                status="interrupted",
                file_paths=recovered.output_path,
                output_summary=recovered.to_dict(),
                user_message=recovered.message,
                path=ACTIVITY_LOG_PATH,
            )
    return entries[-limit:]


@dataclass
class AppState:
    snapshot: CockpitSnapshot
    selected_etf: str
    last_message: str = "Ready"
    last_export_path: Path | None = None
    current_activity: ActivityEntry | None = None
    recent_activity: list[ActivityEntry] = field(default_factory=list)
    workflow_controller: WorkflowController = field(default_factory=WorkflowController, repr=False)
    error_store: ErrorStore = field(default_factory=ErrorStore, repr=False)
    _activity_context: threading.local = field(default_factory=threading.local, repr=False)
    _activity_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    universe_cache_revision: str = ""
    selected_instrument_score: SimpleInstrumentScore | None = None
    financial_projection: dict[str, object] | None = None
    real_asset_projection: dict[str, object] | None = None
    cyclical_projection: dict[str, object] | None = None
    cyclical_source_digest: str | None = None
    innovation_projection: dict[str, object] | None = None
    innovation_source_digest: str | None = None
    evidence_mode: str = "default"
    application_api: LocalApplicationApi = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.refresh_runtime_profile()

    def refresh_runtime_profile(self, resource_profile: str | None = None) -> str:
        """Rebuild the local runtime boundary from persisted onboarding hardware."""

        selected = str(resource_profile or "").strip().casefold()
        if not selected:
            try:
                from etf_cockpit.app.pages.onboarding import load_onboarding

                selected = load_onboarding(ROOT).hardware_profile
            except (OSError, ValueError, TypeError):
                selected = "auto"
        scheduler = DurableJobScheduler(ROOT, resource_profile=selected)
        self.application_api = LocalApplicationApi(
            lambda: self.snapshot,
            root=ROOT,
            scheduler=scheduler,
        )
        return scheduler.resource_policy.requested_profile

    def set_evidence_mode(self, mode: str) -> str:
        """Set the visible evidence density without changing authority."""

        value = str(mode or "").strip().lower()
        if value not in theme.EVIDENCE_MODES:
            raise ValueError(f"Unsupported evidence mode: {mode}")
        self.evidence_mode = value
        self.last_message = theme.EVIDENCE_MODE_LABELS[value]
        return value

    @classmethod
    def load(cls) -> "AppState":
        with timed_step("startup", "migrations"):
            run_startup_migrations()
        with timed_step("startup", "snapshot"):
            snapshot = build_snapshot()
        try:
            refresh_static_trust_artifacts(snapshot.config)
        except Exception:
            pass
        state = cls(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf, recent_activity=_read_recent_activity())
        state.snapshot.signals = [
            signal for signal in state.snapshot.signals
            if _signal_classification_is_current(signal, root=ROOT)
        ]
        return state

    def invalidate_classification_scores(self, instrument_id: str, *, root: Path | None = None) -> None:
        """Remove stale in-memory score consumers after a saved override."""

        canonical_id = str(instrument_id or "").strip()
        if not canonical_id:
            return
        canonical_root = Path(root) if root is not None else ROOT
        self.snapshot.signals = [
            signal for signal in self.snapshot.signals
            if str(getattr(signal, "etf_id", "")).strip() != canonical_id
            or _signal_classification_is_current(signal, root=canonical_root)
        ]
        if (
            self.selected_instrument_score is not None
            and self.selected_instrument_score.display_id == canonical_id
        ):
            self.selected_instrument_score = None
        self.last_message = (
            f"Classification-dependent scores for {canonical_id} are unavailable until recomputed."
        )

    def apply_universe_config(self, config: AppConfig, revision: str) -> None:
        """Apply a saved local universe and invalidate derived cache views.

        This only changes in-memory configuration and filters cached local
        frames; it never starts a provider, model, forecast or broker workflow.
        """

        self.snapshot.config = config
        self.snapshot.universe_revision = revision
        self.universe_cache_revision = revision
        enabled = set(config.universe.enabled_ids)
        for attribute in ("prices", "holdings", "features", "latest_features"):
            frame = getattr(self.snapshot, attribute, None)
            if frame is not None and hasattr(frame, "columns") and "etf_id" in frame.columns:
                setattr(self.snapshot, attribute, frame[frame["etf_id"].astype(str).isin(enabled)].copy())
        self.snapshot.signals = [signal for signal in self.snapshot.signals if signal.etf_id in enabled]
        forecasts = self.snapshot.forecasts
        if forecasts is not None and hasattr(forecasts, "columns") and "etf_id" in forecasts.columns:
            self.snapshot.forecasts = forecasts[forecasts["etf_id"].astype(str).isin(enabled)].copy()
        backtest = getattr(self.snapshot, "backtest", None)
        if backtest is not None:
            try:
                self.snapshot.backtest = replace(
                    backtest,
                    results=backtest.results.iloc[0:0].copy(),
                    equity_curves=backtest.equity_curves.iloc[0:0].copy(),
                    trade_log=backtest.trade_log.iloc[0:0].copy(),
                    signal_log=backtest.signal_log.iloc[0:0].copy(),
                    quality_label="stale_universe",
                    quality_notes=["Cached backtest invalidated because the configured universe revision changed."],
                )
            except (AttributeError, TypeError):
                # Lightweight embedding snapshots may not carry a full report.
                self.snapshot.backtest = None

    @property
    def shared_activity_id(self) -> str | None:
        return getattr(self._activity_context, "action_id", None)

    @contextmanager
    def share_activity(self, action_id: str):
        """Explicitly bind a nested callback to the activity it may mutate."""

        self.require_activity(action_id)
        previous = self.shared_activity_id
        self._activity_context.action_id = action_id
        try:
            yield
        finally:
            self._activity_context.action_id = previous

    def require_activity(self, expected_action_id: str | None) -> ActivityEntry:
        with self._activity_lock:
            entry = self.current_activity
            if entry is None:
                raise WorkflowTransitionError("No running activity owns this publication.")
            resolved_action_id = expected_action_id or self.shared_activity_id
            if not resolved_action_id or entry.action_id != resolved_action_id:
                raise WorkflowTransitionError("The running activity is owned by another action.")
            result = self.workflow_controller.get(resolved_action_id)
            if result is None or result.status is not WorkflowStatus.RUNNING or result.cancel_requested:
                raise WorkflowTransitionError(f"Workflow {expected_action_id} is no longer publishable.")
            return entry

    def activity_was_cancelled(self, action_id: str) -> bool:
        result = self.workflow_controller.get(action_id)
        return bool(result and result.status is WorkflowStatus.CANCELLED)

    def restore_cancelled_activity_message(self, action_id: str) -> str | None:
        """Restore the canonical cancellation message after a worker stops publishing."""

        with self._activity_lock:
            result = self.workflow_controller.get(action_id)
            if result is None or result.status is not WorkflowStatus.CANCELLED:
                return None
            message = result.message
            entry = next(
                (item for item in reversed(self.recent_activity) if item.action_id == action_id),
                None,
            )
            if entry is not None:
                entry.status = WorkflowStatus.CANCELLED.value
                entry.step = "Cancelled"
                entry.message = message
            if self.current_activity is not None and self.current_activity.action_id == action_id:
                self.current_activity.status = WorkflowStatus.CANCELLED.value
                self.current_activity.step = "Cancelled"
                self.current_activity.message = message
            self.last_message = message
            return message

    def assert_activity_publishable(self, expected_action_id: str | None = None) -> str:
        action_id = expected_action_id or self.shared_activity_id
        return self.require_activity(action_id).action_id

    def _record_activity_output(self, step: str, path: Path | str) -> None:
        action_id = getattr(getattr(self, "_activity_context", None), "action_id", None)
        if action_id is not None:
            self.update_activity(step, output_path=path, expected_action_id=action_id)

    @contextmanager
    def activity_publication(self, expected_action_id: str | None = None):
        """Authorize and hold ownership for exactly one durable publication."""

        with self._activity_lock:
            self.require_activity(expected_action_id or self.shared_activity_id)
            yield

    def begin_activity(self, label: str, step: str | None = None) -> ActivityEntry:
        with self._activity_lock:
            if self.current_activity is not None:
                raise WorkflowTransitionError(f"{self.current_activity.label} already owns the activity slot.")
            action_id = self.workflow_controller.start(label, label)
            entry = ActivityEntry(
                label=label,
                status="running",
                step=step or label,
                started_at=_utc_now(),
                action_id=action_id,
                message=f"{label} started.",
            )
            self.current_activity = entry
            self.last_message = entry.message
        log_event(
            event_type="button_click",
            severity="info",
            action_id=entry.action_id,
            component="app_state",
            button_label=label,
            feature=label,
            operation="begin_activity",
            status="started",
            user_message=entry.message,
            path=ACTIVITY_LOG_PATH,
        )
        log_event(
            event_type="activity_update",
            severity="info",
            action_id=entry.action_id,
            component="app_state",
            button_label=label,
            feature=label,
            operation="activity_start",
            status="running",
            output_summary={"step": entry.step, "started_at": entry.started_at},
            path=ACTIVITY_LOG_PATH,
        )
        return entry

    def update_activity(
        self,
        step: str,
        message: str | None = None,
        *,
        completed_units: int = 0,
        total_units: int | None = None,
        output_path: Path | str | None = None,
        expected_action_id: str | None = None,
    ) -> None:
        with self._activity_lock:
            entry = self.require_activity(expected_action_id or self.shared_activity_id)
            next_completed = max(0, int(completed_units))
            next_total = None if total_units is None else max(0, int(total_units))
            next_output = entry.output_path if output_path is None else str(output_path)
            next_message = entry.message if message is None else message
            with timed_step(entry.action_id, step):
                self.workflow_controller.step(
                    entry.action_id,
                    WorkflowStep(step, next_message or step, next_completed, next_total),
                )
            entry.step = step
            entry.completed_units = next_completed
            entry.total_units = next_total
            entry.output_path = next_output
            if message is not None:
                entry.message = message
            self.last_message = message if message is not None else step
            logged_message = self.last_message
            logged_output = entry.output_path
        log_event(
            event_type="activity_update",
            severity="info",
            action_id=entry.action_id,
            component="app_state",
            button_label=entry.label,
            feature=entry.label,
            operation="activity_step",
            status="running",
            output_summary={
                "step": step,
                "message": logged_message,
                "completed_units": next_completed,
                "total_units": next_total,
                "output_path": logged_output,
            },
            path=ACTIVITY_LOG_PATH,
        )

    def finish_activity(self, message: str, output_path: Path | str | None = None, label: str | None = None, *, expected_action_id: str | None = None) -> ActivityEntry:
        with self._activity_lock:
            entry = self.require_activity(expected_action_id or self.shared_activity_id)
            resolved_output_path = entry.output_path if output_path is None else str(output_path)
            result = self.workflow_controller.finish(
                entry.action_id,
                WorkflowStatus.SUCCESS,
                message,
                () if resolved_output_path is None else (resolved_output_path,),
            )
            entry.status = "success"
            entry.step = "Complete"
            entry.finished_at = _utc_now()
            entry.message = result.message
            entry.output_path = resolved_output_path
            entry.error = None
            self.current_activity = None
            self.last_message = message
            self.recent_activity = (self.recent_activity + [entry])[-8:]
        log_event(
            event_type="activity_complete",
            severity="info",
            action_id=entry.action_id,
            component="app_state",
            button_label=entry.label,
            feature=entry.label,
            operation="finish_activity",
            status="success",
            file_paths=entry.output_path,
            output_summary={
                "step": entry.step,
                "message": entry.message,
                "started_at": entry.started_at,
                "finished_at": entry.finished_at,
                "completed_units": entry.completed_units,
                "total_units": entry.total_units,
                "output_path": entry.output_path,
            },
            user_message=message,
            path=ACTIVITY_LOG_PATH,
        )
        return entry

    def fail_activity(
        self,
        label: str,
        exc: Exception,
        *,
        retry_callback=None,
        expected_action_id: str | None = None,
    ) -> ActivityEntry:
        with self._activity_lock:
            entry = self.require_activity(expected_action_id or self.shared_activity_id)
            _, retryable = classify_exception(exc)
            result = self.workflow_controller.fail(entry.action_id, exc, retryable=retryable)
            entry.status = "failed"
            entry.step = "Failed"
            entry.finished_at = _utc_now()
            entry.message = f"{label} failed: {result.message}"
            entry.error = result.message
            self.current_activity = None
            self.last_message = entry.message
            self.recent_activity = (self.recent_activity + [entry])[-8:]
        self.error_store.record_exception(
            action_id=entry.action_id,
            exc=exc,
            retry_callback=retry_callback,
            user_message=entry.message,
        )
        log_event(
            event_type="activity_failed",
            severity="error",
            action_id=entry.action_id,
            component="app_state",
            button_label=entry.label,
            feature=entry.label,
            operation="fail_activity",
            status="failed",
            file_paths=entry.output_path,
            exception_type=type(exc).__name__,
            exception_message_redacted=result.message,
            traceback_fingerprint=result.error_fingerprint,
            output_summary={
                "step": entry.step,
                "message": entry.message,
                "error": entry.error,
                "started_at": entry.started_at,
                "finished_at": entry.finished_at,
                "completed_units": entry.completed_units,
                "total_units": entry.total_units,
                "output_path": entry.output_path,
            },
            user_message=entry.message,
            path=ACTIVITY_LOG_PATH,
        )
        return entry

    def cancel_activity(self, message: str = "Cancelled by user", *, expected_action_id: str | None = None) -> ActivityEntry | None:
        """Request cancellation and publish a terminal, readable activity state."""
        with self._activity_lock:
            entry = self.current_activity
            if entry is None:
                return None
            if expected_action_id is not None and entry.action_id != expected_action_id:
                raise WorkflowTransitionError("The requested activity is owned by another action.")
            result = self.workflow_controller.cancel(entry.action_id, message)
            entry.status = result.status.value
            entry.step = "Cancelled"
            entry.finished_at = _utc_now()
            entry.message = result.message
            self.last_message = result.message
            self.recent_activity = (self.recent_activity + [entry])[-8:]
        log_event(
            event_type="activity_cancelled",
            severity="info",
            action_id=entry.action_id,
            component="app_state",
            button_label=entry.label,
            feature=entry.label,
            operation="cancel_activity",
            status=result.status.value,
            user_message=result.message,
            path=ACTIVITY_LOG_PATH,
        )
        return entry

    def release_activity(self, expected_action_id: str) -> None:
        """Release a terminal activity reservation after its owning callback exits."""

        with self._activity_lock:
            entry = self.current_activity
            if entry is None or entry.action_id != expected_action_id:
                return
            result = self.workflow_controller.get(expected_action_id)
            if result is not None and result.status is not WorkflowStatus.RUNNING:
                self.current_activity = None

    def current_activity_view(self):
        """Project the latest visible workflow state from the session trace."""
        try:
            events, _ = load_events_with_tail_recovery(ACTIVITY_LOG_PATH)
        except Exception:
            events = []
        return current_activity_view(events)

    @_tracked_activity("Refresh sample data", "Refreshing local sample data")
    def refresh_sample_data(self) -> None:
        self.snapshot = build_snapshot(force_sample=True, publish_guard=self.activity_publication)
        self.selected_etf = self.snapshot.config.ui.default_etf
        self.last_message = "Sample data regenerated and signals refreshed."

    @_tracked_activity("Validate current data", "Running dry-run validation")
    def renew_data_dry_run(self) -> str:
        message = DataService(self.snapshot.config).dry_run_update()
        self.last_message = "Renew data dry run completed."
        return message

    @_tracked_activity("Check API/yfinance provider", "Checking provider configuration")
    def renew_data_api_status(self) -> str:
        service = DataService(self.snapshot.config)
        message = redact_text(service.api_update_status(publish_guard=self.activity_publication))
        self.last_message = message
        if not service.last_operation_succeeded:
            raise ActivityUnavailableError(message)
        self.snapshot = build_snapshot(force_sample=False, publish_guard=self.activity_publication)
        return message

    @_tracked_activity("Refresh yfinance data", "Fetching adjusted yfinance prices")
    def refresh_yfinance_data(self) -> str:
        action_id = self.current_activity.action_id if self.current_activity else "yfinance"
        with timed_step(action_id, "yfinance_refresh"):
            service = DataService(self.snapshot.config)
            message = service.refresh_yfinance_data(publish_guard=self.activity_publication)
            if getattr(service, "last_operation_succeeded", True):
                self.snapshot = build_snapshot(force_sample=False, publish_guard=self.activity_publication)
                self._write_current_scoreboard()
                self.last_message = "YFinance data refreshed."
            else:
                self.last_message = message
                raise ActivityUnavailableError(message)
            return message

    @_tracked_activity("Run algorithms", "Running deterministic algorithms")
    def run_algorithm_scores(self) -> str:
        action_id = self.current_activity.action_id if self.current_activity else "algorithms"
        with timed_step(action_id, "algorithm_scores"):
            message = DataService(self.snapshot.config).run_yfinance_candidate_analysis(
                publish_guard=self.activity_publication
            )
            self.snapshot = build_snapshot(force_sample=False, publish_guard=self.activity_publication)
            scoreboard_path = self._write_current_scoreboard()
            self.last_message = "Algorithms refreshed from yfinance data."
            summary = message.split(" Report:", 1)[0]
            return f"{summary}. Scoreboard updated: {scoreboard_path.name}."

    @_tracked_activity("Run forecasting models", "Running baseline forecasts")
    def run_forecasting_models(self) -> str:
        action_id = self.current_activity.action_id if self.current_activity else "forecasts"
        with timed_step(action_id, "forecast_models"):
            service = DataService(self.snapshot.config)
            message = service.run_yfinance_forecasts(
                horizons=[60],
                live_optional_models=False,
                progress_callback=lambda stage, completed, total: self.update_activity(
                    stage,
                    completed_units=completed,
                    total_units=total,
                ),
                publish_guard=self.activity_publication,
            )
            if not getattr(service, "last_operation_succeeded", True):
                self.last_message = message
                raise ActivityUnavailableError(message)
            try:
                self.snapshot = build_snapshot(force_sample=False, publish_guard=self.activity_publication)
            except TypeError as exc:
                if "publish_guard" not in str(exc):
                    raise
                self.snapshot = build_snapshot(force_sample=False)
            scoreboard_path = self._write_current_scoreboard()
            self.update_activity("Forecasts and scoreboard complete", completed_units=4, total_units=4, output_path=scoreboard_path)
            self.last_message = "Fast forecasts refreshed from yfinance data for the 60-trading-day scoring horizon."
            summary = "; ".join(line.split(". Output:", 1)[0] for line in message.splitlines() if line.strip())
            return f"{summary}. Optional TimesFM/Toto live models are kept out of the main workflow if they are not already cached. Scoreboard updated: {scoreboard_path.name}."

    @_tracked_activity("Rollback prices", "Searching previous clean price snapshot")
    def rollback_latest_prices(self) -> str:
        message = DataService(self.snapshot.config).rollback_latest_price_import(publish_guard=self.activity_publication)
        self.last_message = message
        if message.startswith("Rolled back prices"):
            self.snapshot = build_snapshot(force_sample=False, publish_guard=self.activity_publication)
        return message

    @_tracked_activity("Validate local import", "Validating selected import")
    def validate_local_import(self, path: str, dataset_type: str = "prices") -> str:
        return self._import_and_refresh(Path(path), dataset_type)

    @_tracked_activity("Import local upload", "Writing selected upload")
    def import_local_upload(self, file_name: str, content: bytes, dataset_type: str = "prices") -> str:
        upload_dir = RAW_DIR / "browser_uploads"
        with self.activity_publication():
            upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file_name).name or "uploaded_prices.csv"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        upload_path = upload_dir / f"{timestamp}_{safe_name}"
        with self.activity_publication():
            upload_path.write_bytes(content)
        return self._import_and_refresh(upload_path, dataset_type)

    def import_sec_companyfacts(
        self,
        path: Path,
        *,
        instrument_id: str | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        """Import an offline SEC companyfacts JSON and publish clean facts/inventory."""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cik = str(payload.get("cik") or payload.get("cik_str") or "").strip()
            if not cik:
                raise ValueError("SEC companyfacts is missing a CIK")
            normalised_cik = str(cik).strip().upper().removeprefix("CIK").zfill(10)
            if instrument_id is not None:
                requested_instrument_id = str(instrument_id).strip()
                if not requested_instrument_id or not _sec_identity_matches(normalised_cik, requested_instrument_id):
                    raise ValueError("supplied instrument ID does not match a unique persisted SEC CIK identity")
                resolved_instrument_id = requested_instrument_id
                resolved_from_identity = True
            else:
                resolved_instrument_id = _resolve_sec_instrument(normalised_cik) or f"sec_unresolved_{normalised_cik}"
                resolved_from_identity = not resolved_instrument_id.startswith("sec_unresolved_")
            identity = CanonicalIdentity(
                resolved_instrument_id,
                f"Unresolved SEC CIK {normalised_cik}" if not resolved_from_identity else "Imported SEC entity",
                None,
                "needs_verification",
                "",
                None,
                None,
                "stock",
                {},
                "manual_review",
                () if resolved_from_identity else ("cik_not_resolved_to_instrument",),
                cik,
            )
            parsed = parse_companyfacts(path, identity)
            if not parsed.success:
                warning_codes = ", ".join(warning.code for warning in parsed.warnings)
                self.last_message = f"SEC import unavailable: {warning_codes or 'validation failed'}. No data changed."
                return _legacy_unavailable(self, self.last_message)
            source = RawDocument(path, path.resolve().as_uri(), datetime.now(timezone.utc), parsed.source_sha256, "sec_edgar", "sec_companyfacts", "application/json", 200)
            with publication_scope(publish_guard):
                write_statement_evidence(
                    source,
                    parsed.records,
                    STATEMENT_FACTS_PATH,
                    FILINGS_STATEMENTS_PATH,
                    instrument_id=identity.instrument_id,
                    vendor_records=_load_vendor_statement_claims(identity.instrument_id),
                )
            self._record_activity_output("SEC statement evidence published", STATEMENT_FACTS_PATH)
            review_note = " manual identity review required." if not resolved_from_identity else ""
            self.last_message = f"SEC import complete: {len(parsed.records)} facts, {len(parsed.warnings)} mapping warnings.{review_note}"
            return self.last_message
        except (ActivityUnavailableError, WorkflowTransitionError):
            raise
        except Exception as exc:
            self.last_message = f"SEC import unavailable: {type(exc).__name__}. No data changed; scoring and execution were not started."
            return _legacy_unavailable(self, self.last_message, exc)

    def fetch_sec_companyfacts(
        self,
        cik: str,
        *,
        cache_dir: Path | None = None,
        instrument_id: str | None = None,
        user_agent: str | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        """Fetch keyless SEC facts with controlled unavailable state."""

        try:
            configured_agent = str(user_agent or os.getenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT") or "").strip()
            if not configured_agent:
                self.last_message = "SEC import unavailable: configure ETF_COCKPIT_SEC_EDGAR_USER_AGENT with organisation and contact email. Local data was not changed."
                return _legacy_unavailable(self, self.last_message)
            provider = SecEdgarProvider(
                configured_agent,
                cache_dir=cache_dir or (RAW_DIR / "sec_edgar"),
            )
            document = provider.fetch_companyfacts(cik, publish_guard=publish_guard)
            return self.import_sec_companyfacts(
                document.path,
                instrument_id=instrument_id,
                publish_guard=publish_guard,
            )
        except (ActivityUnavailableError, WorkflowTransitionError):
            raise
        except Exception as exc:
            self.last_message = f"SEC import unavailable: {type(exc).__name__}. Local data was not changed."
            return _legacy_unavailable(self, self.last_message, exc)

    def import_esef_package(
        self,
        path: Path,
        *,
        instrument_id: str | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        """Import a local ESEF report package into the shared facts/inventory stores."""

        try:
            package_path = Path(path)
            raw_path, source_sha256 = _preserve_esef_raw(
                package_path,
                publish_guard=publish_guard,
            )
            parsed = parse_esef_package(package_path)
            if not parsed.success or not parsed.records:
                warning_codes = ", ".join(warning.code for warning in parsed.warnings)
                self.last_message = f"ESEF import unavailable: {warning_codes or 'validation failed'}. Raw filing retained at {raw_path}; no clean data changed."
                return _legacy_unavailable(self, self.last_message)
            if parsed.source_sha256 != source_sha256:
                raise ValueError("ESEF source checksum changed during parsing")
            lei = next((record.entity_lei for record in parsed.records if record.entity_lei and record.entity_lei != "unknown"), "unknown")
            resolved_instrument_id = str(instrument_id or f"esef_unresolved_{lei}").strip()
            if not resolved_instrument_id:
                raise ValueError("ESEF import requires a non-empty instrument ID when supplied")
            provider_id, source_url = _esef_source_provenance(package_path)
            records = statement_facts_from_esef(
                parsed.records,
                instrument_id=resolved_instrument_id,
                source_sha256=parsed.source_sha256,
                source_provider=provider_id,
            )
            source = RawDocument(raw_path, source_url, datetime.now(timezone.utc), parsed.source_sha256, provider_id, "esef_report_package", "application/octet-stream", 200)
            with publication_scope(publish_guard):
                write_statement_evidence(
                    source,
                    records,
                    STATEMENT_FACTS_PATH,
                    FILINGS_STATEMENTS_PATH,
                    instrument_id=resolved_instrument_id,
                    vendor_records=_load_vendor_statement_claims(resolved_instrument_id),
                )
            self._record_activity_output("ESEF statement evidence published", STATEMENT_FACTS_PATH)
            warning_codes = ", ".join(sorted({f"{warning.code}:{warning.severity}" for warning in parsed.warnings})) or "none"
            mapping_counts = {
                "mapped": sum(record.mapping_status == "mapped" for record in parsed.records),
                "extensions": sum(record.mapping_status == "unmapped_extension" for record in parsed.records),
                "unmapped": sum(record.mapping_status == "unmapped" for record in parsed.records),
            }
            review_note = " manual identity review required." if instrument_id is None else ""
            authority = "official_filing" if provider_id == "filings_xbrl_org" else "manual_review"
            self.last_message = f"ESEF import complete: {len(records)} facts, warnings={warning_codes}, mapping={mapping_counts}; source_authority={authority}.{review_note}"
            return self.last_message
        except (ActivityUnavailableError, WorkflowTransitionError):
            raise
        except Exception as exc:
            self.last_message = f"ESEF import unavailable: {type(exc).__name__}. No data changed; scoring and execution were not started."
            return _legacy_unavailable(self, self.last_message, exc)

    def discover_esef_filings(
        self,
        country: str = "NL",
        limit: int = 10,
        *,
        cache_dir: Path | None = None,
        expected_action_id: str | None = None,
    ) -> str:
        """Discover official ESEF filings with an explicit unavailable state."""

        try:
            provider = FilingsXbrlOrgProvider(cache_dir=cache_dir or (RAW_DIR / "esef"))
            result = provider.list_filings(country, limit)
            if result.status != "ok":
                self.last_message = f"ESEF discovery unavailable: {redact_text(str(result.message))}"
                raise ActivityUnavailableError(self.last_message)
            filing_count = len(result.data) if result.data is not None else 0
            message = f"ESEF discovery complete: {filing_count} official filings."
            action_id = expected_action_id or getattr(getattr(self, "_activity_context", None), "action_id", None)
            if action_id is None:
                self._esef_provider = provider
                self._esef_filings = result.data
                self.last_message = message
            else:
                with self.activity_publication(action_id):
                    self._esef_provider = provider
                    self._esef_filings = result.data
                    self.last_message = message
            return message
        except (ActivityUnavailableError, WorkflowTransitionError):
            raise
        except Exception as exc:
            self.last_message = f"ESEF discovery unavailable: {type(exc).__name__}. Local data was not changed."
            raise ActivityUnavailableError(self.last_message) from exc

    def discover_oam(
        self,
        country: str,
        *,
        issuer: str = "",
        isin: str = "",
        document_type: str = "",
        date_from: str = "",
        date_to: str = "",
        endpoint: str = "",
        company_number: str = "",
        api_key: str = "",
        cache_dir: Path | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        """Discover one official OAM export without changing clean evidence on failure."""

        try:
            start = datetime.fromisoformat(date_from.strip()).date() if date_from.strip() else None
            end = datetime.fromisoformat(date_to.strip()).date() if date_to.strip() else None
            if start and end and start > end:
                raise ValueError("OAM date_from must not be after date_to")
            country_code = str(country or "").strip().upper()
            adapter_type = oam_adapter_for_country(country_code)
            adapter_kwargs: dict[str, object] = {
                "cache_dir": cache_dir,
                "endpoint": endpoint or None,
                "enabled": bool(endpoint.strip()) or adapter_type is CompaniesHouseFilingAdapter,
                "publish_guard": publish_guard,
            }
            if adapter_type is CompaniesHouseFilingAdapter:
                adapter_kwargs["api_key"] = api_key
            adapter = adapter_type(**adapter_kwargs)
            request = OAMDiscoveryRequest(
                issuer=issuer,
                isin=isin,
                document_type=document_type,
                date_from=start,
                date_to=end,
                company_number=company_number,
            )
            result = adapter.discover(request)
            coverage_path = write_filing_coverage(
                result,
                country=country_code,
                request=request,
                publish_guard=publish_guard,
            )
            if result.status == "ok":
                registry_path = write_oam_discovery_registry(result, publish_guard=publish_guard)
                self._record_activity_output("Official filing registry published", registry_path)
                self.last_message = f"{redact_text(str(result.message))} Snapshot checksum={result.snapshot.sha256[:12] if result.snapshot else 'unavailable'}..."
            else:
                self._record_activity_output("Filing coverage evidence retained", coverage_path)
                self.last_message = f"{redact_text(str(result.message))} Manual fallback remains available; no clean evidence was changed."
                raise ActivityUnavailableError(self.last_message)
            return self.last_message
        except (ActivityUnavailableError, WorkflowTransitionError):
            raise
        except Exception as exc:
            self.last_message = (
                f"OAM discovery unavailable: {type(exc).__name__}. Manual fallback remains available; "
                "the coverage attempt was retained when possible, but no filing evidence or score changed."
            )
            raise ActivityUnavailableError(self.last_message) from exc

    def import_manual_official_filing(
        self,
        path: Path,
        *,
        jurisdiction: str,
        instrument_id: str,
        source_url: str,
        document_type: str = "annual_report",
        published_at: str = "",
        available_at: str = "",
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        """Archive one user-owned official filing for explicit manual review."""

        try:
            record = archive_manual_official_filing(
                path,
                jurisdiction=jurisdiction,
                instrument_id=instrument_id,
                source_url=source_url,
                document_type=document_type,
                published_at=published_at or None,
                available_at=available_at or None,
                publish_guard=publish_guard,
            )
            self._record_activity_output("Manual official filing archived", record.raw_path)
            self.last_message = (
                f"Official filing archived for {record.instrument_id}: {record.sha256[:12]}...; "
                f"availability={record.availability_precision}; manual review required; execution_allowed=false."
            )
            return self.last_message
        except (ActivityUnavailableError, WorkflowTransitionError):
            raise
        except Exception as exc:
            self.last_message = (
                f"Official filing import unavailable: {type(exc).__name__}. "
                "No existing evidence changed; scoring and execution were not started."
            )
            raise ActivityUnavailableError(self.last_message) from exc

    def download_esef_package(
        self,
        filing_id: str,
        *,
        package_url: str | None = None,
        cache_dir: Path | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        """Download one discovered official package while retaining immutable raw bytes."""

        try:
            provider = getattr(self, "_esef_provider", None) or FilingsXbrlOrgProvider(cache_dir=cache_dir or (RAW_DIR / "esef"))
            try:
                document = provider.download_report_package(
                    filing_id,
                    package_url,
                    publish_guard=publish_guard,
                )
            except TypeError as exc:
                if "publish_guard" not in str(exc):
                    raise
                document = provider.download_report_package(filing_id, package_url)
            self._record_activity_output("ESEF package downloaded", document.path)
            self.last_message = f"ESEF package downloaded: {document.path.name} ({document.sha256[:12]}...)."
            return self.last_message
        except (EsefProviderUnavailable, OSError, ValueError) as exc:
            self.last_message = f"ESEF download unavailable: {type(exc).__name__}. Local data was not changed."
            raise ActivityUnavailableError(self.last_message) from exc
    def _import_and_refresh(self, path: Path, dataset_type: str = "prices") -> str:
        self.assert_activity_publishable()
        result = DataService(self.snapshot.config).import_local_file(
            Path(path),
            dataset_type,
            commit=True,
            publish_guard=self.activity_publication,
        )
        self.last_message = result.message
        if not result.ok:
            raise ActivityUnavailableError(result.message)
        self.snapshot = build_snapshot(force_sample=False, publish_guard=self.activity_publication)
        return result.message

    @_tracked_activity("Refresh macro/news context", "Refreshing local context")
    def refresh_signals(self) -> None:
        self.snapshot = build_snapshot(force_sample=False, publish_guard=self.activity_publication)
        self.last_message = "Signals refreshed from local data."

    @_tracked_activity("Export audit packet", "Writing audit packet")
    def export_audit_packet(self) -> Path:
        self.assert_activity_publishable()
        self._write_current_scoreboard()
        self.assert_activity_publishable()
        bridge = ChatGPTBridge(self.snapshot.config)
        path = bridge.export_review_pack(
            self.snapshot.data_report.as_of_date,
            self.snapshot.holdings,
            self.snapshot.features,
            self.snapshot.signals,
            self.snapshot.backtest,
            self.snapshot.data_report,
            publish_guard=self.activity_publication,
        )
        self.last_export_path = path
        self.last_message = f"Audit packet exported: {path}"
        return path

    def export_chatgpt_pack(self) -> Path:
        return self.export_audit_packet()

    def create_trade_proposal(self) -> Path:
        report = create_portfolio_review_report(
            self.snapshot.signals,
            self.snapshot.data_report,
            run_id=self.snapshot.signals[0].run_id if self.snapshot.signals else "manual_trade_proposal",
        )
        path = Path(str(report["path"]))
        self.last_message = f"{report['message']} Report: {path}"
        return path

    def save_provider_settings(self, provider_name: str, active_provider: str, base_url: str, api_key: str = "") -> str:
        save_provider_settings(
            provider_name,
            active_provider=active_provider,
            base_url=base_url,
            api_key=api_key,
        )
        self.snapshot = build_snapshot(force_sample=False)
        suffix = " API key stored in local .env." if api_key.strip() else " Existing local API key, if any, was left unchanged."
        self.last_message = f"Saved provider settings for {provider_name}.{suffix}"
        return self.last_message

    @_tracked_activity("Write scoreboard", "Building scoreboard")
    def _write_current_scoreboard(self) -> Path:
        candidate_report, _ = load_latest_candidate_report()
        reference_context = context_from_snapshot(
            self.snapshot,
            purpose="comparison",
            analysis_id=f"scoreboard:{getattr(self.snapshot, 'universe_revision', 'unknown')}",
        )
        regime = build_market_regime(
            self.snapshot.prices,
            candidate_report,
            benchmark_id=reference_context.benchmark_data_id,
            benchmark_reference=reference_context.projection,
        )
        with self.activity_publication():
            write_market_regime(regime)
        calibration = evaluate_forecast_calibration(load_forecast_history(), self.snapshot.prices)
        with self.activity_publication():
            write_forecast_calibration(calibration)
        scores = build_simple_instrument_scores(
            self.snapshot.config,
            self.snapshot.signals,
            self.snapshot.forecasts,
            self.snapshot.prices,
            benchmark_data_id=reference_context.benchmark_data_id,
            benchmark_reference=reference_context.projection,
            reference_identity=reference_context.identity,
        )
        with self.activity_publication():
            path = write_simple_scoreboard(scores)
        try:
            with self.activity_publication():
                write_trust_artifacts_for_scores(
                    self.snapshot.config,
                    scores,
                    simple_scoreboard_frame(scores),
                    prices=self.snapshot.prices,
                )
        except Exception:
            pass
        return path


MAX_LOCAL_ESEF_BYTES = 300 * 1024 * 1024


def _preserve_esef_raw(
    package_path: Path,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> tuple[Path, str]:
    if not package_path.is_file():
        raise FileNotFoundError(f"ESEF package is not a readable file: {package_path}")
    if package_path.stat().st_size > MAX_LOCAL_ESEF_BYTES:
        raise ValueError("ESEF local package exceeds the size limit")
    source_sha256 = sha256_file(package_path)
    raw_path = RAW_DIR / "filings" / "eu_esef" / f"{source_sha256}.xbri"
    payload = package_path.read_bytes()
    if raw_path.exists():
        _validate_esef_raw_checksum(raw_path, source_sha256)
    else:
        with publication_scope(publish_guard):
            atomic_write_bytes(raw_path, payload, lambda candidate: _validate_esef_raw_checksum(candidate, source_sha256))
    return raw_path, source_sha256


def _esef_source_provenance(package_path: Path) -> tuple[str, str]:
    resolved = package_path.resolve()
    immutable_root = (RAW_DIR / "esef" / "immutable").resolve()
    if resolved == immutable_root or immutable_root in resolved.parents:
        return "filings_xbrl_org", "https://filings.xbrl.org"
    try:
        for fixture in load_fixture_manifest():
            if fixture.document_type == "esef_report_package" and fixture.path.resolve() == resolved:
                return "filings_xbrl_org", fixture.source_url
    except (OSError, ValueError):
        pass
    return "esef_local_import", resolved.as_uri()


def _validate_esef_raw_checksum(path: Path, expected: str) -> None:
    if sha256_file(path) != expected:
        raise ValueError("ESEF raw filing checksum mismatch")


def _resolve_sec_instrument(cik: str) -> str | None:
    """Resolve a unique persisted CIK mapping before falling back to review."""

    try:
        import pandas as pd

        frame = pd.read_parquet(IDENTITY_PATH)
        if "cik" not in frame.columns or "instrument_id" not in frame.columns:
            return None
        values = frame["cik"].map(lambda value: str(value).strip().upper().removeprefix("CIK").zfill(10))
        matches = sorted({str(value) for value in frame.loc[values == cik, "instrument_id"] if str(value).strip()})
        return matches[0] if len(matches) == 1 else None
    except (OSError, ValueError, TypeError, ImportError):
        return None


def _sec_identity_matches(cik: str, instrument_id: str) -> bool:
    """Accept an explicit instrument only when the persisted CIK mapping is unique."""

    try:
        import pandas as pd

        frame = pd.read_parquet(IDENTITY_PATH)
        if "cik" not in frame.columns or "instrument_id" not in frame.columns:
            return False
        values = frame["cik"].map(lambda value: str(value).strip().upper().removeprefix("CIK").zfill(10))
        candidates = sorted({str(value).strip() for value in frame.loc[values == cik, "instrument_id"] if str(value).strip()})
        return len(candidates) == 1 and candidates[0] == instrument_id
    except (OSError, ValueError, TypeError, ImportError):
        return False


def _load_vendor_statement_claims(instrument_id: str) -> tuple[dict[str, object], ...]:
    """Load optional vendor statement claims for exact-match authority checks."""

    try:
        import pandas as pd

        path = CLEAN_DIR / "fundamentals.parquet"
        if not path.exists():
            return ()
        frame = pd.read_parquet(path)
        if "instrument_id" in frame.columns:
            frame = frame[frame["instrument_id"].astype(str) == instrument_id]
        concept_columns = {"concept", "canonical_metric"} & set(frame.columns)
        period_columns = {"period", "end", "instant", "as_of_date"} & set(frame.columns)
        if not concept_columns or "unit" not in frame.columns or not period_columns:
            return ()
        return tuple(frame.to_dict(orient="records"))
    except (OSError, ValueError, TypeError, ImportError):
        return ()
