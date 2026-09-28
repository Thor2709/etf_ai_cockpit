"""Append-only operational incident records for local paper workflows."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Iterator, Mapping


INCIDENT_JOURNAL_SCHEMA = "operational_incident_journal.v1"
_ZERO_HASH = "0" * 64


class IncidentJournalError(ValueError):
    """An invalid operational incident request or journal state."""


class IncidentJournalIntegrityError(IncidentJournalError):
    """The incident journal is malformed or its hash chain has changed."""


class IncidentJournal:
    """Store immutable incident, recovery and post-mortem entries locally."""

    def __init__(self, root: Path, *, account_id: str = "local-paper") -> None:
        self.account_id = _clean_id(account_id, "account_id")
        self.path = root / "data" / "operations" / "incidents" / self.account_id / "journal.jsonl"
        self._lock = threading.RLock()

    @property
    def is_frozen(self) -> bool:
        with self._lock, self._file_lock():
            return bool(self._active_incidents(self._read_events()))

    def record(
        self,
        code: str,
        *,
        message: str,
        related_id: str | None = None,
        requires_freeze: bool = False,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        code_value = _bounded_text(code, "code", 80)
        message_value = _bounded_text(message, "message", 500)
        related_value = None if related_id is None else _clean_id(related_id, "related_id")
        at = _timestamp(occurred_at)
        payload = {
            "account_id": self.account_id,
            "incident_id": "incident_" + _digest(
                {
                    "account_id": self.account_id,
                    "code": code_value,
                    "message": message_value,
                    "related_id": related_value,
                    "occurred_at": at,
                }
            )[:20],
            "code": code_value,
            "message": message_value,
            "related_id": related_value,
            "requires_freeze": bool(requires_freeze),
            "execution_allowed": False,
        }
        with self._lock, self._file_lock():
            events = self._read_events()
            for event in events:
                if event["event_type"] == "incident_recorded" and event["payload"].get("incident_id") == payload["incident_id"]:
                    if event["payload"] != payload:
                        raise IncidentJournalIntegrityError("An incident ID was reused with different content.")
                    return dict(payload)
            self._append(events, "incident_recorded", payload, at)
        return dict(payload)

    def append_postmortem(
        self,
        incident_id: str,
        *,
        summary: str,
        evidence: Mapping[str, object],
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        incident_key = _clean_id(incident_id, "incident_id")
        summary_value = _bounded_text(summary, "summary", 2_000)
        evidence_value = _json_copy(evidence)
        if not isinstance(evidence_value, dict):
            raise IncidentJournalError("Post-mortem evidence must be an object.")
        payload = {
            "account_id": self.account_id,
            "incident_id": incident_key,
            "summary": summary_value,
            "evidence": evidence_value,
            "execution_allowed": False,
        }
        with self._lock, self._file_lock():
            events = self._read_events()
            if not any(
                event["event_type"] == "incident_recorded" and event["payload"].get("incident_id") == incident_key
                for event in events
            ):
                raise IncidentJournalError("A post-mortem requires a recorded incident.")
            previous = next(
                (
                    event["payload"]
                    for event in events
                    if event["event_type"] == "postmortem_recorded"
                    and event["payload"].get("incident_id") == incident_key
                ),
                None,
            )
            if previous is not None:
                if previous != payload:
                    raise IncidentJournalError("An incident post-mortem is immutable once recorded.")
                return dict(previous)
            self._append(events, "postmortem_recorded", payload, _timestamp(occurred_at))
        return dict(payload)

    def reconcile(
        self,
        observed_state: Mapping[str, object],
        expected_state: Mapping[str, object],
        *,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Record a paper-state comparison and clear freezes only on exact match."""

        observed = _canonical_state(observed_state)
        expected = _canonical_state(expected_state)
        with self._lock, self._file_lock():
            events = self._read_events()
            active = self._active_incidents(events)
            if not active:
                return {
                    "status": "ready",
                    "frozen": False,
                    "active_incidents": (),
                    "execution_allowed": False,
                }
            matched = observed == expected
            payload = {
                "account_id": self.account_id,
                "incident_ids": [str(item["incident_id"]) for item in active],
                "observed_state": observed,
                "expected_state": expected,
                "status": "matched" if matched else "mismatch",
                "execution_allowed": False,
            }
            self._append(events, "reconciliation_recorded", payload, _timestamp(occurred_at))
            return {
                "status": "ready" if matched else "mismatch",
                "frozen": not matched,
                "active_incidents": () if matched else tuple(payload["incident_ids"]),
                "execution_allowed": False,
            }

    def events(self) -> tuple[dict[str, object], ...]:
        with self._lock, self._file_lock():
            return tuple(_json_copy(event) for event in self._read_events())

    def snapshot(self) -> dict[str, object]:
        """Return one consistent, verified journal and freeze projection."""

        with self._lock, self._file_lock():
            events = self._read_events()
            return {
                "events": tuple(_json_copy(event) for event in events),
                "frozen": bool(self._active_incidents(events)),
            }

    @staticmethod
    def _active_incidents(events: list[dict[str, object]]) -> list[dict[str, object]]:
        incidents: dict[str, dict[str, object]] = {}
        for event in events:
            kind = event["event_type"]
            payload = event["payload"]
            if kind == "incident_recorded" and payload.get("requires_freeze") is True:
                incidents[str(payload["incident_id"])] = dict(payload)
            elif kind == "reconciliation_recorded" and payload.get("status") == "matched":
                for incident_id in payload.get("incident_ids", []):
                    incidents.pop(str(incident_id), None)
        return list(incidents.values())

    def _append(
        self,
        events: list[dict[str, object]],
        event_type: str,
        payload: Mapping[str, object],
        occurred_at: str,
    ) -> None:
        event: dict[str, object] = {
            "schema_version": INCIDENT_JOURNAL_SCHEMA,
            "account_id": self.account_id,
            "sequence": len(events) + 1,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "payload": _json_copy(payload),
            "prior_hash": str(events[-1]["content_hash"]) if events else _ZERO_HASH,
        }
        event["content_hash"] = _digest(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise IncidentJournalError(f"Incident journal cannot be written: {exc}") from exc

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        lock_path = self.path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_events(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            rows = self.path.read_bytes().splitlines()
        except OSError as exc:
            raise IncidentJournalIntegrityError(f"Incident journal cannot be read: {exc}") from exc
        events: list[dict[str, object]] = []
        prior_hash = _ZERO_HASH
        for sequence, row in enumerate(rows, start=1):
            try:
                event = json.loads(row.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise IncidentJournalIntegrityError(f"Incident journal row {sequence} is malformed.") from exc
            if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
                raise IncidentJournalIntegrityError(f"Incident journal row {sequence} is invalid.")
            claimed_hash = event.get("content_hash")
            unhashed = {key: value for key, value in event.items() if key != "content_hash"}
            if (
                event.get("schema_version") != INCIDENT_JOURNAL_SCHEMA
                or event.get("account_id") != self.account_id
                or event.get("sequence") != sequence
                or event.get("prior_hash") != prior_hash
                or claimed_hash != _digest(unhashed)
                or event.get("event_type") not in {"incident_recorded", "postmortem_recorded", "reconciliation_recorded"}
            ):
                raise IncidentJournalIntegrityError(f"Incident journal hash chain breaks at row {sequence}.")
            prior_hash = str(claimed_hash)
            events.append(event)
        return events


def run_operational_drill(scenario: str) -> dict[str, object]:
    """Exercise freeze, reconciliation and append-only checks using synthetic state."""

    if scenario not in {"disconnect", "order_break"}:
        raise IncidentJournalError("Supported drills are disconnect and order_break.")
    occurred_at = "2000-01-01T00:00:00.000000+00:00"
    code = "unknown_state" if scenario == "disconnect" else "order_break"
    incident = {
        "incident_id": "incident_" + _digest(
            {
                "account_id": "local-paper",
                "code": code,
                "message": "Synthetic operational drill.",
                "related_id": "synthetic-order",
                "occurred_at": occurred_at,
            }
        )[:20],
        "requires_freeze": True,
    }
    journal_events = [{"event_type": "incident_recorded", "payload": incident}]
    frozen = bool(IncidentJournal._active_incidents(journal_events))
    mismatch_state = {"orders": []} != {"orders": ["synthetic-order"]}
    mismatch_events = journal_events + [
        {
            "event_type": "reconciliation_recorded",
            "payload": {"status": "mismatch", "incident_ids": [incident["incident_id"]]},
        }
    ]
    remains_frozen = bool(IncidentJournal._active_incidents(mismatch_events))
    recovery_events = mismatch_events + [
        {
            "event_type": "reconciliation_recorded",
            "payload": {"status": "matched", "incident_ids": [incident["incident_id"]]},
        }
    ]
    recovered = not IncidentJournal._active_incidents(recovery_events)
    ledger_events = [{"event_id": "synthetic-paper-event", "event_type": "order_accepted"}]
    ledger_before = tuple(ledger_events)
    repeated_incident = next(
        event["payload"]
        for event in journal_events
        if event["event_type"] == "incident_recorded"
        and event["payload"].get("incident_id") == incident["incident_id"]
    )
    checks = {
        "incident_freezes": frozen,
        "mismatch_keeps_freeze": mismatch_state and remains_frozen,
        "clean_reconciliation_recovers": recovered,
        "retry_does_not_duplicate_incident": repeated_incident["incident_id"] == incident["incident_id"] and len(journal_events) == 1,
        "ledger_events_preserved": tuple(ledger_events) == ledger_before,
    }
    return {
        "drill_id": scenario,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "execution_allowed": False,
    }


def _canonical_state(value: Mapping[str, object]) -> dict[str, object]:
    copied = _json_copy(value)
    if not isinstance(copied, dict):
        raise IncidentJournalError("Reconciliation state must be an object.")
    return copied


def _clean_id(value: object, label: str) -> str:
    text = str(value or "").strip()
    stem = text.rstrip(" .").split(".", 1)[0].upper()
    reserved = stem in {"CON", "PRN", "AUX", "NUL"} or (
        len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789"
    )
    if (
        not text
        or len(text) > 128
        or text in {".", ".."}
        or any(char in text for char in ("/", "\\", "\x00"))
        or reserved
    ):
        raise IncidentJournalError(f"{label} is invalid.")
    return text


def _bounded_text(value: object, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise IncidentJournalError(f"{label} must be between 1 and {maximum} characters.")
    return text


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    aware = current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _json_copy(value: object) -> object:
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))
    except (TypeError, ValueError) as exc:
        raise IncidentJournalError("Incident evidence must be JSON serialisable.") from exc


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "INCIDENT_JOURNAL_SCHEMA",
    "IncidentJournal",
    "IncidentJournalError",
    "IncidentJournalIntegrityError",
    "run_operational_drill",
]
