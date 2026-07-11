from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from pydantic import ValidationError

from etf_cockpit.core import atomic_io
from etf_cockpit.core.paths import ROOT
from etf_cockpit.core.session_log import SESSION_LOG_PATH, append_event
from etf_cockpit.operations.models import WriteTransaction


@dataclass(frozen=True)
class RecoveryResult:
    transaction_id: str
    state: str
    startup_mode: str
    reason: str
    journal_path: Path
    evidence_checksums: dict[str, str]


def _transaction_root(data_root: Path, transaction_id: str) -> Path:
    return data_root / ".atomic-transactions" / transaction_id


def _journal_path(data_root: Path, transaction_id: str) -> Path:
    return _transaction_root(data_root, transaction_id) / "journal.json"


def _resolved_data_root(data_root: Path | None) -> Path:
    return data_root if data_root is not None else ROOT / "data"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _path_list(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(item) for item in value.values()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _record_from_payload(payload: dict[str, object]) -> WriteTransaction:
    journal_state = str(payload.get("state", "recovery_required"))
    return WriteTransaction(
        transaction_id=str(payload["transaction_id"]),
        workflow_run_id=str(payload.get("workflow_run_id", "")),
        transaction_type=str(payload.get("transaction_type", "atomic_write_group")),
        affected_dataset_ids=[str(item) for item in payload.get("affected_dataset_ids", payload.get("affected_datasets", []))],
        base_generation_ids={
            str(key): str(value)
            for key, value in dict(
                payload.get("base_generation_ids", payload.get("base_generations", {}))
            ).items()
        },
        staging_paths=_path_list(
            payload.get("staged_paths", payload.get("staging_paths_by_dataset", []))
        ),
        final_paths=_path_list(payload.get("final_paths", [])),
        expected_checksums={str(key): str(value) for key, value in dict(payload.get("expected_checksums", {})).items()},
        status="committing" if journal_state == "manifest_publish" else journal_state,
        started_at=payload.get("started_at", payload.get("created_at", _now())),
        updated_at=payload.get("updated_at", _now()),
        committed_at=payload.get("committed_at"),
        recovery_instructions=payload.get(
            "recovery_instructions", ["Manual review required."]
        ),
    )


def begin_write_transaction(
    *,
    transaction_type: str,
    base_generations: dict[str, str],
    data_root: Path | None = None,
    workflow_run_id: str = "",
    affected_datasets: list[str] | None = None,
    staging_paths: list[str] | None = None,
    final_paths: list[str] | None = None,
) -> WriteTransaction:
    transaction_id = uuid.uuid4().hex
    now = _now()
    record = WriteTransaction(
        transaction_id=transaction_id,
        workflow_run_id=workflow_run_id,
        transaction_type=transaction_type,
        affected_dataset_ids=list(affected_datasets or base_generations),
        base_generation_ids=base_generations,
        staging_paths=_path_list(staging_paths or []),
        final_paths=_path_list(final_paths or []),
        expected_checksums={},
        status="planned",
        started_at=now,
        updated_at=now,
        recovery_instructions=[
            "Verify all expected checksums before activation; on ambiguity remain read-only "
            "and request manual recovery."
        ],
    )
    path = _journal_path(_resolved_data_root(data_root), transaction_id)
    path.parent.mkdir(parents=True, exist_ok=False)
    payload = record.model_dump(mode="json")
    payload.update(
        schema_version=2,
        state=record.status,
        owner_pid=__import__("os").getpid(),
        entries=[],
        staged_paths=record.staging_paths,
        lock_paths=[],
    )
    atomic_io._write_journal(path, payload)
    return record


def mark_transaction_ready(
    transaction_id: str,
    checksums: dict[str, str],
    *,
    data_root: Path | None = None,
) -> WriteTransaction:
    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValueError("transaction id must stay within supplied recovery root")
    resolved_root = _resolved_data_root(data_root).resolve()
    transactions_root = (resolved_root / ".atomic-transactions").resolve()
    candidate_root = _transaction_root(resolved_root, transaction_id).resolve()
    try:
        candidate_root.relative_to(transactions_root)
    except ValueError as exc:
        raise ValueError("transaction id must stay within supplied recovery root") from exc
    if candidate_root.parent != transactions_root or candidate_root.name != transaction_id:
        raise ValueError("transaction id must stay within supplied recovery root")
    path = candidate_root / "journal.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = "ready_to_commit"
    payload["status"] = "ready_to_commit"
    payload["expected_checksums"] = dict(checksums)
    payload["updated_at"] = _now().isoformat()
    atomic_io._write_journal(path, payload)
    return _record_from_payload(payload)


def _required_result(journal: Path, transaction_id: str, reason: str) -> RecoveryResult:
    checksums: dict[str, str] = {}
    if journal.is_file():
        try:
            checksums["journal_sha256"] = atomic_io.sha256_file(journal)
        except OSError:
            checksums["journal_sha256"] = "unavailable"
    return RecoveryResult(
        transaction_id,
        "recovery_required",
        "read_only",
        reason,
        journal,
        checksums,
    )


_V2_STATES = {
    "planned",
    "staging",
    "validating",
    "ready_to_commit",
    "committing",
    "manifest_publish",
    "committed",
    "rolling_back",
    "rolled_back",
    "recovery_required",
    "quarantined",
}
_V2_REQUIRED_FIELDS = {
    "schema_version",
    "transaction_id",
    "workflow_run_id",
    "transaction_type",
    "owner_pid",
    "state",
    "affected_dataset_ids",
    "base_generation_ids",
    "entries",
    "staged_paths",
    "final_paths",
    "lock_paths",
    "expected_checksums",
    "started_at",
    "updated_at",
    "committed_at",
    "recovery_instructions",
}


def _is_contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validated_path(value: object, root: Path, label: str) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, f"{label} must be a non-empty path string"
    path = Path(value)
    if not path.is_absolute():
        return None, f"{label} must be absolute"
    path = path.resolve()
    if not _is_contained(path, root):
        return None, f"{label} is outside recovery root: {path}"
    return path, None


def _valid_checksum(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_v2_payload(
    payload: dict[str, object],
    journal: Path,
    recovery_root: Path,
) -> str | None:
    missing = sorted(_V2_REQUIRED_FIELDS - payload.keys())
    if missing:
        return f"required journal fields missing: {', '.join(missing)}"
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 2:
        return "schema_version must equal 2"
    if journal.name != "journal.json" or journal.parent.parent.name != ".atomic-transactions":
        return "transaction journal path has invalid identity"
    if not _is_contained(journal, recovery_root):
        return f"journal is outside recovery root: {journal}"
    transaction_id = payload.get("transaction_id")
    if not isinstance(transaction_id, str) or transaction_id != journal.parent.name:
        return "transaction identity does not match transaction directory"
    state = payload.get("state")
    if state not in _V2_STATES:
        return f"state is not approved: {state!r}"
    if not isinstance(payload.get("workflow_run_id"), str):
        return "workflow_run_id must be a string"
    if not isinstance(payload.get("transaction_type"), str) or not payload["transaction_type"]:
        return "transaction_type must be a non-empty string"
    if type(payload.get("owner_pid")) is not int:
        return "owner_pid must be an integer"
    for field in ("affected_dataset_ids", "staged_paths", "final_paths", "lock_paths"):
        value = payload.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return f"{field} must be a list of strings"
    if not isinstance(payload.get("recovery_instructions"), list) or not payload[
        "recovery_instructions"
    ] or not all(
        isinstance(item, str) and item for item in payload["recovery_instructions"]
    ):
        return "recovery_instructions must be a list of non-empty strings"
    for field in ("base_generation_ids", "expected_checksums"):
        value = payload.get(field)
        if not isinstance(value, dict) or not all(
            isinstance(key, str)
            and bool(key)
            and isinstance(item, str)
            and bool(item)
            for key, item in value.items()
        ):
            return f"{field} must be a string map"
    entries_value = payload.get("entries")
    if not isinstance(entries_value, list) or not all(isinstance(item, dict) for item in entries_value):
        return "entries must be a list of objects"
    entries = [dict(item) for item in entries_value]
    staged_paths = list(payload["staged_paths"])
    final_paths = list(payload["final_paths"])
    checksums = dict(payload["expected_checksums"])
    if entries and not (
        len(entries) == len(staged_paths) == len(final_paths) == len(checksums)
    ):
        return "entry/top-level path and checksum cardinality mismatch"
    if not entries and (staged_paths or checksums):
        return "entry/top-level path and checksum cardinality mismatch"
    if len(set(staged_paths)) != len(staged_paths) or len(set(final_paths)) != len(final_paths):
        return "staged_paths and final_paths must not contain duplicates"
    if "status" in payload and payload["status"] != state:
        return "status contradicts journal state"
    entry_destinations: list[str] = []
    entry_staged_paths: list[str] = []
    transaction_root = journal.parent.resolve()
    for index, value in enumerate(staged_paths):
        _, error = _validated_path(value, recovery_root, f"staged_paths[{index}]")
        if error:
            return error
    for index, value in enumerate(final_paths):
        _, error = _validated_path(value, recovery_root, f"final_paths[{index}]")
        if error:
            return error
    for index, entry in enumerate(entries):
        required_entry_fields = {
            "destination", "backup_path", "previous_sha256", "staged_path", "expected_sha256"
        }
        missing_entry = sorted(required_entry_fields - entry.keys())
        if missing_entry:
            return f"required entry fields missing at index {index}: {', '.join(missing_entry)}"
        destination, error = _validated_path(
            entry.get("destination"), recovery_root, f"entries[{index}].destination"
        )
        if error:
            return error
        staged, error = _validated_path(
            entry.get("staged_path"), recovery_root, f"entries[{index}].staged_path"
        )
        if error:
            return error
        assert destination is not None and staged is not None
        if staged.parent != destination.parent:
            return f"entries[{index}].staged_path must share the destination parent"
        expected_checksum = entry.get("expected_sha256")
        if not _valid_checksum(expected_checksum):
            return f"entries[{index}].expected_sha256 is invalid"
        backup_value = entry.get("backup_path")
        previous_checksum = entry.get("previous_sha256")
        backup: Path | None = None
        if backup_value is not None:
            backup, error = _validated_path(
                backup_value, recovery_root, f"entries[{index}].backup_path"
            )
            if error:
                return error
            assert backup is not None
            if not _is_contained(backup, transaction_root):
                return f"entries[{index}].backup_path is outside transaction directory"
            if not _valid_checksum(previous_checksum):
                return f"entries[{index}].previous_sha256 is invalid"
        elif previous_checksum is not None:
            return f"entries[{index}] has previous checksum without rollback backup"
        entry_destinations.append(str(destination))
        entry_staged_paths.append(str(staged))
        if backup is not None:
            if not backup.is_file():
                return f"missing rollback backup: {backup}"
            if atomic_io.sha256_file(backup) != previous_checksum:
                return f"rollback backup checksum mismatch: {backup}"
        if staged.is_file():
            if atomic_io.sha256_file(staged) != expected_checksum:
                return f"staged payload checksum mismatch: {staged}"
        elif state in {"staging", "validating", "ready_to_commit"}:
            return f"missing staged payload: {staged}"
        if state == "committed":
            if not destination.is_file():
                return f"missing committed payload: {destination}"
            if atomic_io.sha256_file(destination) != expected_checksum:
                return f"committed payload checksum mismatch: {destination}"
    if entries and final_paths != entry_destinations:
        return "final_paths contradict journal entries"
    if entries and staged_paths != entry_staged_paths:
        return "staged_paths contradict journal entries"
    if entries and checksums != {
        destination: entry["expected_sha256"]
        for destination, entry in zip(entry_destinations, entries, strict=True)
    }:
        return "expected_checksums contradict journal entries"
    for index, value in enumerate(payload["lock_paths"]):
        lock, error = _validated_path(value, recovery_root, f"lock_paths[{index}]")
        if error:
            return error
        if lock is None or lock.name != ".atomic-write-group.lock":
            return f"lock_paths[{index}] is not a canonical group lock"
        if lock.is_file():
            try:
                lock_payload = json.loads(lock.read_text(encoding="utf-8"))
                lock_journal = Path(str(lock_payload["journal_path"])).resolve()
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                return f"lock_paths[{index}] has corrupt ownership evidence"
            if lock_journal != journal.resolve():
                return f"lock_paths[{index}] belongs to another transaction"
    committed_at = payload.get("committed_at")
    if state == "committed" and not isinstance(committed_at, str):
        return "committed journal requires committed_at"
    if state != "committed" and committed_at is not None:
        return "non-committed journal cannot have committed_at"
    for field in ("started_at", "updated_at"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            return f"{field} must be a non-empty timestamp string"
    return None


def _validate_legacy_paths(
    payload: dict[str, object], journal: Path, recovery_root: Path
) -> str | None:
    if not _is_contained(journal, recovery_root):
        return f"journal is outside recovery root: {journal}"
    for index, entry_value in enumerate(payload.get("entries", [])):
        if not isinstance(entry_value, dict):
            return f"legacy entry {index} is not an object"
        for field in ("destination", "backup_path", "staged_path"):
            value = entry_value.get(field)
            if value is None:
                continue
            _, error = _validated_path(value, recovery_root, f"entries[{index}].{field}")
            if error:
                return error
    for field in ("staged_paths", "lock_paths"):
        values = payload.get(field, [])
        if not isinstance(values, list):
            return f"legacy {field} must be a list"
        for index, value in enumerate(values):
            _, error = _validated_path(value, recovery_root, f"{field}[{index}]")
            if error:
                return error
    return None


def _emit_recovery_event(result: RecoveryResult, event_path: Path | None) -> None:
    if event_path is None:
        return
    try:
        sequence = 1
        if event_path.is_file():
            sequence += len(event_path.read_text(encoding="utf-8", errors="replace").splitlines())
        append_event(
            {
                "session_id": "startup-recovery",
                "sequence_number": sequence,
                "timestamp_utc": _now().isoformat(),
                "event_type": "write_transaction_recovery",
                "status": result.state,
                "component": "operations.recovery",
                "action_id": result.transaction_id,
                "transaction_id": result.transaction_id,
                "startup_mode": result.startup_mode,
                "reason": result.reason,
                "evidence_checksums": result.evidence_checksums,
            },
            path=event_path,
        )
    except Exception:
        # Recovery state is authoritative even when its optional trace is unavailable.
        return


def recover_incomplete_transactions(
    data_root: Path,
    *,
    event_path: Path | None = None,
) -> list[RecoveryResult]:
    data_root = data_root.resolve()
    resolved_event_path = SESSION_LOG_PATH if event_path is None else event_path
    roots: set[Path] = set()
    direct_root = data_root / ".atomic-transactions"
    if direct_root.is_dir():
        roots.add(direct_root)
    canonical_bases = [
        child for child in (data_root / "data", data_root / "configs") if child.is_dir()
    ]
    if data_root.name in {"data", "configs"} or not canonical_bases:
        canonical_bases.append(data_root)
    for base in canonical_bases:
        for path in base.rglob(".atomic-transactions"):
            relative_parts = path.relative_to(data_root).parts
            if (
                path.is_dir()
                and "logs" not in relative_parts
                and not any(part.startswith("pytest_") for part in relative_parts)
            ):
                roots.add(path)
    if not roots:
        return []
    results: list[RecoveryResult] = []
    transaction_roots = sorted(
        (item for root in sorted(roots, key=str) for item in root.iterdir() if item.is_dir()), key=str
    )
    for transaction_root in transaction_roots:
        journal = transaction_root / "journal.json"
        try:
            raw = journal.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            result = _required_result(journal, transaction_root.name, f"corrupt journal: {exc}")
            results.append(result)
            _emit_recovery_event(result, resolved_event_path)
            continue
        if not isinstance(payload, dict):
            result = _required_result(
                journal, transaction_root.name, "corrupt journal: top-level value must be an object"
            )
            results.append(result)
            _emit_recovery_event(result, resolved_event_path)
            continue
        transaction_id = str(payload.get("transaction_id", transaction_root.name))
        journal_state = str(payload.get("state", ""))
        schema_version = payload.get("schema_version", 1)
        if type(schema_version) is int and schema_version == 2:
            error = _validate_v2_payload(payload, journal, data_root)
            if error:
                result = _required_result(journal, transaction_id, error)
                results.append(result)
                _emit_recovery_event(result, resolved_event_path)
                continue
        elif type(schema_version) is int and schema_version == 1:
            error = _validate_legacy_paths(payload, journal, data_root)
            if error:
                result = _required_result(journal, transaction_id, error)
                results.append(result)
                _emit_recovery_event(result, resolved_event_path)
                continue
        else:
            result = _required_result(
                journal,
                transaction_id,
                f"unsupported or invalid journal schema_version: {schema_version!r}",
            )
            results.append(result)
            _emit_recovery_event(result, resolved_event_path)
            continue
        if journal_state in {"recovery_required", "quarantined"}:
            result = _required_result(
                journal,
                transaction_id,
                f"journal state {journal_state!r} requires manual review",
            )
            results.append(result)
            _emit_recovery_event(result, resolved_event_path)
            continue
        try:
            recovered = atomic_io._recover_journal(journal, force=True)
        except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
            result = _required_result(journal, transaction_id, f"rollback failed: {exc}")
            results.append(result)
            _emit_recovery_event(result, resolved_event_path)
            continue
        if not recovered:
            result = _required_result(journal, transaction_id, "journal could not be recovered")
            results.append(result)
            _emit_recovery_event(result, resolved_event_path)
            continue
        result_state = "committed" if journal_state == "committed" else "rolled_back"
        reason = (
            "verified committed generation retained"
            if result_state == "committed"
            else "previous complete generation restored"
        )
        result = RecoveryResult(
            transaction_id,
            result_state,
            "normal",
            reason,
            journal,
            {"journal_sha256": hashlib.sha256(raw).hexdigest()},
        )
        results.append(result)
        _emit_recovery_event(result, resolved_event_path)
    return results
