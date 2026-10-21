"""#984 backup/restore integrity: chain linkage, retention, tombstones, creation policy, temp files, SQLite secrets."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

import etf_cockpit.data.backup_restore as backup_restore
from etf_cockpit.data.backup_restore import (
    BackupError,
    apply_backup_retention,
    commit_incremental_restore,
    commit_restore,
    create_backup,
    create_encrypted_backup,
    create_incremental_backup,
    restore_encrypted_backup,
    sweep_stale_plaintext_temp,
    validate_encrypted_restore,
    validate_restore,
)
from tests.test_backup_restore import _copy_repository_configs

KEY = "correct recovery key"
CONFIG_NAMES = (
    "settings.yaml",
    "universe.yaml",
    "portfolio_targets.yaml",
    "risk_limits.yaml",
    "costs.yaml",
    "model_settings.yaml",
    "data_providers.yaml",
)


@pytest.fixture(autouse=True)
def _private_system_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    temp_root = tmp_path / "system-temp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    monkeypatch.setattr(backup_restore, "_plaintext_temp_swept", False)
    return temp_root


def _data_dir(tmp_path: Path, **files: str) -> Path:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    for name, text in files.items():
        (data / name).write_text(text, encoding="utf-8")
    return data


def _chain(tmp_path: Path):
    data = _data_dir(tmp_path, **{"holdings.csv": "a", "other.csv": "b"})
    base_archive = tmp_path / "base.backup"
    base = create_backup([data], base_archive)
    (data / "other.csv").write_text("changed", encoding="utf-8")
    delta_archive = tmp_path / "delta.backup"
    delta = create_incremental_backup([data], delta_archive, base)
    return data, base_archive, base, delta_archive, delta


def test_incremental_archive_refused_as_standalone(tmp_path: Path) -> None:  # D023-N001, A.C2.S22.N001
    _data, _base_archive, _base, delta_archive, _delta = _chain(tmp_path)
    destination = tmp_path / "restored"
    result = commit_restore(validate_restore(delta_archive, destination=destination), destination)
    assert result.ok is False
    assert result.error == "incremental_archive_requires_base_chain"
    assert not destination.exists()
    # A chain that starts at a delta is refused too.
    result = commit_incremental_restore([validate_restore(delta_archive)], destination)
    assert result.ok is False and result.error == "incremental_archive_requires_base_chain"
    assert not destination.exists()


def test_second_full_archive_without_linkage_refused(tmp_path: Path) -> None:  # D021-N002
    data, base_archive, _base, _delta_archive, _delta = _chain(tmp_path)
    second_full = tmp_path / "second-full.backup"
    create_backup([data], second_full)
    destination = tmp_path / "restored"
    result = commit_incremental_restore([validate_restore(base_archive), validate_restore(second_full)], destination)
    assert result.ok is False
    assert result.error == "incremental_base_manifest_mismatch"
    assert not destination.exists()


def test_linked_chain_still_restores(tmp_path: Path) -> None:
    _data, base_archive, _base, delta_archive, _delta = _chain(tmp_path)
    destination = tmp_path / "restored"
    result = commit_incremental_restore([validate_restore(base_archive), validate_restore(delta_archive)], destination)
    assert result.ok is True
    assert (destination / "data" / "other.csv").read_text(encoding="utf-8") == "changed"
    assert (destination / "data" / "holdings.csv").read_text(encoding="utf-8") == "a"


def test_retention_keeps_chain_base(tmp_path: Path) -> None:  # D023-N002
    data = _data_dir(tmp_path, **{"a.csv": "1"})
    backups = tmp_path / "backups"
    backups.mkdir()
    base_path = backups / "0-base.backup"
    base = create_backup([data], base_path)
    unrelated = backups / "1-unrelated.backup"
    create_backup([data], unrelated)
    (data / "a.csv").write_text("2", encoding="utf-8")
    delta_one = create_incremental_backup([data], backups / "2-delta.backup", base)
    (data / "a.csv").write_text("3", encoding="utf-8")
    delta_two_path = backups / "3-delta.backup"
    create_incremental_backup([data], delta_two_path, delta_one)
    now = time.time()
    for age, path in enumerate((base_path, unrelated, delta_one.archive, delta_two_path)):
        os.utime(path, (now - 1000 + age * 10, now - 1000 + age * 10))
    removed = apply_backup_retention(backups, keep=2)
    assert removed == (unrelated,)
    assert base_path.exists() and delta_one.archive.exists() and delta_two_path.exists()
    destination = tmp_path / "restored"
    chain = [validate_restore(path) for path in (base_path, delta_one.archive, delta_two_path)]
    assert commit_incremental_restore(chain, destination).ok is True
    assert (destination / "data" / "a.csv").read_text(encoding="utf-8") == "3"


def _tombstone_archive(tmp_path: Path, base_names: dict[str, bytes], deleted: list[str]):
    base_source = tmp_path / "src"
    for name, payload in base_names.items():
        target = base_source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    base_archive = tmp_path / "base.backup"
    base = create_backup([base_source / "data"], base_archive)
    delta_archive = tmp_path / "delta.backup"
    manifest_bytes = (
        json.dumps(
            {
                "schema_version": 2,
                "checksums": {},
                "excluded": [],
                "incremental": True,
                "base_manifest_checksum": base.manifest_checksum,
                "deleted": deleted,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    with zipfile.ZipFile(delta_archive, "w") as archive:
        archive.writestr("manifest.json", manifest_bytes)
    return base_archive, delta_archive


def test_tombstone_outside_prior_inventory_refused(tmp_path: Path) -> None:  # D121-N001
    base_archive, delta_archive = _tombstone_archive(
        tmp_path, {"data/holdings.csv": b"holdings"}, ["data/unrelated.csv"]
    )
    destination = tmp_path / "restored"
    (destination / "data").mkdir(parents=True)
    unrelated = destination / "data" / "unrelated.csv"
    unrelated.write_text("keep me", encoding="utf-8")
    result = commit_incremental_restore([validate_restore(base_archive), validate_restore(delta_archive)], destination)
    assert result.ok is False
    assert result.error == "tombstone_outside_inventory:data/unrelated.csv"
    assert unrelated.read_text(encoding="utf-8") == "keep me"


def test_tombstone_inside_inventory_still_deletes(tmp_path: Path) -> None:
    base_archive, delta_archive = _tombstone_archive(
        tmp_path, {"data/holdings.csv": b"holdings", "data/old.csv": b"old"}, ["data/old.csv"]
    )
    destination = tmp_path / "restored"
    result = commit_incremental_restore([validate_restore(base_archive), validate_restore(delta_archive)], destination)
    assert result.ok is True
    assert not (destination / "data" / "old.csv").exists()
    assert (destination / "data" / "holdings.csv").exists()


def test_deletion_only_config_tombstone_is_validated(tmp_path: Path) -> None:  # D021-N003
    destination = tmp_path / "destination"
    config_dir = _copy_repository_configs(destination)
    base_archive = tmp_path / "base.backup"
    base = create_backup([config_dir / name for name in CONFIG_NAMES], base_archive)
    required = config_dir / "risk_limits.yaml"
    original = required.read_bytes()
    required.unlink()
    delta_archive = tmp_path / "delta.backup"
    delta = create_incremental_backup([config_dir / name for name in CONFIG_NAMES if name != "risk_limits.yaml"], delta_archive, base)
    required.write_bytes(original)
    assert json.loads(zipfile.ZipFile(delta_archive).read("manifest.json"))["deleted"] == ["configs/risk_limits.yaml"]
    assert delta.checksums == {}
    result = commit_incremental_restore(
        [validate_restore(base_archive, destination=destination), validate_restore(delta_archive, destination=destination)],
        destination,
    )
    assert result.ok is False
    assert "settings" in result.error
    assert required.read_bytes() == original


@pytest.mark.parametrize("root", ["models", "exports"])
def test_creation_refuses_roots_restore_refuses(tmp_path: Path, root: str) -> None:  # A119-N001, A.C2.S19.N003
    source = tmp_path / "project" / root / "artifact.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"payload")
    archive = tmp_path / "backup.backup"
    with pytest.raises(BackupError, match=f"unapproved_path:{root}/artifact.bin"):
        create_backup([source], archive)
    assert not archive.exists()
    # Restore's own verdict on such an entry is the same, so the two stay aligned.
    crafted = tmp_path / "crafted.backup"
    with zipfile.ZipFile(crafted, "w") as handle:
        handle.writestr(f"{root}/artifact.bin", b"payload")
        handle.writestr("manifest.json", json.dumps({"schema_version": 1, "checksums": {}}))
    assert any(error.startswith("unapproved_path") for error in validate_restore(crafted).errors)


def test_plaintext_backup_excludes_private_notes_but_encrypted_keeps_them(tmp_path: Path) -> None:  # E118-N002
    data = _data_dir(tmp_path, **{"journal.csv": "x"})
    private = data / "private"
    private.mkdir()
    (private / "notes.txt").write_text("my private note", encoding="utf-8")
    plain = create_backup([data], tmp_path / "plain.backup")
    assert "data/private/notes.txt" not in plain.checksums
    assert "data/private/notes.txt" in plain.excluded
    base = create_backup([data], tmp_path / "base.backup")
    delta = create_incremental_backup([data], tmp_path / "delta.backup", base)
    assert "data/private/notes.txt" not in delta.checksums and "data/private/notes.txt" in delta.excluded
    encrypted = create_encrypted_backup([data], tmp_path / "enc.backup", KEY)
    assert "data/private/notes.txt" in encrypted.checksums


def _sqlite_with(path: Path, schema: str, rows: list[tuple]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(schema)
        placeholders = ",".join("?" for _ in rows[0])
        connection.executemany(f"INSERT INTO t VALUES ({placeholders})", rows)
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("schema", "rows"),
    [
        ("CREATE TABLE t (id INTEGER, api_key TEXT)", [(1, "sk-live-123")]),
        ("CREATE TABLE t (name TEXT, value TEXT)", [("password", "hunter2")]),
        ("CREATE TABLE t (id INTEGER, payload TEXT)", [(1, '{"client_secret": "abc"}')]),
        ("CREATE TABLE t (id INTEGER, blob BLOB)", [(1, b"access_token=abc123")]),
    ],
)
def test_sqlite_row_secret_detected_and_database_excluded(tmp_path: Path, schema: str, rows: list[tuple]) -> None:  # E118-N003
    data = tmp_path / "data"
    data.mkdir()
    database = data / "store.sqlite"
    _sqlite_with(database, schema, rows)
    manifest = create_backup([data], tmp_path / "backup.backup")
    assert "data/store.sqlite" not in manifest.checksums
    assert "data/store.sqlite" in manifest.excluded


def test_sqlite_without_secrets_is_still_backed_up(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _sqlite_with(data / "store.sqlite", "CREATE TABLE t (id INTEGER, note TEXT, api_key TEXT)", [(1, "hello", None), (2, "x", "")])
    manifest = create_backup([data], tmp_path / "backup.backup")
    assert "data/store.sqlite" in manifest.checksums


def test_decrypted_temp_removed_and_private(tmp_path: Path, _private_system_temp: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # A119-N002
    data = _data_dir(tmp_path, **{"journal.csv": "x"})
    archive = tmp_path / "enc.backup"
    create_encrypted_backup([data], archive, KEY)
    seen: list[Path] = []
    original = backup_restore._private_plaintext_archive

    def spy(plaintext: bytes):
        context = original(plaintext)
        path = context.__enter__()
        seen.append(path)

        class Wrapper:
            def __enter__(self_inner):
                return path

            def __exit__(self_inner, *exc):
                return context.__exit__(*exc)

        return Wrapper()

    monkeypatch.setattr(backup_restore, "_private_plaintext_archive", spy)
    assert validate_encrypted_restore(archive, KEY).valid is True
    assert restore_encrypted_backup(archive, tmp_path / "restored", KEY).ok is True
    assert len(seen) == 2
    for path in seen:
        assert path.parent.parent == _private_system_temp
        assert path.parent.name.startswith("etf-cockpit-plain-")
        assert not path.parent.exists()
    assert not list(_private_system_temp.iterdir())


def test_startup_removes_stale_decrypted_temp_without_decrypt(_private_system_temp: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # A119-N002
    from etf_cockpit.app import flet_app

    stale = _private_system_temp / "etf-cockpit-plain-crashed"
    stale.mkdir()
    (stale / "decrypted.backup").write_bytes(b"plaintext")
    old = time.time() - 600  # older than the startup window, younger than the lazy 1h sweep
    os.utime(stale, (old, old))
    fresh = _private_system_temp / "etf-cockpit-plain-live"
    fresh.mkdir()

    class _Stop(Exception):
        pass

    def stop() -> None:
        raise _Stop

    monkeypatch.setattr(flet_app, "_patch_flet_static_temp_dir", stop)  # first step after the sweep in run()
    with pytest.raises(_Stop):
        flet_app.run()
    assert not stale.exists()
    assert fresh.exists()
    shutil.rmtree(fresh)


def test_startup_sweep_goes_through_the_application_facade(_private_system_temp: Path) -> None:
    from etf_cockpit.application.backup_maintenance import sweep_decrypted_backup_temp

    stale = _private_system_temp / "etf-cockpit-plain-startup-stale"
    stale.mkdir()
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = _private_system_temp / "etf-cockpit-plain-startup-fresh"
    fresh.mkdir()
    assert sweep_decrypted_backup_temp(max_age_seconds=3600) == 1
    assert not stale.exists() and fresh.exists()


def test_stale_decrypted_temp_is_swept(tmp_path: Path, _private_system_temp: Path) -> None:  # A119-N002
    stale = _private_system_temp / "etf-cockpit-plain-stale"
    stale.mkdir()
    (stale / "decrypted.backup").write_bytes(b"plaintext")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = _private_system_temp / "etf-cockpit-plain-fresh"
    fresh.mkdir()
    unrelated = _private_system_temp / "other-dir"
    unrelated.mkdir()
    assert sweep_stale_plaintext_temp() == 1
    assert not stale.exists() and fresh.exists() and unrelated.exists()
    # The first decrypt in a process sweeps as well.
    leftover = _private_system_temp / "etf-cockpit-plain-leftover"
    leftover.mkdir()
    os.utime(leftover, (old, old))
    data = _data_dir(tmp_path, **{"journal.csv": "x"})
    archive = tmp_path / "enc.backup"
    create_encrypted_backup([data], archive, KEY)
    assert validate_encrypted_restore(archive, KEY).valid is True
    assert not leftover.exists()
    shutil.rmtree(fresh)
