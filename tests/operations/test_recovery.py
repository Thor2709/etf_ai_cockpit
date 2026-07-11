from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etf_cockpit.core import atomic_io
from etf_cockpit.core.migrations import MigrationContext, run_migrations


def _request(path: Path, payload: bytes) -> atomic_io.AtomicWriteRequest:
    return atomic_io.AtomicWriteRequest(path, payload, lambda staged: staged.read_bytes())


def _recover(data_root: Path):
    try:
        recovery = __import__("etf_cockpit.operations.recovery", fromlist=["recover_incomplete_transactions"])
    except ModuleNotFoundError:
        return []
    return recovery.recover_incomplete_transactions(
        data_root,
        event_path=data_root / "logs" / "session.jsonl",
    )


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
                "affected_dataset_ids": ["canonical"],
                "base_generation_ids": {"canonical": "generation-old"},
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
                "final_paths": [str(destination.resolve())],
                "lock_paths": [],
                "expected_checksums": {
                    str(destination.resolve()): hashlib.sha256(b"new").hexdigest()
                },
                "started_at": "2026-07-11T00:00:00+00:00",
                "updated_at": "2026-07-11T00:00:01+00:00",
                "committed_at": None,
                "recovery_instructions": ["Restore the previous complete generation."],
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


@pytest.mark.parametrize("manual_state", ["recovery_required", "quarantined"])
def test_explicit_manual_review_state_is_preserved_without_payload_mutation(
    tmp_path: Path, manual_state: str
) -> None:
    journal, payload = _valid_v2_payload(tmp_path, transaction_id=f"manual-{manual_state}")
    payload["state"] = manual_state
    journal.write_text(json.dumps(payload), encoding="utf-8")
    destination = Path(payload["entries"][0]["destination"])
    before_destination = destination.read_bytes()
    before_journal = journal.read_bytes()

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert "manual" in outcome[0].reason.lower()
    assert destination.read_bytes() == before_destination
    assert journal.read_bytes() == before_journal
    assert journal.parent.exists()


def test_unreadable_journal_evidence_returns_explicit_unavailable_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction_root = tmp_path / ".atomic-transactions" / "unreadable"
    transaction_root.mkdir(parents=True)
    journal = transaction_root / "journal.json"
    journal.write_text("not-json", encoding="utf-8")
    real_sha256_file = atomic_io.sha256_file

    def unreadable(path: Path) -> str:
        if path == journal:
            raise PermissionError("journal locked")
        return real_sha256_file(path)

    monkeypatch.setattr(atomic_io, "sha256_file", unreadable)

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert outcome[0].evidence_checksums.get("journal_sha256") == "unavailable"
    assert journal.exists()


def test_unreadable_v2_payload_hash_returns_read_only_unavailable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal, payload = _valid_v2_payload(tmp_path, transaction_id="locked-v2")
    entry = payload["entries"][0]
    assert isinstance(entry, dict)
    backup = Path(str(entry["backup_path"]))
    before_journal = journal.read_bytes()
    before_backup = backup.read_bytes()
    real_sha256_file = atomic_io.sha256_file

    def unreadable(path: Path) -> str:
        if path == backup:
            raise PermissionError("locked backup")
        return real_sha256_file(path)

    monkeypatch.setattr(atomic_io, "sha256_file", unreadable)

    try:
        outcome = _recover(tmp_path)
    except BaseException as exc:  # pragma: no cover - regression assertion below
        pytest.fail(f"v2 payload hash failure escaped recovery: {exc!r}")

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert "locked backup" in outcome[0].reason
    assert "unavailable" in outcome[0].evidence_checksums.values()
    assert journal.exists()
    assert journal.read_bytes() == before_journal
    assert backup.read_bytes() == before_backup


def test_unreadable_session_trace_does_not_abort_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _interrupted_transaction(tmp_path, "validating")
    event_path = tmp_path / "logs" / "session.jsonl"
    event_path.parent.mkdir(parents=True)
    event_path.write_text("existing", encoding="utf-8")
    real_read_text = Path.read_text

    def unreadable(path: Path, *args, **kwargs) -> str:
        if path == event_path:
            raise PermissionError("trace locked")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)

    outcome = _recover(tmp_path)

    assert outcome[0].state == "rolled_back"
    assert outcome[0].startup_mode == "normal"


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


def test_legacy_journal_does_not_cleanup_unowned_lock_path(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "legacy.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"new")
    transaction_root = tmp_path / ".atomic-transactions" / "legacy-lock"
    transaction_root.mkdir(parents=True)
    backup = transaction_root / "backup.bin"
    backup.write_bytes(b"old")
    important = destination.parent / "important.bin"
    important.write_bytes(b"keep")
    journal = transaction_root / "journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "legacy-lock",
                "owner_pid": 999999,
                "state": "prepared",
                "entries": [
                    {
                        "destination": str(destination.resolve()),
                        "backup_path": str(backup.resolve()),
                        "previous_sha256": hashlib.sha256(b"old").hexdigest(),
                    }
                ],
                "staged_paths": [],
                "lock_paths": [str(important.resolve())],
            }
        ),
        encoding="utf-8",
    )

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert destination.read_bytes() == b"new"
    assert important.read_bytes() == b"keep"
    assert journal.exists()


def test_legacy_journal_does_not_cleanup_unowned_staged_path(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "legacy-staged.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"new")
    transaction_root = tmp_path / ".atomic-transactions" / "legacy-staged"
    transaction_root.mkdir(parents=True)
    backup = transaction_root / "backup.bin"
    backup.write_bytes(b"old")
    important = destination.parent / "important.bin"
    important.write_bytes(b"new")
    journal = transaction_root / "journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "legacy-staged",
                "owner_pid": 999999,
                "state": "prepared",
                "entries": [
                    {
                        "destination": str(destination.resolve()),
                        "backup_path": str(backup.resolve()),
                        "previous_sha256": hashlib.sha256(b"old").hexdigest(),
                        "staged_path": str(important.resolve()),
                    }
                ],
                "staged_paths": [str(important.resolve())],
                "lock_paths": [],
            }
        ),
        encoding="utf-8",
    )

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert destination.read_bytes() == b"new"
    assert important.read_bytes() == b"new"
    assert journal.exists()


def test_v2_journal_does_not_cleanup_unowned_staged_path(tmp_path: Path) -> None:
    journal, payload = _valid_v2_payload(tmp_path, transaction_id="v2-staged")
    entry = payload["entries"][0]
    assert isinstance(entry, dict)
    destination = Path(str(entry["destination"]))
    important = destination.parent / "important.bin"
    important.write_bytes(b"new")
    entry["staged_path"] = str(important.resolve())
    payload["staged_paths"] = [str(important.resolve())]
    journal.write_text(json.dumps(payload), encoding="utf-8")

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert destination.read_bytes() == b"new"
    assert important.read_bytes() == b"new"
    assert journal.exists()


def test_v2_journal_does_not_cleanup_canonical_lock_outside_writer_group(
    tmp_path: Path,
) -> None:
    journal, payload = _valid_v2_payload(tmp_path, transaction_id="v2-lock")
    unrelated_lock = tmp_path / "other" / ".atomic-write-group.lock"
    unrelated_lock.parent.mkdir(parents=True)
    unrelated_lock.write_text(
        json.dumps(
            {
                "owner_pid": 999999,
                "lock_type": "writer",
                "journal_path": str(journal.resolve()),
            }
        ),
        encoding="utf-8",
    )
    payload["lock_paths"] = [str(unrelated_lock.resolve())]
    journal.write_text(json.dumps(payload), encoding="utf-8")

    outcome = _recover(tmp_path)

    assert outcome[0].state == "recovery_required"
    assert outcome[0].startup_mode == "read_only"
    assert Path(str(payload["entries"][0]["destination"])).read_bytes() == b"new"
    assert unrelated_lock.exists()
    assert journal.exists()


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


def test_recovery_uses_authoritative_session_trace_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _interrupted_transaction(tmp_path, "validating")
    recovery = __import__("etf_cockpit.operations.recovery", fromlist=["SESSION_LOG_PATH"])
    event_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(recovery, "SESSION_LOG_PATH", event_path)

    recovery.recover_incomplete_transactions(tmp_path)

    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event_type"] == "write_transaction_recovery"
    assert event["event_hash"]


def test_migration_recovers_interrupted_atomic_write_before_schema_changes(tmp_path: Path) -> None:
    destination = _interrupted_transaction(tmp_path, "committing")
    context = MigrationContext(tmp_path, tmp_path / "backups")

    report = run_migrations(context)

    assert report.current_version == 4
    assert destination.read_bytes() == b"old"


def test_migration_recovers_real_nested_writer_and_emits_authoritative_event(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "clean" / "canonical.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")

    def interrupt(state: str, _journal: Path) -> None:
        if state == "manifest_publish":
            raise atomic_io.AtomicWriteInterrupted(state)

    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=interrupt)
    journal = next((tmp_path / "data" / "clean").glob(".atomic-transactions/*/journal.json"))

    report = run_migrations(MigrationContext(tmp_path, tmp_path / "backups"))

    assert report.current_version == 4
    assert destination.read_bytes() == b"old"
    assert not journal.exists()
    event_path = tmp_path / "logs" / "session.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    recovery_events = [item for item in events if item["event_type"] == "write_transaction_recovery"]
    assert recovery_events[-1]["status"] == "rolled_back"
    assert recovery_events[-1]["event_hash"]


def _valid_v2_payload(root: Path, transaction_id: str = "valid") -> tuple[Path, dict[str, object]]:
    destination = root / "data" / "current.bin"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"new")
    transaction_root = root / ".atomic-transactions" / transaction_id
    transaction_root.mkdir(parents=True)
    backup = transaction_root / "backup-0.bin"
    backup.write_bytes(b"old")
    staged = destination.parent / ".current.bin.valid.group.tmp"
    staged.write_bytes(b"new")
    expected = hashlib.sha256(b"new").hexdigest()
    payload: dict[str, object] = {
        "schema_version": 2,
        "transaction_id": transaction_id,
        "workflow_run_id": "workflow-1",
        "transaction_type": "canonical_refresh",
        "owner_pid": 999999,
        "state": "committing",
        "affected_dataset_ids": ["canonical"],
        "base_generation_ids": {"canonical": "generation-old"},
        "entries": [{
            "destination": str(destination.resolve()),
            "backup_path": str(backup.resolve()),
            "previous_sha256": hashlib.sha256(b"old").hexdigest(),
            "staged_path": str(staged.resolve()),
            "expected_sha256": expected,
        }],
        "staged_paths": [str(staged.resolve())],
        "final_paths": [str(destination.resolve())],
        "lock_paths": [],
        "expected_checksums": {str(destination.resolve()): expected},
        "started_at": "2026-07-11T00:00:00+00:00",
        "updated_at": "2026-07-11T00:00:01+00:00",
        "committed_at": None,
        "recovery_instructions": ["Restore the previous complete generation."],
    }
    journal = transaction_root / "journal.json"
    journal.write_text(json.dumps(payload), encoding="utf-8")
    return journal, payload


@pytest.mark.parametrize(
    ("damage", "expected_reason"),
    [
        ("unknown_state", "state"),
        ("missing_required", "required"),
        ("contradictory_maps", "cardinality"),
        ("contradictory_checksums", "contradict"),
        ("identity", "transaction"),
    ],
)
def test_structurally_invalid_v2_journal_is_preserved_for_manual_review(
    tmp_path: Path, damage: str, expected_reason: str
) -> None:
    journal, payload = _valid_v2_payload(tmp_path)
    if damage == "unknown_state":
        payload["state"] = "nonsense"
    elif damage == "missing_required":
        payload.pop("recovery_instructions")
    elif damage == "contradictory_maps":
        payload["final_paths"] = []
    elif damage == "contradictory_checksums":
        checksums = payload["expected_checksums"]
        assert isinstance(checksums, dict)
        destination = str(payload["final_paths"][0])
        checksums[destination] = "f" * 64
    else:
        payload["transaction_id"] = "forged-id"
    journal.write_text(json.dumps(payload), encoding="utf-8")

    result = _recover(tmp_path)[0]

    assert result.state == "recovery_required"
    assert result.startup_mode == "read_only"
    assert expected_reason in result.reason.lower()
    assert journal.exists()


@pytest.mark.parametrize("payload", [["not", "an", "object"], {"schema_version": "two"}])
def test_malformed_top_level_journal_is_preserved_without_startup_exception(
    tmp_path: Path, payload: object
) -> None:
    transaction_root = tmp_path / ".atomic-transactions" / "malformed"
    transaction_root.mkdir(parents=True)
    journal = transaction_root / "journal.json"
    journal.write_text(json.dumps(payload), encoding="utf-8")

    result = _recover(tmp_path)[0]

    assert result.state == "recovery_required"
    assert result.startup_mode == "read_only"
    assert journal.exists()


def test_v2_journal_cannot_mutate_a_path_outside_supplied_recovery_root(tmp_path: Path) -> None:
    root = tmp_path / "recovery-root"
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"do-not-touch")
    journal, payload = _valid_v2_payload(root)
    entry = payload["entries"][0]
    assert isinstance(entry, dict)
    original_destination = entry["destination"]
    entry["destination"] = str(outside.resolve())
    payload["final_paths"] = [str(outside.resolve())]
    checksums = payload["expected_checksums"]
    assert isinstance(checksums, dict)
    checksums[str(outside.resolve())] = checksums.pop(original_destination)
    journal.write_text(json.dumps(payload), encoding="utf-8")

    result = _recover(root)[0]

    assert result.state == "recovery_required"
    assert result.startup_mode == "read_only"
    assert "outside recovery root" in result.reason.lower()
    assert outside.read_bytes() == b"do-not-touch"
    assert journal.exists()


def test_lingering_committed_journal_keeps_verified_new_generation(tmp_path: Path) -> None:
    destination = _interrupted_transaction(tmp_path, "manifest_publish")
    root = tmp_path / ".atomic-transactions" / "tx-manifest_publish"
    journal = root / "journal.json"
    payload = json.loads(journal.read_text(encoding="utf-8"))
    payload["state"] = "committed"
    payload["committed_at"] = "2026-07-11T00:00:02+00:00"
    Path(payload["entries"][0]["staged_path"]).unlink()
    journal.write_text(json.dumps(payload), encoding="utf-8")

    outcome = _recover(tmp_path)

    assert outcome[0].state == "committed"
    assert outcome[0].startup_mode == "normal"
    assert destination.read_bytes() == b"new"
    assert not root.exists()
