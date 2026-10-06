from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.core.secure_update import describe_release_evidence


_DEFAULT_REBUILD_MESSAGE = "unavailable (source checkout; no packaged build metadata)"


def read_changelog_excerpt(root: Path, *, max_chars: int = 1200) -> str:
    """Return the latest changelog entry, bounded for display in the UI."""

    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    path = Path(root) / "CHANGELOG.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "unavailable"
    entry_start = next((index for index, line in enumerate(lines) if line.startswith("## ")), None)
    if entry_start is None:
        return "unavailable"
    entry = []
    for line in lines[entry_start:]:
        if entry and line.startswith("## "):
            break
        entry.append(line)
    excerpt = "\n".join(entry).strip()
    if not excerpt:
        return "unavailable"
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 1].rstrip() + "…"


def read_rebuild_timestamp(root: Path) -> str:
    """Read a packaged build timestamp when an explicit metadata file exists."""

    root = Path(root)
    candidates = (
        root / "packaging" / "build-info.json",
        root / "packaging" / "build_metadata.json",
        root / "version.json",
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in ("rebuild_timestamp", "build_timestamp", "built_at"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return _DEFAULT_REBUILD_MESSAGE


__all__ = ["describe_release_evidence", "read_changelog_excerpt", "read_rebuild_timestamp"]
