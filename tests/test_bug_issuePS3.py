from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.core import atomic_io, migrations, session_log
from etf_cockpit.core.migrations import Migration, MigrationContext, run_migrations


def _latest() -> int:
    return max(m.version for m in migrations.MIGRATIONS)


# --- A.C2.S18.N002: failed migration restores stores, state and markers (regression guard) ---
def test_failed_migration_leaves_no_state_marker_or_store_change(tmp_path, monkeypatch):
    store = tmp_path / "data" / "store.json"
    store.parent.mkdir()
    store.write_text('{"v": 0}', encoding="utf-8")
    context = MigrationContext(tmp_path, tmp_path / "backups", (store,))

    def first(ctx: MigrationContext) -> None:
        store.write_text('{"v": 1}', encoding="utf-8")
        migrations._write_schema_marker(ctx, 1, "first")

    def boom(_: MigrationContext) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(migrations, "MIGRATIONS", (Migration(1, "first", first), Migration(2, "boom", boom)))
    with pytest.raises(RuntimeError, match="injected"):
        run_migrations(context)
    assert store.read_text(encoding="utf-8") == '{"v": 0}'
    assert not context.state_path.exists()
    assert not (context.metadata_root / "first.json").exists()
    # A retry after the failure re-attempts from version 0 (no partially recorded progress).
    monkeypatch.setattr(migrations, "MIGRATIONS", (Migration(1, "first", first),))
    assert run_migrations(context).applied_versions == (1,)


# --- D.C3.S21.N001: state schema_version / shape validation ---
@pytest.mark.parametrize("bad_version", [-1, "2", 2.0, True, None, 10_000])
def test_unsupported_state_schema_version_fails_closed(tmp_path, bad_version):
    context = MigrationContext(tmp_path, tmp_path / "backups")
    context.state_path.parent.mkdir(parents=True)
    context.state_path.write_text(json.dumps({"schema_version": bad_version, "applied": []}), encoding="utf-8")
    before = context.state_path.read_bytes()
    with pytest.raises(ValueError):
        run_migrations(context)
    assert context.state_path.read_bytes() == before
    assert not context.metadata_root.exists()


@pytest.mark.parametrize("payload", ["[]", "42", '"text"', "null"])
def test_non_object_migration_state_fails_closed_with_value_error(tmp_path, payload):
    context = MigrationContext(tmp_path, tmp_path / "backups")
    context.state_path.parent.mkdir(parents=True)
    context.state_path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        run_migrations(context)
    assert context.state_path.read_text(encoding="utf-8") == payload


def test_migration_is_idempotent_at_latest_version(tmp_path):
    context = MigrationContext(tmp_path, tmp_path / "backups")
    first = run_migrations(context)
    assert first.current_version == _latest()
    state_bytes = context.state_path.read_bytes()
    second = run_migrations(context)
    assert second.applied_versions == () and second.backup_manifest is None
    assert context.state_path.read_bytes() == state_bytes


# --- D.C4.S21.N001: atomic_write_group failure mid-commit rolls the whole group back ---
def test_group_failure_during_commit_restores_every_destination(tmp_path):
    first = tmp_path / "data" / "a.bin"
    second = tmp_path / "data" / "b.bin"
    first.parent.mkdir()
    first.write_bytes(b"old-a")
    second.write_bytes(b"old-b")
    calls = {"b": 0}

    def validate_b(path: Path) -> None:
        calls["b"] += 1
        if calls["b"] >= 2:  # second call is the commit-time revalidation
            raise ValueError("commit-time validation failure")

    requests = (
        atomic_io.AtomicWriteRequest(first, b"new-a", lambda p: p.read_bytes()),
        atomic_io.AtomicWriteRequest(second, b"new-b", validate_b),
    )
    with pytest.raises(ValueError, match="commit-time"):
        atomic_io.atomic_write_group(requests)
    assert first.read_bytes() == b"old-a"
    assert second.read_bytes() == b"old-b"
    assert not list(tmp_path.rglob(".atomic-transactions/*"))


def test_group_rejects_duplicate_destinations_without_touching_files(tmp_path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"keep")
    req = atomic_io.AtomicWriteRequest(target, b"new", lambda p: None)
    with pytest.raises(ValueError):
        atomic_io.atomic_write_group((req, req))
    assert target.read_bytes() == b"keep"


# --- D.C5.S19.N003: read_session_events limit semantics ---
@pytest.fixture
def log_path(tmp_path, monkeypatch):
    path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", path)
    return path


@pytest.mark.parametrize("limit", [0, -1, -50])
def test_read_session_events_non_positive_limit_returns_nothing(log_path, limit):
    log_path.write_text("".join(json.dumps({"n": i}) + "\n" for i in range(5)), encoding="utf-8")
    assert session_log.read_session_events(limit=limit) == []


def test_read_session_events_returns_last_n_dict_rows_only(log_path):
    rows = ['{"n": 1}', "not json", "[1, 2]", "7", '"s"', "null", '{"n": 2}', '{"n": 3}']
    log_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert session_log.read_session_events(limit=100) == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert session_log.read_session_events(limit=2) == [{"n": 2}, {"n": 3}]


# --- D.C5.S19.N001: _base_event sequence is unique and monotonic ---
def test_base_event_sequence_is_strictly_increasing():
    sequences = [session_log._base_event()["sequence_number"] for _ in range(20)]
    assert sequences == sorted(set(sequences))
