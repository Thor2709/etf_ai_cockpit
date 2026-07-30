from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

from etf_cockpit.core.process import pid_is_alive as _pid_alive
from etf_cockpit.core.file_guard import persistent_file_guard


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


_STAGE_PREFIX_DIGEST_LENGTH = 32
_GROUP_LOCK_SCHEMA_VERSION = 1
_GROUP_GUARD_SUFFIX = ".atomic-write-group.guard"
_GROUP_GUARD_PROTOCOL = "sealed-v1"
_AUTHORITY_PROTOCOL = "destination-authority-v1"
_AUTHORITY_SCHEMA_VERSION = 1
_ATOMIC_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class Deadline:
    """One immutable monotonic deadline shared by guard closure and recovery."""

    value: float

    @classmethod
    def after(cls, timeout_seconds: float) -> "Deadline":
        if timeout_seconds < 0:
            raise ValueError("deadline timeout must be non-negative")
        return cls(time.monotonic() + timeout_seconds)

    def remaining(self) -> float:
        return max(0.0, self.value - time.monotonic())

    def expired(self) -> bool:
        return time.monotonic() >= self.value


@dataclass(frozen=True)
class DestinationAuthority:
    """Immutable transaction authority, independent of mutable journal fields."""

    transaction_id: str
    transaction_nonce: str
    destinations: tuple[Path, ...]
    fingerprint: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class WriterEvidence:
    authority: DestinationAuthority
    state: str
    entries_complete: bool
    markers_complete: bool


class QuarantineError(OSError):
    """Evidence cannot authorise a mutation; callers must leave it untouched."""


def _path_identity(path: Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _canonical_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    unique: dict[str, Path] = {}
    for path in paths:
        resolved = Path(path).resolve()
        unique.setdefault(_path_identity(resolved), resolved)
    return tuple(unique[key] for key in sorted(unique))


def _authority_fingerprint(transaction_id: str, nonce: str, destinations: tuple[Path, ...]) -> str:
    body = {
        "protocol": _AUTHORITY_PROTOCOL,
        "schema_version": _AUTHORITY_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "transaction_nonce": nonce,
        "destinations": [str(path) for path in destinations],
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _authority_bytes(
    transaction_id: str,
    nonce: str,
    destinations: tuple[Path, ...],
    created_at: str,
) -> tuple[bytes, str]:
    fingerprint = _authority_fingerprint(transaction_id, nonce, destinations)
    body = {
        "protocol": _AUTHORITY_PROTOCOL,
        "schema_version": _AUTHORITY_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "transaction_nonce": nonce,
        "destinations": [str(path) for path in destinations],
        "fingerprint": fingerprint,
        "created_at": created_at,
    }
    encoded = (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return encoded, fingerprint


def _publish_authority(
    path: Path,
    *,
    transaction_id: str,
    nonce: str,
    destinations: tuple[Path, ...],
    created_at: str,
) -> DestinationAuthority:
    """Create an authority exactly once, fsyncing both file and containing directory."""
    encoded, fingerprint = _authority_bytes(transaction_id, nonce, destinations, created_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError("destination authority write was incomplete")
        os.fsync(descriptor)
    except FileExistsError as error:
        raise QuarantineError(f"destination authority already exists: {path}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if os.name != "nt":
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return DestinationAuthority(
        transaction_id=transaction_id,
        transaction_nonce=nonce,
        destinations=destinations,
        fingerprint=fingerprint,
        path=path.resolve(),
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def _load_authority(path: Path, *, expected_sha256: str | None = None) -> DestinationAuthority:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise QuarantineError(f"destination authority is unreadable: {path}") from error
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise QuarantineError("destination authority digest mismatch")
    if not isinstance(payload, dict):
        raise QuarantineError("destination authority must be an object")
    required = {
        "protocol", "schema_version", "transaction_id", "transaction_nonce",
        "destinations", "fingerprint", "created_at",
    }
    if set(payload) != required or payload.get("protocol") != _AUTHORITY_PROTOCOL:
        raise QuarantineError("destination authority protocol is invalid")
    if payload.get("schema_version") != _AUTHORITY_SCHEMA_VERSION:
        raise QuarantineError("destination authority schema is invalid")
    transaction_id = payload.get("transaction_id")
    nonce = payload.get("transaction_nonce")
    values = payload.get("destinations")
    fingerprint = payload.get("fingerprint")
    if (
        not isinstance(transaction_id, str) or not transaction_id
        or not isinstance(nonce, str) or not nonce
        or not isinstance(values, list) or not values
        or not isinstance(fingerprint, str)
        or not isinstance(payload.get("created_at"), str)
    ):
        raise QuarantineError("destination authority fields are invalid")
    destinations: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise QuarantineError("destination authority paths must be absolute")
        try:
            resolved = Path(value).resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise QuarantineError("destination authority path cannot be resolved") from error
        if os.path.normcase(str(resolved)) != os.path.normcase(value):
            raise QuarantineError("destination authority path is not canonical")
        destinations.append(resolved)
    canonical = _canonical_paths(destinations)
    if tuple(destinations) != canonical:
        raise QuarantineError("destination authority destinations are not sorted/unique")
    expected_fingerprint = _authority_fingerprint(transaction_id, nonce, canonical)
    if fingerprint != expected_fingerprint:
        raise QuarantineError("destination authority fingerprint mismatch")
    return DestinationAuthority(
        transaction_id=transaction_id,
        transaction_nonce=nonce,
        destinations=canonical,
        fingerprint=fingerprint,
        path=path.resolve(),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _authority_from_payload(payload: dict[str, object], journal_path: Path) -> DestinationAuthority:
    if payload.get("schema_version") != _ATOMIC_SCHEMA_VERSION:
        raise QuarantineError("journal is not destination-authority schema3")
    path_value = payload.get("authority_path")
    digest = payload.get("authority_sha256")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise QuarantineError("journal authority_path is invalid")
    if not isinstance(digest, str) or len(digest) != 64:
        raise QuarantineError("journal authority_sha256 is invalid")
    authority_path = Path(path_value).resolve(strict=False)
    if authority_path.parent != journal_path.parent.resolve() or authority_path.name != "authority.json":
        raise QuarantineError("journal authority path is outside transaction root")
    authority = _load_authority(authority_path, expected_sha256=digest)
    if authority.transaction_id != payload.get("transaction_id"):
        raise QuarantineError("authority transaction identity mismatch")
    nonce = payload.get("transaction_nonce")
    if not isinstance(nonce, str) or authority.transaction_nonce != nonce:
        raise QuarantineError("authority transaction nonce mismatch")
    if payload.get("authority_fingerprint") != authority.fingerprint:
        raise QuarantineError("journal authority fingerprint mismatch")
    affected = payload.get("affected_dataset_ids")
    if not isinstance(affected, list) or tuple(affected) != tuple(str(path) for path in authority.destinations):
        raise QuarantineError("journal affected destinations contradict authority")
    return authority


def _authority_guard_parents(authority: DestinationAuthority) -> tuple[Path, ...]:
    parents = tuple(path.parent for path in authority.destinations)
    common = Path(os.path.commonpath([str(parent) for parent in parents])).resolve()
    return _canonical_paths((*parents, common))


@dataclass
class _GroupGuardLease:
    stack: ExitStack | None
    parents: tuple[Path, ...]
    deadline: float
    sealed: bool = False

    def require(self, parents: Iterable[Path]) -> None:
        required = _canonical_paths(parents)
        if self.stack is None:
            raise OSError("sealed guard lease does not cover the complete required set")
        if self.sealed:
            held_identities = {_path_identity(path) for path in self.parents}
            if not {_path_identity(path) for path in required}.issubset(held_identities):
                raise OSError("sealed guard lease does not cover the complete required set")
        elif self.parents != required:
            raise OSError("unsealed guard lease does not cover the complete required set")

    def seal(self) -> None:
        if self.stack is None:
            raise RuntimeError("cannot seal an unacquired guard lease")
        self.sealed = True

    def close(self, primary_error: BaseException | None = None) -> None:
        stack = self.stack
        self.stack = None
        self.parents = ()
        if stack is None:
            return
        try:
            stack.close()
        except BaseException as release_error:
            if primary_error is not None:
                raise primary_error from release_error
            raise


def _stage_prefix(destination: Path) -> str:
    identity = str(destination.resolve()).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:_STAGE_PREFIX_DIGEST_LENGTH]
    return f".atomic-{digest}."


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_destination_with_retry(source: Path, destination: Path) -> None:
    """Retry only documented Windows sharing violations from read handles."""
    for attempt in range(3):
        try:
            source.replace(destination)
            return
        except PermissionError as error:
            code = getattr(error, "winerror", None)
            if os.name != "nt" or code not in {5, 32} or attempt == 2:
                raise
            time.sleep(0.025 * (attempt + 1))
    raise AssertionError("unreachable")


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
        _replace_destination_with_retry(temp_path, destination)
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
        prefix=_stage_prefix(request.destination),
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


def _remove_group_lock(
    lock: Path, token: str | None = None, *, allow_legacy: bool = False
) -> bool:
    try:
        lock_payload = json.loads(lock.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise OSError(f"cannot verify atomic lock ownership: {lock}") from error
    if not isinstance(lock_payload, dict):
        return False
    if token is not None:
        if lock_payload.get("schema_version") == _GROUP_LOCK_SCHEMA_VERSION:
            if lock_payload.get("token") != token:
                return False
        elif not allow_legacy:
            return False
    elif lock_payload.get("schema_version") == _GROUP_LOCK_SCHEMA_VERSION:
        return False
    lock.unlink(missing_ok=True)
    if lock.exists():
        raise OSError(f"atomic lock remained after cleanup: {lock}")
    return True


def _cleanup_transaction(
    payload: dict[str, object],
    journal_path: Path,
    *,
    lock_tokens: dict[Path, str] | None = None,
    allow_legacy_locks: bool = False,
) -> None:
    staged_values = payload.get("staged_paths", [])
    if isinstance(staged_values, list):
        for value in staged_values:
            _retry_unlink(Path(str(value)))
    lock_values = payload.get("lock_paths", [])
    if isinstance(lock_values, list):
        for value in lock_values:
            lock = Path(str(value))
            token: str | None = None
            if lock_tokens is not None:
                token = lock_tokens.get(lock.resolve())
            if not _remove_group_lock(lock, token, allow_legacy=allow_legacy_locks):
                raise OSError(f"atomic lock ownership changed during cleanup: {lock}")
    shutil.rmtree(journal_path.parent, ignore_errors=True)


def _recovery_root_for_journal(journal_path: Path) -> tuple[Path, Path] | None:
    try:
        resolved = journal_path.resolve()
    except (OSError, RuntimeError):
        return None
    if resolved.name != "journal.json" or resolved.parent.parent.name != ".atomic-transactions":
        return None
    return resolved.parent.parent.parent, resolved.parent


def _is_writer_staged_path(staged_path: Path, destination: Path) -> bool:
    """Return whether a stage path matches the writer's canonical temp-file shape."""
    suffix = ".group.tmp"
    prefixes = (f".{destination.name}.", _stage_prefix(destination))
    return (
        staged_path.parent == destination.parent
        and staged_path.name.endswith(suffix)
        and any(
            staged_path.name.startswith(prefix)
            and len(staged_path.name) > len(prefix) + len(suffix)
            for prefix in prefixes
        )
    )


def _expected_group_lock_parents(destinations: Iterable[Path]) -> set[Path]:
    resolved = _canonical_paths(destinations)
    if not resolved:
        return set()
    parents = tuple(path.parent for path in resolved)
    try:
        common_root = Path(os.path.commonpath([str(parent) for parent in parents])).resolve()
    except (OSError, RuntimeError, ValueError):
        return set()
    return set(_canonical_paths((*parents, common_root)))


def _payload_destination_paths(payload: dict[str, object]) -> tuple[Path, ...] | None:
    """Return the complete destination set published by a sealed journal.

    Sealed atomic journals publish destination paths in ``affected_dataset_ids``
    before their entries are populated.  Once entries exist they are a
    corroborating copy and may describe only the already-staged subset.  Older
    non-sealed operation journals use semantic dataset identifiers, so those
    fall back to their entry destinations.
    """

    if payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
        # Schema3 authority is the sole source of destination identity.  A
        # forged/partial lock_paths or entries field is never an authority.
        authority_path = payload.get("authority_path")
        digest = payload.get("authority_sha256")
        if not isinstance(authority_path, str) or not isinstance(digest, str):
            return None
        try:
            transaction_id = str(payload.get("transaction_id", ""))
            authority_file = Path(authority_path).resolve(strict=False)
            if (
                authority_file.name != "authority.json"
                or authority_file.parent.parent.name != ".atomic-transactions"
                or authority_file.parent.name != transaction_id
            ):
                return None
            authority = _load_authority(authority_file, expected_sha256=digest)
            if authority.transaction_id != transaction_id:
                return None
            return authority.destinations
        except (OSError, RuntimeError, ValueError, QuarantineError):
            return None
    sealed = payload.get("guard_protocol") == _GROUP_GUARD_PROTOCOL
    affected = payload.get("affected_dataset_ids")
    affected_paths: tuple[Path, ...] = ()
    valid_affected = (
        isinstance(affected, list)
        and bool(affected)
        and all(isinstance(value, str) and value for value in affected)
        and all(Path(value).is_absolute() for value in affected)
    )
    if valid_affected:
        assert isinstance(affected, list)
        candidate = tuple(Path(value).resolve() for value in affected)
        if len(_canonical_paths(candidate)) != len(candidate):
            return None
        affected_paths = _canonical_paths(candidate)
    elif sealed:
        return None
    entries = payload.get("entries")
    entry_paths: tuple[Path, ...] = ()
    if isinstance(entries, list):
        raw_entries = [
            entry.get("destination")
            for entry in entries
            if isinstance(entry, dict)
        ]
        if raw_entries and not all(isinstance(value, str) and value for value in raw_entries):
            return None
        if raw_entries:
            candidates = tuple(Path(str(value)).resolve() for value in raw_entries)
            if len(_canonical_paths(candidates)) != len(candidates):
                return None
            entry_paths = _canonical_paths(candidates)
    if affected_paths:
        if entry_paths and not set(entry_paths).issubset(affected_paths):
            return None
        return affected_paths
    return entry_paths


def _expected_group_guard_parents_from_payload(
    payload: dict[str, object],
) -> tuple[Path, ...] | None:
    destinations = _payload_destination_paths(payload)
    if not destinations:
        return None
    return _canonical_paths(_expected_group_lock_parents(destinations))


def _expected_group_lock_paths_from_payload(
    payload: dict[str, object],
) -> tuple[Path, ...] | None:
    parents = _expected_group_guard_parents_from_payload(payload)
    if parents is None:
        return None
    return tuple(
        (parent / ".atomic-write-group.lock").resolve()
        for parent in parents
    )


def _group_guard_paths(parents: Iterable[Path]) -> tuple[Path, ...]:
    guards = tuple(Path(parent) / _GROUP_GUARD_SUFFIX for parent in _canonical_paths(parents))
    return tuple(sorted(guards, key=_path_identity))


def _guard_parents_within_root(parents: Iterable[Path], root: Path) -> bool:
    resolved_root = root.resolve()
    try:
        for parent in parents:
            Path(parent).resolve().relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _acquire_group_guards(
    parents: Iterable[Path],
    timeout_seconds: float = 5.0,
    *,
    deadline: float | None = None,
) -> _GroupGuardLease:
    """Acquire all persistent group guards in canonical order and one deadline."""

    stack = ExitStack()
    if deadline is None:
        deadline = time.monotonic() + timeout_seconds
    canonical_parents = _canonical_paths(parents)
    try:
        for guard_path in _group_guard_paths(canonical_parents):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for file guard: {guard_path}")
            stack.enter_context(
                persistent_file_guard(
                    guard_path,
                    timeout_seconds=remaining,
                    deadline=deadline,
                    clock=time.monotonic,
                )
            )
    except BaseException as error:
        try:
            stack.close()
        except BaseException as release_error:
            raise error from release_error
        raise
    return _GroupGuardLease(stack, canonical_parents, deadline)


def _read_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _discover_journal_guards(
    journal_path: Path, *, deadline: float
) -> tuple[_GroupGuardLease, dict[str, object]] | None:
    """Acquire a complete guard set at a journal fixed point, before mutation."""
    payload = _read_object(journal_path)
    if payload is None:
        return None
    if payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
        try:
            _authority_from_payload(payload, journal_path)
        except (QuarantineError, OSError, RuntimeError, ValueError):
            return None
    required = _guard_parents_from_payload(payload)
    is_v3 = payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION
    declared = () if is_v3 else _declared_lock_paths(payload)
    roots = _recovery_root_for_journal(journal_path)
    if not required or roots is None or not _guard_parents_within_root(required, roots[0]):
        return None
    while True:
        if time.monotonic() >= deadline:
            return None
        guards = _acquire_group_guards(required, deadline=deadline)
        reread = _read_object(journal_path)
        if reread is not None:
            if reread.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
                try:
                    _authority_from_payload(reread, journal_path)
                except (QuarantineError, OSError, RuntimeError, ValueError):
                    guards.close()
                    return None
            discovered = _guard_parents_from_payload(reread)
            discovered_paths = () if reread.get("schema_version") == _ATOMIC_SCHEMA_VERSION else _declared_lock_paths(reread)
            if discovered == required and discovered_paths == declared:
                guards.seal()
                return guards, reread
            if discovered and _guard_parents_within_root(discovered, roots[0]):
                guards.close()
                required, declared = discovered, discovered_paths
                continue
        guards.close()
        return None


def _guard_parents_from_payload(payload: dict[str, object]) -> tuple[Path, ...]:
    if payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
        destinations = _payload_destination_paths(payload)
        if destinations is None:
            return ()
        return _canonical_paths(_expected_group_lock_parents(destinations))
    if payload.get("schema_version") == 2:
        if payload.get("guard_protocol") != _GROUP_GUARD_PROTOCOL:
            return ()
        affected = payload.get("affected_dataset_ids")
        if not isinstance(affected, list) or not affected or any(
            not isinstance(value, str) or not Path(value).is_absolute() for value in affected
        ):
            return ()
        destinations = tuple(Path(value).resolve(strict=False) for value in affected)
        if tuple(str(path) for path in destinations) != tuple(affected):
            return ()
        if _canonical_paths(destinations) != destinations:
            return ()
        return _canonical_paths(_expected_group_lock_parents(destinations))
    # Schema1/semantic journals and unknown schemas are read-only evidence.
    return ()


def _declared_lock_paths(payload: dict[str, object]) -> tuple[Path, ...]:
    values = payload.get("lock_paths", [])
    if not isinstance(values, list):
        return ()
    return _canonical_paths(
        Path(value).resolve() for value in values if isinstance(value, str) and value
    )


def _marker_closure(marker: Path) -> tuple[tuple[Path, ...], bool]:
    """Inspect one existing marker without mutating it.

    The Boolean reports whether the marker is structurally inspectable.  An
    uninspectable marker remains a blocker; callers must not publish a new
    transaction in its presence.
    """

    payload = _read_object(marker)
    if payload is None:
        return (), False
    lock_type = payload.get("lock_type", "writer")
    # Reader markers are not part of the v3 protocol.  Treating one as
    # reclaimable would let a stale marker authorize a destination mutation.
    if lock_type == "reader":
        return (), False
    if lock_type != "writer":
        return (), False
    journal_value = payload.get("journal_path")
    if not isinstance(journal_value, str) or not journal_value:
        return (), False
    journal = Path(journal_value).resolve()
    roots = _recovery_root_for_journal(journal)
    if roots is None:
        return (), False
    journal_payload = _read_object(journal)
    if journal_payload is None:
        return (), False
    if journal_payload.get("schema_version") != _ATOMIC_SCHEMA_VERSION:
        # Legacy markers have no immutable destination authority and cannot
        # participate in live closure/reclamation.
        return (), False
    if journal_payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
        try:
            authority = _authority_from_payload(journal_payload, journal)
        except QuarantineError:
            return (), False
        marker_authority = payload.get("authority_sha256")
        if marker_authority != authority.sha256:
            return (), False
    parents = _guard_parents_from_payload(journal_payload)
    if not parents or marker.resolve().parent not in parents:
        return (), False
    if not _guard_parents_within_root(parents, roots[0]):
        return (), False
    return parents, True


def _preflight_group_guards(
    parents: Iterable[Path],
    *,
    timeout_seconds: float = 5.0,
    deadline: float | None = None,
    ignored_markers: Iterable[Path] = (),
) -> _GroupGuardLease:
    """Acquire a marker-closure guard superset before publishing evidence.

    No transaction root, journal, or lock marker is created by this routine.
    Existing writer journals are inspected under the requested guards; any
    valid declared closure is unioned, then the full immutable set is
    reacquired before stale evidence is recovered.  An unresolved marker is a
    hard blocker and therefore times out without allowing a caller to publish.
    """

    if deadline is None:
        deadline = time.monotonic() + timeout_seconds
    required = _canonical_paths(parents)
    ignored = {_path_identity(Path(path)) for path in ignored_markers}
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError("atomic guard closure did not converge before deadline")
        guards = _acquire_group_guards(required, deadline=deadline)
        guards.seal()
        unresolved = False
        discovered = set(required)
        markers: list[Path] = []
        try:
            for parent in required:
                marker = (parent / ".atomic-write-group.lock").resolve()
                if _path_identity(marker) in ignored or not marker.is_file():
                    continue
                markers.append(marker)
                closure, inspectable = _marker_closure(marker)
                if not inspectable:
                    unresolved = True
                else:
                    discovered.update(closure)
            expanded = _canonical_paths(discovered)
            if expanded != required:
                guards.close()
                required = expanded
                continue
            # Re-read the closure under the complete lease, then reclaim every
            # stale marker.  A marker that remains is an unresolved blocker.
            for marker in tuple(markers):
                if marker.is_file() and not _recover_lock(
                    marker,
                    held_guards=guards,
                    deadline=deadline,
                ):
                    unresolved = True
            post_markers: list[Path] = []
            for parent in required:
                marker = (parent / ".atomic-write-group.lock").resolve()
                if _path_identity(marker) in ignored or not marker.is_file():
                    continue
                post_markers.append(marker)
                closure, inspectable = _marker_closure(marker)
                if not inspectable:
                    unresolved = True
                else:
                    post_required = set(required)
                    post_required.update(closure)
                    if _canonical_paths(post_required) != required:
                        guards.close()
                        required = _canonical_paths(post_required)
                        break
            else:
                if post_markers or unresolved:
                    remaining = deadline - time.monotonic()
                    guards.close()
                    if remaining <= 0:
                        raise TimeoutError(
                            "timed out waiting for existing atomic transaction evidence"
                        )
                    # The native guards are already held, so an unresolved
                    # marker cannot be safely bypassed.  Give an external
                    # reclaimer one bounded opportunity before retrying.
                    time.sleep(min(0.025, remaining))
                    continue
                return guards
            continue
        except BaseException as error:
            try:
                guards.close(primary_error=error)
            except BaseException:
                raise
            raise


def _validate_sealed_publication(
    payload: dict[str, object], lock_parents: Iterable[Path]
) -> bool:
    canonical_parents = _canonical_paths(lock_parents)
    expected_paths = tuple(
        (parent / ".atomic-write-group.lock").resolve()
        for parent in canonical_parents
    )
    if payload.get("guard_protocol") != _GROUP_GUARD_PROTOCOL:
        return False
    payload_parents = _expected_group_guard_parents_from_payload(payload)
    if payload_parents != canonical_parents:
        return False
    if _declared_lock_paths(payload) != expected_paths:
        return False
    values = payload.get("lock_tokens")
    if not isinstance(values, dict):
        return False
    normalized: dict[str, str] = {}
    for key, token in values.items():
        if not isinstance(key, str) or not isinstance(token, str) or not token:
            return False
        resolved = str(Path(key).resolve())
        if resolved in normalized or token in normalized.values():
            return False
        normalized[resolved] = token
    return set(normalized) == {str(path) for path in expected_paths}


def _is_writer_lock_path(lock_path: Path, destinations: Iterable[Path]) -> bool:
    if lock_path.name != ".atomic-write-group.lock":
        return False
    destination_set = tuple(destinations)
    # A staging journal can declare the complete intended lock set before its
    # entries are populated.  The recovery-root containment check remains the
    # authority for those early paths.
    return not destination_set or lock_path.parent in _expected_group_lock_parents(destination_set)


def _path_is_contained(path_value: object, root: Path, *, transaction_root: Path | None = None) -> bool:
    if not isinstance(path_value, str) or not path_value:
        return False
    try:
        path = Path(path_value).resolve()
        path.relative_to(root.resolve())
        if transaction_root is not None:
            path.relative_to(transaction_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _validate_recovery_payload_paths(payload: dict[str, object], journal_path: Path) -> bool:
    if payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
        return _validate_schema3_payload(payload, journal_path)
    roots = _recovery_root_for_journal(journal_path)
    if roots is None:
        return False
    recovery_root, transaction_root = roots
    transaction_id = payload.get("transaction_id")
    if transaction_id is not None and transaction_id != transaction_root.name:
        return False
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return False
    destinations: list[Path] = []
    entry_staged_paths: set[Path] = set()
    lock_values = payload.get("lock_paths", [])
    if not isinstance(lock_values, list) or any(
        not isinstance(value, str) or not value for value in lock_values
    ):
        return False
    declared_locks = _canonical_paths(Path(value) for value in lock_values)
    if len(declared_locks) != len(lock_values) or [str(path) for path in declared_locks] != [
        str(Path(value).resolve()) for value in lock_values
    ]:
        return False
    token_values = payload.get("lock_tokens", {})
    protocol = payload.get("guard_protocol")
    if protocol is not None and protocol != _GROUP_GUARD_PROTOCOL:
        return False
    if not isinstance(token_values, dict):
        return False
    token_keys: dict[str, str] = {}
    for key, token in token_values.items():
        if not isinstance(key, str) or not isinstance(token, str) or not token:
            return False
        resolved_key = str(Path(key).resolve())
        if resolved_key in token_keys or token in token_keys.values():
            return False
        token_keys[resolved_key] = token
    declared_key_set = {str(path) for path in declared_locks}
    if protocol == _GROUP_GUARD_PROTOCOL and set(token_keys) != declared_key_set:
        return False
    if token_keys and set(token_keys) != declared_key_set:
        return False
    sealed_destinations: tuple[Path, ...] = ()
    if protocol == _GROUP_GUARD_PROTOCOL:
        payload_destinations = _payload_destination_paths(payload)
        expected_locks = _expected_group_lock_paths_from_payload(payload)
        if payload_destinations is None or expected_locks is None:
            return False
        sealed_destinations = payload_destinations
        if declared_locks != expected_locks:
            return False
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        destination_value = entry.get("destination")
        if not _path_is_contained(destination_value, recovery_root):
            return False
        destination = Path(str(destination_value)).resolve()
        destinations.append(destination)
        backup_path = entry.get("backup_path")
        if backup_path is not None and not _path_is_contained(
            backup_path, recovery_root, transaction_root=transaction_root
        ):
            return False
        if (
            payload.get("schema_version") == 2
            and backup_path is None
            and payload.get("state") != "committed"
            and destination.exists()
        ):
            expected_checksum = entry.get("expected_sha256")
            if not isinstance(expected_checksum, str):
                return False
            try:
                if sha256_file(destination) != expected_checksum:
                    return False
            except (OSError, RuntimeError, ValueError):
                return False
        staged_path = entry.get("staged_path")
        if staged_path is not None:
            if not _path_is_contained(staged_path, recovery_root):
                return False
            staged = Path(str(staged_path)).resolve()
            if not _is_writer_staged_path(staged, destination):
                return False
            entry_staged_paths.add(staged)
    for field in ("staged_paths", "final_paths", "lock_paths"):
        values = payload.get(field, [])
        if not isinstance(values, list):
            return False
        for value in values:
            if not _path_is_contained(value, recovery_root):
                return False
            resolved = Path(str(value)).resolve()
            if field == "staged_paths" and resolved not in entry_staged_paths:
                return False
            if field == "lock_paths":
                if not _is_writer_lock_path(resolved, destinations):
                    return False
                if resolved.is_file():
                    try:
                        lock_payload = json.loads(resolved.read_text(encoding="utf-8"))
                        if not isinstance(lock_payload, dict):
                            return False
                        if lock_payload.get("lock_type") == "reader":
                            return False
                        lock_journal = lock_payload.get("journal_path")
                        if not isinstance(lock_journal, str):
                            return False
                        if Path(lock_journal).resolve() != journal_path.resolve():
                            return False
                        lock_owner = lock_payload.get("owner_pid")
                        journal_owner = payload.get("owner_pid")
                        if type(lock_owner) is not int or type(journal_owner) is not int:
                            return False
                        if lock_owner != journal_owner:
                            return False
                        if lock_payload.get("schema_version") == _GROUP_LOCK_SCHEMA_VERSION:
                            expected_token = token_keys.get(str(resolved))
                            if expected_token is None or lock_payload.get("token") != expected_token:
                                return False
                            if set(lock_payload) != {
                                "schema_version", "owner_pid", "lock_type", "token", "journal_path"
                            }:
                                return False
                        elif token_keys:
                            return False
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        return False
    if protocol == _GROUP_GUARD_PROTOCOL:
        staged_values = payload.get("staged_paths", [])
        final_values = payload.get("final_paths", [])
        if not isinstance(staged_values, list) or not isinstance(final_values, list):
            return False
        resolved_staged = tuple(Path(str(value)).resolve() for value in staged_values)
        resolved_finals = tuple(Path(str(value)).resolve() for value in final_values)
        if len(set(resolved_staged)) != len(resolved_staged):
            return False
        if len(set(resolved_finals)) != len(resolved_finals):
            return False
        if entries:
            if resolved_finals != tuple(destinations):
                return False
            if set(resolved_staged) != entry_staged_paths:
                return False
        elif resolved_staged or resolved_finals:
            return False
    if protocol == _GROUP_GUARD_PROTOCOL and destinations:
        if not set(destinations).issubset(sealed_destinations):
            return False
    return True


_SCHEMA3_STATES = {
    "authority_published", "markers_publishing", "armed", "preparing",
    "prepared", "committing", "committed", "cleaned", "recovery_required", "quarantined",
}


def _validate_schema3_payload(payload: dict[str, object], journal_path: Path) -> bool:
    """Validate schema3 without allowing mutable journal lists to create authority."""
    roots = _recovery_root_for_journal(journal_path)
    if roots is None:
        return False
    try:
        authority = _authority_from_payload(payload, journal_path)
    except (QuarantineError, OSError, RuntimeError, ValueError):
        return False
    if payload.get("transaction_id") != journal_path.parent.name:
        return False
    state = payload.get("state")
    if not isinstance(state, str) or state not in _SCHEMA3_STATES:
        return False
    if payload.get("status", state) != state:
        return False
    owner_pid = payload.get("owner_pid")
    if type(owner_pid) is not int or owner_pid <= 0:
        return False
    for field in ("entries", "staged_paths", "final_paths", "marker_paths", "expected_checksums"):
        if field not in payload:
            return False
    entries = payload.get("entries")
    staged_values = payload.get("staged_paths")
    final_values = payload.get("final_paths")
    marker_values = payload.get("marker_paths")
    checksums = payload.get("expected_checksums")
    if (
        not isinstance(entries, list) or not isinstance(staged_values, list)
        or not isinstance(final_values, list) or not isinstance(marker_values, list)
        or not isinstance(checksums, dict)
    ):
        return False
    expected_markers = tuple(
        str((parent / ".atomic-write-group.lock").resolve())
        for parent in _authority_guard_parents(authority)
    )
    if tuple(str(Path(value).resolve()) for value in marker_values if isinstance(value, str)) != expected_markers:
        return False
    if len(marker_values) != len(expected_markers) or any(not isinstance(value, str) for value in marker_values):
        return False
    entry_destinations: list[Path] = []
    entry_staged: list[Path] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        required = {"destination", "backup_path", "previous_sha256", "staged_path", "expected_sha256"}
        if set(entry) != required:
            return False
        destination_value = entry.get("destination")
        if not isinstance(destination_value, str) or not Path(destination_value).is_absolute():
            return False
        destination = Path(destination_value).resolve(strict=False)
        if str(destination) != destination_value or destination not in authority.destinations:
            return False
        staged_value = entry.get("staged_path")
        if not isinstance(staged_value, str) or not _path_is_contained(staged_value, roots[0]):
            return False
        staged = Path(staged_value).resolve(strict=False)
        if not _is_writer_staged_path(staged, destination):
            return False
        expected = entry.get("expected_sha256")
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            return False
        backup_value = entry.get("backup_path")
        previous = entry.get("previous_sha256")
        if backup_value is None:
            if previous is not None:
                return False
        else:
            if not isinstance(backup_value, str) or not _path_is_contained(backup_value, roots[0], transaction_root=journal_path.parent):
                return False
            if not isinstance(previous, str) or len(previous) != 64 or any(c not in "0123456789abcdef" for c in previous):
                return False
            backup = Path(backup_value).resolve(strict=False)
            if not backup.is_file() or sha256_file(backup) != previous:
                return False
        entry_destinations.append(destination)
        entry_staged.append(staged)
        if staged.is_file() and sha256_file(staged) != expected:
            return False
    if any(not isinstance(value, str) or not _path_is_contained(value, roots[0]) for value in staged_values):
        return False
    resolved_staged_values = tuple(Path(value).resolve(strict=False) for value in staged_values)
    if len(set(resolved_staged_values)) != len(resolved_staged_values) or set(resolved_staged_values) != set(entry_staged):
        return False
    if any(not isinstance(value, str) or not Path(value).is_absolute() for value in final_values):
        return False
    resolved_final_values = tuple(Path(value).resolve(strict=False) for value in final_values)
    if any(path not in authority.destinations for path in resolved_final_values):
        return False
    complete = tuple(entry_destinations) == authority.destinations and len(entries) == len(authority.destinations)
    complete = complete and tuple(str(path) for path in staged_values) == tuple(str(path) for path in entry_staged)
    complete = complete and tuple(str(path) for path in final_values) == tuple(str(path) for path in entry_destinations)
    complete = complete and checksums == {str(path): str(entry["expected_sha256"]) for path, entry in zip(entry_destinations, entries, strict=True)}
    if state in {"prepared", "committing", "committed", "cleaned"} and not complete:
        return False
    if state == "committed":
        for destination, entry in zip(entry_destinations, entries, strict=True):
            if not destination.is_file() or sha256_file(destination) != entry["expected_sha256"]:
                return False
    if state in {"armed", "prepared", "committing", "committed", "cleaned"}:
        # Once armed, every marker must carry the authority digest and token;
        # PID liveness is intentionally irrelevant to schema3 authority.
        tokens = payload.get("marker_tokens")
        if not isinstance(tokens, dict) or set(tokens) != set(expected_markers):
            return False
        if any(not isinstance(key, str) or not isinstance(value, str) or not value for key, value in tokens.items()):
            return False
        for marker_value, token in tokens.items():
            marker = Path(marker_value)
            if marker.is_file():
                marker_payload = _read_object(marker)
                if marker_payload is None or marker_payload.get("schema_version") != _ATOMIC_SCHEMA_VERSION:
                    return False
                if marker_payload.get("token") != token or marker_payload.get("authority_sha256") != authority.sha256:
                    return False
                if marker_payload.get("journal_path") != str(journal_path.resolve()):
                    return False
    return True


def _mark_recovery_required(
    journal_path: Path, reason: BaseException | str
) -> None:
    """Persist an unresolved writer failure while leaving all recovery evidence in place."""
    try:
        current = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(current, dict):
        return
    durable = current
    durable["state"] = "recovery_required"
    durable["status"] = "recovery_required"
    durable["updated_at"] = datetime.now(timezone.utc).isoformat()
    durable["recovery_error"] = str(reason)
    try:
        _write_journal(journal_path, durable)
    except Exception:
        return


def _cleanup_schema3_transaction(payload: dict[str, object], journal_path: Path) -> None:
    """Cleanup only evidence whose ownership is verified under native guards."""
    authority = _authority_from_payload(payload, journal_path)
    staged = payload.get("staged_paths", [])
    if not isinstance(staged, list):
        raise QuarantineError("schema3 staged_paths is not a list")
    for value in staged:
        if not isinstance(value, str):
            raise QuarantineError("schema3 staged path is invalid")
        _retry_unlink(Path(value))
    marker_values = payload.get("marker_paths", [])
    tokens = payload.get("marker_tokens", {})
    if not isinstance(marker_values, list) or not isinstance(tokens, dict):
        raise QuarantineError("schema3 marker evidence is incomplete")
    for value in reversed(marker_values):
        if not isinstance(value, str):
            raise QuarantineError("schema3 marker path is invalid")
        marker = Path(value).resolve()
        if not marker.exists():
            continue
        marker_payload = _read_object(marker)
        expected_token = tokens.get(str(marker))
        if (
            marker_payload is None
            or marker_payload.get("schema_version") != _ATOMIC_SCHEMA_VERSION
            or marker_payload.get("marker_protocol") != _AUTHORITY_PROTOCOL
            or marker_payload.get("lock_type") != "writer"
            or marker_payload.get("journal_path") != str(journal_path.resolve())
            or marker_payload.get("authority_sha256") != authority.sha256
            or marker_payload.get("transaction_id") != authority.transaction_id
            or marker_payload.get("transaction_nonce") != authority.transaction_nonce
            or not isinstance(expected_token, str)
            or marker_payload.get("token") != expected_token
        ):
            raise QuarantineError(f"schema3 marker ownership changed: {marker}")
        marker.unlink()
        if marker.exists():
            raise OSError(f"schema3 marker remained after cleanup: {marker}")
    shutil.rmtree(journal_path.parent, ignore_errors=False)


def _recover_schema3_journal(
    journal_path: Path,
    *,
    held_guards: _GroupGuardLease | None = None,
    deadline: float | None = None,
) -> bool:
    if deadline is None:
        deadline = time.monotonic() + 5.0
    own_guards = held_guards is None
    guards = held_guards
    try:
        if guards is None:
            discovered = _discover_journal_guards(journal_path, deadline=deadline)
            if discovered is None:
                return False
            guards, payload = discovered
        else:
            reread_payload = _read_object(journal_path)
            if reread_payload is None:
                return False
            payload = reread_payload
            required = _guard_parents_from_payload(payload)
            if not required:
                return False
            try:
                guards.require(required)
            except OSError:
                return False
            guards.seal()
            reread = _read_object(journal_path)
            if reread is None or _guard_parents_from_payload(reread) != required:
                return False
            payload = reread
        if payload.get("schema_version") != _ATOMIC_SCHEMA_VERSION:
            return False
        if not _validate_schema3_payload(payload, journal_path):
            return False
        state = payload.get("state")
        if state in {"recovery_required", "quarantined"}:
            return False
        entries = payload.get("entries")
        assert isinstance(entries, list)
        if state == "committed" or state == "cleaned":
            # Validation already proved every destination is the committed
            # generation.  Never roll it back based on owner PID.
            _cleanup_schema3_transaction(payload, journal_path)
            return True
        if state in {"authority_published", "markers_publishing", "armed", "preparing", "prepared"}:
            # No destination mutation is legal before committing; cleanup is
            # therefore safe even when entries are partial.
            _cleanup_schema3_transaction(payload, journal_path)
            return True
        if state != "committing":
            return False
        # Committing has complete evidence.  Restore each prior generation in
        # reverse order while the immutable authority-derived guards remain held.
        for entry in reversed(entries):
            assert isinstance(entry, dict)
            destination = Path(str(entry["destination"]))
            backup_value = entry.get("backup_path")
            expected = str(entry["expected_sha256"])
            if backup_value is None:
                if destination.exists():
                    if not destination.is_file() or sha256_file(destination) != expected:
                        raise QuarantineError("schema3 new destination has ambiguous content")
                    _retry_unlink(destination)
                continue
            backup = Path(str(backup_value))
            previous = str(entry["previous_sha256"])
            if destination.is_file() and sha256_file(destination) == previous:
                continue
            original = backup.read_bytes()

            def validate(path: Path, checksum: str = previous) -> None:
                if sha256_file(path) != checksum:
                    raise OSError(f"schema3 rollback checksum mismatch: {path}")

            atomic_write_bytes(destination, original, validate)
        _cleanup_schema3_transaction(payload, journal_path)
        return True
    finally:
        if own_guards and guards is not None:
            guards.close(primary_error=sys.exc_info()[1])


def _recover_journal(
    journal_path: Path,
    *,
    force: bool = False,
    held_guards: _GroupGuardLease | None = None,
    deadline: float | None = None,
) -> bool:
    initial = _read_object(journal_path)
    if initial is not None and initial.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
        # ``force`` is intentionally ignored for schema3: native guard
        # ownership plus immutable authority, not PID liveness, is decisive.
        return _recover_schema3_journal(
            journal_path, held_guards=held_guards, deadline=deadline
        )
    if deadline is None:
        deadline = time.monotonic() + 5.0
    own_guards = held_guards is None
    guards: _GroupGuardLease | None = held_guards
    try:
        if guards is None:
            discovered = _discover_journal_guards(journal_path, deadline=deadline)
            if discovered is None:
                return False
            guards, payload = discovered
        else:
            reread_payload = _read_object(journal_path)
            if reread_payload is None:
                return False
            payload = reread_payload
            required = _guard_parents_from_payload(payload)
            try:
                guards.require(required)
            except OSError:
                return False
            guards.seal()
            reread = _read_object(journal_path)
            if reread is None or _guard_parents_from_payload(reread) != required:
                return False
            if _declared_lock_paths(reread) != _declared_lock_paths(payload):
                return False
            payload = reread
        if not _validate_recovery_payload_paths(payload, journal_path):
            return False
        state = payload.get("state")
        if not isinstance(state, str) or state in {"recovery_required", "quarantined"}:
            return False
        owner_pid = payload.get("owner_pid")
        if type(owner_pid) is not int or owner_pid <= 0:
            return False
        versioned = payload.get("schema_version") == 2
        if not versioned and not force and _pid_alive(owner_pid):
            return False
        if state != "committed":
            entries_value = payload.get("entries", [])
            if not isinstance(entries_value, list) or not all(
                isinstance(item, dict) for item in entries_value
            ):
                return False
            for entry in reversed(entries_value):
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
                elif destination.exists():
                    _retry_unlink(destination)
        token_values = payload.get("lock_tokens", {})
        lock_tokens: dict[Path, str] = {}
        if isinstance(token_values, dict):
            lock_tokens = {
                Path(path).resolve(): token
                for path, token in token_values.items()
                if isinstance(path, str) and isinstance(token, str)
            }
        _cleanup_transaction(
            payload,
            journal_path,
            lock_tokens=lock_tokens,
            allow_legacy_locks=True,
        )
        return True
    finally:
        if own_guards and guards is not None:
            guards.close(primary_error=sys.exc_info()[1])


def _recover_lock(
    lock: Path,
    *,
    held_guards: _GroupGuardLease | None = None,
    deadline: float | None = None,
) -> bool:
    if held_guards is None:
        raise RuntimeError("lock recovery requires a live guard lease")
    if deadline is None:
        deadline = time.monotonic() + 5.0
    own_guards = held_guards is None
    guards: _GroupGuardLease | None = held_guards
    try:
        initial = _read_object(lock)
        if initial is None:
            return False
        journal_value = initial.get("journal_path")
        if initial.get("lock_type", "writer") == "writer" and isinstance(journal_value, str):
            journal_path = Path(journal_value).resolve()
            journal_payload = _read_object(journal_path)
            if journal_payload is None:
                return False
            parents = _guard_parents_from_payload(journal_payload)
            roots = _recovery_root_for_journal(journal_path)
            if roots is None or not _guard_parents_within_root(parents, roots[0]):
                return False
        else:
            parents = (lock.resolve().parent,)
        if not parents:
            return False
        if guards is None:
            guards = _preflight_group_guards(
                parents,
                deadline=deadline,
                ignored_markers=(lock,),
            )
        else:
            try:
                guards.require(parents)
            except OSError:
                return False
            guards.seal()
        resolved_lock = lock.resolve()
        if resolved_lock.name != ".atomic-write-group.lock":
            return False
        lock_payload = _read_object(lock)
        if lock_payload is None:
            return False
        if lock_payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
            required_fields = {
                "schema_version", "marker_protocol", "owner_pid", "lock_type",
                "token", "journal_path", "transaction_id", "transaction_nonce",
                "authority_sha256",
            }
            if set(lock_payload) != required_fields or lock_payload.get("marker_protocol") != _AUTHORITY_PROTOCOL:
                return False
            if lock_payload.get("lock_type") != "writer" or not isinstance(lock_payload.get("token"), str):
                return False
            journal_payload = _read_object(journal_path)
            if journal_payload is None or journal_payload.get("schema_version") != _ATOMIC_SCHEMA_VERSION:
                return False
            try:
                authority = _authority_from_payload(journal_payload, journal_path)
            except QuarantineError:
                return False
            if lock_payload.get("authority_sha256") != authority.sha256:
                return False
            if lock_payload.get("transaction_nonce") != authority.transaction_nonce:
                return False
            # A live native guard cannot be bypassed.  Once the complete guard
            # set is held, stale PID/age metadata is irrelevant and the token
            # is reread before any marker removal.
            return _recover_journal(
                journal_path, held_guards=guards, deadline=deadline
            )
        lock_type = lock_payload.get("lock_type", "writer")
        lock_owner = lock_payload.get("owner_pid")
        if type(lock_owner) is not int or lock_owner <= 0:
            return False
        if lock_type == "reader":
            # v3 readers never publish markers; a legacy reader marker is an
            # unresolved blocker and is preserved for manual review.
            return False
        # Reader locks have no journal to recover.  Versioned markers are
        # reclaimable under their exact native guard set; legacy markers still
        # require a stale, dead owner and exact legacy evidence.
        if lock_type == "reader":
            token: str | None = None
            versioned = lock_payload.get("schema_version") == _GROUP_LOCK_SCHEMA_VERSION
            if versioned:
                if set(lock_payload) != {
                    "schema_version",
                    "owner_pid",
                    "lock_type",
                    "token",
                } or not isinstance(lock_payload.get("token"), str):
                    return False
                token = str(lock_payload["token"])
            elif set(lock_payload) != {"owner_pid", "lock_type"}:
                return False
            if not versioned and _pid_alive(lock_owner):
                return False
            removed = _remove_group_lock(resolved_lock, token, allow_legacy=token is None)
            return removed
        if lock_type != "writer":
            return False
        versioned = lock_payload.get("schema_version") == _GROUP_LOCK_SCHEMA_VERSION
        if versioned:
            if (
                set(lock_payload)
                != {"schema_version", "owner_pid", "lock_type", "token", "journal_path"}
                or not isinstance(lock_payload.get("token"), str)
                or not lock_payload["token"]
            ):
                return False
        elif set(lock_payload) not in (
            {"owner_pid", "journal_path"},
            {"owner_pid", "lock_type", "journal_path"},
        ):
            return False
        journal_value = lock_payload["journal_path"]
        if not isinstance(journal_value, str) or not Path(journal_value).is_absolute():
            return False
        journal_path = Path(journal_value).resolve()
        roots = _recovery_root_for_journal(journal_path)
        if roots is None:
            return False
        recovery_root, transaction_root = roots
        try:
            resolved_lock.parent.relative_to(recovery_root.resolve())
        except ValueError:
            return False
        if not versioned and _pid_alive(lock_owner):
            return False
        journal_payload = _read_object(journal_path)
        if journal_payload is None:
            return False
        if journal_payload.get("transaction_id") != transaction_root.name:
            return False
        lock_paths = journal_payload.get("lock_paths")
        if not isinstance(lock_paths, list):
            return False
        if _path_identity(resolved_lock) not in {
            _path_identity(Path(str(value)))
            for value in lock_paths
            if isinstance(value, str)
        }:
            return False
        journal_owner = journal_payload.get("owner_pid")
        if type(journal_owner) is not int or lock_owner != journal_owner:
            return False
        return _recover_journal(
            journal_path,
            held_guards=guards,
            deadline=deadline,
        )
    finally:
        if own_guards and guards is not None:
            guards.close(primary_error=sys.exc_info()[1])


def _acquire_group_locks(
    parents: tuple[Path, ...],
    journal_path: Path | None,
    timeout_seconds: float = 5.0,
    *,
    lock_type: str = "writer",
    held_guards: _GroupGuardLease | None = None,
    deadline: float | None = None,
    tokens_out: dict[Path, str] | None = None,
    tokens_in: dict[Path, str] | None = None,
) -> tuple[Path, ...]:
    if timeout_seconds < 0:
        raise ValueError("atomic lock timeout must be non-negative")
    if held_guards is None:
        raise RuntimeError("group marker publication requires a live guard lease")
    guards = held_guards
    if deadline is None:
        deadline = guards.deadline
    own_guards = False
    canonical_parents = _canonical_paths(parents)
    locks: list[Path] = []
    try:
        guards.require(canonical_parents)
        generated_tokens: dict[Path, str]
        if tokens_in is not None:
            expected_keys = {str(parent / ".atomic-write-group.lock") for parent in canonical_parents}
            generated_tokens = {Path(key).resolve(): token for key, token in tokens_in.items()}
            actual_keys = {str(key) for key in generated_tokens}
            if actual_keys != expected_keys or len(generated_tokens) != len(expected_keys):
                raise ValueError("atomic lock token map does not cover the complete guard set")
            if any(not isinstance(token, str) or not token for token in generated_tokens.values()):
                raise ValueError("atomic lock tokens must be non-empty strings")
            if len(set(generated_tokens.values())) != len(generated_tokens):
                raise ValueError("atomic lock tokens must be unique")
        else:
            generated_tokens = {
                (parent / ".atomic-write-group.lock").resolve(): uuid.uuid4().hex
                for parent in canonical_parents
            }
        for parent in canonical_parents:
            parent.mkdir(parents=True, exist_ok=True)
            lock = parent / ".atomic-write-group.lock"
            while True:
                descriptor: int | None = None
                try:
                    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    # On Windows an exclusive open against an existing lock
                    # is ordinary contention.
                    pass
                except PermissionError:
                    # A sharing-denied open is retryable only when the lock
                    # already exists.  Absent-lock ACL/filesystem failures
                    # must remain visible to the caller.
                    if not lock.exists():
                        raise
                    pass
                else:
                    token = generated_tokens[lock.resolve()]
                    marker_payload: dict[str, object] = {
                        "schema_version": _GROUP_LOCK_SCHEMA_VERSION,
                        "owner_pid": os.getpid(),
                        "lock_type": lock_type,
                        "token": token,
                    }
                    if journal_path is not None:
                        marker_payload["journal_path"] = str(journal_path.resolve())
                        journal_payload = _read_object(journal_path)
                        if journal_payload is not None and journal_payload.get("schema_version") == _ATOMIC_SCHEMA_VERSION:
                            marker_payload.update(
                                {
                                    "schema_version": _ATOMIC_SCHEMA_VERSION,
                                    "marker_protocol": _AUTHORITY_PROTOCOL,
                                    "transaction_id": journal_payload.get("transaction_id"),
                                    "transaction_nonce": journal_payload.get("transaction_nonce"),
                                    "authority_sha256": journal_payload.get("authority_sha256"),
                                }
                            )
                    payload = json.dumps(marker_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    try:
                        written = os.write(descriptor, payload)
                        if written != len(payload):
                            raise OSError("atomic write lock ownership write was incomplete")
                    except BaseException:
                        # The lock was created by this process.  Close the
                        # descriptor before removing the partial ownership
                        # evidence and propagate the original write failure.
                        try:
                            os.close(descriptor)
                        finally:
                            descriptor = None
                            lock.unlink(missing_ok=True)
                        raise
                    os.close(descriptor)
                    descriptor = None
                    locks.append(lock)
                    if tokens_out is not None:
                        tokens_out[lock.resolve()] = token
                    break
                if _recover_lock(lock, held_guards=guards, deadline=deadline):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for atomic write lock: {lock}")
                time.sleep(0.025)
        return tuple(locks)
    except BaseException as error:
        cleanup_error: BaseException | None = None
        for lock in reversed(locks):
            cleanup_token = generated_tokens.get(lock.resolve())
            try:
                removed = _remove_group_lock(
                    lock,
                    cleanup_token,
                    allow_legacy=cleanup_token is None,
                )
                if not removed:
                    raise OSError(f"atomic lock ownership changed during cleanup: {lock}")
            except BaseException as cleanup_failure:
                cleanup_error = cleanup_error or cleanup_failure
        if cleanup_error is not None:
            raise error from cleanup_error
        raise
    finally:
        # The caller owns the guard capability and must keep it through
        # transaction cleanup; this function never returns a bare marker lease.
        del own_guards


def wait_for_atomic_group(path: Path, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    parent = Path(path).resolve().parent
    lock = parent / ".atomic-write-group.lock"
    guards = _preflight_group_guards((parent,), deadline=deadline)
    try:
        while lock.exists():
            if _recover_lock(lock, held_guards=guards, deadline=deadline):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for atomic write transaction: {lock}")
            time.sleep(0.025)
    finally:
        guards.close(primary_error=sys.exc_info()[1])



def read_atomic_group(
    paths: Iterable[Path], *, timeout_seconds: float = 5.0
) -> tuple[bytes, ...]:
    """Read an atomic group while holding the native guard closure directly."""
    path_tuple = tuple(Path(path).resolve() for path in paths)
    if not path_tuple:
        return ()
    if len({_path_identity(path) for path in path_tuple}) != len(path_tuple):
        raise ValueError("atomic group reader paths must be unique")
    parents = _canonical_paths(path.parent for path in path_tuple)
    common_root = Path(os.path.commonpath([str(parent) for parent in parents])).resolve()
    lock_parents = _canonical_paths((*parents, common_root))
    deadline = Deadline.after(timeout_seconds)
    guards = _preflight_group_guards(lock_parents, deadline=deadline.value)
    try:
        return tuple(path.read_bytes() for path in path_tuple)
    finally:
        guards.close(primary_error=sys.exc_info()[1])

def atomic_write_group(
    requests: Iterable[AtomicWriteRequest],
    *,
    lifecycle_hook: Callable[[str, Path], None] | None = None,
    precondition: Callable[[], None] | None = None,
) -> tuple[AtomicWriteResult, ...]:
    """Publish a complete destination-authority-v1 group under native guards."""
    request_tuple = tuple(requests)
    if not request_tuple:
        return ()
    destinations = _canonical_paths(Path(request.destination).resolve() for request in request_tuple)
    if len(destinations) != len(request_tuple):
        raise ValueError("atomic write group destinations must be unique")
    by_destination = {Path(request.destination).resolve(): request for request in request_tuple}
    parents = _canonical_paths(path.parent for path in destinations)
    common_root = Path(os.path.commonpath([str(parent) for parent in parents])).resolve()
    lock_parents = _canonical_paths((*parents, common_root))
    deadline = Deadline.after(5.0)
    transaction_id = uuid.uuid4().hex
    nonce = uuid.uuid4().hex
    transaction_root = common_root / ".atomic-transactions" / transaction_id
    journal_path = transaction_root / "journal.json"
    authority_path = transaction_root / "authority.json"
    created_at = datetime.now(timezone.utc).isoformat()
    marker_paths = tuple(str((parent / ".atomic-write-group.lock").resolve()) for parent in lock_parents)
    marker_tokens = {path: uuid.uuid4().hex for path in marker_paths}
    staged: dict[Path, Path] = {}
    previous: dict[Path, bytes | None] = {}
    entries: list[dict[str, object]] = []
    guards: _GroupGuardLease | None = None
    interrupted = False
    recovery_pending = False
    journal_payload: dict[str, object] | None = None

    def hook(state: str) -> None:
        if lifecycle_hook is not None:
            lifecycle_hook(state, journal_path)

    try:
        hook("memory")
        guards = _preflight_group_guards(lock_parents, deadline=deadline.value)
        guards.require(lock_parents)
        guards.seal()
        transaction_root.mkdir(parents=True, exist_ok=False)
        authority = _publish_authority(
            authority_path,
            transaction_id=transaction_id,
            nonce=nonce,
            destinations=destinations,
            created_at=created_at,
        )
        journal_payload = {
            "schema_version": _ATOMIC_SCHEMA_VERSION,
            "protocol": _AUTHORITY_PROTOCOL,
            "transaction_id": transaction_id,
            "transaction_nonce": nonce,
            "authority_path": str(authority.path),
            "authority_sha256": authority.sha256,
            "authority_fingerprint": authority.fingerprint,
            "owner_pid": os.getpid(),
            "state": "authority_published",
            "status": "authority_published",
            "affected_dataset_ids": [str(path) for path in destinations],
            "entries": entries,
            "staged_paths": [],
            "final_paths": [],
            "lock_paths": [],
            "marker_paths": list(marker_paths),
            "marker_tokens": marker_tokens,
            "expected_checksums": {},
            "created_at": created_at,
            "started_at": created_at,
            "updated_at": created_at,
            "committed_at": None,
            "recovery_instructions": ["Recover only from immutable destination-authority-v1 and complete evidence."],
        }
        _write_journal(journal_path, journal_payload)
        hook("authority_published")
        journal_payload["state"] = "markers_publishing"
        journal_payload["status"] = "markers_publishing"
        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_journal(journal_path, journal_payload)
        hook("markers_publishing")
        locks = _acquire_group_locks(
            lock_parents,
            journal_path,
            held_guards=guards,
            deadline=deadline.value,
            tokens_in={Path(key).resolve(): value for key, value in marker_tokens.items()},
        )
        if tuple(str(path.resolve()) for path in locks) != marker_paths:
            raise QuarantineError("marker publication did not cover complete authority closure")
        journal_payload["state"] = "armed"
        journal_payload["status"] = "armed"
        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_journal(journal_path, journal_payload)
        hook("armed")
        if precondition is not None:
            precondition()
        journal_payload["state"] = "preparing"
        journal_payload["status"] = "preparing"
        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_journal(journal_path, journal_payload)
        hook("preparing")
        for index, destination in enumerate(destinations):
            request = by_destination[destination]
            original = destination.read_bytes() if destination.is_file() else None
            previous[destination] = original
            backup_path: Path | None = None
            if original is not None:
                backup_path = transaction_root / f"backup-{index}.bin"
                with backup_path.open("wb") as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
            staged_path = _stage_request(request, validate=False)
            staged[destination] = staged_path
            expected = hashlib.sha256(request.payload).hexdigest()
            entries.append({
                "destination": str(destination),
                "backup_path": str(backup_path.resolve()) if backup_path else None,
                "previous_sha256": hashlib.sha256(original).hexdigest() if original is not None else None,
                "staged_path": str(staged_path.resolve()),
                "expected_sha256": expected,
            })
            journal_payload["staged_paths"] = [str(path.resolve()) for path in staged.values()]
            journal_payload["final_paths"] = [str(entry["destination"]) for entry in entries]
            expected_checksums = journal_payload["expected_checksums"]
            assert isinstance(expected_checksums, dict)
            expected_checksums[str(destination)] = expected
            journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_journal(journal_path, journal_payload)
        assert journal_payload is not None
        expected_checksums_final = journal_payload.get("expected_checksums")
        if not isinstance(expected_checksums_final, dict):
            raise QuarantineError("schema3 expected checksum evidence is missing")
        for destination in destinations:
            request = by_destination[destination]
            request.validator(staged[destination])
            expected = str(expected_checksums_final[str(destination)])
            if sha256_file(staged[destination]) != expected:
                raise OSError(f"staged payload checksum mismatch: {staged[destination]}")
        journal_payload["state"] = "prepared"
        journal_payload["status"] = "prepared"
        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_journal(journal_path, journal_payload)
        hook("prepared")
        journal_payload["state"] = "committing"
        journal_payload["status"] = "committing"
        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_journal(journal_path, journal_payload)
        hook("committing")
        for destination in destinations:
            staged[destination].replace(destination)
        journal_payload["state"] = "committed"
        journal_payload["status"] = "committed"
        journal_payload["committed_at"] = datetime.now(timezone.utc).isoformat()
        journal_payload["updated_at"] = journal_payload["committed_at"]
        _write_journal(journal_path, journal_payload)
        hook("committed")
        journal_payload["state"] = "cleaned"
        journal_payload["status"] = "cleaned"
        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_journal(journal_path, journal_payload)
        hook("cleaned")
        _cleanup_schema3_transaction(journal_payload, journal_path)
        return tuple(
            AtomicWriteResult(
                destination=destination,
                sha256=hashlib.sha256(by_destination[destination].payload).hexdigest(),
                bytes_written=len(by_destination[destination].payload),
                replaced_existing=previous[destination] is not None,
            )
            for destination in destinations
        )
    except AtomicWriteInterrupted:
        interrupted = True
        raise
    except Exception:
        if journal_path.is_file() and guards is not None:
            try:
                recovered = _recover_journal(journal_path, force=True, held_guards=guards, deadline=deadline.value)
            except Exception as recovery_error:
                recovery_pending = True
                _mark_recovery_required(journal_path, recovery_error)
                raise
            if not recovered:
                recovery_pending = True
                _mark_recovery_required(journal_path, "rollback could not be proven from immutable authority evidence")
        raise
    finally:
        primary_error = sys.exc_info()[1]
        if not interrupted and not recovery_pending and journal_path.is_file() and journal_payload is not None:
            try:
                _cleanup_schema3_transaction(journal_payload, journal_path)
            except BaseException as cleanup_error:
                if primary_error is not None:
                    raise primary_error from cleanup_error
                raise
        if guards is not None:
            try:
                guards.close(primary_error=primary_error)
            except BaseException as release_error:
                if primary_error is not None:
                    raise primary_error from release_error
                raise

def atomic_write_json(destination: Path, payload: object) -> AtomicWriteResult:
    encoded = (json.dumps(payload, indent=2, default=str) + "\n").encode("utf-8")

    def validate(path: Path) -> None:
        json.loads(path.read_text(encoding="utf-8"))

    return atomic_write_bytes(destination, encoded, validate)


def parquet_payload(frame: object) -> bytes:
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)  # type: ignore[attr-defined]
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

        def validate_restore(path: Path, expected: str = entry.sha256) -> None:
            if sha256_file(path) != expected:
                raise OSError(f"restore checksum mismatch: {path}")

        for attempt in range(3):
            try:
                atomic_write_bytes(entry.source_path, payload, validate_restore)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
