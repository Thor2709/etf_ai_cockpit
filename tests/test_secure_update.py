from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from etf_cockpit.core.secure_update import (
    build_update_manifest,
    extract_verified_update,
    sign_update_manifest,
    verify_update_bundle,
)


KEY = b"a sufficiently long offline update key"


def _bundle(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)


def test_signed_update_is_verified_and_staged_without_replacing_target(tmp_path: Path) -> None:
    archive = tmp_path / "update.zip"
    _bundle(archive, [("app/version.txt", b"0.1.0rc2\n"), ("configs/update.yaml", b"offline: true\n")])
    manifest = build_update_manifest(archive)
    signature = sign_update_manifest(manifest, KEY, key_id="offline-test")

    result = verify_update_bundle(archive, manifest, signature, KEY)
    staging = extract_verified_update(archive, manifest, signature, KEY, tmp_path / "installed")

    assert result.ok is True
    assert result.status == "verified"
    assert (staging / "app" / "version.txt").read_text(encoding="utf-8") == "0.1.0rc2\n"
    assert not (tmp_path / "installed").exists()


def test_tampered_or_unsigned_update_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "update.zip"
    _bundle(archive, [("app.txt", b"original")])
    manifest = build_update_manifest(archive)
    signature = sign_update_manifest(manifest, KEY, key_id="offline-test")
    _bundle(archive, [("app.txt", b"tampered")])

    tampered = verify_update_bundle(archive, manifest, signature, KEY)
    unsigned = verify_update_bundle(archive, manifest, None, None)

    assert tampered.ok is False
    assert any("archive SHA-256" in error for error in tampered.errors)
    assert unsigned.ok is False
    assert any("signing key" in error for error in unsigned.errors)


def test_update_rejects_traversal_and_symbolic_link_members(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    _bundle(traversal, [("../outside.txt", b"no")])
    with pytest.raises(ValueError, match="unsafe update member"):
        build_update_manifest(traversal)

    symlink = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink, "w") as archive:
        archive.writestr(info, b"target")
    with pytest.raises(ValueError, match="symbolic links"):
        build_update_manifest(symlink)
