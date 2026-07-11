# Wave 0 Task 2 review package - no-Git base snapshot to current workspace

## Review basis
- Base: immutable Task 2 snapshot captured before the fresh implementer was dispatched; no Git repository or commit existed.
- Head: current workspace after the completion implementer reported COMPLETE.
- Scope: Wave 0 Task 2 only. Task 3 and all later waves are out of scope.
- Base manifest: `.ai_worklog/task-2-code-manifest-before.csv`.
- Base source copies: `.ai_worklog/task-2-base/`.
- The first implementer's original RED transcript was unavailable after the usage-limit interruption; the completion audit's RED/GREEN evidence is recorded in `.ai_worklog/task-2-report.md`.

## Task brief and report
- `.ai_worklog/task-2-brief.md`
- `.ai_worklog/task-2-report.md`

## Changed task paths
- `src/etf_cockpit/operations/__init__.py`
- `src/etf_cockpit/operations/models.py`
- `src/etf_cockpit/operations/event_store.py` (new)
- `src/etf_cockpit/core/session_log.py`
- `src/etf_cockpit/app/state.py`
- `src/etf_cockpit/app/pages/diagnostics.py`
- `tests/operations/test_operational_events.py` (new)
- `tests/operations/test_event_store.py` (new)
- `tests/operations/test_redaction.py` (new)
- `tests/operations/fixtures/session_incomplete_tail.jsonl` (new)

## Diffs

### src/etf_cockpit/operations/__init__.py

diff --git "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\operations\\__init__.py" b/src/etf_cockpit/operations/__init__.py
index 8a1cb2e..de5c3be 100644
--- "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\operations\\__init__.py"
+++ b/src/etf_cockpit/operations/__init__.py
@@ -1,5 +1,5 @@
 """Typed operational and verification records."""
 
-from etf_cockpit.operations.models import ClosureEvidenceRecord, VerificationRun
+from etf_cockpit.operations.models import ClosureEvidenceRecord, OperationalEvent, VerificationRun
 
-__all__ = ["ClosureEvidenceRecord", "VerificationRun"]
+__all__ = ["ClosureEvidenceRecord", "OperationalEvent", "VerificationRun"]

### src/etf_cockpit/operations/models.py

diff --git "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\operations\\models.py" b/src/etf_cockpit/operations/models.py
index 1abacd2..66a9b2c 100644
--- "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\operations\\models.py"
+++ b/src/etf_cockpit/operations/models.py
@@ -1,15 +1,33 @@
 from __future__ import annotations
 
+from datetime import datetime
 from typing import Literal, Self
 
-from pydantic import BaseModel, model_validator
+from pydantic import BaseModel, ConfigDict, model_validator
+
+
+class OperationalEvent(BaseModel):
+    """Typed projection of one row in the authoritative session trace."""
+
+    model_config = ConfigDict(extra="allow")
+
+    event_id: str = ""
+    session_id: str
+    sequence_number: int
+    timestamp_utc: datetime
+    event_type: str
+    status: str | None = None
+    component: str | None = None
+    action_id: str | None = None
+    prior_event_hash: str | None = None
+    event_hash: str | None = None
 
 
 class VerificationRun(BaseModel):
     verification_run_id: str
     verification_type: str
     command: str
     source_hash: str
     result: Literal["pass", "fail", "blocked"]
     exit_code: int
     output_paths: list[str]

### src/etf_cockpit/operations/event_store.py

New file (no base copy):
```text
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from etf_cockpit.core.session_log import SESSION_LOG_PATH, append_event
from etf_cockpit.operations.models import OperationalEvent


@dataclass(frozen=True)
class TailRecovery:
    quarantined_tail: bool = False
    quarantine_path: Path | None = None


@dataclass(frozen=True)
class ActivityView:
    status: str
    sequence_number: int | None = None
    action_id: str | None = None
    event_type: str | None = None

    @classmethod
    def from_event(cls, event: OperationalEvent | None) -> "ActivityView":
        if event is None:
            return cls(status="idle")
        return cls(
            status=event.status or "unknown",
            sequence_number=event.sequence_number,
            action_id=event.action_id,
            event_type=event.event_type,
        )


def load_events_with_tail_recovery(path: Path) -> tuple[list[OperationalEvent], TailRecovery]:
    if not path.exists():
        return [], TailRecovery()

    content = path.read_bytes()
    rows = content.splitlines(keepends=True)
    events: list[OperationalEvent] = []
    valid_length = 0
    for index, row in enumerate(rows):
        payload = row.rstrip(b"\r\n")
        if not payload:
            valid_length += len(row)
            continue
        try:
            data = json.loads(payload.decode("utf-8"))
            events.append(OperationalEvent.model_validate(data))
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            is_incomplete_tail = index == len(rows) - 1 and not row.endswith((b"\n", b"\r"))
            if not is_incomplete_tail:
                raise ValueError(f"Malformed complete JSONL row {index + 1} in {path}") from exc
            quarantine_path = _quarantine_tail(path, payload)
            path.write_bytes(content[:valid_length])
            return events, TailRecovery(True, quarantine_path)
        valid_length += len(row)
    return events, TailRecovery()


def _quarantine_tail(path: Path, tail: bytes) -> Path:
    digest = hashlib.sha256(tail).hexdigest()[:12]
    quarantine_path = path.with_name(f"{path.name}.tail-{digest}.quarantine")
    quarantine_path.write_bytes(tail)
    return quarantine_path


def append_operational_event(
    event: OperationalEvent,
    *,
    path: Path = SESSION_LOG_PATH,
) -> None:
    append_event(event.model_dump(mode="json"), path=path)


def current_activity_view(events: Iterable[OperationalEvent]) -> ActivityView:
    latest = max(events, key=lambda item: item.sequence_number, default=None)
    return ActivityView.from_event(latest)
```

### src/etf_cockpit/core/session_log.py

diff --git "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\core\\session_log.py" b/src/etf_cockpit/core/session_log.py
index eaa3e62..fc54663 100644
--- "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\core\\session_log.py"
+++ b/src/etf_cockpit/core/session_log.py
@@ -110,20 +110,21 @@ def log_event(
     output_summary: Any | None = None,
     row_counts: dict[str, int] | None = None,
     file_paths: list[str | Path] | str | Path | None = None,
     checksums: dict[str, str] | None = None,
     warnings: list[str] | str | None = None,
     blocked_by: list[str] | str | None = None,
     user_message: str | None = None,
     exception_type: str | None = None,
     exception_message_redacted: str | None = None,
     traceback_fingerprint: str | None = None,
+    path: Path | None = None,
     **extra: Any,
 ) -> None:
     try:
         event = _base_event()
         event.update(
             {
                 "action_id": action_id,
                 "parent_action_id": parent_action_id,
                 "event_type": event_type,
                 "severity": severity,
@@ -146,52 +147,54 @@ def log_event(
                 "warnings": _normalise_list(warnings),
                 "blocked_by": _normalise_list(blocked_by),
                 "user_message": user_message,
                 "exception_type": exception_type,
                 "exception_message_redacted": exception_message_redacted,
                 "traceback_fingerprint": traceback_fingerprint,
             }
         )
         if extra:
             event["extra"] = extra
-        _append_event(event)
+        _append_event(event, path=path)
     except Exception:
         pass
 
 
 def log_exception(
     *,
     event_type: str,
     exc: BaseException,
     action_id: str | None = None,
     route: str | None = None,
     component: str | None = None,
     button_label: str | None = None,
     feature: str | None = None,
     operation: str | None = None,
     user_message: str | None = None,
+    path: Path | None = None,
 ) -> None:
     tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
     log_event(
         event_type=event_type,
         severity="error",
         action_id=action_id,
         route=route,
         component=component,
         button_label=button_label,
         feature=feature,
         operation=operation,
         status="failed",
         user_message=user_message,
         exception_type=type(exc).__name__,
         exception_message_redacted=str(_redact(str(exc))),
         traceback_fingerprint=hashlib.sha256(tb_text.encode("utf-8", errors="replace")).hexdigest()[:16],
+        path=path,
     )
 
 
 def read_session_events(limit: int = 100) -> list[dict[str, Any]]:
     try:
         if not SESSION_LOG_PATH.exists():
             return []
         lines = SESSION_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
         events: list[dict[str, Any]] = []
         for line in lines[-limit:]:
@@ -247,32 +250,58 @@ def _base_event() -> dict[str, Any]:
     return {
         "timestamp_utc": now_utc.isoformat(timespec="milliseconds"),
         "timestamp_local": now_utc.astimezone().isoformat(timespec="milliseconds"),
         "session_id": _SESSION_ID,
         "sequence_number": sequence,
         "schema_version": SCHEMA_VERSION,
         "app_version": APP_VERSION,
     }
 
 
-def _append_event(event: dict[str, Any]) -> None:
+def append_event(event: dict[str, Any], *, path: Path = SESSION_LOG_PATH) -> None:
+    """Append one redacted, hash-chained row to the existing JSONL trace."""
+    _append_event(event, path=path)
+
+
+def _append_event(event: dict[str, Any], *, path: Path | None = None) -> None:
     try:
         ensure_project_dirs()
+        target = SESSION_LOG_PATH if path is None else path
         event = _redact(event)
         with _LOCK:
-            SESSION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
-            with SESSION_LOG_PATH.open("a", encoding="utf-8") as handle:
+            target.parent.mkdir(parents=True, exist_ok=True)
+            event["event_id"] = str(event.get("event_id") or uuid.uuid4().hex)
+            event["prior_event_hash"] = _last_event_hash(target)
+            event.pop("event_hash", None)
+            event["event_hash"] = _event_hash(event)
+            with target.open("a", encoding="utf-8") as handle:
                 handle.write(json.dumps(event, ensure_ascii=True, default=str, sort_keys=True) + "\n")
     except Exception:
         pass
 
 
+def _last_event_hash(path: Path) -> str | None:
+    if not path.exists() or path.stat().st_size == 0:
+        return None
+    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
+    if not lines:
+        return None
+    previous = json.loads(lines[-1])
+    value = previous.get("event_hash")
+    return str(value) if value else None
+
+
+def _event_hash(event: dict[str, Any]) -> str:
+    canonical = json.dumps(event, ensure_ascii=True, default=str, sort_keys=True, separators=(",", ":"))
+    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
+
+
 def _redact(value: Any) -> Any:
     if isinstance(value, dict):
         redacted: dict[str, Any] = {}
         for key, item in value.items():
             key_text = str(key)
             if _SECRET_KEY_RE.search(key_text):
                 redacted[key_text] = "***redacted***" if item is not None and item != "" else item
             else:
                 redacted[key_text] = _redact(item)
         return redacted

### src/etf_cockpit/app/state.py

diff --git "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\app\\state.py" b/src/etf_cockpit/app/state.py
index ada319f..a6aad01 100644
--- "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\app\\state.py"
+++ b/src/etf_cockpit/app/state.py
@@ -1,33 +1,35 @@
 from __future__ import annotations
 
-import json
 from dataclasses import dataclass, field
 from datetime import datetime, timezone
 from pathlib import Path
 from typing import Any
 
 from etf_cockpit.core.config import save_provider_settings
 from etf_cockpit.core.migrations import run_startup_migrations
-from etf_cockpit.core.paths import LOG_DIR, RAW_DIR
-from etf_cockpit.core.session_log import log_event, log_exception
+from etf_cockpit.core.paths import RAW_DIR
+from etf_cockpit.core.session_log import SESSION_LOG_PATH, log_event, log_exception
 from etf_cockpit.core.errors import ErrorStore, classify_exception
 from etf_cockpit.core.workflow import WorkflowController, WorkflowStatus, WorkflowStep
 from etf_cockpit.data.trust_artifacts import refresh_static_trust_artifacts, write_trust_artifacts_for_scores
 from etf_cockpit.features.regime import build_market_regime, write_market_regime
 from etf_cockpit.models.calibration import evaluate_forecast_calibration, load_forecast_history, write_forecast_calibration
+from etf_cockpit.operations.event_store import current_activity_view, load_events_with_tail_recovery
 from etf_cockpit.portfolio.proposals import create_manual_trade_proposal_report
 from etf_cockpit.services import ChatGPTBridge, CockpitSnapshot, DataService, build_snapshot
 from etf_cockpit.signals.simple_scores import build_simple_instrument_scores, load_latest_candidate_report, simple_scoreboard_frame, write_simple_scoreboard
 
 
-ACTIVITY_LOG_PATH = LOG_DIR / "activity_log.jsonl"
+# Compatibility seam for existing callers and tests. This is the session trace,
+# not a second mutable activity store.
+ACTIVITY_LOG_PATH = SESSION_LOG_PATH
 
 
 @dataclass
 class ActivityEntry:
     label: str
     status: str
     step: str
     started_at: str
     action_id: str = ""
     parent_action_id: str | None = None
@@ -71,44 +73,47 @@ class ActivityEntry:
             completed_units=int(data.get("completed_units") or 0),
             total_units=None if data.get("total_units") is None else int(data.get("total_units")),
         )
 
 
 def _utc_now() -> str:
     return datetime.now(timezone.utc).isoformat(timespec="seconds")
 
 
 def _read_recent_activity(limit: int = 8) -> list[ActivityEntry]:
-    if not ACTIVITY_LOG_PATH.exists():
-        return []
     entries: list[ActivityEntry] = []
     try:
-        lines = ACTIVITY_LOG_PATH.read_text(encoding="utf-8").splitlines()
+        events, _ = load_events_with_tail_recovery(ACTIVITY_LOG_PATH)
     except Exception:
         return []
-    for line in lines[-limit:]:
-        try:
-            entries.append(ActivityEntry.from_dict(json.loads(line)))
-        except Exception:
+    for event in events:
+        if event.event_type not in {"activity_complete", "activity_failed"}:
             continue
+        data = event.model_dump(mode="json")
+        output_summary = data.get("output_summary") or {}
+        file_paths = data.get("file_paths") or []
+        entries.append(
+            ActivityEntry(
+                label=str(data.get("button_label") or data.get("feature") or "Workflow action"),
+                status=str(event.status or "unknown"),
+                step="Complete" if event.event_type == "activity_complete" else "Failed",
+                started_at=str(data.get("timestamp_local") or data.get("timestamp_utc") or ""),
+                action_id=str(event.action_id or ""),
+                finished_at=str(data.get("timestamp_local") or data.get("timestamp_utc") or ""),
+                message=str(data.get("user_message") or output_summary.get("message") or ""),
+                output_path=str(file_paths[0]) if file_paths else None,
+            )
+        )
+    entries = entries[-limit:]
     return entries
 
 
-def _append_activity(entry: ActivityEntry) -> None:
-    try:
-        ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
-        with ACTIVITY_LOG_PATH.open("a", encoding="utf-8") as handle:
-            handle.write(json.dumps(entry.to_dict(), ensure_ascii=True) + "\n")
-    except Exception:
-        pass
-
-
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
@@ -140,31 +145,33 @@ class AppState:
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
+            path=ACTIVITY_LOG_PATH,
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
+            path=ACTIVITY_LOG_PATH,
         )
         return entry
 
     def update_activity(
         self,
         step: str,
         message: str | None = None,
         *,
         completed_units: int = 0,
         total_units: int | None = None,
@@ -187,50 +194,51 @@ class AppState:
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
+            path=ACTIVITY_LOG_PATH,
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
-        _append_activity(entry)
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
+            path=ACTIVITY_LOG_PATH,
         )
         return entry
 
     def fail_activity(self, label: str, exc: Exception) -> ActivityEntry:
         entry = self.current_activity or self.begin_activity(label, "Failed")
         result = self.workflow_controller.fail(entry.action_id, exc, retryable=isinstance(exc, (TimeoutError, ConnectionError)))
         entry.status = "failed"
         entry.step = "Failed"
         entry.finished_at = _utc_now()
         entry.message = f"{label} failed: {result.message}"
@@ -238,33 +246,41 @@ class AppState:
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
-        _append_activity(entry)
         log_exception(
             event_type="activity_failed",
             exc=exc,
             action_id=entry.action_id,
             component="app_state",
             button_label=entry.label,
             feature=entry.label,
             operation="fail_activity",
             user_message=entry.message,
+            path=ACTIVITY_LOG_PATH,
         )
         return entry
 
+    def current_activity_view(self):
+        """Project the latest visible workflow state from the session trace."""
+        try:
+            events, _ = load_events_with_tail_recovery(ACTIVITY_LOG_PATH)
+        except Exception:
+            events = []
+        return current_activity_view(events)
+
     def refresh_sample_data(self) -> None:
         self.snapshot = build_snapshot(force_sample=True)
         self.selected_etf = self.snapshot.config.ui.default_etf
         self.last_message = "Sample data regenerated and signals refreshed."
 
     def renew_data_dry_run(self) -> str:
         message = DataService(self.snapshot.config).dry_run_update()
         self.last_message = "Renew data dry run completed."
         return message
 

### src/etf_cockpit/app/pages/diagnostics.py

diff --git "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\app\\pages\\diagnostics.py" b/src/etf_cockpit/app/pages/diagnostics.py
index 7956928..e76df89 100644
--- "a/.ai_worklog\\task-2-base\\src\\etf_cockpit\\app\\pages\\diagnostics.py"
+++ b/src/etf_cockpit/app/pages/diagnostics.py
@@ -6,20 +6,21 @@ import platform
 import sys
 
 import flet as ft
 
 from etf_cockpit.app import theme
 from etf_cockpit.app.components.cards import panel, section_header
 from etf_cockpit.app.state import AppState
 from etf_cockpit.core.paths import DATA_DIR, LOG_DIR, MODEL_DIR
 from etf_cockpit.core.session_log import read_session_events, session_log_status
 from etf_cockpit.core.errors import ErrorStore
+from etf_cockpit.operations.event_store import load_events_with_tail_recovery
 
 
 def _module_status(name: str) -> str:
     try:
         module = importlib.import_module(name)
         return f"ok {getattr(module, '__version__', '')}"
     except Exception as exc:
         return f"missing: {exc}"
 
 
@@ -82,29 +83,39 @@ def _performance_panel(state: AppState) -> ft.Control:
         ft.Text(f"Current workflow: {state.current_activity.label if state.current_activity else 'idle'}", color=theme.MUTED),
     ]
     for line in reversed(timing_lines[-6:]):
         rows.append(ft.Text(line, color=theme.MUTED, size=11, selectable=True))
     return panel(ft.Column([section_header("Performance and recovery", "Workflow timing, slow-step visibility and controlled error counts."), *rows], spacing=6))
 
 
 def _session_log_panel() -> ft.Control:
     status = session_log_status()
     events = list(reversed(read_session_events(limit=40)))
+    try:
+        _, recovery = load_events_with_tail_recovery(LOG_DIR / "session.jsonl")
+        integrity_text = (
+            f"Tail recovery: quarantined to {recovery.quarantine_path}"
+            if recovery.quarantined_tail
+            else "Tail recovery: complete JSONL trace"
+        )
+    except ValueError as exc:
+        integrity_text = f"Tail recovery: integrity error - {exc}"
     rows: list[ft.Control] = [
         ft.Text(f"Session ID: {status.get('session_id')}", color=theme.TEXT, selectable=True),
         ft.Text(f"Path: {status.get('path')}", color=theme.MUTED, selectable=True),
         ft.Text(
             f"Exists: {status.get('exists')} | Size: {status.get('size_bytes')} bytes | Initialised: {status.get('initialised')}",
             color=theme.MUTED,
             selectable=True,
         ),
         ft.Text("Secrets are redacted before writing. Logging failures do not block the app.", color=theme.MUTED),
+        ft.Text(integrity_text, color=theme.MUTED, selectable=True),
     ]
     if not events:
         rows.append(ft.Text("No session events recorded yet. Start the app server or press a workflow button.", color=theme.MUTED))
     else:
         rows.append(ft.Text("Recent events", color=theme.TEXT, weight=ft.FontWeight.BOLD))
         for event in events[:25]:
             severity = str(event.get("severity") or "info").lower()
             colour = theme.RED if severity == "error" else theme.AMBER if severity == "warning" else theme.CYAN
             title = (
                 f"{event.get('sequence_number')} | {event.get('event_type')} | "

### tests/operations/test_operational_events.py

New file (no base copy):
```text
from __future__ import annotations

from datetime import datetime, timezone

from etf_cockpit.operations import OperationalEvent
from etf_cockpit.operations.event_store import current_activity_view


def _event(sequence_number: int, status: str) -> OperationalEvent:
    return OperationalEvent(
        event_id=f"event-{sequence_number}",
        session_id="session-1",
        sequence_number=sequence_number,
        timestamp_utc=datetime(2026, 7, 11, tzinfo=timezone.utc),
        event_type="activity_update",
        status=status,
        action_id="action-1",
    )


def test_operational_event_public_model_accepts_legacy_hash_fields() -> None:
    event = OperationalEvent(
        session_id="legacy-session",
        sequence_number=1,
        timestamp_utc=datetime(2026, 7, 11, tzinfo=timezone.utc),
        event_type="session_start",
    )

    assert event.event_id == ""
    assert event.prior_event_hash is None
    assert event.event_hash is None


def test_current_activity_view_uses_the_latest_sequence() -> None:
    view = current_activity_view([_event(2, "completed"), _event(1, "queued")])

    assert view.status == "completed"
    assert view.sequence_number == 2
    assert view.action_id == "action-1"


def test_current_activity_view_is_idle_without_events() -> None:
    assert current_activity_view([]).status == "idle"
```

### tests/operations/test_event_store.py

New file (no base copy):
```text
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from etf_cockpit.app.state import AppState
from etf_cockpit.operations.models import OperationalEvent
from etf_cockpit.operations.event_store import (
    append_operational_event,
    load_events_with_tail_recovery,
)


FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _event(sequence_number: int, *, status: str = "running") -> OperationalEvent:
    return OperationalEvent(
        event_id=f"requested-{sequence_number}",
        session_id="session-1",
        sequence_number=sequence_number,
        timestamp_utc=datetime(2026, 7, 11, 2, sequence_number, tzinfo=timezone.utc),
        event_type="activity_update",
        status=status,
        component="test",
        action_id="action-1",
    )


def test_append_operational_events_builds_an_ordered_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"

    append_operational_event(_event(1), path=path)
    append_operational_event(_event(2, status="completed"), path=path)
    events, recovery = load_events_with_tail_recovery(path)

    assert recovery.quarantined_tail is False
    assert [event.sequence_number for event in events] == [1, 2]
    assert all(event.event_id for event in events)
    assert events[0].prior_event_hash is None
    assert events[0].event_hash
    assert events[1].prior_event_hash == events[0].event_hash
    assert events[1].event_hash != events[0].event_hash


def test_event_store_recovers_only_the_incomplete_jsonl_tail(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    fixture = FIXTURE_DIR / "session_incomplete_tail.jsonl"
    path.write_bytes(fixture.read_bytes() + b'{"event_id":')

    events, recovery = load_events_with_tail_recovery(path)

    assert [event.event_id for event in events] == ["event-1"]
    assert recovery.quarantined_tail is True
    assert recovery.quarantine_path is not None
    assert recovery.quarantine_path.read_text(encoding="utf-8") == '{"event_id":'
    assert path.read_text(encoding="utf-8").endswith('"status":"running"}\n')


def test_event_store_does_not_silently_skip_a_malformed_complete_row(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text('{"event_id":}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="complete JSONL row"):
        load_events_with_tail_recovery(path)


def test_event_store_reports_a_schema_invalid_complete_row_as_an_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text('{"event_id":"incomplete-schema"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed complete JSONL row 1"):
        load_events_with_tail_recovery(path)


def test_app_state_activity_view_is_derived_from_session_events(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "session.jsonl"
    append_operational_event(_event(1, status="queued"), path=path)
    append_operational_event(_event(2, status="completed"), path=path)
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", path)

    state = object.__new__(AppState)

    assert state.current_activity_view().status == "completed"


def test_append_failure_is_best_effort(tmp_path: Path) -> None:
    directory = tmp_path / "not-a-jsonl-file"
    directory.mkdir()

    assert append_operational_event(_event(1), path=directory) is None
```

### tests/operations/test_redaction.py

New file (no base copy):
```text
from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.core.session_log import append_event
from etf_cockpit.operations.event_store import load_events_with_tail_recovery


def test_operational_append_redacts_nested_secrets_before_hashing(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"

    append_event(
        {
            "session_id": "session-1",
            "sequence_number": 1,
            "timestamp_utc": "2026-07-11T00:00:00+00:00",
            "event_type": "activity_update",
            "status": "running",
            "input_summary": {
                "nested": {"api_key": "SHOULD_NOT_APPEAR"},
                "message": "authorization: Bearer SHOULD_NOT_APPEAR",
            },
        },
        path=path,
    )

    text = path.read_text(encoding="utf-8")
    row = json.loads(text)
    events, _ = load_events_with_tail_recovery(path)

    assert "SHOULD_NOT_APPEAR" not in text
    assert row["input_summary"]["nested"]["api_key"] == "***redacted***"
    assert "Bearer ***redacted***" in row["input_summary"]["message"]
    assert events[0].event_hash
```

### tests/operations/fixtures/session_incomplete_tail.jsonl

New file (no base copy):
```text
{"event_id":"event-1","session_id":"session-1","sequence_number":1,"timestamp_utc":"2026-07-11T00:00:00+00:00","event_type":"activity_update","status":"running"}
```

## Verification evidence

# Wave 0 Task 2 - Session trace operational authority

Date: 2026-07-11  
Status: implementation audit complete; no commit and no issue closure.

## Scope and provenance

This report completes the interrupted Task 2 implementation review. The prior implementer reached its usage limit after creating the partial shared change set and left no Task 2 report or trustworthy RED/GREEN transcript. Those prior results are therefore not claimed here.

Review package range: `.ai_worklog/task-2-base/` to the current exact Task 2 scope:

- `src/etf_cockpit/operations/__init__.py`
- `src/etf_cockpit/operations/models.py`
- `src/etf_cockpit/operations/event_store.py`
- `src/etf_cockpit/core/session_log.py`
- `src/etf_cockpit/app/state.py`
- `src/etf_cockpit/app/pages/diagnostics.py`
- `tests/operations/test_operational_events.py`
- `tests/operations/test_event_store.py`
- `tests/operations/test_redaction.py`
- `tests/operations/fixtures/session_incomplete_tail.jsonl`

There is no usable Git repository, so this is a filesystem snapshot range rather than a commit range. No Task 3 scope, broker/order/credential/upload integration, issue status, or execution authority was changed. `execution_allowed` remains `false`.

## Requirement audit

- `OperationalEvent` is typed in the existing operations model module and re-exported from `etf_cockpit.operations`.
- Session-log writes redact first, then add `event_id`, `prior_event_hash`, and canonical `event_hash`; append exceptions remain swallowed by the existing best-effort logging boundary.
- The loader accepts valid legacy rows without event or hash fields, retains all valid complete rows, and quarantines only an unterminated invalid last physical row.
- Malformed complete JSON or schema-invalid complete rows now surface the same contextual `ValueError` integrity failure. This is the only completion-audit production change.
- `AppState.current_activity_view()` reloads the session trace and projects activity with `current_activity_view(events)`. The former persistent `activity_log.jsonl` writer is absent; `ACTIVITY_LOG_PATH` is a compatibility alias for the session trace.
- Diagnostics continues to render the redacted session trace, and reports either tail recovery or an integrity error without preventing the panel from rendering.

## TDD evidence for the completion-audit fix

The gap was error consistency for a complete JSON row that decoded but did not satisfy `OperationalEvent`: Pydantic emitted raw multi-line validation detail, bypassing the loader's documented row-context error.

RED command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_event_store.py -q
```

RED output: exit 1; `test_event_store_reports_a_schema_invalid_complete_row_as_an_integrity_error` failed because the expected `Malformed complete JSONL row 1` did not match Pydantic's raw four-field `ValidationError`.

GREEN implementation: import `ValidationError` and include it in the existing loader parse/validation exception branch. This retains tail recovery only for an incomplete last row; complete rows raise the contextual integrity error.

GREEN command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_event_store.py -q
```

GREEN output: exit 0, `6 passed`.

No other production behaviour was changed during the audit.

## Verification

Focused operational and diagnostics regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_trust_critical_artifacts.py -q
```

Result: exit 0, `21 passed`. Two pre-existing warnings remained: GluonTS JSON performance and pandas mixed-dtype loading.

Scoped static checks:

```powershell
.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\operations\__init__.py src\etf_cockpit\operations\models.py src\etf_cockpit\operations\event_store.py src\etf_cockpit\core\session_log.py src\etf_cockpit\app\state.py src\etf_cockpit\app\pages\diagnostics.py tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py
.\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit\operations src\etf_cockpit\core\session_log.py src\etf_cockpit\app\state.py src\etf_cockpit\app\pages\diagnostics.py
```

Result: both exit 0; Ruff reported `All checks passed!`.

Full check:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Result: exit 0. Existing warnings were GluonTS JSON performance, pandas mixed-dtype loading, and pandas concatenation deprecation. The earlier related workflow/UI run also exited 0 with `34 passed`.

## Fixture and source checksums

JSONL tail fixture SHA-256:

```text
ef7a5209f51a197b239b83e1ae117d6676817883d016325c7704dad1c80d806b  tests/operations/fixtures/session_incomplete_tail.jsonl
```

Current source/test SHA-256 values:

```text
9fdf5b5df2f3833d5637438ba47ab6ba9295294a2476cc29b778978a0df87cf5  src/etf_cockpit/operations/__init__.py
01bdbd1549a8e165fbf136b39666d48a8a6ccd83ea060879481f01d656be916c  src/etf_cockpit/operations/models.py
76e5ff07fd0764d4e9b9c322525ff3eb087ae88086dba69970e5db9e9731652e  src/etf_cockpit/operations/event_store.py
6bd606aa9e6ae001efba3dfe27450d37645406e382fb185f2902706fca418d12  src/etf_cockpit/core/session_log.py
6fbd7fc0a45958b840179146b28f0d61dfd787e9e29086be476ea6ac0a035bb7  src/etf_cockpit/app/state.py
9922f0163ebc78b80f4275defc082199a4a4683476160c8837c92846187193c4  src/etf_cockpit/app/pages/diagnostics.py
8226f91563c3311edc5b616f74ba1ab9fd9ec84e1b7e19837d84ad81e5928c9d  tests/operations/test_operational_events.py
eeced15e1ccdf7535b15d7bb866d0f71873b33c1bb00935917b378872cedbe84  tests/operations/test_event_store.py
a51d28533582ae21696ff55e625cc92f36ad34f613bb9f5e1a466c5aeba676a2  tests/operations/test_redaction.py
```

## Diagnostics semantic capture plan

1. Start the local app with an intentionally incomplete final `logs/session.jsonl` row containing a redaction sentinel, then open Diagnostics.
2. Capture the Session log panel screenshot showing the session path, secret-redaction notice, recent event fields, and `Tail recovery: quarantined to ...` text.
3. Capture the semantic values: panel heading `Session log`; the redaction notice; the tail-recovery text; no sentinel secret in any rendered event detail; and a readable current workflow line.
4. Repeat with a complete schema-invalid row and capture `Tail recovery: integrity error - Malformed complete JSONL row ...`; verify the Diagnostics page remains renderable.
5. Preserve screenshots and the semantic-value transcription with the fixture SHA-256 above. Do not use the capture as evidence to close an issue without independent review.

## Self-review and residual concerns

- The session trace is the only persistent activity log; the in-memory `current_activity` and `recent_activity` fields remain transient UI/workflow convenience state. A fresh reviewer should verify no new persistent activity writer has been introduced elsewhere.
- Hashes are generated for new writes and linked to the preceding write. This task does not add historical chain verification or retroactively hash legacy rows, which is deliberate under the narrow adapter scope.
- Best-effort append failures intentionally do not block application flow; callers receive no durable-failure signal. This matches the existing logging contract and is covered by the append-failure test.
- The prior implementer's original RED evidence is unavailable. The exact completion-audit RED/GREEN cycle above is preserved, and the full suite was run after it.
