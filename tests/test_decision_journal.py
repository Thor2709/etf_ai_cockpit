from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.data.decision_journal import DecisionJournal, JournalEntry, JournalIntegrityError


def _entry(**updates: object) -> JournalEntry:
    values: dict[str, object] = {
        "journal_entry_id": "entry-1",
        "created_at": "2026-07-12T00:00:00+00:00",
        "thesis": "private thesis text",
        "decision": "review",
        "outcome": "pending",
        "private_notes": "do not expose this note",
    }
    values.update(updates)
    return JournalEntry(**values)


def test_journal_correction_appends_without_mutating_original(tmp_path: Path) -> None:
    journal = DecisionJournal()
    original = journal.create(_entry(), root=tmp_path)
    corrected = journal.supersede(
        original.journal_entry_id,
        original.model_copy(update={"thesis": "revised"}),
        root=tmp_path,
    )

    assert journal.get(original.journal_entry_id, root=tmp_path).thesis == "private thesis text"
    assert corrected.thesis == "revised"
    assert corrected.supersedes_entry_id == original.journal_entry_id
    assert len(journal.list_entries(root=tmp_path)) == 2


def test_journal_rejects_duplicate_ids_and_checksum_tampering(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)

    with pytest.raises(ValueError, match="duplicate journal entry id"):
        journal.create(_entry(), root=tmp_path)

    payload_path = tmp_path / "decision_journal" / "entries" / "entry-1.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["thesis"] = "tampered"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(JournalIntegrityError, match="checksum"):
        journal.get("entry-1", root=tmp_path)


def test_journal_operational_log_and_export_summary_exclude_private_text(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)

    log_path = tmp_path / "decision_journal" / "operations.jsonl"
    assert "private thesis text" not in log_path.read_text(encoding="utf-8")
    assert "do not expose this note" not in log_path.read_text(encoding="utf-8")

    summary = journal.export_summary(root=tmp_path)
    assert summary["row_count"] == 1
    assert summary["ids"] == ["entry-1"]
    assert "private thesis text" not in json.dumps(summary)
    assert "do not expose this note" not in json.dumps(summary)


def test_journal_missing_index_fails_closed(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    (tmp_path / "decision_journal" / "index.json").unlink()

    with pytest.raises(JournalIntegrityError, match="index is missing"):
        journal.list_entries(root=tmp_path)
