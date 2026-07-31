from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etf_cockpit.core import atomic_io
from etf_cockpit.operations.recovery import recover_incomplete_transactions


def _request(path: Path, payload: bytes) -> atomic_io.AtomicWriteRequest:
    return atomic_io.AtomicWriteRequest(path, payload, lambda candidate: candidate.read_bytes())


def _interrupt_at(state: str):
    def hook(current: str, _journal: Path) -> None:
        if current == state:
            raise atomic_io.AtomicWriteInterrupted(current)

    return hook


def test_schema3_authority_is_immutable_and_lifecycle_is_complete(tmp_path: Path) -> None:
    first = tmp_path / "data" / "a.bin"
    second = tmp_path / "configs" / "b.bin"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    states: list[str] = []
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group(
            (_request(first, b"a"), _request(second, b"b")),
            lifecycle_hook=lambda state, _path: (
                states.append(state),
                (_ for _ in ()).throw(atomic_io.AtomicWriteInterrupted(state))
                if state == "armed"
                else None,
            ),
        )
    journal = next(tmp_path.rglob("journal.json"))
    authority = journal.parent / "authority.json"
    payload = json.loads(journal.read_text(encoding="utf-8"))
    authority_raw = authority.read_bytes()
    assert payload["schema_version"] == 3
    assert payload["protocol"] == "destination-authority-v1"
    assert payload["authority_sha256"] == hashlib.sha256(authority_raw).hexdigest()
    assert payload["lock_paths"] == []
    expected_markers = {
        str((first.parent / ".atomic-write-group.lock").resolve()),
        str((second.parent / ".atomic-write-group.lock").resolve()),
        str((tmp_path / ".atomic-write-group.lock").resolve()),
    }
    assert set(payload["marker_paths"]) == expected_markers
    assert set(payload["marker_tokens"]) == expected_markers
    assert all(Path(marker).exists() for marker in expected_markers)
    assert states == ["memory", "authority_published", "markers_publishing", "armed"]
    original = authority_raw
    with pytest.raises((FileExistsError, atomic_io.QuarantineError, OSError)):
        atomic_io._publish_authority(
            authority,
            transaction_id=payload["transaction_id"],
            nonce=payload["transaction_nonce"],
            destinations=tuple(Path(value) for value in payload["affected_dataset_ids"]),
            created_at=payload["created_at"],
        )
    assert authority.read_bytes() == original
    assert recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0].state == "rolled_back"


def test_schema3_authority_tamper_quarantines_without_mutation(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "value.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=_interrupt_at("armed"))
    journal = next(tmp_path.rglob("journal.json"))
    authority = journal.parent / "authority.json"
    journal_before = journal.read_bytes()
    authority_payload = json.loads(authority.read_text(encoding="utf-8"))
    authority_payload["destinations"] = [str((tmp_path / "data" / "forged.bin").resolve())]
    authority.write_text(json.dumps(authority_payload), encoding="utf-8")
    result = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0]
    assert result.state == "quarantined"
    assert destination.read_bytes() == b"old"
    assert journal.exists() and authority.exists()
    assert journal.read_bytes() == journal_before


def test_schema3_marker_aba_quarantines_without_unlink(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "value.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=_interrupt_at("armed"))
    journal = next(tmp_path.rglob("journal.json"))
    payload = json.loads(journal.read_text(encoding="utf-8"))
    marker = destination.parent / ".atomic-write-group.lock"
    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    marker_payload["token"] = "foreign-token"
    marker.write_text(json.dumps(marker_payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    journal_before = journal.read_bytes()
    result = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0]
    assert result.state == "quarantined"
    assert destination.read_bytes() == b"old"
    assert marker.exists() and journal.read_bytes() == journal_before
    assert payload["marker_tokens"][str(marker.resolve())] != "foreign-token"


def test_schema3_marker_publication_flushes_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "data" / "value.bin"
    destination.parent.mkdir(parents=True)
    flushed: list[Path] = []
    original_fsync_directory = atomic_io._fsync_directory

    def record_fsync(path: Path) -> None:
        flushed.append(Path(path).resolve())
        original_fsync_directory(path)

    monkeypatch.setattr(atomic_io, "_fsync_directory", record_fsync)
    atomic_io.atomic_write_group((_request(destination, b"new"),))
    assert destination.parent.resolve() in flushed
    assert any(path.name == ".atomic-transactions" for path in flushed)


def test_schema3_transaction_root_flush_precedes_authority_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "data" / "value.bin"
    destination.parent.mkdir(parents=True)
    flushed: list[Path] = []
    original_fsync_directory = atomic_io._fsync_directory

    def record_fsync(path: Path) -> None:
        flushed.append(Path(path).resolve())
        original_fsync_directory(path)

    monkeypatch.setattr(atomic_io, "_fsync_directory", record_fsync)
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group(
            (_request(destination, b"new"),),
            lifecycle_hook=_interrupt_at("authority_published"),
        )
    assert flushed[0] == (destination.parent / ".atomic-transactions").resolve()


def test_atomic_group_reader_publishes_no_reader_markers(tmp_path: Path) -> None:
    first = tmp_path / "data" / "a.bin"
    second = tmp_path / "configs" / "b.bin"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    assert atomic_io.read_atomic_group((first, second)) == (b"a", b"b")
    assert not list(tmp_path.rglob(".atomic-write-group.lock"))


@pytest.mark.parametrize(
    "state",
    ["authority_published", "markers_publishing", "armed", "preparing", "prepared", "committing", "committed", "cleaned"],
)
def test_crash_boundary_is_recoverable_or_preserves_commit(tmp_path: Path, state: str) -> None:
    destination = tmp_path / "data" / f"{state}.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group(
            (_request(destination, b"new"),),
            lifecycle_hook=_interrupt_at(state),
        )
    result = recover_incomplete_transactions(tmp_path, event_path=tmp_path / f"{state}.events")[0]
    assert result.state == "committed" if state in {"committed", "cleaned"} else result.state == "rolled_back"
    assert destination.read_bytes() == (b"new" if state in {"committed", "cleaned"} else b"old")
    assert not list(tmp_path.rglob(".atomic-transactions/*"))


def test_committing_third_party_destination_is_quarantined(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "value.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group(
            (_request(destination, b"new"),),
            lifecycle_hook=_interrupt_at("committing"),
        )
    journal = next(tmp_path.rglob("journal.json"))
    destination.write_bytes(b"third-party")
    journal_before = journal.read_bytes()
    result = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0]
    assert result.state == "quarantined"
    assert destination.read_bytes() == b"third-party"
    assert journal.exists() and journal.read_bytes() == journal_before


@pytest.mark.parametrize("mutation", ["third", "missing", "directory"])
def test_prepared_ambiguous_destination_is_quarantined_without_cleanup(
    tmp_path: Path, mutation: str
) -> None:
    destination = tmp_path / "data" / "value.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group(
            (_request(destination, b"new"),),
            lifecycle_hook=_interrupt_at("prepared"),
        )
    journal = next(tmp_path.rglob("journal.json"))
    journal_before = journal.read_bytes()
    if mutation == "third":
        destination.write_bytes(b"third-party")
    else:
        destination.unlink()
        if mutation == "directory":
            destination.mkdir()
    result = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0]
    assert result.state == "quarantined"
    if mutation == "third":
        assert destination.read_bytes() == b"third-party"
    elif mutation == "directory":
        assert destination.is_dir()
    else:
        assert not destination.exists()
    assert journal.exists() and journal.read_bytes() == journal_before


def test_rollback_terminal_state_survives_cleanup_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "data" / "value.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        atomic_io.atomic_write_group(
            (_request(destination, b"new"),),
            lifecycle_hook=_interrupt_at("committing"),
        )
    journal = next(tmp_path.rglob("journal.json"))
    cleanup = atomic_io._cleanup_schema3_transaction
    failed = False

    def fail_once(payload: dict[str, object], journal_path: Path) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated cleanup interruption")
        cleanup(payload, journal_path)

    monkeypatch.setattr(atomic_io, "_cleanup_schema3_transaction", fail_once)
    first = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "first.events")[0]
    assert first.state == "recovery_required"
    durable = json.loads(journal.read_text(encoding="utf-8"))
    assert durable["state"] == "rolled_back"
    assert durable["status"] == "rolled_back"
    assert destination.read_bytes() == b"old"
    monkeypatch.setattr(atomic_io, "_cleanup_schema3_transaction", cleanup)
    second = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "second.events")[0]
    assert second.state == "rolled_back"
    assert not list(tmp_path.rglob(".atomic-transactions/*"))
