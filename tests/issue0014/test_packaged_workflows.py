from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import release_gate
from tests.issue0014._support import (
    copy_repository_runtime,
    isolated_environment,
    run_offline_smoke,
)


def test_real_sdist_runs_packaged_offline_smoke_from_artifact_root(tmp_path: Path) -> None:
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip(
            "configured sdist backend is absent from preflight; the mandatory package gate "
            "installs release tooling and executes the same package command"
        )
    package_source = copy_repository_runtime(tmp_path / "package-source", packaging=True)
    artifact_root = package_source / "build" / "python-dist"
    artifact_root.mkdir(parents=True)
    build_expression = (
        "from setuptools.build_meta import build_sdist; "
        f"print(build_sdist({str(artifact_root)!r}))"
    )
    built = subprocess.run(
        [sys.executable, "-c", build_expression],
        cwd=package_source,
        env=isolated_environment(package_source),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr

    package = release_gate.prepare_package_artifact(
        package_source,
        {"artifact_roots": ["build/python-dist"]},
        tmp_path / "extract",
        platform_name="posix",
    )
    assert package is not None and package.layout == "sdist"
    assert release_gate.source_package_parity(package_source, package).status == "passed"

    smoke = run_offline_smoke(package.root, package.smoke_script)

    assert "smoke_ok mode=offline" in smoke.stdout
    assert str(package.root) in smoke.stdout or "127.0.0.1" in smoke.stdout


def test_posix_package_command_uses_the_configured_isolated_builder(tmp_path: Path) -> None:
    assert release_gate.package_command(tmp_path, platform_name="posix") == (
        sys.executable,
        "-m",
        "build",
        "--outdir",
        "build/python-dist",
    )


def test_packaged_smoke_fails_closed_when_artifact_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="artifact is missing"):
        run_offline_smoke(tmp_path, None)


def test_packaged_smoke_fails_closed_when_artifact_is_not_runnable(tmp_path: Path) -> None:
    root = tmp_path / "broken-package"
    script = root / "scripts" / "smoke_app.py"
    script.parent.mkdir(parents=True)
    script.write_text("raise SystemExit(7)\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"not runnable \(7\)"):
        run_offline_smoke(root, script, timeout=10)
