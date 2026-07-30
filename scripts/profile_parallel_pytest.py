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
from typing import Sequence


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
        nodeid = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
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


def cache_evidence(root: Path) -> dict[str, object]:
    lock_paths = [root / "requirements-release.txt", root / "requirements-release-parsers.txt"]
    lock_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in lock_paths
        if path.is_file()
    }
    build_tools: dict[str, str] = {}
    for name in ("build", "pip", "pytest", "pytest-xdist"):
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
        "key_sha256": hashlib.sha256(encoded).hexdigest(),
        "inputs": inputs,
        "setup_python_cache_hit": os.getenv("ETF_COCKPIT_SETUP_PYTHON_CACHE_HIT", "unknown"),
    }


def profile(root: Path, output: Path, repetitions: int) -> dict[str, object]:
    if repetitions < 2:
        raise ValueError("repetitions must be at least 2")
    output.mkdir(parents=True, exist_ok=True)
    modes = {
        "serial": [],
        "parallel": ["-n", "4", "--dist", "loadgroup"],
    }
    collections: dict[str, list[list[str]]] = {name: [] for name in modes}
    results: dict[str, list[dict[str, str]]] = {name: [] for name in modes}
    durations: dict[str, list[float]] = {name: [] for name in modes}
    exit_codes: dict[str, list[int]] = {name: [] for name in modes}
    collection_exit_codes: dict[str, list[int]] = {name: [] for name in modes}
    junit_present: dict[str, list[bool]] = {name: [] for name in modes}
    run_order: list[list[str]] = []

    for repetition in range(repetitions):
        order = ["serial", "parallel"] if repetition % 2 == 0 else ["parallel", "serial"]
        run_order.append(order)
        for mode in order:
            mode_args = modes[mode]
            collection, _ = _run(
                root, [sys.executable, "-m", "pytest", *mode_args, "--collect-only", "-q"]
            )
            stem = f"{mode}-{repetition + 1}"
            _write_diagnostics(output, f"collection-{stem}", collection)
            collection_exit_codes[mode].append(collection.returncode)
            collections[mode].append(_collection_nodeids(collection.stdout))
            junit = output / f"junit-{mode}-{repetition + 1}.xml"
            completed, duration = _run(
                root,
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *mode_args,
                    "-q",
                    "--durations=100",
                    "--durations-min=0.25",
                    f"--junitxml={junit}",
                ],
            )
            _write_diagnostics(output, f"tests-{stem}", completed)
            durations[mode].append(round(duration, 3))
            exit_codes[mode].append(completed.returncode)
            present = junit.is_file()
            junit_present[mode].append(present)
            results[mode].append(_junit_results(junit) if present else {})

    serial_collection = collections["serial"][0]
    serial_results = results["serial"][0]
    collection_parity = all(
        nodeids == serial_collection for mode_runs in collections.values() for nodeids in mode_runs
    )
    result_parity = all(
        run_results == serial_results for mode_runs in results.values() for run_results in mode_runs
    )
    repeatable = all(len({json.dumps(run, sort_keys=True) for run in mode_runs}) == 1 for mode_runs in results.values())
    collection_fingerprints = {
        mode: [_fingerprint(nodeids) for nodeids in runs]
        for mode, runs in collections.items()
    }
    result_fingerprints = {
        mode: [_fingerprint(run_results) for run_results in runs]
        for mode, runs in results.items()
    }
    collection_counts = {
        mode: [_collection_count(run) for run in runs]
        for mode, runs in collections.items()
    }
    result_counts = {mode: [len(run) for run in runs] for mode, runs in results.items()}
    timings = {
        mode: {
            "samples_seconds": samples,
            "p50_seconds": round(_percentile(samples, 0.50), 3),
            "p95_seconds": round(_percentile(samples, 0.95), 3),
        }
        for mode, samples in durations.items()
    }
    return {
        "schema_version": "pytest-parallel-pilot.v1",
        "mode": "report_only",
        "authority": "serial_release_gate",
        "workers": 4,
        "repetitions": repetitions,
        "sample_count": repetitions,
        "sample_counts": {mode: len(runs) for mode, runs in collections.items()},
        "run_order": run_order,
        "platform": os.getenv("ETF_COCKPIT_PLATFORM", platform.system().lower()),
        "unsafe_groups": ["concurrency", "environment", "flet", "package", "ports", "sqlite"],
        "collection_parity": collection_parity,
        "result_parity": result_parity,
        "repeatable_results": repeatable,
        "collection_fingerprints": collection_fingerprints,
        "collection_counts": collection_counts,
        "result_fingerprints": result_fingerprints,
        "result_counts": result_counts,
        "junit_present": junit_present,
        "collection_exit_codes": collection_exit_codes,
        "exit_codes": exit_codes,
        "timings": timings,
        "cache": cache_evidence(root),
        "status": "passed"
        if collection_parity
        and result_parity
        and repeatable
        and all(all(present for present in flags) for flags in junit_present.values())
        and all(not any(codes) for codes in collection_exit_codes.values())
        and all(not any(codes) for codes in exit_codes.values())
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
