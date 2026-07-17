from __future__ import annotations

import json
import sqlite3

import duckdb
import pandas as pd
import pytest

from etf_cockpit.data.local_storage import (
    STORAGE_SCHEMA_VERSION,
    StorageSchemaError,
    TransactionalStore,
    initialise_storage,
    storage_layout,
)


def test_storage_bootstrap_is_idempotent_and_enables_safe_sqlite_pragmas(tmp_path):
    layout = initialise_storage(tmp_path)
    second = initialise_storage(tmp_path)

    assert layout == second == storage_layout(tmp_path)
    assert layout.transactional_path.is_file()
    with TransactionalStore(tmp_path) as store:
        assert store.connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.integrity().ok
        assert store.integrity().schema_version == STORAGE_SCHEMA_VERSION


def test_transactional_records_are_versioned_soft_deletable_and_recoverable(tmp_path):
    with TransactionalStore(tmp_path) as store:
        first = store.put("journal", "decision-1", {"decision": "hold", "confidence": 0.7})
        second = store.put("journal", "decision-1", {"decision": "review", "confidence": 0.8})

        assert first.revision == 1
        assert second.revision == 2
        assert store.get("journal", "decision-1").payload["decision"] == "review"
        assert store.delete("journal", "decision-1")
        assert store.get("journal", "decision-1") is None
        deleted = store.get("journal", "decision-1", include_deleted=True)
        assert deleted is not None and deleted.deleted_at is not None


def test_explicit_transaction_rolls_back_all_records_on_failure(tmp_path):
    with TransactionalStore(tmp_path) as store:
        with pytest.raises(RuntimeError, match="rollback me"):
            with store.transaction() as connection:
                connection.execute(
                    "INSERT INTO transactional_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("portfolio", "p-1", json.dumps({"cash": 100}), 1, "now", "now", None),
                )
                raise RuntimeError("rollback me")
        assert store.get("portfolio", "p-1") is None


def test_export_is_atomic_and_duckdb_readable(tmp_path):
    with TransactionalStore(tmp_path) as store:
        store.put("experiment", "run-1", {"status": "complete"})
        exported = store.export_parquet()

    frame = pd.read_parquet(exported.path)
    assert exported.rows == 1
    assert frame.loc[0, "entity_id"] == "run-1"
    with duckdb.connect(database=":memory:") as connection:
        assert connection.execute("SELECT count(*) FROM read_parquet(?)", [str(exported.path)]).fetchone()[0] == 1


def test_newer_storage_schema_fails_closed(tmp_path):
    layout = initialise_storage(tmp_path)
    with sqlite3.connect(layout.transactional_path) as connection:
        connection.execute("DELETE FROM schema_migrations")
        connection.execute(
            "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
            (STORAGE_SCHEMA_VERSION + 1, "future", "now"),
        )
    with pytest.raises(StorageSchemaError, match="newer than supported"):
        initialise_storage(tmp_path)
