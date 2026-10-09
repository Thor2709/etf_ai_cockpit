"""User-picked peers per stock (S4), stored locally in ``data/stock_peers/user_peers.json``."""

from __future__ import annotations

import json
import re
from pathlib import Path

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import ROOT

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=^-]{0,31}$")


def picks_path(root: Path | None = None) -> Path:
    return Path(root or ROOT) / "data" / "stock_peers" / "user_peers.json"


def _validate(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def load_user_peers(root: Path | None = None) -> dict[str, list[str]]:
    path = picks_path(root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): [str(i) for i in v] for k, v in raw.items() if isinstance(v, list)}


def _save(picks: dict[str, list[str]], root: Path | None) -> None:
    payload = json.dumps(picks, indent=2, sort_keys=True).encode("utf-8")
    atomic_write_bytes(picks_path(root), payload, _validate)


def set_user_peers(instrument_id: str, peer_ids: list[str], *, root: Path | None = None) -> list[str]:
    """Replace the picked peers of ``instrument_id`` (order kept, duplicates and itself dropped)."""

    clean: list[str] = []
    for peer in peer_ids:
        peer = (peer or "").strip()
        if not peer:
            continue
        if not _SAFE_ID.match(peer):
            raise ValueError(f"'{peer}' is not a valid instrument id or ticker")
        if peer != instrument_id and peer not in clean:
            clean.append(peer)
    picks = load_user_peers(root)
    if clean:
        picks[instrument_id] = clean
    else:
        picks.pop(instrument_id, None)
    _save(picks, root)
    return clean
