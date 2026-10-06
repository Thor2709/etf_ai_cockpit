from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def test_s6_01_missing_holdings_does_not_rewrite_existing_prices(tmp_path, monkeypatch):
    from etf_cockpit.data import sample_data

    prices_dir = tmp_path / "raw" / "prices"
    portfolios_dir = tmp_path / "portfolios"
    prices_dir.mkdir(parents=True)
    portfolios_dir.mkdir()
    price_path = prices_dir / "sample_prices.csv"
    price_path.write_text("close\n10\n", encoding="utf-8")
    monkeypatch.setattr(sample_data, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sample_data, "PORTFOLIOS_DIR", portfolios_dir)
    monkeypatch.setattr(sample_data, "ensure_project_dirs", lambda: None)
    monkeypatch.setattr(pd, "read_csv", lambda path: pd.DataFrame({"close": [10]}))
    monkeypatch.setattr(
        sample_data,
        "generate_sample_holdings",
        lambda config, prices: pd.DataFrame({"shares": [1]}),
    )
    writes = []
    monkeypatch.setattr(pd.DataFrame, "to_csv", lambda self, path, **kwargs: writes.append(Path(path)))

    sample_data.ensure_sample_files(object())

    assert writes == [portfolios_dir / "current_holdings.csv"]


def test_s7_01_linked_data_ancestor_skips_private_deletion(tmp_path, monkeypatch):
    from etf_cockpit.data.privacy import delete_private_data

    root = tmp_path / "app"
    data_path = root / "data"
    data_path.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "keep.txt"
    victim.write_text("keep", encoding="utf-8")
    original_is_symlink = Path.is_symlink

    def report_data_link(path):
        return path == data_path or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_data_link)
    assert delete_private_data(root, confirmation="DELETE PRIVATE DATA") == ()
    assert victim.exists()


def test_s7_02_sqlite_snapshot_failure_aborts_backup(tmp_path, monkeypatch):
    import sqlite3

    import etf_cockpit.data.backup_restore as backup_restore

    database = tmp_path / "cockpit.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value INTEGER)")
    archive = tmp_path / "backup.zip"

    def fail_snapshot(path):
        raise OSError("snapshot failure")

    monkeypatch.setattr(backup_restore, "_sqlite_snapshot", fail_snapshot)
    with pytest.raises(OSError, match="snapshot failure"):
        backup_restore.create_backup([database], archive)
    assert not archive.exists()
