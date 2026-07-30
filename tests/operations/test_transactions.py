from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
from typing import get_args, get_origin

import pytest

from etf_cockpit.core import atomic_io


def _request(path: Path, payload: bytes) -> atomic_io.AtomicWriteRequest:
    return atomic_io.AtomicWriteRequest(path, payload, lambda staged: staged.read_bytes())


def test_grouped_write_journal_exposes_durable_transaction_identity_and_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[dict[str, object]] = []
    real_write = atomic_io._write_journal

    def capture(path: Path, payload: dict[str, object]) -> None:
        observed.append(json.loads(json.dumps(payload)))
        real_write(path, payload)

    monkeypatch.setattr(atomic_io, "_write_journal", capture)
    destination = tmp_path / "data" / "canonical.bin"

    atomic_io.atomic_write_group((_request(destination, b"new"),))

    assert {str(item["state"]) for item in observed} >= {
        "staging",
        "validating",
        "committing",
        "manifest_publish",
        "committed",
    }
    assert len({str(item["transaction_id"]) for item in observed}) == 1
    committed = observed[-1]
    assert committed["expected_checksums"] == {
        str(destination.resolve()): hashlib.sha256(b"new").hexdigest()
    }
    assert committed["recovery_instructions"]


def test_transaction_model_carries_the_approved_recovery_fields() -> None:
    model = getattr(__import__("etf_cockpit.operations.models", fromlist=["WriteTransaction"]), "WriteTransaction", None)
    assert model is not None
    fields = set(model.model_fields)
    assert {
        "transaction_id",
        "workflow_run_id",
        "transaction_type",
        "affected_dataset_ids",
        "base_generation_ids",
        "staging_paths",
        "final_paths",
        "expected_checksums",
        "status",
        "started_at",
        "updated_at",
        "committed_at",
        "recovery_instructions",
    } <= fields
    assert get_origin(model.model_fields["staging_paths"].annotation) is list
    assert get_args(model.model_fields["staging_paths"].annotation) == (str,)
    assert get_origin(model.model_fields["final_paths"].annotation) is list
    assert get_args(model.model_fields["final_paths"].annotation) == (str,)
    assert get_origin(model.model_fields["recovery_instructions"].annotation) is list
    assert get_args(model.model_fields["recovery_instructions"].annotation) == (str,)
    assert "planned" in get_args(model.model_fields["status"].annotation)
    assert "manifest_publish" not in get_args(model.model_fields["status"].annotation)


def test_begin_and_ready_lifecycle_is_durable_in_the_atomic_journal(tmp_path: Path) -> None:
    try:
        recovery = __import__("etf_cockpit.operations.recovery", fromlist=["begin_write_transaction"])
    except ModuleNotFoundError:
        pytest.fail("transaction lifecycle API is absent")

    transaction = recovery.begin_write_transaction(
        data_root=tmp_path,
        transaction_type="canonical_refresh",
        workflow_run_id="workflow-1",
        affected_datasets=["canonical"],
        base_generations={"canonical": "generation-old"},
        final_paths=[str(tmp_path / "data" / "canonical.bin")],
    )
    ready = recovery.mark_transaction_ready(
        transaction.transaction_id,
        {"canonical": hashlib.sha256(b"new").hexdigest()},
        data_root=tmp_path,
    )
    journal = tmp_path / ".atomic-transactions" / transaction.transaction_id / "journal.json"
    durable = json.loads(journal.read_text(encoding="utf-8"))

    assert ready.status == "ready_to_commit"
    assert durable["transaction_id"] == transaction.transaction_id
    assert durable["state"] == "ready_to_commit"
    assert durable["expected_checksums"] == ready.expected_checksums
    assert transaction.base_generation_ids == {"canonical": "generation-old"}
    assert transaction.base_generations == transaction.base_generation_ids
    assert transaction.status == "planned"
    assert isinstance(durable["final_paths"], list)
    assert isinstance(durable["recovery_instructions"], list)


def test_mark_transaction_ready_rejects_transaction_id_outside_supplied_root(tmp_path: Path) -> None:
    from etf_cockpit.operations.recovery import mark_transaction_ready

    outside_root = tmp_path.parent / f"outside-{tmp_path.name}"
    outside_root.mkdir()
    outside_journal = outside_root / ".atomic-transactions" / "outside" / "journal.json"
    outside_journal.parent.mkdir(parents=True)
    outside_journal.write_text("must-not-be-read-or-written", encoding="utf-8")

    with pytest.raises(ValueError, match="transaction id.*root"):
        mark_transaction_ready(
            str(outside_journal.parent.parent.resolve()),
            {"outside": "a" * 64},
            data_root=tmp_path,
        )

    assert outside_journal.read_text(encoding="utf-8") == "must-not-be-read-or-written"


@pytest.mark.serial
@pytest.mark.xdist_group("concurrency")
def test_group_reader_cannot_observe_mixed_generation_during_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "data" / "first.bin"
    second = tmp_path / "configs" / "second.bin"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"old-a")
    second.write_bytes(b"old-b")
    first_replaced = threading.Event()
    release_first = threading.Event()
    writer_errors: list[BaseException] = []
    reader_errors: list[BaseException] = []
    reader_done = threading.Event()
    observed: list[bytes] = []
    real_replace = Path.replace

    def pause_first(self: Path, destination: Path):
        result = real_replace(self, destination)
        if Path(destination) == first:
            first_replaced.set()
            assert release_first.wait(timeout=5)
        return result

    monkeypatch.setattr(Path, "replace", pause_first)

    def write_group() -> None:
        try:
            atomic_io.atomic_write_group(
                (_request(first, b"new-a"), _request(second, b"new-b")),
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)

    def read_group() -> None:
        try:
            reader = getattr(atomic_io, "read_atomic_group", None)
            assert callable(reader), "group reader protocol is missing"
            observed.extend(reader((first, second), timeout_seconds=5))
        except BaseException as exc:  # pragma: no cover - asserted below
            reader_errors.append(exc)
        finally:
            reader_done.set()

    writer = threading.Thread(target=write_group)
    writer.start()
    assert first_replaced.wait(timeout=5)
    reader = threading.Thread(target=read_group)
    reader.start()
    assert not reader_done.wait(timeout=0.1)
    release_first.set()
    writer.join(timeout=5)
    reader.join(timeout=5)

    assert not writer.is_alive() and not reader.is_alive()
    assert writer_errors == []
    assert reader_errors == []
    assert observed == [b"new-a", b"new-b"]


@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
def test_real_group_interruption_leaves_one_existing_journal_for_startup_recovery(
    tmp_path: Path, crash_point: str
) -> None:
    destination = tmp_path / "data" / "canonical.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")

    def interrupt(state: str, _journal: Path) -> None:
        if state == crash_point:
            raise atomic_io.AtomicWriteInterrupted(state)

    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=interrupt)

    journals = list(tmp_path.rglob(".atomic-transactions/*/journal.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["state"] == crash_point


@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
def test_real_group_interruption_recovers_the_previous_complete_generation(
    tmp_path: Path, crash_point: str
) -> None:
    from etf_cockpit.operations.recovery import recover_incomplete_transactions

    destination = tmp_path / "data" / "canonical.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")

    def interrupt(state: str, _journal: Path) -> None:
        if state == crash_point:
            raise atomic_io.AtomicWriteInterrupted(state)

    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=interrupt)

    result = recover_incomplete_transactions(
        tmp_path,
        event_path=tmp_path / "logs" / "session.jsonl",
    )[0]

    assert result.state == "rolled_back"
    assert result.startup_mode == "normal"
    assert destination.read_bytes() == b"old"


def test_concurrent_writer_times_out_without_changing_previous_value(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "canonical.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    lock = destination.parent / ".atomic-write-group.lock"
    lock.write_text(
        json.dumps({"owner_pid": __import__("os").getpid(), "journal_path": "active"}),
        encoding="utf-8",
    )

    with pytest.raises(TimeoutError):
        atomic_io.wait_for_atomic_group(destination, timeout_seconds=0.01)

    assert destination.read_bytes() == b"old"


def test_group_lock_retries_one_shot_windows_open_sharing_violation(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "data"
    parent.mkdir(parents=True)
    lock = parent / ".atomic-write-group.lock"
    real_open = atomic_io.os.open
    calls = 0

    def flaky_open(path, flags, mode=0o777):
        nonlocal calls
        calls += 1
        if calls == 1:
            lock.write_text("{}", encoding="utf-8")
            raise PermissionError("sharing violation")
        lock.unlink(missing_ok=True)
        return real_open(path, flags, mode)

    monkeypatch.setattr(atomic_io.os, "open", flaky_open)
    locks = atomic_io._acquire_group_locks((parent,), None, timeout_seconds=1)
    assert calls == 2
    for lock in locks:
        lock.unlink(missing_ok=True)


def test_group_lock_persistent_open_sharing_violation_times_out(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "data"
    parent.mkdir(parents=True)
    (parent / ".atomic-write-group.lock").write_text("{}", encoding="utf-8")
    ticks = iter((10.0, 16.0))
    monkeypatch.setattr(atomic_io.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        atomic_io.os,
        "open",
        lambda *_args: (_ for _ in ()).throw(PermissionError("sharing violation")),
    )
    with pytest.raises(TimeoutError):
        atomic_io._acquire_group_locks((parent,), None, timeout_seconds=5)


def test_group_lock_absent_open_permission_error_propagates(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "data"
    monkeypatch.setattr(
        atomic_io.os,
        "open",
        lambda *_args: (_ for _ in ()).throw(PermissionError("ACL denied")),
    )
    with pytest.raises(PermissionError, match="ACL denied"):
        atomic_io._acquire_group_locks((parent,), None, timeout_seconds=1)


def test_group_lock_ownership_write_failure_cleans_owned_lock(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "data"
    monkeypatch.setattr(
        atomic_io.os,
        "write",
        lambda *_args: (_ for _ in ()).throw(PermissionError("denied")),
    )
    with pytest.raises(PermissionError):
        atomic_io._acquire_group_locks((parent,), None, timeout_seconds=1)
    assert not (parent / ".atomic-write-group.lock").exists()


@pytest.mark.parametrize(
    ("payload", "alive", "reclaimed"),
    [
        ({"owner_pid": 999999, "lock_type": "reader"}, False, True),
        ({"owner_pid": 999999, "lock_type": "reader"}, True, False),
        ({"owner_pid": "999999", "lock_type": "reader"}, False, False),
        ({"owner_pid": 999999, "lock_type": "reader", "journal_path": "forged"}, False, False),
    ],
)
def test_reader_lock_recovery_requires_exact_dead_owner_evidence(
    tmp_path: Path, monkeypatch, payload: dict[str, object], alive: bool, reclaimed: bool
) -> None:
    lock = tmp_path / ".atomic-write-group.lock"
    lock.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(atomic_io, "_pid_alive", lambda _pid: alive)
    assert atomic_io._recover_lock(lock) is reclaimed
    assert lock.exists() is not reclaimed


def test_stale_lock_cannot_recover_a_journal_outside_its_recovery_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside-new")
    forged_root = tmp_path / "forged" / ".atomic-transactions" / "forged"
    forged_root.mkdir(parents=True)
    backup = forged_root / "backup.bin"
    backup.write_bytes(b"outside-old")
    journal = forged_root / "journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "forged",
                "owner_pid": 999999,
                "state": "prepared",
                "entries": [
                    {
                        "destination": str(outside.resolve()),
                        "backup_path": str(backup.resolve()),
                        "previous_sha256": hashlib.sha256(b"outside-old").hexdigest(),
                    }
                ],
                "staged_paths": [],
                "lock_paths": [],
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "data" / "store.bin"
    destination.parent.mkdir(parents=True)
    lock = destination.parent / ".atomic-write-group.lock"
    lock.write_text(
        json.dumps({"owner_pid": 999999, "journal_path": str(journal.resolve())}),
        encoding="utf-8",
    )

    with pytest.raises(TimeoutError):
        atomic_io.wait_for_atomic_group(destination, timeout_seconds=0.01)

    assert outside.read_bytes() == b"outside-new"
    assert lock.exists()


def test_stale_lock_does_not_recover_unrelated_transaction_under_sibling_root(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "data" / "store.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"current")
    victim = tmp_path / "other" / "victim.bin"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(b"new")
    transaction_root = tmp_path / "other" / ".atomic-transactions" / "forged"
    transaction_root.mkdir(parents=True)
    backup = transaction_root / "backup.bin"
    backup.write_bytes(b"old")
    journal = transaction_root / "journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "forged",
                "owner_pid": 999999,
                "state": "prepared",
                "entries": [
                    {
                        "destination": str(victim.resolve()),
                        "backup_path": str(backup.resolve()),
                        "previous_sha256": hashlib.sha256(b"old").hexdigest(),
                    }
                ],
                "staged_paths": [],
                "lock_paths": [],
            }
        ),
        encoding="utf-8",
    )
    lock = destination.parent / ".atomic-write-group.lock"
    lock.write_text(
        json.dumps(
            {
                "owner_pid": 999999,
                "journal_path": str(journal.resolve()),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TimeoutError):
        atomic_io.wait_for_atomic_group(destination, timeout_seconds=0.01)

    assert victim.read_bytes() == b"new"
    assert journal.exists()
    assert lock.exists()


def test_stale_lock_with_unhashable_journal_state_is_left_in_place(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "store.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"new")
    transaction_root = tmp_path / ".atomic-transactions" / "invalid-state"
    transaction_root.mkdir(parents=True)
    backup = transaction_root / "backup.bin"
    backup.write_bytes(b"old")
    lock = destination.parent / ".atomic-write-group.lock"
    journal = transaction_root / "journal.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "invalid-state",
                "owner_pid": 999999,
                "state": [],
                "entries": [
                    {
                        "destination": str(destination.resolve()),
                        "backup_path": str(backup.resolve()),
                        "previous_sha256": hashlib.sha256(b"old").hexdigest(),
                    }
                ],
                "staged_paths": [],
                "lock_paths": [str(lock.resolve())],
            }
        ),
        encoding="utf-8",
    )
    lock.write_text(
        json.dumps(
            {
                "owner_pid": 999999,
                "journal_path": str(journal.resolve()),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TimeoutError):
        atomic_io.wait_for_atomic_group(destination, timeout_seconds=0.01)

    assert destination.read_bytes() == b"new"
    assert journal.exists()
    assert lock.exists()


def test_activation_rollback_failure_preserves_recovery_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "data" / "first.bin"
    second = tmp_path / "configs" / "second.bin"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"old-a")
    second.write_bytes(b"old-b")
    real_replace = Path.replace
    first_activated = False

    def fail_activation_and_rollback(source: Path, destination: Path):
        nonlocal first_activated
        if Path(destination) == second:
            raise PermissionError("activation denied for second")
        if Path(destination) == first:
            if first_activated:
                raise PermissionError("rollback denied for first")
            first_activated = True
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_activation_and_rollback)

    with pytest.raises(PermissionError):
        atomic_io.atomic_write_group(
            (_request(first, b"new-a"), _request(second, b"new-b")),
        )

    journals = list(tmp_path.rglob(".atomic-transactions/*/journal.json"))
    assert len(journals) == 1
    payload = json.loads(journals[0].read_text(encoding="utf-8"))
    assert payload["state"] == "recovery_required"
    assert first.read_bytes() == b"new-a"
    assert second.read_bytes() == b"old-b"
    assert any(Path(path).exists() for path in payload["staged_paths"])
    assert all(Path(path).exists() for path in payload["lock_paths"])

    from etf_cockpit.operations.recovery import recover_incomplete_transactions

    result = recover_incomplete_transactions(
        tmp_path,
        event_path=tmp_path / "logs" / "session.jsonl",
    )[0]
    assert result.state == "recovery_required"
    assert result.startup_mode == "read_only"
    assert journals[0].exists()


@pytest.mark.serial
@pytest.mark.xdist_group("concurrency")
def test_recovery_of_interrupted_second_real_writer_preserves_first_commit(tmp_path: Path) -> None:
    from etf_cockpit.operations.recovery import recover_incomplete_transactions

    destination = tmp_path / "data" / "canonical.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    first_at_commit = threading.Event()
    release_first = threading.Event()
    second_at_commit = threading.Event()
    errors: list[BaseException] = []

    def first_hook(state: str, _journal: Path) -> None:
        if state == "committing":
            first_at_commit.set()
            assert release_first.wait(timeout=5)

    def second_hook(state: str, _journal: Path) -> None:
        if state == "committing":
            second_at_commit.set()
        if state == "manifest_publish":
            raise atomic_io.AtomicWriteInterrupted(state)

    def write(payload: bytes, hook) -> None:
        try:
            atomic_io.atomic_write_group((_request(destination, payload),), lifecycle_hook=hook)
        except atomic_io.AtomicWriteInterrupted:
            pass
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=write, args=(b"new-1", first_hook))
    second = threading.Thread(target=write, args=(b"new-2", second_hook))
    first.start()
    assert first_at_commit.wait(timeout=5)
    second.start()
    second_at_commit.wait(timeout=0.25)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert destination.read_bytes() == b"new-2"

    results = recover_incomplete_transactions(
        tmp_path,
        event_path=tmp_path / "logs" / "session.jsonl",
    )

    assert [result.state for result in results] == ["rolled_back"]
    assert destination.read_bytes() == b"new-1"


def test_staged_checksum_is_recomputed_after_commit_hook_before_activation(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "canonical.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")

    def tamper(state: str, journal: Path) -> None:
        if state == "committing":
            payload = json.loads(journal.read_text(encoding="utf-8"))
            Path(payload["entries"][0]["staged_path"]).write_bytes(b"TAMPERED")

    with pytest.raises(OSError, match="staged payload checksum mismatch"):
        atomic_io.atomic_write_group(
            (_request(destination, b"new"),),
            lifecycle_hook=tamper,
        )

    assert destination.read_bytes() == b"old"
    assert list(tmp_path.rglob(".atomic-transactions/*/journal.json")) == []
