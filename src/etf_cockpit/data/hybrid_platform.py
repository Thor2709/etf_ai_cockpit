from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import duckdb
import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, sha256_file, validate_parquet_file
from etf_cockpit.data.local_storage import StorageIntegrity, StorageLayout, TransactionalStore


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_GENERATION_COLUMNS = ("stable_id", "run_id")


@dataclass(frozen=True)
class AnalyticalGeneration:
    dataset_id: str
    generation_id: str
    relative_path: str
    sha256: str
    row_count: int
    columns: tuple[str, ...]
    stable_id_count: int
    run_id_count: int
    committed_at: str


@dataclass(frozen=True)
class StorageSummary:
    layout: StorageLayout
    schema_version: int
    migration_versions: tuple[int, ...]
    integrity: StorageIntegrity
    transactional_bytes: int
    analytics_bytes: int
    transactional_rows: int
    published_generations: int
    last_compaction: str | None


class HybridPlatform:
    """Local transactional state plus immutable, catalogued Parquet generations."""

    def __init__(self, root: Path):
        self.store = TransactionalStore(root)
        self.layout = self.store.layout
        self._recover_pending_generations()

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> HybridPlatform:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def publish_generation(self, dataset_id: str, generation_id: str, frame: pd.DataFrame) -> AnalyticalGeneration:
        dataset_id = _safe_component(dataset_id, "dataset_id")
        generation_id = _safe_component(generation_id, "generation_id")
        _validate_generation_frame(frame)
        payload = parquet_payload(frame)
        checksum = hashlib.sha256(payload).hexdigest()
        relative_path = (Path("data") / "analytics" / dataset_id / f"{generation_id}.parquet").as_posix()
        destination = self._safe_analytics_path(relative_path)
        self._recover_pending_generations()

        with self.store.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM analytical_generations WHERE dataset_id = ? AND generation_id = ?",
                (dataset_id, generation_id),
            ).fetchone()
            if existing:
                existing_generation = _generation(existing)
                if existing_generation.sha256 != checksum:
                    raise ValueError(f"generation {dataset_id}/{generation_id} already exists with different content")
                if existing["status"] == "published" and destination.is_file() and sha256_file(destination) == checksum:
                    return existing_generation
                if existing["status"] == "publishing":
                    raise RuntimeError(f"generation {dataset_id}/{generation_id} is already being published")
                raise StorageIntegrityError(f"catalogued generation is not recoverable: {relative_path}")
            committed_at = _utc_now()
            connection.execute(
                """
                INSERT INTO analytical_generations
                    (dataset_id, generation_id, relative_path, sha256, row_count, columns_json,
                     stable_id_count, run_id_count, status, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'publishing', ?)
                """,
                (
                    dataset_id,
                    generation_id,
                    relative_path,
                    checksum,
                    len(frame),
                    json.dumps(list(map(str, frame.columns)), sort_keys=True),
                    frame["stable_id"].nunique(dropna=False),
                    frame["run_id"].nunique(dropna=False),
                    committed_at,
                ),
            )
            connection.executemany(
                "INSERT INTO analytical_generation_keys(dataset_id, generation_id, stable_id, run_id) VALUES (?, ?, ?, ?)",
                [
                    (dataset_id, generation_id, str(stable_id), str(run_id))
                    for stable_id, run_id in frame[["stable_id", "run_id"]].itertuples(index=False, name=None)
                ],
            )

        staging = self.layout.analytics_root / ".staging" / f"{dataset_id}-{generation_id}-{checksum[:16]}.parquet"
        try:
            atomic_write_bytes(staging, payload, validate_parquet_file)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(destination)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE analytical_generations SET status = 'published' WHERE dataset_id = ? AND generation_id = ?",
                    (dataset_id, generation_id),
                )
        except Exception:
            staging.unlink(missing_ok=True)
            self._recover_pending_generations()
            raise
        return self.get_generation(dataset_id, generation_id)  # type: ignore[return-value]

    def get_generation(self, dataset_id: str, generation_id: str | None = None) -> AnalyticalGeneration | None:
        dataset_id = _safe_component(dataset_id, "dataset_id")
        query = "SELECT * FROM analytical_generations WHERE dataset_id = ? AND status = 'published'"
        parameters: tuple[object, ...] = (dataset_id,)
        if generation_id is not None:
            generation_id = _safe_component(generation_id, "generation_id")
            query += " AND generation_id = ?"
            parameters += (generation_id,)
        else:
            query += " ORDER BY committed_at DESC, generation_id DESC LIMIT 1"
        row = self.store.connection.execute(query, parameters).fetchone()
        return _generation(row) if row else None

    def list_generations(self, dataset_id: str) -> tuple[AnalyticalGeneration, ...]:
        dataset_id = _safe_component(dataset_id, "dataset_id")
        rows = self.store.connection.execute(
            "SELECT * FROM analytical_generations WHERE dataset_id = ? AND status = 'published' ORDER BY committed_at DESC, generation_id DESC",
            (dataset_id,),
        )
        return tuple(_generation(row) for row in rows)

    def query_generation(self, dataset_id: str, generation_id: str | None = None) -> pd.DataFrame:
        generation = self.get_generation(dataset_id, generation_id)
        if generation is None:
            raise KeyError(f"published generation unavailable: {dataset_id}/{generation_id or 'latest'}")
        path = self._safe_analytics_path(generation.relative_path)
        if not path.is_file() or sha256_file(path) != generation.sha256:
            raise StorageIntegrityError(f"published generation failed checksum validation: {path}")
        with duckdb.connect(database=":memory:") as connection:
            connection.execute("SET enable_progress_bar=false")
            return connection.execute("SELECT * FROM read_parquet(?)", [str(path)]).df()

    def retention_candidates(self, before: datetime) -> tuple[AnalyticalGeneration, ...]:
        cutoff = before.astimezone(timezone.utc).isoformat()
        rows = self.store.connection.execute(
            "SELECT * FROM analytical_generations WHERE status = 'published' AND committed_at < ? ORDER BY committed_at",
            (cutoff,),
        )
        return tuple(_generation(row) for row in rows)

    def compact_generations(self, dataset_id: str, *, keep_latest: int = 1, confirm: bool = False) -> tuple[str, ...]:
        if keep_latest < 1:
            raise ValueError("keep_latest must be at least 1")
        generations = self.list_generations(dataset_id)
        candidates = generations[keep_latest:]
        if not confirm:
            return tuple(generation.generation_id for generation in candidates)
        for generation in candidates:
            path = self._safe_analytics_path(generation.relative_path)
            if not path.is_file() or sha256_file(path) != generation.sha256:
                raise StorageIntegrityError(f"refusing to compact unverifiable generation: {path}")
        for generation in candidates:
            self._safe_analytics_path(generation.relative_path).unlink()
        with self.store.transaction() as connection:
            connection.executemany(
                "DELETE FROM analytical_generations WHERE dataset_id = ? AND generation_id = ? AND status = 'published'",
                [(generation.dataset_id, generation.generation_id) for generation in candidates],
            )
            connection.execute(
                "INSERT INTO storage_operations(operation, completed_at, detail_json) VALUES (?, ?, ?)",
                ("compaction", _utc_now(), json.dumps({"dataset_id": dataset_id, "removed": [item.generation_id for item in candidates]})),
            )
        return tuple(generation.generation_id for generation in candidates)

    def create_backup(self, destination: Path):
        from etf_cockpit.data.backup_restore import create_backup

        integrity = self.store.integrity()
        if not integrity.ok:
            raise StorageIntegrityError("backup blocked by failed SQLite integrity check")
        self.store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return create_backup([self.layout.transactional_path, self.layout.analytics_root], Path(destination))

    def validate_backup(self, archive: Path):
        from etf_cockpit.data.backup_restore import validate_restore

        return validate_restore(Path(archive))

    def restore_backup(self, preview):
        from etf_cockpit.data.backup_restore import commit_restore

        return commit_restore(preview, self.layout.root)

    def export_transactional_json(self, destination: Path) -> Path:
        frame = self._transactional_frame(include_deleted=False)
        payload = (json.dumps(frame.to_dict(orient="records"), indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
        atomic_write_bytes(Path(destination), payload, lambda path: json.loads(path.read_text(encoding="utf-8")))
        return Path(destination)

    def export_transactional_csv(self, destination: Path) -> Path:
        frame = self._transactional_frame(include_deleted=False)
        payload = frame.to_csv(index=False).encode("utf-8")
        atomic_write_bytes(Path(destination), payload, lambda path: pd.read_csv(path))
        return Path(destination)

    def summary(self) -> StorageSummary:
        integrity = self.store.integrity()
        migrations = tuple(int(row[0]) for row in self.store.connection.execute("SELECT version FROM schema_migrations ORDER BY version"))
        transactional_rows = int(self.store.connection.execute("SELECT count(*) FROM transactional_records WHERE deleted_at IS NULL").fetchone()[0])
        published = int(self.store.connection.execute("SELECT count(*) FROM analytical_generations WHERE status = 'published'").fetchone()[0])
        last_compaction = self.store.connection.execute(
            "SELECT completed_at FROM storage_operations WHERE operation = 'compaction' ORDER BY operation_id DESC LIMIT 1"
        ).fetchone()
        return StorageSummary(
            self.layout,
            integrity.schema_version,
            migrations,
            integrity,
            _file_size(self.layout.transactional_path),
            _directory_size(self.layout.analytics_root),
            transactional_rows,
            published,
            str(last_compaction[0]) if last_compaction else None,
        )

    def _transactional_frame(self, *, include_deleted: bool) -> pd.DataFrame:
        query = "SELECT entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at FROM transactional_records"
        if not include_deleted:
            query += " WHERE deleted_at IS NULL"
        rows = self.store.connection.execute(query + " ORDER BY entity_type, entity_id").fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    def _safe_analytics_path(self, relative_path: str) -> Path:
        candidate = (self.layout.root / Path(relative_path)).resolve()
        analytics_root = self.layout.analytics_root.resolve()
        if not candidate.is_relative_to(analytics_root) or candidate.suffix.lower() != ".parquet":
            raise StorageIntegrityError(f"analytics path outside approved root: {relative_path}")
        return candidate

    def _recover_pending_generations(self) -> None:
        rows = self.store.connection.execute(
            "SELECT * FROM analytical_generations WHERE status = 'publishing' ORDER BY committed_at"
        ).fetchall()
        for row in rows:
            try:
                path = self._safe_analytics_path(str(row["relative_path"]))
            except StorageIntegrityError:
                path = None
            valid = path is not None and path.is_file() and sha256_file(path) == str(row["sha256"])
            with self.store.transaction() as connection:
                if valid:
                    connection.execute(
                        "UPDATE analytical_generations SET status = 'published' WHERE dataset_id = ? AND generation_id = ?",
                        (row["dataset_id"], row["generation_id"]),
                    )
                else:
                    connection.execute(
                        "DELETE FROM analytical_generations WHERE dataset_id = ? AND generation_id = ? AND status = 'publishing'",
                        (row["dataset_id"], row["generation_id"]),
                    )


class StorageIntegrityError(RuntimeError):
    """Raised when a published local generation cannot be verified safely."""


def _validate_generation_frame(frame: pd.DataFrame) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = [column for column in _GENERATION_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"analytical generation requires columns: {', '.join(missing)}")
    for column in _GENERATION_COLUMNS:
        values = frame[column].astype("string")
        if values.isna().any() or values.str.strip().eq("").any():
            raise ValueError(f"analytical generation column {column} contains an unavailable value")
    if frame.duplicated(subset=list(_GENERATION_COLUMNS)).any():
        raise ValueError("analytical generation stable_id/run_id pairs must be unique")


def _generation(row: Any) -> AnalyticalGeneration:
    return AnalyticalGeneration(
        dataset_id=str(row["dataset_id"]),
        generation_id=str(row["generation_id"]),
        relative_path=str(row["relative_path"]),
        sha256=str(row["sha256"]),
        row_count=int(row["row_count"]),
        columns=tuple(str(item) for item in json.loads(str(row["columns_json"]))),
        stable_id_count=int(row["stable_id_count"]),
        run_id_count=int(row["run_id_count"]),
        committed_at=str(row["committed_at"]),
    )


def _safe_component(value: str, label: str) -> str:
    value = str(value).strip()
    if not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"{label} must be a single safe local identifier")
    return value


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.is_dir() else 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
