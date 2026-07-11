from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etf_cockpit.core import atomic_io
from etf_cockpit.core.migrations import MigrationContext, run_migrations


def _recover(data_root: Path):
    try:
        recovery = __import__("etf_cockpit.operations.recovery", fromlist=["recover_incomplete_transactions"])
    except ModuleNotFoundError:
        return []
    return recovery.recover_incomplete_transactions(data_root)


def _interrupted_transaction(tmp_path: Path, state: str, *, corrupt_payload: bool = False) -> Path:
    destination = tmp_path / "data" / "current.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    transaction_root = tmp_path / ".atomic-transactions" / f"tx-{state}"
    transaction_root.mkdir(parents=True)
    backup = transaction_root / "backup-0.bin"
    backup.write_bytes(b"old")
    staged = destination.parent / ".current.bin.interrupted.group.tmp"
    staged.write_bytes(b"corrupt" if corrupt_payload else b"new")
    if state in {"committing", "manifest_publish"}:
        destination.write_bytes(b"new")
    journal = transaction_root / "journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "transaction_id": f"tx-{state}",
                "workflow_run_id": "workflow-1",
                "transaction_type": "canonical_refresh",
                "owner_pid": 999999,
                "state": state,
                "affected_datasets": ["canonical"],
                "base_generations": {"canonical": "generation-old"},
                "entries": [
                    {
                        "destination": str(destination.resolve()),
                        "backup_path": str(backup.resolve()),
                        "previous_sha256": hashlib.sha256(b"old").hexdigest(),
                        "staged_path": str(staged.resolve()),
                        "expected_sha256": hashlib.sha256(b"new").hexdigest(),
                    }
                ],
                "staged_paths": [str(staged.resolve())],
                "lock_paths": [],
                "expected_checksums": {
                    str(destination.resolve()): hashlib.sha256(b"new").hexdigest()
                },
                "recovery_instructions": "Restore the previous complete generation.",
            }
        ),
        encoding="utf-8",
    )
    return destination


@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
def test_recovery_exposes_old_complete_generation_after_every_interruption(
    tmp_path: Path, crash_point: str
) -> None:
    destination = _interrupted_transaction(tmp_path, crash_point)

    outcome = _recover(tmp_path)

    assert outcome[0].state == "rolled_back"
    assert outcome[0].startup_mode == "normal"
    assert destination.read_bytes() == b"old"
    assert _recover(tmp_path) == []


def test_corrupt_journal_requires_read_only_manual_recovery(tmp_path: Path) -> None:
    transaction_root = tmp_path / ".atomic-transactions" / "broken"
    transaction_root.mkdir(parents=True)
    (transaction_root / "journal.json").write_text('{"transaction_id":', encoding="utf-8")

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert "journal" in outcome[0].reason.lower()


@pytest.mark.parametrize("damage", ["checksum", "missing_payload", "missing_backup"])
def test_corrupt_or_incomplete_transaction_is_not_promoted(tmp_path: Path, damage: str) -> None:
    state = "staging" if damage == "missing_payload" else "committing"
    destination = _interrupted_transaction(tmp_path, state, corrupt_payload=damage == "checksum")
    transaction_root = tmp_path / ".atomic-transactions" / f"tx-{state}"
    payload = json.loads((transaction_root / "journal.json").read_text(encoding="utf-8"))
    if damage == "missing_payload":
        Path(payload["entries"][0]["staged_path"]).unlink()
    elif damage == "missing_backup":
        Path(payload["entries"][0]["backup_path"]).unlink()

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert destination.read_bytes() in {b"old", b"new"}
    assert transaction_root.exists()


def test_legacy_v1_prepared_journal_remains_recoverable(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "legacy.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"new")
    root = tmp_path / ".atomic-transactions" / "legacy"
    root.mkdir(parents=True)
    backup = root / "backup.bin"
    backup.write_bytes(b"old")
    (root / "journal.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "legacy",
                "owner_pid": 999999,
                "state": "prepared",
                "entries": [{
                    "destination": str(destination.resolve()),
                    "backup_path": str(backup.resolve()),
                    "previous_sha256": hashlib.sha256(b"old").hexdigest(),
                }],
                "staged_paths": [],
                "lock_paths": [],
            }
        ),
        encoding="utf-8",
    )

    outcome = _recover(tmp_path)

    assert outcome[0].state == "rolled_back"
    assert destination.read_bytes() == b"old"


def test_permission_failure_during_rollback_requires_manual_read_only_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _interrupted_transaction(tmp_path, "committing")

    def denied(*_args, **_kwargs):
        raise PermissionError("locked destination")

    monkeypatch.setattr(atomic_io, "atomic_write_bytes", denied)
    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert "locked destination" in outcome[0].reason


def test_clean_restart_has_no_recovery_results(tmp_path: Path) -> None:
    assert _recover(tmp_path) == []


def test_recovery_outcome_is_visible_in_the_authoritative_operational_trace(tmp_path: Path) -> None:
    _interrupted_transaction(tmp_path, "validating")
    event_path = tmp_path / "logs" / "session.jsonl"
    recovery = __import__("etf_cockpit.operations.recovery", fromlist=["recover_incomplete_transactions"])

    recovery.recover_incomplete_transactions(tmp_path, event_path=event_path)

    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event_type"] == "write_transaction_recovery"
    assert event["status"] == "rolled_back"
    assert event["transaction_id"] == "tx-validating"
    assert event["event_hash"]


def test_migration_recovers_interrupted_atomic_write_before_schema_changes(tmp_path: Path) -> None:
    destination = _interrupted_transaction(tmp_path, "committing")
    context = MigrationContext(tmp_path, tmp_path / "backups")

    report = run_migrations(context)

    assert report.current_version == 4
    assert destination.read_bytes() == b"old"


def test_lingering_committed_journal_keeps_verified_new_generation(tmp_path: Path) -> None:
    destination = _interrupted_transaction(tmp_path, "manifest_publish")
    root = tmp_path / ".atomic-transactions" / "tx-manifest_publish"
    journal = root / "journal.json"
    payload = json.loads(journal.read_text(encoding="utf-8"))
    payload["state"] = "committed"
    Path(payload["entries"][0]["staged_path"]).unlink()
    journal.write_text(json.dumps(payload), encoding="utf-8")

    outcome = _recover(tmp_path)

    assert outcome[0].state == "committed"
    assert outcome[0].startup_mode == "normal"
    assert destination.read_bytes() == b"new"
    assert not root.exists()
