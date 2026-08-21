from __future__ import annotations

import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import release_gate


def test_full_suite_timeout_is_scoped_to_the_full_release_test_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[int] = []

    def completed(*_args, **kwargs):
        observed.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(release_gate.subprocess, "run", completed)
    output = tmp_path / "evidence"
    output.mkdir()

    release_gate.run_command(tmp_path, output, "full_tests", ("pytest",))
    release_gate.run_command(tmp_path, output, "package_build", ("build",))

    assert observed == [2400, 1800]


def _source_fixture(root: Path) -> None:
    (root / "src" / "etf_cockpit").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "scripts").mkdir()
    (root / "src" / "etf_cockpit" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "configs" / "sample.yaml").write_text("enabled: true\n", encoding="utf-8")
    (root / "scripts" / "smoke_app.py").write_text("raise SystemExit(0)\n", encoding="utf-8")


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


def test_sbom_records_source_and_packaged_artifact_evidence(tmp_path: Path) -> None:
    source = release_gate.build_source_manifest(tmp_path)
    artifacts = {"manifest_sha256": "artifact-manifest", "files": [{"path": "app.exe"}]}
    sbom = release_gate.build_sbom(tmp_path, source, {"dependency_lock": "missing.txt"}, artifact_manifest=artifacts)

    app = next(component for component in sbom["components"] if component["bom-ref"] == "etf-ai-cockpit")
    properties = app["properties"]
    values = {str(row["name"]): str(row["value"]) for row in properties}
    assert values["source-manifest-sha256"] == str(source["manifest_sha256"])
    assert values["artifact-manifest-sha256"] == "artifact-manifest"
    assert values["artifact-file-count"] == "1"


def test_run_gate_writes_machine_readable_failure_evidence(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "release_policy.yaml").write_text(
        "schema_version: '1.0'\npython_version: '3.12.10'\ndependency_lock: requirements-release.txt\nartifact_roots: [build]\nsigning_key_env: TEST_RELEASE_KEY\n",
        encoding="utf-8",
    )
    locked_versions = {
        "exchange-calendars": "4.13.2",
        "flet": "0.85.3",
        "hypothesis": "6.156.6",
        "mypy": "1.20.2",
        "pytest": "9.1.1",
        "ruff": "0.15.20",
    }
    (tmp_path / "requirements-release.txt").write_text(
        "".join(f"{name}=={version}\n" for name, version in locked_versions.items()),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_RELEASE_KEY", "a sufficiently long test signing key")
    monkeypatch.setattr(release_gate, "git_snapshot", lambda _root: {"branch": "test", "head": "abc", "origin_main": "abc", "dirty": False})

    def installed_version(name: str) -> str:
        try:
            return locked_versions[name]
        except KeyError as exc:
            raise release_gate.importlib.metadata.PackageNotFoundError(name) from exc

    monkeypatch.setattr(release_gate.importlib.metadata, "version", installed_version)

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
    assert len(manifest["environment"]["fingerprint_sha256"]) == 64
    assert manifest["environment"]["retry"]["automatic_test_retries"] == 0
    assert manifest["evidence_paths"]["output_dir"] == str(result.output_dir)
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


def test_package_commands_cover_windows_and_linux_outputs() -> None:
    windows = release_gate.package_command(Path("."), platform_name="nt")
    linux = release_gate.package_command(Path("."), platform_name="posix")

    assert windows == ("cmd", "/c", "scripts\\build_windows.bat")
    assert linux[-3:] == ("build", "--outdir", "build/python-dist")


def test_windows_portable_parity_matches_real_build_layout(tmp_path: Path) -> None:
    _source_fixture(tmp_path)
    package = tmp_path / "build" / "portable"
    (package / "app").mkdir(parents=True)
    import shutil
    shutil.copytree(tmp_path / "src", package / "app" / "src")
    shutil.copytree(tmp_path / "configs", package / "configs")
    shutil.copytree(tmp_path / "scripts", package / "scripts")
    (tmp_path / "build" / "portable_outdir.txt").write_text("build/portable\n", encoding="utf-8")
    prepared = release_gate.prepare_package_artifact(
        tmp_path, {"artifact_roots": ["build"]}, tmp_path / "extract", platform_name="nt"
    )
    assert prepared is not None and prepared.layout == "windows-portable"
    assert release_gate.source_package_parity(tmp_path, prepared).status == "passed"
    (package / "app" / "src" / "etf_cockpit" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
    failure = release_gate.source_package_parity(tmp_path, prepared)
    assert failure.status == "failed"
    assert "src/etf_cockpit/sample.py" in failure.failure


def test_sdist_is_safely_extracted_runnable_and_parity_checked(tmp_path: Path) -> None:
    _source_fixture(tmp_path)
    staging = tmp_path / "staging" / "etf_ai_cockpit-1.0"
    import shutil
    shutil.copytree(tmp_path / "src", staging / "src")
    shutil.copytree(tmp_path / "configs", staging / "configs")
    shutil.copytree(tmp_path / "scripts", staging / "scripts")
    build = tmp_path / "build"
    build.mkdir()
    archive = build / "etf_ai_cockpit-1.0.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(staging, arcname=staging.name)
    prepared = release_gate.prepare_package_artifact(
        tmp_path, {"artifact_roots": ["build"]}, tmp_path / "extract", platform_name="posix"
    )
    assert prepared is not None and prepared.layout == "sdist"
    assert prepared.smoke_script is not None and prepared.smoke_script.is_file()
    assert release_gate.source_package_parity(tmp_path, prepared).status == "passed"
    (prepared.root / "configs" / "sample.yaml").unlink()
    assert release_gate.source_package_parity(tmp_path, prepared).status == "failed"


def test_wheel_without_runtime_configs_fails_truthfully(tmp_path: Path) -> None:
    _source_fixture(tmp_path)
    build = tmp_path / "build"
    build.mkdir()
    wheel = build / "etf_ai_cockpit-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as handle:
        handle.write(
            tmp_path / "src" / "etf_cockpit" / "sample.py",
            "etf_cockpit/sample.py",
        )
    prepared = release_gate.prepare_package_artifact(
        tmp_path, {"artifact_roots": ["build"]}, tmp_path / "extract", platform_name="posix"
    )
    assert prepared is not None and prepared.layout == "wheel"
    assert prepared.smoke_script is None
    result = release_gate.source_package_parity(tmp_path, prepared)
    assert result.status == "failed"
    assert "configs->configs missing" in result.failure


def test_archive_extraction_rejects_path_escape(tmp_path: Path) -> None:
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as handle:
        handle.writestr("../escape.py", "bad")
    with pytest.raises(ValueError, match="escapes extraction root"):
        release_gate._safe_extract_archive(wheel, tmp_path / "extract")


@pytest.mark.parametrize(
    ("member_name", "member_type", "link_name"),
    [
        ("../escape.py", tarfile.REGTYPE, ""),
        ("symbolic-link.py", tarfile.SYMTYPE, "target.py"),
        ("hard-link.py", tarfile.LNKTYPE, "target.py"),
    ],
)
def test_tar_archive_extraction_rejects_escape_and_links(
    tmp_path: Path, member_name: str, member_type: bytes, link_name: str
) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    payload = b"unsafe"
    member = tarfile.TarInfo(member_name)
    member.type = member_type
    member.linkname = link_name
    member.size = len(payload) if member_type == tarfile.REGTYPE else 0
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.addfile(member, io.BytesIO(payload) if member.size else None)

    with pytest.raises(ValueError, match="unsafe archive member"):
        release_gate._safe_extract_archive(archive_path, tmp_path / "extract")


def test_dependency_snapshot_accepts_exact_parser_lock(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    (tmp_path / "requirements-release-parsers.txt").write_text("defusedxml==0.7.1\n", encoding="utf-8")
    policy = {
        "dependency_lock": "requirements-release.txt",
        "parser_dependency_lock": "requirements-release-parsers.txt",
    }
    versions = {"pytest": "9.1.1", "defusedxml": "0.7.1"}
    monkeypatch.setattr(release_gate.importlib.metadata, "version", versions.__getitem__)

    snapshot = release_gate.dependency_snapshot(tmp_path, policy)

    assert [row["path"] for row in snapshot["lock_files"]] == [
        "requirements-release.txt",
        "requirements-release-parsers.txt",
    ]
    assert snapshot["missing"] == []
    assert snapshot["mismatched"] == []
    assert snapshot["profiles"]["release"]["packages"] == ["pytest"]
    assert snapshot["profiles"]["parsers"] == {
        "required": True,
        "status": "required",
        "lock_path": "requirements-release-parsers.txt",
        "packages": ["defusedxml"],
    }


def test_dependency_snapshot_reports_optional_parser_tier_unavailable(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    monkeypatch.setattr(release_gate.importlib.metadata, "version", lambda _name: "9.1.1")

    snapshot = release_gate.dependency_snapshot(tmp_path, {"dependency_lock": "requirements-release.txt"})

    assert snapshot["profiles"]["parsers"] == {
        "required": False,
        "status": "unavailable",
        "lock_path": None,
        "packages": [],
    }


def test_environment_check_fails_when_named_tooling_is_absent_without_parser_lock(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    monkeypatch.setattr(release_gate.platform, "python_version", lambda: "3.12.10")
    monkeypatch.setattr(release_gate.importlib.metadata, "version", lambda _name: "9.1.1")
    monkeypatch.setattr(release_gate, "git_snapshot", lambda _root: {"dirty": False})

    check = release_gate.environment_check(
        tmp_path,
        {
            "python_version": "3.12.10",
            "dependency_lock": "requirements-release.txt",
        },
        allow_dirty=False,
    )

    assert check.status == "failed"
    assert "required tooling absent from lock profile" in check.failure
    assert "flet" in check.failure


def test_environment_verification_emits_structured_failure_for_missing_lock(
    tmp_path: Path, capsys
) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "release_policy.yaml").write_text(
        "python_version: '3.12.10'\ndependency_lock: missing.txt\n",
        encoding="utf-8",
    )

    exit_code = release_gate.main(["--root", str(tmp_path), "--verify-environment"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["check"]["status"] == "failed"
    assert payload["check"]["exit_code"] == 2
    assert "dependency lock is missing" in payload["check"]["failure"]
    assert payload["environment"] is None


def test_parallel_pilot_is_report_only_when_xdist_is_unavailable(monkeypatch) -> None:
    def missing(_name: str) -> str:
        raise release_gate.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(release_gate.importlib.metadata, "version", missing)

    evidence = release_gate.parallel_pilot_evidence()

    assert evidence["status"] == "unavailable"
    assert evidence["mode"] == "report_only"
    assert evidence["authority"] == "serial"
    assert evidence["workers"] == 4
    assert evidence["collection_parity"] == {
        "required": True,
        "comparison": "ordered_nodeids",
        "status": "not_run",
    }
    assert evidence["schema_version"] == "pytest-parallel-pilot.v2"
    assert "--collect-only" in evidence["commands"]["candidate_safe_collection"]
    assert "-n 4 --dist loadgroup" in evidence["commands"]["candidate_safe_execution"]
    assert evidence["serial_groups"] == [
        "concurrency",
        "environment",
        "flet",
        "package",
        "ports",
        "sqlite",
    ]


def test_git_snapshot_ignores_only_generated_release_evidence(monkeypatch) -> None:
    values = {
        ("status", "--porcelain", "--untracked-files=all"): "?? artifacts/release/latest/release-report.md\n M configs/release_policy.yaml\n",
        ("branch", "--show-current"): "feature",
        ("rev-parse", "HEAD"): "head",
        ("rev-parse", "origin/main"): "main",
    }
    monkeypatch.setattr(release_gate, "_git", lambda _root, *args: values.get(args, ""))

    snapshot = release_gate.git_snapshot(Path("."))

    assert snapshot["dirty"] is True
    assert snapshot["dirty_paths"] == [" M configs/release_policy.yaml"]


def test_release_workflow_is_matrixed_isolated_and_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release-gate.yml").read_text(encoding="utf-8")
    trigger = workflow.split("permissions:", maxsplit=1)[0]

    assert "\n  pull_request:\n" in trigger
    assert "\n  push:" not in trigger
    assert "windows-latest" in workflow
    assert "ubuntu-latest" in workflow
    assert "fail-fast: false" in workflow
    assert "timeout-minutes: 50" in workflow
    assert "Configure isolated user profile" in workflow
    assert "Pin reviewed canonical generation base" in workflow
    assert "PR_BASE_SHA: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || '' }}" in workflow
    assert "github.event.pull_request.base.ref || 'main'" in workflow
    assert "git update-ref refs/remotes/origin/main \"$REVIEWED_BASE_SHA\"" in workflow
    assert 'test "$(git rev-parse origin/main)" = "$REVIEWED_BASE_SHA"' in workflow
    assert "requirements-release-parsers.txt" in workflow
    assert "ETF_COCKPIT_RELEASE_BUILD: \"1\"" in workflow
    assert "secrets.RELEASE_SIGNING_KEY" not in workflow
    assert "github.event_name == 'pull_request' && needs.classifier.outputs.package_gate_required == 'true'" in workflow
    assert "arguments=(--root . --output \"$output\" --allow-unsigned)" in workflow
    assert "repository_dispatch:" in trigger
    assert "workflow_dispatch:" not in trigger
    assert "parallel-pilot-drift" in trigger
    assert "parallel-pilot-full" in trigger
    assert "name: release-gate-${{ github.sha }}-${{ matrix.platform }}" in workflow
    assert "contents: read" in workflow
    assert "issues: write" not in workflow
    assert "releases: write" not in workflow
