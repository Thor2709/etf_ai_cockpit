"""Per-user display preferences, kept outside the revisioned settings bundle.

They change how scores are presented, never stored evidence or score history.
"""

from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import ROOT

MISSING_DATA_PENALTY = "missing_data_penalty"
_DEFAULTS: dict[str, object] = {MISSING_DATA_PENALTY: False}
_CACHE: dict[str, object] = {}


def _path(root: Path | None) -> Path:
    return (Path(root) if root is not None else ROOT) / "data" / "ui_preferences.json"


def load_preferences(root: Path | None = None) -> dict[str, object]:
    path = _path(root)
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return dict(_DEFAULTS)
    if _CACHE.get("key") != key:
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        _CACHE.update(key=key, value={**_DEFAULTS, **(stored if isinstance(stored, dict) else {})})
    return dict(_CACHE["value"])  # type: ignore[arg-type]


def save_preference(name: str, value: object, root: Path | None = None) -> None:
    if name not in _DEFAULTS:
        raise ValueError(f"Unknown preference: {name}")
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {**load_preferences(root), name: value})
    _CACHE.clear()


def missing_data_penalty(root: Path | None = None) -> bool:
    return bool(load_preferences(root).get(MISSING_DATA_PENALTY))
