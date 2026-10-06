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
