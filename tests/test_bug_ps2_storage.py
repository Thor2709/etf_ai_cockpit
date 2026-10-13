"""Bughunt A/D (#959): storage CAS, tombstone revisions, migrations and nested recovery."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from etf_cockpit.core.migrations import MigrationContext, run_migrations
from etf_cockpit.data.local_storage import (
    STORAGE_SCHEMA_VERSION,
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
    storage_layout,
)
from etf_cockpit.operations.recovery import recover_incomplete_transactions

_TYPE = "ps2_storage"


def test_stale_expected_revision_cannot_resurrect_deleted_record(tmp_path: Path) -> None:
    """A018-N001 / D022-N001: a tombstone is a revision."""

    with TransactionalStore(tmp_path) as store:
        created = store.put(_TYPE, "x", {"v": 1}, expected_revision=0)
        assert store.delete(_TYPE, "x", expected_revision=created.revision)
        tombstone = store.get(_TYPE, "x", include_deleted=True)
        assert tombstone is not None and tombstone.deleted_at is not None
        assert tombstone.revision == created.revision + 1
        with pytest.raises(StorageRevisionConflict):
            store.put(_TYPE, "x", {"v": 2}, expected_revision=created.revision)
        with pytest.raises(StorageRevisionConflict):
            store.put_many_cas(
                [(_TYPE, "x", {"v": 3})], expected_revisions={(_TYPE, "x"): created.revision}
            )
        assert store.get(_TYPE, "x") is None
        # An explicit re-create against the tombstone revision is still allowed.
        revived = store.put(_TYPE, "x", {"v": 4}, expected_revision=tombstone.revision)
        assert revived.revision == tombstone.revision + 1
        assert store.get(_TYPE, "x").payload == {"v": 4}


def test_stale_delete_does_not_overwrite_newer_revision(tmp_path: Path) -> None:
    """D022-N002."""

    with TransactionalStore(tmp_path) as store:
        first = store.put(_TYPE, "x", {"v": 1})
        store.put(_TYPE, "x", {"v": 2}, expected_revision=first.revision)
        with pytest.raises(StorageRevisionConflict):
            store.delete(_TYPE, "x", expected_revision=first.revision)
        live = store.get(_TYPE, "x")
        assert live is not None and live.payload == {"v": 2} and live.deleted_at is None
        assert store.delete(_TYPE, "x", expected_revision=live.revision)
        assert store.delete(_TYPE, "x") is False


def test_json_equivalent_tuple_list_immutable_payload_does_not_conflict(tmp_path: Path) -> None:
    """A018-N002."""

    with TransactionalStore(tmp_path) as store:
        first = store.put_many([(_TYPE, "i", {"a": [1, 2]})], immutable=True)[0]
        again = store.put_many([(_TYPE, "i", {"a": (1, 2)})], immutable=True)[0]
        assert again.revision == first.revision == 1
        with store.transaction() as connection:
            same = store.put_in_transaction(connection, _TYPE, "i", {"a": (1, 2)}, immutable=True)
        assert same.revision == 1
        with pytest.raises(StorageRevisionConflict):
            store.put_many([(_TYPE, "i", {"a": (1, 3)})], immutable=True)


def _marker_only_store(root: Path, versions: range) -> Path:
    path = storage_layout(root).transactional_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?, ?, ?)",
            [(version, f"m{version}", "2026-01-01T00:00:00+00:00") for version in versions],
        )
        connection.commit()
    finally:
        connection.close()
    return path


def test_valid_sqlite_file_missing_mandatory_tables_is_rejected(tmp_path: Path) -> None:
    """D023-N003."""

    _marker_only_store(tmp_path, range(1, STORAGE_SCHEMA_VERSION + 1))
    with pytest.raises(StorageSchemaError, match="mandatory tables"):
        TransactionalStore(tmp_path)
    # A healthy store still opens and reports a clean integrity result.
    healthy = tmp_path / "healthy"
    with TransactionalStore(healthy) as store:
        assert store.integrity().ok
    with TransactionalStore(healthy) as store:
        store.connection.execute("DROP TABLE durable_job_events")
        store.connection.commit()
        assert not store.integrity().ok
    with pytest.raises(StorageSchemaError, match="durable_job_events"):
        TransactionalStore(healthy)


def _write_journal(base: Path, payload: dict[str, object] | str) -> Path:
    journal = base / ".atomic-transactions" / "tx-1" / "journal.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return journal


def test_quarantined_store_and_unsupported_schema_version_fail_migrations(tmp_path: Path) -> None:
    """D021-N001 / D121-N002."""

    quarantined = tmp_path / "quarantined"
    _write_journal(quarantined / "data", {"schema_version": 1, "transaction_id": "tx-1", "state": "committing"})
    context = MigrationContext(root=quarantined, backup_root=quarantined / "backups")
    with pytest.raises(OSError, match="migration blocked"):
        run_migrations(context)
    assert not context.state_path.exists()
    assert not context.metadata_root.exists()

    future = tmp_path / "future"
    context = MigrationContext(root=future, backup_root=future / "backups")
    context.state_path.parent.mkdir(parents=True)
    context.state_path.write_text(json.dumps({"schema_version": 999, "applied": []}), encoding="utf-8")
    before = context.state_path.read_bytes()
    with pytest.raises(ValueError, match="unsupported migration state schema_version 999"):
        run_migrations(context)
    assert context.state_path.read_bytes() == before
    assert not context.metadata_root.exists()


@pytest.mark.parametrize("folder", ["models", "exports"])
def test_recovery_finds_nested_models_and_exports_journals(tmp_path: Path, folder: str) -> None:
    """D121-N003."""

    (tmp_path / "data").mkdir()
    journal = _write_journal(tmp_path / folder / "nested", "{not json")
    results = recover_incomplete_transactions(tmp_path, event_path=None)
    assert [result.journal_path.resolve() for result in results] == [journal.resolve()]
    assert results[0].state == "recovery_required"


def test_recovery_root_scan_fallback_survives_models_or_exports_only_root(tmp_path: Path) -> None:
    """D121-N003: no data/ or configs/ keeps the whole-root scan alongside models/exports."""

    (tmp_path / "models").mkdir()
    (tmp_path / "exports").mkdir()
    journal = _write_journal(tmp_path / "artifacts" / "x", "{not json")
    results = recover_incomplete_transactions(tmp_path, event_path=None)
    assert [result.journal_path.resolve() for result in results] == [journal.resolve()]
