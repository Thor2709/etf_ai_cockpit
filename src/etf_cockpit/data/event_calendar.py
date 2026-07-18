"""Availability-aware, local-first calendar events.

Calendar observations are descriptive context.  They are deliberately kept
outside score, target and order paths and fail closed when their temporal
provenance is incomplete.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR


EVENT_SCHEMA_VERSION = "event_calendar.v1"
EVENT_CLEAN_PATH = CLEAN_DIR / "event_calendar.parquet"
EVENT_RAW_DIR = RAW_DIR / "event_calendar"
EVENT_COLUMNS = (
    "schema_version", "event_id", "instrument_id", "event_type", "event_date",
    "event_time", "available_at", "ingested_at", "source_id", "source_authority",
    "source_url", "timezone_name", "precision", "title", "description",
    "risk_level", "validation_status", "validation_reason", "backtest_eligible",
    "context_only", "execution_allowed", "executable_authority", "raw_path", "event_checksum",
)
EVENT_TYPES = frozenset({"earnings", "dividend", "ex_dividend", "split", "corporate_action", "high_risk", "filing", "guidance", "fund_rebalance", "index_change", "review_date"})
RISK_LEVELS = frozenset({"low", "medium", "high", "critical", "unknown"})


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    instrument_id: str
    event_type: str
    event_date: str
    event_time: str = ""
    available_at: str = ""
    ingested_at: str = ""
    source_id: str = ""
    source_authority: str = ""
    source_url: str = ""
    timezone_name: str = "UTC"
    precision: str = "date"
    title: str = ""
    description: str = ""
    risk_level: str = "unknown"


@dataclass(frozen=True)
class EventValidation:
    status: str
    reason: str
    backtest_eligible: bool
    context_only: bool = True
    execution_allowed: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventPersistenceResult:
    raw_paths: tuple[Path, ...]
    clean_path: Path
    audit_path: Path
    rows: int
    checksum: str
    idempotent: bool = False


def validate_event(event: CalendarEvent, decision_time: datetime | None = None) -> EventValidation:
    """Validate event identity, provenance and point-in-time availability."""

    if not str(event.event_id).strip() or not str(event.instrument_id).strip():
        return _invalid("missing_identity", "Event and instrument identifiers are required.")
    event_type = str(event.event_type).strip().casefold()
    if event_type not in EVENT_TYPES:
        return _invalid("unknown_event_type", "Event type is outside the supported context calendar.")
    precision = str(event.precision).strip().casefold()
    if precision not in {"date", "minute", "second"}:
        return _invalid("invalid_precision", "Event precision must be date, minute or second.")
    event_date = _parse_date(event.event_date)
    if event_date is None:
        return _invalid("invalid_event_date", "Event date must be an ISO calendar date.")
    if precision != "date" and _parse_aware(event.event_time) is None:
        return _invalid("ambiguous_event_time", "Timed events require an explicit timezone.")
    available = _parse_aware(event.available_at)
    ingested = _parse_aware(event.ingested_at)
    if available is None or ingested is None:
        return _invalid("ambiguous_availability", "Availability and ingestion timestamps must include an explicit timezone.")
    if ingested < available:
        return _invalid("invalid_availability_order", "Ingestion cannot precede source availability.")
    if not str(event.source_id).strip() or not str(event.source_authority).strip():
        return _invalid("missing_provenance", "Source ID and source authority are required.")
    if str(event.source_url).strip() and not str(event.source_url).strip().lower().startswith(("http://", "https://")):
        return _invalid("invalid_source_url", "Source URL must be HTTP(S) when supplied.")
    risk_level = str(event.risk_level).strip().casefold()
    if risk_level not in RISK_LEVELS:
        return _invalid("invalid_risk_level", "Risk level is outside the supported event vocabulary.")
    if decision_time is not None:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            return _invalid("ambiguous_decision_time", "Decision timestamp must include an explicit timezone.")
        if available > decision_time or ingested > decision_time:
            return _invalid("after_decision_time", "Event was not available at the decision time.")
    return EventValidation("valid_context", "Event provenance and point-in-time metadata are valid.", True)


def persist_calendar_events(
    events: Iterable[CalendarEvent],
    *,
    raw_dir: Path = EVENT_RAW_DIR,
    clean_path: Path = EVENT_CLEAN_PATH,
    audit_path: Path | None = None,
    decision_time: datetime | None = None,
) -> EventPersistenceResult:
    """Validate and atomically append a complete event batch."""

    items = tuple(events)
    if not items:
        raise ValueError("At least one calendar event is required.")
    raw_dir, clean_path = Path(raw_dir), Path(clean_path)
    audit_path = Path(audit_path or clean_path.with_name(clean_path.stem + "_audit.json"))
    existing = _read_clean_strict(clean_path)
    rows: list[dict[str, Any]] = []
    raw_requests: list[AtomicWriteRequest] = []
    raw_paths: list[Path] = []
    validations: list[dict[str, Any]] = []
    for event in items:
        validation = validate_event(event, decision_time)
        if not validation.backtest_eligible:
            raise ValueError(f"Invalid event {event.event_id}: {validation.status}: {validation.reason}")
        payload = _event_payload(event)
        checksum = _checksum(payload)
        raw_path = raw_dir / f"{_safe_id(event.event_id)}-{checksum[:16]}.json"
        raw_paths.append(raw_path)
        if not raw_path.exists():
            raw_requests.append(AtomicWriteRequest(raw_path, (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"), lambda path: json.loads(path.read_text(encoding="utf-8"))))
        rows.append(_clean_row(event, validation, checksum, raw_path, raw_dir))
        validations.append({"event_id": event.event_id, **asdict(validation)})
    candidate = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    _reject_conflicting_duplicates(pd.concat([existing, candidate], ignore_index=True))
    combined = pd.concat([existing, candidate], ignore_index=True).drop_duplicates(subset=["event_id", "event_checksum"], keep="last")
    combined = sort_calendar_events(combined)
    payload = {"schema_version": EVENT_SCHEMA_VERSION, "rows": len(combined), "checksum": _frame_checksum(combined), "validations": validations, "context_only": True, "execution_allowed": False}
    csv_payload = _safe_csv(combined).encode("utf-8")
    requests = [
        AtomicWriteRequest(clean_path, parquet_payload(combined), validate_parquet_file),
        AtomicWriteRequest(clean_path.with_suffix(".csv"), csv_payload, lambda path: pd.read_csv(path)),
        AtomicWriteRequest(audit_path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"), lambda path: json.loads(path.read_text(encoding="utf-8"))),
        *raw_requests,
    ]
    atomic_write_group(tuple(requests))
    return EventPersistenceResult(tuple(raw_paths), clean_path, audit_path, len(combined), _frame_checksum(combined), len(existing) == len(combined))


def load_calendar_events(path: Path = EVENT_CLEAN_PATH) -> pd.DataFrame:
    return sort_calendar_events(_read_clean(Path(path)))


def sort_calendar_events(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(columns=EVENT_COLUMNS)
    result = frame.copy()
    result["_date_sort"] = pd.to_datetime(result.get("event_date"), errors="coerce")
    result["_time_sort"] = pd.to_datetime(result.get("event_time"), errors="coerce", utc=True)
    result = result.sort_values(["_date_sort", "_time_sort", "instrument_id", "event_id", "event_checksum"], kind="stable", na_position="last")
    return result.drop(columns=["_date_sort", "_time_sort"], errors="ignore").reset_index(drop=True)


def events_available_as_of(frame: pd.DataFrame, decision_time: datetime, instrument_id: str | None = None) -> pd.DataFrame:
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("Decision timestamp must include an explicit timezone.")
    source = load_calendar_events() if frame is None else frame.copy()
    if source.empty:
        return source
    available = pd.to_datetime(source.get("available_at"), errors="coerce", utc=True)
    ingested = pd.to_datetime(source.get("ingested_at"), errors="coerce", utc=True)
    cutoff = pd.Timestamp(decision_time).tz_convert("UTC")
    mask = available.notna() & ingested.notna() & (available <= cutoff) & (ingested <= cutoff)
    if "backtest_eligible" in source.columns:
        mask &= source["backtest_eligible"].map(lambda value: value is True or str(value).strip().casefold() in {"1", "true", "yes"})
    if "validation_status" in source.columns:
        mask &= source["validation_status"].astype(str).str.casefold().eq("valid_context")
    if instrument_id is not None and "instrument_id" in source.columns:
        mask &= source["instrument_id"].astype(str).eq(str(instrument_id))
    return sort_calendar_events(source.loc[mask].copy())


def _invalid(status: str, reason: str) -> EventValidation:
    return EventValidation(status, reason, False)


def _parse_aware(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _parse_date(value: object) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None
    return parsed.isoformat()


def _event_payload(event: CalendarEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload.update({"schema_version": EVENT_SCHEMA_VERSION, "context_only": True, "execution_allowed": False, "executable_authority": False})
    return payload


def _clean_row(event: CalendarEvent, validation: EventValidation, checksum: str, raw_path: Path, raw_dir: Path) -> dict[str, Any]:
    row = _event_payload(event)
    row.update({"validation_status": validation.status, "validation_reason": validation.reason, "backtest_eligible": validation.backtest_eligible, "context_only": True, "execution_allowed": False, "executable_authority": False, "raw_path": raw_path.relative_to(raw_dir.parent.parent).as_posix() if raw_dir.parent.parent.exists() else raw_path.name, "event_checksum": checksum})
    return {column: row.get(column, "") for column in EVENT_COLUMNS}


def _read_clean(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=EVENT_COLUMNS)
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    for column, default in (("context_only", True), ("execution_allowed", False), ("executable_authority", False)):
        if column not in frame.columns:
            frame[column] = default
    frame["context_only"], frame["execution_allowed"], frame["executable_authority"] = True, False, False
    return frame


def _read_clean_strict(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=EVENT_COLUMNS)
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise ValueError(f"Canonical event ledger cannot be read: {path}") from exc
    missing = [column for column in ("event_id", "instrument_id", "event_checksum", "available_at", "ingested_at") if column not in frame.columns]
    if missing:
        raise ValueError("Canonical event ledger has unsupported schema; missing: " + ", ".join(missing))
    return frame


def _reject_conflicting_duplicates(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    grouped = frame.groupby(["event_id", "source_id"], dropna=False)["event_checksum"].nunique()
    if bool((grouped > 1).any()):
        raise ValueError("Conflicting observations for the same event/source are retained for manual resolution.")


def _safe_csv(frame: pd.DataFrame) -> str:
    safe = frame.copy()
    for column in safe.select_dtypes(include=["object"]).columns:
        safe[column] = safe[column].map(lambda value: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value)
    return safe.to_csv(index=False)


def _frame_checksum(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    stable = frame.sort_index(axis=1).astype(str).sort_values(list(frame.columns), kind="stable")
    return hashlib.sha256(stable.to_csv(index=False).encode("utf-8")).hexdigest()


def _checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in str(value)) or "unknown"


__all__ = ["CalendarEvent", "EventPersistenceResult", "EventValidation", "EVENT_CLEAN_PATH", "EVENT_RAW_DIR", "EVENT_SCHEMA_VERSION", "EVENT_TYPES", "events_available_as_of", "load_calendar_events", "persist_calendar_events", "sort_calendar_events", "validate_event"]
