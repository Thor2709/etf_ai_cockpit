from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid

import duckdb
import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, sha256_file, validate_parquet_file
from etf_cockpit.data.local_storage import StorageIntegrity, StorageLayout, TransactionalStore


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_GENERATION_COLUMNS = ("stable_id", "run_id")
_PUBLISHING_GRACE = timedelta(minutes=5)
_LEASE_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_MAX_PUBLISHER_LEASE_CANDIDATES = 32


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


@dataclass(frozen=True)
class _PublicationIdentity:
    dataset_id: str
    generation_id: str
    sha256: str
    committed_at: str
    catalogue_rowid: int
    token: str
    owner_pid: int
    process_start_id: str
    created_at: str


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
        publication_token = uuid.uuid4().hex
        staging = self._publisher_staging_path(dataset_id, generation_id, publication_token)
        publisher_lease = self._publisher_lease_path(
            dataset_id, generation_id, publication_token
        )
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
            self._assert_no_live_publisher_claims(dataset_id, generation_id)
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
            inserted = connection.execute(
                """
                SELECT rowid AS catalogue_rowid
                FROM analytical_generations
                WHERE dataset_id = ? AND generation_id = ? AND status = 'publishing'
                """,
                (dataset_id, generation_id),
            ).fetchone()
            if inserted is None:
                raise StorageIntegrityError(
                    f"generation catalogue did not return a publication identity: "
                    f"{dataset_id}/{generation_id}"
                )
            catalogue_rowid = int(inserted["catalogue_rowid"])

        if catalogue_rowid <= 0:
            raise StorageIntegrityError(
                f"generation catalogue returned an invalid publication identity: "
                f"{dataset_id}/{generation_id}"
            )
        publication = _PublicationIdentity(
            dataset_id=dataset_id,
            generation_id=generation_id,
            sha256=checksum,
            committed_at=committed_at,
            catalogue_rowid=catalogue_rowid,
            token=publication_token,
            owner_pid=os.getpid(),
            process_start_id=_process_start_identity(os.getpid()) or "unavailable",
            created_at=_utc_now(),
        )

        lease_acquired = False
        try:
            self._claim_publisher_lease(publisher_lease, publication)
            lease_acquired = True
            atomic_write_bytes(staging, payload, validate_parquet_file)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(destination)
            self._finalise_publication(publisher_lease, publication)
        except Exception as publication_error:
            cleanup_errors: list[Exception] = []
            try:
                staging.unlink(missing_ok=True)
            except Exception as cleanup_error:
                cleanup_errors.append(cleanup_error)
            if lease_acquired:
                try:
                    self._unlink_owned_publisher_lease(publisher_lease, publication.token)
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                finally:
                    lease_acquired = False
            try:
                self._cleanup_failed_publication(publication, destination)
            except Exception as cleanup_error:
                cleanup_errors.append(cleanup_error)
            for cleanup_error in cleanup_errors:
                publication_error.add_note(
                    f"publication cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}"
                )
            raise
        finally:
            if lease_acquired:
                try:
                    self._unlink_owned_publisher_lease(publisher_lease, publication.token)
                except Exception:
                    pass
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
            """
            SELECT rowid AS catalogue_rowid, *
            FROM analytical_generations
            WHERE status = 'publishing'
            ORDER BY committed_at
            """
        ).fetchall()
        for row in rows:
            protected, inactive_owned_leases = self._pending_claims(row)
            if protected:
                continue
            try:
                path = self._safe_analytics_path(str(row["relative_path"]))
            except StorageIntegrityError:
                path = None
            valid = path is not None and path.is_file() and sha256_file(path) == str(row["sha256"])
            with self.store.transaction() as connection:
                if valid:
                    recovered = connection.execute(
                        """
                        UPDATE analytical_generations
                        SET status = 'published'
                        WHERE rowid = ? AND dataset_id = ? AND generation_id = ?
                          AND status = 'publishing' AND sha256 = ? AND committed_at = ?
                        """,
                        (
                            row["catalogue_rowid"],
                            row["dataset_id"],
                            row["generation_id"],
                            row["sha256"],
                            row["committed_at"],
                        ),
                    )
                else:
                    recovered = connection.execute(
                        """
                        DELETE FROM analytical_generations
                        WHERE rowid = ? AND dataset_id = ? AND generation_id = ?
                          AND status = 'publishing' AND committed_at = ?
                        """,
                        (
                            row["catalogue_rowid"],
                            row["dataset_id"],
                            row["generation_id"],
                            row["committed_at"],
                        ),
                    )
            if recovered.rowcount == 1:
                for lease, token in inactive_owned_leases:
                    self._unlink_owned_publisher_lease(lease, token)

    def _publisher_lease_prefix(self, dataset_id: str, generation_id: str) -> str:
        lease_id = hashlib.sha256(f"{dataset_id}\0{generation_id}".encode("utf-8")).hexdigest()[:32]
        return f"{lease_id}-"

    def _publisher_staging_path(
        self, dataset_id: str, generation_id: str, token: str
    ) -> Path:
        if _LEASE_TOKEN.fullmatch(token) is None:
            raise ValueError("publisher staging token must be 32 lowercase hexadecimal characters")
        identity_hash = hashlib.sha256(
            f"{dataset_id}\0{generation_id}".encode("utf-8")
        ).hexdigest()[:16]
        return self.layout.analytics_root / ".staging" / f"{identity_hash}-{token}.parquet"

    def _publisher_lease_path(
        self, dataset_id: str, generation_id: str, token: str
    ) -> Path:
        if _LEASE_TOKEN.fullmatch(token) is None:
            raise ValueError("publisher lease token must be 32 lowercase hexadecimal characters")
        prefix = self._publisher_lease_prefix(dataset_id, generation_id)
        return self.layout.analytics_root / ".staging" / f"{prefix}{token}.publishing.json"

    def _publisher_lease_candidates(
        self, dataset_id: str, generation_id: str
    ) -> tuple[tuple[Path, ...], bool]:
        staging = self.layout.analytics_root / ".staging"
        if not staging.is_dir():
            return (), False
        prefix = self._publisher_lease_prefix(dataset_id, generation_id)
        candidates = tuple(
            islice(
                staging.glob(f"{prefix}*.publishing.json"),
                _MAX_PUBLISHER_LEASE_CANDIDATES + 1,
            )
        )
        overflow = len(candidates) > _MAX_PUBLISHER_LEASE_CANDIDATES
        return tuple(sorted(candidates[:_MAX_PUBLISHER_LEASE_CANDIDATES])), overflow

    def _claim_publisher_lease(self, lease: Path, publication: _PublicationIdentity) -> None:
        lease.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_publication_payload(publication), sort_keys=True).encode("utf-8")
        try:
            descriptor = os.open(lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError(
                f"generation {publication.dataset_id}/{publication.generation_id} is already being published"
            ) from exc
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _assert_no_live_publisher_claims(self, dataset_id: str, generation_id: str) -> None:
        candidates, overflow = self._publisher_lease_candidates(dataset_id, generation_id)
        if overflow:
            raise StorageIntegrityError(
                f"too many publisher lease candidates: {dataset_id}/{generation_id}"
            )
        prefix = self._publisher_lease_prefix(dataset_id, generation_id)
        for lease in candidates:
            try:
                payload = _read_lease_payload(lease)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise StorageIntegrityError(
                    f"publisher lease cannot be proven inactive: {dataset_id}/{generation_id}"
                ) from exc
            token = _lease_token_from_path(lease, prefix)
            if (
                not _lease_payload_is_well_formed(payload)
                or token is None
                or payload["token"] != token
            ):
                raise StorageIntegrityError(
                    f"publisher lease identity is invalid: {dataset_id}/{generation_id}"
                )
            if _lease_owner_state(payload) != "inactive":
                raise RuntimeError(f"generation {dataset_id}/{generation_id} is already being published")
            self._unlink_owned_publisher_lease(lease, token)

    def _pending_claims(self, row: Any) -> tuple[bool, tuple[tuple[Path, str], ...]]:
        dataset_id = str(row["dataset_id"])
        generation_id = str(row["generation_id"])
        candidates, overflow = self._publisher_lease_candidates(dataset_id, generation_id)
        if overflow:
            return True, ()
        if not candidates:
            return _timestamp_within(str(row["committed_at"]), _PUBLISHING_GRACE), ()
        inactive_owned: list[tuple[Path, str]] = []
        prefix = self._publisher_lease_prefix(dataset_id, generation_id)
        for lease in candidates:
            try:
                payload = _read_lease_payload(lease)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return True, ()
            token = _lease_token_from_path(lease, prefix)
            if (
                not _lease_payload_is_well_formed(payload)
                or token is None
                or payload["token"] != token
            ):
                return True, ()
            if _lease_owner_state(payload) != "inactive":
                return True, ()
            if _lease_matches_row(payload, row):
                inactive_owned.append((lease, token))
        return False, tuple(inactive_owned)

    def _unlink_owned_publisher_lease(self, lease: Path, token: str) -> bool:
        try:
            payload = _read_lease_payload(lease)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return False
        if payload.get("token") != token or not lease.name.endswith(
            f"-{token}.publishing.json"
        ):
            return False
        try:
            lease.unlink()
        except FileNotFoundError:
            return False
        return True

    def _validate_owned_publisher_lease(
        self, lease: Path, publication: _PublicationIdentity
    ) -> None:
        try:
            payload = _read_lease_payload(lease)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise StorageIntegrityError(
                f"publisher lease is unreadable: {publication.dataset_id}/{publication.generation_id}"
            ) from exc
        if payload != _publication_payload(publication):
            raise StorageIntegrityError(
                f"publisher lease identity changed: {publication.dataset_id}/{publication.generation_id}"
            )

    def _finalise_publication(
        self, lease: Path, publication: _PublicationIdentity
    ) -> None:
        last_rowcount = 0
        for _attempt in range(2):
            self._validate_owned_publisher_lease(lease, publication)
            with self.store.transaction() as connection:
                transition = connection.execute(
                    """
                    UPDATE analytical_generations
                    SET status = 'published'
                    WHERE rowid = ? AND dataset_id = ? AND generation_id = ?
                      AND status = 'publishing' AND sha256 = ? AND committed_at = ?
                    """,
                    (
                        publication.catalogue_rowid,
                        publication.dataset_id,
                        publication.generation_id,
                        publication.sha256,
                        publication.committed_at,
                    ),
                )
                last_rowcount = transition.rowcount
            if last_rowcount == 1:
                return
            row = self.store.connection.execute(
                """
                SELECT rowid AS catalogue_rowid, *
                FROM analytical_generations
                WHERE dataset_id = ? AND generation_id = ?
                """,
                (publication.dataset_id, publication.generation_id),
            ).fetchone()
            if row is not None and _row_matches_publication(row, publication, status="published"):
                return
        raise StorageIntegrityError(
            f"generation catalogue transition affected {last_rowcount} rows: "
            f"{publication.dataset_id}/{publication.generation_id}"
        )

    def _cleanup_failed_publication(
        self, publication: _PublicationIdentity, destination: Path
    ) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                DELETE FROM analytical_generations
                WHERE rowid = ? AND dataset_id = ? AND generation_id = ?
                  AND status = 'publishing' AND committed_at = ?
                """,
                (
                    publication.catalogue_rowid,
                    publication.dataset_id,
                    publication.generation_id,
                    publication.committed_at,
                ),
            )
            row = connection.execute(
                """
                SELECT rowid AS catalogue_rowid, *
                FROM analytical_generations
                WHERE dataset_id = ? AND generation_id = ?
                """,
                (publication.dataset_id, publication.generation_id),
            ).fetchone()
            if (
                row is None
                and destination.is_file()
                and sha256_file(destination) == publication.sha256
            ):
                destination.unlink()


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


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _publication_payload(publication: _PublicationIdentity) -> dict[str, object]:
    return {
        "dataset_id": publication.dataset_id,
        "generation_id": publication.generation_id,
        "sha256": publication.sha256,
        "committed_at": publication.committed_at,
        "catalogue_rowid": publication.catalogue_rowid,
        "token": publication.token,
        "owner_pid": publication.owner_pid,
        "process_start_id": publication.process_start_id,
        "created_at": publication.created_at,
    }


def _read_lease_payload(lease: Path) -> dict[str, Any]:
    payload = json.loads(lease.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("publisher lease must contain an object")
    return payload


def _lease_payload_is_well_formed(payload: dict[str, Any]) -> bool:
    expected_keys = {
        "dataset_id",
        "generation_id",
        "sha256",
        "committed_at",
        "catalogue_rowid",
        "token",
        "owner_pid",
        "process_start_id",
        "created_at",
    }
    return (
        set(payload) == expected_keys
        and isinstance(payload["dataset_id"], str)
        and _SAFE_COMPONENT.fullmatch(payload["dataset_id"]) is not None
        and isinstance(payload["generation_id"], str)
        and _SAFE_COMPONENT.fullmatch(payload["generation_id"]) is not None
        and isinstance(payload["sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", payload["sha256"]) is not None
        and type(payload["catalogue_rowid"]) is int
        and payload["catalogue_rowid"] > 0
        and isinstance(payload["token"], str)
        and _LEASE_TOKEN.fullmatch(payload["token"]) is not None
        and type(payload["owner_pid"]) is int
        and payload["owner_pid"] > 0
        and isinstance(payload["process_start_id"], str)
        and bool(payload["process_start_id"])
        and isinstance(payload["committed_at"], str)
        and _parse_timestamp(payload["committed_at"]) is not None
        and isinstance(payload["created_at"], str)
        and _parse_timestamp(payload["created_at"]) is not None
    )


def _timestamp_within(value: str | None, maximum_age: timedelta) -> bool:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return False
    age = datetime.now(timezone.utc) - parsed
    return timedelta(0) <= age <= maximum_age


def _lease_token_from_path(lease: Path, prefix: str) -> str | None:
    suffix = ".publishing.json"
    if not lease.name.startswith(prefix) or not lease.name.endswith(suffix):
        return None
    token = lease.name[len(prefix) : -len(suffix)]
    return token if _LEASE_TOKEN.fullmatch(token) is not None else None


def _lease_matches_row(payload: dict[str, Any], row: Any) -> bool:
    return (
        payload["dataset_id"] == str(row["dataset_id"])
        and payload["generation_id"] == str(row["generation_id"])
        and payload["sha256"] == str(row["sha256"])
        and payload["committed_at"] == str(row["committed_at"])
        and payload["catalogue_rowid"] == int(row["catalogue_rowid"])
    )


def _lease_owner_state(payload: dict[str, Any]) -> str:
    owner_pid = int(payload["owner_pid"])
    expected_start = str(payload["process_start_id"])
    actual_start = _process_start_identity(owner_pid)
    if expected_start != "unavailable" and actual_start is not None:
        return "live" if actual_start == expected_start else "inactive"
    return "unknown" if _pid_alive(owner_pid) else "inactive"


def _process_start_identity(pid: int) -> str | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_start_identity(pid)
    if os.name == "posix" and Path("/proc").is_dir():
        return _linux_process_start_identity(pid)
    return None


def _windows_process_start_identity(pid: int) -> str | None:
    import ctypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    creation = FileTime()
    exit_time = FileTime()
    kernel_time = FileTime()
    user_time = FileTime()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
    finally:
        kernel32.CloseHandle(handle)
    value = (int(creation.high) << 32) | int(creation.low)
    return f"windows-filetime:{value}"


def _linux_process_start_identity(pid: int) -> str | None:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        closing_parenthesis = stat_text.rfind(")")
        fields_after_name = stat_text[closing_parenthesis + 2 :].split()
        start_ticks = fields_after_name[19]
    except (OSError, IndexError):
        return None
    if closing_parenthesis < 0 or not boot_id or not start_ticks.isdigit():
        return None
    return f"linux-proc:{boot_id}:{start_ticks}"


def _row_matches_publication(
    row: Any, publication: _PublicationIdentity, *, status: str
) -> bool:
    return (
        int(row["catalogue_rowid"]) == publication.catalogue_rowid
        and str(row["dataset_id"]) == publication.dataset_id
        and str(row["generation_id"]) == publication.generation_id
        and str(row["sha256"]) == publication.sha256
        and str(row["committed_at"]) == publication.committed_at
        and str(row["status"]) == status
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    return _posix_pid_alive(pid)


def _posix_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.is_dir() else 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
