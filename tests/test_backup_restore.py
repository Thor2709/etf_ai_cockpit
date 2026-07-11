from __future__ import annotations

from pathlib import Path

from etf_cockpit.data.backup_restore import create_backup, validate_restore, commit_restore


def test_backup_restore_round_trip_and_manifest_checksums(tmp_path: Path) -> None:
    source = tmp_path / "configs" / "settings.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("safe: true\n", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    manifest = create_backup([source], archive)
    preview = validate_restore(archive)
    assert preview.valid is True
    destination = tmp_path / "restored"
    result = commit_restore(preview, destination)
    assert result.restored == 1
    assert (destination / "configs" / "settings.yaml").read_text(encoding="utf-8") == "safe: true\n"
    assert manifest.checksums


def test_restore_rejects_zip_traversal(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../secret.txt", "bad")
    assert validate_restore(archive).valid is False
