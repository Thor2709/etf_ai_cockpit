from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file


STORAGE_SCHEMA_VERSION = 4


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


def connect_storage(root: Path) -> sqlite3.Connection:
    layout = storage_layout(root)
    layout.transactional_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(layout.transactional_path, timeout=30.0)
    try:
        connection.row_factory = sqlite3.Row
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


class TransactionalStore:
    """Small ACID store for user-owned state; analytical data remains Parquet."""

    def __init__(self, root: Path):
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
        except Exception:
            self.connection.rollback()
            raise
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
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        now = _utc_now()
        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT revision, created_at FROM transactional_records WHERE entity_type = ? AND entity_id = ?",
                (entity_type, entity_id),
            ).fetchone()
            current_revision = int(previous[0]) if previous else 0
            if expected_revision is not None and current_revision != expected_revision:
                raise StorageRevisionConflict(
                    f"expected revision {expected_revision}, current revision is {current_revision}"
                )
            revision = int(previous[0]) + 1 if previous else 1
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
            stored = StoredRecord(
                entity_type=entity_type,
                entity_id=entity_id,
                payload=dict(json.loads(encoded)),
                revision=revision,
                created_at=created_at,
                updated_at=now,
            )
        return stored

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
