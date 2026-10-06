"""Bug hunt slice S12 reproduction tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts import generate_completion_documents, release_gate
from scripts.issue_registry_core import PROGRAMME_ROOT


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-01: Short signing key passes signature check then crashes release gate with unhandled ValueError",
)
def test_s12_01_short_signing_key_fails_gate_gracefully(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv("TEST_RELEASE_KEY", "short")
    monkeypatch.setattr(
        release_gate,
        "git_snapshot",
        lambda _root: {"branch": "test", "head": "abc", "origin_main": "abc", "dirty": False},
    )

    def installed_version(name: str) -> str:
        try:
            return locked_versions[name]
        except KeyError as exc:
            raise release_gate.importlib.metadata.PackageNotFoundError(name) from exc

    monkeypatch.setattr(release_gate.importlib.metadata, "version", installed_version)

    output = tmp_path / "evidence"
    try:
        result = release_gate.run_gate(
            tmp_path,
            output_dir=output,
            skip_tests=True,
            skip_package=True,
            skip_smoke=True,
        )
    except ValueError as exc:
        raise AssertionError(f"run_gate crashed with unhandled ValueError instead of failing gate check: {exc}") from exc

    assert result.exit_code == 1
    assert any(check.name == "signature" and check.status == "failed" for check in result.checks)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-02: --check stale detection misses newly generated files because candidate paths are evaluated before generation",
)
def test_s12_02_check_detects_missing_file_as_stale(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shutil.copytree(repo_root / "issues", tmp_path / "issues")
    shutil.copytree(repo_root / "docs", tmp_path / "docs")
    shutil.copytree(repo_root / "src", tmp_path / "src")
    shutil.copyfile(repo_root / "README.md", tmp_path / "README.md")
    shutil.copyfile(repo_root / "CHANGELOG.md", tmp_path / "CHANGELOG.md")

    roadmap_file = tmp_path / PROGRAMME_ROOT / "programme" / "roadmap.md"
    assert roadmap_file.is_file()
    roadmap_file.unlink()
    assert not roadmap_file.exists()

    exit_code = generate_completion_documents.main(["--root", str(tmp_path), "--check"])
    assert exit_code == 1
    assert not roadmap_file.exists()
