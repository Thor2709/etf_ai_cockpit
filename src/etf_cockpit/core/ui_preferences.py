"""Per-user display preferences, kept outside the revisioned settings bundle.

They change how scores are presented, never stored evidence or score history.
"""

from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
from etf_cockpit.core.paths import ROOT

MISSING_DATA_PENALTY = "missing_data_penalty"
SPAREBANK_PEERS = "sparebank_peers"  # {instrument_id: [owner-picked peer ids]}
_DEFAULTS: dict[str, object] = {MISSING_DATA_PENALTY: False, SPAREBANK_PEERS: {}}
_CACHE: dict[str, object] = {}
_SAVE_ATTEMPTS = 8


class _PreferencesChanged(Exception):
    """The stored file changed between the read and the guarded write."""


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


def _stored_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except FileNotFoundError:
        return None


def _validate_preferences(path: Path) -> None:
    if not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
        raise ValueError("preferences must contain an object")


def save_preference(name: str, value: object, root: Path | None = None) -> None:
    """Read-modify-write under the atomic group guards (compare-and-set, bounded retry)."""

    if name not in _DEFAULTS:
        raise ValueError(f"Unknown preference: {name}")
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(_SAVE_ATTEMPTS):
        before = _stored_bytes(path)
        try:
            stored = json.loads(before.decode("utf-8")) if before is not None else {}
        except (UnicodeDecodeError, ValueError):
            stored = {}
        merged = {**_DEFAULTS, **(stored if isinstance(stored, dict) else {}), name: value}
        encoded = (json.dumps(merged, indent=2, default=str) + "\n").encode("utf-8")

        def unchanged(before: bytes | None = before) -> None:
            if _stored_bytes(path) != before:
                raise _PreferencesChanged

        try:
            atomic_write_group((AtomicWriteRequest(path, encoded, _validate_preferences),), precondition=unchanged)
        except _PreferencesChanged:
            continue
        _CACHE.clear()
        return
    raise OSError("preferences kept changing concurrently; save not applied")


def missing_data_penalty(root: Path | None = None) -> bool:
    return bool(load_preferences(root).get(MISSING_DATA_PENALTY))
