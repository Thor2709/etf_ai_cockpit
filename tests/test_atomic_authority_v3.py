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


def test_atomic_group_reader_publishes_no_reader_markers(tmp_path: Path) -> None:
    first = tmp_path / "data" / "a.bin"
    second = tmp_path / "configs" / "b.bin"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    assert atomic_io.read_atomic_group((first, second)) == (b"a", b"b")
    assert not list(tmp_path.rglob(".atomic-write-group.lock"))

