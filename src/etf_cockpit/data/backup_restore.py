from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group


@dataclass(frozen=True)
class BackupManifest:
    archive: Path
    checksums: dict[str, str]


@dataclass(frozen=True)
class RestorePreview:
    archive: Path
    valid: bool
    entries: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class RestoreResult:
    destination: Path
    restored: int


def create_backup(paths: list[Path], destination: Path) -> BackupManifest:
    checksums: dict[str, str] = {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if not path.exists() or not path.is_file():
                continue
            if _secret_path(path):
                continue
            arcname = _archive_name(path)
            data = path.read_bytes()
            checksum = hashlib.sha256(data).hexdigest()
            checksums[arcname] = checksum
            archive.writestr(arcname, data)
        archive.writestr("manifest.json", json.dumps({"schema_version": 1, "checksums": checksums}, sort_keys=True, indent=2))
    return BackupManifest(destination, checksums)


def validate_restore(archive_path: Path) -> RestorePreview:
    errors: list[str] = []
    entries: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if name == "manifest.json":
                    continue
                if _unsafe(name):
                    errors.append(f"unsafe_path:{name}")
                entries.append(name)
            if "manifest.json" not in archive.namelist():
                errors.append("manifest_missing")
            else:
                manifest = json.loads(archive.read("manifest.json"))
                for name, expected in manifest.get("checksums", {}).items():
                    if name not in archive.namelist() or hashlib.sha256(archive.read(name)).hexdigest() != expected:
                        errors.append(f"checksum_mismatch:{name}")
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, TypeError, ValueError) as exc:
        errors.append(f"archive_invalid:{type(exc).__name__}")
    return RestorePreview(archive_path, not errors, tuple(entries), tuple(errors))


def commit_restore(preview: RestorePreview, destination: Path) -> RestoreResult:
    if not preview.valid:
        raise ValueError("Restore preview is invalid")
    destination.mkdir(parents=True, exist_ok=True)
    requests: list[AtomicWriteRequest] = []
    with zipfile.ZipFile(preview.archive) as archive:
        for name in preview.entries:
            target = destination / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            requests.append(AtomicWriteRequest(target, archive.read(name), lambda _path: None))
    atomic_write_group(requests)
    return RestoreResult(destination, len(requests))


def _unsafe(name: str) -> bool:
    path = PurePosixPath(name)
    return path.is_absolute() or ".." in path.parts or ":" in name.split("/", 1)[0]


def _secret_path(path: Path) -> bool:
    return path.name.lower() in {".env", ".env.local", "secrets.json"} or "secret" in path.name.lower()


def _archive_name(path: Path) -> str:
    parts = list(path.parts)
    for marker in ("configs", "data", "models", "logs", "exports"):
        if marker in parts:
            return Path(*parts[parts.index(marker) :]).as_posix()
    return path.name
