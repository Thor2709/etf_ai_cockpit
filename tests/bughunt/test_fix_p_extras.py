from __future__ import annotations

import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data import trust_artifacts
from etf_cockpit.data.backup_restore import create_backup
from etf_cockpit.data.privacy import PrivacyDeletionError, delete_private_data
from etf_cockpit.data.score_history import append_score_run, score_history_frame


def test_s8_03_serialized_appends_preserve_both_runs(tmp_path):
    scores = pd.DataFrame([{"instrument_id": "X", "final_combined_score_10": 5.0}])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(append_score_run, scores, run_id, "2026-10-05T00:00:00Z", root=tmp_path)
            for run_id in ("A", "B")
        ]
        for future in futures:
            future.result(timeout=10)

    history = score_history_frame(root=tmp_path)
    assert set(history["run_id"]) == {"A", "B"}


def test_c1_linked_private_root_fails_closed(monkeypatch, tmp_path):
    root = tmp_path / "application"
    private = root / "data" / "private"
    private.mkdir(parents=True)
    outside = tmp_path / "outside-private"
    outside.mkdir()
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == private:
            return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(PrivacyDeletionError):
        delete_private_data(root, confirmation="DELETE PRIVATE DATA")


def test_c2_unreadable_trust_history_aborts_append(monkeypatch, tmp_path):
    path = tmp_path / "history.parquet"
    path.write_bytes(b"existing")
    monkeypatch.setattr(trust_artifacts, "_safe_read_parquet", lambda path, columns: pd.DataFrame(columns=columns))

    def unreadable(path):
        raise PermissionError("history is temporarily unreadable")

    monkeypatch.setattr(pd, "read_parquet", unreadable)
    with pytest.raises(OSError, match="cannot append to unreadable evidence history"):
        trust_artifacts._append_parquet(path, pd.DataFrame([{"id": "new"}]), ["id"], id_columns=["id"])


def test_c3_sqlite_backup_excludes_database_sidecars(monkeypatch, tmp_path):
    database = tmp_path / "store.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('kept')")
    for suffix in ("-wal", "-shm", "-journal"):
        database.with_name(database.name + suffix).write_bytes(b"stale sidecar")
    archive_path = tmp_path / "backup.zip"
    monkeypatch.setattr("etf_cockpit.data.backup_restore._sqlite_snapshot", lambda path: b"snapshot")

    create_backup([database.parent], archive_path, include_transient=True)

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "store.sqlite" in names
    assert not any(name.startswith("store.sqlite-") for name in names)
