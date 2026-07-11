from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid


@dataclass(frozen=True)
class AtomicWriteResult:
    destination: Path
    sha256: str
    bytes_written: int
    replaced_existing: bool


@dataclass(frozen=True)
class BackupEntry:
    source_path: Path
    backup_path: Path
    sha256: str
    bytes_copied: int


@dataclass(frozen=True)
class BackupManifest:
    created_at: datetime
    backup_root: Path
    entries: tuple[BackupEntry, ...]
    manifest_path: Path


@dataclass(frozen=True)
class AtomicWriteRequest:
    destination: Path
    payload: bytes
    validator: Callable[[Path], None]


class AtomicWriteInterrupted(RuntimeError):
    """Fault-injection signal that preserves the durable journal for startup recovery."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(
    destination: Path,
    payload: bytes,
    validator: Callable[[Path], None],
) -> AtomicWriteResult:
    destination.parent.mkdir(parents=True, exist_ok=True)
    replaced_existing = destination.exists()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        validator(temp_path)
        temp_path.replace(destination)
        return AtomicWriteResult(
            destination=destination,
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes_written=len(payload),
            replaced_existing=replaced_existing,
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _stage_request(request: AtomicWriteRequest, *, validate: bool = True) -> Path:
    request.destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=request.destination.parent,
        prefix=f".{request.destination.name}.",
        suffix=".group.tmp",
        delete=False,
    ) as handle:
        path = Path(handle.name)
        handle.write(request.payload)
        handle.flush()
        os.fsync(handle.fileno())
    if validate:
        try:
            request.validator(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _retry_unlink(path: Path) -> None:
    for attempt in range(3):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))


def _write_journal(path: Path, payload: dict[str, object]) -> None:
    atomic_write_json(path, payload)


def _cleanup_transaction(payload: dict[str, object], journal_path: Path) -> None:
    for value in payload.get("staged_paths", []):
        _retry_unlink(Path(str(value)))
    for value in payload.get("lock_paths", []):
        _retry_unlink(Path(str(value)))
    shutil.rmtree(journal_path.parent, ignore_errors=True)


def _recover_journal(journal_path: Path, *, force: bool = False) -> bool:
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    owner_pid = int(payload.get("owner_pid", 0))
    if not force and _pid_alive(owner_pid):
        return False
    if payload.get("state") != "committed":
        for entry in reversed(payload.get("entries", [])):
            destination = Path(str(entry["destination"]))
            backup_value = entry.get("backup_path")
            if backup_value:
                backup_path = Path(str(backup_value))
                expected = str(entry["previous_sha256"])
                if destination.is_file() and sha256_file(destination) == expected:
                    continue
                original = backup_path.read_bytes()

                def validate(path: Path, checksum: str = expected) -> None:
                    if sha256_file(path) != checksum:
                        raise OSError(f"transaction recovery checksum mismatch: {path}")

                atomic_write_bytes(destination, original, validate)
            else:
                if destination.exists():
                    _retry_unlink(destination)
    _cleanup_transaction(payload, journal_path)
    return True


def _recover_lock(lock: Path) -> bool:
    try:
        lock_payload = json.loads(lock.read_text(encoding="utf-8"))
        journal_path = Path(str(lock_payload["journal_path"]))
    except (OSError, json.JSONDecodeError, KeyError):
        return False
    return _recover_journal(journal_path)


def _acquire_group_locks(
    parents: tuple[Path, ...],
    journal_path: Path,
    timeout_seconds: float = 5.0,
) -> tuple[Path, ...]:
    deadline = time.monotonic() + timeout_seconds
    locks: list[Path] = []
    try:
        for parent in parents:
            parent.mkdir(parents=True, exist_ok=True)
            lock = parent / ".atomic-write-group.lock"
            while True:
                try:
                    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(
                        descriptor,
                        json.dumps(
                            {"owner_pid": os.getpid(), "journal_path": str(journal_path.resolve())}
                        ).encode("utf-8"),
                    )
                    os.close(descriptor)
                    locks.append(lock)
                    break
                except FileExistsError:
                    if _recover_lock(lock):
                        continue
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out waiting for atomic write lock: {lock}")
                    time.sleep(0.025)
        return tuple(locks)
    except Exception:
        for lock in locks:
            lock.unlink(missing_ok=True)
        raise


def wait_for_atomic_group(path: Path, timeout_seconds: float = 5.0) -> None:
    lock = path.parent / ".atomic-write-group.lock"
    deadline = time.monotonic() + timeout_seconds
    while lock.exists():
        if _recover_lock(lock):
            continue
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for atomic write transaction: {lock}")
        time.sleep(0.025)


def atomic_write_group(
    requests: Iterable[AtomicWriteRequest],
    *,
    lifecycle_hook: Callable[[str, Path], None] | None = None,
) -> tuple[AtomicWriteResult, ...]:
    request_tuple = tuple(requests)
    if not request_tuple:
        return ()
    destinations = [request.destination.resolve() for request in request_tuple]
    if len(destinations) != len(set(destinations)):
        raise ValueError("atomic write group destinations must be unique")
    parents = tuple(sorted({request.destination.parent.resolve() for request in request_tuple}, key=str))
    common_root = Path(os.path.commonpath([str(parent) for parent in parents]))
    transaction_root = common_root / ".atomic-transactions" / uuid.uuid4().hex
    transaction_root.mkdir(parents=True, exist_ok=False)
    journal_path = transaction_root / "journal.json"
    staged: dict[Path, Path] = {}
    previous: dict[Path, bytes | None] = {}
    entries: list[dict[str, object]] = []
    locks: tuple[Path, ...] = ()
    now = datetime.now(timezone.utc).isoformat()
    journal_payload: dict[str, object] = {
        "schema_version": 2,
        "transaction_id": transaction_root.name,
        "workflow_run_id": "",
        "transaction_type": "atomic_write_group",
        "owner_pid": os.getpid(),
        "state": "staging",
        "affected_dataset_ids": [str(path) for path in destinations],
        "base_generation_ids": {},
        "entries": entries,
        "staged_paths": [],
        "final_paths": [],
        "lock_paths": [],
        "expected_checksums": {},
        "started_at": now,
        "updated_at": now,
        "committed_at": None,
        "recovery_instructions": [
            "On interrupted startup, verify journal and payload checksums, then restore the "
            "previous complete generation. Never promote ambiguous staging data."
        ],
    }
    interrupted = False

    def publish_state(state: str) -> None:
        journal_payload["state"] = state
        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        if state == "committed":
            journal_payload["committed_at"] = journal_payload["updated_at"]
        _write_journal(journal_path, journal_payload)
        if lifecycle_hook is not None:
            lifecycle_hook(state, journal_path)

    try:
        _write_journal(journal_path, journal_payload)
        if lifecycle_hook is not None:
            lifecycle_hook("staging", journal_path)
        locks = _acquire_group_locks(parents, journal_path)
        journal_payload["lock_paths"] = [str(path.resolve()) for path in locks]
        _write_journal(journal_path, journal_payload)
        for index, request in enumerate(request_tuple):
            original = request.destination.read_bytes() if request.destination.is_file() else None
            previous[request.destination] = original
            backup_path: Path | None = None
            if original is not None:
                backup_path = transaction_root / f"backup-{index}.bin"
                with backup_path.open("wb") as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
            staged[request.destination] = _stage_request(request, validate=False)
            entries.append(
                {
                    "destination": str(request.destination.resolve()),
                    "backup_path": str(backup_path.resolve()) if backup_path else None,
                    "previous_sha256": hashlib.sha256(original).hexdigest() if original is not None else None,
                    "staged_path": str(staged[request.destination].resolve()),
                    "expected_sha256": hashlib.sha256(request.payload).hexdigest(),
                }
            )
            journal_payload["staged_paths"] = [str(path.resolve()) for path in staged.values()]
            journal_payload["final_paths"] = [str(entry["destination"]) for entry in entries]
            expected_checksums = journal_payload["expected_checksums"]
            assert isinstance(expected_checksums, dict)
            expected_checksums[str(request.destination.resolve())] = hashlib.sha256(
                request.payload
            ).hexdigest()
            journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_journal(journal_path, journal_payload)
        publish_state("validating")
        for request in request_tuple:
            request.validator(staged[request.destination])
        publish_state("committing")
        for request in request_tuple:
            staged_path = staged[request.destination]
            request.validator(staged_path)
            expected = str(journal_payload["expected_checksums"][str(request.destination.resolve())])
            actual = sha256_file(staged_path)
            if actual != expected:
                raise OSError(
                    f"staged payload checksum mismatch: {staged_path} "
                    f"(expected {expected}, found {actual})"
                )
        for request in request_tuple:
            staged[request.destination].replace(request.destination)
        publish_state("manifest_publish")
        publish_state("committed")
        return tuple(
            AtomicWriteResult(
                destination=request.destination,
                sha256=hashlib.sha256(request.payload).hexdigest(),
                bytes_written=len(request.payload),
                replaced_existing=previous[request.destination] is not None,
            )
            for request in request_tuple
        )
    except AtomicWriteInterrupted:
        interrupted = True
        raise
    except Exception:
        if journal_path.is_file():
            _recover_journal(journal_path, force=True)
        raise
    finally:
        if interrupted:
            pass
        elif journal_path.is_file():
            _cleanup_transaction(journal_payload, journal_path)
        else:
            for path in staged.values():
                path.unlink(missing_ok=True)
            for lock in locks:
                lock.unlink(missing_ok=True)
            shutil.rmtree(transaction_root, ignore_errors=True)


def atomic_write_json(destination: Path, payload: object) -> AtomicWriteResult:
    encoded = (json.dumps(payload, indent=2, default=str) + "\n").encode("utf-8")

    def validate(path: Path) -> None:
        json.loads(path.read_text(encoding="utf-8"))

    return atomic_write_bytes(destination, encoded, validate)


def parquet_payload(frame: object) -> bytes:
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)  # type: ignore[union-attr]
    return buffer.getvalue()


def validate_parquet_file(path: Path) -> None:
    import pandas as pd

    pd.read_parquet(path)


def backup_paths(paths: Iterable[Path], backup_root: Path) -> BackupManifest:
    created_at = datetime.now(timezone.utc)
    checkpoint_root = backup_root / created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    checkpoint_root.mkdir(parents=True, exist_ok=False)
    entries: list[BackupEntry] = []
    for source in paths:
        if not source.is_file():
            continue
        key = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
        destination = checkpoint_root / f"{key}_{source.name}"
        shutil.copy2(source, destination)
        source_sha = sha256_file(source)
        if sha256_file(destination) != source_sha:
            raise OSError(f"backup checksum mismatch for {source}")
        entries.append(
            BackupEntry(
                source_path=source.resolve(),
                backup_path=destination.resolve(),
                sha256=source_sha,
                bytes_copied=destination.stat().st_size,
            )
        )
    manifest_path = checkpoint_root / "manifest.json"
    atomic_write_json(
        manifest_path,
        {
            "schema_version": 1,
            "created_at": created_at.isoformat(),
            "entries": [
                {
                    **asdict(entry),
                    "source_path": str(entry.source_path),
                    "backup_path": str(entry.backup_path),
                }
                for entry in entries
            ],
        },
    )
    return BackupManifest(created_at, checkpoint_root, tuple(entries), manifest_path)


def verify_backup_manifest(manifest: BackupManifest) -> bool:
    if not manifest.manifest_path.is_file():
        return False
    try:
        payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    recorded_entries = payload.get("entries", ())
    if len(recorded_entries) != len(manifest.entries):
        return False
    for entry, recorded in zip(manifest.entries, recorded_entries, strict=True):
        expected = {
            "source_path": str(entry.source_path),
            "backup_path": str(entry.backup_path),
            "sha256": entry.sha256,
            "bytes_copied": entry.bytes_copied,
        }
        if recorded != expected:
            return False
        if (
            not entry.backup_path.is_file()
            or entry.backup_path.stat().st_size != entry.bytes_copied
            or sha256_file(entry.backup_path) != entry.sha256
        ):
            return False
    return True


def restore_backup_manifest(manifest: BackupManifest) -> None:
    if not verify_backup_manifest(manifest):
        raise OSError(f"cannot restore an invalid backup manifest: {manifest.manifest_path}")
    for entry in manifest.entries:
        payload = entry.backup_path.read_bytes()
        for attempt in range(3):
            try:
                atomic_write_bytes(
                    entry.source_path,
                    payload,
                    validator=lambda path, expected=entry.sha256: (
                        None
                        if sha256_file(path) == expected
                        else (_ for _ in ()).throw(OSError(f"restore checksum mismatch: {path}"))
                    ),
                )
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
