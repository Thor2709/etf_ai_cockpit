from __future__ import annotations

import json
from pathlib import Path

from scripts import release_gate


def test_source_manifest_normalises_text_line_endings_but_not_binary(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_bytes(b"one\r\ntwo\rthree\n")
    (tmp_path / "blob.bin").write_bytes(b"one\r\ntwo")

    manifest = release_gate.build_source_manifest(tmp_path)
    by_path = {str(row["path"]): row for row in manifest["files"]}

    assert by_path["notes.md"]["bytes"] == len(b"one\ntwo\nthree\n")
    assert by_path["notes.md"]["sha256"] == release_gate.sha256_bytes(b"one\ntwo\nthree\n")
    assert by_path["blob.bin"]["sha256"] == release_gate.sha256_bytes(b"one\r\ntwo")


def test_release_signature_detects_manifest_tampering() -> None:
    payload = b'{"release":"one"}\n'
    key = b"a sufficiently long test signing key"
    signature = release_gate.sign_manifest(payload, key, key_id="test")

    assert release_gate.verify_manifest_signature(payload, signature, key)
    assert not release_gate.verify_manifest_signature(payload + b"tampered", signature, key)


def test_run_gate_writes_machine_readable_failure_evidence(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "release_policy.yaml").write_text(
        "schema_version: '1.0'\npython_version: '3.12.10'\ndependency_lock: requirements-release.txt\nartifact_roots: [build]\nsigning_key_env: TEST_RELEASE_KEY\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    monkeypatch.setenv("TEST_RELEASE_KEY", "a sufficiently long test signing key")
    monkeypatch.setattr(release_gate, "git_snapshot", lambda _root: {"branch": "test", "head": "abc", "origin_main": "abc", "dirty": False})

    result = release_gate.run_gate(
        tmp_path,
        output_dir=tmp_path / "evidence",
        skip_tests=True,
        skip_package=True,
        skip_smoke=True,
    )

    assert result.exit_code == 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["failures"] == []
    assert (result.output_dir / "sbom.cdx.json").exists()
    signature = json.loads((result.output_dir / "release-manifest.sig.json").read_text(encoding="utf-8"))
    assert signature["status"] == "signed"
    assert release_gate.verify_manifest_signature(
        result.manifest_path.read_bytes(), signature, b"a sufficiently long test signing key"
    )


def test_dry_run_lists_full_release_contract(tmp_path: Path, capsys) -> None:
    assert release_gate.main(["--root", str(tmp_path), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert any("pytest" in command for command in payload["commands"])
    assert any("SBOM" in command for command in payload["commands"])
    assert any("HMAC-SHA256" in command for command in payload["commands"])
