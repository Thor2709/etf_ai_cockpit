"""Append-only operational incident records for local paper workflows."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Iterator, Mapping


INCIDENT_JOURNAL_SCHEMA = "operational_incident_journal.v1"
INCIDENT_JOURNAL_HEAD_SCHEMA = "operational_incident_journal_head.v1"
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
        self._head_path = self.path.with_name("journal.head.json")
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
        self._write_head_anchor(sequence=event["sequence"], head_hash=str(event["content_hash"]))

    def _write_head_anchor(self, *, sequence: int, head_hash: str) -> None:
        body = {
            "schema_version": INCIDENT_JOURNAL_HEAD_SCHEMA,
            "account_id": self.account_id,
            "event_count": sequence,
            "head_hash": head_hash,
        }
        anchor = {**body, "content_hash": _digest(body)}
        self._head_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._head_path.with_name(self._head_path.name + ".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(anchor, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._head_path)
            if os.name != "nt":
                directory_fd = os.open(self._head_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as exc:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise IncidentJournalError(f"Incident journal head anchor cannot be written: {exc}") from exc

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
            if self._head_path.exists():
                raise IncidentJournalIntegrityError("Incident journal is missing while its durable head anchor exists.")
            return []
        head_missing = not self._head_path.exists()
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
        if head_missing:
            # An interrupted FIRST append leaves exactly one verified row and no anchor yet; any other
            # shape (empty or longer journal without an anchor) stays fail-closed.
            if len(events) != 1:
                raise IncidentJournalIntegrityError("Incident journal durable head anchor is missing.")
            self._roll_forward_anchor(events)
            return events
        try:
            anchor = json.loads(self._head_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IncidentJournalIntegrityError("Incident journal durable head anchor is malformed.") from exc
        if not isinstance(anchor, dict):
            raise IncidentJournalIntegrityError("Incident journal durable head anchor is invalid.")
        anchor_body = {key: value for key, value in anchor.items() if key != "content_hash"}
        expected_head = str(events[-1]["content_hash"]) if events else _ZERO_HASH
        anchor_valid = (
            set(anchor) == {"schema_version", "account_id", "event_count", "head_hash", "content_hash"}
            and anchor_body.get("schema_version") == INCIDENT_JOURNAL_HEAD_SCHEMA
            and anchor_body.get("account_id") == self.account_id
            and type(anchor_body.get("event_count")) is int
            and anchor.get("content_hash") == _digest(anchor_body)
        )
        if anchor_valid and anchor_body.get("event_count") == len(events) and anchor_body.get("head_hash") == expected_head:
            return events
        # Roll forward ONLY an interrupted append: a valid anchor that describes exactly the journal minus its
        # last (hash-chain verified) row. Truncation, extra rows or any other mismatch stay fail-closed.
        if anchor_valid and events and anchor_body.get("event_count") == len(events) - 1:
            previous_head = str(events[-2]["content_hash"]) if len(events) > 1 else _ZERO_HASH
            if anchor_body.get("head_hash") == previous_head:
                self._roll_forward_anchor(events)
                return events
        raise IncidentJournalIntegrityError("Incident journal does not match its durable head anchor.")

    def _roll_forward_anchor(self, events: list[dict[str, object]]) -> None:
        """Re-anchor a journal whose last append was durable but whose anchor update was interrupted."""

        try:
            self._write_head_anchor(sequence=len(events), head_hash=str(events[-1]["content_hash"]))
        except IncidentJournalError:
            # The verified chain is still trustworthy for this read; the next successful append re-anchors.
            pass


def run_operational_drill(scenario: str) -> dict[str, object]:
    """Exercise paper incident recovery using isolated synthetic persistence."""

    if scenario not in {"disconnect", "order_break"}:
        raise IncidentJournalError("Supported drills are disconnect and order_break.")
    from etf_cockpit.governance.product_scope import load_gate_policy
    from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, _digest as paper_digest
    from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum

    at = datetime.now(timezone.utc)
    code = "disconnect" if scenario == "disconnect" else "order_break"
    input_material = {"instrument_id": "VWCE", "target_quantity": 10.0, "source": f"incident-drill-{scenario}"}
    input_checksum = paper_digest(input_material)
    gate_policy = load_gate_policy()
    if gate_policy.policy is None:
        raise IncidentJournalError("The local paper drill requires a valid gate policy.")
    proposal: dict[str, object] = {
        "schema_version": "proposal.v1",
        "proposal_id": f"proposal_{input_checksum[:20]}",
        "instrument_id": "VWCE",
        "outcome": "proposal_ready",
        "proposal_allowed": True,
        "authority_stage": "paper",
        "execution_allowed": False,
        "quantity_delta": 10.0,
        "rationale": "Synthetic operational incident drill.",
        "gates": [
            {"gate_id": gate_id, "passed": True, "reason": "passed", "blocker": True}
            for gate_id in REQUIRED_GATES
        ],
        "alternatives": [],
        "as_of": at.isoformat(),
        "expires_at": (at + timedelta(days=1)).isoformat(),
        "policy_version": "proposal-policy.v1",
        "authority_policy_checksum": current_authority_policy_checksum(),
        "gate_policy_version": gate_policy.policy.policy_version,
        "gate_policy_checksum": gate_policy.checksum,
        "input_checksum": input_checksum,
        "input_material": input_material,
    }
    proposal["decision_checksum"] = paper_digest(proposal)

    with tempfile.TemporaryDirectory(prefix="paper-incident-drill-") as directory:
        root = Path(directory)
        ledger = PaperLedger(root)
        journal = IncidentJournal(root)
        ledger.open_account(initial_cash=1_000, occurred_at=at)
        accepted_order = ledger.accept_proposal(proposal, execution_price=10, occurred_at=at)
        ledger_before_incident = tuple(
            (str(event["event_id"]), str(event["event_hash"])) for event in ledger._read_events()
        )

        incident = ledger.record_operational_error(
            code,
            message="Synthetic operational drill incident.",
            related_id="synthetic-order",
            occurred_at=at,
        )
        journal_after_incident = tuple(
            (str(event["sequence"]), str(event["content_hash"])) for event in journal.events()
        )
        ledger_after_incident = tuple(
            (str(event["event_id"]), str(event["event_hash"])) for event in ledger._read_events()
        )
        retry_incident = ledger.record_operational_error(
            code,
            message="Synthetic operational drill incident.",
            related_id="synthetic-order",
            occurred_at=at,
        )
        journal_after_incident_retry = tuple(
            (str(event["sequence"]), str(event["content_hash"])) for event in journal.events()
        )
        ledger_after_incident_retry = tuple(
            (str(event["event_id"]), str(event["event_hash"])) for event in ledger._read_events()
        )
        frozen = journal.is_frozen and ledger.snapshot().reconciliation_status == "frozen"
        expected = ledger.reconciliation_state()
        observed = {**expected, "cash": float(expected["cash"]) + 1.0}
        mismatch = ledger.reconcile_operational_state(observed)
        mismatch_frozen = (
            mismatch["status"] == "mismatch"
            and mismatch["frozen"] is True
            and journal.is_frozen
            and ledger.snapshot().reconciliation_status == "frozen"
        )
        try:
            ledger.accept_proposal(proposal, execution_price=10, occurred_at=at)
        except PaperLedgerError:
            frozen_order_retry_blocked = True
        else:
            frozen_order_retry_blocked = False

        recovery = ledger.reconcile_operational_state(expected)
        journal_after_recovery = tuple(
            (str(event["sequence"]), str(event["content_hash"])) for event in journal.events()
        )
        ledger_before_order_retry = tuple(
            (str(event["event_id"]), str(event["event_hash"])) for event in ledger._read_events()
        )
        recovery_retry = ledger.reconcile_operational_state(expected)
        order_retry = ledger.accept_proposal(proposal, execution_price=10, occurred_at=at)
        journal_after_retries = tuple(
            (str(event["sequence"]), str(event["content_hash"])) for event in journal.events()
        )
        ledger_after_retries = tuple(
            (str(event["event_id"]), str(event["event_hash"])) for event in ledger._read_events()
        )
        recovered = (
            recovery["status"] == "ready"
            and recovery["frozen"] is False
            and not journal.is_frozen
            and ledger.snapshot().reconciliation_status == "ready"
        )
        checks = {
            "incident_freezes": frozen,
            "mismatch_keeps_freeze": mismatch_frozen and frozen_order_retry_blocked,
            "clean_reconciliation_recovers": recovered,
            "retry_does_not_duplicate_incident": (
                retry_incident == incident
                and journal_after_incident_retry == journal_after_incident
                and ledger_after_incident_retry == ledger_after_incident
            ),
            "recovery_retry_preserves_journal": (
                recovery_retry["status"] == "ready"
                and journal_after_retries == journal_after_recovery
            ),
            "order_retry_is_idempotent": order_retry["order_id"] == accepted_order["order_id"],
            "ledger_events_preserved": (
                ledger_after_incident[: len(ledger_before_incident)] == ledger_before_incident
                and ledger_after_retries == ledger_before_order_retry
                and len(ledger_after_retries) == ledger.snapshot().event_count
            ),
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
