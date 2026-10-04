from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import threading
from typing import Any, Callable, TypeVar, cast

from etf_cockpit.application.settings import AppConfig, save_provider_settings
from etf_cockpit.application.runtime import run_startup_migrations
from etf_cockpit.core.types import latest_signal
from etf_cockpit.core.paths import FILINGS_STATEMENTS_PATH, RAW_DIR, ROOT, STATEMENT_FACTS_PATH  # noqa: F401 - compatibility re-export
from etf_cockpit.core.session_log import SESSION_LOG_PATH, log_event, redact_text
from etf_cockpit.core.errors import ErrorStore, classify_exception
from etf_cockpit.core.timing import timed_step
from etf_cockpit.core.workflow import (
    PublicationScopeFactory,
    WorkflowController,
    WorkflowStatus,
    WorkflowStep,
    WorkflowTransitionError,
)
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.sec_bulk_import import BulkImportResult, import_sec_companyfacts_bulk as _import_sec_companyfacts_bulk  # noqa: F401 - compatibility re-export
from etf_cockpit.application.sec_submissions_import import SubmissionsImportResult, import_sec_submissions as _import_sec_submissions  # noqa: F401 - compatibility re-export
from etf_cockpit.application.runtime import DurableJobScheduler
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH, refresh_static_trust_artifacts, write_trust_artifacts_for_scores  # noqa: F401 - compatibility re-export
from etf_cockpit.data.classification import classification_score_state  # noqa: F401 - compatibility re-export
from etf_cockpit.features.regime import build_market_regime, write_market_regime  # noqa: F401 - compatibility re-export
from etf_cockpit.application.benchmark_reference import context_from_snapshot  # noqa: F401 - compatibility re-export
from etf_cockpit.models.calibration import evaluate_forecast_calibration, load_forecast_history, write_forecast_calibration  # noqa: F401 - compatibility re-export
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider  # noqa: F401
from etf_cockpit.data.esef_provider import FilingsXbrlOrgProvider  # noqa: F401 - compatibility re-export
from etf_cockpit.data.oam_adapters import oam_adapter_for_country, write_filing_coverage, write_oam_discovery_registry  # noqa: F401 - compatibility re-export
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.esef_ixbrl import parse_esef_package  # noqa: F401 - compatibility re-export
from etf_cockpit.parsers.sec_facts import parse_companyfacts, write_statement_evidence  # noqa: F401
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity
from etf_cockpit.operations.event_store import current_activity_view, load_events_with_tail_recovery
from etf_cockpit.portfolio.review_reports import create_portfolio_review_report
from etf_cockpit.application.chatgpt_review import ChatGPTBridge
from etf_cockpit.application.data_service import DataService
from etf_cockpit.application.snapshot_builder import CockpitSnapshot, build_snapshot
from etf_cockpit.signals.simple_scores import SimpleInstrumentScore, build_simple_instrument_scores, load_latest_candidate_report, simple_scoreboard_frame, write_simple_scoreboard  # noqa: F401 - compatibility re-export
from etf_cockpit.app import theme
from etf_cockpit.application.contracts import ApplicationCommand, DashboardActionCommand
from etf_cockpit.application.filing_ingestion import (
    _bulk_result_message,  # noqa: F401
    _cached_sec_bulk_document,  # noqa: F401
    _sec_failure_detail,  # noqa: F401
)
from etf_cockpit.application.activity_results import (
    activity_result_error,
    ActivityUnavailableError,
)
from etf_cockpit.application import filing_ingestion_workflows as _filing_ingestion_workflows
from etf_cockpit.application.scoreboard_publication import _signal_classification_is_current
from etf_cockpit.application import scoreboard_publication as _scoreboard_publication


# Compatibility seam for existing callers and tests. This is the session trace,
# not a second mutable activity store.
ACTIVITY_LOG_PATH = SESSION_LOG_PATH

_TrackedResult = TypeVar("_TrackedResult")


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
    analysis_depth: str | None = None
    settings_root: Path | None = None
    score_history_warning: str | None = None
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
            command_handlers={"dashboard_action": self._handle_dashboard_action},
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

    def set_analysis_depth(self, depth: str) -> str:
        """Select the analysis-depth profile; workload semantics stay in the application layer."""

        value = str(depth or "").strip().lower()
        if value not in ("quick", "medium", "high", "full"):
            raise ValueError(f"Unsupported analysis depth: {depth}")
        self.analysis_depth = value
        self.last_message = f"Analysis depth: {value.capitalize()}"
        return value

    def persist_analysis_depth(self, depth: str) -> str:
        """Write the depth into the settings bundle (single source of truth shared with Settings).

        Returns a short status line. Without a settings root (tests, detached state) nothing is
        written and the status says so; a rejected save never changes the in-memory choice.
        """

        value = str(depth or "").strip().lower()
        if self.settings_root is None:
            return "Analysis depth kept for this session only (no settings location bound)."
        from etf_cockpit.application.settings import (
            SettingsError,
            load_settings_bundle,
            preview_settings,
            save_settings,
        )

        try:
            bundle = load_settings_bundle(self.settings_root)
            if bundle.controls.analysis_depth == value:
                return f"Analysis depth {value.capitalize()} already saved in Settings."
            candidate = bundle.model_copy(update={"controls": bundle.controls.model_copy(update={"analysis_depth": value})})
            preview_settings(candidate, expected_revision=bundle.revision, root=self.settings_root)
            result = save_settings(candidate, expected_revision=bundle.revision, root=self.settings_root)
            return f"Analysis depth {value.capitalize()} saved to Settings v{result.settings_version}."
        except (SettingsError, OSError, ValueError) as exc:
            return f"Analysis depth {value.capitalize()} not saved to Settings: {exc}"

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
        state = cls(
            snapshot=snapshot,
            selected_etf=snapshot.config.ui.default_etf,
            recent_activity=_read_recent_activity(),
            settings_root=ROOT,
        )
        try:
            from etf_cockpit.application.settings import load_settings_bundle

            state.analysis_depth = load_settings_bundle(ROOT).controls.analysis_depth
        except Exception:  # the chip stays Unavailable rather than guessing a depth
            state.analysis_depth = None
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
            self.last_message = message
            self.recent_activity = (self.recent_activity + [entry])[-8:]
            self.current_activity = None
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
            entry.message = f"{label} failed: {result.message}"
            self.error_store.record_exception(
                action_id=entry.action_id,
                exc=exc,
                retry_callback=retry_callback,
                user_message=entry.message,
            )
            entry.status = "failed"
            entry.step = "Failed"
            entry.finished_at = _utc_now()
            entry.error = result.message
            self.last_message = entry.message
            self.recent_activity = (self.recent_activity + [entry])[-8:]
            self.current_activity = None
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
                self.last_message = self._with_score_history_warning("YFinance data refreshed.")
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
            self.last_message = self._with_score_history_warning("Algorithms refreshed from yfinance data.")
            summary = message.split(" Report:", 1)[0]
            return self._with_score_history_warning(f"{summary}. Scoreboard updated: {scoreboard_path.name}.")

    @_tracked_activity("Run forecasting models", "Running baseline forecasts")
    def run_forecasting_models(self) -> str:
        action_id = self.current_activity.action_id if self.current_activity else "forecasts"
        with timed_step(action_id, "forecast_models"):
            service = DataService(self.snapshot.config)
            request_identity = configured_forecast_request_identity(self.snapshot.config)
            message = service.run_yfinance_forecasts(
                horizons=list(request_identity["requested_horizons"]),
                live_optional_models=bool(request_identity["live_optional_models"]),
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
            self.last_message = self._with_score_history_warning(
                "Fast forecasts refreshed from yfinance data for the 60-trading-day scoring horizon."
            )
            summary = "; ".join(line.split(". Output:", 1)[0] for line in message.splitlines() if line.strip())
            return self._with_score_history_warning(
                f"{summary}. Optional TimesFM/Toto live models are kept out of the main workflow if they are not already cached. Scoreboard updated: {scoreboard_path.name}."
            )

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

    def _handle_dashboard_action(self, command: ApplicationCommand) -> dict[str, object]:
        if not isinstance(command, DashboardActionCommand):
            raise ValueError("Dashboard action handler received an unsupported command.")
        dataset_type = command.dataset_type or "prices"
        if command.action == "refresh_yfinance_data":
            result = self.refresh_yfinance_data()
        elif command.action == "run_algorithm_scores":
            result = self.run_algorithm_scores()
        elif command.action == "run_forecasting_models":
            result = self.run_forecasting_models()
        elif command.action == "renew_data_dry_run":
            result = self.renew_data_dry_run()
        elif command.action == "renew_data_api_status":
            result = self.renew_data_api_status()
        elif command.action == "rollback_latest_prices":
            result = self.rollback_latest_prices()
        elif command.action == "export_audit_packet":
            output_path = self.export_audit_packet()
            return {
                "message": f"Audit packet exported: {output_path}",
                "output_path": str(output_path),
            }
        elif command.action == "validate_local_import":
            if command.selected_path is None:
                raise ValueError("A local path is required to validate an import.")
            result = self.validate_local_import(command.selected_path, dataset_type)
        elif command.action == "import_local_upload":
            if command.file_name is None or command.content is None:
                raise ValueError("A file name and content are required to import an upload.")
            result = self.import_local_upload(command.file_name, command.content, dataset_type)
        else:
            raise ValueError(f"Unsupported dashboard action: {command.action}")
        return {"message": str(result)}

    def import_sec_companyfacts(
        self,
        path: Path,
        *,
        instrument_id: str | None = None,
        document: RawDocument | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        return _filing_ingestion_workflows.import_sec_companyfacts(self, path, instrument_id=instrument_id, document=document, publish_guard=publish_guard)

    def fetch_sec_companyfacts(
        self,
        cik: str,
        *,
        cache_dir: Path | None = None,
        instrument_id: str | None = None,
        user_agent: str | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        return _filing_ingestion_workflows.fetch_sec_companyfacts(self, cik, cache_dir=cache_dir, instrument_id=instrument_id, user_agent=user_agent, publish_guard=publish_guard)

    def import_sec_companyfacts_bulk(
        self,
        archive: Path,
        *,
        cik: str | None = None,
        instrument_id: str | None = None,
        identity: CanonicalIdentity | None = None,
        cache_dir: Path | None = None,
        provenance: RawDocument | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        return _filing_ingestion_workflows.import_sec_companyfacts_bulk(self, archive, cik=cik, instrument_id=instrument_id, identity=identity, cache_dir=cache_dir, provenance=provenance, publish_guard=publish_guard)

    def fetch_sec_companyfacts_bulk(
        self,
        cik: str,
        *,
        instrument_id: str | None = None,
        cache_dir: Path | None = None,
        user_agent: str | None = None,
        publish_guard: PublicationScopeFactory | None = None,
        cache_only: bool = False,
    ) -> str:
        return _filing_ingestion_workflows.fetch_sec_companyfacts_bulk(self, cik, instrument_id=instrument_id, cache_dir=cache_dir, user_agent=user_agent, publish_guard=publish_guard, cache_only=cache_only)

    def _record_sec_bulk_outputs(self, result: BulkImportResult) -> None:
        return _filing_ingestion_workflows._record_sec_bulk_outputs(self, result)

    def _finish_sec_submissions_import(self, result: SubmissionsImportResult) -> str:
        return _filing_ingestion_workflows._finish_sec_submissions_import(self, result)

    def import_sec_submissions_bulk(
        self, archive: Path, *, cik: str | None = None, instrument_id: str | None = None,
        identity: CanonicalIdentity | None = None, cache_dir: Path | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        return _filing_ingestion_workflows.import_sec_submissions_bulk(self, archive, cik=cik, instrument_id=instrument_id, identity=identity, cache_dir=cache_dir, publish_guard=publish_guard)

    def fetch_sec_submissions_bulk(
        self, cik: str, *, instrument_id: str | None = None, cache_dir: Path | None = None,
        user_agent: str | None = None, publish_guard: PublicationScopeFactory | None = None,
        cache_only: bool = False,
    ) -> str:
        return _filing_ingestion_workflows.fetch_sec_submissions_bulk(self, cik, instrument_id=instrument_id, cache_dir=cache_dir, user_agent=user_agent, publish_guard=publish_guard, cache_only=cache_only)

    def import_esef_package(
        self,
        path: Path,
        *,
        instrument_id: str | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        return _filing_ingestion_workflows.import_esef_package(self, path, instrument_id=instrument_id, publish_guard=publish_guard)

    def discover_esef_filings(
        self,
        country: str = "NL",
        limit: int = 10,
        *,
        cache_dir: Path | None = None,
        expected_action_id: str | None = None,
    ) -> str:
        return _filing_ingestion_workflows.discover_esef_filings(self, country, limit, cache_dir=cache_dir, expected_action_id=expected_action_id)

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
        return _filing_ingestion_workflows.discover_oam(self, country, issuer=issuer, isin=isin, document_type=document_type, date_from=date_from, date_to=date_to, endpoint=endpoint, company_number=company_number, api_key=api_key, cache_dir=cache_dir, publish_guard=publish_guard)

    def import_local_oam(
        self,
        path: Path,
        country: str,
        *,
        issuer: str = "",
        isin: str = "",
        document_type: str = "",
        date_from: str = "",
        date_to: str = "",
        company_number: str = "",
        cache_dir: Path | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        return _filing_ingestion_workflows.import_local_oam(self, path, country, issuer=issuer, isin=isin, document_type=document_type, date_from=date_from, date_to=date_to, company_number=company_number, cache_dir=cache_dir, publish_guard=publish_guard)

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
        return _filing_ingestion_workflows.import_manual_official_filing(self, path, jurisdiction=jurisdiction, instrument_id=instrument_id, source_url=source_url, document_type=document_type, published_at=published_at, available_at=available_at, publish_guard=publish_guard)

    def download_esef_package(
        self,
        filing_id: str,
        *,
        package_url: str | None = None,
        cache_dir: Path | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        return _filing_ingestion_workflows.download_esef_package(self, filing_id, package_url=package_url, cache_dir=cache_dir, publish_guard=publish_guard)
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
        self.last_message = self._with_score_history_warning(f"Audit packet exported: {path}")
        return path

    def export_chatgpt_pack(self) -> Path:
        return self.export_audit_packet()

    def create_trade_proposal(self) -> Path:
        newest_signal = latest_signal(self.snapshot.signals)
        report = create_portfolio_review_report(
            self.snapshot.signals,
            self.snapshot.data_report,
            run_id=newest_signal.run_id if newest_signal is not None else "manual_trade_proposal",
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
        return _scoreboard_publication._write_current_scoreboard(self)

    def _record_score_history_failure(self, exc: Exception, scoreboard_path: Path) -> None:
        reason = redact_text(" ".join(f"{type(exc).__name__}: {exc}".split()))[:240]
        warning = (
            f"Score history was not persisted ({reason}). "
            f"Scoreboard {scoreboard_path.name} was written; score history, components, evidence ledger "
            "and feature drivers for this run are unavailable, not empty. Scores and actions are unchanged."
        )
        self.score_history_warning = warning
        self.last_message = warning
        action_id = self.shared_activity_id or (self.current_activity.action_id if self.current_activity else None)
        log_event(
            event_type="score_history_not_persisted",
            severity="warning",
            action_id=action_id,
            component="app_state",
            feature="Write scoreboard",
            operation="write_trust_artifacts_for_scores",
            status="unavailable",
            file_paths=scoreboard_path,
            warnings="score_history_not_persisted",
            user_message=warning,
            exception_type=type(exc).__name__,
            exception_message_redacted=reason,
            path=ACTIVITY_LOG_PATH,
        )

    def _with_score_history_warning(self, message: str) -> str:
        warning = self.score_history_warning
        return f"{message} {warning}" if warning else message
