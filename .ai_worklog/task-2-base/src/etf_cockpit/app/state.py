from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etf_cockpit.core.config import save_provider_settings
from etf_cockpit.core.migrations import run_startup_migrations
from etf_cockpit.core.paths import LOG_DIR, RAW_DIR
from etf_cockpit.core.session_log import log_event, log_exception
from etf_cockpit.core.errors import ErrorStore, classify_exception
from etf_cockpit.core.workflow import WorkflowController, WorkflowStatus, WorkflowStep
from etf_cockpit.data.trust_artifacts import refresh_static_trust_artifacts, write_trust_artifacts_for_scores
from etf_cockpit.features.regime import build_market_regime, write_market_regime
from etf_cockpit.models.calibration import evaluate_forecast_calibration, load_forecast_history, write_forecast_calibration
from etf_cockpit.portfolio.proposals import create_manual_trade_proposal_report
from etf_cockpit.services import ChatGPTBridge, CockpitSnapshot, DataService, build_snapshot
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores, load_latest_candidate_report, simple_scoreboard_frame, write_simple_scoreboard


ACTIVITY_LOG_PATH = LOG_DIR / "activity_log.jsonl"


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
    if not ACTIVITY_LOG_PATH.exists():
        return []
    entries: list[ActivityEntry] = []
    try:
        lines = ACTIVITY_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines[-limit:]:
        try:
            entries.append(ActivityEntry.from_dict(json.loads(line)))
        except Exception:
            continue
    return entries


def _append_activity(entry: ActivityEntry) -> None:
    try:
        ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ACTIVITY_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=True) + "\n")
    except Exception:
        pass


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

    @classmethod
    def load(cls) -> "AppState":
        run_startup_migrations()
        snapshot = build_snapshot()
        try:
            refresh_static_trust_artifacts(snapshot.config)
        except Exception:
            pass
        return cls(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf, recent_activity=_read_recent_activity())

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
        _append_activity(entry)
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
        )
        return entry

    def fail_activity(self, label: str, exc: Exception) -> ActivityEntry:
        entry = self.current_activity or self.begin_activity(label, "Failed")
        result = self.workflow_controller.fail(entry.action_id, exc, retryable=isinstance(exc, (TimeoutError, ConnectionError)))
        entry.status = "failed"
        entry.step = "Failed"
        entry.finished_at = _utc_now()
        entry.message = f"{label} failed: {result.message}"
        self.current_activity = None
        self.last_message = entry.message
        self.recent_activity = (self.recent_activity + [entry])[-8:]
        category, retryable = classify_exception(exc)
        self.error_store.append(
            action_id=entry.action_id,
            category=category,
            user_message=entry.message,
            retryable=retryable,
            detail=str(exc),
        )
        _append_activity(entry)
        log_exception(
            event_type="activity_failed",
            exc=exc,
            action_id=entry.action_id,
            component="app_state",
            button_label=entry.label,
            feature=entry.label,
            operation="fail_activity",
            user_message=entry.message,
        )
        return entry

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
        report = create_manual_trade_proposal_report(
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
