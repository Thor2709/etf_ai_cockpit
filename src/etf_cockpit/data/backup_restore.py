from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group


# Named schemas are intentionally allow-listed.  A future-looking label such
# as ``cockpit.v999`` must not be treated as compatible merely because it has a
# version-shaped suffix; it may carry fields this runtime cannot interpret.
_SUPPORTED_NAMED_SCHEMA_VERSIONS = {"cockpit.v1"}


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
    """Write only changed, policy-approved files relative to a prior manifest."""

    checksums, excluded, payloads = _collect_payloads(
        paths,
        include_transient=include_transient,
        previous_checksums=base_manifest.checksums,
    )
    manifest_payload = _manifest_payload(
        checksums,
        excluded,
        schema_version=2,
        incremental=True,
        base_manifest_checksum=base_manifest.manifest_checksum,
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


def validate_restore(archive_path: Path) -> RestorePreview:
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
            for name in names:
                if name != "manifest.json":
                    if _unsafe(name):
                        errors.append(f"unsafe_path:{name}")
                    elif not _approved_payload_root(name):
                        errors.append(f"unapproved_path:{name}")
                    entries.append(name)
            if "manifest.json" not in names:
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
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        errors.append(f"archive_invalid:{type(exc).__name__}")
    return RestorePreview(Path(archive_path), not errors, tuple(sorted(set(entries))), tuple(errors), checksums, manifest_checksum, excluded)


def commit_restore(preview: RestorePreview, destination: Path) -> RestoreResult:
    destination = Path(destination)
    if not preview.valid:
        return RestoreResult(destination, 0, False, "; ".join(preview.errors) or "Restore preview is invalid")
    current = validate_restore(preview.archive)
    if not current.valid or current.manifest_checksum != preview.manifest_checksum or current.checksums != preview.checksums:
        return RestoreResult(destination, 0, False, "restore_preview_stale_or_archive_changed")
    requests: list[AtomicWriteRequest] = []
    try:
        with zipfile.ZipFile(preview.archive) as archive:
            for name in preview.entries:
                target = destination / Path(name)
                requests.append(AtomicWriteRequest(target, archive.read(name), lambda _path: None))
        atomic_write_group(requests)
    except Exception as exc:
        return RestoreResult(destination, 0, False, f"restore_failed:{type(exc).__name__}:{exc}")
    return RestoreResult(destination, len(requests), True)


def commit_incremental_restore(previews: list[RestorePreview] | tuple[RestorePreview, ...], destination: Path) -> RestoreResult:
    """Apply a validated base archive followed by validated incremental archives."""

    if not previews:
        return RestoreResult(Path(destination), 0, False, "no_restore_archives")
    requests_by_name: dict[str, AtomicWriteRequest] = {}
    try:
        for preview in previews:
            current = validate_restore(preview.archive)
            if not current.valid or current.manifest_checksum != preview.manifest_checksum or current.checksums != preview.checksums:
                return RestoreResult(Path(destination), 0, False, "restore_preview_stale_or_archive_changed")
            with zipfile.ZipFile(preview.archive) as archive:
                for name in preview.entries:
                    requests_by_name[name] = AtomicWriteRequest(Path(destination) / Path(name), archive.read(name), lambda _path: None)
        atomic_write_group(list(requests_by_name.values()))
    except Exception as exc:
        return RestoreResult(Path(destination), 0, False, f"restore_failed:{type(exc).__name__}:{exc}")
    return RestoreResult(Path(destination), len(requests_by_name), True)


def validate_encrypted_restore(archive_path: Path, recovery_key: str | bytes) -> RestorePreview:
    """Decrypt and validate an encrypted archive without writing restored data."""

    try:
        plaintext = _decrypt_backup(Path(archive_path), recovery_key)
    except (BackupKeyError, EncryptionUnavailable, OSError, ValueError, TypeError) as exc:
        return RestorePreview(Path(archive_path), False, (), (f"decryption_failed:{type(exc).__name__}",))
    return _preview_from_plaintext(Path(archive_path), plaintext)


def restore_encrypted_backup(archive_path: Path, destination: Path, recovery_key: str | bytes) -> RestoreResult:
    preview = validate_encrypted_restore(archive_path, recovery_key)
    if not preview.valid:
        return RestoreResult(Path(destination), 0, False, "; ".join(preview.errors))
    try:
        plaintext = _decrypt_backup(Path(archive_path), recovery_key)
        with tempfile.NamedTemporaryFile(suffix=".backup", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(plaintext)
        try:
            plain_preview = validate_restore(temporary)
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
            validate_encrypted_restore(archive, recovery_key)
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
) -> tuple[dict[str, str], list[str], dict[str, bytes]]:
    files = sorted(_iter_files(paths), key=lambda item: str(item))
    checksums: dict[str, str] = {}
    excluded: list[str] = []
    payloads: dict[str, bytes] = {}
    for path in files:
        relative = _archive_name(path)
        data = path.read_bytes()
        if _secret_path(path) or _secret_content(data) or (not include_transient and _transient_path(path)):
            excluded.append(relative)
            continue
        checksum = hashlib.sha256(data).hexdigest()
        if previous_checksums is not None and previous_checksums.get(relative) == checksum:
            continue
        checksums[relative] = checksum
        payloads[relative] = data
    return checksums, excluded, payloads


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


def _preview_from_plaintext(display_path: Path, plaintext: bytes) -> RestorePreview:
    with tempfile.NamedTemporaryFile(suffix=".backup", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(plaintext)
    try:
        preview = validate_restore(temporary)
        return RestorePreview(display_path, preview.valid, preview.entries, preview.errors, preview.checksums, preview.manifest_checksum, preview.excluded)
    finally:
        temporary.unlink(missing_ok=True)


def _iter_files(paths: list[Path]):
    for path in paths:
        source = Path(path)
        if source.is_dir():
            yield from (item for item in source.rglob("*") if item.is_file())
        elif source.is_file():
            yield source


def _manifest_payload(
    checksums: dict[str, str],
    excluded: list[str] | tuple[str, ...] = (),
    *,
    schema_version: int = 1,
    incremental: bool = False,
    base_manifest_checksum: str | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "checksums": checksums,
        "excluded": sorted(set(excluded)),
    }
    if incremental:
        payload["incremental"] = True
        payload["base_manifest_checksum"] = base_manifest_checksum
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _unsafe(name: str) -> bool:
    path = PurePosixPath(name)
    return not name or path.is_absolute() or ".." in path.parts or ":" in name.split("/", 1)[0]


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


_SECRET_CONTENT = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|secret[_-]?key|password|private[_-]?key)\s*[:=]"
)


def _secret_content(data: bytes) -> bool:
    text = data.decode("utf-8", errors="ignore")
    return bool(_SECRET_CONTENT.search(text) or "-----BEGIN" in text and "PRIVATE KEY-----" in text)


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
