from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.core import atomic_io
from etf_cockpit.core.atomic_io import (
    atomic_write_bytes,
    atomic_write_group,
    backup_paths,
    verify_backup_manifest,
    wait_for_atomic_group,
)
from etf_cockpit.core.atomic_io import AtomicWriteRequest
from etf_cockpit.core.exceptions import StoreValidationError
from etf_cockpit.data import trust_artifacts
from etf_cockpit.data.import_pipeline import commit_price_import
from etf_cockpit.data.providers import ProviderResult


def test_failed_validator_preserves_previous_destination(tmp_path):
    destination = tmp_path / "store.json"
    destination.write_text('{"valid": true}', encoding="utf-8")

    def reject(_: Path) -> None:
        raise StoreValidationError("invalid replacement")

    with pytest.raises(StoreValidationError, match="invalid replacement"):
        atomic_write_bytes(destination, b"broken", validator=reject)

    assert destination.read_text(encoding="utf-8") == '{"valid": true}'
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_failed_replace_preserves_previous_destination(tmp_path, monkeypatch):
    destination = tmp_path / "store.json"
    destination.write_text('{"valid": true}', encoding="utf-8")

    def fail_replace(self: Path, target: Path):
        raise PermissionError("locked destination")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError, match="locked destination"):
        atomic_write_bytes(destination, b'{"valid": false}', validator=lambda _: None)

    assert destination.read_text(encoding="utf-8") == '{"valid": true}'
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def _windows_permission_error(code: int, message: str) -> PermissionError:
    error = PermissionError(message)
    error.winerror = code
    return error


def test_windows_replace_retries_candidate_error_then_succeeds(tmp_path, monkeypatch):
    destination = tmp_path / "store.json"
    destination.write_bytes(b"old")
    real_replace = Path.replace
    candidate = _windows_permission_error(5, "destination in use")
    attempts = 0
    sleeps: list[float] = []

    def replace(self: Path, target: Path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise candidate
        return real_replace(self, target)

    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", True)
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(atomic_io.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(atomic_io.time, "sleep", sleeps.append)

    atomic_write_bytes(destination, b"new", validator=lambda _: None)

    assert attempts == 2
    assert sleeps == [0.010]
    assert destination.read_bytes() == b"new"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_windows_replace_propagates_first_persistent_candidate_error(
    tmp_path, monkeypatch
):
    destination = tmp_path / "store.json"
    destination.write_bytes(b"old")
    first = _windows_permission_error(32, "first sharing violation")
    later = _windows_permission_error(5, "later access denied")
    errors = iter((first, later))
    clock = iter((20.0, 20.0, 20.250))
    sleeps: list[float] = []

    def replace(self: Path, target: Path):
        raise next(errors)

    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", True)
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(atomic_io.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(atomic_io.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError) as raised:
        atomic_write_bytes(destination, b"new", validator=lambda _: None)

    assert raised.value is first
    assert sleeps == [0.010]
    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_windows_replace_does_not_attempt_again_after_sleep_overshoots_deadline(
    tmp_path, monkeypatch
):
    destination = tmp_path / "store.json"
    destination.write_bytes(b"old")
    candidate = _windows_permission_error(32, "sharing violation")
    attempts = 0
    clock = iter((30.0, 30.0, 30.251))
    sleeps: list[float] = []

    def replace(self: Path, target: Path):
        nonlocal attempts
        attempts += 1
        raise candidate

    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", True)
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(atomic_io.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(atomic_io.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError) as raised:
        atomic_write_bytes(destination, b"new", validator=lambda _: None)

    assert raised.value is candidate
    assert attempts == 1
    assert sleeps == [0.010]
    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_windows_replace_propagates_noncandidate_error_without_retry(
    tmp_path, monkeypatch
):
    destination = tmp_path / "store.json"
    destination.write_bytes(b"old")
    noncandidate = _windows_permission_error(13, "not retryable")
    attempts = 0
    sleeps: list[float] = []

    def replace(self: Path, target: Path):
        nonlocal attempts
        attempts += 1
        raise noncandidate

    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", True)
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(atomic_io.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError) as raised:
        atomic_write_bytes(destination, b"new", validator=lambda _: None)

    assert raised.value is noncandidate
    assert attempts == 1
    assert sleeps == []
    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_atomic_write_does_not_retry_validator(tmp_path):
    destination = tmp_path / "store.json"
    destination.write_bytes(b"old")
    error = _windows_permission_error(5, "validator rejected staged file")
    validations = 0

    def validate(_: Path) -> None:
        nonlocal validations
        validations += 1
        raise error

    with pytest.raises(PermissionError) as raised:
        atomic_write_bytes(destination, b"new", validator=validate)

    assert raised.value is error
    assert validations == 1
    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_group_write_bounds_stage_name_for_long_destination(tmp_path):
    destination = tmp_path / "decision_journal" / "entries" / ("a" * 64 + ".json")

    def validate(staged: Path) -> None:
        if staged.read_bytes() != b"new":
            raise AssertionError("staged payload mismatch")

    atomic_write_group(
        (
            AtomicWriteRequest(destination, b"new", validate),
        )
    )

    assert destination.read_bytes() == b"new"
    assert not list(destination.parent.glob("*.group.tmp"))


def test_backup_manifest_matches_checksums(tmp_path):
    first = tmp_path / "data" / "one.json"
    second = tmp_path / "configs" / "two.yaml"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text('{"one": 1}', encoding="utf-8")
    second.write_text("two: 2", encoding="utf-8")

    manifest = backup_paths((first, second), tmp_path / "backups")

    assert len(manifest.entries) == 2
    assert verify_backup_manifest(manifest) is True
    assert manifest.manifest_path.is_file()

    payload = __import__("json").loads(manifest.manifest_path.read_text(encoding="utf-8"))
    payload["entries"][0]["sha256"] = "0" * 64
    manifest.manifest_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    assert verify_backup_manifest(manifest) is False


def test_failed_second_price_store_write_restores_both_previous_stores(tmp_path, monkeypatch):
    compatibility = tmp_path / "validated" / "prices.parquet"
    clean = tmp_path / "clean" / "prices.parquet"
    compatibility.parent.mkdir()
    clean.parent.mkdir()
    previous = pd.DataFrame({"date": ["2026-01-01"], "adjusted_close": [100.0]})
    previous.to_parquet(compatibility, index=False)
    previous.to_parquet(clean, index=False)
    replacement = pd.DataFrame({"date": ["2026-01-02"], "adjusted_close": [101.0]})
    real_replace = Path.replace

    def fail_clean(self, destination):
        if Path(destination) == clean:
            raise PermissionError("clean store locked")
        return real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", fail_clean)
    with pytest.raises(PermissionError, match="clean store locked"):
        commit_price_import(
            ProviderResult("test", "prices", "ok", "replacement", replacement),
            compatibility_path=compatibility,
            clean_path=clean,
            raw_dir=tmp_path / "raw",
            snapshots_dir=tmp_path / "snapshots",
        )

    assert pd.read_parquet(compatibility)["adjusted_close"].tolist() == [100.0]
    assert pd.read_parquet(clean)["adjusted_close"].tolist() == [100.0]


def test_failed_trust_csv_write_restores_previous_parquet(tmp_path, monkeypatch):
    path = tmp_path / "evidence.parquet"
    previous = pd.DataFrame({"instrument": ["OLD"], "score": [1.0]})
    previous.to_parquet(path, index=False)
    previous.to_csv(path.with_suffix(".csv"), index=False)
    real_replace = Path.replace

    def fail_csv(self, destination):
        if Path(destination).suffix == ".csv":
            raise PermissionError("csv locked")
        return real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", fail_csv)
    with pytest.raises(PermissionError, match="csv locked"):
        trust_artifacts._write_dual(
            pd.DataFrame({"instrument": ["NEW"], "score": [2.0]}),
            path,
        )

    assert pd.read_parquet(path).to_dict("records") == previous.to_dict("records")
    assert pd.read_csv(path.with_suffix(".csv")).to_dict("records") == previous.to_dict("records")


def test_stale_group_lock_recovers_prepared_transaction(tmp_path):
    destination = tmp_path / "data" / "store.bin"
    destination.parent.mkdir()
    destination.write_bytes(b"new")
    transaction_root = tmp_path / ".atomic-transactions" / "stale"
    transaction_root.mkdir(parents=True)
    backup = transaction_root / "backup.bin"
    backup.write_bytes(b"old")
    journal = transaction_root / "journal.json"
    journal.write_text(
        __import__("json").dumps(
            {
                "schema_version": 1,
                "transaction_id": "stale",
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
                "lock_paths": [str((destination.parent / ".atomic-write-group.lock").resolve())],
            }
        ),
        encoding="utf-8",
    )
    lock = destination.parent / ".atomic-write-group.lock"
    lock.write_text(
        __import__("json").dumps({"owner_pid": 999999, "journal_path": str(journal.resolve())}),
        encoding="utf-8",
    )

    with pytest.raises(TimeoutError):
        wait_for_atomic_group(destination, timeout_seconds=0.01)

    from etf_cockpit.operations.recovery import recover_incomplete_transactions

    outcome = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0]
    assert outcome.state == "quarantined"
    assert destination.read_bytes() == b"new"
    assert lock.exists()
    assert transaction_root.exists()


def test_group_failure_removes_newly_created_first_destination(tmp_path, monkeypatch):
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    real_replace = Path.replace

    def fail_second(self, destination):
        if Path(destination) == second:
            raise PermissionError("second locked")
        return real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", fail_second)
    requests = (
        AtomicWriteRequest(first, b"first", lambda path: None),
        AtomicWriteRequest(second, b"second", lambda path: None),
    )

    with pytest.raises(PermissionError, match="second locked"):
        atomic_write_group(requests)

    assert not first.exists()
    assert not second.exists()
