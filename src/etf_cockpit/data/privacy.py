"""Local-first privacy classification, export redaction and scoped deletion."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etf_cockpit.core.atomic_io import atomic_write_bytes


class PrivacyDeletionError(ValueError):
    """Raised when a privacy operation is not explicitly authorised."""


@dataclass(frozen=True)
class PrivacyExport:
    path: Path
    rows: int
    sha256: str
    included_private: bool = False


_PRIVATE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "access_token",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "password",
        "private_key",
        "private_note",
        "private_notes",
        "recovery_key",
        "secret",
        "secrets",
        "token",
    }
)


def classify_field(field_name: str) -> str:
    normalised = str(field_name).strip().casefold().replace("-", "_")
    return "private" if normalised in _PRIVATE_FIELD_NAMES or any(word in normalised for word in ("secret", "password", "token")) else "public"


def redact_private_fields(value: Any, *, include_private: bool = False) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if classify_field(key_text) == "private" and not include_private:
                continue
            result[key_text] = redact_private_fields(item, include_private=include_private)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_private_fields(item, include_private=include_private) for item in value]
    return value


def export_redacted_records(
    records: Sequence[Mapping[str, Any]],
    destination: Path,
    *,
    include_private: bool = False,
    confirm_private: bool = False,
) -> PrivacyExport:
    if include_private and not confirm_private:
        raise PrivacyDeletionError("explicit private export confirmation is required")
    payload = redact_private_fields(records, include_private=include_private)
    encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
    result = atomic_write_bytes(Path(destination), encoded, lambda path: json.loads(path.read_text(encoding="utf-8")))
    return PrivacyExport(result.destination, len(records), result.sha256, include_private)


def delete_private_data(root: Path, *, confirmation: str) -> tuple[Path, ...]:
    if confirmation != "DELETE PRIVATE DATA":
        raise PrivacyDeletionError("confirmation must be exactly 'DELETE PRIVATE DATA'")
    private_root = (Path(root) / "data" / "private").resolve()
    if not private_root.exists():
        return ()
    deleted: list[Path] = []
    for path in sorted(private_root.rglob("*"), key=lambda item: str(item), reverse=True):
        if path.is_symlink() or path.is_file():
            path.unlink()
            deleted.append(path)
    for directory in sorted((item for item in private_root.rglob("*") if item.is_dir()), key=lambda item: str(item), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return tuple(sorted(deleted, key=lambda item: str(item)))


__all__ = [
    "PrivacyDeletionError",
    "PrivacyExport",
    "classify_field",
    "delete_private_data",
    "export_redacted_records",
    "redact_private_fields",
]
