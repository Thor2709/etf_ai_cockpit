from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.session_log import SESSION_LOG_PATH, _event_hash, append_event, event_log_lock_path
from etf_cockpit.operations.models import OperationalEvent


_RECOVERY_LOCK_TIMEOUT_SECONDS = 10.0


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
    """Read the trace, verify its hash chain and quarantine only a genuinely incomplete tail.

    Readers never mutate the file without the cross-process writer lock: a partial last row may be
    a write in flight, so the tail is re-read and re-judged under the lock before truncation.
    """
    if not path.exists():
        return [], TailRecovery()

    events, valid_length, incomplete_tail = _parse_events(path, path.read_bytes())
    if incomplete_tail is None:
        return events, TailRecovery()

    with persistent_file_guard(event_log_lock_path(path), timeout_seconds=_RECOVERY_LOCK_TIMEOUT_SECONDS):
        content = path.read_bytes()
        events, valid_length, incomplete_tail = _parse_events(path, content)
        if incomplete_tail is None:
            return events, TailRecovery()
        quarantine_path = _quarantine_tail(path, incomplete_tail)
        with path.open("r+b") as handle:
            handle.truncate(valid_length)
            handle.flush()
            os.fsync(handle.fileno())
        return events, TailRecovery(True, quarantine_path)


def _parse_events(path: Path, content: bytes) -> tuple[list[OperationalEvent], int, bytes | None]:
    rows = content.splitlines(keepends=True)
    events: list[OperationalEvent] = []
    valid_length = 0
    prior_hash: str | None = None
    hashed = False
    for index, row in enumerate(rows):
        payload = row.rstrip(b"\r\n")
        if not payload:
            valid_length += len(row)
            continue
        try:
            data = json.loads(payload.decode("utf-8"))
            event = OperationalEvent.model_validate(data)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            is_incomplete_tail = index == len(rows) - 1 and not row.endswith((b"\n", b"\r"))
            if not is_incomplete_tail:
                raise ValueError(f"Malformed complete JSONL row {index + 1} in {path}") from exc
            return events, valid_length, payload
        prior_hash, hashed = _verify_link(data, index + 1, path, prior_hash, hashed)
        events.append(event)
        valid_length += len(row)
    return events, valid_length, None


def _verify_link(
    data: dict[str, object],
    row_number: int,
    path: Path,
    prior_hash: str | None,
    hashed: bool,
) -> tuple[str | None, bool]:
    """Check one row against the chain; unhashed rows are tolerated only as a legacy prefix."""
    stored = data.get("event_hash")
    if not stored:
        if hashed:
            raise ValueError(f"Event hash is missing at row {row_number} of {path}")
        return None, False
    if data.get("prior_event_hash") != prior_hash:
        raise ValueError(f"Event hash chain breaks at row {row_number} of {path}")
    unhashed = {key: value for key, value in data.items() if key != "event_hash"}
    if _event_hash(unhashed) != stored:
        raise ValueError(f"Event hash is invalid at row {row_number} of {path}")
    return str(stored), True


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
    ordered = list(events)
    if not ordered:
        return ActivityView.from_event(None)
    # Sequence numbers restart per session, so a stale higher number from an earlier session must not
    # shadow the session that wrote last (the trace is in append order).
    current_session = ordered[-1].session_id
    latest = max(
        (item for item in ordered if item.session_id == current_session),
        key=lambda item: item.sequence_number,
    )
    return ActivityView.from_event(latest)
