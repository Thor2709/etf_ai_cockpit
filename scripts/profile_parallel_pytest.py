"""Measure the report-only four-worker pytest pilot against serial runs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Sequence


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _junit_results(path: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    for case in ET.parse(path).iter("testcase"):
        identity = (case.attrib.get("classname", ""), case.attrib.get("name", ""))
        nodeid = f"{identity[0]}::{identity[1]}"
        if nodeid in results:
            raise ValueError(f"duplicate JUnit testcase identity: {nodeid}")
        outcome = "passed"
        for status in ("failure", "error", "skipped"):
            if case.find(status) is not None:
                outcome = status
                break
        results[nodeid] = outcome
    return results


_COLLECTION_SUMMARY_RE = re.compile(r"^(tests[\\/].+\.py):\s+(\d+)$")


def _collection_nodeids(output: str) -> list[str]:
    """Normalise pytest 9's ordered per-file collection summary."""

    collected: list[str] = []
    for raw_line in output.splitlines():
        match = _COLLECTION_SUMMARY_RE.fullmatch(raw_line.strip())
        if match is not None:
            normalised_path = match.group(1).replace("\\", "/")
            collected.append(f"{normalised_path}:{match.group(2)}")
    return collected


def _collection_count(summary: list[str]) -> int:
    return sum(int(row.rpartition(":")[2]) for row in summary)


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_nodeids(nodeids: list[str]) -> list[str]:
    return sorted(set(nodeids))


def _run(root: Path, command: Sequence[str]) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed, time.perf_counter() - started


def _write_diagnostics(
    output: Path, stem: str, completed: subprocess.CompletedProcess[str]
) -> None:
    (output / f"{stem}.stdout.log").write_text(
        completed.stdout, encoding="utf-8", newline="\n"
    )
    (output / f"{stem}.stderr.log").write_text(
        completed.stderr, encoding="utf-8", newline="\n"
    )


_MANIFEST_ENV = "ETF_COCKPIT_PILOT_NODEID_MANIFEST"
_EXECUTED_MANIFEST_ENV = "ETF_COCKPIT_PILOT_EXECUTED_NODEID_MANIFEST"
_EXECUTED_RESULTS_ENV = "ETF_COCKPIT_PILOT_EXECUTED_RESULTS"
_UNSAFE_GROUPS = ["concurrency", "environment", "flet", "package", "ports", "sqlite"]
_PILOT_PLUGIN = "scripts.profile_parallel_pytest"
_LOCK_FILES = ("requirements-release.txt", "requirements-release-parsers.txt")
_TOOL_NAMES = ("build", "pip", "pytest", "pytest-xdist")
_EXECUTED_NODEID_EVENTS: list[str] = []
_EXECUTED_RESULTS: dict[str, str] = {}


def pytest_runtest_logreport(report: object) -> None:
    """Capture exact nodeids from reports received by the pytest controller."""

    when = getattr(report, "when", None)
    if when in {"setup", "call", "teardown"}:
        nodeid = getattr(report, "nodeid", None)
        if isinstance(nodeid, str) and nodeid:
            nodeid = nodeid.replace("\\", "/")
            outcome = getattr(report, "outcome", None)
            if when == "call" or (when == "setup" and outcome in {"failed", "skipped"}):
                _EXECUTED_NODEID_EVENTS.append(nodeid)
            if outcome in {"failed", "skipped"}:
                _EXECUTED_RESULTS[nodeid] = "error" if outcome == "failed" else "skipped"
            elif when == "call":
                _EXECUTED_RESULTS[nodeid] = "passed"
            elif nodeid not in _EXECUTED_RESULTS:
                _EXECUTED_RESULTS[nodeid] = "passed"


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    """Write exact executed nodeids after serial or xdist execution."""

    del exitstatus
    worker_input = getattr(getattr(session, "config", None), "workerinput", None)
    if worker_input is not None:
        return
    manifest_value = os.getenv(_EXECUTED_MANIFEST_ENV)
    if not manifest_value:
        return
    destination = Path(manifest_value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(sorted(_EXECUTED_NODEID_EVENTS)) + "\n", encoding="utf-8")
    results_value = os.getenv(_EXECUTED_RESULTS_ENV)
    if results_value:
        Path(results_value).write_text(json.dumps(_EXECUTED_RESULTS, sort_keys=True) + "\n", encoding="utf-8")


def _manifest_nodeids(path: Path) -> list[str]:
    """Read one exact selected-nodeid manifest, rejecting ambiguity."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(value, str) and value for value in payload):
        raise ValueError(f"selected-nodeid manifest is malformed: {path}")
    nodeids = [value.replace("\\", "/") for value in payload]
    if len(nodeids) != len(set(nodeids)):
        raise ValueError(f"selected-nodeid manifest contains duplicates: {path}")
    return nodeids


def _run_with_manifest(
    root: Path,
    command: Sequence[str],
    manifest: Path,
    *,
    executed: bool = False,
    result_manifest: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], float]:
    variable = _EXECUTED_MANIFEST_ENV if executed else _MANIFEST_ENV
    previous = os.environ.get(variable)
    previous_results = os.environ.get(_EXECUTED_RESULTS_ENV)
    os.environ[variable] = str(manifest)
    if executed and result_manifest is not None:
        os.environ[_EXECUTED_RESULTS_ENV] = str(result_manifest)
    try:
        return _run(root, command)
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        if previous_results is None:
            os.environ.pop(_EXECUTED_RESULTS_ENV, None)
        else:
            os.environ[_EXECUTED_RESULTS_ENV] = previous_results


def _timing_summary(samples: list[float]) -> dict[str, object]:
    return {
        "samples_seconds": samples,
        "p50_seconds": round(_percentile(samples, 0.50), 3) if samples else None,
        "p95_seconds": round(_percentile(samples, 0.95), 3) if samples else None,
    }


def _lane_record(
    collections: list[list[str]],
    results: list[dict[str, str]],
    collection_codes: list[int],
    exit_codes: list[int],
    junit_present: list[bool],
    durations: list[float],
) -> dict[str, object]:
    return {
        "collection_counts": [len(value) for value in collections],
        "result_counts": [len(value) for value in results],
        "collection_exit_codes": collection_codes,
        "exit_codes": exit_codes,
        "junit_present": junit_present,
        "collection_fingerprints": [
            _fingerprint(_canonical_nodeids(value)) for value in collections
        ],
        "result_fingerprints": [_fingerprint(value) for value in results],
        "executed_nodeids": [sorted(value) for value in results],
        "result_outcomes": results,
        "timings": _timing_summary(durations),
    }


def cache_evidence(root: Path) -> dict[str, object]:
    lock_paths = [root / name for name in _LOCK_FILES]
    lock_hashes = {
        path.name: hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        ).hexdigest()
        for path in lock_paths
        if path.is_file()
    }
    build_tools: dict[str, str] = {}
    for name in _TOOL_NAMES:
        try:
            build_tools[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            build_tools[name] = "unavailable"
    inputs = {
        "os": platform.system(),
        "python": platform.python_version(),
        "locks": lock_hashes,
        "build_tools": build_tools,
    }
    encoded = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "pytest-parallel-pilot-cache.v1",
        "key_sha256": hashlib.sha256(encoded).hexdigest(),
        "inputs": inputs,
        "setup_python_cache_hit": os.getenv("ETF_COCKPIT_SETUP_PYTHON_CACHE_HIT", "unknown"),
    }


def profile(
    root: Path,
    output: Path,
    repetitions: int,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, object]:
    if repetitions < 2:
        raise ValueError("repetitions must be at least 2")
    output.mkdir(parents=True, exist_ok=True)
    lanes = ("full_serial", "candidate_safe", "candidate_unsafe", "candidate_combined")
    collections: dict[str, list[list[str]]] = {name: [] for name in lanes}
    results: dict[str, list[dict[str, str]]] = {name: [] for name in lanes}
    durations: dict[str, list[float]] = {name: [] for name in lanes}
    exit_codes: dict[str, list[int]] = {name: [] for name in lanes}
    collection_exit_codes: dict[str, list[int]] = {name: [] for name in lanes}
    junit_present: dict[str, list[bool]] = {name: [] for name in lanes}
    manifest_valid: dict[str, list[bool]] = {name: [] for name in lanes}
    run_order: list[list[str]] = []
    candidate_wall_durations: list[float] = []

    for repetition in range(repetitions):
        order = ["full_serial", "candidate"] if repetition % 2 == 0 else ["candidate", "full_serial"]
        run_order.append(order)
        for lane in order:
            candidate_started: float | None = None
            candidate_collection_elapsed = 0.0
            phases: tuple[tuple[str, list[str], str], ...]
            if lane == "full_serial":
                phases = (("full_serial", [], "full_serial"),)
            else:
                phases = (
                    ("candidate_safe", ["-m", "not serial", "-n", "4", "--dist", "loadgroup"], "safe"),
                    ("candidate_unsafe", ["-m", "serial"], "unsafe"),
                )
            for mode, mode_args, phase in phases:
                stem = f"{phase}-{repetition + 1}"
                collection_manifest = output / f"manifest-collection-{stem}.json"
                collection, collection_duration = _run_with_manifest(
                    root,
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-p",
                        _PILOT_PLUGIN,
                        *mode_args[:2],
                        "--collect-only",
                        "-q",
                    ],
                    collection_manifest,
                )
                if lane == "candidate" and phase == "unsafe":
                    candidate_collection_elapsed += collection_duration
                _write_diagnostics(output, f"collection-{stem}", collection)
                collection_exit_codes[mode].append(collection.returncode)
                try:
                    selected = _manifest_nodeids(collection_manifest)
                    if not selected:
                        raise ValueError("selected-nodeid manifest is empty")
                    collections[mode].append(selected)
                    manifest_valid[mode].append(True)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    collections[mode].append([])
                    manifest_valid[mode].append(False)
                junit = output / f"junit-{phase}-{repetition + 1}.xml"
                run_manifest = output / f"manifest-run-{stem}.json"
                run_results = output / f"manifest-results-{stem}.json"
                if lane == "candidate" and phase == "safe":
                    # Start after safe collection; collection is evidence,
                    # not part of candidate execution wall time.
                    candidate_started = clock()
                completed, duration = _run_with_manifest(
                    root,
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-p",
                        _PILOT_PLUGIN,
                        *mode_args,
                        "-q",
                        "--durations=100",
                        "--durations-min=0.25",
                        f"--junitxml={junit}",
                    ],
                    run_manifest,
                    executed=True,
                    result_manifest=run_results,
                )
                _write_diagnostics(output, f"tests-{stem}", completed)
                durations[mode].append(round(duration, 3))
                exit_codes[mode].append(completed.returncode)
                present = junit.is_file()
                junit_present[mode].append(present)
                try:
                    run_selected = _manifest_nodeids(run_manifest)
                    if not manifest_valid[mode][-1] or set(run_selected) != set(collections[mode][-1]):
                        manifest_valid[mode][-1] = False
                    junit_results = _junit_results(junit) if present else {}
                    executed_results = json.loads(run_results.read_text(encoding="utf-8"))
                    if (
                        not isinstance(executed_results, dict)
                        or set(executed_results) != set(run_selected)
                        or not all(value in {"passed", "failure", "error", "skipped"} for value in executed_results.values())
                        or len(junit_results) != len(run_selected)
                    ):
                        manifest_valid[mode][-1] = False
                    parsed = executed_results if isinstance(executed_results, dict) else {}
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, ET.ParseError):
                    manifest_valid[mode][-1] = False
                    parsed = {}
                results[mode].append(parsed)

            if lane == "candidate":
                assert candidate_started is not None
                candidate_wall_durations.append(
                    round(clock() - candidate_started - candidate_collection_elapsed, 3)
                )

        safe = collections["candidate_safe"][-1]
        unsafe = collections["candidate_unsafe"][-1]
        safe_results = results["candidate_safe"][-1]
        unsafe_results = results["candidate_unsafe"][-1]
        combined = {**safe_results, **unsafe_results}
        if set(safe_results).intersection(unsafe_results):
            combined = {}
            manifest_valid["candidate_combined"].append(False)
        else:
            manifest_valid["candidate_combined"].append(
                manifest_valid["candidate_safe"][-1] and manifest_valid["candidate_unsafe"][-1]
            )
        collections["candidate_combined"].append(list(dict.fromkeys([*safe, *unsafe])))
        results["candidate_combined"].append(combined)
        exit_codes["candidate_combined"].append(
            max(exit_codes["candidate_safe"][-1], exit_codes["candidate_unsafe"][-1])
        )
        collection_exit_codes["candidate_combined"].append(
            max(collection_exit_codes["candidate_safe"][-1], collection_exit_codes["candidate_unsafe"][-1])
        )
        junit_present["candidate_combined"].append(
            junit_present["candidate_safe"][-1] and junit_present["candidate_unsafe"][-1]
        )
        durations["candidate_combined"].append(
            round(durations["candidate_safe"][-1] + durations["candidate_unsafe"][-1], 3)
        )

    serial_collections = collections["full_serial"]
    candidate_collections = collections["candidate_combined"]
    serial_results = results["full_serial"]
    candidate_results = results["candidate_combined"]
    collection_parity = bool(serial_collections) and all(
        _canonical_nodeids(serial_collections[index])
        == _canonical_nodeids(candidate_collections[index])
        for index in range(repetitions)
    )
    repeatable_collections = all(
        len({_fingerprint(_canonical_nodeids(run)) for run in collections[lane]}) == 1
        for lane in ("full_serial", "candidate_safe", "candidate_unsafe", "candidate_combined")
    )
    result_parity = bool(serial_results) and all(
        candidate_results[index] == serial_results[index] for index in range(repetitions)
    )
    repeatable = (
        bool(serial_results)
        and len({json.dumps(run, sort_keys=True) for run in serial_results}) == 1
        and len({json.dumps(run, sort_keys=True) for run in candidate_results}) == 1
    )
    collection_evidence_valid = all(
        manifest_valid[lane][index]
        and len(collections[lane][index]) == len(results[lane][index])
        for lane in ("full_serial", "candidate_combined")
        for index in range(repetitions)
    ) and all(
        manifest_valid[lane][index]
        and collections["candidate_safe"][index]
        and collections["candidate_unsafe"][index]
        and not set(collections["candidate_safe"][index]).intersection(collections["candidate_unsafe"][index])
        and set(collections["candidate_safe"][index]).union(collections["candidate_unsafe"][index])
        == set(collections["full_serial"][index])
        for index in range(repetitions)
        for lane in ("candidate_safe", "candidate_unsafe")
    )
    lane_reports = {
        lane: _lane_record(
            collections[lane],
            results[lane],
            collection_exit_codes[lane],
            exit_codes[lane],
            junit_present[lane],
            durations[lane],
        )
        for lane in lanes
    }
    all_codes_zero = all(
        code == 0
        for lane in lanes
        for code in (*collection_exit_codes[lane], *exit_codes[lane])
    )
    all_junit_present = all(flag for lane in lanes for flag in junit_present[lane])
    return {
        "schema_version": "pytest-parallel-pilot.v2",
        "mode": "report_only",
        "authority": "serial_release_gate",
        "workers": 4,
        "repetitions": repetitions,
        "sample_count": repetitions,
        "strategy": "full_serial_vs_two_phase_xdist",
        "phase_order": ["safe", "unsafe"],
        "selectors": {
            "full_serial": [],
            "safe": ["-m", "not serial"],
            "unsafe": ["-m", "serial"],
        },
        "run_order": run_order,
        "platform": os.getenv("ETF_COCKPIT_PLATFORM", platform.system().lower()),
        "unsafe_groups": _UNSAFE_GROUPS,
        "collection_parity": collection_parity,
        "collection_evidence_valid": collection_evidence_valid,
        "result_parity": result_parity,
        "repeatable_results": repeatable,
        "repeatable_collections": repeatable_collections,
        "manifest_valid": manifest_valid,
        "lanes": lane_reports,
        "lane_counts": {
            lane: {"collection": lane_reports[lane]["collection_counts"], "results": lane_reports[lane]["result_counts"]}
            for lane in lanes
        },
        "lane_codes": {
            lane: {"collection": lane_reports[lane]["collection_exit_codes"], "tests": lane_reports[lane]["exit_codes"]}
            for lane in lanes
        },
        "lane_fingerprints": {
            lane: {
                "collection": lane_reports[lane]["collection_fingerprints"],
                "results": lane_reports[lane]["result_fingerprints"],
            }
            for lane in lanes
        },
        "timings": {
            **{lane: lane_reports[lane]["timings"] for lane in lanes},
            "candidate_wall": _timing_summary(candidate_wall_durations),
        },
        "cache": cache_evidence(root),
        "status": "passed"
        if collection_parity
        and collection_evidence_valid
        and result_parity
        and repeatable
        and repeatable_collections
        and all_junit_present
        and all_codes_zero
        else "divergent",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args(argv)
    if args.repetitions < 2:
        parser.error("--repetitions must be at least 2")
    destination_dir = args.output.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    report = profile(args.root.resolve(), destination_dir, args.repetitions)
    destination = destination_dir / "parallel-pilot.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
