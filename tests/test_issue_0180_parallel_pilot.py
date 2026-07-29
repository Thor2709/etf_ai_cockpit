from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import profile_parallel_pytest


def test_profile_records_repeated_serial_parallel_parity_and_timings(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "requirements-release.txt").write_text("build==1.3.0\n", encoding="utf-8")
    def completed(_root: Path, command: list[str]):
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "tests/test_one.py::test_ok\n", ""), 6.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        Path(junit_arg.partition("=")[2]).write_text(
            '<testsuite><testcase classname="tests.test_one" name="test_ok"/></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 4.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    report = profile_parallel_pytest.profile(root, tmp_path / "evidence", 2)

    assert report["status"] == "passed"
    assert report["mode"] == "report_only"
    assert report["authority"] == "serial_release_gate"
    assert report["workers"] == 4
    assert report["repetitions"] == 2
    assert report["collection_parity"] is True
    assert report["result_parity"] is True
    assert report["collection_exit_codes"] == {"serial": [0, 0], "parallel": [0, 0]}
    assert report["timings"]["serial"]["p50_seconds"] == 4.0
    assert report["timings"]["parallel"]["p95_seconds"] == 4.0
    assert len(report["cache"]["key_sha256"]) == 64
    assert (tmp_path / "evidence" / "collection-serial-1.stdout.log").is_file()
    assert (tmp_path / "evidence" / "tests-parallel-2.stderr.log").is_file()


def test_collection_failure_makes_report_divergent(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    calls = 0

    def completed(_root: Path, command: list[str]):
        nonlocal calls
        calls += 1
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 2 if calls == 1 else 0, "", "collection failed"), 1.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        Path(junit_arg.partition("=")[2]).write_text(
            '<testsuite><testcase classname="tests.test_one" name="test_ok"/></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 1.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    report = profile_parallel_pytest.profile(root, tmp_path / "evidence", 2)

    assert report["status"] == "divergent"
    assert report["collection_exit_codes"]["serial"] == [2, 0]
    assert (
        tmp_path / "evidence" / "collection-serial-1.stderr.log"
    ).read_text(encoding="utf-8") == "collection failed"


def test_main_returns_nonzero_for_divergence_and_writes_json(tmp_path: Path, monkeypatch) -> None:
    report = {"status": "divergent", "mode": "report_only"}
    monkeypatch.setattr(profile_parallel_pytest, "profile", lambda *_args: report)
    output = tmp_path / "evidence"

    assert profile_parallel_pytest.main(["--root", str(tmp_path), "--output", str(output)]) == 1
    assert json.loads((output / "parallel-pilot.json").read_text(encoding="utf-8")) == report
