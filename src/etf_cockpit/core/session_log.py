from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etf_cockpit.core.constants import APP_VERSION
from etf_cockpit.core.paths import LOG_DIR, ROOT, ensure_project_dirs

SESSION_LOG_PATH = LOG_DIR / "session.jsonl"
SCHEMA_VERSION = "1.0"
SESSION_LOG_MAX_EVENTS = 5000

_LOCK = threading.Lock()
_SESSION_ID = uuid.uuid4().hex
_SEQUENCE = 0
_INITIALISED = False
_EVENT_COUNTS: dict[Path, int] = {}

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|password|passwd|authorization|bearer)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?ix)"
    r"(?P<key>api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|password|passwd|authorization|bearer)"
    r"(?P<separator>\s*['\"]?\s*[=:]\s*)(?P<quote>['\"]?)(?P<scheme>bearer\s+)?"
    r"(?P<value>[^'\"\s,;}\]]+)"
)
_REDACTED_SECRET_VALUE = "***redacted***"


def init_session_log(
    *,
    clear: bool = True,
    app_version: str = APP_VERSION,
    build_mode: str = "",
    port: int | str | None = None,
    route: str = "/",
) -> Path:
    """Start a fresh app-server diagnostics trace.

    The function is deliberately best-effort. Logging must never prevent the
    cockpit from starting.
    """

    global _SESSION_ID, _SEQUENCE, _INITIALISED
    try:
        ensure_project_dirs()
        with _LOCK:
            _SESSION_ID = uuid.uuid4().hex
            _SEQUENCE = 0
            SESSION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if clear:
                SESSION_LOG_PATH.write_text("", encoding="utf-8")
            else:
                _compact_session_log(SESSION_LOG_PATH, max_events=SESSION_LOG_MAX_EVENTS)
            _EVENT_COUNTS[SESSION_LOG_PATH] = _session_log_event_count(SESSION_LOG_PATH)
            _INITIALISED = True
        log_event(
            event_type="session_start",
            severity="info",
            route=route,
            component="app_server",
            feature="startup",
            operation="init_session_log",
            status="started",
            output_summary={
                "app_version": app_version,
                "build_mode": build_mode,
                "port": None if port is None else str(port),
                "root": str(ROOT),
                "pid": os.getpid(),
            },
        )
    except Exception:
        pass
    return SESSION_LOG_PATH


def session_id() -> str:
    return _SESSION_ID


def new_action_id(prefix: str = "action") -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in prefix.strip().lower())[:28] or "action"
    return f"{cleaned}_{uuid.uuid4().hex[:12]}"


def log_event(
    *,
    event_type: str,
    severity: str = "info",
    action_id: str | None = None,
    parent_action_id: str | None = None,
    route: str | None = None,
    component: str | None = None,
    button_label: str | None = None,
    feature: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    duration_ms: float | int | None = None,
    instrument_id: str | None = None,
    ticker: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    input_summary: Any | None = None,
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
    path: Path | None = None,
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
                "route": route,
                "component": component,
                "button_label": button_label,
                "feature": feature,
                "operation": operation,
                "status": status,
                "duration_ms": duration_ms,
                "instrument_id": instrument_id,
                "ticker": ticker,
                "provider": provider,
                "model": model,
                "input_summary": input_summary,
                "output_summary": output_summary,
                "row_counts": row_counts or {},
                "file_paths": _normalise_paths(file_paths),
                "checksums": checksums or {},
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
        _append_event(event, path=path)
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
    path: Path | None = None,
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
        path=path,
    )


def read_session_events(limit: int = 100) -> list[dict[str, Any]]:
    try:
        if not SESSION_LOG_PATH.exists():
            return []
        lines = SESSION_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        events: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events
    except Exception:
        return []


def session_log_status() -> dict[str, Any]:
    try:
        exists = SESSION_LOG_PATH.exists()
        size_bytes = SESSION_LOG_PATH.stat().st_size if exists else 0
        return {
            "path": str(SESSION_LOG_PATH),
            "exists": exists,
            "size_bytes": size_bytes,
            "session_id": _SESSION_ID,
            "initialised": _INITIALISED,
        }
    except Exception as exc:
        return {
            "path": str(SESSION_LOG_PATH),
            "exists": False,
            "size_bytes": 0,
            "session_id": _SESSION_ID,
            "initialised": _INITIALISED,
            "error": str(_redact(str(exc))),
        }


def copy_session_log_to(destination: Path) -> bool:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not SESSION_LOG_PATH.exists():
            destination.write_text("session log unavailable\n", encoding="utf-8")
            return False
        destination.write_text(SESSION_LOG_PATH.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return True
    except Exception:
        return False


def _base_event() -> dict[str, Any]:
    global _SEQUENCE
    now_utc = datetime.now(timezone.utc)
    with _LOCK:
        _SEQUENCE += 1
        sequence = _SEQUENCE
    return {
        "timestamp_utc": now_utc.isoformat(timespec="milliseconds"),
        "timestamp_local": now_utc.astimezone().isoformat(timespec="milliseconds"),
        "session_id": _SESSION_ID,
        "sequence_number": sequence,
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
    }


def append_event(event: dict[str, Any], *, path: Path = SESSION_LOG_PATH) -> None:
    """Append one redacted, hash-chained row to the existing JSONL trace."""
    _append_event(event, path=path)


def _compact_session_log(path: Path, *, max_events: int) -> None:
    """Bound the canonical trace while retaining a valid hash-chained tail."""

    if max_events < 1 or not path.exists():
        return
    rows = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if len(rows) <= max_events:
        return
    retained = [json.loads(row) for row in rows[-max_events:] if row.strip()]
    prior_hash: str | None = None
    rewritten: list[str] = []
    for event in retained:
        event["prior_event_hash"] = prior_hash
        event.pop("event_hash", None)
        event["event_hash"] = _event_hash(event)
        prior_hash = str(event["event_hash"])
        rewritten.append(json.dumps(event, ensure_ascii=True, default=str, sort_keys=True))
    path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def _session_log_event_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(bool(row.strip()) for row in path.read_text(encoding="utf-8", errors="strict").splitlines())


def _append_event(event: dict[str, Any], *, path: Path | None = None) -> None:
    try:
        ensure_project_dirs()
        target = SESSION_LOG_PATH if path is None else path
        event = _redact(event)
        with _LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            event_count = _EVENT_COUNTS.get(target)
            if event_count is None:
                event_count = _session_log_event_count(target)
            if event_count >= SESSION_LOG_MAX_EVENTS:
                _compact_session_log(target, max_events=SESSION_LOG_MAX_EVENTS - 1)
                event_count = min(event_count, SESSION_LOG_MAX_EVENTS - 1)
            event["event_id"] = str(event.get("event_id") or uuid.uuid4().hex)
            event["prior_event_hash"] = _last_event_hash(target)
            event.pop("event_hash", None)
            event["event_hash"] = _event_hash(event)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True, default=str, sort_keys=True) + "\n")
            _EVENT_COUNTS[target] = event_count + 1
    except Exception:
        pass


def _last_event_hash(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if not lines:
        return None
    previous = json.loads(lines[-1])
    value = previous.get("event_hash")
    return str(value) if value else None


def _event_hash(event: dict[str, Any]) -> str:
    canonical = json.dumps(event, ensure_ascii=True, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    """Redact assignment and JSON-style secret values in arbitrary text."""
    return _SECRET_VALUE_RE.sub(_redact_secret_match, value)


def _redact_secret_match(match: re.Match[str]) -> str:
    return (
        f"{match.group('key')}{match.group('separator')}{match.group('quote')}"
        f"{match.group('scheme') or ''}{_REDACTED_SECRET_VALUE}"
    )


def _normalise_paths(value: list[str | Path] | str | Path | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    return [str(item) for item in value]


def _normalise_list(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value]
