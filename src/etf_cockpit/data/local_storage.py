from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file


STORAGE_SCHEMA_VERSION = 1


class StorageSchemaError(RuntimeError):
    """Raised when a local store cannot be read safely by this application."""


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
    connection = sqlite3.connect(layout.transactional_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
    highest = max(applied, default=0)
    if highest > STORAGE_SCHEMA_VERSION:
        raise StorageSchemaError(
            f"storage schema {highest} is newer than supported version {STORAGE_SCHEMA_VERSION}"
        )
    for version, name, migration in ((1, "transactional_records_v1", _migration_v1),):
        if version in applied:
            continue
        with connection:
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, _utc_now()),
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

    def put(self, entity_type: str, entity_id: str, payload: Mapping[str, Any]) -> StoredRecord:
        entity_type, entity_id = _validate_identity(entity_type, entity_id)
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        now = _utc_now()
        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT revision, created_at FROM transactional_records WHERE entity_type = ? AND entity_id = ?",
                (entity_type, entity_id),
            ).fetchone()
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
        return self.get(entity_type, entity_id, include_deleted=True)  # type: ignore[return-value]

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
