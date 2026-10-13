from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, cast

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file


STORAGE_SCHEMA_VERSION = 7


class StorageSchemaError(RuntimeError):
    """Raised when a local store cannot be read safely by this application."""


class StorageRevisionConflict(RuntimeError):
    """Raised when a stale writer attempts to replace newer local state."""


@dataclass(frozen=True)
class StorageLayout:
    root: Path

    @property
    def transactional_path(self) -> Path:
        return self.root / "data" / "storage" / "cockpit.sqlite3"

    @property
    def analytics_root(self) -> Path:
        return self.root / "data" / "analytics"

    @property
    def snapshot_root(self) -> Path:
        return self.root / "data" / "snapshots"

    @property
    def export_root(self) -> Path:
        return self.root / "exports" / "storage"


@dataclass(frozen=True)
class StoredRecord:
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    revision: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None


@dataclass(frozen=True)
class StorageIntegrity:
    ok: bool
    schema_version: int
    sqlite_integrity: str
    foreign_key_violations: tuple[str, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class StorageExport:
    path: Path
    rows: int
    sha256: str


def storage_layout(root: Path) -> StorageLayout:
    return StorageLayout(Path(root).resolve())


def transactional_store_initialized(root: Path) -> bool:
    """Return whether an existing store has its transactional schema marker."""

    path = storage_layout(root).transactional_path
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if "schema_migrations" not in tables or "transactional_records" not in tables:
                return False
            marker = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return marker is not None and int(marker[0] or 0) > 0
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise StorageSchemaError(f"transactional store schema marker is unreadable: {exc}") from exc


def connect_storage(root: Path) -> sqlite3.Connection:
    layout = storage_layout(root)
    layout.transactional_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(layout.transactional_path, timeout=30.0)
    try:
        connection.row_factory = sqlite3.Row
        _register_ledger_sql_functions(connection)
        # Set the busy handler before the WAL transition.  Two first-time local
        # writers may open the same store concurrently and journal_mode itself
        # can need the database write lock.
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        _enable_wal(connection)
        connection.execute("PRAGMA synchronous = NORMAL")
    except Exception:
        connection.close()
        raise
    return connection


def connect_local_database(db_path: Path, *, timeout: float = 30.0) -> sqlite3.Connection:
    """Open a local SQLite file in autocommit mode with foreign keys and a busy timeout.

    Local persistence only; used by paper/order bookkeeping so no module in a broker or
    order context opens connections itself (static execution-boundary rule).
    """
    connection = sqlite3.connect(db_path, timeout=timeout, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    return connection


def connect_storage_read_only(root: Path) -> sqlite3.Connection:
    """Open one verified in-memory snapshot without touching source storage."""

    layout = storage_layout(root)
    source = layout.transactional_path
    if not source.is_file():
        raise StorageSchemaError(f"transactional store is missing: {source}")
    sidecars = tuple(Path(f"{source}{suffix}") for suffix in ("-wal", "-shm", "-journal"))
    if any(path.exists() for path in sidecars):
        raise StorageSchemaError("transactional store has an active SQLite journal")
    try:
        snapshot = source.read_bytes()
        verified = source.read_bytes()
    except OSError as exc:
        raise StorageSchemaError(f"transactional store snapshot is unavailable: {exc}") from exc
    if snapshot != verified or any(path.exists() for path in sidecars):
        raise StorageSchemaError("transactional store changed while its snapshot was read")
    if len(snapshot) < 100 or snapshot[:16] != b"SQLite format 3\x00":
        raise StorageSchemaError("transactional store snapshot has an invalid SQLite header")
    memory_image = bytearray(snapshot)
    if memory_image[18] not in {1, 2} or memory_image[19] not in {1, 2}:
        raise StorageSchemaError("transactional store snapshot has invalid journal metadata")
    # The source store uses WAL.  The detached image has no WAL file by
    # construction, so mark only the in-memory copy as a rollback-journal
    # image before deserialising it.
    memory_image[18] = 1
    memory_image[19] = 1

    connection = sqlite3.connect(":memory:", timeout=30.0)
    try:
        connection.deserialize(bytes(memory_image))
        connection.row_factory = sqlite3.Row
        _register_ledger_sql_functions(connection)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
    except Exception:
        connection.close()
        raise
    return connection


def _enable_wal(connection: sqlite3.Connection) -> None:
    """Enable WAL with a bounded retry for SQLite's journal-mode lock race."""

    deadline = time.monotonic() + 30.0
    while True:
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).casefold() or time.monotonic() >= deadline:
                raise
            time.sleep(0.025)


def initialise_storage(root: Path) -> StorageLayout:
    layout = storage_layout(root)
    for path in (layout.transactional_path.parent, layout.analytics_root, layout.snapshot_root, layout.export_root):
        path.mkdir(parents=True, exist_ok=True)
    connection = connect_storage(layout.root)
    try:
        _apply_migrations(connection)
    finally:
        connection.close()
    return layout


def _apply_migrations(connection: sqlite3.Connection) -> None:
    migrations = (
        (1, "transactional_records_v1", _migration_v1),
        (2, "analytical_catalog_v1", _migration_v2),
        (3, "bitemporal_observations_v1", _migration_v3),
        (4, "durable_workflows_v1", _migration_v4),
        (5, "double_entry_ledger_v1", _migration_v5),
        (6, "ledger_authority_and_integrity_v2", _migration_v6),
        (7, "ledger_positions_and_settlement_v1", _migration_v7),
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    applied = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
    _validate_storage_schema(applied)
    if all(version in applied for version, _name, _migration in migrations):
        return

    # Only pending migrations take the write lock.  Re-read after acquiring it
    # because another constructor may have completed the same first-open work.
    try:
        connection.execute("BEGIN IMMEDIATE")
        applied = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
        _validate_storage_schema(applied)
        for version, name, migration in migrations:
            if version in applied:
                continue
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, _utc_now()),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _validate_storage_schema(applied: set[int]) -> None:
    highest = max(applied, default=0)
    if highest > STORAGE_SCHEMA_VERSION:
        raise StorageSchemaError(
            f"storage schema {highest} is newer than supported version {STORAGE_SCHEMA_VERSION}"
        )


def _migration_v1(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE transactional_records (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            PRIMARY KEY(entity_type, entity_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX transactional_records_type_updated ON transactional_records(entity_type, updated_at)"
    )


def _migration_v2(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE analytical_generations (
            dataset_id TEXT NOT NULL,
            generation_id TEXT NOT NULL,
            relative_path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            row_count INTEGER NOT NULL CHECK (row_count >= 0),
            columns_json TEXT NOT NULL,
            stable_id_count INTEGER NOT NULL CHECK (stable_id_count >= 0),
            run_id_count INTEGER NOT NULL CHECK (run_id_count >= 0),
            status TEXT NOT NULL CHECK (status IN ('publishing', 'published')),
            committed_at TEXT NOT NULL,
            PRIMARY KEY(dataset_id, generation_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX analytical_generations_latest ON analytical_generations(dataset_id, status, committed_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE analytical_generation_keys (
            dataset_id TEXT NOT NULL,
            generation_id TEXT NOT NULL,
            stable_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            PRIMARY KEY(dataset_id, generation_id, stable_id, run_id),
            FOREIGN KEY(dataset_id, generation_id)
                REFERENCES analytical_generations(dataset_id, generation_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE storage_operations (
            operation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            detail_json TEXT NOT NULL
        )
        """
    )


def _migration_v3(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE bitemporal_observations (
            observation_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            stable_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            value_json TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            published_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            revised_at TEXT,
            revision INTEGER NOT NULL CHECK (revision > 0),
            source_id TEXT NOT NULL,
            source_checksum TEXT NOT NULL,
            timezone_confidence TEXT NOT NULL CHECK (timezone_confidence IN ('exact', 'normalised', 'unknown')),
            availability_confidence TEXT NOT NULL CHECK (availability_confidence IN ('exact', 'inferred')),
            status TEXT NOT NULL CHECK (status IN ('active', 'retracted', 'superseded')),
            UNIQUE(dataset_id, stable_id, source_id, revision)
        )
        """
    )
    connection.execute(
        "CREATE INDEX bitemporal_observations_as_of ON bitemporal_observations(dataset_id, stable_id, available_at, revision)"
    )
    connection.execute(
        "CREATE INDEX bitemporal_observations_entity ON bitemporal_observations(dataset_id, entity_id, available_at)"
    )
    connection.execute(
        """
        CREATE TRIGGER bitemporal_observations_append_only_update
        BEFORE UPDATE ON bitemporal_observations
        BEGIN
            SELECT RAISE(ABORT, 'bitemporal observations are append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER bitemporal_observations_append_only_delete
        BEFORE DELETE ON bitemporal_observations
        BEGIN
            SELECT RAISE(ABORT, 'bitemporal observations are append-only');
        END
        """
    )


def _migration_v4(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE workflow_runs (
            workflow_id TEXT PRIMARY KEY,
            workflow_type TEXT NOT NULL,
            label TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'blocked')),
            dedupe_key TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            outputs_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT NOT NULL DEFAULT '',
            error_fingerprint TEXT,
            resource_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX workflow_runs_active_dedupe
        ON workflow_runs(dedupe_key)
        WHERE status IN ('queued', 'running')
        """
    )
    connection.execute(
        """
        CREATE TABLE durable_jobs (
            job_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            job_key TEXT NOT NULL,
            label TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'blocked')),
            input_hash TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            outputs_json TEXT NOT NULL,
            resource_json TEXT NOT NULL,
            max_retries INTEGER NOT NULL CHECK (max_retries >= 0),
            retry_count INTEGER NOT NULL CHECK (retry_count >= 0),
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            checkpoint_json TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
            error_message TEXT NOT NULL DEFAULT '',
            error_fingerprint TEXT,
            retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            UNIQUE(workflow_id, job_key),
            FOREIGN KEY(workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute("CREATE INDEX durable_jobs_ready ON durable_jobs(status, created_at)")
    connection.execute("CREATE INDEX durable_jobs_workflow ON durable_jobs(workflow_id, created_at)")
    connection.execute(
        """
        CREATE TABLE durable_job_dependencies (
            job_id TEXT NOT NULL,
            dependency_job_id TEXT NOT NULL,
            PRIMARY KEY(job_id, dependency_job_id),
            FOREIGN KEY(job_id) REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
            FOREIGN KEY(dependency_job_id) REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
            CHECK(job_id <> dependency_job_id)
        )
        """
    )
    connection.execute("CREATE INDEX durable_job_dependencies_dependency ON durable_job_dependencies(dependency_job_id)")
    connection.execute(
        """
        CREATE TABLE durable_job_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            job_id TEXT,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE,
            FOREIGN KEY(workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
            FOREIGN KEY(job_id) REFERENCES durable_jobs(job_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute("CREATE INDEX durable_job_events_workflow ON durable_job_events(workflow_id, event_id)")


def _migration_v5(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE ledger_accounts (
            account_id TEXT PRIMARY KEY,
            parent_account_id TEXT,
            name TEXT NOT NULL CHECK(length(trim(name)) > 0),
            account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'income', 'expense')),
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            created_at TEXT NOT NULL,
            UNIQUE(account_id, authority),
            FOREIGN KEY(parent_account_id, authority)
                REFERENCES ledger_accounts(account_id, authority),
            CHECK(parent_account_id IS NULL OR parent_account_id <> account_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ledger_entries (
            entry_id TEXT PRIMARY KEY,
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            effective_at TEXT NOT NULL CHECK(length(trim(effective_at)) > 0),
            recorded_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reversal_of_entry_id TEXT UNIQUE,
            status TEXT NOT NULL CHECK(status IN ('posting', 'posted')),
            UNIQUE(entry_id, authority),
            FOREIGN KEY(reversal_of_entry_id, authority)
                REFERENCES ledger_entries(entry_id, authority),
            CHECK(reversal_of_entry_id IS NULL OR reversal_of_entry_id <> entry_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ledger_postings (
            entry_id TEXT NOT NULL,
            line_number INTEGER NOT NULL CHECK(line_number > 0),
            account_id TEXT NOT NULL,
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            currency TEXT NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]'),
            debit_amount TEXT NOT NULL,
            credit_amount TEXT NOT NULL,
            PRIMARY KEY(entry_id, line_number),
            FOREIGN KEY(entry_id, authority)
                REFERENCES ledger_entries(entry_id, authority),
            FOREIGN KEY(account_id, authority)
                REFERENCES ledger_accounts(account_id, authority),
            CHECK(
                (debit_amount = '0' AND credit_amount <> '0') OR
                (credit_amount = '0' AND debit_amount <> '0')
            )
        )
        """
    )
    connection.execute("CREATE INDEX ledger_entries_effective ON ledger_entries(authority, effective_at, entry_id)")
    connection.execute("CREATE INDEX ledger_postings_account ON ledger_postings(account_id, currency, entry_id)")
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_post_transition
        BEFORE UPDATE ON ledger_entries
        WHEN NOT (
            OLD.status = 'posting' AND NEW.status = 'posted' AND
            NEW.entry_id IS OLD.entry_id AND
            NEW.authority IS OLD.authority AND
            NEW.effective_at IS OLD.effective_at AND
            NEW.recorded_at IS OLD.recorded_at AND
            NEW.description IS OLD.description AND
            NEW.reversal_of_entry_id IS OLD.reversal_of_entry_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries are immutable after posting');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_no_delete
        BEFORE DELETE ON ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries cannot be deleted');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_insert_while_posting
        BEFORE INSERT ON ledger_postings
        WHEN (SELECT status FROM ledger_entries WHERE entry_id = NEW.entry_id) <> 'posting'
        BEGIN
            SELECT RAISE(ABORT, 'postings can only be added while an entry is being posted');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_no_update
        BEFORE UPDATE ON ledger_postings
        BEGIN
            SELECT RAISE(ABORT, 'ledger postings are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_no_delete
        BEFORE DELETE ON ledger_postings
        BEGIN
            SELECT RAISE(ABORT, 'ledger postings cannot be deleted');
        END
        """
    )


def _migration_v6(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA defer_foreign_keys = ON")
    for trigger in (
        "ledger_entries_post_transition",
        "ledger_entries_no_delete",
        "ledger_postings_insert_while_posting",
        "ledger_postings_no_update",
        "ledger_postings_no_delete",
    ):
        connection.execute(f"DROP TRIGGER {trigger}")
    connection.execute("DROP INDEX ledger_entries_effective")
    connection.execute("DROP INDEX ledger_postings_account")
    connection.execute("ALTER TABLE ledger_postings RENAME TO ledger_postings_v5")
    connection.execute("ALTER TABLE ledger_entries RENAME TO ledger_entries_v5")
    connection.execute("ALTER TABLE ledger_accounts RENAME TO ledger_accounts_v5")

    connection.execute(
        """
        CREATE TABLE ledger_accounts (
            account_id TEXT NOT NULL,
            parent_account_id TEXT,
            name TEXT NOT NULL CHECK(length(trim(name)) > 0),
            account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'income', 'expense')),
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(account_id, authority),
            FOREIGN KEY(parent_account_id, authority)
                REFERENCES ledger_accounts(account_id, authority),
            CHECK(parent_account_id IS NULL OR parent_account_id <> account_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ledger_entries (
            entry_id TEXT NOT NULL,
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            effective_at TEXT NOT NULL CHECK(length(trim(effective_at)) > 0),
            recorded_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reversal_of_entry_id TEXT,
            status TEXT NOT NULL CHECK(status IN ('posting', 'posted')),
            PRIMARY KEY(entry_id, authority),
            UNIQUE(reversal_of_entry_id, authority),
            FOREIGN KEY(reversal_of_entry_id, authority)
                REFERENCES ledger_entries(entry_id, authority),
            CHECK(reversal_of_entry_id IS NULL OR reversal_of_entry_id <> entry_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ledger_postings (
            entry_id TEXT NOT NULL,
            line_number INTEGER NOT NULL CHECK(line_number > 0),
            account_id TEXT NOT NULL,
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            currency TEXT NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]'),
            debit_amount TEXT NOT NULL
                CHECK(ledger_decimal_valid(debit_amount) = 1),
            credit_amount TEXT NOT NULL
                CHECK(ledger_decimal_valid(credit_amount) = 1),
            PRIMARY KEY(entry_id, authority, line_number),
            FOREIGN KEY(entry_id, authority)
                REFERENCES ledger_entries(entry_id, authority),
            FOREIGN KEY(account_id, authority)
                REFERENCES ledger_accounts(account_id, authority),
            CHECK(ledger_posting_amounts_valid(debit_amount, credit_amount) = 1)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO ledger_accounts(
            account_id, parent_account_id, name, account_type, authority, created_at
        )
        SELECT account_id, parent_account_id, name, account_type, authority, created_at
        FROM ledger_accounts_v5
        """
    )
    connection.execute(
        """
        INSERT INTO ledger_entries(
            entry_id, authority, effective_at, recorded_at, description,
            reversal_of_entry_id, status
        )
        SELECT entry_id, authority, effective_at, recorded_at, description,
            reversal_of_entry_id, status
        FROM ledger_entries_v5
        """
    )
    connection.execute(
        """
        INSERT INTO ledger_postings(
            entry_id, line_number, account_id, authority, currency, debit_amount, credit_amount
        )
        SELECT entry_id, line_number, account_id, authority, currency, debit_amount, credit_amount
        FROM ledger_postings_v5
        """
    )
    connection.execute("DROP TABLE ledger_postings_v5")
    connection.execute("DROP TABLE ledger_entries_v5")
    connection.execute("DROP TABLE ledger_accounts_v5")

    invalid_entry = connection.execute(
        """
        SELECT entry_id, authority
        FROM ledger_entries AS entry
        WHERE status = 'posted'
          AND (
              (SELECT COUNT(*) FROM ledger_postings
               WHERE entry_id = entry.entry_id AND authority = entry.authority) < 2
              OR EXISTS (
                  SELECT currency
                  FROM ledger_postings
                  WHERE entry_id = entry.entry_id AND authority = entry.authority
                  GROUP BY currency
                  HAVING ledger_currency_balanced(debit_amount, credit_amount) <> 1
              )
          )
        LIMIT 1
        """
    ).fetchone()
    if invalid_entry is not None:
        raise sqlite3.IntegrityError(
            f"cannot migrate unbalanced posted ledger entry: {invalid_entry[1]}:{invalid_entry[0]}"
        )

    connection.execute(
        "CREATE INDEX ledger_entries_effective ON ledger_entries(authority, effective_at, entry_id)"
    )
    connection.execute(
        "CREATE INDEX ledger_postings_account ON ledger_postings(authority, account_id, currency, entry_id)"
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_posting_only
        BEFORE INSERT ON ledger_entries
        WHEN NEW.status <> 'posting'
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries must be inserted in posting status');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_post_transition
        BEFORE UPDATE ON ledger_entries
        WHEN NOT (
            OLD.status = 'posting' AND NEW.status = 'posted' AND
            NEW.entry_id IS OLD.entry_id AND
            NEW.authority IS OLD.authority AND
            NEW.effective_at IS OLD.effective_at AND
            NEW.recorded_at IS OLD.recorded_at AND
            NEW.description IS OLD.description AND
            NEW.reversal_of_entry_id IS OLD.reversal_of_entry_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries are immutable after posting');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_validate_posted
        BEFORE UPDATE OF status ON ledger_entries
        WHEN OLD.status = 'posting' AND NEW.status = 'posted'
          AND (
              (SELECT COUNT(*) FROM ledger_postings
               WHERE entry_id = NEW.entry_id AND authority = NEW.authority) < 2
              OR EXISTS (
                  SELECT currency
                  FROM ledger_postings
                  WHERE entry_id = NEW.entry_id AND authority = NEW.authority
                  GROUP BY currency
                  HAVING ledger_currency_balanced(debit_amount, credit_amount) <> 1
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'ledger entry postings must balance by currency');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_no_delete
        BEFORE DELETE ON ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries cannot be deleted');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_validate_insert
        BEFORE INSERT ON ledger_postings
        WHEN ledger_posting_amounts_valid(NEW.debit_amount, NEW.credit_amount) <> 1
        BEGIN
            SELECT RAISE(ABORT, 'posting amounts must be finite non-negative decimals with one positive side');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_insert_while_posting
        BEFORE INSERT ON ledger_postings
        WHEN COALESCE(
            (SELECT status FROM ledger_entries
             WHERE entry_id = NEW.entry_id AND authority = NEW.authority),
            ''
        ) <> 'posting'
        BEGIN
            SELECT RAISE(ABORT, 'postings can only be added while an entry is being posted');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_no_update
        BEFORE UPDATE ON ledger_postings
        BEGIN
            SELECT RAISE(ABORT, 'ledger postings are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_no_delete
        BEFORE DELETE ON ledger_postings
        BEGIN
            SELECT RAISE(ABORT, 'ledger postings cannot be deleted');
        END
        """
    )


def _migration_v7(connection: sqlite3.Connection) -> None:
    """Add explicit cash/position dimensions without rewriting posted facts."""

    connection.execute("PRAGMA defer_foreign_keys = ON")
    for trigger in (
        "ledger_entries_posting_only",
        "ledger_entries_post_transition",
        "ledger_entries_validate_posted",
        "ledger_entries_no_delete",
        "ledger_postings_insert_while_posting",
        "ledger_postings_validate_insert",
        "ledger_postings_no_update",
        "ledger_postings_no_delete",
    ):
        connection.execute(f"DROP TRIGGER {trigger}")
    connection.execute("DROP INDEX ledger_entries_effective")
    connection.execute("DROP INDEX ledger_postings_account")
    connection.execute("ALTER TABLE ledger_postings RENAME TO ledger_postings_v6")
    connection.execute("ALTER TABLE ledger_entries RENAME TO ledger_entries_v6")
    connection.execute("ALTER TABLE ledger_accounts RENAME TO ledger_accounts_v6")

    connection.execute(
        """
        CREATE TABLE ledger_accounts (
            account_id TEXT NOT NULL,
            parent_account_id TEXT,
            name TEXT NOT NULL CHECK(length(trim(name)) > 0),
            account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'income', 'expense')),
            account_role TEXT NOT NULL DEFAULT 'general' CHECK(account_role IN ('general', 'cash', 'position')),
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(account_id, authority),
            FOREIGN KEY(parent_account_id, authority)
                REFERENCES ledger_accounts(account_id, authority),
            CHECK(parent_account_id IS NULL OR parent_account_id <> account_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ledger_entries (
            entry_id TEXT NOT NULL,
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            effective_at TEXT NOT NULL CHECK(length(trim(effective_at)) > 0),
            settlement_at TEXT CHECK(settlement_at IS NULL OR length(trim(settlement_at)) > 0),
            recorded_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reversal_of_entry_id TEXT,
            status TEXT NOT NULL CHECK(status IN ('posting', 'posted')),
            PRIMARY KEY(entry_id, authority),
            UNIQUE(reversal_of_entry_id, authority),
            FOREIGN KEY(reversal_of_entry_id, authority)
                REFERENCES ledger_entries(entry_id, authority),
            CHECK(reversal_of_entry_id IS NULL OR reversal_of_entry_id <> entry_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ledger_postings (
            entry_id TEXT NOT NULL,
            line_number INTEGER NOT NULL CHECK(line_number > 0),
            account_id TEXT NOT NULL,
            authority TEXT NOT NULL CHECK(authority IN ('paper', 'broker')),
            currency TEXT,
            debit_amount TEXT NOT NULL CHECK(ledger_decimal_valid(debit_amount) = 1),
            credit_amount TEXT NOT NULL CHECK(ledger_decimal_valid(credit_amount) = 1),
            instrument_id TEXT,
            quantity_delta TEXT,
            lot_id TEXT,
            PRIMARY KEY(entry_id, authority, line_number),
            FOREIGN KEY(entry_id, authority)
                REFERENCES ledger_entries(entry_id, authority),
            FOREIGN KEY(account_id, authority)
                REFERENCES ledger_accounts(account_id, authority),
            CHECK(
                (currency IS NOT NULL AND currency GLOB '[A-Z][A-Z][A-Z]' AND
                 ledger_posting_amounts_valid(debit_amount, credit_amount) = 1)
                OR
                (currency IS NULL AND debit_amount = '0' AND credit_amount = '0' AND
                 instrument_id IS NOT NULL AND quantity_delta IS NOT NULL AND
                 ledger_quantity_nonzero_valid(quantity_delta) = 1)
            ),
            CHECK(
                (instrument_id IS NULL AND quantity_delta IS NULL AND lot_id IS NULL)
                OR
                (instrument_id IS NOT NULL AND length(trim(instrument_id)) > 0 AND
                 quantity_delta IS NOT NULL AND ledger_signed_decimal_valid(quantity_delta) = 1 AND
                 (lot_id IS NULL OR length(trim(lot_id)) > 0))
            )
        )
        """
    )
    connection.execute(
        """
        INSERT INTO ledger_accounts(
            account_id, parent_account_id, name, account_type, account_role, authority, created_at
        )
        SELECT account_id, parent_account_id, name, account_type, 'general', authority, created_at
        FROM ledger_accounts_v6
        """
    )
    connection.execute(
        """
        INSERT INTO ledger_entries(
            entry_id, authority, effective_at, settlement_at, recorded_at,
            description, reversal_of_entry_id, status
        )
        SELECT entry_id, authority, effective_at, NULL, recorded_at,
            description, reversal_of_entry_id, status
        FROM ledger_entries_v6
        """
    )
    connection.execute(
        """
        INSERT INTO ledger_postings(
            entry_id, line_number, account_id, authority, currency, debit_amount,
            credit_amount, instrument_id, quantity_delta, lot_id
        )
        SELECT entry_id, line_number, account_id, authority, currency, debit_amount,
            credit_amount, NULL, NULL, NULL
        FROM ledger_postings_v6
        """
    )
    connection.execute("DROP TABLE ledger_postings_v6")
    connection.execute("DROP TABLE ledger_entries_v6")
    connection.execute("DROP TABLE ledger_accounts_v6")

    connection.execute(
        "CREATE INDEX ledger_entries_effective ON ledger_entries(authority, effective_at, entry_id)"
    )
    connection.execute(
        "CREATE INDEX ledger_postings_account ON ledger_postings(authority, account_id, currency, entry_id)"
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_posting_only
        BEFORE INSERT ON ledger_entries
        WHEN NEW.status <> 'posting'
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries must be inserted in posting status');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_post_transition
        BEFORE UPDATE ON ledger_entries
        WHEN NOT (
            OLD.status = 'posting' AND NEW.status = 'posted' AND
            NEW.entry_id IS OLD.entry_id AND NEW.authority IS OLD.authority AND
            NEW.effective_at IS OLD.effective_at AND NEW.settlement_at IS OLD.settlement_at AND
            NEW.recorded_at IS OLD.recorded_at AND NEW.description IS OLD.description AND
            NEW.reversal_of_entry_id IS OLD.reversal_of_entry_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries are immutable after posting');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_validate_posted
        BEFORE UPDATE OF status ON ledger_entries
        WHEN OLD.status = 'posting' AND NEW.status = 'posted'
          AND (
              (SELECT COUNT(*) FROM ledger_postings
               WHERE entry_id = NEW.entry_id AND authority = NEW.authority) < 2
              OR EXISTS (
                  SELECT currency FROM ledger_postings
                  WHERE entry_id = NEW.entry_id AND authority = NEW.authority
                  GROUP BY currency
                  HAVING ledger_currency_balanced(debit_amount, credit_amount) <> 1
              )
              OR EXISTS (
                  SELECT instrument_id, lot_id FROM ledger_postings
                  WHERE entry_id = NEW.entry_id AND authority = NEW.authority
                    AND instrument_id IS NOT NULL
                  GROUP BY instrument_id, lot_id
                  HAVING ledger_quantity_balanced(quantity_delta) <> 1
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'ledger entry postings must balance by currency and quantity');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_entries_no_delete
        BEFORE DELETE ON ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'ledger entries cannot be deleted');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_validate_insert
        BEFORE INSERT ON ledger_postings
        WHEN NOT (
            (NEW.currency IS NOT NULL AND
             ledger_posting_amounts_valid(NEW.debit_amount, NEW.credit_amount) = 1)
            OR
            (NEW.currency IS NULL AND NEW.debit_amount = '0' AND NEW.credit_amount = '0' AND
             NEW.instrument_id IS NOT NULL AND NEW.quantity_delta IS NOT NULL AND
             ledger_quantity_nonzero_valid(NEW.quantity_delta) = 1)
        )
        BEGIN
            SELECT RAISE(ABORT, 'ledger posting must contain valid money or quantity');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_insert_while_posting
        BEFORE INSERT ON ledger_postings
        WHEN COALESCE(
            (SELECT status FROM ledger_entries
             WHERE entry_id = NEW.entry_id AND authority = NEW.authority),
            ''
        ) <> 'posting'
        BEGIN
            SELECT RAISE(ABORT, 'postings can only be added while an entry is being posted');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_no_update
        BEFORE UPDATE ON ledger_postings
        BEGIN
            SELECT RAISE(ABORT, 'ledger postings are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ledger_postings_no_delete
        BEFORE DELETE ON ledger_postings
        BEGIN
            SELECT RAISE(ABORT, 'ledger postings cannot be deleted');
        END
        """
    )


class TransactionalStore:
    """Small ACID store for user-owned state; analytical data remains Parquet."""

    def __init__(self, root: Path, *, read_only: bool = False):
        self.read_only = read_only
        if read_only:
            self.layout = storage_layout(root)
            self.connection = connect_storage_read_only(self.layout.root)
        else:
            self.layout = initialise_storage(root)
            self.connection = connect_storage(self.layout.root)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> TransactionalStore:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Expose one explicit transaction for multi-record updates."""

        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    @contextmanager
    def read_transaction(self) -> Iterator[sqlite3.Connection]:
        """Pin multiple reads to one SQLite snapshot without blocking WAL writers."""

        try:
            self.connection.execute("BEGIN")
            yield self.connection
        except Exception:
            self.connection.rollback()
            raise
        else:
            if self.read_only:
                self.connection.rollback()
            else:
                self.connection.commit()

    def put(
        self,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> StoredRecord:
        entity_type, entity_id = _validate_identity(entity_type, entity_id)
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        if expected_revision is not None and (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        with self.transaction() as connection:
            stored = self.put_in_transaction(
                connection,
                entity_type,
                entity_id,
                payload,
                expected_revision=expected_revision,
            )
        return stored

    def put_in_transaction(
        self,
        connection: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
        *,
        expected_revision: int | None = None,
        immutable: bool = False,
    ) -> StoredRecord:
        """Put one record into the caller's already-open transaction."""

        if connection is not self.connection or not connection.in_transaction:
            raise ValueError("put_in_transaction requires this store's open transaction")
        entity_type, entity_id = _validate_identity(entity_type, entity_id)
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        if expected_revision is not None and (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        now = _utc_now()
        previous = connection.execute(
            "SELECT revision, created_at, payload_json, updated_at FROM transactional_records WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        ).fetchone()
        if previous and immutable:
            if dict(json.loads(str(previous[2]))) != dict(payload):
                raise StorageRevisionConflict(
                    f"immutable record already exists with different content: {entity_id}"
                )
            return StoredRecord(
                entity_type,
                entity_id,
                dict(json.loads(str(previous[2]))),
                int(previous[0]),
                str(previous[1]),
                str(previous[3]),
            )
        current_revision = int(previous[0]) if previous else 0
        if expected_revision is not None and current_revision != expected_revision:
            raise StorageRevisionConflict(
                f"expected revision {expected_revision}, current revision is {current_revision}"
            )
        revision = current_revision + 1
        created_at = str(previous[1]) if previous else now
        connection.execute(
            """
            INSERT INTO transactional_records
                (entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                revision = excluded.revision,
                updated_at = excluded.updated_at,
                deleted_at = NULL
            """,
            (entity_type, entity_id, encoded, revision, created_at, now),
        )
        return StoredRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            payload=dict(json.loads(encoded)),
            revision=revision,
            created_at=created_at,
            updated_at=now,
        )

    def put_many(
        self,
        records: Sequence[tuple[str, str, Mapping[str, Any]]],
        *,
        immutable: bool = False,
    ) -> tuple[StoredRecord, ...]:
        """Write a batch atomically, optionally preserving immutable records."""

        prepared = []
        for entity_type, entity_id, payload in records:
            entity_type, entity_id = _validate_identity(entity_type, entity_id)
            if not isinstance(payload, Mapping):
                raise TypeError("payload must be a mapping")
            encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            prepared.append((entity_type, entity_id, dict(payload), encoded))
        now = _utc_now()
        stored: list[StoredRecord] = []
        with self.transaction() as connection:
            for entity_type, entity_id, payload, encoded in prepared:
                previous = connection.execute(
                    "SELECT revision, created_at, payload_json, updated_at FROM transactional_records WHERE entity_type = ? AND entity_id = ?",
                    (entity_type, entity_id),
                ).fetchone()
                if previous and immutable:
                    if dict(json.loads(str(previous[2]))) != payload:
                        raise StorageRevisionConflict(f"immutable record already exists with different content: {entity_id}")
                    stored.append(StoredRecord(entity_type, entity_id, payload, int(previous[0]), str(previous[1]), str(previous[3])))
                    continue
                current_revision = int(previous[0]) if previous else 0
                revision = current_revision + 1
                created_at = str(previous[1]) if previous else now
                connection.execute(
                    """
                    INSERT INTO transactional_records
                        (entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        revision = excluded.revision,
                        updated_at = excluded.updated_at,
                        deleted_at = NULL
                    """,
                    (entity_type, entity_id, encoded, revision, created_at, now),
                )
                stored.append(StoredRecord(entity_type, entity_id, payload, revision, created_at, now))
        return tuple(stored)

    def put_many_cas(
        self,
        records: Sequence[tuple[str, str, Mapping[str, Any]]],
        *,
        expected_revisions: Mapping[tuple[str, str], int],
    ) -> tuple[StoredRecord, ...]:
        """Atomically publish a small batch with an expected revision per row."""

        prepared = []
        for entity_type, entity_id, payload in records:
            entity_type, entity_id = _validate_identity(entity_type, entity_id)
            if not isinstance(payload, Mapping):
                raise TypeError("payload must be a mapping")
            expected = expected_revisions.get((entity_type, entity_id))
            if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
                raise ValueError(f"expected revision is missing or invalid for {entity_type}:{entity_id}")
            encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            prepared.append((entity_type, entity_id, dict(payload), encoded, expected))
        if len({(item[0], item[1]) for item in prepared}) != len(prepared):
            raise ValueError("CAS records must have unique identities")

        now = _utc_now()
        stored: list[StoredRecord] = []
        with self.transaction() as connection:
            current_rows = []
            for entity_type, entity_id, payload, encoded, expected in prepared:
                previous = connection.execute(
                    "SELECT revision, created_at FROM transactional_records WHERE entity_type = ? AND entity_id = ?",
                    (entity_type, entity_id),
                ).fetchone()
                current_revision = int(previous[0]) if previous else 0
                if current_revision != expected:
                    raise StorageRevisionConflict(
                        f"expected revision {expected}, current revision is {current_revision}"
                    )
                current_rows.append((entity_type, entity_id, payload, encoded, expected, previous))
            for entity_type, entity_id, payload, encoded, expected, previous in current_rows:
                revision = expected + 1
                created_at = str(previous[1]) if previous else now
                connection.execute(
                    """
                    INSERT INTO transactional_records
                        (entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        revision = excluded.revision,
                        updated_at = excluded.updated_at,
                        deleted_at = NULL
                    """,
                    (entity_type, entity_id, encoded, revision, created_at, now),
                )
                stored.append(StoredRecord(entity_type, entity_id, payload, revision, created_at, now))
        return tuple(stored)

    def get(self, entity_type: str, entity_id: str, *, include_deleted: bool = False) -> StoredRecord | None:
        entity_type, entity_id = _validate_identity(entity_type, entity_id)
        query = "SELECT * FROM transactional_records WHERE entity_type = ? AND entity_id = ?"
        params: tuple[object, ...] = (entity_type, entity_id)
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        row = self.connection.execute(query, params).fetchone()
        return _record(row) if row else None

    def list(self, entity_type: str, *, include_deleted: bool = False) -> tuple[StoredRecord, ...]:
        entity_type, _ = _validate_identity(entity_type, "list")
        query = "SELECT * FROM transactional_records WHERE entity_type = ?"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        query += " ORDER BY entity_id"
        return tuple(_record(row) for row in self.connection.execute(query, (entity_type,)))

    def delete(self, entity_type: str, entity_id: str) -> bool:
        entity_type, entity_id = _validate_identity(entity_type, entity_id)
        now = _utc_now()
        with self.transaction() as connection:
            result = connection.execute(
                "UPDATE transactional_records SET deleted_at = ?, updated_at = ? WHERE entity_type = ? AND entity_id = ? AND deleted_at IS NULL",
                (now, now, entity_type, entity_id),
            )
        return result.rowcount == 1

    def integrity(self) -> StorageIntegrity:
        try:
            sqlite_integrity = str(self.connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = tuple(
                ":".join(str(value) for value in row)
                for row in self.connection.execute("PRAGMA foreign_key_check")
            )
            version = int(self.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0)
            errors = () if sqlite_integrity == "ok" and not foreign_keys else ("sqlite integrity check failed",)
            return StorageIntegrity(not errors, version, sqlite_integrity, foreign_keys, errors)
        except (sqlite3.DatabaseError, TypeError, ValueError) as exc:
            return StorageIntegrity(False, 0, "unavailable", (), (f"integrity check failed: {exc}",))

    def export_parquet(self, destination: Path | None = None, *, include_deleted: bool = False) -> StorageExport:
        destination = destination or self.layout.export_root / "transactional_records.parquet"
        query = "SELECT entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at FROM transactional_records"
        if not include_deleted:
            query += " WHERE deleted_at IS NULL"
        query += " ORDER BY entity_type, entity_id"
        rows = self.connection.execute(query).fetchall()
        frame = pd.DataFrame([dict(row) for row in rows])
        if frame.empty:
            frame = pd.DataFrame(
                columns=["entity_type", "entity_id", "payload_json", "revision", "created_at", "updated_at", "deleted_at"]
            )
        payload = parquet_payload(frame)
        result = atomic_write_bytes(Path(destination), payload, validate_parquet_file)
        return StorageExport(result.destination, len(frame), result.sha256)


def _record(row: sqlite3.Row) -> StoredRecord:
    return StoredRecord(
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        payload=dict(json.loads(str(row["payload_json"]))),
        revision=int(row["revision"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        deleted_at=str(row["deleted_at"]) if row["deleted_at"] is not None else None,
    )


def _validate_identity(entity_type: str, entity_id: str) -> tuple[str, str]:
    values = (str(entity_type).strip(), str(entity_id).strip())
    if not all(values):
        raise ValueError("entity_type and entity_id must be non-empty")
    return values


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _register_ledger_sql_functions(connection: sqlite3.Connection) -> None:
    connection.create_function("ledger_decimal_valid", 1, _ledger_decimal_valid, deterministic=True)
    connection.create_function("ledger_signed_decimal_valid", 1, _ledger_signed_decimal_valid, deterministic=True)
    connection.create_function("ledger_quantity_nonzero_valid", 1, _ledger_quantity_nonzero_valid, deterministic=True)
    connection.create_function("ledger_posting_amounts_valid", 2, _ledger_posting_amounts_valid, deterministic=True)
    connection.create_aggregate("ledger_currency_balanced", 2, cast(Any, _LedgerCurrencyBalance))
    connection.create_aggregate("ledger_quantity_balanced", 1, cast(Any, _LedgerQuantityBalance))


def _as_ledger_decimal(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _ledger_decimal_valid(value: object) -> int:
    amount = _as_ledger_decimal(value)
    return int(amount is not None and amount.is_finite() and amount >= 0)


def _ledger_signed_decimal_valid(value: object) -> int:
    amount = _as_ledger_decimal(value)
    return int(amount is not None and amount.is_finite())


def _ledger_quantity_nonzero_valid(value: object) -> int:
    amount = _as_ledger_decimal(value)
    return int(amount is not None and amount.is_finite() and amount != 0)


def _ledger_posting_amounts_valid(debit_value: object, credit_value: object) -> int:
    debit = _as_ledger_decimal(debit_value)
    credit = _as_ledger_decimal(credit_value)
    if debit is None or credit is None or not debit.is_finite() or not credit.is_finite():
        return 0
    return int(debit >= 0 and credit >= 0 and ((debit > 0) != (credit > 0)))


class _LedgerCurrencyBalance:
    def __init__(self) -> None:
        self.debits: list[Decimal] = []
        self.credits: list[Decimal] = []
        self.valid = True

    def step(self, debit_value: object, credit_value: object) -> None:
        debit = _as_ledger_decimal(debit_value)
        credit = _as_ledger_decimal(credit_value)
        if (
            debit is None
            or credit is None
            or not debit.is_finite()
            or not credit.is_finite()
            or debit < 0
            or credit < 0
        ):
            self.valid = False
            return
        self.debits.append(debit)
        self.credits.append(credit)

    def finalize(self) -> int:
        if not self.valid or not self.debits:
            return 0
        return int(_ledger_decimal_total(self.debits) == _ledger_decimal_total(self.credits))


class _LedgerQuantityBalance:
    def __init__(self) -> None:
        self.quantities: list[Decimal] = []
        self.valid = True

    def step(self, quantity_value: object) -> None:
        quantity = _as_ledger_decimal(quantity_value)
        if quantity is None or not quantity.is_finite():
            self.valid = False
            return
        self.quantities.append(quantity)

    def finalize(self) -> int:
        if not self.valid or not self.quantities:
            return 0
        return int(_ledger_decimal_sum(self.quantities) == 0)


def _ledger_decimal_total(amounts: list[Decimal]) -> Decimal:
    nonzero = [amount for amount in amounts if amount]
    if not nonzero:
        return Decimal("0")
    min_exponent = min(int(amount.as_tuple().exponent) for amount in nonzero)
    max_adjusted = max(amount.adjusted() for amount in nonzero)
    precision = max(28, max_adjusted - min_exponent + len(str(len(nonzero))) + 2)
    with localcontext() as context:
        context.prec = precision
        return sum(amounts, Decimal("0"))


def _ledger_decimal_sum(amounts: list[Decimal]) -> Decimal:
    nonzero = [amount for amount in amounts if amount]
    if not nonzero:
        return Decimal("0")
    min_exponent = min(int(amount.as_tuple().exponent) for amount in nonzero)
    max_adjusted = max(amount.adjusted() for amount in nonzero)
    precision = max(28, max_adjusted - min_exponent + len(str(len(nonzero))) + 2)
    with localcontext() as context:
        context.prec = precision
        return sum(amounts, Decimal("0"))
