from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import aggregate_parallel_pilot
from scripts import profile_parallel_pytest


def test_profile_records_repeated_serial_parallel_parity_and_timings(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "requirements-release.txt").write_text("build==1.3.0\n", encoding="utf-8")
    def completed(_root: Path, command: list[str]):
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "tests/test_one.py: 1\n", ""), 6.0
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
    assert report["sample_count"] == 2
    assert report["sample_counts"] == {"serial": 2, "parallel": 2}
    assert report["run_order"] == [["serial", "parallel"], ["parallel", "serial"]]
    assert report["collection_parity"] is True
    assert report["collection_evidence_valid"] is True
    assert report["result_parity"] is True
    assert len(report["collection_fingerprints"]["serial"]) == 2
    assert report["collection_counts"] == {"serial": [1, 1], "parallel": [1, 1]}
    assert len(report["result_fingerprints"]["parallel"]) == 2
    assert report["result_counts"] == {"serial": [1, 1], "parallel": [1, 1]}
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
            return subprocess.CompletedProcess(
                command,
                2 if calls == 1 else 0,
                "tests/test_one.py: 1\n",
                "collection failed",
            ), 1.0
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


def test_collection_summary_normalises_platform_paths_and_counts() -> None:
    output = (
        "tests/operations/test_events.py: 6\n"
        "tests\\ui\\test_shell.py: 3\n"
        "9 tests collected in 0.12s\n"
    )

    summary = profile_parallel_pytest._collection_nodeids(output)

    assert summary == [
        "tests/operations/test_events.py:6",
        "tests/ui/test_shell.py:3",
    ]
    assert profile_parallel_pytest._collection_count(summary) == 9


def test_duplicate_junit_identity_is_rejected(tmp_path: Path) -> None:
    junit = tmp_path / "duplicate.xml"
    junit.write_text(
        "<testsuite>"
        '<testcase classname="tests.test_one" name="test_ok"/>'
        '<testcase classname="tests.test_one" name="test_ok"/>'
        "</testsuite>",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JUnit testcase identity"):
        profile_parallel_pytest._junit_results(junit)


def test_empty_collection_summary_cannot_pass_with_matching_junit(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    def completed(_root: Path, command: list[str]):
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "2200 tests collected\n", ""), 1.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        Path(junit_arg.partition("=")[2]).write_text(
            '<testsuite><testcase classname="tests.test_one" name="test_ok"/></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 1.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    report = profile_parallel_pytest.profile(root, tmp_path / "evidence", 2)

    assert report["collection_evidence_valid"] is False
    assert report["status"] == "divergent"


def test_main_returns_nonzero_for_divergence_and_writes_json(tmp_path: Path, monkeypatch) -> None:
    report = {"status": "divergent", "mode": "report_only"}
    monkeypatch.setattr(profile_parallel_pytest, "profile", lambda *_args: report)
    output = tmp_path / "evidence"

    assert profile_parallel_pytest.main(["--root", str(tmp_path), "--output", str(output)]) == 1
    assert json.loads((output / "parallel-pilot.json").read_text(encoding="utf-8")) == report


def test_missing_junit_evidence_is_divergent(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()

    def completed(_root: Path, command: list[str]):
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "tests/test_one.py: 1\n", ""), 1.0
        return subprocess.CompletedProcess(command, 0, "", ""), 1.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    report = profile_parallel_pytest.profile(root, tmp_path / "evidence", 2)

    assert report["status"] == "divergent"
    assert report["junit_present"] == {"serial": [False, False], "parallel": [False, False]}


def test_profile_rejects_less_than_two_samples(tmp_path: Path) -> None:
    try:
        profile_parallel_pytest.profile(tmp_path, tmp_path / "evidence", 1)
    except ValueError as exc:
        assert str(exc) == "repetitions must be at least 2"
    else:
        raise AssertionError("profile accepted fewer than two repetitions")


def _pilot_report(*, status: str = "passed", result_suffix: str = "") -> dict[str, object]:
    return {
        "schema_version": "pytest-parallel-pilot.v1",
        "mode": "report_only",
        "authority": "serial_release_gate",
        "platform": "linux",
        "workers": 4,
        "repetitions": 2,
        "unsafe_groups": ["concurrency", "environment", "flet", "package", "ports", "sqlite"],
        "collection_parity": True,
        "collection_evidence_valid": True,
        "result_parity": True,
        "repeatable_results": True,
        "collection_fingerprints": {
            "serial": ["collection", "collection"],
            "parallel": ["collection", "collection"],
        },
        "collection_counts": {"serial": [3, 3], "parallel": [3, 3]},
        "result_fingerprints": {
            "serial": [f"result{result_suffix}", f"result{result_suffix}"],
            "parallel": [f"result{result_suffix}", f"result{result_suffix}"],
        },
        "result_counts": {"serial": [3, 3], "parallel": [3, 3]},
        "junit_present": {"serial": [True, True], "parallel": [True, True]},
        "collection_exit_codes": {"serial": [0, 0], "parallel": [0, 0]},
        "exit_codes": {"serial": [0, 0], "parallel": [0, 0]},
        "sample_count": 2,
        "sample_counts": {"serial": 2, "parallel": 2},
        "run_order": [["serial", "parallel"], ["parallel", "serial"]],
        "status": status,
    }


def _write_platform_reports(
    linux: Path,
    windows: Path,
    *,
    linux_report: dict[str, object] | None = None,
    windows_report: dict[str, object] | None = None,
) -> None:
    linux_payload = linux_report or _pilot_report()
    windows_payload = windows_report or _pilot_report()
    windows_payload["platform"] = "windows"
    linux.write_text(json.dumps(linux_payload), encoding="utf-8")
    windows.write_text(json.dumps(windows_payload), encoding="utf-8")


def test_cross_platform_aggregation_rejects_result_and_status_divergence(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    _write_platform_reports(
        linux,
        windows,
        windows_report=_pilot_report(result_suffix="-windows"),
    )

    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "divergent"
    assert "result_fingerprints" in report["differences"]

    divergent_windows = _pilot_report(status="divergent")
    divergent_windows["platform"] = "windows"
    windows.write_text(json.dumps(divergent_windows), encoding="utf-8")
    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "divergent"
    assert "status" in report["differences"]

    output = tmp_path / "aggregate.json"
    assert (
        aggregate_parallel_pilot.main(
            [
                "--linux-report",
                str(linux),
                "--windows-report",
                str(windows),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "divergent"


def test_cross_platform_aggregation_accepts_matching_reports(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    _write_platform_reports(linux, windows)

    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "passed"
    assert report["differences"] == {}


def test_cross_platform_aggregation_rejects_missing_evidence_fields(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    payload = _pilot_report()
    payload.pop("junit_present")
    windows_payload = dict(payload)
    windows_payload["platform"] = "windows"
    linux.write_text(json.dumps(payload), encoding="utf-8")
    windows.write_text(json.dumps(windows_payload), encoding="utf-8")

    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "divergent"
    assert "junit_present" in report["differences"]


def test_cross_platform_aggregation_rejects_nonzero_exit_codes(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    linux_report = _pilot_report()
    windows_report = _pilot_report()
    windows_report["exit_codes"] = {"serial": [0, 0], "parallel": [1, 0]}
    _write_platform_reports(
        linux,
        windows,
        linux_report=linux_report,
        windows_report=windows_report,
    )

    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "divergent"
    assert "exit_codes" in report["differences"]
    assert report["differences"]["windows_validity"] is False


def test_workflow_isolates_pilot_and_keeps_aggregation_non_authoritative() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release-gate.yml").read_text(encoding="utf-8")
    pilot = workflow.split("  parallel-pilot:\n", maxsplit=1)[1].split(
        "  parallel-pilot-aggregate:\n", maxsplit=1
    )[0]
    aggregate = workflow.split("  parallel-pilot-aggregate:\n", maxsplit=1)[1].split(
        "  validation-summary:\n", maxsplit=1
    )[0]

    assert pilot.index("Configure isolated user profile") < pilot.index("Verify protected environment")
    assert pilot.index("Verify protected environment") < pilot.index("Prepare pilot evidence directory")
    assert pilot.index("Prepare pilot evidence directory") < pilot.index(
        "Run repeated report-only four-worker pilot"
    )
    assert "python scripts/release_gate.py --root . --verify-environment" in pilot
    assert "ETF_COCKPIT_RELEASE_SIGNING_KEY" not in pilot
    assert "Ensure pilot evidence directory for upload" in pilot
    assert "parallel-pilot-aggregate:" in workflow
    assert "actions/download-artifact@v4" in aggregate
    assert "scripts/aggregate_parallel_pilot.py" in aggregate
    assert "continue-on-error: true" in aggregate
    assert "needs: [classifier, parallel-pilot]" in aggregate
