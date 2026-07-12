"""Append-only, user-owned decision journal with checksum evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, atomic_write_json


class JournalIntegrityError(ValueError):
    """Raised when persisted journal evidence cannot be trusted."""


class JournalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal_entry_id: str
    created_at: str
    thesis: str
    decision: str
    outcome: str
    private_notes: str | None = None
    supersedes_entry_id: str | None = None
    schema_version: str = "1.0"
    checksum: str | None = None


def _canonical_values(entry: JournalEntry) -> dict[str, object]:
    values = entry.model_dump(mode="json")
    values.pop("checksum", None)
    return values


def _checksum(entry: JournalEntry) -> str:
    encoded = json.dumps(_canonical_values(entry), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DecisionJournal:
    """Persist journal entries as immutable payloads plus a checksum index."""

    def _directory(self, root: Path) -> Path:
        return root / "decision_journal"

    def _index_path(self, root: Path) -> Path:
        return self._directory(root) / "index.json"

    def _entry_path(self, root: Path, entry_id: str) -> Path:
        return self._directory(root) / "entries" / f"{entry_id}.json"

    def _read_index(self, root: Path) -> list[dict[str, str]]:
        path = self._index_path(root)
        if not path.is_file():
            entries_dir = self._directory(root) / "entries"
            if entries_dir.is_dir() and any(entries_dir.glob("*.json")):
                raise JournalIntegrityError("journal index is missing")
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JournalIntegrityError(f"journal index is unreadable: {path}") from exc
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise JournalIntegrityError("journal index is malformed")
        return [dict(row) for row in value]

    def create(self, entry: JournalEntry, *, root: Path) -> JournalEntry:
        root = Path(root)
        entry_dir = self._directory(root) / "entries"
        entry_dir.mkdir(parents=True, exist_ok=True)
        entry_id = entry.journal_entry_id.strip()
        if not entry_id:
            raise ValueError("journal entry id must not be empty")
        destination = self._entry_path(root, entry_id)
        if destination.exists():
            raise ValueError(f"duplicate journal entry id: {entry_id}")
        stored = entry.model_copy(update={"journal_entry_id": entry_id, "checksum": None})
        stored = stored.model_copy(update={"checksum": _checksum(stored)})
        index = self._read_index(root)
        if any(row.get("journal_entry_id") == entry_id for row in index):
            raise ValueError(f"duplicate journal entry id: {entry_id}")
        index.append({"journal_entry_id": entry_id, "created_at": stored.created_at, "checksum": str(stored.checksum)})
        index.sort(key=lambda row: (row.get("created_at", ""), row.get("journal_entry_id", "")))
        payload = (json.dumps(stored.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode("utf-8")
        index_payload = (json.dumps(index, indent=2, sort_keys=True) + "\n").encode("utf-8")
        atomic_write_group(
            (
                AtomicWriteRequest(destination, payload, lambda path: JournalEntry.model_validate(json.loads(path.read_text(encoding="utf-8")))),
                AtomicWriteRequest(self._index_path(root), index_payload, lambda path: json.loads(path.read_text(encoding="utf-8"))),
            )
        )
        self._append_operation(root, "created", stored)
        return stored

    def get(self, journal_entry_id: str, *, root: Path) -> JournalEntry:
        path = self._entry_path(Path(root), journal_entry_id)
        if not path.is_file():
            raise KeyError(journal_entry_id)
        try:
            entry = JournalEntry.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise JournalIntegrityError(f"journal entry is malformed: {journal_entry_id}") from exc
        if not entry.checksum or entry.checksum != _checksum(entry):
            raise JournalIntegrityError(f"journal entry checksum mismatch: {journal_entry_id}")
        return entry

    def list_entries(self, *, root: Path) -> list[JournalEntry]:
        index = self._read_index(Path(root))
        entries: list[JournalEntry] = []
        for row in index:
            entry = self.get(str(row["journal_entry_id"]), root=Path(root))
            if row.get("checksum") != entry.checksum:
                raise JournalIntegrityError(f"journal index checksum mismatch: {entry.journal_entry_id}")
            entries.append(entry)
        return entries

    def supersede(self, journal_entry_id: str, replacement: JournalEntry, *, root: Path) -> JournalEntry:
        self.get(journal_entry_id, root=Path(root))
        existing = self._read_index(Path(root))
        replacement_id = f"{journal_entry_id}-supersede-{len(existing) + 1}"
        replacement = replacement.model_copy(
            update={
                "journal_entry_id": replacement_id,
                "supersedes_entry_id": journal_entry_id,
                "checksum": None,
            }
        )
        return self.create(replacement, root=Path(root))

    def export_summary(self, *, root: Path) -> dict[str, object]:
        entries = self.list_entries(root=Path(root))
        summary: dict[str, object] = {
            "schema_version": "1.0",
            "row_count": len(entries),
            "ids": [entry.journal_entry_id for entry in entries],
            "checksums": [entry.checksum for entry in entries],
            "private_notes_exported": False,
        }
        atomic_write_json(self._directory(Path(root)) / "export_summary.json", summary)
        return summary

    def _append_operation(self, root: Path, operation: str, entry: JournalEntry) -> None:
        path = self._directory(Path(root)) / "operations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "operation": operation,
            "journal_entry_id": entry.journal_entry_id,
            "checksum": entry.checksum,
            "schema_version": entry.schema_version,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


__all__ = ["DecisionJournal", "JournalEntry", "JournalIntegrityError"]
