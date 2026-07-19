"""Local, append-only forward-evidence diary.

Decision-time manifests are immutable. Later outcome observations are separate
versioned records so an updated price, source or reconciliation state never
rewrites the original decision evidence.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from etf_cockpit.core.atomic_io import AtomicWriteRequest, _pid_alive, atomic_write_group, read_atomic_group


class ForwardEvidenceIntegrityError(ValueError):
    """Raised when diary evidence is missing, malformed or tampered with."""


HashText = str
OutcomeStatus = Literal["pending", "available", "unavailable", "stale", "conflicted"]
ProposalOutcome = Literal[
    "not_proposed",
    "observation_only",
    "paper_proposed",
    "paper_accepted",
    "paper_rejected",
    "cancelled",
    "expired",
]

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA_VERSION = "forward-evidence.v1"
_ROOT_NAME = "forward_evidence_diary"
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK = threading.RLock()
_MAX_IDENTIFIERS = 128
_MAX_METRICS = 64
_MAX_METRIC_NAME_LENGTH = 80
_MAX_METRIC_TEXT_LENGTH = 1_000


def _validate_hash(value: str, field_name: str) -> str:
    value = str(value).strip().lower()
    if not _HASH_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 checksum")
    return value


def _validate_id(value: str, field_name: str) -> str:
    value = str(value).strip()
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe identifier")
    return value


def _canonical(model: BaseModel) -> bytes:
    payload = model.model_dump(mode="json", exclude={"checksum"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _checksum(model: BaseModel) -> str:
    return hashlib.sha256(_canonical(model)).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ForwardInputManifest(BaseModel):
    """Hashes and provenance captured at decision time."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    data_hash: HashText
    formula_hash: HashText
    model_hash: HashText
    portfolio_hash: HashText
    policy_hash: HashText
    proposal_hash: HashText
    source_authority: str = Field(min_length=1, max_length=200)
    source_checksum: HashText

    @field_validator("data_hash", "formula_hash", "model_hash", "portfolio_hash", "policy_hash", "proposal_hash", "source_checksum")
    @classmethod
    def validate_checksums(cls, value: str, info) -> str:
        return _validate_hash(value, info.field_name)

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return value


class ForwardEvidenceObservation(BaseModel):
    """Immutable decision-time observation opportunity."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    created_at: datetime
    instrument_ids: tuple[str, ...] = Field(min_length=1)
    manifest: ForwardInputManifest
    proposal_outcome: ProposalOutcome
    proposal_id: str | None = None
    paper_order_ids: tuple[str, ...] = ()
    decision: str = Field(min_length=1, max_length=80)
    rationale: str = Field(default="", max_length=2_000)
    execution_allowed: Literal[False] = False
    schema_version: str = _SCHEMA_VERSION
    checksum: str | None = None

    @field_validator("observation_id")
    @classmethod
    def validate_observation_id(cls, value: str) -> str:
        return _validate_id(value, "observation_id")

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("instrument_ids", "paper_order_ids")
    @classmethod
    def validate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > _MAX_IDENTIFIERS:
            raise ValueError(f"diary identifiers cannot exceed {_MAX_IDENTIFIERS} values")
        cleaned = tuple(_validate_id(value, "instrument_id") for value in values)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("diary identifiers must be unique")
        return cleaned

    @field_validator("proposal_id")
    @classmethod
    def validate_proposal_id(cls, value: str | None) -> str | None:
        return None if value is None else _validate_id(value, "proposal_id")


class ForwardEvidenceOutcome(BaseModel):
    """Immutable version of a later outcome observation."""

    model_config = ConfigDict(extra="forbid")

    outcome_id: str
    observation_id: str
    version: int = Field(ge=1)
    recorded_at: datetime
    outcome_as_of: datetime
    status: OutcomeStatus
    source_authority: str = Field(min_length=1, max_length=200)
    source_checksum: HashText
    metrics: dict[str, float | str] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2_000)
    checksum: str | None = None

    @field_validator("outcome_id", "observation_id")
    @classmethod
    def validate_record_ids(cls, value: str, info) -> str:
        return _validate_id(value, info.field_name)

    @field_validator("source_checksum")
    @classmethod
    def validate_source_checksum(cls, value: str) -> str:
        return _validate_hash(value, "source_checksum")

    @field_validator("recorded_at", "outcome_as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("outcome timestamps must include a timezone")
        return value

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, values: dict[str, float | str]) -> dict[str, float | str]:
        if len(values) > _MAX_METRICS:
            raise ValueError(f"outcome metrics cannot exceed {_MAX_METRICS} values")
        cleaned: dict[str, float | str] = {}
        for key, value in values.items():
            key_text = str(key).strip()
            if not key_text or len(key_text) > _MAX_METRIC_NAME_LENGTH:
                raise ValueError("outcome metric names must be non-blank and bounded")
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError("outcome metrics must be finite")
            if isinstance(value, str) and len(value) > _MAX_METRIC_TEXT_LENGTH:
                raise ValueError("outcome metric text values are too long")
            cleaned[key_text] = value
        return cleaned


class ForwardEvidenceSnapshot(BaseModel):
    """Read model combining one immutable manifest with its latest outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation: ForwardEvidenceObservation
    outcome: ForwardEvidenceOutcome


class ForwardEvidenceDiary:
    """Persist decision manifests and outcome revisions under a local root."""

    def _directory(self, root: Path) -> Path:
        return Path(root) / _ROOT_NAME

    def _observation_path(self, root: Path, observation_id: str) -> Path:
        return self._directory(root) / "observations" / f"{_validate_id(observation_id, 'observation_id')}.json"

    def _outcome_path(self, root: Path, outcome_id: str) -> Path:
        return self._directory(root) / "outcomes" / f"{_validate_id(outcome_id, 'outcome_id')}.json"

    def _index_path(self, root: Path) -> Path:
        return self._directory(root) / "index.json"

    def _operations_path(self, root: Path) -> Path:
        return self._directory(root) / "operations.jsonl"

    def _lock_path(self, root: Path) -> Path:
        return self._directory(root) / ".diary-write.lock"

    @contextmanager
    def _write_lock(self, root: Path):
        directory = self._directory(root)
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = self._lock_path(root)
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        token = f"{os.getpid()}:{uuid.uuid4().hex}"
        while True:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(descriptor, token.encode("ascii"))
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    try:
                        owner_text = lock_path.read_text(encoding="ascii")
                        owner_pid_text, separator, _ = owner_text.partition(":")
                        owner_pid = int(owner_pid_text) if separator else 0
                        if owner_pid > 0 and not _pid_alive(owner_pid):
                            if lock_path.read_text(encoding="ascii") == owner_text:
                                lock_path.unlink()
                                continue
                    except (OSError, UnicodeDecodeError, ValueError):
                        pass
                    raise TimeoutError(f"forward-evidence diary lock is unavailable: {lock_path}")
                time.sleep(0.025)
        try:
            yield
        finally:
            try:
                if lock_path.read_text(encoding="ascii") == token:
                    lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_index(self, root: Path) -> list[dict[str, object]]:
        path = self._index_path(root)
        if not path.is_file():
            directory = self._directory(root)
            if any((directory / folder).is_dir() and any((directory / folder).glob("*.json")) for folder in ("observations", "outcomes")) or (directory / "operations.jsonl").is_file():
                raise ForwardEvidenceIntegrityError("forward-evidence index is missing")
            return []
        try:
            value = json.loads(read_atomic_group((path,))[0].decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ForwardEvidenceIntegrityError("forward-evidence index is unreadable") from exc
        return self._validate_index_value(value)

    @staticmethod
    def _validate_index_value(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            raise ForwardEvidenceIntegrityError("forward-evidence index is malformed")
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        required = {"observation_id", "observation_checksum", "outcome_id", "outcome_checksum", "version"}
        for row in value:
            if not isinstance(row, dict) or set(row) != required:
                raise ForwardEvidenceIntegrityError("forward-evidence index row is malformed")
            observation_id = _validate_id(str(row["observation_id"]), "observation_id")
            if observation_id in seen or not _HASH_RE.fullmatch(str(row["observation_checksum"])) or not _HASH_RE.fullmatch(str(row["outcome_checksum"])):
                raise ForwardEvidenceIntegrityError("forward-evidence index row is invalid")
            if not isinstance(row["version"], int) or row["version"] < 1:
                raise ForwardEvidenceIntegrityError("forward-evidence outcome version is invalid")
            seen.add(observation_id)
            rows.append(dict(row))
        return rows

    def _validate_artifacts(self, root: Path, index: list[dict[str, object]]) -> None:
        directory = self._directory(root)
        observation_paths = {path.stem: path for path in (directory / "observations").glob("*.json")} if (directory / "observations").is_dir() else {}
        index_ids = {str(row["observation_id"]) for row in index}
        if set(observation_paths) != index_ids:
            raise ForwardEvidenceIntegrityError("forward-evidence observation files do not match the index")
        outcome_paths = tuple((directory / "outcomes").glob("*.json")) if (directory / "outcomes").is_dir() else ()
        versions: dict[str, list[int]] = {}
        for row in index:
            observation_id = str(row["observation_id"])
            self._stored_observation(root, observation_paths[observation_id], str(row["observation_checksum"]))
            current_path = self._outcome_path(root, str(row["outcome_id"]))
            current = self._stored_outcome(current_path, str(row["outcome_checksum"]))
            if current.observation_id != observation_id or current.version != row["version"]:
                raise ForwardEvidenceIntegrityError(f"forward-evidence current outcome linkage mismatch: {observation_id}")
        for path in outcome_paths:
            try:
                outcome = ForwardEvidenceOutcome.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ForwardEvidenceIntegrityError(f"forward-evidence outcome is malformed: {path.name}") from exc
            expected_name = f"{outcome.observation_id}-outcome-{outcome.version}"
            if outcome.observation_id not in index_ids or path.stem != outcome.outcome_id or path.stem != expected_name:
                raise ForwardEvidenceIntegrityError(f"forward-evidence outcome linkage is invalid: {path.name}")
            if not outcome.checksum or outcome.checksum != _checksum(outcome):
                raise ForwardEvidenceIntegrityError(f"forward-evidence outcome checksum mismatch: {path.name}")
            versions.setdefault(outcome.observation_id, []).append(outcome.version)
        for observation_id in index_ids:
            observed_versions = sorted(versions.get(observation_id, ()))
            if observed_versions != list(range(1, max(observed_versions, default=0) + 1)):
                raise ForwardEvidenceIntegrityError(f"forward-evidence outcome history has a gap: {observation_id}")
        if index:
            operations_path = self._operations_path(root)
            if not operations_path.is_file():
                raise ForwardEvidenceIntegrityError("forward-evidence operation log is missing")
            raw = self._read_operations(root)
            operation_ids = {json.loads(line)["observation_id"] for line in raw.decode("utf-8").splitlines() if line.strip()}
            if not index_ids.issubset(operation_ids):
                raise ForwardEvidenceIntegrityError("forward-evidence operation log is incomplete")

    def _read_operations(self, root: Path) -> bytes:
        path = self._operations_path(root)
        if not path.is_file():
            return b""
        try:
            raw = read_atomic_group((path,))[0]
            self._validate_operations_bytes(raw)
            return raw
        except ForwardEvidenceIntegrityError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ForwardEvidenceIntegrityError("forward-evidence operation log is unreadable") from exc

    @staticmethod
    def _validate_operations_bytes(raw: bytes) -> None:
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or set(row) != {"operation", "observation_id", "record_id", "checksum", "schema_version"}:
                raise ForwardEvidenceIntegrityError("forward-evidence operation row is malformed")
            if row["operation"] not in {"observed", "outcome_updated"} or row["schema_version"] != _SCHEMA_VERSION:
                raise ForwardEvidenceIntegrityError("forward-evidence operation row is invalid")
            _validate_id(str(row["observation_id"]), "observation_id")
            _validate_id(str(row["record_id"]), "record_id")
            _validate_hash(str(row["checksum"]), "checksum")

    def _stored_observation(self, root: Path, path: Path, expected_checksum: str) -> ForwardEvidenceObservation:
        try:
            observation = ForwardEvidenceObservation.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ForwardEvidenceIntegrityError(f"forward-evidence observation is malformed: {path.name}") from exc
        if path.stem != observation.observation_id or not observation.checksum or observation.checksum != _checksum(observation) or observation.checksum != expected_checksum:
            raise ForwardEvidenceIntegrityError(f"forward-evidence observation checksum mismatch: {path.name}")
        return observation

    def _stored_outcome(self, path: Path, expected_checksum: str) -> ForwardEvidenceOutcome:
        try:
            outcome = ForwardEvidenceOutcome.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ForwardEvidenceIntegrityError(f"forward-evidence outcome is malformed: {path.name}") from exc
        if path.stem != outcome.outcome_id or not outcome.checksum or outcome.checksum != _checksum(outcome) or outcome.checksum != expected_checksum:
            raise ForwardEvidenceIntegrityError(f"forward-evidence outcome checksum mismatch: {path.name}")
        return outcome

    @staticmethod
    def _operation_bytes(existing: bytes, operation: str, observation_id: str, record_id: str, checksum: str) -> bytes:
        record = {"operation": operation, "observation_id": observation_id, "record_id": record_id, "checksum": checksum, "schema_version": _SCHEMA_VERSION}
        return existing + (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def record_observation(self, observation: ForwardEvidenceObservation, *, root: Path) -> ForwardEvidenceSnapshot:
        root = Path(root)
        if observation.schema_version != _SCHEMA_VERSION:
            raise ValueError("unsupported forward-evidence schema version")
        stored = observation.model_copy(update={"checksum": None})
        stored = stored.model_copy(update={"checksum": _checksum(stored)})
        pending = ForwardEvidenceOutcome(
            outcome_id=f"{stored.observation_id}-outcome-1",
            observation_id=stored.observation_id,
            version=1,
            recorded_at=stored.created_at,
            outcome_as_of=stored.manifest.as_of,
            status="pending",
            source_authority="not_recorded",
            source_checksum="0" * 64,
        )
        pending = pending.model_copy(update={"checksum": _checksum(pending)})
        with _LOCK, self._write_lock(root):
            index = self._read_index(root)
            self._validate_artifacts(root, index)
            if any(row["observation_id"] == stored.observation_id for row in index):
                raise ValueError(f"duplicate observation id: {stored.observation_id}")
            observation_path = self._observation_path(root, stored.observation_id)
            outcome_path = self._outcome_path(root, pending.outcome_id)
            if observation_path.exists() or outcome_path.exists():
                raise ForwardEvidenceIntegrityError("forward-evidence immutable destination already exists")
            index.append({"observation_id": stored.observation_id, "observation_checksum": stored.checksum, "outcome_id": pending.outcome_id, "outcome_checksum": pending.checksum, "version": 1})
            index.sort(key=lambda row: str(row["observation_id"]))
            operations = self._operation_bytes(self._read_operations(root), "observed", stored.observation_id, stored.observation_id, str(stored.checksum))
            operations = self._operation_bytes(operations, "outcome_updated", stored.observation_id, pending.outcome_id, str(pending.checksum))
            requests = (
                AtomicWriteRequest(self._observation_path(root, stored.observation_id), _json_bytes(stored.model_dump(mode="json")), lambda path: ForwardEvidenceObservation.model_validate(json.loads(path.read_text(encoding="utf-8")))),
                AtomicWriteRequest(self._outcome_path(root, pending.outcome_id), _json_bytes(pending.model_dump(mode="json")), lambda path: ForwardEvidenceOutcome.model_validate(json.loads(path.read_text(encoding="utf-8")))),
                AtomicWriteRequest(self._index_path(root), _json_bytes(index), lambda path: self._validate_index_value(json.loads(path.read_text(encoding="utf-8")))),
                AtomicWriteRequest(self._operations_path(root), operations, lambda path: self._validate_operations_bytes(path.read_bytes())),
            )
            atomic_write_group(requests)
        return ForwardEvidenceSnapshot(observation=stored, outcome=pending)

    def update_outcome(
        self,
        observation_id: str,
        *,
        status: OutcomeStatus,
        outcome_as_of: datetime,
        source_authority: str,
        source_checksum: str,
        metrics: dict[str, float | str] | None = None,
        notes: str = "",
        root: Path,
    ) -> ForwardEvidenceOutcome:
        if status == "pending":
            raise ValueError("outcome updates must record a resolved or unavailable state")
        observation_id = _validate_id(observation_id, "observation_id")
        with _LOCK, self._write_lock(Path(root)):
            index = self._read_index(Path(root))
            self._validate_artifacts(Path(root), index)
            row = next((item for item in index if item["observation_id"] == observation_id), None)
            if row is None:
                raise ForwardEvidenceIntegrityError(f"observation is missing: {observation_id}")
            observation = self._stored_observation(Path(root), self._observation_path(Path(root), observation_id), str(row["observation_checksum"]))
            previous = self._stored_outcome(self._outcome_path(Path(root), str(row["outcome_id"])), str(row["outcome_checksum"]))
            if outcome_as_of < observation.manifest.as_of:
                raise ValueError("outcome cannot predate the decision-time manifest")
            version = previous.version + 1
            outcome = ForwardEvidenceOutcome(
                outcome_id=f"{observation_id}-outcome-{version}", observation_id=observation_id, version=version,
                recorded_at=datetime.now(timezone.utc), outcome_as_of=outcome_as_of, status=status,
                source_authority=source_authority, source_checksum=source_checksum, metrics=metrics or {}, notes=notes,
            )
            outcome = outcome.model_copy(update={"checksum": _checksum(outcome)})
            if self._outcome_path(Path(root), outcome.outcome_id).exists():
                raise ForwardEvidenceIntegrityError("forward-evidence outcome version already exists")
            updated_row = dict(row)
            updated_row.update({"outcome_id": outcome.outcome_id, "outcome_checksum": outcome.checksum, "version": version})
            index[index.index(row)] = updated_row
            operations = self._operation_bytes(self._read_operations(Path(root)), "outcome_updated", observation_id, outcome.outcome_id, str(outcome.checksum))
            requests = (
                AtomicWriteRequest(self._outcome_path(Path(root), outcome.outcome_id), _json_bytes(outcome.model_dump(mode="json")), lambda path: ForwardEvidenceOutcome.model_validate(json.loads(path.read_text(encoding="utf-8")))),
                AtomicWriteRequest(self._index_path(Path(root)), _json_bytes(index), lambda path: self._validate_index_value(json.loads(path.read_text(encoding="utf-8")))),
                AtomicWriteRequest(self._operations_path(Path(root)), operations, lambda path: self._validate_operations_bytes(path.read_bytes())),
            )
            atomic_write_group(requests)
            return outcome

    def list_entries(self, *, root: Path) -> tuple[ForwardEvidenceSnapshot, ...]:
        root = Path(root)
        index = self._read_index(root)
        self._validate_artifacts(root, index)
        snapshots = []
        for row in index:
            observation = self._stored_observation(root, self._observation_path(root, str(row["observation_id"])), str(row["observation_checksum"]))
            outcome = self._stored_outcome(self._outcome_path(root, str(row["outcome_id"])), str(row["outcome_checksum"]))
            if outcome.observation_id != observation.observation_id or outcome.version != row["version"]:
                raise ForwardEvidenceIntegrityError(f"forward-evidence index linkage mismatch: {observation.observation_id}")
            snapshots.append(ForwardEvidenceSnapshot(observation=observation, outcome=outcome))
        return tuple(snapshots)

    def get(self, observation_id: str, *, root: Path) -> ForwardEvidenceSnapshot:
        observation_id = _validate_id(observation_id, "observation_id")
        for snapshot in self.list_entries(root=root):
            if snapshot.observation.observation_id == observation_id:
                return snapshot
        raise ForwardEvidenceIntegrityError(f"observation is missing: {observation_id}")

    def export_summary(self, *, root: Path) -> dict[str, object]:
        rows = self.list_entries(root=root)
        return {
            "schema_version": _SCHEMA_VERSION,
            "row_count": len(rows),
            "observations": [
                {
                    "observation_id": item.observation.observation_id,
                    "as_of": item.observation.manifest.as_of.isoformat(),
                    "proposal_outcome": item.observation.proposal_outcome,
                    "outcome_status": item.outcome.status,
                    "manifest_checksum": item.observation.checksum,
                    "outcome_checksum": item.outcome.checksum,
                    "execution_allowed": False,
                }
                for item in rows
            ],
        }


__all__ = [
    "ForwardEvidenceDiary",
    "ForwardEvidenceIntegrityError",
    "ForwardEvidenceObservation",
    "ForwardEvidenceOutcome",
    "ForwardEvidenceSnapshot",
    "ForwardInputManifest",
]
