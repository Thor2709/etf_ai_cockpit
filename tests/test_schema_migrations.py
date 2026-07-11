from __future__ import annotations

import json

import pytest

from etf_cockpit.core.atomic_io import verify_backup_manifest
from etf_cockpit.core import migrations
from etf_cockpit.core.migrations import Migration, MigrationContext, run_migrations


def test_migration_is_idempotent_and_backup_manifest_matches_checksums(tmp_path):
    existing = tmp_path / "data" / "provider_status.json"
    existing.parent.mkdir()
    existing.write_text(json.dumps({"provider": "yfinance", "state": "ok"}), encoding="utf-8")
    context = MigrationContext(
        root=tmp_path,
        backup_root=tmp_path / "backups",
        managed_paths=(existing,),
    )

    first = run_migrations(context)
    second = run_migrations(context)

    assert first.applied_versions == (1, 2, 3, 4)
    assert second.applied_versions == ()
    assert first.backup_manifest is not None
    assert verify_backup_manifest(first.backup_manifest)
    assert json.loads(existing.read_text(encoding="utf-8")) == {
        "provider": "yfinance",
        "state": "ok",
    }


def test_migration_accepts_absent_stores_and_writes_version_metadata(tmp_path):
    context = MigrationContext(root=tmp_path, backup_root=tmp_path / "backups")

    report = run_migrations(context)

    assert report.applied_versions == (1, 2, 3, 4)
    state = json.loads((tmp_path / "data" / ".migration_state.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == 4
    assert [item["version"] for item in state["applied"]] == [1, 2, 3, 4]
    assert (tmp_path / "data" / ".schema_versions" / "history_changes_v1.json").is_file()


def test_failed_migration_restores_managed_store_and_removes_partial_metadata(tmp_path, monkeypatch):
    store = tmp_path / "data" / "store.json"
    store.parent.mkdir()
    store.write_text('{"version": 0}', encoding="utf-8")
    context = MigrationContext(tmp_path, tmp_path / "backups", (store,))

    def mutate(_: MigrationContext) -> None:
        store.write_text('{"version": 1}', encoding="utf-8")

    def fail(_: MigrationContext) -> None:
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        (
            Migration(1, "mutate", mutate),
            Migration(2, "fail", fail),
        ),
    )

    with pytest.raises(RuntimeError, match="injected migration failure"):
        run_migrations(context)

    assert store.read_text(encoding="utf-8") == '{"version": 0}'
    assert not context.state_path.exists()
