from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from etf_cockpit.core.paths import WORKSPACES_DIR, safe_file_stem


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def save_workspace(name: str, payload: dict[str, Any], *, directory: Path = WORKSPACES_DIR) -> Path:
    """Persist a versioned local workspace without network or executable authority."""

    path = directory / f"{safe_file_stem(name)}.json"
    directory.mkdir(parents=True, exist_ok=True)
    content = dict(payload)
    content.setdefault("schema_version", "1.0")
    content["execution_allowed"] = False
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    return path


def load_workspace(name: str, *, directory: Path = WORKSPACES_DIR) -> dict[str, Any] | None:
    path = directory / f"{safe_file_stem(name)}.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return None
    value["execution_allowed"] = False
    return value
