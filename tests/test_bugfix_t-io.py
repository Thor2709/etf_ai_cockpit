"""Regression tests for the T-IO bug-hunt batch (docs/development/BUGFIX-PLAN-2026-10-10.md)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from datetime import date
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest
import yaml

from etf_cockpit.core import secure_update, session_log
from etf_cockpit.core.http_fetch import get_checked
from etf_cockpit.core.secure_update import (
    SIGNING_KEY_ENV,
    build_update_manifest,
    extract_verified_update,
    sign_update_manifest,
    verify_update_bundle,
)
from etf_cockpit.data import backup_restore
from etf_cockpit.data.backup_restore import (
    BackupError,
    commit_incremental_restore,
    commit_restore,
    create_backup,
    create_incremental_backup,
    validate_restore,
)
from etf_cockpit.data.bulk_cache import BulkCacheError, ContentAddressedCache, DownloadRequest, DownloadResponse
from etf_cockpit.data.esef_provider import EsefProviderUnavailable, FilingsXbrlOrgProvider
from etf_cockpit.data.oam_adapters import NetherlandsAfmOamAdapter, OAMUnavailable
from etf_cockpit.governance.release_certification import _signed_manifest_status
from etf_cockpit.governance.static_checks import MAX_TEXT_FILE_BYTES, run_static_execution_boundary_check
from etf_cockpit.security.policy import (
    SECRET_KEY_RE,
    SecurityPolicyError,
    build_security_report,
    load_security_policy,
    redact_secrets,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = b"a sufficiently long offline update key"


@pytest.fixture(autouse=True)
def _isolated_temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    temp_root = tmp_path / "system-temp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    monkeypatch.setenv("TEMP", str(temp_root))
    monkeypatch.setenv("TMP", str(temp_root))


# ---------------------------------------------------------------- redirects (P01-N006)


def _redirecting_opener(monkeypatch: pytest.MonkeyPatch, target: str, contacted: list[str]) -> None:
    class Opener:
        def open(self, request, timeout=None):
            contacted.append(request.full_url)
            if request.full_url == target:
                raise AssertionError("off-list target must never be contacted")
            headers = Message()
            headers["Location"] = target
            raise HTTPError(request.full_url, 302, "Found", headers, None)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_a, **_k: Opener())


def test_p01_n006(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = "https://evil.example/steal"
    contacted: list[str] = []
    _redirecting_opener(monkeypatch, target, contacted)

    with pytest.raises(ValueError, match="source_redirect_not_supported"):
        get_checked("https://www.afm.nl/x", allowed=lambda url: "afm.nl" in url, headers={}, timeout=1, max_bytes=10)

    adapter = NetherlandsAfmOamAdapter(cache_dir=tmp_path / "oam", endpoint="https://export.afm.nl/oam.csv", enabled=True, retries=0)
    with pytest.raises(OAMUnavailable):
        adapter._get("https://export.afm.nl/oam.csv")
    provider = FilingsXbrlOrgProvider(cache_dir=tmp_path / "esef")
    with pytest.raises(EsefProviderUnavailable):
        provider._get("https://filings.xbrl.org/api/filings")
    assert target not in contacted


# ---------------------------------------------------------------- bulk cache (P02-N003/4/14)


def test_p02_n003(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    source = tmp_path / "src.csv"
    manifests = set()
    for index, source_id in enumerate(("feed/a", "feed:a", "feed_a")):
        source.write_bytes(f"payload-{index}".encode())
        result = cache.store_local_file(source_id, source, licence="official")
        assert result.manifest.version == 1
        manifests.add(cache._manifest_path(source_id))
    assert len(manifests) == 3
    assert all(path.is_file() for path in manifests)
    assert cache._manifest_path("feed_a").name == "feed_a.json"  # already-safe names keep their path


def test_p02_n004(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    source = tmp_path / "official.csv"
    source.write_bytes(b"genuine bytes\n")
    first = cache.store_local_file("official", source, licence="official")
    object_path = tmp_path / first.manifest.object_path
    object_path.write_bytes(b"corrupted")

    again = cache.store_local_file("official-2", source, licence="official")

    assert hashlib.sha256(object_path.read_bytes()).hexdigest() == again.manifest.content_sha256
    assert object_path.read_bytes() == b"genuine bytes\n"


def test_p02_n014(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    request = DownloadRequest("short", "https://example.test/file", allowlisted_hosts=("example.test",))

    with pytest.raises(BulkCacheError, match="size mismatch"):
        cache.download(request, fetcher=lambda _r, _o: DownloadResponse(200, [b"abc"], total_size=20))

    assert not (cache.manifests / "short.json").exists()
    assert not [path for path in cache.objects.rglob("*") if path.is_file()]


# ---------------------------------------------------------------- backup / restore (P02-N009/12/13/15)


def _data_tree(root: Path, files: dict[str, bytes]) -> Path:
    data = root / "data"
    for name, payload in files.items():
        target = data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return data


def test_p02_n009(tmp_path: Path) -> None:
    data = _data_tree(tmp_path / "live", {"a.txt": b"A", "b.txt": b"B"})
    base = create_backup([data], tmp_path / "base.backup")
    (data / "a.txt").unlink()
    (data / "b.txt").write_bytes(b"B2")
    delta = create_incremental_backup([data], tmp_path / "delta.backup", base_manifest=base)
    assert json.loads(zipfile.ZipFile(delta.archive).read("manifest.json"))["deleted"] == ["data/a.txt"]

    destination = tmp_path / "restored"
    previews = [validate_restore(base.archive), validate_restore(delta.archive)]
    assert all(preview.valid for preview in previews), [preview.errors for preview in previews]
    result = commit_incremental_restore(previews, destination)

    assert result.ok is True, result
    assert not (destination / "data" / "a.txt").exists()
    assert (destination / "data" / "b.txt").read_bytes() == b"B2"


def test_p02_n012(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _data_tree(tmp_path / "live", {"a.txt": b"A" * 1000})
    manifest = create_backup([data], tmp_path / "ok.backup")
    assert validate_restore(manifest.archive).valid is True

    monkeypatch.setattr(backup_restore, "DEFAULT_MAX_ARCHIVE_MEMBERS", 0)
    reads: list[str] = []
    original = zipfile.ZipFile.read

    def tracking_read(self, name, *args, **kwargs):
        reads.append(str(name))
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", tracking_read)
    preview = validate_restore(manifest.archive)

    assert preview.valid is False
    assert any(error.startswith("archive_limits_exceeded") for error in preview.errors)
    assert reads == []
    destination = tmp_path / "dest"
    assert commit_restore(preview, destination).ok is False
    assert not destination.exists() or not any(path.is_file() for path in destination.rglob("*"))


def test_p02_n013(tmp_path: Path) -> None:
    root_a = _data_tree(tmp_path / "rootA", {"x": b"1"})
    root_b = _data_tree(tmp_path / "rootB", {"x": b"2"})

    with pytest.raises(BackupError, match="archive_name_collision:data/x"):
        create_backup([root_a, root_b], tmp_path / "collide.backup")


def test_p02_n015(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("private", encoding="utf-8")
    data = _data_tree(tmp_path / "live", {"inside.txt": b"ok"})
    links = ["data/link"]
    try:
        os.symlink(outside, data / "link", target_is_directory=True)
        os.symlink(outside / "sentinel.txt", data / "file_link.txt")
        links.append("data/file_link.txt")
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("symlinks are not permitted in this environment")
        # Windows without symlink rights: a directory junction exercises the same escape.
        subprocess.run(["cmd", "/c", "mklink", "/J", str(data / "link"), str(outside)], check=True, capture_output=True)

    manifest = create_backup([data], tmp_path / "links.backup")

    names = zipfile.ZipFile(manifest.archive).namelist()
    assert "data/inside.txt" in names
    assert not any("sentinel" in name or name.startswith("data/link") or name == "data/file_link.txt" for name in names)
    assert set(links) <= set(manifest.excluded)


# ---------------------------------------------------------------- export pack (P07-N015 / N020)


def _fake_stage(files_by_call: list[dict[str, str]], fail_on_call: int | None = None):
    calls = {"n": 0}

    def stage(export_dir: Path, *_args, **_kwargs) -> None:
        calls["n"] += 1
        export_dir.mkdir(parents=True, exist_ok=True)
        if fail_on_call == calls["n"]:
            (export_dir / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("stage failed")
        for name, text in files_by_call[calls["n"] - 1].items():
            (export_dir / name).write_text(text, encoding="utf-8")

    return stage


def _export(ep) -> Path:
    return ep.export_review_pack(None, None, None, [], None, as_of_date=date(2026, 10, 10))


def test_p07_n015(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.chatgpt_bridge import export_pack as ep

    monkeypatch.setattr(ep, "CHATGPT_EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(
        ep, "_stage_review_pack", _fake_stage([{"14_scoreboard.csv": "a", "manifest.json": "A"}, {"manifest.json": "B"}])
    )
    first = _export(ep)
    assert "14_scoreboard.csv" in zipfile.ZipFile(first).namelist()

    second = _export(ep)

    assert second == first
    assert sorted(zipfile.ZipFile(second).namelist()) == ["manifest.json"]
    assert not (second.with_suffix("") / "14_scoreboard.csv").exists()
    assert not list((tmp_path / "exports").glob("*.staging-*"))


def test_p07_n020(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.chatgpt_bridge import export_pack as ep

    monkeypatch.setattr(ep, "CHATGPT_EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(ep, "_stage_review_pack", _fake_stage([{"manifest.json": "good"}, {}], fail_on_call=2))
    zip_path = _export(ep)
    before = zip_path.read_bytes()

    with pytest.raises(RuntimeError, match="stage failed"):
        _export(ep)

    assert zip_path.read_bytes() == before
    assert (zip_path.with_suffix("") / "manifest.json").read_text(encoding="utf-8") == "good"
    assert not list((tmp_path / "exports").glob("*.staging-*"))


# ---------------------------------------------------------------- build_windows.bat (P08-N001/5/6)


def _bat() -> str:
    return (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8")


def test_p08_n001() -> None:
    script = _bat()
    data_copies = [line for line in script.splitlines() if re.search(r"(xcopy|copy)\b.*\bdata\\", line, re.IGNORECASE)]
    assert data_copies == []
    assert 'mkdir "%OUTDIR%\\data"' in script


def test_p08_n005() -> None:
    script = _bat()
    head, _, subroutine = script.partition(":copy_required\nrem")
    if not subroutine:  # CRLF checkout
        head, _, subroutine = script.partition(":copy_required\r\nrem")
    required = [line.strip() for line in head.splitlines() if re.match(r"\s*(xcopy|copy)\b", line, re.IGNORECASE)]
    # Raw copies are allowed only for the explicitly optional release notes (guarded by `if exist`).
    assert required == []
    for source in ("src", "configs", "scripts"):
        assert re.search(rf"call :copy_required {source} ", script)
    assert 'call :copy_required "%%f"' in script
    assert "|| exit /b 1" in script or "if errorlevel 1 exit /b 1" in subroutine
    assert "xcopy /e /i /y" in subroutine and "copy /y" in subroutine


def test_p08_n006() -> None:
    script = _bat()
    assert re.search(r'if /I "%ETF_COCKPIT_RELEASE_BUILD%"=="1" \(\s+set "LAUNCHER_REQ=requirements-release.txt"', script)
    assert "requirements-release-parsers.txt" in script
    assert "pip install -r %LAUNCHER_REQ%" in script
    assert "pip install -r %LAUNCHER_REQ_PARSERS%" in script
    assert "-m pip install -r requirements.txt" not in script  # the launcher no longer hard-codes the dev pins
    assert (ROOT / "requirements-release.txt").is_file() and (ROOT / "requirements-release-parsers.txt").is_file()


# ---------------------------------------------------------------- secure update (P08-N002, CHAT-P08-N007/N008)


def _bundle(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)


def test_p08_n002(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "update.zip"
    _bundle(archive, [("app.txt", b"payload" * 100)])
    manifest = build_update_manifest(archive)
    signature = sign_update_manifest(manifest, KEY, key_id="t")
    assert verify_update_bundle(archive, manifest, signature, KEY).ok is True

    def fail_read(self, *_args, **_kwargs):
        raise AssertionError("members must not be read")

    monkeypatch.setattr(zipfile.ZipFile, "read", fail_read)
    monkeypatch.setattr(secure_update, "MAX_ARCHIVE_BYTES", 10)
    oversized = verify_update_bundle(archive, manifest, signature, KEY)
    monkeypatch.setattr(secure_update, "MAX_ARCHIVE_BYTES", 1 << 30)
    monkeypatch.setattr(secure_update, "MAX_COMPRESSION_RATIO", 0.0001)
    ratio = verify_update_bundle(archive, manifest, signature, KEY)

    assert oversized.ok is False and oversized.status == "rejected"
    assert any("size limit" in error for error in oversized.errors)
    assert ratio.ok is False and ratio.status == "rejected"
    assert any("safety limits" in error for error in ratio.errors)


def test_chat_p08_n007(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "update.zip"
    _bundle(archive, [("app.txt", b"original")])
    manifest = build_update_manifest(archive)
    signature = sign_update_manifest(manifest, KEY, key_id="t")
    real_verify = secure_update.verify_update_bundle

    def verify_then_swap(*args, **kwargs):
        result = real_verify(*args, **kwargs)
        _bundle(archive, [("app.txt", b"swapped!")])  # the file changes after the verification
        return result

    monkeypatch.setattr(secure_update, "verify_update_bundle", verify_then_swap)
    destination = tmp_path / "installed"

    with pytest.raises(ValueError, match="changed after verification|hash mismatch"):
        extract_verified_update(archive, manifest, signature, KEY, destination)

    assert not list(tmp_path.rglob("app.txt"))


def test_chat_p08_n008() -> None:
    for name in (".", "./"):
        with pytest.raises(ValueError, match="unsafe update member"):
            secure_update._safe_member(name)


# ---------------------------------------------------------------- release certification (P08-N003)


def test_p08_n003(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = tmp_path / "artifacts" / "release" / "issue-0152"
    release.mkdir(parents=True)
    manifest_bytes = json.dumps({"git": {"head": "abc123"}}).encode()
    (release / "release-manifest.json").write_bytes(manifest_bytes)
    (release / "release-manifest.sig.json").write_text(json.dumps({"status": "signed"}), encoding="utf-8")

    monkeypatch.delenv(SIGNING_KEY_ENV, raising=False)
    status, reason = _signed_manifest_status(tmp_path, "abc123")
    assert status == "blocked" and "not cryptographically verified" in reason

    monkeypatch.setenv(SIGNING_KEY_ENV, KEY.decode())
    status, reason = _signed_manifest_status(tmp_path, "abc123")
    assert status == "blocked" and "not cryptographically verified" in reason

    signature = {
        "status": "signed",
        "payload_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "signature": hmac.new(KEY, manifest_bytes, hashlib.sha256).hexdigest(),
    }
    (release / "release-manifest.sig.json").write_text(json.dumps(signature), encoding="utf-8")
    assert _signed_manifest_status(tmp_path, "abc123")[0] == "passed"


# ---------------------------------------------------------------- security policy (CHAT-P08-N003/N004)


def _policy_root(tmp_path: Path, **network: object) -> Path:
    (tmp_path / "configs").mkdir(exist_ok=True)
    payload = yaml.safe_load((ROOT / "configs" / "security_policy.yaml").read_text(encoding="utf-8"))
    payload["network"].update(network)
    (tmp_path / "configs" / "security_policy.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    shutil.copy(ROOT / "configs" / "plugin_registry.yaml", tmp_path / "configs" / "plugin_registry.yaml")
    return tmp_path


@pytest.mark.parametrize(
    "network",
    [
        {"default_deny": False},
        {"http_api_exposed": True, "require_authentication_if_exposed": False},
        {"http_api_exposed": True, "require_csrf_if_exposed": False},
        {"default_deny": "false"},
        {"http_api_exposed": "false"},
        {"require_csrf_if_exposed": "no"},
    ],
)
def test_chat_p08_n003(tmp_path: Path, network: dict[str, object]) -> None:
    root = _policy_root(tmp_path, **network)
    if any(isinstance(value, str) for value in network.values()):
        with pytest.raises(SecurityPolicyError):
            load_security_policy(root / "configs" / "security_policy.yaml")
    report = build_security_report(root)
    assert report["status"] == "failed"
    assert report["failures"]


def test_chat_p08_n003_default_policy_is_strict_and_loads(tmp_path: Path) -> None:
    policy = load_security_policy(_policy_root(tmp_path) / "configs" / "security_policy.yaml")
    assert policy.default_deny is True and policy.http_api_exposed is False


def test_chat_p08_n004() -> None:
    keys = ["refresh_token", "private_key", "privateKey", "signing-key", "credential", "clientSecret", "accessToken", "Authorization", "id_token"]
    payload: dict[str, object] = {key: "v" for key in keys}
    payload["nested"] = [{"deep": {"refresh_token": "v", "name": "ok"}}]
    payload["name"] = "ok"

    redacted = redact_secrets(payload)

    assert all(redacted[key] == "***redacted***" for key in keys)
    assert redacted["nested"][0]["deep"] == {"refresh_token": "***redacted***", "name": "ok"}
    assert redacted["name"] == "ok"
    logged = session_log._redact(payload)
    assert all(logged[key] == "***redacted***" for key in keys)
    assert SECRET_KEY_RE is session_log.SECRET_KEY_RE  # one matcher for both redactors


# ---------------------------------------------------------------- static checks (CHAT-P08-N006)


def test_chat_p08_n006(tmp_path: Path) -> None:
    (tmp_path / "big.py").write_bytes(b"#" * (MAX_TEXT_FILE_BYTES + 1))

    report = run_static_execution_boundary_check(tmp_path)

    assert any(violation.code == "UNSCANNED_TOO_LARGE" and violation.path == "big.py" for violation in report.violations)


@pytest.mark.parametrize("failure", ["directory_deletion", "directory_replacement"])
def test_int_io_1_publication_failure_restores_both_artifacts(tmp_path, monkeypatch, failure) -> None:
    from etf_cockpit.chatgpt_bridge import export_pack as ep

    monkeypatch.setattr(ep, "CHATGPT_EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(ep, "_stage_review_pack", _fake_stage([
        {"manifest.json": "good", "old.txt": "retained"}, {"manifest.json": "new", "new.txt": "candidate"},
    ]))
    zip_path = _export(ep)
    export_dir = zip_path.with_suffix("")
    before_zip = zip_path.read_bytes()
    before_dir = {p.relative_to(export_dir): p.read_bytes() for p in export_dir.rglob("*") if p.is_file()}
    original_delete, original_replace = ep.shutil.rmtree, ep.os.replace

    def delete(path, *args, **kwargs):
        if Path(path) == export_dir:
            (export_dir / "old.txt").unlink()  # failure after a partial deletion
            raise OSError("directory deletion failed")
        return original_delete(path, *args, **kwargs)

    def replace(source, target):
        if Path(target) == export_dir and ".staging-" in Path(source).name and not Path(source).name.endswith(".backup"):
            raise OSError("directory replacement failed")
        return original_replace(source, target)

    if failure == "directory_deletion":
        monkeypatch.setattr(ep.shutil, "rmtree", delete)
    else:
        monkeypatch.setattr(ep.os, "replace", replace)
    with pytest.raises(OSError, match="directory (deletion|replacement) failed"):
        _export(ep)
    assert zip_path.read_bytes() == before_zip
    assert {p.relative_to(export_dir): p.read_bytes() for p in export_dir.rglob("*") if p.is_file()} == before_dir


def test_int_io_2_three_archive_chain_preserves_deletions(tmp_path) -> None:
    data = _data_tree(tmp_path / "live", {"a.txt": b"A", "b.txt": b"B"})
    base = create_backup([data], tmp_path / "base.backup")
    (data / "b.txt").write_bytes(b"B2")
    delta_one = create_incremental_backup([data], tmp_path / "delta-one.backup", base)
    assert set(delta_one.checksums) == {"data/b.txt"}
    assert delta_one.inventory_checksums == {**base.checksums, **delta_one.checksums}
    with zipfile.ZipFile(delta_one.archive) as archive:
        assert set(archive.namelist()) == {"data/b.txt", "manifest.json"}
        assert set(json.loads(archive.read("manifest.json"))["checksums"]) == {"data/b.txt"}
    (data / "a.txt").unlink()
    delta_two = create_incremental_backup([data], tmp_path / "delta-two.backup", delta_one)
    with zipfile.ZipFile(delta_two.archive) as archive:
        assert json.loads(archive.read("manifest.json"))["deleted"] == ["data/a.txt"]
    assert set(delta_two.inventory_checksums) == {"data/b.txt"}
    destination = tmp_path / "restored"
    result = commit_incremental_restore([validate_restore(item.archive) for item in (base, delta_one, delta_two)], destination)
    assert result.ok, result.error
    assert not (destination / "data" / "a.txt").exists()
    assert (destination / "data" / "b.txt").read_bytes() == b"B2"


@pytest.mark.parametrize("failure", ["deletion", "replacement"])
def test_int_io_3_failed_restore_preserves_every_original_file(tmp_path, monkeypatch, failure) -> None:
    data = _data_tree(tmp_path / "live", {"a.txt": b"A", "b.txt": b"B", "c.txt": b"C"})
    base = create_backup([data], tmp_path / "base.backup")
    (data / "a.txt").unlink()
    (data / "b.txt").unlink()
    (data / "c.txt").write_bytes(b"changed")
    (data / "new.txt").write_bytes(b"new")
    delta = create_incremental_backup([data], tmp_path / "delta.backup", base)
    destination = tmp_path / "destination"
    restored_data = _data_tree(destination, {"a.txt": b"original-a", "b.txt": b"original-b", "c.txt": b"original-c", "extra.txt": b"extra"})
    backup_restore.atomic_write_group([
        backup_restore.AtomicWriteRequest(restored_data / "c.txt", b"original-c", lambda _path: None),
    ])
    before = {p.name: p.read_bytes() for p in restored_data.iterdir() if p.is_file()}
    original_unlink = Path.unlink
    original_group = backup_restore.atomic_write_group
    failed = False

    def unlink(path, *args, **kwargs):
        nonlocal failed
        if path == restored_data / "b.txt" and not failed:
            failed = True
            raise OSError("injected deletion failure")
        return original_unlink(path, *args, **kwargs)

    def group(requests, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected replacement failure")
        return original_group(requests, **kwargs)

    if failure == "deletion":
        monkeypatch.setattr(Path, "unlink", unlink)
    else:
        monkeypatch.setattr(backup_restore, "atomic_write_group", group)
    result = commit_incremental_restore([validate_restore(base.archive), validate_restore(delta.archive)], destination)
    assert not result.ok and f"injected {failure} failure" in result.error
    assert {p.name: p.read_bytes() for p in restored_data.iterdir() if p.is_file()} == before


@pytest.mark.parametrize("link_kind", ["symlink", "junction", "reparse"])
def test_int_io_4_direct_linked_roots_are_excluded_before_traversal(tmp_path, monkeypatch, link_kind) -> None:
    source = _data_tree(tmp_path / "external", {"sentinel.txt": b"private"})
    if link_kind == "symlink":
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == source or original(p))
    elif link_kind == "junction":
        original = os.path.isjunction
        monkeypatch.setattr(os.path, "isjunction", lambda p: Path(p) == source or original(p))
    else:
        original = backup_restore._is_reparse_point
        monkeypatch.setattr(backup_restore, "_is_reparse_point", lambda p: p == source or original(p))
    manifest = create_backup([source], tmp_path / "linked.backup")
    assert manifest.checksums == {} and manifest.excluded == ("data",)
    with zipfile.ZipFile(manifest.archive) as archive:
        assert archive.namelist() == ["manifest.json"]


def test_int_io_4_direct_directory_link_does_not_archive_target(tmp_path) -> None:
    outside = _data_tree(tmp_path / "external", {"sentinel.txt": b"private"})
    link = tmp_path / "data"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    manifest = create_backup([link], tmp_path / "direct-link.backup")
    assert manifest.checksums == {} and manifest.excluded == ("data",)
    with zipfile.ZipFile(manifest.archive) as archive:
        assert archive.namelist() == ["manifest.json"]


def test_int_io_5_transformed_identifiers_do_not_share_manifests_or_generations(tmp_path) -> None:
    from etf_cockpit.data.bulk_cache import _safe_name

    raw = "feed/a"
    constructed = _safe_name(raw, "source_id")
    old_constructed = "feed_a-" + hashlib.sha256(raw.encode()).hexdigest()[:12]
    cache = ContentAddressedCache(tmp_path)
    source = tmp_path / "source.bin"
    paths = []
    for identifier in (raw, constructed, old_constructed):
        source.write_bytes(identifier.encode())
        first = cache.store_local_file(identifier, source)
        second = cache.store_local_file(identifier, source)
        assert first.manifest.version == 1 and second.manifest.version == 2
        assert first.manifest.source_id == identifier
        paths.append(cache._manifest_path(identifier))
        staged = cache.stage_generation(identifier, identifier.encode(), source_sha256=first.manifest.content_sha256)
        promoted = cache.promote_generation(staged)
        assert promoted.dataset_id == identifier
        assert Path(promoted.relative_path).parent.name == _safe_name(identifier, "dataset_id")
        assert (tmp_path / promoted.relative_path).read_bytes() == identifier.encode()
    assert len(set(paths)) == 3
    assert all(path.is_file() for path in paths)


@pytest.mark.parametrize("field", ["payload_sha256", "signature"])
@pytest.mark.parametrize("invalid", ["\u00e9", "g" * 64, "0" * 63, None, 1, []])
def test_int_io_6_malformed_detached_signature_blocks_certification(tmp_path, monkeypatch, field, invalid) -> None:
    release = tmp_path / "artifacts" / "release" / "issue-0152"
    release.mkdir(parents=True)
    payload = json.dumps({"git": {"head": "abc123"}}).encode()
    (release / "release-manifest.json").write_bytes(payload)
    signature = {"status": "signed", "payload_sha256": hashlib.sha256(payload).hexdigest(),
                 "signature": hmac.new(KEY, payload, hashlib.sha256).hexdigest()}
    signature[field] = invalid
    (release / "release-manifest.sig.json").write_text(json.dumps(signature), encoding="utf-8")
    monkeypatch.setenv(SIGNING_KEY_ENV, KEY.decode())
    assert secure_update.detached_signature_errors(payload, signature, KEY)
    status, reason = _signed_manifest_status(tmp_path, "abc123")
    assert status == "blocked" and "not cryptographically verified" in reason
