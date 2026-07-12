"""Append-only, user-owned decision journal with checksum evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from etf_cockpit.core.atomic_io import (
    AtomicWriteRequest,
    atomic_write_group,
    atomic_write_json,
    read_atomic_group,
)
from etf_cockpit.governance.product_scope import load_gate_policy


class JournalIntegrityError(ValueError):
    """Raised when persisted journal evidence cannot be trusted."""


class JournalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal_entry_id: str
    created_at: str
    thesis: str
    decision: str
    outcome: str
    private_notes: str | None = None
    supersedes_entry_id: str | None = None
    schema_version: str = "1.0"
    checksum: str | None = None


_ENTRY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CHECKSUM_RE = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_OPERATIONS = {"created", "superseded"}
_SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
_UNAVAILABLE = "unavailable"


def _canonical_values(entry: JournalEntry) -> dict[str, object]:
    values = entry.model_dump(mode="json")
    values.pop("checksum", None)
    return values


def _checksum(entry: JournalEntry) -> str:
    encoded = json.dumps(_canonical_values(entry), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _validate_entry_id(entry_id: str) -> str:
    normalised = entry_id.strip()
    if not _ENTRY_ID_RE.fullmatch(normalised):
        raise ValueError("journal entry id must be a safe path component")
    return normalised


def _policy_metadata() -> tuple[str, str]:
    result = load_gate_policy()
    if result.policy is None or result.diagnostic_mode:
        return _UNAVAILABLE, _UNAVAILABLE
    return str(result.policy.policy_version or _UNAVAILABLE), str(result.checksum or _UNAVAILABLE)


class DecisionJournal:
    """Persist journal entries as immutable payloads plus a checksum index."""

    _write_lock = threading.RLock()

    def _directory(self, root: Path) -> Path:
        return root / "decision_journal"

    def _index_path(self, root: Path) -> Path:
        return self._directory(root) / "index.json"

    def _entry_path(self, root: Path, entry_id: str) -> Path:
        safe_id = _validate_entry_id(entry_id)
        filename = safe_id if len(safe_id) <= 80 else hashlib.sha256(safe_id.encode("utf-8")).hexdigest()
        return self._directory(root) / "entries" / f"{filename}.json"

    def _decode_index(self, raw: bytes) -> list[dict[str, str]]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JournalIntegrityError("journal index is unreadable") from exc
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise JournalIntegrityError("journal index is malformed")
        decoded: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in value:
            required = {"journal_entry_id", "created_at", "checksum"}
            if set(row) != required or any(not isinstance(row[key], str) or not row[key] for key in required):
                raise JournalIntegrityError("journal index row is malformed")
            try:
                entry_id = _validate_entry_id(row["journal_entry_id"])
            except ValueError as exc:
                raise JournalIntegrityError("journal index row id is malformed") from exc
            if entry_id in seen:
                raise JournalIntegrityError(f"duplicate journal index row: {entry_id}")
            seen.add(entry_id)
            if len(row["checksum"]) != 64:
                raise JournalIntegrityError(f"journal index row checksum is malformed: {entry_id}")
            decoded.append({key: row[key] for key in required})
        return decoded

    def _read_index(self, root: Path) -> list[dict[str, str]]:
        path = self._index_path(root)
        if not path.is_file():
            entries_dir = self._directory(root) / "entries"
            if entries_dir.is_dir() and any(entries_dir.glob("*.json")):
                raise JournalIntegrityError("journal index is missing")
            return []
        try:
            raw = read_atomic_group((path,))[0]
        except OSError as exc:
            raise JournalIntegrityError(f"journal index is unreadable: {path}") from exc
        return self._decode_index(raw)

    def _read_operations(self, root: Path) -> bytes:
        path = self._directory(root) / "operations.jsonl"
        if not path.is_file():
            return b""
        try:
            return read_atomic_group((path,))[0]
        except OSError as exc:
            raise JournalIntegrityError("journal operation log is unreadable") from exc

    @staticmethod
    def _validate_operations(raw: bytes) -> None:
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise JournalIntegrityError("journal operation log is unreadable") from exc
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JournalIntegrityError("journal operation log is malformed") from exc
            required = {"operation", "journal_entry_id", "checksum", "schema_version"}
            if not isinstance(record, dict) or set(record) != required:
                raise JournalIntegrityError("journal operation record is malformed")
            if any(not isinstance(record[key], str) or not record[key] for key in required):
                raise JournalIntegrityError("journal operation record is malformed")
            if record["operation"] not in _ALLOWED_OPERATIONS:
                raise JournalIntegrityError("journal operation record operation is unsupported")
            if record["schema_version"] not in _SUPPORTED_SCHEMA_VERSIONS:
                raise JournalIntegrityError("journal operation record schema is unsupported")
            if not _CHECKSUM_RE.fullmatch(record["checksum"]):
                raise JournalIntegrityError("journal operation record checksum is malformed")
            try:
                _validate_entry_id(record["journal_entry_id"])
            except ValueError as exc:
                raise JournalIntegrityError("journal operation record id is malformed") from exc

    @staticmethod
    def _operation_record(operation: str, entry: JournalEntry) -> dict[str, object]:
        return {
            "operation": operation,
            "journal_entry_id": entry.journal_entry_id,
            "checksum": entry.checksum,
            "schema_version": entry.schema_version,
        }

    @contextmanager
    def _journal_write_lock(self, root: Path):
        directory = self._directory(root)
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".journal-write.lock"
        deadline = time.monotonic() + 10.0
        owner_token = uuid.uuid4().hex
        owner_payload = f"{os.getpid()}:{owner_token}"
        while True:
            descriptor: int | None = None
            created = False
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                created = True
                os.write(descriptor, owner_payload.encode("ascii"))
                os.fsync(descriptor)
                os.close(descriptor)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"decision journal lock is unavailable; manual review required: {lock_path}"
                    )
                time.sleep(0.025)
            except Exception:
                if descriptor is not None:
                    os.close(descriptor)
                if created:
                    try:
                        if lock_path.read_text(encoding="ascii") == owner_payload:
                            lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise
        try:
            yield
        finally:
            try:
                if lock_path.read_text(encoding="ascii") == owner_payload:
                    lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def create(self, entry: JournalEntry, *, root: Path, operation: str = "created") -> JournalEntry:
        root = Path(root)
        with self._write_lock:
            with self._journal_write_lock(root):
                if operation not in _ALLOWED_OPERATIONS:
                    raise ValueError(f"unsupported journal operation: {operation}")
                if entry.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
                    raise ValueError(f"unsupported journal schema version: {entry.schema_version}")
                if operation == "superseded":
                    if not entry.supersedes_entry_id:
                        raise ValueError("superseded journal entry must name its source")
                    self.get(entry.supersedes_entry_id, root=root)
                elif entry.supersedes_entry_id is not None:
                    raise ValueError("created journal entry cannot name a superseded source")
                entry_id = _validate_entry_id(entry.journal_entry_id)
                index = self._read_index(root)
                destination = self._entry_path(root, entry_id)
                if destination.exists():
                    raise ValueError(f"duplicate journal entry id: {entry_id}")
                existing_row = next((row for row in index if row["journal_entry_id"] == entry_id), None)
                if existing_row is not None:
                    raise JournalIntegrityError(f"journal entry payload is missing: {entry_id}")
                stored = entry.model_copy(update={"journal_entry_id": entry_id, "checksum": None})
                stored = stored.model_copy(update={"checksum": _checksum(stored)})
                index.append({"journal_entry_id": entry_id, "created_at": stored.created_at, "checksum": str(stored.checksum)})
                index.sort(key=lambda row: (row["created_at"], row["journal_entry_id"]))
                operations_path = self._directory(root) / "operations.jsonl"
                operations = self._read_operations(root)
                self._validate_operations(operations)
                operations = self._append_operation(root, operation, stored, existing=operations)
                requests = (
                AtomicWriteRequest(
                    destination,
                    _json_bytes(stored.model_dump(mode="json")),
                    lambda path: JournalEntry.model_validate(json.loads(path.read_text(encoding="utf-8"))),
                ),
                AtomicWriteRequest(
                    self._index_path(root),
                    _json_bytes(index),
                    lambda path: self._decode_index(path.read_bytes()),
                ),
                AtomicWriteRequest(
                    operations_path,
                    operations,
                    lambda path: self._validate_operations(path.read_bytes()),
                ),
                )
                atomic_write_group(requests)
                return stored

    def get(self, journal_entry_id: str, *, root: Path) -> JournalEntry:
        root = Path(root)
        path = self._entry_path(root, journal_entry_id)
        index_path = self._index_path(root)
        if not index_path.is_file():
            if path.is_file():
                raise JournalIntegrityError("journal index is missing")
            raise JournalIntegrityError(f"journal entry is missing: {journal_entry_id}")
        try:
            discovery_index = self._decode_index(read_atomic_group((index_path,))[0])
            row = next((candidate for candidate in discovery_index if candidate["journal_entry_id"] == journal_entry_id), None)
            if row is None:
                if path.is_file():
                    raise JournalIntegrityError(f"journal entry is not indexed: {journal_entry_id}")
                raise JournalIntegrityError(f"journal entry is missing: {journal_entry_id}")
            grouped = read_atomic_group((index_path, path))
            final_index = self._decode_index(grouped[0])
            final_row = next((candidate for candidate in final_index if candidate["journal_entry_id"] == journal_entry_id), None)
            if final_row != row:
                raise JournalIntegrityError("journal generation changed during read")
            raw = grouped[1]
        except FileNotFoundError as exc:
            raise JournalIntegrityError(f"journal entry is missing: {journal_entry_id}") from exc
        except OSError as exc:
            raise JournalIntegrityError(f"journal entry is unreadable: {journal_entry_id}") from exc
        try:
            entry = JournalEntry.model_validate(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise JournalIntegrityError(f"journal entry is malformed: {journal_entry_id}") from exc
        if entry.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise JournalIntegrityError(f"journal entry schema is unsupported: {journal_entry_id}")
        if not entry.checksum or entry.checksum != _checksum(entry):
            raise JournalIntegrityError(f"journal entry checksum mismatch: {journal_entry_id}")
        if entry.journal_entry_id != row["journal_entry_id"]:
            raise JournalIntegrityError(f"journal entry identity mismatch: {journal_entry_id}")
        if row["checksum"] != entry.checksum:
            raise JournalIntegrityError(f"journal index checksum mismatch: {journal_entry_id}")
        return entry

    def list_entries(self, *, root: Path) -> list[JournalEntry]:
        root = Path(root)
        index_path = self._index_path(root)
        if not index_path.is_file():
            return self._read_index(root)
        try:
            discovery_index = self._decode_index(read_atomic_group((index_path,))[0])
            paths = [self._entry_path(root, row["journal_entry_id"]) for row in discovery_index]
            grouped = read_atomic_group((index_path, *paths))
            index = self._decode_index(grouped[0])
            if [row["journal_entry_id"] for row in index] != [row["journal_entry_id"] for row in discovery_index]:
                raise JournalIntegrityError("journal generation changed during read")
            payloads = grouped[1:]
        except FileNotFoundError as exc:
            raise JournalIntegrityError("journal entry payload is missing") from exc
        except OSError as exc:
            raise JournalIntegrityError("journal group is unreadable") from exc
        entries: list[JournalEntry] = []
        for row, raw in zip(index, payloads, strict=True):
            try:
                entry = JournalEntry.model_validate(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise JournalIntegrityError(f"journal entry is malformed: {row['journal_entry_id']}") from exc
            if entry.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
                raise JournalIntegrityError(f"journal entry schema is unsupported: {row['journal_entry_id']}")
            if not entry.checksum or entry.checksum != _checksum(entry):
                raise JournalIntegrityError(f"journal entry checksum mismatch: {entry.journal_entry_id}")
            if entry.journal_entry_id != row["journal_entry_id"]:
                raise JournalIntegrityError(f"journal entry identity mismatch: {row['journal_entry_id']}")
            if row["checksum"] != entry.checksum:
                raise JournalIntegrityError(f"journal index checksum mismatch: {entry.journal_entry_id}")
            entries.append(entry)
        return entries

    def supersede(self, journal_entry_id: str, replacement: JournalEntry, *, root: Path) -> JournalEntry:
        _validate_entry_id(journal_entry_id)
        self.get(journal_entry_id, root=Path(root))
        candidate = replacement.model_copy(
            update={
                "journal_entry_id": journal_entry_id,
                "supersedes_entry_id": journal_entry_id,
                "checksum": None,
            }
        )
        digest = _checksum(candidate)[:16]
        replacement_id = f"supersede-{digest}"
        replacement = candidate.model_copy(update={"journal_entry_id": replacement_id})
        destination = self._entry_path(Path(root), replacement_id)
        if destination.exists():
            existing = self.get(replacement_id, root=Path(root))
            if existing.checksum == _checksum(replacement):
                return existing
            raise ValueError(f"duplicate journal entry id: {replacement_id}")
        return self.create(replacement, root=Path(root), operation="superseded")

    def export_summary(self, *, root: Path) -> dict[str, object]:
        entries = self.list_entries(root=Path(root))
        policy_version, policy_checksum = _policy_metadata()
        summary: dict[str, object] = {
            "schema_version": "1.0",
            "policy_version": policy_version,
            "policy_checksum": policy_checksum,
            "row_count": len(entries),
            "ids": [entry.journal_entry_id for entry in entries],
            "checksums": [entry.checksum for entry in entries],
            "private_notes_exported": False,
        }
        atomic_write_json(self._directory(Path(root)) / "export_summary.json", summary)
        return summary

    def _append_operation(
        self,
        root: Path,
        operation: str,
        entry: JournalEntry,
        *,
        existing: bytes | None = None,
    ) -> bytes:
        """Build an operation-log generation for grouped publication.

        The optional no-argument compatibility path preserves the historical
        append helper; normal creates pass existing bytes and publish the
        returned generation through ``atomic_write_group``.
        """

        prefix = existing if existing is not None else self._read_operations(root)
        result = prefix + (json.dumps(self._operation_record(operation, entry), sort_keys=True) + "\n").encode("utf-8")
        if existing is None:
            path = self._directory(Path(root)) / "operations.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(result)
        return result


__all__ = ["DecisionJournal", "JournalEntry", "JournalIntegrityError"]
