"""Personal, dated notes per stock (S3): ``data/notes/<instrument_id>.jsonl``, append-only, local only.

Every write rewrites the whole file through ``core.atomic_io`` so a crash never leaves a half
line. A note is never edited in place: a retraction line hides it from the default view but the
history stays on disk.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import ROOT

MAX_NOTE_CHARS = 10_000
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class NoteError(ValueError):
    """The note or instrument id cannot be stored."""


def notes_path(instrument_id: str, root: Path | None = None) -> Path:
    if not _SAFE_ID.match(instrument_id or "") or ".." in instrument_id:
        raise NoteError(f"'{instrument_id}' is not a valid instrument id for a notes file")
    return Path(root or ROOT) / "data" / "notes" / f"{instrument_id}.jsonl"


def _validate_jsonl(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a damaged line is skipped, never guessed
    return records


def _append(path: Path, record: dict[str, Any]) -> None:
    existing = path.read_bytes() if path.is_file() else b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    payload = existing + (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload, _validate_jsonl)


def add_note(instrument_id: str, text: str, *, root: Path | None = None, now: datetime | None = None, tags: tuple[str, ...] = ()) -> dict[str, Any]:
    clean = (text or "").strip()
    if not clean:
        raise NoteError("A note cannot be empty")
    if len(clean) > MAX_NOTE_CHARS:
        raise NoteError(f"A note is limited to {MAX_NOTE_CHARS} characters")
    path = notes_path(instrument_id, root)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    record = {
        "type": "note",
        "note_id": uuid.uuid4().hex,
        "instrument_id": instrument_id,
        "created_at": stamp.isoformat(),
        "text": clean,
        "tags": [str(tag) for tag in tags],
    }
    _append(path, record)
    return record


def retract_note(instrument_id: str, note_id: str, *, root: Path | None = None, now: datetime | None = None) -> None:
    path = notes_path(instrument_id, root)
    if not any(item.get("note_id") == note_id for item in _read_lines(path) if item.get("type") == "note"):
        raise NoteError("That note does not exist for this instrument")
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _append(path, {"type": "retract", "note_id": note_id, "instrument_id": instrument_id, "at": stamp.isoformat()})


def list_notes(instrument_id: str, *, root: Path | None = None, include_retracted: bool = False) -> list[dict[str, Any]]:
    """Notes newest first; retracted notes are hidden unless asked for."""

    records = _read_lines(notes_path(instrument_id, root))
    retracted = {item.get("note_id") for item in records if item.get("type") == "retract"}
    notes = [item for item in records if item.get("type") == "note"]
    if not include_retracted:
        notes = [item for item in notes if item.get("note_id") not in retracted]
    else:
        for item in notes:
            item["retracted"] = item.get("note_id") in retracted
    return sorted(notes, key=lambda item: str(item.get("created_at")), reverse=True)
