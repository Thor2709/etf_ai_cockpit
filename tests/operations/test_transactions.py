from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
        "base_generations",
        "staging_paths",
        "final_paths",
        "expected_checksums",
        "status",
        "started_at",
        "updated_at",
        "committed_at",
        "recovery_instructions",
    } <= fields


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
        final_paths={"canonical": str(tmp_path / "data" / "canonical.bin")},
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
