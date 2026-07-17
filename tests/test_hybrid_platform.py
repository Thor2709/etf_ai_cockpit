from __future__ import annotations

from datetime import datetime, timezone
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
