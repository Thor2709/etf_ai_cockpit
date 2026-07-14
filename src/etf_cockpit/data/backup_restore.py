from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group


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


def create_backup(paths: list[Path], destination: Path, *, include_transient: bool = False) -> BackupManifest:
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
        checksums[relative] = hashlib.sha256(data).hexdigest()
        payloads[relative] = data
    manifest_payload = _manifest_payload(checksums, excluded)
    manifest_checksum = hashlib.sha256(manifest_payload).hexdigest()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(payloads):
                archive.writestr(name, payloads[name])
            archive.writestr("manifest.json", manifest_payload)
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)
    return BackupManifest(destination, checksums, 1, manifest_checksum, tuple(excluded), False)


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
                if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("checksums"), dict):
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


def _iter_files(paths: list[Path]):
    for path in paths:
        source = Path(path)
        if source.is_dir():
            yield from (item for item in source.rglob("*") if item.is_file())
        elif source.is_file():
            yield source


def _manifest_payload(checksums: dict[str, str], excluded: list[str] | tuple[str, ...] = ()) -> bytes:
    return (json.dumps({"schema_version": 1, "checksums": checksums, "excluded": sorted(set(excluded))}, sort_keys=True, indent=2) + "\n").encode("utf-8")


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
    if normalised == ".ai_worklog/changes.md":
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
    return bool(transient_indexes) or path.suffix.lower() in {".pyc", ".tmp"}


def _archive_name(path: Path) -> str:
    parts = list(path.parts)
    lowered = [part.casefold() for part in parts]
    if ".ai_worklog" in lowered:
        index = lowered.index(".ai_worklog")
        return Path(*parts[index:]).as_posix()
    for marker in ("configs", "data", "models", "version", "changelog", "exports"):
        if marker in parts:
            return Path(*parts[parts.index(marker) :]).as_posix()
    return path.name
