from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import aggregate_parallel_pilot
from scripts import profile_parallel_pytest


def _selected_for_command(command: list[str]) -> list[str]:
    all_nodes = [
        "tests/test_one.py::test_safe",
        "tests/operations/test_transactions.py::test_serial",
    ]
    if "not serial" in command:
        return all_nodes[:1]
    if "serial" in command:
        return all_nodes[1:]
    return all_nodes


def _write_selected_manifest(command: list[str]) -> None:
    target = os.getenv("ETF_COCKPIT_PILOT_NODEID_MANIFEST")
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_selected_for_command(command)), encoding="utf-8")


def _write_executed_manifest(command: list[str]) -> None:
    target = os.getenv("ETF_COCKPIT_PILOT_EXECUTED_NODEID_MANIFEST")
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        selected = sorted(_selected_for_command(command))
        path.write_text(json.dumps(selected), encoding="utf-8")
        results_target = os.getenv("ETF_COCKPIT_PILOT_EXECUTED_RESULTS")
        if results_target:
            Path(results_target).write_text(
                json.dumps({nodeid: "passed" for nodeid in selected}), encoding="utf-8"
            )


def _junit_case(nodeid: str, body: str = "") -> str:
    path, name = nodeid.split("::", 1)
    classname = path.replace("/", ".")[:-3]
    return (
        f'<testcase classname="{classname}" name="{name}">'
        '<properties>'
        f'<property name="pilot_nodeid" value="{nodeid}"/>'
        f"</properties>{body}</testcase>"
    )


def test_profile_records_repeated_serial_parallel_parity_and_timings(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "requirements-release.txt").write_text("build==1.3.0\n", encoding="utf-8")
    (root / "requirements-release-parsers.txt").write_text("parser==1.0.0\n", encoding="utf-8")
    def completed(_root: Path, command: list[str]):
        _write_selected_manifest(command)
        _write_executed_manifest(command)
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "tests/test_one.py: 1\n", ""), 6.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        selected = _selected_for_command(command)
        Path(junit_arg.partition("=")[2]).write_text(
            "<testsuite>"
            + "".join(
                _junit_case(node)
                for node in selected
            )
            + "</testsuite>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 4.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    ticks = iter((100.0, 108.0, 200.0, 208.0))
    report = profile_parallel_pytest.profile(
        root, tmp_path / "evidence", 2, clock=lambda: next(ticks)
    )

    assert report["status"] == "passed"
    assert report["mode"] == "report_only"
    assert report["authority"] == "serial_release_gate"
    assert report["workers"] == 4
    assert report["repetitions"] == 2
    assert report["sample_count"] == 2
    assert report["strategy"] == "full_serial_vs_two_phase_xdist"
    assert report["phase_order"] == ["safe", "unsafe"]
    assert report["run_order"] == [["full_serial", "candidate"], ["candidate", "full_serial"]]
    assert report["collection_parity"] is True
    assert report["collection_evidence_valid"] is True
    assert report["result_parity"] is True
    assert len(report["lane_fingerprints"]["full_serial"]["collection"]) == 2
    assert report["lane_counts"]["candidate_combined"] == {"collection": [2, 2], "results": [2, 2]}
    assert report["lane_codes"]["candidate_safe"]["collection"] == [0, 0]
    assert report["timings"]["candidate_wall"]["p50_seconds"] == 2.0
    assert len(report["cache"]["key_sha256"]) == 64
    assert (tmp_path / "evidence" / "collection-full_serial-1.stdout.log").is_file()
    assert (tmp_path / "evidence" / "tests-unsafe-2.stderr.log").is_file()


def test_collection_failure_makes_report_divergent(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    calls = 0

    def completed(_root: Path, command: list[str]):
        nonlocal calls
        calls += 1
        _write_selected_manifest(command)
        if "--collect-only" in command:
            return subprocess.CompletedProcess(
                command,
                2 if calls == 1 else 0,
                "tests/test_one.py: 1\n",
                "collection failed",
            ), 1.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        Path(junit_arg.partition("=")[2]).write_text(
            '<testsuite>' + _junit_case("tests/test_one.py::test_ok") + "</testsuite>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 1.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    report = profile_parallel_pytest.profile(root, tmp_path / "evidence", 2)

    assert report["status"] == "divergent"
    assert report["lanes"]["full_serial"]["collection_exit_codes"] == [2, 0]
    assert (
        tmp_path / "evidence" / "collection-full_serial-1.stderr.log"
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


def test_cache_evidence_normalises_lock_line_endings(tmp_path: Path) -> None:
    (tmp_path / "requirements-release.txt").write_bytes(b"build==1.3.0\n")
    (tmp_path / "requirements-release-parsers.txt").write_bytes(b"parser==1.0.0\n")
    first = profile_parallel_pytest.cache_evidence(tmp_path)
    (tmp_path / "requirements-release.txt").write_bytes(b"build==1.3.0\r\n")
    (tmp_path / "requirements-release-parsers.txt").write_bytes(b"parser==1.0.0\r\n")
    second = profile_parallel_pytest.cache_evidence(tmp_path)

    assert first["inputs"]["locks"] == second["inputs"]["locks"]
    assert first["key_sha256"] == second["key_sha256"]


def test_duplicate_junit_identity_is_rejected(tmp_path: Path) -> None:
    junit = tmp_path / "duplicate.xml"
    junit.write_text(
        "<testsuite>"
        + _junit_case("tests/test_one.py::test_ok")
        + _junit_case("tests/test_one.py::test_ok")
        + "</testsuite>",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JUnit testcase identity"):
        profile_parallel_pytest._junit_results(junit)


def test_duplicate_executed_manifest_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "executed.json"
    manifest.write_text(json.dumps(["tests/test_one.py::test_ok"] * 2), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest contains duplicates"):
        profile_parallel_pytest._manifest_nodeids(manifest)


def test_junit_parameter_identity_with_colons_is_checked_without_reconstruction(tmp_path: Path) -> None:
    junit = tmp_path / "parameter.xml"
    junit.write_text(
        "<testsuite>"
        + _junit_case("tests/test_one.py::test_value[a::b]")
        + _junit_case("tests/test_one.py::test_value[a::b]")
        + "</testsuite>",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JUnit testcase identity"):
        profile_parallel_pytest._junit_results(junit)


def test_profile_rejects_same_count_wrong_executed_identity(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "requirements-release.txt").write_text("build==1.3.0\n", encoding="utf-8")
    (root / "requirements-release-parsers.txt").write_text("parser==1.0.0\n", encoding="utf-8")

    def completed(_root: Path, command: list[str]):
        _write_selected_manifest(command)
        _write_executed_manifest(command)
        if "--collect-only" not in command:
            target = os.getenv("ETF_COCKPIT_PILOT_EXECUTED_NODEID_MANIFEST")
            assert target is not None
            Path(target).write_text(json.dumps(["tests/test_one.py::test_wrong"]), encoding="utf-8")
            results_target = os.getenv("ETF_COCKPIT_PILOT_EXECUTED_RESULTS")
            assert results_target is not None
            Path(results_target).write_text(
                json.dumps({"tests/test_one.py::test_wrong": "passed"}), encoding="utf-8"
            )
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "tests/test_one.py: 1\n", ""), 1.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        Path(junit_arg.partition("=")[2]).write_text(
            '<testsuite>' + _junit_case("tests/test_one.py::test_safe") + "</testsuite>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 1.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    report = profile_parallel_pytest.profile(root, tmp_path / "evidence", 2)

    assert report["status"] == "divergent"
    assert report["collection_evidence_valid"] is False


def test_profile_rejects_same_count_wrong_junit_identity_and_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "requirements-release.txt").write_text("build==1.3.0\n", encoding="utf-8")
    (root / "requirements-release-parsers.txt").write_text("parser==1.0.0\n", encoding="utf-8")

    def completed(_root: Path, command: list[str]):
        _write_selected_manifest(command)
        _write_executed_manifest(command)
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "tests/test_one.py: 1\n", ""), 1.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        selected = _selected_for_command(command)
        Path(junit_arg.partition("=")[2]).write_text(
            "<testsuite>"
            + "".join(_junit_case(f"{node}[wrong]", "<failure/>") for node in selected)
            + "</testsuite>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 1.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    report = profile_parallel_pytest.profile(root, tmp_path / "evidence", 2)

    assert report["status"] == "divergent"
    assert report["collection_evidence_valid"] is False


def test_controller_state_does_not_reset_for_nested_parent_session(monkeypatch) -> None:
    outer = SimpleNamespace(config=SimpleNamespace(workerinput=None))
    nested = SimpleNamespace(config=SimpleNamespace(workerinput=None))
    # Isolate the faithful nested-controller simulation from this pytest
    # process's real outer session, then restore it before this test returns so
    # its own JUnit/result report remains in the outer manifest.
    with monkeypatch.context() as isolated:
        isolated.setattr(profile_parallel_pytest, "_CONTROLLER_STATE", None)
        profile_parallel_pytest.pytest_sessionstart(outer)
        profile_parallel_pytest.pytest_runtest_logreport(
            SimpleNamespace(when="call", nodeid="tests/outer.py::test_outer", outcome="passed")
        )
        profile_parallel_pytest.pytest_sessionstart(nested)
        profile_parallel_pytest.pytest_runtest_logreport(
            SimpleNamespace(
                when="call", nodeid="tests/outer.py::test_after_nested", outcome="passed"
            )
        )
        profile_parallel_pytest.pytest_sessionfinish(nested, 0)

        state = profile_parallel_pytest._CONTROLLER_STATE
        assert state is not None
        assert state.session is outer
        assert state.nodeid_events == [
            "tests/outer.py::test_outer",
            "tests/outer.py::test_after_nested",
        ]
        assert state.results == {
            "tests/outer.py::test_outer": "passed",
            "tests/outer.py::test_after_nested": "passed",
        }


def test_controller_state_resets_only_after_owning_parent_finishes(monkeypatch) -> None:
    first = SimpleNamespace(config=SimpleNamespace(workerinput=None))
    second = SimpleNamespace(config=SimpleNamespace(workerinput=None))
    with monkeypatch.context() as isolated:
        isolated.setattr(profile_parallel_pytest, "_CONTROLLER_STATE", None)
        profile_parallel_pytest.pytest_sessionstart(first)
        profile_parallel_pytest.pytest_runtest_logreport(
            SimpleNamespace(when="call", nodeid="tests/first.py::test_first", outcome="passed")
        )
        profile_parallel_pytest.pytest_sessionfinish(second, 0)
        state = profile_parallel_pytest._CONTROLLER_STATE
        assert state is not None
        assert state.session is first
        profile_parallel_pytest.pytest_sessionfinish(first, 0)
        assert profile_parallel_pytest._CONTROLLER_STATE is None

        profile_parallel_pytest.pytest_sessionstart(second)
        state = profile_parallel_pytest._CONTROLLER_STATE
        assert state is not None
        assert state.session is second
        assert state.nodeid_events == []
        assert state.results == {}


def test_real_pytest_manifest_is_post_deselection_and_disjoint(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    selected: dict[str, set[str]] = {}
    for label, selector in (
        ("full", []),
        ("safe", ["-m", "not serial"]),
        ("unsafe", ["-m", "serial"]),
    ):
        manifest = tmp_path / f"{label}.json"
        environment = os.environ.copy()
        environment["ETF_COCKPIT_PILOT_NODEID_MANIFEST"] = str(manifest)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_screen_store.py::test_saved_screen_revisions_are_immutable_and_replayable",
                "tests/test_screen_store.py::test_revision_lock_does_not_reclaim_malformed_or_live_stale_owner",
                "tests/operations/test_transactions.py::test_group_reader_cannot_observe_mixed_generation_during_activation",
                "tests/operations/test_transactions.py::test_recovery_of_interrupted_second_real_writer_preserves_first_commit",
                *selector,
                "--collect-only",
                "-q",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        selected[label] = set(json.loads(manifest.read_text(encoding="utf-8")))
    assert selected["full"]
    assert selected["safe"]
    assert selected["unsafe"]
    assert selected["safe"].isdisjoint(selected["unsafe"])
    assert selected["safe"] | selected["unsafe"] == selected["full"]
    assert {
        "tests/test_screen_store.py::test_revision_lock_does_not_reclaim_malformed_or_live_stale_owner[malformed-owner]",
        "tests/test_screen_store.py::test_revision_lock_does_not_reclaim_malformed_or_live_stale_owner[live-owner]",
        "tests/operations/test_transactions.py::test_recovery_of_interrupted_second_real_writer_preserves_first_commit",
    } <= selected["unsafe"]


def test_aggregate_rejects_forged_projection_and_timing_evidence(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    payload = _pilot_report()
    payload["lane_counts"]["full_serial"]["collection"][0] += 1
    payload["timings"]["candidate_wall"]["samples_seconds"][0] = -1.0
    windows_payload = _pilot_report()
    windows_payload["platform"] = "windows"
    linux.write_text(json.dumps(payload), encoding="utf-8")
    windows.write_text(json.dumps(windows_payload), encoding="utf-8")
    report = aggregate_parallel_pilot.compare_reports(linux, windows)
    assert report["status"] == "divergent"
    assert report["differences"]["linux_validity"] is False


def test_empty_collection_summary_cannot_pass_with_matching_junit(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    def completed(_root: Path, command: list[str]):
        _write_selected_manifest(command)
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
    assert report["lanes"]["full_serial"]["junit_present"] == [False, False]
    assert report["lanes"]["candidate_safe"]["junit_present"] == [False, False]


def test_profile_accepts_one_drift_sample_and_rejects_zero(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    def completed(_root: Path, command: list[str]):
        _write_selected_manifest(command)
        _write_executed_manifest(command)
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0, "tests/test_one.py: 1\n", ""), 1.0
        junit_arg = next(value for value in command if value.startswith("--junitxml="))
        Path(junit_arg.partition("=")[2]).write_text(
            "<testsuite>"
            + "".join(_junit_case(node) for node in _selected_for_command(command))
            + "</testsuite>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", ""), 1.0

    monkeypatch.setattr(profile_parallel_pytest, "_run", completed)
    ticks = iter((100.0, 108.0))
    report = profile_parallel_pytest.profile(
        root, tmp_path / "evidence", 1, clock=lambda: next(ticks)
    )

    assert report["status"] == "passed"
    assert report["repetitions"] == 1
    assert report["sample_count"] == 1
    with pytest.raises(ValueError, match="repetitions must be at least 1"):
        profile_parallel_pytest.profile(root, tmp_path / "invalid", 0)


def _pilot_report(*, status: str = "passed", result_suffix: str = "") -> dict[str, object]:
    lane_shapes = {
        "full_serial": 3,
        "candidate_safe": 1,
        "candidate_unsafe": 2,
        "candidate_combined": 3,
    }
    lanes: dict[str, dict[str, object]] = {}
    for lane, count in lane_shapes.items():
        duration = 2.0 if lane == "candidate_combined" else 1.0
        nodeids = [f"tests/test_case_{index}.py::test_case" for index in range(count)]
        outcome = "failure" if result_suffix else "passed"
        outcome_map = {nodeid: outcome for nodeid in nodeids}
        collection_fingerprint = hashlib.sha256(
            json.dumps(sorted(set(nodeids)), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result_fingerprint = hashlib.sha256(
            json.dumps(outcome_map, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        lanes[lane] = {
            "collection_counts": [count, count],
            "result_counts": [count, count],
            "collection_exit_codes": [0, 0],
            "exit_codes": [0, 0],
            "junit_present": [True, True],
            "collection_fingerprints": [collection_fingerprint, collection_fingerprint],
            "result_fingerprints": [result_fingerprint, result_fingerprint],
            "executed_nodeids": [nodeids, nodeids],
            "result_outcomes": [outcome_map, outcome_map],
            "timings": {
                "samples_seconds": [duration, duration],
                "p50_seconds": duration,
                "p95_seconds": duration,
            },
        }
    inputs = {
        "os": "linux",
        "python": "3.12.10",
        "locks": {
            "requirements-release.txt": "a" * 64,
            "requirements-release-parsers.txt": "b" * 64,
        },
        "build_tools": {name: "1.0" for name in ("build", "pip", "pytest", "pytest-xdist")},
    }
    return {
        "schema_version": "pytest-parallel-pilot.v2",
        "mode": "report_only",
        "authority": "serial_release_gate",
        "platform": "linux",
        "workers": 4,
        "repetitions": 2,
        "sample_count": 2,
        "strategy": "full_serial_vs_two_phase_xdist",
        "phase_order": ["safe", "unsafe"],
        "selectors": {
            "full_serial": [],
            "safe": ["-m", "not serial"],
            "unsafe": ["-m", "serial"],
        },
        "unsafe_groups": ["concurrency", "environment", "flet", "package", "ports", "sqlite"],
        "collection_parity": True,
        "collection_evidence_valid": True,
        "result_parity": True,
        "repeatable_results": True,
        "repeatable_collections": True,
        "manifest_valid": {lane: [True, True] for lane in lane_shapes},
        "lanes": lanes,
        "lane_counts": {
            lane: {"collection": value["collection_counts"], "results": value["result_counts"]}
            for lane, value in lanes.items()
        },
        "lane_codes": {
            lane: {"collection": value["collection_exit_codes"], "tests": value["exit_codes"]}
            for lane, value in lanes.items()
        },
        "lane_fingerprints": {
            lane: {"collection": value["collection_fingerprints"], "results": value["result_fingerprints"]}
            for lane, value in lanes.items()
        },
        "timings": {
            **{lane: value["timings"] for lane, value in lanes.items()},
            "candidate_wall": {
                "samples_seconds": [2.0, 2.0],
                "p50_seconds": 2.0,
                "p95_seconds": 2.0,
            },
        },
        "cache": {
            "schema_version": "pytest-parallel-pilot-cache.v1",
            "key_sha256": hashlib.sha256(
                json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "inputs": inputs,
            "setup_python_cache_hit": "true",
        },
        "run_order": [["full_serial", "candidate"], ["candidate", "full_serial"]],
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
    windows_cache = windows_payload["cache"]
    assert isinstance(windows_cache, dict)
    windows_inputs = windows_cache["inputs"]
    assert isinstance(windows_inputs, dict)
    windows_inputs["os"] = "windows"
    windows_cache["key_sha256"] = hashlib.sha256(
        json.dumps(windows_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
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
    assert "full_serial.result_outcomes[0]" in report["differences"]

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


def test_cross_platform_aggregation_accepts_only_known_pid_outcome_difference(tmp_path: Path) -> None:
    linux = _pilot_report()
    windows = _pilot_report()
    known = "tests/test_pid_liveness.py::test_windows_pid_probe_does_not_terminate_a_child_process"
    for payload, outcome in ((linux, "skipped"), (windows, "passed")):
        for lane_name, lane in payload["lanes"].items():
            if lane_name not in aggregate_parallel_pilot._KNOWN_PLATFORM_LANES:
                continue
            nodeids = list(lane["executed_nodeids"][0])
            old_nodeid = nodeids[0]
            nodeids[0] = known
            nodeids.sort()
            lane["executed_nodeids"][0] = nodeids
            lane["result_outcomes"][0] = {
                known: outcome,
                **{
                    nodeid: value
                    for nodeid, value in lane["result_outcomes"][0].items()
                    if nodeid != old_nodeid
                },
            }
            lane["collection_fingerprints"][0] = hashlib.sha256(
                json.dumps(sorted(set(nodeids)), separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            lane["result_fingerprints"][0] = hashlib.sha256(
                json.dumps(lane["result_outcomes"][0], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            lane["executed_nodeids"][1] = list(nodeids)
            lane["result_outcomes"][1] = dict(lane["result_outcomes"][0])
            lane["collection_fingerprints"][1] = lane["collection_fingerprints"][0]
            lane["result_fingerprints"][1] = lane["result_fingerprints"][0]
        for lane_name, lane in payload["lanes"].items():
            payload["lane_fingerprints"][lane_name]["collection"] = lane["collection_fingerprints"]
            payload["lane_fingerprints"][lane_name]["results"] = lane["result_fingerprints"]
    linux_path = tmp_path / "linux.json"
    windows_path = tmp_path / "windows.json"
    _write_platform_reports(linux_path, windows_path, linux_report=linux, windows_report=windows)

    report = aggregate_parallel_pilot.compare_reports(linux_path, windows_path)

    assert report["status"] == "passed"


def test_cross_platform_aggregation_rejects_tampered_or_missing_cache(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    payload = _pilot_report()
    payload["cache"]["key_sha256"] = "0" * 64
    _write_platform_reports(linux, windows, linux_report=payload)
    report = aggregate_parallel_pilot.compare_reports(linux, windows)
    assert report["status"] == "divergent"
    assert report["differences"]["linux_validity"] is False

    payload = _pilot_report()
    payload.pop("cache")
    _write_platform_reports(linux, windows, linux_report=payload)
    report = aggregate_parallel_pilot.compare_reports(linux, windows)
    assert report["status"] == "divergent"
    assert report["differences"]["linux_validity"] is False


def test_cross_platform_aggregation_recomputes_identity_and_result_fingerprints(tmp_path: Path) -> None:
    linux = _pilot_report()
    lane = linux["lanes"]["full_serial"]
    lane["result_fingerprints"][0] = "0" * 64
    linux["lane_fingerprints"]["full_serial"]["results"] = lane["result_fingerprints"]
    windows = _pilot_report()
    linux_path = tmp_path / "linux.json"
    windows_path = tmp_path / "windows.json"
    _write_platform_reports(linux_path, windows_path, linux_report=linux, windows_report=windows)

    report = aggregate_parallel_pilot.compare_reports(linux_path, windows_path)

    assert report["status"] == "divergent"
    assert report["differences"]["linux_validity"] is False


def test_cross_platform_aggregation_rejects_same_count_wrong_executed_ids(tmp_path: Path) -> None:
    linux = _pilot_report()
    windows = _pilot_report()
    for lane_name, lane in windows["lanes"].items():
        nodeids = list(lane["executed_nodeids"][0])
        old_nodeid = nodeids[0]
        nodeids[0] = "tests/wrong.py::test_case"
        nodeids.sort()
        outcomes = {
            nodeid: value
            for nodeid, value in lane["result_outcomes"][0].items()
            if nodeid != old_nodeid
        }
        outcomes["tests/wrong.py::test_case"] = "passed"
        lane["executed_nodeids"][0] = nodeids
        lane["result_outcomes"][0] = outcomes
        lane["collection_fingerprints"][0] = hashlib.sha256(
            json.dumps(nodeids, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        lane["result_fingerprints"][0] = hashlib.sha256(
            json.dumps(outcomes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        lane["executed_nodeids"][1] = list(nodeids)
        lane["result_outcomes"][1] = dict(outcomes)
        lane["collection_fingerprints"][1] = lane["collection_fingerprints"][0]
        lane["result_fingerprints"][1] = lane["result_fingerprints"][0]
        windows["lane_fingerprints"][lane_name]["collection"] = lane["collection_fingerprints"]
        windows["lane_fingerprints"][lane_name]["results"] = lane["result_fingerprints"]
    linux_path = tmp_path / "linux.json"
    windows_path = tmp_path / "windows.json"
    _write_platform_reports(linux_path, windows_path, linux_report=linux, windows_report=windows)

    report = aggregate_parallel_pilot.compare_reports(linux_path, windows_path)

    assert report["status"] == "divergent"
    assert "full_serial.executed_nodeids" in report["differences"]


def test_cross_platform_aggregation_rejects_missing_evidence_fields(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    payload = _pilot_report()
    payload.pop("lane_counts")
    windows_payload = dict(payload)
    windows_payload["platform"] = "windows"
    linux.write_text(json.dumps(payload), encoding="utf-8")
    windows.write_text(json.dumps(windows_payload), encoding="utf-8")

    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "divergent"
    assert "lane_counts" in report["differences"]


def test_cross_platform_aggregation_rejects_nonzero_exit_codes(tmp_path: Path) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    linux_report = _pilot_report()
    windows_report = _pilot_report()
    windows_report["lanes"]["candidate_safe"]["exit_codes"] = [1, 0]
    _write_platform_reports(
        linux,
        windows,
        linux_report=linux_report,
        windows_report=windows_report,
    )

    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "divergent"
    assert report["differences"]["windows_validity"] is False


@pytest.mark.parametrize(
    "mutation",
    ("impossible_wall", "nonrepeatable_collection", "result_mismatch"),
)
def test_cross_platform_aggregation_rejects_semantic_contradictions(
    tmp_path: Path, mutation: str
) -> None:
    linux = tmp_path / "linux.json"
    windows = tmp_path / "windows.json"
    windows_report = _pilot_report()
    if mutation == "impossible_wall":
        windows_report["timings"]["candidate_wall"] = {
            "samples_seconds": [0.0, 0.0],
            "p50_seconds": 0.0,
            "p95_seconds": 0.0,
        }
    elif mutation == "nonrepeatable_collection":
        windows_report["lanes"]["candidate_safe"]["collection_fingerprints"][1] = (
            "d" * 64
        )
        windows_report["lane_fingerprints"]["candidate_safe"]["collection"][1] = (
            "d" * 64
        )
    else:
        windows_report["lanes"]["candidate_combined"]["result_fingerprints"] = [
            "e" * 64,
            "e" * 64,
        ]
        windows_report["lane_fingerprints"]["candidate_combined"]["results"] = [
            "e" * 64,
            "e" * 64,
        ]
    _write_platform_reports(
        linux,
        windows,
        windows_report=windows_report,
    )

    report = aggregate_parallel_pilot.compare_reports(linux, windows)

    assert report["status"] == "divergent"
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
    assert '"${RUNNER_TEMP}/etf-cockpit-parallel-pilot-${{ matrix.platform }}"' in pilot
    assert "artifacts/parallel-pilot" not in pilot
    assert "path: ${{ runner.temp }}/etf-cockpit-parallel-pilot-${{ matrix.platform }}" in pilot
    assert "parallel-pilot-aggregate:" in workflow
    assert "actions/download-artifact@v4" in aggregate
    assert "scripts/aggregate_parallel_pilot.py" in aggregate
    assert "continue-on-error: true" in aggregate
    assert "needs: [classifier, preflight, supply-chain, parallel-pilot]" in aggregate
    assert "parallel_pilot_repetitions" in workflow
