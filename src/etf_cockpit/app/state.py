from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etf_cockpit.core.config import AppConfig, save_provider_settings
from etf_cockpit.core.migrations import run_startup_migrations
from etf_cockpit.core.paths import RAW_DIR
from etf_cockpit.core.session_log import SESSION_LOG_PATH, log_event, log_exception
from etf_cockpit.core.errors import ErrorStore, classify_exception
from etf_cockpit.core.timing import timed_step
from etf_cockpit.core.workflow import WorkflowController, WorkflowStatus, WorkflowStep
from etf_cockpit.data.trust_artifacts import refresh_static_trust_artifacts, write_trust_artifacts_for_scores
from etf_cockpit.features.regime import build_market_regime, write_market_regime
from etf_cockpit.models.calibration import evaluate_forecast_calibration, load_forecast_history, write_forecast_calibration
from etf_cockpit.operations.event_store import current_activity_view, load_events_with_tail_recovery
from etf_cockpit.portfolio.review_reports import create_portfolio_review_report
from etf_cockpit.services import ChatGPTBridge, CockpitSnapshot, DataService, build_snapshot
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores, load_latest_candidate_report, simple_scoreboard_frame, write_simple_scoreboard


# Compatibility seam for existing callers and tests. This is the session trace,
# not a second mutable activity store.
ACTIVITY_LOG_PATH = SESSION_LOG_PATH


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
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_recent_activity(limit: int = 8) -> list[ActivityEntry]:
    entries: list[ActivityEntry] = []
    try:
        events, _ = load_events_with_tail_recovery(ACTIVITY_LOG_PATH)
    except Exception:
        return []
    for event in events:
        if event.event_type not in {"activity_complete", "activity_failed"}:
            continue
        data = event.model_dump(mode="json")
        output_summary = data.get("output_summary") or {}
        file_paths = data.get("file_paths") or []
        entries.append(
            ActivityEntry(
                label=str(data.get("button_label") or data.get("feature") or "Workflow action"),
                status=str(event.status or "unknown"),
                step="Complete" if event.event_type == "activity_complete" else "Failed",
                started_at=str(data.get("timestamp_local") or data.get("timestamp_utc") or ""),
                action_id=str(event.action_id or ""),
                finished_at=str(data.get("timestamp_local") or data.get("timestamp_utc") or ""),
                message=str(data.get("user_message") or output_summary.get("message") or ""),
                output_path=str(file_paths[0]) if file_paths else None,
            )
        )
    entries = entries[-limit:]
    return entries


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
    universe_cache_revision: str = ""

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
        return cls(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf, recent_activity=_read_recent_activity())

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

    def begin_activity(self, label: str, step: str | None = None) -> ActivityEntry:
        if self.current_activity is not None:
            return self.current_activity
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
            output_summary={"step": entry.step},
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
    ) -> None:
        if self.current_activity is None:
            self.begin_activity(step, step)
        assert self.current_activity is not None
        self.current_activity.step = step
        self.current_activity.completed_units = max(0, int(completed_units))
        self.current_activity.total_units = None if total_units is None else max(0, int(total_units))
        if message is not None:
            self.current_activity.message = message
            self.last_message = message
        else:
            self.last_message = step
        with timed_step(self.current_activity.action_id, step):
            self.workflow_controller.step(
                self.current_activity.action_id,
                WorkflowStep(step, self.current_activity.message or step, completed_units, total_units),
            )
        log_event(
            event_type="activity_update",
            severity="info",
            action_id=self.current_activity.action_id,
            component="app_state",
            button_label=self.current_activity.label,
            feature=self.current_activity.label,
            operation="activity_step",
            status="running",
            output_summary={"step": step, "message": self.last_message},
            path=ACTIVITY_LOG_PATH,
        )

    def finish_activity(self, message: str, output_path: Path | str | None = None, label: str | None = None) -> ActivityEntry:
        entry = self.current_activity or self.begin_activity(label or "Workflow action", "Completing")
        result = self.workflow_controller.finish(
            entry.action_id,
            WorkflowStatus.SUCCESS,
            message,
            () if output_path is None else (output_path,),
        )
        entry.status = "success"
        entry.step = "Complete"
        entry.finished_at = _utc_now()
        entry.message = result.message
        entry.output_path = None if output_path is None else str(output_path)
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
    ) -> ActivityEntry:
        entry = self.current_activity or self.begin_activity(label, "Failed")
        _, retryable = classify_exception(exc)
        result = self.workflow_controller.fail(entry.action_id, exc, retryable=retryable)
        entry.status = "failed"
        entry.step = "Failed"
        entry.finished_at = _utc_now()
        entry.message = f"{label} failed: {result.message}"
        self.current_activity = None
        self.last_message = entry.message
        self.recent_activity = (self.recent_activity + [entry])[-8:]
        self.error_store.record_exception(
            action_id=entry.action_id,
            exc=exc,
            retry_callback=retry_callback,
            user_message=entry.message,
        )
        log_exception(
            event_type="activity_failed",
            exc=exc,
            action_id=entry.action_id,
            component="app_state",
            button_label=entry.label,
            feature=entry.label,
            operation="fail_activity",
            user_message=entry.message,
            path=ACTIVITY_LOG_PATH,
        )
        return entry

    def current_activity_view(self):
        """Project the latest visible workflow state from the session trace."""
        try:
            events, _ = load_events_with_tail_recovery(ACTIVITY_LOG_PATH)
        except Exception:
            events = []
        return current_activity_view(events)

    def refresh_sample_data(self) -> None:
        self.snapshot = build_snapshot(force_sample=True)
        self.selected_etf = self.snapshot.config.ui.default_etf
        self.last_message = "Sample data regenerated and signals refreshed."

    def renew_data_dry_run(self) -> str:
        message = DataService(self.snapshot.config).dry_run_update()
        self.last_message = "Renew data dry run completed."
        return message

    def renew_data_api_status(self) -> str:
        message = DataService(self.snapshot.config).api_update_status()
        self.last_message = message
        self.snapshot = build_snapshot(force_sample=False)
        return message

    def refresh_yfinance_data(self) -> str:
        service = DataService(self.snapshot.config)
        message = service.refresh_yfinance_data()
        if getattr(service, "last_operation_succeeded", True):
            self.snapshot = build_snapshot(force_sample=False)
            self._write_current_scoreboard()
            self.last_message = "YFinance data refreshed."
        else:
            self.last_message = message
        return message

    def run_algorithm_scores(self) -> str:
        message = DataService(self.snapshot.config).run_yfinance_candidate_analysis()
        self.snapshot = build_snapshot(force_sample=False)
        scoreboard_path = self._write_current_scoreboard()
        self.last_message = "Algorithms refreshed from yfinance data."
        summary = message.split(" Report:", 1)[0]
        return f"{summary}. Scoreboard updated: {scoreboard_path.name}."

    def run_forecasting_models(self) -> str:
        message = DataService(self.snapshot.config).run_yfinance_forecasts(horizons=[60], live_optional_models=False)
        self.snapshot = build_snapshot(force_sample=False)
        scoreboard_path = self._write_current_scoreboard()
        self.last_message = "Fast forecasts refreshed from yfinance data for the 60-trading-day scoring horizon."
        summary = "; ".join(line.split(". Output:", 1)[0] for line in message.splitlines() if line.strip())
        return f"{summary}. Optional TimesFM/Toto live models are kept out of the main workflow if they are not already cached. Scoreboard updated: {scoreboard_path.name}."

    def rollback_latest_prices(self) -> str:
        message = DataService(self.snapshot.config).rollback_latest_price_import()
        self.last_message = message
        if message.startswith("Rolled back prices"):
            self.snapshot = build_snapshot(force_sample=False)
        return message

    def validate_local_import(self, path: str, dataset_type: str = "prices") -> str:
        return self._import_and_refresh(Path(path), dataset_type)

    def import_local_upload(self, file_name: str, content: bytes, dataset_type: str = "prices") -> str:
        upload_dir = RAW_DIR / "browser_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file_name).name or "uploaded_prices.csv"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        upload_path = upload_dir / f"{timestamp}_{safe_name}"
        upload_path.write_bytes(content)
        return self._import_and_refresh(upload_path, dataset_type)

    def _import_and_refresh(self, path: Path, dataset_type: str = "prices") -> str:
        result = DataService(self.snapshot.config).import_local_file(Path(path), dataset_type, commit=True)
        self.last_message = result.message
        if result.ok:
            self.snapshot = build_snapshot(force_sample=False)
        return result.message

    def refresh_signals(self) -> None:
        self.snapshot = build_snapshot(force_sample=False)
        self.last_message = "Signals refreshed from local data."

    def export_audit_packet(self) -> Path:
        self._write_current_scoreboard()
        bridge = ChatGPTBridge(self.snapshot.config)
        path = bridge.export_review_pack(
            self.snapshot.data_report.as_of_date,
            self.snapshot.holdings,
            self.snapshot.features,
            self.snapshot.signals,
            self.snapshot.backtest,
            self.snapshot.data_report,
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

    def _write_current_scoreboard(self) -> Path:
        candidate_report, _ = load_latest_candidate_report()
        regime = build_market_regime(self.snapshot.prices, candidate_report)
        write_market_regime(regime)
        calibration = evaluate_forecast_calibration(load_forecast_history(), self.snapshot.prices)
        write_forecast_calibration(calibration)
        scores = build_simple_instrument_scores(
            self.snapshot.config,
            self.snapshot.signals,
            self.snapshot.forecasts,
            self.snapshot.prices,
        )
        path = write_simple_scoreboard(scores)
        try:
            write_trust_artifacts_for_scores(
                self.snapshot.config,
                scores,
                simple_scoreboard_frame(scores),
                prices=self.snapshot.prices,
            )
        except Exception:
            pass
        return path
