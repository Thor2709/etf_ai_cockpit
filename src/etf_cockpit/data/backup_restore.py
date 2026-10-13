from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group
from etf_cockpit.data.bulk_cache import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ARCHIVE_MEMBERS,
    DEFAULT_MAX_COMPRESSION_RATIO,
    ArchiveValidationError,
    _validate_archive_members,
)
from etf_cockpit.core.settings_bundle import SETTINGS_SCHEMA_VERSION, SettingsError, load_settings_bundle


# Named schemas are intentionally allow-listed.  A future-looking label such
# as ``cockpit.v999`` must not be treated as compatible merely because it has a
# version-shaped suffix; it may carry fields this runtime cannot interpret.
# The canonical settings bundle schema comes from the settings contract.
_SUPPORTED_NAMED_SCHEMA_VERSIONS = {"cockpit.v1", SETTINGS_SCHEMA_VERSION}


@dataclass(frozen=True)
class BackupManifest:
    archive: Path
    checksums: dict[str, str]
    schema_version: int = 1
    manifest_checksum: str = ""
    excluded: tuple[str, ...] = ()
    execution_allowed: bool = False
    encrypted: bool = False
    incremental: bool = False
    base_manifest_checksum: str | None = None
    # Archive payload checksums stay sparse; chained deltas need the full inventory.
    inventory_checksums: dict[str, str] | None = None


@dataclass(frozen=True)
class RestorePreview:
    archive: Path
    valid: bool
    entries: tuple[str, ...]
    errors: tuple[str, ...]
    checksums: dict[str, str] | None = None
    manifest_checksum: str = ""
    excluded: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoreResult:
    destination: Path
    restored: int
    ok: bool = True
    error: str = ""
    execution_allowed: bool = False


@dataclass(frozen=True)
class RecoveryDrillResult:
    archive: Path
    restored_files: int
    ok: bool
    errors: tuple[str, ...] = ()


class BackupError(RuntimeError):
    """Raised when a backup cannot be created without losing or mixing files."""


class EncryptionUnavailable(RuntimeError):
    """Raised when the approved cryptography dependency is unavailable."""


class BackupKeyError(ValueError):
    """Raised when a user-managed recovery key does not meet the minimum policy."""


_ENCRYPTED_MAGIC = b"ETFCOCKPIT-BACKUP-ENC-1\n"
_PBKDF2_ITERATIONS = 390_000
_MIN_RECOVERY_KEY_BYTES = 16


def create_backup(paths: list[Path], destination: Path, *, include_transient: bool = False) -> BackupManifest:
    checksums, excluded, payloads = _collect_payloads(paths, include_transient=include_transient)
    manifest_payload = _manifest_payload(checksums, excluded)
    manifest_checksum = hashlib.sha256(manifest_payload).hexdigest()
    _write_backup_archive(destination, _zip_payload(payloads, manifest_payload))
    return BackupManifest(Path(destination), checksums, 1, manifest_checksum, tuple(excluded), False)


def create_incremental_backup(
    paths: list[Path],
    destination: Path,
    base_manifest: BackupManifest,
    *,
    include_transient: bool = False,
) -> BackupManifest:
    """Archive changed files and return the complete policy-approved current inventory."""

    seen: set[str] = set()
    previous_inventory = base_manifest.inventory_checksums if base_manifest.inventory_checksums is not None else base_manifest.checksums
    checksums, excluded, payloads = _collect_payloads(
        paths,
        include_transient=include_transient,
        previous_checksums=previous_inventory,
        seen=seen,
    )
    manifest_payload = _manifest_payload(
        checksums,
        excluded,
        schema_version=2,
        incremental=True,
        base_manifest_checksum=base_manifest.manifest_checksum,
        deleted=sorted(set(previous_inventory) - seen),
    )
    manifest_checksum = hashlib.sha256(manifest_payload).hexdigest()
    _write_backup_archive(destination, _zip_payload(payloads, manifest_payload))
    return BackupManifest(
        Path(destination),
        checksums,
        2,
        manifest_checksum,
        tuple(excluded),
        False,
        False,
        True,
        base_manifest.manifest_checksum,
        {**{name: value for name, value in previous_inventory.items() if name in seen}, **checksums},
    )


def create_encrypted_backup(
    paths: list[Path],
    destination: Path,
    recovery_key: str | bytes,
    *,
    include_transient: bool = False,
) -> BackupManifest:
    """Create a Fernet-encrypted backup using a user-managed recovery key."""

    checksums, excluded, payloads = _collect_payloads(paths, include_transient=include_transient)
    manifest_payload = _manifest_payload(checksums, excluded, schema_version=2)
    manifest_checksum = hashlib.sha256(manifest_payload).hexdigest()
    salt = os.urandom(16)
    fernet = _fernet_from_key(recovery_key, salt)
    header = {
        "format": 1,
        "algorithm": "Fernet",
        "kdf": "PBKDF2HMAC-SHA256",
        "iterations": _PBKDF2_ITERATIONS,
        "salt": _b64(salt),
    }
    encrypted = _ENCRYPTED_MAGIC + _json_line(header) + fernet.encrypt(_zip_payload(payloads, manifest_payload))
    _write_backup_archive(destination, encrypted)
    return BackupManifest(
        Path(destination),
        checksums,
        2,
        manifest_checksum,
        tuple(excluded),
        False,
        True,
    )


def validate_restore(
    archive_path: Path,
    *,
    destination: Path | None = None,
    check_consistency: bool = True,
) -> RestorePreview:
    errors: list[str] = []
    entries: list[str] = []
    checksums: dict[str, str] = {}
    manifest_checksum = ""
    excluded: tuple[str, ...] = ()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = [info.filename.replace("\\", "/") for info in archive.infolist()]
            if len(names) != len(set(names)):
                errors.append("duplicate_entry")
            limit_error = _archive_limit_error(archive.infolist())
            if limit_error:
                errors.append(limit_error)
            for name in names:
                if name != "manifest.json":
                    if _unsafe(name):
                        errors.append(f"unsafe_path:{name}")
                    elif not _approved_payload_root(name):
                        errors.append(f"unapproved_path:{name}")
                    entries.append(name)
            if limit_error:
                pass  # nothing is read from an archive that exceeds the member/size/ratio limits
            elif "manifest.json" not in names:
                errors.append("manifest_missing")
            else:
                manifest_bytes = archive.read("manifest.json")
                manifest_checksum = hashlib.sha256(manifest_bytes).hexdigest()
                payload = json.loads(manifest_bytes)
                if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2} or not isinstance(payload.get("checksums"), dict):
                    errors.append("manifest_schema_invalid")
                else:
                    checksums = {str(name): str(value) for name, value in payload["checksums"].items()}
                    excluded = tuple(str(name) for name in payload.get("excluded", ()) if str(name))
                    for name in payload.get("deleted", ()):
                        if _unsafe(str(name)) or not _approved_payload_root(str(name)):
                            errors.append(f"unsafe_path:{name}")
                    if set(checksums) != set(entries):
                        errors.append("manifest_entries_mismatch")
                    for name, expected in checksums.items():
                        if _unsafe(name):
                            errors.append(f"unsafe_path:{name}")
                            continue
                        if not _approved_payload_root(name):
                            errors.append(f"unapproved_path:{name}")
                            continue
                        try:
                            actual = hashlib.sha256(archive.read(name)).hexdigest()
                        except KeyError:
                            errors.append(f"checksum_missing:{name}")
                            continue
                        if actual != expected:
                            errors.append(f"checksum_mismatch:{name}")
                        schema_error = _validate_payload_schema(name, archive.read(name))
                        if schema_error:
                            errors.append(schema_error)
            if not limit_error and check_consistency and any(name.casefold().startswith("configs/") for name in entries):
                consistency_error = _validate_config_consistency(
                    archive,
                    entries,
                    destination=destination,
                )
                if consistency_error:
                    errors.append(consistency_error)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        errors.append(f"archive_invalid:{type(exc).__name__}")
    return RestorePreview(Path(archive_path), not errors, tuple(sorted(set(entries))), tuple(errors), checksums, manifest_checksum, excluded)


_LIMIT_CHECK_ROOT = Path(tempfile.gettempdir()).resolve()


def _archive_limit_error(members: list[zipfile.ZipInfo]) -> str:
    """Member-count, total-size and ratio limits shared with bulk_cache (unsafe names are reported separately)."""

    safe = [member for member in members if not _unsafe(member.filename.replace("\\", "/"))]
    try:
        _validate_archive_members(
            safe,
            _LIMIT_CHECK_ROOT,
            DEFAULT_MAX_ARCHIVE_MEMBERS,
            DEFAULT_MAX_ARCHIVE_BYTES,
            DEFAULT_MAX_COMPRESSION_RATIO,
            zip_mode=True,
        )
    except ArchiveValidationError as exc:
        return f"archive_limits_exceeded:{exc}"
    return ""


def commit_restore(preview: RestorePreview, destination: Path) -> RestoreResult:
    destination = Path(destination)
    if not preview.valid:
        return RestoreResult(destination, 0, False, "; ".join(preview.errors) or "Restore preview is invalid")
    current = validate_restore(preview.archive, destination=destination)
    if not current.valid or current.manifest_checksum != preview.manifest_checksum or current.checksums != preview.checksums:
        return RestoreResult(destination, 0, False, "restore_preview_stale_or_archive_changed")
    try:
        destination_root = destination.resolve()
        payloads: dict[str, bytes] = {}
        targets: dict[str, Path] = {}
        with zipfile.ZipFile(preview.archive) as archive:
            for name in preview.entries:
                targets[name] = _restore_target(destination_root, name)
                payloads[name] = archive.read(name)
        requests = [
            AtomicWriteRequest(targets[name], payloads[name], _checksum_validator(preview.checksums[name], name))
            for name in preview.entries
        ]

        def precondition() -> None:
            consistency_error = _validate_config_payloads(payloads, destination_root, temp_parent=destination_root.parent)
            if consistency_error:
                raise ValueError(consistency_error)

        atomic_write_group(requests, precondition=precondition)
    except Exception as exc:
        return RestoreResult(destination, 0, False, f"restore_failed:{type(exc).__name__}:{exc}")
    return RestoreResult(destination, len(requests), True)


def commit_incremental_restore(previews: list[RestorePreview] | tuple[RestorePreview, ...], destination: Path) -> RestoreResult:
    """Apply a validated base archive followed by validated incremental archives."""

    if not previews:
        return RestoreResult(Path(destination), 0, False, "no_restore_archives")
    try:
        destination_root = Path(destination).resolve()
        snapshot: dict[str, bytes] = {}
        composed: dict[str, bytes] = {}
        checksums: dict[str, str] = {}
        targets: dict[str, Path] = {}
        previous_manifest_checksum: str | None = None
        touched_names: list[str] = []
        deleted_names: set[str] = set()
        for preview in previews:
            current = validate_restore(preview.archive, check_consistency=False)
            if not current.valid or current.manifest_checksum != preview.manifest_checksum or current.checksums != preview.checksums:
                return RestoreResult(Path(destination), 0, False, "restore_preview_stale_or_archive_changed")
            with zipfile.ZipFile(preview.archive) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    return RestoreResult(Path(destination), 0, False, "restore_manifest_invalid")
                linkage = manifest.get("base_manifest_checksum")
                if linkage is not None and (
                    manifest.get("incremental") is not True or linkage != previous_manifest_checksum
                ):
                    return RestoreResult(Path(destination), 0, False, "incremental_base_manifest_mismatch")
                for name in manifest.get("deleted", ()):
                    name = str(name)
                    targets.setdefault(name, _restore_target(destination_root, name))
                    composed.pop(name, None)
                    checksums.pop(name, None)
                    deleted_names.add(name)
                for name in preview.entries:
                    payload = archive.read(name)
                    deleted_names.discard(name)
                    if name not in snapshot:
                        target = _restore_target(destination_root, name)
                        targets[name] = target
                        snapshot[name] = target.read_bytes() if target.is_file() else b""
                        touched_names.append(name)
                    if name not in composed:
                        composed[name] = snapshot[name]
                    composed[name] = payload
                    checksums[name] = preview.checksums[name]
                previous_manifest_checksum = preview.manifest_checksum

        payloads = {name: composed[name] for name in touched_names if name in composed}
        requests = [
            AtomicWriteRequest(targets[name], payloads[name], _checksum_validator(checksums[name], name))
            for name in touched_names
            if name in payloads
        ]

        def precondition() -> None:
            consistency_error = _validate_config_payloads(payloads, destination_root, temp_parent=destination_root.parent)
            if consistency_error:
                raise ValueError(consistency_error)

        # Delete before publishing replacements, retaining the original bytes
        # until the write group commits. Its own rollback covers replacements.
        deletion_backups = {
            name: targets[name].read_bytes()
            for name in sorted(deleted_names)
            if targets[name].is_file()
        }
        try:
            precondition()
            for name in sorted(deleted_names):
                targets[name].unlink(missing_ok=True)
            atomic_write_group(requests, precondition=precondition)
        except Exception:
            atomic_write_group([
                AtomicWriteRequest(targets[name], payload, _checksum_validator(hashlib.sha256(payload).hexdigest(), name))
                for name, payload in deletion_backups.items()
            ])
            raise
    except Exception as exc:
        return RestoreResult(Path(destination), 0, False, f"restore_failed:{type(exc).__name__}:{exc}")
    return RestoreResult(Path(destination), len(requests), True)


def validate_encrypted_restore(
    archive_path: Path,
    recovery_key: str | bytes,
    *,
    destination: Path | None = None,
) -> RestorePreview:
    """Decrypt and validate an encrypted archive without writing restored data."""

    try:
        plaintext = _decrypt_backup(Path(archive_path), recovery_key)
    except (BackupKeyError, EncryptionUnavailable, OSError, ValueError, TypeError) as exc:
        return RestorePreview(Path(archive_path), False, (), (f"decryption_failed:{type(exc).__name__}",))
    return _preview_from_plaintext(Path(archive_path), plaintext, destination=destination)


def restore_encrypted_backup(archive_path: Path, destination: Path, recovery_key: str | bytes) -> RestoreResult:
    preview = validate_encrypted_restore(archive_path, recovery_key, destination=destination)
    if not preview.valid:
        return RestoreResult(Path(destination), 0, False, "; ".join(preview.errors))
    try:
        plaintext = _decrypt_backup(Path(archive_path), recovery_key)
        with tempfile.NamedTemporaryFile(suffix=".backup", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(plaintext)
        try:
            plain_preview = validate_restore(temporary, destination=destination)
            return commit_restore(plain_preview, destination)
        finally:
            temporary.unlink(missing_ok=True)
    except (BackupKeyError, EncryptionUnavailable, OSError, ValueError, TypeError) as exc:
        return RestoreResult(Path(destination), 0, False, f"decryption_failed:{type(exc).__name__}")


def apply_backup_retention(directory: Path, *, keep: int = 5, pattern: str = "*.backup") -> tuple[Path, ...]:
    if keep < 1:
        raise ValueError("backup retention must keep at least one archive")
    candidates = sorted(
        (path for path in Path(directory).glob(pattern) if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed: list[Path] = []
    for path in candidates[keep:]:
        path.unlink()
        removed.append(path)
    return tuple(removed)


def run_disaster_recovery_drill(
    paths: list[Path],
    work_dir: Path,
    *,
    recovery_key: str | bytes | None = None,
) -> RecoveryDrillResult:
    """Create, validate and restore a local backup as an auditable recovery drill."""

    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "disaster-recovery-drill.backup"
    destination = root / "restored"
    try:
        manifest = (
            create_encrypted_backup(paths, archive, recovery_key)
            if recovery_key is not None
            else create_backup(paths, archive)
        )
        preview = (
            validate_encrypted_restore(archive, recovery_key, destination=destination)
            if manifest.encrypted and recovery_key is not None
            else validate_restore(archive)
        )
        if not preview.valid:
            return RecoveryDrillResult(archive, 0, False, preview.errors)
        result = (
            restore_encrypted_backup(archive, destination, recovery_key)
            if manifest.encrypted and recovery_key is not None
            else commit_restore(preview, destination)
        )
        return RecoveryDrillResult(archive, result.restored, result.ok, (result.error,) if result.error else ())
    except (BackupKeyError, EncryptionUnavailable, OSError, ValueError, TypeError) as exc:
        return RecoveryDrillResult(archive, 0, False, (f"drill_failed:{type(exc).__name__}:{exc}",))


def _collect_payloads(
    paths: list[Path],
    *,
    include_transient: bool,
    previous_checksums: dict[str, str] | None = None,
    seen: set[str] | None = None,
) -> tuple[dict[str, str], list[str], dict[str, bytes]]:
    found, skipped = _iter_files(paths)
    files = sorted(found, key=lambda item: str(item))
    sqlite_mains = {
        path.resolve()
        for path in files
        if path.is_file() and path.read_bytes().startswith(b"SQLite format 3\x00")
    }
    checksums: dict[str, str] = {}
    excluded: list[str] = [_archive_name(path) for path in skipped]
    payloads: dict[str, bytes] = {}
    origins: dict[str, Path] = {}
    for path in files:
        if path.name.endswith(("-wal", "-shm", "-journal")) and any(
            path.resolve() == Path(f"{database}{suffix}").resolve()
            for database in sqlite_mains
            for suffix in ("-wal", "-shm", "-journal")
        ):
            continue
        relative = _archive_name(path)
        if origins.setdefault(relative, path.resolve()) != path.resolve():
            raise BackupError(f"archive_name_collision:{relative}")
        data = path.read_bytes()
        if data.startswith(b"SQLite format 3\x00"):
            data = _sqlite_snapshot(path)
        if _secret_path(path) or _secret_content(data, path) or (not include_transient and _transient_path(path)):
            excluded.append(relative)
            continue
        if seen is not None:
            seen.add(relative)
        checksum = hashlib.sha256(data).hexdigest()
        if previous_checksums is not None and previous_checksums.get(relative) == checksum:
            continue
        checksums[relative] = checksum
        payloads[relative] = data
    return checksums, excluded, payloads


def _sqlite_snapshot(path: Path) -> bytes:
    source = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    snapshot = sqlite3.connect(":memory:")
    try:
        source.backup(snapshot)
        return snapshot.serialize()
    finally:
        snapshot.close()
        source.close()


def _zip_payload(payloads: dict[str, bytes], manifest_payload: bytes) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(name, payloads[name])
        archive.writestr("manifest.json", manifest_payload)
    return buffer.getvalue()


def _write_backup_archive(destination: Path, payload: bytes) -> None:
    destination = Path(destination)
    atomic_write_bytes(destination, payload, lambda path: None)


def _json_line(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _b64(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64_decode(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value.encode("ascii"))


def _fernet_from_key(recovery_key: str | bytes, salt: bytes):
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError as exc:
        raise EncryptionUnavailable("cryptography is required for encrypted backups") from exc
    key = recovery_key.encode("utf-8") if isinstance(recovery_key, str) else bytes(recovery_key)
    if len(key) < _MIN_RECOVERY_KEY_BYTES:
        raise BackupKeyError(f"recovery key must contain at least {_MIN_RECOVERY_KEY_BYTES} bytes")
    derivation = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_PBKDF2_ITERATIONS)
    return Fernet(__import__("base64").urlsafe_b64encode(derivation.derive(key)))


def _decrypt_backup(archive_path: Path, recovery_key: str | bytes) -> bytes:
    raw = Path(archive_path).read_bytes()
    if not raw.startswith(_ENCRYPTED_MAGIC):
        raise ValueError("encrypted backup header is missing")
    try:
        header_bytes, token = raw[len(_ENCRYPTED_MAGIC) :].split(b"\n", 1)
        header = json.loads(header_bytes)
        if header.get("format") != 1 or header.get("algorithm") != "Fernet" or header.get("kdf") != "PBKDF2HMAC-SHA256":
            raise ValueError("unsupported encrypted backup format")
        if int(header.get("iterations", 0)) != _PBKDF2_ITERATIONS:
            raise ValueError("unsupported encrypted backup KDF parameters")
        salt = _b64_decode(str(header["salt"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("encrypted backup header is invalid") from exc
    fernet = _fernet_from_key(recovery_key, salt)
    try:
        return fernet.decrypt(token)
    except Exception as exc:
        raise ValueError("encrypted backup authentication failed") from exc


def _preview_from_plaintext(
    display_path: Path,
    plaintext: bytes,
    *,
    destination: Path | None = None,
) -> RestorePreview:
    with tempfile.NamedTemporaryFile(suffix=".backup", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(plaintext)
    try:
        preview = validate_restore(temporary, destination=destination)
        return RestorePreview(display_path, preview.valid, preview.entries, preview.errors, preview.checksums, preview.manifest_checksum, preview.excluded)
    finally:
        temporary.unlink(missing_ok=True)


def _iter_files(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """Return (files to archive, links/reparse points or items resolving outside their root)."""

    found: list[Path] = []
    skipped: list[Path] = []

    def inside(item: Path, root: Path) -> bool:
        return not (item.is_symlink() or _is_reparse_point(item) or os.path.isjunction(item)) and item.resolve().is_relative_to(root)

    for path in paths:
        source = Path(path)
        if source.is_symlink() or os.path.isjunction(source) or _is_reparse_point(source):
            skipped.append(source)
        elif source.is_dir():
            root = source.resolve()
            for item in source.rglob("*"):
                if item.is_symlink() or os.path.isjunction(item) or _is_reparse_point(item) or item.is_file():
                    (found if inside(item, root) and item.is_file() else skipped).append(item)
        elif source.is_file() or source.is_symlink():
            (found if inside(source, source.resolve().parent) and source.is_file() else skipped).append(source)
    return found, skipped


def _manifest_payload(
    checksums: dict[str, str],
    excluded: list[str] | tuple[str, ...] = (),
    *,
    schema_version: int = 1,
    incremental: bool = False,
    base_manifest_checksum: str | None = None,
    deleted: list[str] | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "checksums": checksums,
        "excluded": sorted(set(excluded)),
    }
    if incremental:
        payload["incremental"] = True
        payload["base_manifest_checksum"] = base_manifest_checksum
        payload["deleted"] = sorted(set(deleted or ()))
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _unsafe(name: str) -> bool:
    path = PurePosixPath(name)
    # A colon anywhere is refused: drive-relative components and NTFS alternate data streams.
    return not name or path.is_absolute() or ".." in path.parts or ":" in name


def _approved_payload_root(name: str) -> bool:
    """Allow only user data/configuration and explicit release metadata."""

    normalised = str(name).replace("\\", "/").strip("/").casefold()
    if not normalised or normalised == "manifest.json":
        return normalised == "manifest.json"
    if normalised.startswith(("data/", "configs/", "version/", "changelog/")):
        return True
    return normalised in {"pyproject.toml", "version", "version.txt", "version.json", "changelog.md", "changes.md"}


def _secret_path(path: Path) -> bool:
    lowered = path.name.lower()
    return lowered in {".env", ".env.local", "secrets.json", "credentials.json"} or "secret" in lowered or "credential" in lowered


_SECRET_KEY_NAMES = {"apikey", "accesstoken", "clientsecret", "secretkey", "password", "privatekey"}
_SECRET_CONTENT = re.compile(
    r"(?im)[\"']?\s*(?:api[_-]?key|access[_-]?token|client[_-]?secret|secret[_-]?key|password|private[_-]?key)\s*[\"']?\s*[:=]\s*([^\r\n,}]+)"
)


def _normalise_secret_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _structured_secret_value(value: object) -> bool:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return False
    return not (isinstance(value, str) and not value.strip())


def _contains_structured_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _normalise_secret_key(key) in _SECRET_KEY_NAMES and _structured_secret_value(child):
                return True
            if _contains_structured_secret(child):
                return True
    elif isinstance(value, (list, tuple, set)):
        return any(_contains_structured_secret(child) for child in value)
    return False


def _secret_content(data: bytes, path: Path | None = None) -> bool:
    text = data.decode("utf-8", errors="ignore")
    suffix = Path(path).suffix.casefold() if path is not None else ""
    if suffix in {".json", ".yaml", ".yml"}:
        try:
            if suffix == ".json":
                payload = json.loads(text)
            else:
                import yaml  # type: ignore[import-not-found]

                payload = yaml.safe_load(text)
        except Exception:
            payload = None
        else:
            return bool(_contains_structured_secret(payload)) or ("-----BEGIN" in text and "PRIVATE KEY-----" in text)
    for match in _SECRET_CONTENT.finditer(text):
        value = match.group(1).strip().strip("'\"")
        if value and value.casefold() not in {"null", "none"}:
            return True
    return "-----BEGIN" in text and "PRIVATE KEY-----" in text


def _validate_payload_schema(name: str, data: bytes) -> str | None:
    lowered = name.lower()
    if not lowered.startswith(("configs/", "data/")) or Path(lowered).suffix not in {".json", ".yaml", ".yml"}:
        return None
    try:
        if lowered.endswith(".json"):
            payload = json.loads(data)
        else:
            try:
                import yaml  # type: ignore[import-not-found]

                payload = yaml.safe_load(data.decode("utf-8"))
            except ImportError:
                return None
    except Exception:
        return f"payload_schema_invalid:{name}"
    if not isinstance(payload, dict):
        return None
    for key in ("schema_version", "programme_schema_version"):
        if key not in payload:
            continue
        value = payload[key]
        try:
            numeric = float(str(value).strip())
        except (TypeError, ValueError):
            named = str(value).strip()
            if named in _SUPPORTED_NAMED_SCHEMA_VERSIONS:
                continue
            return f"unsupported_schema_version:{name}:{value}"
        if not 0 < numeric <= 4:
            return f"unsupported_schema_version:{name}:{value}"
    return None


def _checksum_validator(expected: str, name: str):
    def validate(path: Path) -> None:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"restore checksum mismatch:{name}")

    return validate


def _restore_target(destination_root: Path, name: str) -> Path:
    root = Path(destination_root).resolve()
    candidate = root / Path(name)
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"restore target escapes destination root: {name}") from exc
    current = root
    for component in candidate.relative_to(root).parts:
        current /= component
        if os.path.lexists(current) and (os.path.islink(current) or _is_reparse_point(current)):
            raise ValueError(f"restore target crosses symlink or reparse point: {name}")
    return candidate


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.stat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _validate_config_payloads(
    payloads: dict[str, bytes],
    destination: Path | None,
    *,
    temp_parent: Path | None = None,
) -> str | None:
    config_payloads = {name: data for name, data in payloads.items() if name.casefold().startswith("configs/")}
    if not config_payloads:
        return None
    # System temp, never beside the app root. temp_parent is kept for API compatibility only.
    temporary_path = Path(tempfile.mkdtemp(prefix="restore-config-"))
    result: str | None = None
    step = "initialise"
    try:
        root = temporary_path
        config_dir = root / "configs"
        step = "mkdir"
        config_dir.mkdir(parents=True, exist_ok=True)
        step = "copy_destination"
        # Stage the destination's config files exactly as the canonical loader
        # would see them, except files the backup scanner treats as secret:
        # credentials are never copied into the temporary validation root.
        source_dir = Path(destination) / "configs" if destination is not None else None
        if source_dir is not None and source_dir.is_dir():
            for source in sorted(source_dir.iterdir()):
                # Only the top-level config documents the loader reads; hidden
                # lock/staging files held by the atomic writer are skipped.
                if (
                    source.name.startswith(".")
                    or source.suffix.casefold() not in {".yaml", ".yml", ".json"}
                    or not source.is_file()
                    or source.is_symlink()
                ):
                    continue
                relative = source.relative_to(source_dir)
                data = source.read_bytes()
                if _secret_path(source) or _secret_content(data, source):
                    continue
                target = config_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        for name, data in config_payloads.items():
            step = "overlay_payload"
            if _unsafe(name) or not _approved_payload_root(name):
                continue
            target = root / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        step = "load_settings_bundle"
        load_settings_bundle(root)
    except SettingsError as exc:
        reason = str(exc)
        if "revision" in reason.casefold():
            result = f"settings_revision_mismatch:{reason}"
        else:
            result = f"settings_consistency_invalid:{reason}"
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = f"settings_consistency_invalid:{step}:{type(exc).__name__}:{exc}"
    except Exception as exc:
        result = f"settings_consistency_invalid:{step}:{type(exc).__name__}:{exc}"
    finally:
        try:
            shutil.rmtree(temporary_path, onerror=_remove_readonly)
        except Exception as exc:
            cleanup_error = f"settings_consistency_invalid:cleanup_failed:{type(exc).__name__}:{exc}"
            result = f"{result}; {cleanup_error}" if result else cleanup_error
    return result


def _remove_readonly(function, path: str, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _validate_config_consistency(
    archive: zipfile.ZipFile,
    entries: list[str],
    *,
    destination: Path | None,
) -> str | None:
    """Validate the post-restore config bundle with the canonical settings loader."""

    payloads = {
        name: archive.read(name)
        for name in entries
        if name.casefold().startswith("configs/") and not _unsafe(name) and _approved_payload_root(name)
    }
    archive_parent = Path(destination).resolve().parent if destination is not None else Path.cwd()
    return _validate_config_payloads(
        payloads,
        Path(destination) if destination is not None else None,
        temp_parent=archive_parent,
    )


def _transient_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    transient = {"logs", "log", "build", "dist", "__pycache__", ".pytest_cache", ".venv", "venv", "cache", "caches"}
    stable = {"data", "configs", "models", "exports", "version", "changelog"}
    transient_indexes = [index for index, part in enumerate(parts) if part in transient]
    stable_indexes = [index for index, part in enumerate(parts) if part in stable]
    if stable_indexes and transient_indexes and max(stable_indexes) > max(transient_indexes):
        return False
    # Explicitly selected release metadata remains stable even when pytest or
    # another caller places it below a transient ancestor such as ``logs``.
    metadata_name = _archive_name(path).casefold()
    if metadata_name in {"pyproject.toml", "version", "version.txt", "version.json", "changelog.md", "changes.md"}:
        return False
    return bool(transient_indexes) or path.suffix.lower() in {".pyc", ".tmp"}


def _archive_name(path: Path) -> str:
    parts = list(path.parts)
    for marker in ("configs", "data", "models", "version", "changelog", "exports"):
        if marker in parts:
            return Path(*parts[parts.index(marker) :]).as_posix()
    return path.name
