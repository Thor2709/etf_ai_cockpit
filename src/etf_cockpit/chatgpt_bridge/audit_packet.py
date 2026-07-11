from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuditValidationReport:
    valid: bool
    included: tuple[str, ...]
    missing: tuple[str, ...]
    checksum_errors: tuple[str, ...]
    secret_findings: tuple[str, ...]


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?ix)"
    r"(?<![A-Za-z0-9_])"
    r"(?P<key>(?:[A-Za-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|password|passwd|authorization|bearer))"
    r"\s*(?:[\"']?\s*)?(?:=|:)\s*[\"']?"
    r"(?P<scheme>bearer\s+)?(?P<value>[^\"'\s,;}\]]+)"
)
_REDACTED_VALUE = "***redacted***"


def _contains_unredacted_secret(text: str) -> bool:
    for match in _SECRET_ASSIGNMENT_RE.finditer(text):
        key = match.group("key").lower().replace("-", "_")
        if key in {"has_api_key", "requires_api_key"}:
            continue
        if match.group("value") != _REDACTED_VALUE:
            return True
    return False


def validate_audit_archive(path: Path) -> AuditValidationReport:
    included: list[str] = []
    missing: list[str] = []
    checksum_errors: list[str] = []
    secret_findings: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "audit_manifest.json" not in names:
                return AuditValidationReport(False, (), ("audit_manifest.json",), (), ())
            manifest = json.loads(archive.read("audit_manifest.json"))
            for item in manifest.get("required", []):
                name = str(item.get("path") or "")
                if name in names:
                    included.append(name)
                elif bool(item.get("allow_unavailable")):
                    marker = str(item.get("unavailable_marker") or "")
                    if not marker or marker not in names:
                        missing.append(f"unavailable_marker_missing:{marker or name}")
                    else:
                        included.append(name)
                else:
                    missing.append(name)
            for name, expected in (manifest.get("checksums") or {}).items():
                if name not in names or hashlib.sha256(archive.read(name)).hexdigest() != str(expected):
                    checksum_errors.append(str(name))
            checksummed = {str(name) for name in (manifest.get("checksums") or {})}
            for name in names:
                if name != "audit_manifest.json" and not name.endswith("/") and name not in checksummed:
                    checksum_errors.append(f"unlisted:{name}")
            for name in names:
                if name.endswith("/"):
                    continue
                text = archive.read(name).decode("utf-8", errors="replace")
                if _contains_unredacted_secret(text):
                    secret_findings.append(name)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, TypeError, ValueError) as exc:
        return AuditValidationReport(False, (), (f"archive_invalid:{type(exc).__name__}",), (), ())
    return AuditValidationReport(not missing and not checksum_errors and not secret_findings, tuple(included), tuple(missing), tuple(checksum_errors), tuple(secret_findings))
