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
from etf_cockpit.core.session_log import append_event
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


def _record_from_payload(payload: dict[str, object]) -> WriteTransaction:
    return WriteTransaction(
        transaction_id=str(payload["transaction_id"]),
        workflow_run_id=str(payload.get("workflow_run_id", "")),
        transaction_type=str(payload.get("transaction_type", "atomic_write_group")),
        affected_dataset_ids=[str(item) for item in payload.get("affected_dataset_ids", payload.get("affected_datasets", []))],
        base_generations={str(key): str(value) for key, value in dict(payload.get("base_generations", {})).items()},
        staging_paths={str(key): str(value) for key, value in dict(payload.get("staging_paths_by_dataset", {})).items()},
        final_paths={str(key): str(value) for key, value in dict(payload.get("final_paths", {})).items()},
        expected_checksums={str(key): str(value) for key, value in dict(payload.get("expected_checksums", {})).items()},
        status=str(payload.get("state", "recovery_required")),
        started_at=payload.get("started_at", payload.get("created_at", _now())),
        updated_at=payload.get("updated_at", _now()),
        committed_at=payload.get("committed_at"),
        recovery_instructions=str(payload.get("recovery_instructions", "Manual review required.")),
    )


def begin_write_transaction(
    *,
    transaction_type: str,
    base_generations: dict[str, str],
    data_root: Path | None = None,
    workflow_run_id: str = "",
    affected_datasets: list[str] | None = None,
    staging_paths: dict[str, str] | None = None,
    final_paths: dict[str, str] | None = None,
) -> WriteTransaction:
    transaction_id = uuid.uuid4().hex
    now = _now()
    record = WriteTransaction(
        transaction_id=transaction_id,
        workflow_run_id=workflow_run_id,
        transaction_type=transaction_type,
        affected_dataset_ids=list(affected_datasets or base_generations),
        base_generations=base_generations,
        staging_paths=staging_paths or {},
        final_paths=final_paths or {},
        expected_checksums={},
        status="started",
        started_at=now,
        updated_at=now,
        recovery_instructions=(
            "Verify all expected checksums before activation; on ambiguity remain read-only "
            "and request manual recovery."
        ),
    )
    path = _journal_path(_resolved_data_root(data_root), transaction_id)
    path.parent.mkdir(parents=True, exist_ok=False)
    payload = record.model_dump(mode="json")
    payload.update(
        schema_version=2,
        state=record.status,
        owner_pid=__import__("os").getpid(),
        entries=[],
        staged_paths=list(record.staging_paths.values()),
        staging_paths_by_dataset=record.staging_paths,
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
    path = _journal_path(_resolved_data_root(data_root), transaction_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = "ready_to_commit"
    payload["status"] = "ready_to_commit"
    payload["expected_checksums"] = dict(checksums)
    payload["updated_at"] = _now().isoformat()
    atomic_io._write_journal(path, payload)
    return _record_from_payload(payload)


def _required_result(journal: Path, transaction_id: str, reason: str) -> RecoveryResult:
    return RecoveryResult(transaction_id, "recovery_required", "read_only", reason, journal, {})


def _validate_v2_payload(payload: dict[str, object]) -> str | None:
    state = str(payload.get("state", ""))
    for entry_value in payload.get("entries", []):
        entry = dict(entry_value)
        backup_value = entry.get("backup_path")
        previous_checksum = entry.get("previous_sha256")
        if backup_value:
            backup = Path(str(backup_value))
            if not backup.is_file():
                return f"missing rollback backup: {backup}"
            if previous_checksum and atomic_io.sha256_file(backup) != str(previous_checksum):
                return f"rollback backup checksum mismatch: {backup}"
        staged_value = entry.get("staged_path")
        expected_checksum = entry.get("expected_sha256")
        if staged_value and Path(str(staged_value)).is_file():
            if expected_checksum and atomic_io.sha256_file(Path(str(staged_value))) != str(expected_checksum):
                return f"staged payload checksum mismatch: {staged_value}"
        elif state in {"staging", "validating", "ready", "ready_to_commit"} and staged_value:
            return f"missing staged payload: {staged_value}"
        if state == "committed":
            destination = Path(str(entry.get("destination", "")))
            if not destination.is_file():
                return f"missing committed payload: {destination}"
            if expected_checksum and atomic_io.sha256_file(destination) != str(expected_checksum):
                return f"committed payload checksum mismatch: {destination}"
    return None


def _emit_recovery_event(result: RecoveryResult, event_path: Path | None) -> None:
    if event_path is None:
        return
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


def recover_incomplete_transactions(
    data_root: Path,
    *,
    event_path: Path | None = None,
) -> list[RecoveryResult]:
    direct_root = data_root / ".atomic-transactions"
    roots = [direct_root] if direct_root.is_dir() else []
    if data_root.is_dir():
        roots.extend(
            sorted(
                (
                    item / ".atomic-transactions"
                    for item in data_root.iterdir()
                    if item.is_dir() and (item / ".atomic-transactions").is_dir()
                ),
                key=str,
            )
        )
    if not roots:
        return []
    results: list[RecoveryResult] = []
    transaction_roots = sorted(
        (item for root in roots for item in root.iterdir() if item.is_dir()), key=str
    )
    for transaction_root in transaction_roots:
        journal = transaction_root / "journal.json"
        try:
            raw = journal.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            result = _required_result(journal, transaction_root.name, f"corrupt journal: {exc}")
            results.append(result)
            _emit_recovery_event(result, event_path)
            continue
        transaction_id = str(payload.get("transaction_id", transaction_root.name))
        journal_state = str(payload.get("state", ""))
        if int(payload.get("schema_version", 1)) >= 2:
            error = _validate_v2_payload(payload)
            if error:
                result = _required_result(journal, transaction_id, error)
                results.append(result)
                _emit_recovery_event(result, event_path)
                continue
        try:
            recovered = atomic_io._recover_journal(journal, force=True)
        except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
            result = _required_result(journal, transaction_id, f"rollback failed: {exc}")
            results.append(result)
            _emit_recovery_event(result, event_path)
            continue
        if not recovered:
            result = _required_result(journal, transaction_id, "journal could not be recovered")
            results.append(result)
            _emit_recovery_event(result, event_path)
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
        _emit_recovery_event(result, event_path)
    return results
