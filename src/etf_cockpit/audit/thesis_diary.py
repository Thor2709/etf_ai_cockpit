"""Immutable, local-only diary records for non-executable LLM theses."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, read_atomic_group
from etf_cockpit.core.paths import DATA_DIR


THESIS_DIARY_SCHEMA = "thesis-diary.v1"
THESIS_DIARY_DIR = DATA_DIR / "thesis_diary"
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_OPERATIONS = {"created", "redaction", "review", "expiry", "outcome"}
_REVIEW_STATES = {"pending", "approved", "rejected", "deferred"}
_REDACTION_STATES = {"unredacted", "redacted"}
_OUTCOME_HORIZONS = {"20", "60", "120"}
_BACKTEST_VALIDITY = {"unknown", "forward_only"}


class ThesisDiaryIntegrityError(ValueError):
    """Raised when a diary store or audit-packet record cannot be trusted."""


class ThesisDiaryConflictError(ValueError):
    """Raised when an identity is reused for different immutable content."""


def canonical_json(value: Any) -> bytes:
    """Return the only byte representation used for diary hashes."""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("thesis diary values must be deterministic JSON") from exc


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _normalise_time(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("thesis diary timestamps must be non-empty strings")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("thesis diary timestamps must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("thesis diary timestamps must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _time_key(value: str) -> datetime:
    return datetime.fromisoformat(_normalise_time(value))


def _safe_id(value: str, label: str = "thesis id") -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{label} must be a safe non-empty identifier")
    return value


def _hash(value: str, label: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hash")
    return value


class ThesisDiaryEntry(BaseModel):
    """The immutable input/output packet for one LLM thesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["thesis-diary.v1"] = THESIS_DIARY_SCHEMA
    thesis_id: str
    created_at: str
    decision_time: str
    prompt: str = Field(min_length=1, max_length=200_000)
    prompt_hash: str
    model: str = Field(min_length=1, max_length=1_000)
    model_hash: str
    source_snapshot: dict[str, Any]
    source_hash: str
    retrieval_snapshot: dict[str, Any]
    retrieval_hash: str
    evidence_snapshot: dict[str, Any]
    evidence_snapshot_hash: str
    llm_output: dict[str, Any]
    llm_output_hash: str
    instrument_id: str = "unavailable"
    input_sources: list[str] = Field(default_factory=list)
    thesis_summary: str = ""
    risk_summary: str = ""
    contradiction_summary: str = ""
    uncertainty: float = Field(default=1.0, ge=0, le=1)
    human_review_status: Literal["pending", "approved", "rejected", "deferred"] = "pending"
    evidence_score: float | None = None
    evidence_quality: float | None = None
    risk_friction: float | None = None
    final_advisory_label: str = "manual_review"
    outcomes: dict[str, Any] = Field(default_factory=lambda: {horizon: None for horizon in sorted(_OUTCOME_HORIZONS)})
    backtest_validity: Literal["unknown", "forward_only"] = "unknown"
    redaction_state: Literal["unredacted", "redacted"] = "unredacted"
    expires_at: str | None = None
    execution_allowed: Literal[False] = False
    executable_authority: Literal[False] = False
    checksum: str | None = None


class ThesisDiaryState(BaseModel):
    """Decision-time replay of an immutable entry and its append-only events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["thesis-diary.v1"] = THESIS_DIARY_SCHEMA
    thesis_id: str
    entry: ThesisDiaryEntry
    redaction_state: Literal["unredacted", "redacted"]
    human_review: dict[str, Any]
    expires_at: str | None
    expired: bool
    outcomes: tuple[dict[str, Any], ...]
    applied_event_ids: tuple[str, ...]
    replayed_at: str | None
    execution_allowed: Literal[False] = False
    executable_authority: Literal[False] = False


def build_thesis_entry(
    *,
    prompt: str,
    model: str,
    source_snapshot: dict[str, Any],
    retrieval_snapshot: dict[str, Any],
    evidence_snapshot: dict[str, Any],
    llm_output: dict[str, Any],
    instrument_id: str = "unavailable",
    input_sources: list[str] | None = None,
    thesis_summary: str = "",
    risk_summary: str = "",
    contradiction_summary: str = "",
    uncertainty: float = 1.0,
    human_review_status: Literal["pending", "approved", "rejected", "deferred"] = "pending",
    evidence_score: float | None = None,
    evidence_quality: float | None = None,
    risk_friction: float | None = None,
    final_advisory_label: str = "manual_review",
    outcomes: dict[str, Any] | None = None,
    backtest_validity: Literal["unknown", "forward_only"] = "unknown",
    thesis_id: str | None = None,
    decision_time: str | None = None,
    created_at: str | None = None,
    redaction_state: Literal["unredacted", "redacted"] = "unredacted",
    expires_at: str | None = None,
) -> ThesisDiaryEntry:
    """Build a hash-bound entry; no caller-supplied content hash is trusted."""

    if redaction_state not in _REDACTION_STATES:
        raise ValueError("unsupported thesis redaction state")
    decision = _normalise_time(decision_time or datetime.now(timezone.utc).isoformat())
    created = _normalise_time(created_at or decision)
    expiry = _normalise_time(expires_at) if expires_at is not None else None
    if expiry is not None and _time_key(expiry) < _time_key(decision):
        raise ValueError("thesis expiry cannot precede its decision time")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("thesis prompt must be non-empty")
    instrument = _safe_id(instrument_id, "instrument id")
    sources = list(input_sources or [])
    if any(not isinstance(source, str) or not source.strip() for source in sources):
        raise ValueError("thesis input sources must be non-empty strings")
    checkpoint_values = dict(outcomes or {horizon: None for horizon in sorted(_OUTCOME_HORIZONS)})
    if set(checkpoint_values) - _OUTCOME_HORIZONS:
        raise ValueError("thesis outcomes must use 20, 60 or 120 trading-day horizons")
    if backtest_validity not in _BACKTEST_VALIDITY:
        raise ValueError("unsupported thesis backtest validity")
    if backtest_validity == "forward_only":
        metadata = evidence_snapshot.get("backtest_metadata")
        if not isinstance(metadata, dict) or metadata.get("forward_only") is not True or metadata.get("llm_available_at_decision") is not True:
            raise ValueError("forward-only LLM backtest validity requires explicit decision-time markers")
    for name, value in (("source_snapshot", source_snapshot), ("retrieval_snapshot", retrieval_snapshot), ("evidence_snapshot", evidence_snapshot), ("llm_output", llm_output)):
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be a JSON object")
        canonical_json(value)
    fields = {
        "prompt": prompt,
        "model": model,
        "source_snapshot": source_snapshot,
        "retrieval_snapshot": retrieval_snapshot,
        "evidence_snapshot": evidence_snapshot,
        "llm_output": llm_output,
        "instrument_id": instrument,
        "input_sources": sources,
        "thesis_summary": thesis_summary,
        "risk_summary": risk_summary,
        "contradiction_summary": contradiction_summary,
        "uncertainty": uncertainty,
        "human_review_status": human_review_status,
        "evidence_score": evidence_score,
        "evidence_quality": evidence_quality,
        "risk_friction": risk_friction,
        "final_advisory_label": final_advisory_label,
        "outcomes": checkpoint_values,
        "backtest_validity": backtest_validity,
    }
    identity = sha256_value({**fields, "created_at": created, "decision_time": decision})
    entry = ThesisDiaryEntry(
        thesis_id=_safe_id(thesis_id or f"thesis-{identity[:32]}"),
        created_at=created,
        decision_time=decision,
        prompt=prompt,
        prompt_hash=sha256_value(prompt),
        model=model,
        model_hash=sha256_value(model),
        source_snapshot=source_snapshot,
        source_hash=sha256_value(source_snapshot),
        retrieval_snapshot=retrieval_snapshot,
        retrieval_hash=sha256_value(retrieval_snapshot),
        evidence_snapshot=evidence_snapshot,
        evidence_snapshot_hash=sha256_value(evidence_snapshot),
        llm_output=llm_output,
        llm_output_hash=sha256_value(llm_output),
        instrument_id=instrument,
        input_sources=sources,
        thesis_summary=thesis_summary,
        risk_summary=risk_summary,
        contradiction_summary=contradiction_summary,
        uncertainty=uncertainty,
        human_review_status=human_review_status,
        evidence_score=evidence_score,
        evidence_quality=evidence_quality,
        risk_friction=risk_friction,
        final_advisory_label=final_advisory_label,
        outcomes=checkpoint_values,
        backtest_validity=backtest_validity,
        redaction_state=redaction_state,
        expires_at=expiry,
    )
    return entry.model_copy(update={"checksum": _entry_checksum(entry)})


def _entry_values(entry: ThesisDiaryEntry) -> dict[str, Any]:
    values = entry.model_dump(mode="json")
    values.pop("checksum", None)
    return values


def _entry_checksum(entry: ThesisDiaryEntry) -> str:
    return sha256_value(_entry_values(entry))


def _event_values(event: dict[str, Any]) -> dict[str, Any]:
    values = dict(event)
    values.pop("event_hash", None)
    return values


def _event_checksum(event: dict[str, Any]) -> str:
    return sha256_value(_event_values(event))


def _event_identity_values(event: dict[str, Any]) -> dict[str, Any]:
    values = _event_values(event)
    values.pop("sequence", None)
    values.pop("previous_event_hash", None)
    return values


def _json_bytes(value: Any) -> bytes:
    return canonical_json(value) + b"\n"


def _validate_hash_bindings(entry: ThesisDiaryEntry) -> None:
    expected = {
        "prompt_hash": sha256_value(entry.prompt),
        "model_hash": sha256_value(entry.model),
        "source_hash": sha256_value(entry.source_snapshot),
        "retrieval_hash": sha256_value(entry.retrieval_snapshot),
        "evidence_snapshot_hash": sha256_value(entry.evidence_snapshot),
        "llm_output_hash": sha256_value(entry.llm_output),
    }
    for field, value in expected.items():
        if getattr(entry, field) != value:
            raise ThesisDiaryIntegrityError(f"thesis hash binding mismatch: {entry.thesis_id}:{field}")
    if entry.checksum != _entry_checksum(entry):
        raise ThesisDiaryIntegrityError(f"thesis checksum mismatch: {entry.thesis_id}")
    _safe_id(entry.thesis_id)
    _safe_id(entry.instrument_id, "instrument id")
    if any(not isinstance(source, str) or not source.strip() for source in entry.input_sources):
        raise ThesisDiaryIntegrityError(f"thesis input source is invalid: {entry.thesis_id}")
    if set(entry.outcomes) - _OUTCOME_HORIZONS:
        raise ThesisDiaryIntegrityError(f"thesis outcome horizon is invalid: {entry.thesis_id}")
    if entry.backtest_validity == "forward_only":
        metadata = entry.evidence_snapshot.get("backtest_metadata")
        if not isinstance(metadata, dict) or metadata.get("forward_only") is not True or metadata.get("llm_available_at_decision") is not True:
            raise ThesisDiaryIntegrityError(f"forward-only thesis backtest markers are missing: {entry.thesis_id}")
    _normalise_time(entry.created_at)
    _normalise_time(entry.decision_time)
    if entry.expires_at is not None and _time_key(entry.expires_at) < _time_key(entry.decision_time):
        raise ThesisDiaryIntegrityError(f"thesis expiry precedes decision time: {entry.thesis_id}")
    if entry.execution_allowed is not False or entry.executable_authority is not False:
        raise ThesisDiaryIntegrityError("thesis diary execution authority is not false")


def _validate_event(event: dict[str, Any], expected_sequence: int | None = None) -> None:
    required = {"schema_version", "sequence", "event_id", "thesis_id", "operation", "decision_time", "payload", "previous_event_hash", "event_hash", "execution_allowed"}
    if set(event) != required:
        raise ThesisDiaryIntegrityError("thesis diary event is malformed")
    if event["schema_version"] != THESIS_DIARY_SCHEMA or event["execution_allowed"] is not False:
        raise ThesisDiaryIntegrityError("thesis diary event schema or authority is invalid")
    if not isinstance(event["sequence"], int) or event["sequence"] < 1 or (expected_sequence is not None and event["sequence"] != expected_sequence):
        raise ThesisDiaryIntegrityError("thesis diary event sequence is invalid")
    _safe_id(event["event_id"], "event id")
    _safe_id(event["thesis_id"])
    if event["operation"] not in _OPERATIONS or not isinstance(event["payload"], dict):
        raise ThesisDiaryIntegrityError("thesis diary event operation is invalid")
    _normalise_time(event["decision_time"])
    payload = event["payload"]
    if event["operation"] == "created" and set(payload) != {"entry_checksum"}:
        raise ThesisDiaryIntegrityError("thesis diary created event payload is invalid")
    if event["operation"] == "redaction" and set(payload) != {"state", "reason"}:
        raise ThesisDiaryIntegrityError("thesis diary redaction event payload is invalid")
    if event["operation"] == "review" and set(payload) != {"status", "reviewer", "notes"}:
        raise ThesisDiaryIntegrityError("thesis diary review event payload is invalid")
    if event["operation"] == "expiry" and set(payload) != {"expires_at", "reason"}:
        raise ThesisDiaryIntegrityError("thesis diary expiry event payload is invalid")
    if event["operation"] == "outcome" and set(payload) not in ({"outcome", "observed_at", "details"}, {"horizon", "outcome", "observed_at", "details"}):
        raise ThesisDiaryIntegrityError("thesis diary outcome event payload is invalid")
    if event["operation"] == "created":
        _hash(payload["entry_checksum"], "entry checksum")
    elif event["operation"] == "redaction":
        if payload["state"] not in _REDACTION_STATES or not isinstance(payload["reason"], str):
            raise ThesisDiaryIntegrityError("thesis diary redaction event payload is invalid")
    elif event["operation"] == "review":
        if (
            payload["status"] not in _REVIEW_STATES
            or not isinstance(payload["reviewer"], str)
            or not payload["reviewer"].strip()
            or not isinstance(payload["notes"], str)
        ):
            raise ThesisDiaryIntegrityError("thesis diary review event payload is invalid")
    elif event["operation"] == "expiry":
        _normalise_time(payload["expires_at"])
        if not isinstance(payload["reason"], str):
            raise ThesisDiaryIntegrityError("thesis diary expiry event payload is invalid")
    elif event["operation"] == "outcome":
        if not isinstance(payload["outcome"], str) or not payload["outcome"] or not isinstance(payload["details"], dict):
            raise ThesisDiaryIntegrityError("thesis diary outcome event payload is invalid")
        if "horizon" in payload and payload["horizon"] not in _OUTCOME_HORIZONS:
            raise ThesisDiaryIntegrityError("thesis diary outcome horizon is invalid")
        _normalise_time(payload["observed_at"])
    if event["previous_event_hash"] is not None:
        _hash(event["previous_event_hash"], "previous event hash")
    _hash(event["event_hash"], "event hash")
    if event["event_hash"] != _event_checksum(event):
        raise ThesisDiaryIntegrityError(f"thesis diary event checksum mismatch: {event['event_id']}")


class ThesisDiaryStore:
    """Persist immutable entry payloads and a chained append-only event log."""

    _lock = threading.RLock()

    def __init__(self, root: Path = DATA_DIR):
        self.root = Path(root)

    @property
    def directory(self) -> Path:
        return self.root / "thesis_diary"

    @property
    def index_path(self) -> Path:
        return self.directory / "index.json"

    @property
    def events_path(self) -> Path:
        return self.directory / "events.jsonl"

    def entry_path(self, thesis_id: str) -> Path:
        return self.directory / "entries" / f"{_safe_id(thesis_id)}.json"

    def _read_index(self) -> list[dict[str, str]]:
        if not self.index_path.is_file():
            if (self.directory / "entries").is_dir() and any((self.directory / "entries").glob("*.json")):
                raise ThesisDiaryIntegrityError("thesis diary index is missing")
            return []
        try:
            raw = read_atomic_group((self.index_path,))[0]
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThesisDiaryIntegrityError("thesis diary index is unreadable") from exc
        if not isinstance(value, list):
            raise ThesisDiaryIntegrityError("thesis diary index is not a list")
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in value:
            if not isinstance(row, dict) or set(row) != {"thesis_id", "created_at", "checksum"}:
                raise ThesisDiaryIntegrityError("thesis diary index row is malformed")
            _safe_id(row["thesis_id"])
            _normalise_time(row["created_at"])
            _hash(row["checksum"], "entry checksum")
            if row["thesis_id"] in seen:
                raise ThesisDiaryIntegrityError("duplicate thesis diary index identity")
            seen.add(row["thesis_id"])
            rows.append(row)
        if rows != sorted(rows, key=lambda row: (row["created_at"], row["thesis_id"])):
            raise ThesisDiaryIntegrityError("thesis diary index ordering is invalid")
        return rows

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.is_file():
            return []
        try:
            raw = read_atomic_group((self.events_path,))[0].decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ThesisDiaryIntegrityError("thesis diary event log is unreadable") from exc
        events: list[dict[str, Any]] = []
        previous: str | None = None
        for sequence, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ThesisDiaryIntegrityError("thesis diary event log is malformed") from exc
            if not isinstance(event, dict):
                raise ThesisDiaryIntegrityError("thesis diary event is not an object")
            _validate_event(event, sequence)
            if event["previous_event_hash"] != previous:
                raise ThesisDiaryIntegrityError("thesis diary event hash chain is broken")
            previous = event["event_hash"]
            events.append(event)
        return events

    def _load(self) -> tuple[dict[str, ThesisDiaryEntry], list[dict[str, Any]]]:
        index = self._read_index()
        entries: dict[str, ThesisDiaryEntry] = {}
        for row in index:
            path = self.entry_path(row["thesis_id"])
            try:
                raw = read_atomic_group((path,))[0]
                entry = ThesisDiaryEntry.model_validate(json.loads(raw.decode("utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
                raise ThesisDiaryIntegrityError(f"thesis diary entry is unreadable: {row['thesis_id']}") from exc
            _validate_hash_bindings(entry)
            if entry.thesis_id != row["thesis_id"] or entry.created_at != row["created_at"] or entry.checksum != row["checksum"]:
                raise ThesisDiaryIntegrityError(f"thesis diary index binding mismatch: {entry.thesis_id}")
            entries[entry.thesis_id] = entry
        entries_dir = self.directory / "entries"
        actual_files = {path.stem for path in entries_dir.glob("*.json")} if entries_dir.is_dir() else set()
        if actual_files != set(entries):
            raise ThesisDiaryIntegrityError("thesis diary has unindexed or missing entry payloads")
        events = self._read_events()
        if events and not entries:
            raise ThesisDiaryIntegrityError("thesis diary has events but no entries")
        created_ids: set[str] = set()
        first_event_by_thesis: set[str] = set()
        for event in events:
            if event["thesis_id"] not in entries:
                raise ThesisDiaryIntegrityError("thesis diary event references an unknown thesis")
            if event["thesis_id"] not in first_event_by_thesis and event["operation"] != "created":
                raise ThesisDiaryIntegrityError("thesis diary lifecycle starts without a creation event")
            first_event_by_thesis.add(event["thesis_id"])
            if event["operation"] == "created":
                if event["thesis_id"] in created_ids or event["payload"] != {"entry_checksum": entries[event["thesis_id"]].checksum} or event["decision_time"] != entries[event["thesis_id"]].decision_time:
                    raise ThesisDiaryIntegrityError("thesis diary created event is inconsistent")
                created_ids.add(event["thesis_id"])
        if created_ids != set(entries):
            raise ThesisDiaryIntegrityError("thesis diary creation events are incomplete")
        return entries, events

    def create(self, entry: ThesisDiaryEntry) -> ThesisDiaryEntry:
        """Create once; replaying the same identity/content is idempotent."""

        _validate_hash_bindings(entry)
        with self._lock:
            entries, events = self._load()
            existing = entries.get(entry.thesis_id)
            if existing is not None:
                if existing.model_dump(mode="json") == entry.model_dump(mode="json"):
                    return existing
                raise ThesisDiaryConflictError(f"conflicting thesis identity: {entry.thesis_id}")
            if entry.thesis_id in {row["thesis_id"] for row in self._read_index()}:
                raise ThesisDiaryIntegrityError(f"thesis diary identity is indexed without a payload: {entry.thesis_id}")
            index = [
                {"thesis_id": item.thesis_id, "created_at": item.created_at, "checksum": str(item.checksum)}
                for item in entries.values()
            ]
            index.append({"thesis_id": entry.thesis_id, "created_at": entry.created_at, "checksum": str(entry.checksum)})
            index.sort(key=lambda row: (row["created_at"], row["thesis_id"]))
            previous = events[-1]["event_hash"] if events else None
            event = {
                "schema_version": THESIS_DIARY_SCHEMA,
                "sequence": len(events) + 1,
                "event_id": f"created-{entry.checksum[:32]}",
                "thesis_id": entry.thesis_id,
                "operation": "created",
                "decision_time": entry.decision_time,
                "payload": {"entry_checksum": entry.checksum},
                "previous_event_hash": previous,
                "execution_allowed": False,
            }
            event["event_hash"] = _event_checksum(event)
            diary_entry_path = self.entry_path(entry.thesis_id)
            new_events = events + [event]
            event_bytes = b"".join(_json_bytes(item) for item in new_events)
            requests = (
                AtomicWriteRequest(diary_entry_path, _json_bytes(entry.model_dump(mode="json")), lambda path: ThesisDiaryEntry.model_validate(json.loads(path.read_text(encoding="utf-8")))),
                AtomicWriteRequest(self.index_path, _json_bytes(index), lambda path: json.loads(path.read_text(encoding="utf-8"))),
                AtomicWriteRequest(self.events_path, event_bytes, lambda path: path.read_bytes()),
            )
            atomic_write_group(requests)
            return entry

    def get(self, thesis_id: str) -> ThesisDiaryEntry:
        entries, _ = self._load()
        try:
            return entries[_safe_id(thesis_id)]
        except KeyError as exc:
            raise KeyError(f"unknown thesis: {thesis_id}") from exc

    def list_entries(self) -> list[ThesisDiaryEntry]:
        entries, _ = self._load()
        return sorted(entries.values(), key=lambda entry: (entry.created_at, entry.thesis_id))

    def _append(self, thesis_id: str, operation: str, payload: dict[str, Any], *, decision_time: str, event_id: str | None = None) -> dict[str, Any]:
        entry = self.get(thesis_id)
        decision = _normalise_time(decision_time)
        if operation not in _OPERATIONS - {"created"}:
            raise ValueError("unsupported thesis diary event operation")
        if not isinstance(payload, dict):
            raise ValueError("thesis diary event payload must be an object")
        canonical_json(payload)
        if operation == "redaction" and payload.get("state") not in _REDACTION_STATES:
            raise ValueError("redaction event requires a supported state")
        if operation == "review":
            if payload.get("status") not in _REVIEW_STATES:
                raise ValueError("review event requires a supported status")
            if not isinstance(payload.get("reviewer"), str) or not payload["reviewer"].strip():
                raise ValueError("review event requires a non-empty reviewer")
        if operation == "expiry":
            payload = {**payload, "expires_at": _normalise_time(str(payload.get("expires_at", "")))}
        if operation == "outcome" and not payload.get("outcome"):
            raise ValueError("outcome event requires a non-empty outcome")
        with self._lock:
            entries, events = self._load()
            entry = entries[entry.thesis_id]
            existing_event_id = event_id or f"{operation}-{sha256_value({'thesis_id': thesis_id, 'decision_time': decision, 'payload': payload})[:32]}"
            _safe_id(existing_event_id, "event id")
            candidate_values = {
                "schema_version": THESIS_DIARY_SCHEMA,
                "sequence": len(events) + 1,
                "event_id": existing_event_id,
                "thesis_id": entry.thesis_id,
                "operation": operation,
                "decision_time": decision,
                "payload": payload,
                "previous_event_hash": events[-1]["event_hash"] if events else None,
                "execution_allowed": False,
            }
            candidate_values["event_hash"] = _event_checksum(candidate_values)
            for existing in events:
                if existing["event_id"] == existing_event_id:
                    if _event_identity_values(existing) == _event_identity_values(candidate_values):
                        return existing
                    raise ThesisDiaryConflictError(f"conflicting thesis event identity: {existing_event_id}")
            if events and _time_key(decision) < _time_key(events[-1]["decision_time"]):
                raise ValueError("thesis diary events cannot be backdated")
            _validate_event(candidate_values, len(events) + 1)
            new_events = events + [candidate_values]
            atomic_write_group((AtomicWriteRequest(self.events_path, b"".join(_json_bytes(item) for item in new_events), lambda path: path.read_bytes()),))
            return candidate_values

    def append_redaction(self, thesis_id: str, *, state: Literal["unredacted", "redacted"], reason: str, decision_time: str, event_id: str | None = None) -> dict[str, Any]:
        return self._append(thesis_id, "redaction", {"state": state, "reason": reason}, decision_time=decision_time, event_id=event_id)

    def append_review(self, thesis_id: str, *, status: Literal["pending", "approved", "rejected", "deferred"], reviewer: str, decision_time: str, notes: str = "", event_id: str | None = None) -> dict[str, Any]:
        return self._append(thesis_id, "review", {"status": status, "reviewer": reviewer, "notes": notes}, decision_time=decision_time, event_id=event_id)

    def append_expiry(self, thesis_id: str, *, expires_at: str, decision_time: str, reason: str = "", event_id: str | None = None) -> dict[str, Any]:
        return self._append(thesis_id, "expiry", {"expires_at": expires_at, "reason": reason}, decision_time=decision_time, event_id=event_id)

    def append_outcome(self, thesis_id: str, *, outcome: str, observed_at: str, decision_time: str, details: dict[str, Any] | None = None, horizon: Literal["20", "60", "120"] | None = None, event_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"outcome": outcome, "observed_at": _normalise_time(observed_at), "details": details or {}}
        if horizon is not None:
            payload["horizon"] = horizon
        return self._append(thesis_id, "outcome", payload, decision_time=decision_time, event_id=event_id)

    def replay(self, thesis_id: str, *, at: str | None = None) -> ThesisDiaryState:
        entries, events = self._load()
        entry = entries.get(_safe_id(thesis_id))
        if entry is None:
            raise KeyError(f"unknown thesis: {thesis_id}")
        cutoff = _normalise_time(at) if at is not None else None
        if cutoff is not None and _time_key(cutoff) < _time_key(entry.decision_time):
            raise ValueError("replay time precedes thesis decision time")
        selected = [event for event in events if event["thesis_id"] == entry.thesis_id and (cutoff is None or _time_key(event["decision_time"]) <= _time_key(cutoff))]
        selected.sort(key=lambda event: (event["decision_time"], event["sequence"]))
        redaction_state = entry.redaction_state
        review: dict[str, Any] = {"status": entry.human_review_status, "reviewer": None, "notes": ""}
        expires_at = entry.expires_at
        outcomes: list[dict[str, Any]] = []
        applied: list[str] = []
        for event in selected:
            applied.append(event["event_id"])
            if event["operation"] == "redaction":
                redaction_state = event["payload"]["state"]
            elif event["operation"] == "review":
                review = dict(event["payload"])
            elif event["operation"] == "expiry":
                expires_at = event["payload"]["expires_at"]
            elif event["operation"] == "outcome":
                outcomes.append(dict(event["payload"]))
        replayed_at = cutoff
        replay_time = _time_key(cutoff) if cutoff is not None else datetime.now(timezone.utc)
        expired = expires_at is not None and _time_key(expires_at) <= replay_time
        return ThesisDiaryState(thesis_id=entry.thesis_id, entry=entry, redaction_state=redaction_state, human_review=review, expires_at=expires_at, expired=expired, outcomes=tuple(outcomes), applied_event_ids=tuple(applied), replayed_at=replayed_at)

    def export_packet(self) -> dict[str, Any]:
        entries, events = self._load()
        entry_records = [entries[key].model_dump(mode="json") for key in sorted(entries)]
        event_records = [dict(event) for event in events]
        return {
            "schema_version": THESIS_DIARY_SCHEMA,
            "execution_allowed": False,
            "executable_authority": False,
            "entries": entry_records,
            "events": event_records,
            "checksums": {
                "entries": {record["thesis_id"]: record["checksum"] for record in entry_records},
                "events": sha256_value(event_records),
            },
        }


def reproduce_thesis_from_packet(packet: dict[str, Any], thesis_id: str, *, at: str | None = None) -> ThesisDiaryState:
    """Validate and replay one thesis using only records in an audit packet."""

    if not isinstance(packet, dict) or packet.get("schema_version") != THESIS_DIARY_SCHEMA or packet.get("execution_allowed") is not False or packet.get("executable_authority", False) is not False:
        raise ThesisDiaryIntegrityError("thesis diary audit packet is malformed or executable")
    entries_raw = packet.get("entries")
    events_raw = packet.get("events")
    checksums = packet.get("checksums")
    if not isinstance(entries_raw, list) or not isinstance(events_raw, list) or not isinstance(checksums, dict):
        raise ThesisDiaryIntegrityError("thesis diary audit packet is incomplete")
    entries: dict[str, ThesisDiaryEntry] = {}
    for raw in entries_raw:
        try:
            entry = ThesisDiaryEntry.model_validate(raw)
        except ValidationError as exc:
            raise ThesisDiaryIntegrityError("thesis diary packet entry is malformed") from exc
        _validate_hash_bindings(entry)
        if entry.thesis_id in entries:
            raise ThesisDiaryIntegrityError("duplicate thesis diary packet identity")
        entries[entry.thesis_id] = entry
    if checksums.get("entries") != {key: entries[key].checksum for key in sorted(entries)} or checksums.get("events") != sha256_value(events_raw):
        raise ThesisDiaryIntegrityError("thesis diary packet checksums are inconsistent")
    previous: str | None = None
    parsed_events: list[dict[str, Any]] = []
    created_ids: set[str] = set()
    first_event_by_thesis: set[str] = set()
    for sequence, event in enumerate(events_raw, start=1):
        if not isinstance(event, dict):
            raise ThesisDiaryIntegrityError("thesis diary packet event is malformed")
        _validate_event(event, sequence)
        if event["previous_event_hash"] != previous or event["thesis_id"] not in entries:
            raise ThesisDiaryIntegrityError("thesis diary packet event binding is inconsistent")
        if event["thesis_id"] not in first_event_by_thesis and event["operation"] != "created":
            raise ThesisDiaryIntegrityError("thesis diary packet lifecycle starts without a creation event")
        first_event_by_thesis.add(event["thesis_id"])
        if event["operation"] == "created":
            entry = entries[event["thesis_id"]]
            if event["thesis_id"] in created_ids or event["payload"] != {"entry_checksum": entry.checksum} or event["decision_time"] != entry.decision_time:
                raise ThesisDiaryIntegrityError("thesis diary packet creation binding is inconsistent")
            created_ids.add(event["thesis_id"])
        previous = event["event_hash"]
        parsed_events.append(event)
    if created_ids != set(entries):
        raise ThesisDiaryIntegrityError("thesis diary packet creation records are incomplete")
    thesis = _safe_id(thesis_id)
    if thesis not in entries:
        raise KeyError(f"unknown thesis: {thesis_id}")
    entry = entries[thesis]
    cutoff = _normalise_time(at) if at is not None else None
    if cutoff is not None and _time_key(cutoff) < _time_key(entry.decision_time):
        raise ValueError("replay time precedes thesis decision time")
    selected = [event for event in parsed_events if event["thesis_id"] == thesis and (cutoff is None or _time_key(event["decision_time"]) <= _time_key(cutoff))]
    selected.sort(key=lambda event: (event["decision_time"], event["sequence"]))
    redaction = entry.redaction_state
    review: dict[str, Any] = {"status": entry.human_review_status, "reviewer": None, "notes": ""}
    expires_at = entry.expires_at
    outcomes: list[dict[str, Any]] = []
    applied: list[str] = []
    for event in selected:
        applied.append(event["event_id"])
        if event["operation"] == "redaction":
            redaction = event["payload"]["state"]
        elif event["operation"] == "review":
            review = dict(event["payload"])
        elif event["operation"] == "expiry":
            expires_at = event["payload"]["expires_at"]
        elif event["operation"] == "outcome":
            outcomes.append(dict(event["payload"]))
    replay_time = _time_key(cutoff) if cutoff is not None else datetime.now(timezone.utc)
    expired = expires_at is not None and _time_key(expires_at) <= replay_time
    return ThesisDiaryState(thesis_id=thesis, entry=entry, redaction_state=redaction, human_review=review, expires_at=expires_at, expired=expired, outcomes=tuple(outcomes), applied_event_ids=tuple(applied), replayed_at=cutoff)


def export_thesis_diary_packet(destination: Path, *, root: Path = DATA_DIR) -> Path:
    """Write a deterministic, independently reproducible diary evidence file."""

    payload = ThesisDiaryStore(root).export_packet()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_group((AtomicWriteRequest(destination, _json_bytes(payload), lambda path: json.loads(path.read_text(encoding="utf-8"))),))
    return destination
