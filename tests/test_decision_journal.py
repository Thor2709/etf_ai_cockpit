from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.data.decision_journal import DecisionJournal, JournalEntry, JournalIntegrityError, _checksum


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
    operations = [json.loads(line) for line in (tmp_path / "decision_journal" / "operations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [record["operation"] for record in operations] == ["created", "superseded"]


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


def test_journal_rejects_path_traversal_ids(tmp_path: Path) -> None:
    journal = DecisionJournal()
    with pytest.raises(ValueError, match="safe"):
        journal.create(_entry(journal_entry_id="../outside"), root=tmp_path)


def test_journal_malformed_index_fails_closed(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    index_path = tmp_path / "decision_journal" / "index.json"
    index_path.write_text(json.dumps([{"journal_entry_id": "entry-1"}]), encoding="utf-8")
    with pytest.raises(JournalIntegrityError, match="index row"):
        journal.list_entries(root=tmp_path)


def test_journal_log_failure_does_not_publish_a_second_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = DecisionJournal()
    original = journal.create(_entry(), root=tmp_path)
    monkeypatch.setattr(journal, "_append_operation", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("log full")))
    replacement = original.model_copy(update={"journal_entry_id": "entry-2", "thesis": "new"})
    with pytest.raises(OSError, match="log full"):
        journal.create(replacement, root=tmp_path)
    assert [entry.journal_entry_id for entry in journal.list_entries(root=tmp_path)] == ["entry-1"]
    assert not (tmp_path / "decision_journal" / "entries" / "entry-2.json").exists()


def test_journal_supersede_id_is_content_deterministic(tmp_path: Path) -> None:
    journal = DecisionJournal()
    original = journal.create(_entry(), root=tmp_path)
    replacement = original.model_copy(update={"thesis": "revised"})
    first = journal.supersede(original.journal_entry_id, replacement, root=tmp_path)
    second = journal.supersede(original.journal_entry_id, replacement, root=tmp_path)
    assert first.journal_entry_id == second.journal_entry_id
    assert len(journal.list_entries(root=tmp_path)) == 2


def test_journal_get_fails_closed_when_index_is_missing(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    (tmp_path / "decision_journal" / "index.json").unlink()
    with pytest.raises(JournalIntegrityError, match="index is missing"):
        journal.get("entry-1", root=tmp_path)


def test_journal_rejects_private_operation_log_fields(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    operations = tmp_path / "decision_journal" / "operations.jsonl"
    record = json.loads(operations.read_text(encoding="utf-8"))
    record["thesis"] = "LEAK"
    operations.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(JournalIntegrityError, match="operation record"):
        journal.create(_entry(journal_entry_id="entry-2"), root=tmp_path)


def test_journal_rejects_invalid_operation_semantics(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    operations = tmp_path / "decision_journal" / "operations.jsonl"
    operations.write_text(
        json.dumps(
            {
                "operation": "arbitrary",
                "journal_entry_id": "entry-1",
                "checksum": "x",
                "schema_version": "anything",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(JournalIntegrityError, match="operation record"):
        journal.create(_entry(journal_entry_id="entry-2"), root=tmp_path)


def test_journal_rejects_index_payload_identity_mismatch(tmp_path: Path) -> None:
    journal = DecisionJournal()
    stored = journal.create(_entry(), root=tmp_path)
    payload_path = tmp_path / "decision_journal" / "entries" / "entry-1.json"
    other = stored.model_copy(update={"journal_entry_id": "other-id", "checksum": None})
    other = other.model_copy(update={"checksum": _checksum(other)})
    payload_path.write_text(other.model_dump_json(), encoding="utf-8")
    index_path = tmp_path / "decision_journal" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index[0]["checksum"] = other.checksum
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(JournalIntegrityError, match="identity"):
        journal.get("entry-1", root=tmp_path)


def test_journal_rejects_unsupported_persisted_schema(tmp_path: Path) -> None:
    journal = DecisionJournal()
    stored = journal.create(_entry(), root=tmp_path)
    payload_path = tmp_path / "decision_journal" / "entries" / "entry-1.json"
    unsupported = stored.model_copy(update={"schema_version": "999", "checksum": None})
    unsupported = unsupported.model_copy(update={"checksum": _checksum(unsupported)})
    payload_path.write_text(unsupported.model_dump_json(), encoding="utf-8")
    with pytest.raises(JournalIntegrityError, match="schema"):
        journal.get("entry-1", root=tmp_path)


def test_journal_rejects_false_superseded_operation(tmp_path: Path) -> None:
    journal = DecisionJournal()
    with pytest.raises(ValueError, match="must name its source"):
        journal.create(_entry(), root=tmp_path, operation="superseded")


def test_journal_lock_acquisition_error_preserves_foreign_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = DecisionJournal()
    lock_path = tmp_path / "decision_journal" / ".journal-write.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("foreign:token", encoding="ascii")

    def fail_open(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("denied")

    monkeypatch.setattr("etf_cockpit.data.decision_journal.os.open", fail_open)
    with pytest.raises(PermissionError):
        with journal._journal_write_lock(tmp_path):
            pass
    assert lock_path.read_text(encoding="ascii") == "foreign:token"


def test_journal_persisted_unsafe_index_id_is_integrity_error(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    index_path = tmp_path / "decision_journal" / "index.json"
    index_path.write_text(
        json.dumps([{"journal_entry_id": "../outside", "created_at": "now", "checksum": "0" * 64}]),
        encoding="utf-8",
    )
    with pytest.raises(JournalIntegrityError, match="index row id"):
        journal.list_entries(root=tmp_path)


def test_journal_supersede_bounds_long_source_id(tmp_path: Path) -> None:
    journal = DecisionJournal()
    source_id = "a" * 128
    original = journal.create(_entry(journal_entry_id=source_id), root=tmp_path)
    corrected = journal.supersede(source_id, original.model_copy(update={"thesis": "revised"}), root=tmp_path)
    assert len(corrected.journal_entry_id) <= 128


def test_journal_records_decision_lifecycle_evidence_and_immutable_links(tmp_path: Path) -> None:
    journal = DecisionJournal()
    stored = journal.create(
        _entry(
            decision_state="accepted",
            evidence_refs=["scoreboard:run-1", "backtest:signal_strategy"],
            alternatives=["hold_cash", "reduce_position"],
            confidence=0.78,
            invalidation_rules=["stale_price", "thesis_break"],
            review_date="2026-09-30",
            portfolio_context={"portfolio_id": "long-term", "weight_before": 0.12},
            instrument_ids=["VWCE"],
            model_run_ids=["model-run-1"],
            proposal_ids=["proposal-1"],
            order_ids=[],
        ),
        root=tmp_path,
    )

    loaded = journal.get(stored.journal_entry_id, root=tmp_path)
    assert loaded.decision_state == "accepted"
    assert loaded.evidence_refs == ["scoreboard:run-1", "backtest:signal_strategy"]
    assert loaded.alternatives == ["hold_cash", "reduce_position"]
    assert loaded.confidence == 0.78
    assert loaded.invalidation_rules == ["stale_price", "thesis_break"]
    assert loaded.review_date == "2026-09-30"
    assert loaded.portfolio_context["weight_before"] == 0.12
    assert loaded.model_run_ids == ["model-run-1"]
    assert loaded.proposal_ids == ["proposal-1"]
    assert loaded.order_ids == []

    summary = journal.export_summary(root=tmp_path)
    assert summary["decision_state_counts"] == {"accepted": 1}
    assert summary["linked_evidence_count"] == 2
    assert "private thesis text" not in json.dumps(summary)


def test_journal_rejects_invalid_decision_state_and_confidence(tmp_path: Path) -> None:
    journal = DecisionJournal()
    with pytest.raises(ValueError, match="decision state"):
        journal.create(_entry(decision_state="unknown"), root=tmp_path)
    with pytest.raises(ValueError):
        journal.create(_entry(confidence=1.5), root=tmp_path)


def test_journal_reads_legacy_v1_payloads_without_checksum_drift(tmp_path: Path) -> None:
    journal = DecisionJournal()
    legacy = {
        "journal_entry_id": "legacy-1",
        "created_at": "2026-07-12T00:00:00+00:00",
        "thesis": "legacy thesis",
        "decision": "review",
        "outcome": "pending",
        "private_notes": None,
        "supersedes_entry_id": None,
        "schema_version": "1.0",
    }
    legacy_entry = JournalEntry.model_validate(legacy)
    legacy["checksum"] = _checksum(legacy_entry)
    root = tmp_path / "legacy"
    entries_dir = root / "decision_journal" / "entries"
    entries_dir.mkdir(parents=True)
    (entries_dir / "legacy-1.json").write_text(json.dumps(legacy), encoding="utf-8")
    (root / "decision_journal" / "index.json").write_text(
        json.dumps(
            [
                {
                    "journal_entry_id": "legacy-1",
                    "created_at": legacy["created_at"],
                    "checksum": legacy["checksum"],
                }
            ]
        ),
        encoding="utf-8",
    )

    loaded = journal.get("legacy-1", root=root)

    assert loaded.schema_version == "1.0"
    assert loaded.decision_state == "pending"
    assert loaded.thesis == "legacy thesis"
