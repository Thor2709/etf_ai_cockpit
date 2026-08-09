from __future__ import annotations

import json
from pathlib import Path
import shutil

from scripts import release_gate


def _portable_fixture(root: Path) -> None:
    (root / "src" / "etf_cockpit").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "scripts").mkdir()
    (root / "src" / "etf_cockpit" / "sample.py").write_text("EXECUTION_ALLOWED = False\n", encoding="utf-8")
    (root / "configs" / "release_policy.yaml").write_text("execution_allowed: false\n", encoding="utf-8")
    (root / "scripts" / "smoke_app.py").write_text("# offline package smoke route\n", encoding="utf-8")
    portable = root / "build" / "portable"
    (portable / "app").mkdir(parents=True)
    shutil.copytree(root / "src", portable / "app" / "src")
    shutil.copytree(root / "configs", portable / "configs")
    shutil.copytree(root / "scripts", portable / "scripts")
    (root / "build" / "portable_outdir.txt").write_text("build/portable\n", encoding="utf-8")


def test_packaged_offline_journey_requires_parity_and_packaged_smoke_route(tmp_path: Path) -> None:
    _portable_fixture(tmp_path)
    package = release_gate.prepare_package_artifact(
        tmp_path,
        {"artifact_roots": ["build"]},
        tmp_path / "extract",
        platform_name="nt",
    )

    assert package is not None
    assert package.layout == "windows-portable"
    assert package.smoke_script == package.root / "scripts" / "smoke_app.py"
    assert release_gate.source_package_parity(tmp_path, package).status == "passed"
    assert "offline" in "python scripts/smoke_app.py --mode offline"


def test_release_gate_dry_run_documents_package_and_offline_smoke_contract(
    tmp_path: Path, capsys
) -> None:
    assert release_gate.main(["--root", str(tmp_path), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert any("build" in command.lower() for command in payload["commands"])
    assert any("smoke_app.py --mode offline" in command for command in payload["commands"])
