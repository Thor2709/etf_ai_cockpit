"""Durable, reusable records for release verification.

The release ledger deliberately keeps executable identity separate from the
evidence captured while verifying it.  A record can therefore be shared by
several owning issues without allowing a change to a plan, worklog or issue
description to change the executable identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import os
import tempfile
import time
from typing import Callable, Literal, Mapping


VerificationStatus = Literal["pass", "fail", "blocked", "in_progress"]


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            error_access_denied = 5
            error_invalid_parameter = 87
            error_not_found = 1168

            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if not handle:
                error = ctypes.get_last_error()
                if error == error_access_denied:
                    return True
                if error in {error_invalid_parameter, error_not_found}:
                    return False
                return True
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (OSError, ValueError, AttributeError):
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _unlink_lock_with_retry(path: Path, *, timeout_seconds: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> bytes:
    """Encode JSON-compatible values deterministically."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compute_executable_hash(executable: Path | str | os.PathLike[str] | bytes | bytearray) -> str:
    """Return the SHA-256 of executable bytes only.

    The function intentionally accepts bytes for callers that already hold a
    packaged executable in memory.  Paths are read as raw bytes; file names,
    surrounding metadata and repository documentation are not included.
    """

    if isinstance(executable, (bytes, bytearray)):
        return _sha256(bytes(executable))
    path = Path(executable)
    if not path.is_file():
        raise FileNotFoundError(f"executable is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_value(value: object, *, root: Path | None = None) -> object:
    """Convert evidence input into a stable, content-addressed value."""

    if isinstance(value, (bytes, bytearray)):
        return {"kind": "bytes", "sha256": _sha256(bytes(value)), "size": len(value)}
    if isinstance(value, Path):
        path = value
        if path.is_file():
            if root is None:
                relative = path.name
            else:
                try:
                    relative = path.resolve().relative_to(root).as_posix()
                except ValueError:
                    relative = path.resolve().as_posix()
            return {
                "kind": "file",
                "path": relative,
                "sha256": compute_executable_hash(path),
                "size": path.stat().st_size,
            }
        if path.is_dir():
            base = path.resolve()
            files = []
            for candidate in sorted((item for item in base.rglob("*") if item.is_file()), key=lambda p: p.as_posix()):
                files.append(_evidence_value(candidate, root=base))
            return {"kind": "directory", "path": base.name, "files": files}
        return {"kind": "path", "path": path.as_posix()}
    if isinstance(value, Mapping):
        return {str(key): _evidence_value(item, root=root) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [_evidence_value(item, root=root) for item in value]
        if isinstance(value, (set, frozenset)):
            values.sort(key=lambda item: _canonical_json(item))
        return values
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def compute_evidence_hash(evidence: object, *, root: Path | str | None = None) -> str:
    """Return a deterministic, domain-separated hash of captured evidence.

    This hash covers the supplied evidence content and paths, never the
    executable identity.  The domain prefix prevents accidental equality with
    a raw executable SHA-256 even when a caller supplies identical bytes.
    """

    payload = {
        "domain": "etf-ai-cockpit/evidence/v1",
        "evidence": _evidence_value(evidence, root=Path(root).resolve() if root is not None else None),
    }
    return _sha256(_canonical_json(payload))


deterministic_evidence_hash = compute_evidence_hash


@dataclass(frozen=True)
class ReleaseRecordKey:
    """Identity of one reusable verification command."""

    commit: str
    executable_hash: str
    environment_hash: str
    command: str

    def as_dict(self) -> dict[str, str]:
        return {
            "commit": self.commit,
            "executable_hash": self.executable_hash,
            "environment_hash": self.environment_hash,
            "command": self.command,
        }

    def to_dict(self) -> dict[str, str]:
        return self.as_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ReleaseRecordKey":
        return cls(
            commit=str(value.get("commit", "")),
            executable_hash=str(value.get("executable_hash", "")),
            environment_hash=str(value.get("environment_hash", "")),
            command=str(value.get("command", "")),
        )


@dataclass
class VerificationRecord:
    """One durable gate result, shareable by multiple issue records."""

    record_id: str
    key: ReleaseRecordKey
    gate: str
    status: VerificationStatus
    evidence_hash: str
    issue_ids: list[str] = field(default_factory=list)
    review_id: str | None = None
    evidence_state: str = "staged"
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    @property
    def executable_hash(self) -> str:
        return self.key.executable_hash

    @property
    def environment_hash(self) -> str:
        return self.key.environment_hash

    @property
    def commit(self) -> str:
        return self.key.commit

    @property
    def command(self) -> str:
        return self.key.command

    @property
    def issue_references(self) -> list[str]:
        """Compatibility name for consumers that call issue links references."""

        return self.issue_ids

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "key": self.key.as_dict(),
            "gate": self.gate,
            "status": self.status,
            "evidence_hash": self.evidence_hash,
            "issue_ids": list(self.issue_ids),
            "review_id": self.review_id,
            "evidence_state": self.evidence_state,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, object]:
        return self.as_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "VerificationRecord":
        raw_status = str(value.get("status", "blocked"))
        status: VerificationStatus = raw_status if raw_status in {"pass", "fail", "blocked", "in_progress"} else "blocked"  # type: ignore[assignment]
        issue_ids = value.get("issue_ids", value.get("issues", []))
        if not isinstance(issue_ids, list):
            issue_ids = list(issue_ids) if isinstance(issue_ids, (tuple, set)) else []
        metadata = value.get("metadata", {})
        return cls(
            record_id=str(value.get("record_id", "")),
            key=ReleaseRecordKey.from_dict(value.get("key", {}) if isinstance(value.get("key"), Mapping) else value),
            gate=str(value.get("gate", "")),
            status=status,
            evidence_hash=str(value.get("evidence_hash", "")),
            issue_ids=[str(issue) for issue in issue_ids],
            review_id=(str(value["review_id"]) if value.get("review_id") is not None else None),
            evidence_state=str(value.get("evidence_state", "staged")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
            created_at=str(value.get("created_at", _utc_now())),
            updated_at=str(value.get("updated_at", _utc_now())),
        )


def _record_id(key: ReleaseRecordKey, gate: str) -> str:
    digest = _sha256(_canonical_json({"key": key.as_dict(), "gate": gate}))
    return f"vr-{digest[:32]}"


def _runner_result(runner: Callable[[], object] | None) -> Mapping[str, object]:
    if runner is None:
        return run_verification_command()
    result = runner()
    if isinstance(result, Mapping):
        return result
    return {"status": "blocked", "limitation": "verification runner returned a non-mapping result", "result": repr(result)}


def run_verification_command(*_args: object, **_kwargs: object) -> Mapping[str, object]:
    """Default no-authority runner used when no concrete command runner is supplied."""

    return {"status": "blocked", "limitation": "no verification runner supplied"}


class VerificationRecordLedger:
    """JSON-backed ledger for exactly-once, shared verification records."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._records: dict[str, VerificationRecord] = {}
        self._load()

    @contextmanager
    def _exclusive_lock(self):
        """Serialise reload, runner execution and publication across processes."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 30.0
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            except FileExistsError:
                owner = ""
                try:
                    owner = self.lock_path.read_text(encoding="ascii").strip()
                except (OSError, UnicodeError):
                    pass
                pid_text = owner.removeprefix("pid=").strip()
                if pid_text.isdigit() and not _pid_is_alive(int(pid_text)):
                    _unlink_lock_with_retry(self.lock_path)
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"verification ledger lock is held: {self.lock_path}")
                time.sleep(0.02)
        try:
            yield
        finally:
            os.close(descriptor)
            _unlink_lock_with_retry(self.lock_path)

    def _load(self) -> None:
        self._records.clear()
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        rows = raw.get("records", []) if isinstance(raw, Mapping) else raw
        if not isinstance(rows, list):
            raise ValueError("verification record ledger records must be a list")
        for item in rows:
            if isinstance(item, Mapping):
                record = VerificationRecord.from_dict(item)
                if record.record_id:
                    self._records[record.record_id] = record

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "records": [record.as_dict() for record in sorted(self._records.values(), key=lambda item: item.record_id)],
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            try:
                directory_descriptor = os.open(self.path.parent, os.O_RDONLY)
            except OSError:
                directory_descriptor = None
            if directory_descriptor is not None:
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
        finally:
            if temporary.exists():
                temporary.unlink()

    @property
    def records(self) -> tuple[VerificationRecord, ...]:
        return tuple(sorted(self._records.values(), key=lambda item: item.record_id))

    def record(self, record_id: str | VerificationRecord) -> VerificationRecord:
        if isinstance(record_id, VerificationRecord):
            record_id = record_id.record_id
        try:
            return self._records[str(record_id)]
        except KeyError as exc:
            raise KeyError(f"unknown verification record: {record_id}") from exc

    def get(self, record_id: str) -> VerificationRecord | None:
        """Return a record when present, without changing ledger state."""

        return self._records.get(str(record_id))

    def find(self, key: ReleaseRecordKey, gate: str) -> VerificationRecord | None:
        wanted_gate = str(gate)
        return next((record for record in self._records.values() if record.key == key and record.gate == wanted_gate), None)

    def get_or_run(
        self,
        key: ReleaseRecordKey,
        gate: str,
        issue_id: str,
        runner: Callable[[], object] | None = None,
    ) -> VerificationRecord:
        """Return an existing key match or execute and persist exactly once."""

        with self._exclusive_lock():
            self._load()
            existing = self.find(key, gate)
            if existing is not None:
                if issue_id and issue_id not in existing.issue_ids:
                    existing.issue_ids.append(str(issue_id))
                    existing.updated_at = _utc_now()
                    self._persist()
                return existing

            now = _utc_now()
            record = VerificationRecord(
                record_id=_record_id(key, str(gate)),
                key=key,
                gate=str(gate),
                status="in_progress",
                evidence_hash=compute_evidence_hash({"state": "in_progress", "key": key.as_dict()}),
                issue_ids=[str(issue_id)],
                evidence_state="staged",
                metadata={"state": "in_progress"},
                created_at=now,
                updated_at=now,
            )
            self._records[record.record_id] = record
            self._persist()
            try:
                result = dict(_runner_result(runner))
            except Exception as exc:
                record.status = "blocked"
                record.metadata = {"state": "runner_exception", "error": str(exc)}
                record.updated_at = _utc_now()
                self._persist()
                return record
            raw_status = str(result.pop("status", "blocked")).strip().lower()
            status: VerificationStatus = raw_status if raw_status in {"pass", "fail", "blocked"} else "blocked"  # type: ignore[assignment]
            evidence_hash = str(result.pop("evidence_hash", ""))
            if not evidence_hash:
                evidence_hash = compute_evidence_hash(result)
            evidence_state = str(result.pop("evidence_state", "staged"))
            record.status = status
            record.evidence_hash = evidence_hash
            record.evidence_state = evidence_state
            record.metadata = _evidence_value(result)
            record.updated_at = _utc_now()
            self._persist()
            return record

    def attach_issue(self, record_id: str | VerificationRecord, issue_id: str) -> VerificationRecord:
        with self._exclusive_lock():
            self._load()
            record = self.record(record_id)
            issue = str(issue_id)
            if issue and issue not in record.issue_ids:
                record.issue_ids.append(issue)
                record.updated_at = _utc_now()
                self._persist()
            return record

    def attach_review(self, record_id: str | VerificationRecord, review_id: str) -> VerificationRecord:
        with self._exclusive_lock():
            self._load()
            record = self.record(record_id)
            review = str(review_id).strip()
            if not review:
                raise ValueError("review_id must be non-empty")
            if record.review_id not in {None, review}:
                raise ValueError("verification record already references a different review")
            record.review_id = review
            record.updated_at = _utc_now()
            self._persist()
            return record

    def status(self, record_id: str | VerificationRecord) -> VerificationStatus:
        return self.record(record_id).status


def reuse_gate_record(
    ledger: VerificationRecordLedger,
    key: ReleaseRecordKey,
    gate: str,
    issue_id: str,
) -> VerificationRecord | None:
    """Attach an issue to an existing gate record without running anything."""

    record = ledger.find(key, gate)
    if record is None:
        return None
    return ledger.attach_issue(record.record_id, issue_id)


def evidence_state_allows_closure(state: object) -> bool:
    """Only atomically promoted final evidence can satisfy closure."""

    return isinstance(state, str) and state.strip().casefold() == "final"


def validate_shared_record(
    ledger: VerificationRecordLedger,
    record_id: str,
    *,
    key: ReleaseRecordKey,
    gate: str,
    require_final: bool = True,
) -> VerificationRecord:
    """Validate a manifest's shared record against its complete release key."""

    record = ledger.get(record_id)
    if record is None:
        raise ValueError(f"shared verification record is missing: {record_id}")
    if record.key != key:
        raise ValueError(f"shared verification record key mismatch: {record_id}")
    if record.gate != str(gate):
        raise ValueError(f"shared verification record gate mismatch: {record_id}")
    if record.status != "pass":
        raise ValueError(f"shared verification record is not passing: {record_id}")
    if require_final and not evidence_state_allows_closure(record.evidence_state):
        raise ValueError(f"shared verification record evidence is not final: {record_id}")
    return record


@dataclass(frozen=True)
class ResumeCheckpoint:
    status: str
    next_action: str | None
    redispatch_required: bool
    dispatch_id: str | None = None


def load_resume_checkpoint(path: Path | str) -> ResumeCheckpoint:
    """Load the authoritative run-state checkpoint for a resumed controller."""

    checkpoint_path = Path(path)
    try:
        raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return ResumeCheckpoint(status="missing", next_action=None, redispatch_required=True)
    if not isinstance(raw, Mapping):
        return ResumeCheckpoint(status="invalid", next_action=None, redispatch_required=True)
    active = raw.get("active_programme") if isinstance(raw.get("active_programme"), Mapping) else {}
    last_checkpoint = raw.get("last_checkpoint") if isinstance(raw.get("last_checkpoint"), Mapping) else {}
    status_raw = raw.get("status", raw.get("checkpoint_status", active.get("status")))
    if status_raw is None and last_checkpoint:
        status_raw = "committed"
    status = str(status_raw or "unknown").strip().lower()
    next_action_raw = raw.get("next_action", raw.get("next_task"))
    if next_action_raw is None:
        checkpoint_actions = [
            value.get("next_action", value.get("next_task"))
            for name, value in raw.items()
            if isinstance(value, Mapping)
            and (name.endswith("_checkpoint") or name.endswith("_closure"))
            and value.get("next_action", value.get("next_task")) is not None
        ]
        if checkpoint_actions:
            next_action_raw = checkpoint_actions[-1]
    if next_action_raw is None:
        next_action_raw = active.get("next_action", active.get("next_task"))
    if next_action_raw is None:
        next_action_raw = raw.get("next_command")
    next_action = str(next_action_raw) if next_action_raw is not None else None
    redispatch = False if status == "committed" else bool(raw.get("redispatch_required", True))
    dispatch = raw.get("dispatch_id")
    return ResumeCheckpoint(
        status=status,
        next_action=next_action,
        redispatch_required=redispatch,
        dispatch_id=str(dispatch) if dispatch is not None else None,
    )


__all__ = [
    "ReleaseRecordKey",
    "ResumeCheckpoint",
    "VerificationRecord",
    "VerificationRecordLedger",
    "compute_evidence_hash",
    "compute_executable_hash",
    "deterministic_evidence_hash",
    "evidence_state_allows_closure",
    "load_resume_checkpoint",
    "reuse_gate_record",
    "run_verification_command",
    "validate_shared_record",
]
