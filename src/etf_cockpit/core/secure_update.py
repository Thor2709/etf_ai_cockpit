"""Offline, signed update-bundle verification and safe staging."""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "1.0"
SIGNING_KEY_ENV = "ETF_COCKPIT_RELEASE_SIGNING_KEY"
MAX_MEMBER_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class UpdateVerification:
    ok: bool
    status: str
    errors: tuple[str, ...]
    archive_sha256: str = ""
    manifest_sha256: str = ""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest_digest(manifest: dict[str, object]) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return sha256_bytes(canonical_json(unsigned))


def _safe_member(name: str) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise ValueError(f"unsafe update member name: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ":" in path.parts[0] or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe update member name: {name!r}")
    return path.as_posix()


def _file_infos(archive: zipfile.ZipFile) -> list[tuple[str, zipfile.ZipInfo]]:
    rows: list[tuple[str, zipfile.ZipInfo]] = []
    seen: set[str] = set()
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = _safe_member(info.filename)
        if name in seen:
            raise ValueError(f"duplicate update member: {name}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"update member exceeds size limit: {name}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"symbolic links are not allowed in updates: {name}")
        seen.add(name)
        rows.append((name, info))
    if not rows:
        raise ValueError("update archive contains no files")
    return sorted(rows, key=lambda row: row[0])


def build_update_manifest(archive_path: str | Path) -> dict[str, object]:
    archive = Path(archive_path)
    entries: list[dict[str, object]] = []
    with zipfile.ZipFile(archive) as bundle:
        for name, info in _file_infos(bundle):
            payload = bundle.read(info)
            entries.append({"path": name, "bytes": len(payload), "sha256": sha256_bytes(payload)})
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "archive_sha256": sha256_bytes(archive.read_bytes()),
        "entries": entries,
        "offline_only": True,
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    return manifest


def sign_update_manifest(manifest: dict[str, object], key: bytes, *, key_id: str) -> dict[str, object]:
    if len(key) < 16:
        raise ValueError("update signing key must contain at least 16 bytes")
    payload = canonical_json(manifest)
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "HMAC-SHA256",
        "key_id": key_id,
        "payload_sha256": sha256_bytes(payload),
        "signature": hmac.new(key, payload, hashlib.sha256).hexdigest(),
    }


def verify_update_bundle(
    archive_path: str | Path,
    manifest: dict[str, object],
    signature: dict[str, object] | None,
    key: bytes | None,
) -> UpdateVerification:
    archive = Path(archive_path)
    errors: list[str] = []
    try:
        expected_archive = str(manifest["archive_sha256"])
        archive_sha = sha256_bytes(archive.read_bytes())
        if not hmac.compare_digest(str(manifest.get("manifest_sha256", "")), _manifest_digest(manifest)):
            errors.append("manifest SHA-256 does not match its contents")
        if not hmac.compare_digest(archive_sha, expected_archive):
            errors.append("archive SHA-256 does not match the signed manifest")
        expected_payload = sha256_bytes(canonical_json(manifest))
        if signature is None or not key:
            errors.append("a signing key and detached signature are required")
        else:
            if str(signature.get("payload_sha256", "")) != expected_payload:
                errors.append("detached signature payload hash does not match the manifest")
            expected_signature = hmac.new(key, canonical_json(manifest), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(str(signature.get("signature", "")), expected_signature):
                errors.append("detached signature is invalid")
        expected_entries = manifest.get("entries")
        if not isinstance(expected_entries, list):
            raise ValueError("manifest entries must be a list")
        expected_by_path = {str(row["path"]): row for row in expected_entries if isinstance(row, dict)}
        with zipfile.ZipFile(archive) as bundle:
            actual_infos = _file_infos(bundle)
            actual_names = {name for name, _info in actual_infos}
            if actual_names != set(expected_by_path):
                errors.append("archive members do not match the signed manifest")
            for name, info in actual_infos:
                row = expected_by_path.get(name)
                if row is None:
                    continue
                payload = bundle.read(info)
                if int(row.get("bytes", -1)) != len(payload) or str(row.get("sha256", "")) != sha256_bytes(payload):
                    errors.append(f"update member hash mismatch: {name}")
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        errors.append(str(exc))
        archive_sha = ""
    status = "verified" if not errors else "rejected"
    return UpdateVerification(not errors, status, tuple(dict.fromkeys(errors)), archive_sha, _manifest_digest(manifest))


def extract_verified_update(
    archive_path: str | Path,
    manifest: dict[str, object],
    signature: dict[str, object] | None,
    key: bytes | None,
    destination: str | Path,
) -> Path:
    verification = verify_update_bundle(archive_path, manifest, signature, key)
    if not verification.ok:
        raise ValueError("; ".join(verification.errors))
    target = Path(destination).resolve()
    staging = target.parent / f".{target.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as bundle:
        for name, info in _file_infos(bundle):
            output = (staging / Path(*PurePosixPath(name).parts)).resolve()
            if staging not in output.parents:
                raise ValueError(f"update member escaped staging directory: {name}")
            output.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, output.open("wb") as destination_file:
                shutil.copyfileobj(source, destination_file)
    return staging


def describe_release_evidence(root: str | Path) -> dict[str, str]:
    root = Path(root)
    release_dir = root / "artifacts" / "release" / "latest"
    manifest_path = release_dir / "release-manifest.json"
    signature_path = release_dir / "release-manifest.sig.json"
    notices_path = root / "packaging" / "THIRD_PARTY_NOTICES.md"
    if not manifest_path.is_file():
        verification = "unavailable (no local release manifest)"
        version = "unavailable"
    else:
        try:
            manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
            signature: dict[str, Any] = json.loads(signature_path.read_text(encoding="utf-8")) if signature_path.is_file() else {}
            verification = str(signature.get("status", "unsigned"))
            policy = manifest.get("policy", {})
            policy_version = policy.get("version") if isinstance(policy, dict) else None
            version = str(manifest.get("project_version", policy_version or "unknown"))
        except (OSError, json.JSONDecodeError, AttributeError):
            verification = "invalid local release evidence"
            version = "unavailable"
    return {
        "verification": verification,
        "version": version,
        "notices": "available" if notices_path.is_file() else "unavailable",
        "manifest": str(manifest_path),
        "notices_path": str(notices_path),
    }
