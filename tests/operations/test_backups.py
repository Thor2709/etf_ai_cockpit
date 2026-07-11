from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.core.atomic_io import backup_paths, restore_backup_manifest, verify_backup_manifest


def test_backup_manifest_is_checksum_evidence_and_tampering_blocks_restore(tmp_path: Path) -> None:
    source = tmp_path / "data" / "canonical.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"generation": "old"}', encoding="utf-8")
    manifest = backup_paths((source,), tmp_path / "backups")
    evidence = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))

    assert evidence["entries"][0]["sha256"] == manifest.entries[0].sha256
    manifest.entries[0].backup_path.write_text("tampered", encoding="utf-8")
    assert verify_backup_manifest(manifest) is False
    with pytest.raises(OSError, match="invalid backup manifest"):
        restore_backup_manifest(manifest)
