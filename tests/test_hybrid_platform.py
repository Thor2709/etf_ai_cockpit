from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import etf_cockpit.data.hybrid_platform as hybrid
from etf_cockpit.data.hybrid_platform import HybridPlatform
from etf_cockpit.data.local_storage import connect_storage


def _frame(value: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stable_id": ["instrument-1", "instrument-2"],
            "run_id": ["run-1", "run-1"],
            "value": [value, value + 1],
        }
    )


def test_published_generation_is_idempotent_catalogued_and_queryable(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as platform:
        first = platform.publish_generation("scores", "generation-1", _frame())
        second = platform.publish_generation("scores", "generation-1", _frame())

        assert first == second
        assert platform.query_generation("scores", "generation-1")["stable_id"].tolist() == ["instrument-1", "instrument-2"]
        assert platform.summary().published_generations == 1
        assert platform.summary().integrity.foreign_key_violations == ()


def test_fresh_and_migrated_roots_return_the_same_canonical_query(tmp_path: Path) -> None:
    fresh_root = tmp_path / "fresh"
    migrated_root = tmp_path / "migrated"
    with HybridPlatform(fresh_root) as fresh:
        fresh.publish_generation("scores", "generation-1", _frame())
        fresh_query = fresh.query_generation("scores", "generation-1")
    connection = connect_storage(migrated_root)
    connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE transactional_records (entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT, PRIMARY KEY(entity_type, entity_id))"
    )
    connection.execute("INSERT INTO schema_migrations VALUES (1, 'transactional_records_v1', 'now')")
    connection.commit()
    connection.close()
    with HybridPlatform(migrated_root) as migrated:
        migrated.publish_generation("scores", "generation-1", _frame())
        migrated_query = migrated.query_generation("scores", "generation-1")

    assert_frame_equal(fresh_query, migrated_query, check_dtype=False)


def test_generation_requires_stable_and_run_lineage_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as platform:
        with pytest.raises(ValueError, match="requires columns"):
            platform.publish_generation("scores", "generation-1", pd.DataFrame({"value": [1]}))
        with pytest.raises(ValueError, match="safe local identifier"):
            platform.publish_generation("../scores", "generation-1", _frame())
        with pytest.raises(ValueError, match="pairs must be unique"):
            platform.publish_generation("scores", "generation-1", pd.concat([_frame(), _frame()], ignore_index=True))


def test_failed_publication_is_not_visible_after_recovery(tmp_path: Path, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("injected publish failure")

    with HybridPlatform(tmp_path) as platform:
        platform.publish_generation("scores", "generation-0", _frame())
        monkeypatch.setattr(hybrid, "atomic_write_bytes", fail)
        with pytest.raises(RuntimeError, match="injected publish failure"):
            platform.publish_generation("scores", "generation-1", _frame(2))
        assert platform.query_generation("scores", "generation-0")["value"].tolist() == [1, 2]
    with HybridPlatform(tmp_path) as recovered:
        assert [item.generation_id for item in recovered.list_generations("scores")] == ["generation-0"]
        assert not (tmp_path / "data" / "analytics" / "scores" / "generation-1.parquet").exists()


def test_reader_can_use_previous_generation_while_writer_publishes_next(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as initial:
        initial.publish_generation("scores", "generation-1", _frame())
    errors: list[BaseException] = []

    def write_next() -> None:
        try:
            with HybridPlatform(tmp_path) as writer:
                writer.publish_generation("scores", "generation-2", _frame(2))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    writer_thread = threading.Thread(target=write_next)
    writer_thread.start()
    with HybridPlatform(tmp_path) as reader:
        for _ in range(20):
            assert reader.query_generation("scores", "generation-1")["stable_id"].tolist() == ["instrument-1", "instrument-2"]
    writer_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert errors == []
    with HybridPlatform(tmp_path) as verified:
        assert verified.get_generation("scores", "generation-2") is not None


def test_reader_recovery_does_not_delete_an_active_publisher(tmp_path: Path, monkeypatch) -> None:
    writer_reached_file_publish = threading.Event()
    allow_file_publish = threading.Event()
    original_atomic_write = hybrid.atomic_write_bytes
    results = []
    errors: list[BaseException] = []

    def blocked_atomic_write(*args, **kwargs):
        writer_reached_file_publish.set()
        if not allow_file_publish.wait(timeout=5):
            raise TimeoutError("test did not release the active publisher")
        return original_atomic_write(*args, **kwargs)

    monkeypatch.setattr(hybrid, "atomic_write_bytes", blocked_atomic_write)

    def publish() -> None:
        try:
            with HybridPlatform(tmp_path) as writer:
                results.append(writer.publish_generation("scores", "generation-active", _frame()))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    writer_thread = threading.Thread(target=publish)
    writer_thread.start()
    assert writer_reached_file_publish.wait(timeout=5)
    try:
        with HybridPlatform(tmp_path) as reader:
            pending = reader.store.connection.execute(
                "SELECT status FROM analytical_generations WHERE dataset_id = ? AND generation_id = ?",
                ("scores", "generation-active"),
            ).fetchone()
            assert pending is not None
            assert pending["status"] == "publishing"
            assert reader.get_generation("scores", "generation-active") is None
    finally:
        allow_file_publish.set()
        writer_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert errors == []
    assert len(results) == 1
    assert results[0].generation_id == "generation-active"


def test_publisher_fails_if_final_catalogue_transition_updates_no_row(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as platform:
        platform.store.connection.execute(
            """
            CREATE TRIGGER ignore_generation_publish
            BEFORE UPDATE OF status ON analytical_generations
            WHEN OLD.status = 'publishing' AND NEW.status = 'published'
            BEGIN
                SELECT RAISE(IGNORE);
            END
            """
        )
        with pytest.raises(hybrid.StorageIntegrityError, match="catalogue transition"):
            platform.publish_generation("scores", "generation-ignored", _frame())
        assert platform.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-ignored",),
        ).fetchone() is None
        assert not (tmp_path / "data" / "analytics" / "scores" / "generation-ignored.parquet").exists()
        assert list((tmp_path / "data" / "analytics" / ".staging").glob("*.publishing.json")) == []


def test_zero_row_transition_accepts_matching_published_readback(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as platform:
        platform.store.connection.execute(
            """
            CREATE TRIGGER publish_before_outer_transition
            BEFORE UPDATE OF status ON analytical_generations
            WHEN OLD.status = 'publishing' AND NEW.status = 'published'
            BEGIN
                UPDATE analytical_generations
                SET status = 'published'
                WHERE rowid = OLD.rowid;
                SELECT RAISE(IGNORE);
            END
            """
        )

        published = platform.publish_generation("scores", "generation-readback", _frame())

        assert published.generation_id == "generation-readback"
        assert platform.query_generation("scores", "generation-readback")["value"].tolist() == [1, 2]


def test_checksum_mutation_cannot_be_published_and_is_cleaned_immediately(tmp_path: Path, monkeypatch) -> None:
    writer_reached_file_publish = threading.Event()
    allow_file_publish = threading.Event()
    original_atomic_write = hybrid.atomic_write_bytes
    errors: list[BaseException] = []

    def blocked_atomic_write(*args, **kwargs):
        writer_reached_file_publish.set()
        if not allow_file_publish.wait(timeout=5):
            raise TimeoutError("test did not release the checksum-mutation publisher")
        return original_atomic_write(*args, **kwargs)

    monkeypatch.setattr(hybrid, "atomic_write_bytes", blocked_atomic_write)

    def publish() -> None:
        try:
            with HybridPlatform(tmp_path) as writer:
                writer.publish_generation("scores", "generation-mutated", _frame())
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    writer_thread = threading.Thread(target=publish)
    writer_thread.start()
    assert writer_reached_file_publish.wait(timeout=5)
    original_lease = next(
        (tmp_path / "data" / "analytics" / ".staging").glob("*.publishing.json")
    )
    replacement_payload = json.loads(original_lease.read_text(encoding="utf-8"))
    replacement_payload["token"] = "b" * 32
    with HybridPlatform(tmp_path) as lease_platform:
        replacement_lease = lease_platform._publisher_lease_path(
            "scores", "generation-mutated", replacement_payload["token"]
        )
    replacement_lease.write_text(json.dumps(replacement_payload), encoding="utf-8")
    connection = connect_storage(tmp_path)
    try:
        connection.execute(
            "UPDATE analytical_generations SET sha256 = ? WHERE generation_id = ?",
            ("f" * 64, "generation-mutated"),
        )
        connection.commit()
    finally:
        connection.close()
        allow_file_publish.set()
        writer_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], hybrid.StorageIntegrityError)
    connection = connect_storage(tmp_path)
    try:
        assert connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-mutated",),
        ).fetchone() is None
    finally:
        connection.close()
    assert not (tmp_path / "data" / "analytics" / "scores" / "generation-mutated.parquet").exists()
    assert replacement_lease.exists()
    assert not original_lease.exists()


def test_failed_owner_preserves_foreign_replacement_with_identical_content(
    tmp_path: Path, monkeypatch
) -> None:
    writer_reached_file_publish = threading.Event()
    allow_file_publish = threading.Event()
    original_atomic_write = hybrid.atomic_write_bytes
    errors: list[BaseException] = []

    def blocked_atomic_write(*args, **kwargs):
        writer_reached_file_publish.set()
        if not allow_file_publish.wait(timeout=5):
            raise TimeoutError("test did not release the foreign-replacement publisher")
        return original_atomic_write(*args, **kwargs)

    monkeypatch.setattr(hybrid, "atomic_write_bytes", blocked_atomic_write)

    def publish() -> None:
        try:
            with HybridPlatform(tmp_path) as writer:
                writer.publish_generation("scores", "generation-foreign", _frame())
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    writer_thread = threading.Thread(target=publish)
    writer_thread.start()
    assert writer_reached_file_publish.wait(timeout=5)
    connection = connect_storage(tmp_path)
    try:
        original = connection.execute(
            "SELECT * FROM analytical_generations WHERE generation_id = ?",
            ("generation-foreign",),
        ).fetchone()
        assert original is not None
        connection.execute(
            "DELETE FROM analytical_generations WHERE generation_id = ?",
            ("generation-foreign",),
        )
        connection.execute(
            """
            INSERT INTO analytical_generations
                (dataset_id, generation_id, relative_path, sha256, row_count, columns_json,
                 stable_id_count, run_id_count, status, committed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?)
            """,
            (
                original["dataset_id"],
                original["generation_id"],
                original["relative_path"],
                original["sha256"],
                original["row_count"],
                original["columns_json"],
                original["stable_id_count"],
                original["run_id_count"],
                "2099-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()
        allow_file_publish.set()
        writer_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], hybrid.StorageIntegrityError)
    with HybridPlatform(tmp_path) as foreign:
        assert foreign.query_generation("scores", "generation-foreign")["value"].tolist() == [1, 2]


def test_takeover_staging_is_not_removed_by_failed_old_owner(tmp_path: Path, monkeypatch) -> None:
    old_waiting = threading.Event()
    takeover_staged = threading.Event()
    release_old = threading.Event()
    release_takeover = threading.Event()
    original_atomic_write = hybrid.atomic_write_bytes
    call_lock = threading.Lock()
    call_count = 0
    old_errors: list[BaseException] = []
    takeover_errors: list[BaseException] = []
    takeover_results = []

    def controlled_atomic_write(path, payload, validator):
        nonlocal call_count
        with call_lock:
            call_count += 1
            call_number = call_count
        if call_number == 1:
            old_waiting.set()
            if not release_old.wait(timeout=5):
                raise TimeoutError("test did not release old publisher")
            return original_atomic_write(path, payload, validator)
        if call_number == 2:
            result = original_atomic_write(path, payload, validator)
            takeover_staged.set()
            if not release_takeover.wait(timeout=5):
                raise TimeoutError("test did not release takeover publisher")
            return result
        raise AssertionError(f"unexpected atomic publication call {call_number}")

    monkeypatch.setattr(hybrid, "atomic_write_bytes", controlled_atomic_write)

    def publish_old() -> None:
        try:
            with HybridPlatform(tmp_path) as writer:
                writer.publish_generation("scores", "generation-takeover", _frame())
        except BaseException as exc:  # pragma: no cover - asserted below
            old_errors.append(exc)

    def publish_takeover() -> None:
        try:
            with HybridPlatform(tmp_path) as writer:
                takeover_results.append(
                    writer.publish_generation("scores", "generation-takeover", _frame())
                )
        except BaseException as exc:  # pragma: no cover - asserted below
            takeover_errors.append(exc)

    old_thread = threading.Thread(target=publish_old)
    old_thread.start()
    assert old_waiting.wait(timeout=5)
    old_lease = next(
        (tmp_path / "data" / "analytics" / ".staging").glob("*.publishing.json")
    )
    stale_payload = json.loads(old_lease.read_text(encoding="utf-8"))
    stale_payload["process_start_id"] = "replaced-process-start"
    old_lease.write_text(json.dumps(stale_payload), encoding="utf-8")
    connection = connect_storage(tmp_path)
    try:
        connection.execute(
            "DELETE FROM analytical_generations WHERE generation_id = ?",
            ("generation-takeover",),
        )
        connection.commit()
    finally:
        connection.close()

    takeover_thread = threading.Thread(target=publish_takeover)
    takeover_thread.start()
    assert takeover_staged.wait(timeout=5)
    takeover_staging = list(
        (tmp_path / "data" / "analytics" / ".staging").glob("*.parquet")
    )
    assert len(takeover_staging) == 1
    try:
        release_old.set()
        old_thread.join(timeout=5)
    finally:
        release_takeover.set()
        takeover_thread.join(timeout=5)

    assert not old_thread.is_alive()
    assert not takeover_thread.is_alive()
    assert len(old_errors) == 1
    assert isinstance(old_errors[0], hybrid.StorageIntegrityError)
    assert takeover_errors == []
    assert len(takeover_results) == 1
    with HybridPlatform(tmp_path) as verified:
        assert verified.query_generation("scores", "generation-takeover")["value"].tolist() == [1, 2]
        assert verified.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE status = 'publishing'"
        ).fetchone() is None


def test_staging_unlink_failure_preserves_original_error_and_reconciles_state(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_after_staging(path, _payload, _validator):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"token-scoped-test-residue")
        raise RuntimeError("original publication failure")

    real_unlink = Path.unlink

    def fail_staging_unlink(path: Path, *args, **kwargs):
        if path.parent.name == ".staging" and path.suffix == ".parquet":
            raise PermissionError("injected staging unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(hybrid, "atomic_write_bytes", fail_after_staging)
    monkeypatch.setattr(Path, "unlink", fail_staging_unlink)

    with HybridPlatform(tmp_path) as platform:
        with pytest.raises(RuntimeError, match="original publication failure"):
            platform.publish_generation("s" * 128, "g" * 128, _frame())
        assert platform.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE status = 'publishing'"
        ).fetchone() is None

    staging_root = tmp_path / "data" / "analytics" / ".staging"
    assert list(staging_root.glob("*.publishing.json")) == []
    residue = list(staging_root.glob("*.parquet"))
    assert len(residue) == 1
    assert len(residue[0].name) <= 64
    assert "s" * 128 not in residue[0].name
    assert "g" * 128 not in residue[0].name


def test_maximum_length_identifiers_publish_without_pending_orphan(tmp_path: Path) -> None:
    dataset_id = "d" * 128
    generation_id = "g" * 128

    with HybridPlatform(tmp_path) as platform:
        published = platform.publish_generation(dataset_id, generation_id, _frame())

        assert published.dataset_id == dataset_id
        assert published.generation_id == generation_id
        assert platform.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE status = 'publishing'"
        ).fetchone() is None
    assert list((tmp_path / "data" / "analytics" / ".staging").glob("*")) == []


def test_committed_publication_survives_lease_unlink_failure_and_retries_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    real_unlink = Path.unlink

    def fail_lease_unlink(path: Path, *args, **kwargs):
        if path.suffixes[-2:] == [".publishing", ".json"]:
            raise PermissionError("injected committed-lease unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lease_unlink)

    with HybridPlatform(tmp_path) as platform:
        first = platform.publish_generation("scores", "generation-committed", _frame())
        assert first.generation_id == "generation-committed"
        assert platform.query_generation("scores", "generation-committed")["value"].tolist() == [1, 2]

        retry = platform.publish_generation("scores", "generation-committed", _frame())
        assert retry == first
        with pytest.raises(ValueError, match="different content"):
            platform.publish_generation("scores", "generation-committed", _frame(2))

    assert len(list((tmp_path / "data" / "analytics" / ".staging").glob("*.publishing.json"))) == 1


def test_thirty_third_lease_candidate_fails_closed_with_bounded_result(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as platform:
        for index in range(hybrid._MAX_PUBLISHER_LEASE_CANDIDATES + 1):
            token = f"{index:032x}"
            lease = platform._publisher_lease_path("scores", "generation-overflow", token)
            lease.parent.mkdir(parents=True, exist_ok=True)
            lease.write_text("{}", encoding="utf-8")

        candidates, overflow = platform._publisher_lease_candidates(
            "scores", "generation-overflow"
        )
        assert overflow is True
        assert len(candidates) == hybrid._MAX_PUBLISHER_LEASE_CANDIDATES
        assert candidates == tuple(sorted(candidates))
        with pytest.raises(hybrid.StorageIntegrityError, match="too many publisher lease candidates"):
            platform.publish_generation("scores", "generation-overflow", _frame())
        assert platform.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-overflow",),
        ).fetchone() is None


def test_lease_token_mutation_cannot_authorise_final_publication(tmp_path: Path, monkeypatch) -> None:
    writer_reached_file_publish = threading.Event()
    allow_file_publish = threading.Event()
    original_atomic_write = hybrid.atomic_write_bytes
    errors: list[BaseException] = []

    def blocked_atomic_write(*args, **kwargs):
        writer_reached_file_publish.set()
        if not allow_file_publish.wait(timeout=5):
            raise TimeoutError("test did not release the lease-mutation publisher")
        return original_atomic_write(*args, **kwargs)

    monkeypatch.setattr(hybrid, "atomic_write_bytes", blocked_atomic_write)

    def publish() -> None:
        try:
            with HybridPlatform(tmp_path) as writer:
                writer.publish_generation("scores", "generation-lease-mutated", _frame())
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    writer_thread = threading.Thread(target=publish)
    writer_thread.start()
    assert writer_reached_file_publish.wait(timeout=5)
    lease_paths = list((tmp_path / "data" / "analytics" / ".staging").glob("*.publishing.json"))
    assert len(lease_paths) == 1
    lease_payload = json.loads(lease_paths[0].read_text(encoding="utf-8"))
    lease_payload["token"] = "0" * 32
    lease_paths[0].write_text(json.dumps(lease_payload), encoding="utf-8")
    allow_file_publish.set()
    writer_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], hybrid.StorageIntegrityError)
    with HybridPlatform(tmp_path) as recovered:
        assert recovered.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-lease-mutated",),
        ).fetchone() is None
    assert not (tmp_path / "data" / "analytics" / "scores" / "generation-lease-mutated.parquet").exists()
    assert lease_paths[0].exists()


def test_stale_and_future_pending_generations_without_a_publisher_lease_are_recovered(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as platform:
        with platform.store.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO analytical_generations
                    (dataset_id, generation_id, relative_path, sha256, row_count, columns_json,
                     stable_id_count, run_id_count, status, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'publishing', ?)
                """,
                [
                    (
                        "scores",
                        generation_id,
                        f"data/analytics/scores/{generation_id}.parquet",
                        "0" * 64,
                        0,
                        "[]",
                        0,
                        0,
                        committed_at,
                    )
                    for generation_id, committed_at in (
                        ("generation-stale", "2000-01-01T00:00:00+00:00"),
                        ("generation-future", "2999-01-01T00:00:00+00:00"),
                        ("generation-invalid", "not-a-timestamp"),
                    )
                ],
            )

    with HybridPlatform(tmp_path) as recovered:
        pending = recovered.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE dataset_id = ?",
            ("scores",),
        ).fetchone()
        assert pending is None


def test_malformed_or_unreadable_lease_is_not_destructively_recovered_by_age(
    tmp_path: Path, monkeypatch
) -> None:
    with HybridPlatform(tmp_path) as platform:
        with platform.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analytical_generations
                    (dataset_id, generation_id, relative_path, sha256, row_count, columns_json,
                     stable_id_count, run_id_count, status, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'publishing', ?)
                """,
                (
                    "scores",
                    "generation-malformed",
                    "data/analytics/scores/generation-malformed.parquet",
                    "0" * 64,
                    0,
                    "[]",
                    0,
                    0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        lease = platform._publisher_lease_path("scores", "generation-malformed", "c" * 32)
        lease.parent.mkdir(parents=True, exist_ok=True)
        lease.write_text("{malformed", encoding="utf-8")

    with HybridPlatform(tmp_path) as protected:
        assert protected.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-malformed",),
        ).fetchone() is not None

    real_read_text = Path.read_text

    def unreadable(path: Path, *args, **kwargs):
        if path == lease:
            raise PermissionError("transient lease read failure")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with HybridPlatform(tmp_path) as protected:
        assert protected.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-malformed",),
        ).fetchone() is not None

    stale_time = datetime.now(timezone.utc) - timedelta(days=2)
    connection = connect_storage(tmp_path)
    try:
        connection.execute(
            "UPDATE analytical_generations SET committed_at = ? WHERE generation_id = ?",
            (stale_time.isoformat(), "generation-malformed"),
        )
        connection.commit()
    finally:
        connection.close()
    os.utime(lease, (stale_time.timestamp(), stale_time.timestamp()))

    with HybridPlatform(tmp_path) as recovered:
        assert recovered.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-malformed",),
        ).fetchone() is not None


def test_posix_permission_error_means_process_is_alive(monkeypatch) -> None:
    def denied(_pid: int, _signal: int) -> None:
        raise PermissionError("EPERM")

    monkeypatch.setattr(hybrid.os, "kill", denied)

    assert hybrid._posix_pid_alive(12345) is True


def test_publisher_lease_is_created_with_private_mode(tmp_path: Path, monkeypatch) -> None:
    real_open = hybrid.os.open
    lease_modes: list[int] = []

    def recording_open(path, flags, mode=0o777):
        if str(path).endswith(".publishing.json"):
            lease_modes.append(mode)
        return real_open(path, flags, mode)

    monkeypatch.setattr(hybrid.os, "open", recording_open)

    with HybridPlatform(tmp_path) as platform:
        platform.publish_generation("scores", "generation-private-lease", _frame())

    assert lease_modes == [0o600]


def test_live_identity_matching_publisher_is_not_expired_by_wall_clock(
    tmp_path: Path,
) -> None:
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    process_start_id = hybrid._process_start_identity(os.getpid())
    assert process_start_id is not None
    with HybridPlatform(tmp_path) as platform:
        with platform.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analytical_generations
                    (dataset_id, generation_id, relative_path, sha256, row_count, columns_json,
                     stable_id_count, run_id_count, status, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'publishing', ?)
                """,
                (
                    "scores",
                    "generation-old-live",
                    "data/analytics/scores/generation-old-live.parquet",
                    "0" * 64,
                    0,
                    "[]",
                    0,
                    0,
                    old_timestamp,
                ),
            )
            row = connection.execute(
                "SELECT rowid AS catalogue_rowid FROM analytical_generations WHERE generation_id = ?",
                ("generation-old-live",),
            ).fetchone()
        assert row is not None
        publication = hybrid._PublicationIdentity(
            dataset_id="scores",
            generation_id="generation-old-live",
            sha256="0" * 64,
            committed_at=old_timestamp,
            catalogue_rowid=int(row["catalogue_rowid"]),
            token="a" * 32,
            owner_pid=os.getpid(),
            process_start_id=process_start_id,
            created_at=old_timestamp,
        )
        platform._claim_publisher_lease(
            platform._publisher_lease_path("scores", "generation-old-live", publication.token),
            publication,
        )

    with HybridPlatform(tmp_path) as recovered:
        assert recovered.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-old-live",),
        ).fetchone() is not None


def test_reused_pid_with_different_process_start_does_not_preserve_lease(
    tmp_path: Path, monkeypatch
) -> None:
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with HybridPlatform(tmp_path) as platform:
        with platform.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analytical_generations
                    (dataset_id, generation_id, relative_path, sha256, row_count, columns_json,
                     stable_id_count, run_id_count, status, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'publishing', ?)
                """,
                (
                    "scores",
                    "generation-reused-pid",
                    "data/analytics/scores/generation-reused-pid.parquet",
                    "0" * 64,
                    0,
                    "[]",
                    0,
                    0,
                    old_timestamp,
                ),
            )
            row = connection.execute(
                "SELECT rowid AS catalogue_rowid FROM analytical_generations WHERE generation_id = ?",
                ("generation-reused-pid",),
            ).fetchone()
        assert row is not None
        publication = hybrid._PublicationIdentity(
            dataset_id="scores",
            generation_id="generation-reused-pid",
            sha256="0" * 64,
            committed_at=old_timestamp,
            catalogue_rowid=int(row["catalogue_rowid"]),
            token="d" * 32,
            owner_pid=12345,
            process_start_id="old-process-start",
            created_at=old_timestamp,
        )
        platform._claim_publisher_lease(
            platform._publisher_lease_path("scores", "generation-reused-pid", publication.token),
            publication,
        )

    monkeypatch.setattr(hybrid, "_process_start_identity", lambda _pid: "new-process-start")
    monkeypatch.setattr(hybrid, "_pid_alive", lambda _pid: True)

    with HybridPlatform(tmp_path) as recovered:
        assert recovered.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-reused-pid",),
        ).fetchone() is None


def test_live_pid_with_unavailable_start_identity_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with HybridPlatform(tmp_path) as platform:
        with platform.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analytical_generations
                    (dataset_id, generation_id, relative_path, sha256, row_count, columns_json,
                     stable_id_count, run_id_count, status, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'publishing', ?)
                """,
                (
                    "scores",
                    "generation-unknown-start",
                    "data/analytics/scores/generation-unknown-start.parquet",
                    "0" * 64,
                    0,
                    "[]",
                    0,
                    0,
                    old_timestamp,
                ),
            )
            row = connection.execute(
                "SELECT rowid AS catalogue_rowid FROM analytical_generations WHERE generation_id = ?",
                ("generation-unknown-start",),
            ).fetchone()
        assert row is not None
        publication = hybrid._PublicationIdentity(
            dataset_id="scores",
            generation_id="generation-unknown-start",
            sha256="0" * 64,
            committed_at=old_timestamp,
            catalogue_rowid=int(row["catalogue_rowid"]),
            token="e" * 32,
            owner_pid=12345,
            process_start_id="unavailable",
            created_at=old_timestamp,
        )
        platform._claim_publisher_lease(
            platform._publisher_lease_path("scores", "generation-unknown-start", publication.token),
            publication,
        )

    monkeypatch.setattr(hybrid, "_process_start_identity", lambda _pid: None)
    monkeypatch.setattr(hybrid, "_pid_alive", lambda _pid: True)

    with HybridPlatform(tmp_path) as protected:
        assert protected.store.connection.execute(
            "SELECT 1 FROM analytical_generations WHERE generation_id = ?",
            ("generation-unknown-start",),
        ).fetchone() is not None


def test_compaction_is_preview_only_until_explicitly_confirmed(tmp_path: Path) -> None:
    with HybridPlatform(tmp_path) as platform:
        platform.publish_generation("scores", "generation-1", _frame(1))
        platform.publish_generation("scores", "generation-2", _frame(2))
        assert platform.compact_generations("scores") == ("generation-1",)
        assert platform.list_generations("scores")
        assert platform.compact_generations("scores", confirm=True) == ("generation-1",)
        assert [item.generation_id for item in platform.list_generations("scores")] == ["generation-2"]
        assert platform.summary().last_compaction is not None
        assert platform.retention_candidates(datetime.now(timezone.utc)) == platform.list_generations("scores")


def test_backup_restore_and_legacy_exports_preserve_catalogue(tmp_path: Path) -> None:
    backup = tmp_path / "backup.zip"
    restored_root = tmp_path / "restored"
    with HybridPlatform(tmp_path / "source") as source:
        source.store.put("journal", "decision-1", {"decision": "hold"})
        source.publish_generation("scores", "generation-1", _frame())
        source.export_transactional_json(tmp_path / "source.json")
        source.export_transactional_csv(tmp_path / "source.csv")
        manifest = source.create_backup(backup)
        preview = source.validate_backup(manifest.archive)
        assert preview.valid
        restored_root.mkdir()
        target = HybridPlatform(restored_root)
        target.close()
        result = target.restore_backup(preview)
        assert result.ok
    with HybridPlatform(restored_root) as restored:
        assert restored.store.get("journal", "decision-1") is not None
        assert restored.query_generation("scores", "generation-1")["value"].tolist() == [1, 2]
    assert (tmp_path / "source.json").is_file()
    assert (tmp_path / "source.csv").is_file()
