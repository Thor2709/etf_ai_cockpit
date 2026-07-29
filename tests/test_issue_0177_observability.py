from __future__ import annotations

import json
from pathlib import Path

from scripts import release_gate, validate_app


def test_release_pytest_contract_writes_junit_and_slowest_phase_durations(tmp_path: Path) -> None:
    commands = release_gate._planned_commands(tmp_path)
    pytest_command = next(command for command in commands if "pytest" in command)

    assert "--durations=100" in pytest_command
    assert "--durations-min=0.25" in pytest_command
    assert "--junitxml=<output>/junit-full.xml" in pytest_command


def test_changed_validation_pytest_uses_supplied_report_root(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    report_dir = tmp_path / "isolated-evidence" / "latest"
    monkeypatch.setattr(validate_app, "_changed_test_paths", lambda _root: ["tests/test_sample.py"])

    check = next(
        item
        for item in validate_app._checks_for_mode(
            source_root,
            "changed",
            {},
            report_dir=report_dir,
        )
        if item.name == "changed_tests"
    )

    assert "--durations=100" in check.command
    assert "--durations-min=0.25" in check.command
    assert f"--junitxml={report_dir / 'junit-affected.xml'}" in check.command


def test_environment_verification_fails_before_tests_for_wrong_python(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "release_policy.yaml").write_text(
        "python_version: '0.0.0'\ndependency_lock: requirements-release.txt\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    monkeypatch.setattr(release_gate, "git_snapshot", lambda _root: {"dirty": False})
    monkeypatch.setattr(
        release_gate,
        "dependency_snapshot",
        lambda _root, _policy: {
            "lock_path": "requirements-release.txt",
            "lock_files": [],
            "installed": {"pytest": "9.1.1"},
            "missing": [],
            "mismatched": [],
        },
    )

    exit_code = release_gate.main(["--root", str(tmp_path), "--verify-environment"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["check"]["name"] == "pinned_environment"
    assert "does not match pinned" in payload["check"]["failure"]


def test_release_workflow_verifies_environment_before_protected_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release-gate.yml").read_text(encoding="utf-8")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    assert workflow.index("Verify protected environment") < workflow.index("Run protected release gate")
    assert "python scripts/release_gate.py --root . --verify-environment" in workflow
    assert "artifacts/release/**" in gitignore


def test_validation_environment_fingerprint_and_junit_path_are_recorded(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    junit = tmp_path / "isolated-evidence" / "latest" / "junit-affected.xml"
    junit.parent.mkdir(parents=True)
    junit.write_text("<testsuites />\n", encoding="utf-8")

    environment = validate_app._environment(source_root)
    paths = validate_app._existing_log_paths(source_root, report_dir=junit.parent)

    assert len(str(environment["fingerprint_sha256"])) == 64
    assert paths == [str(junit.resolve())]


def test_release_environment_evidence_keeps_parallel_pilot_report_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        release_gate,
        "dependency_snapshot",
        lambda _root, _policy: {"lock_files": [], "installed": {}},
    )
    monkeypatch.setattr(
        release_gate,
        "parallel_pilot_evidence",
        lambda: {"mode": "report_only", "authority": "serial", "workers": 4},
    )

    environment = release_gate.environment_evidence(tmp_path, {})

    assert environment["parallel_pilot"] == {
        "mode": "report_only",
        "authority": "serial",
        "workers": 4,
    }
