from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from etf_cockpit.core.paths import WORKSPACES_DIR


def save_workspace(name: str, payload: dict[str, Any], *, directory: Path = WORKSPACES_DIR) -> Path:
    """Persist a versioned local workspace without network or executable authority."""

    safe_name = "".join(character if character.isalnum() or character in "-_" else "_" for character in str(name).strip()) or "workspace"
    path = directory / f"{safe_name}.json"
    directory.mkdir(parents=True, exist_ok=True)
    content = dict(payload)
    content.setdefault("schema_version", "1.0")
    content.setdefault("execution_allowed", False)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_workspace(name: str, *, directory: Path = WORKSPACES_DIR) -> dict[str, Any] | None:
    safe_name = "".join(character if character.isalnum() or character in "-_" else "_" for character in str(name).strip()) or "workspace"
    path = directory / f"{safe_name}.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None
