"""Run the protected, reproducible release gate and write closure evidence.

The gate is deliberately local-first.  It runs the repository test command,
builds the Windows package, smoke-tests the built source package, creates a
CycloneDX SBOM and signs the resulting manifest with a key supplied by the
protected environment.  Every mandatory failure is retained in the report and
causes a non-zero exit code.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import hmac
import importlib.metadata
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "1.0"
DEFAULT_POLICY = Path("configs/release_policy.yaml")
DEFAULT_OUTPUT = Path("artifacts/release/latest")
SIGNING_KEY_ENV = "ETF_COCKPIT_RELEASE_SIGNING_KEY"
SIGNING_KEY_ID_ENV = "ETF_COCKPIT_RELEASE_SIGNING_KEY_ID"
XDIST_WORKERS_ENV = "ETF_COCKPIT_XDIST_WORKERS"
XDIST_MAX_ENV = "ETF_COCKPIT_XDIST_MAX"
_FULL_TEST_EVIDENCE_PREFIX = "Two-phase xdist evidence: "
TEXT_SUFFIXES = frozenset(
    {
        ".bat",
        ".cfg",
        ".csv",
        ".json",
        ".md",
        ".ps1",
        ".py",
        ".pyi",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    required: bool
    command: str = ""
    exit_code: int | None = None
    duration_ms: float = 0.0
    output: str = ""
    failure: str = ""


@dataclass(frozen=True)
class GateResult:
    exit_code: int
    output_dir: Path
    manifest_path: Path
    report_path: Path
    checks: tuple[CheckResult, ...]


@dataclass
class GateState:
    checks: list[CheckResult] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        if result.required and result.status != "passed":
            self.failures.append(f"{result.name}: {result.failure or result.output or result.status}")


@dataclass(frozen=True)
class PreparedPackage:
    root: Path
    layout: str
    smoke_script: Path | None


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalised_file_bytes(path: Path) -> bytes:
    payload = path.read_bytes()
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return payload
    return payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _tracked_paths(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    except (OSError, subprocess.CalledProcessError):
        return []
    return [root / item for item in output.decode("utf-8").split("\0") if item]


def _excluded(relative: Path, *, output_dir: Path | None = None) -> bool:
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return True
    if output_dir is not None:
        try:
            relative.relative_to(output_dir)
            return True
        except ValueError:
            pass
    return relative.parts[:1] == ("artifacts",) and relative.parts[1:2] == ("release",)


def build_source_manifest(root: Path, *, output_dir: Path | None = None) -> dict[str, object]:
    """Return a deterministic manifest of tracked source files.

    Text files are hashed after CRLF/CR normalisation, while binary artefacts
    retain their exact bytes.  This keeps the release identity stable on
    Windows and Unix without weakening binary integrity checks.
    """

    paths = _tracked_paths(root)
    if not paths:
        paths = [path for path in root.rglob("*") if path.is_file()]
    files: list[dict[str, object]] = []
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _excluded(relative, output_dir=output_dir):
            continue
        payload = normalised_file_bytes(path)
        files.append(
            {
                "path": relative.as_posix(),
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "normalisation": "UTF-8 text CRLF/CR to LF; binary bytes unchanged",
        "files": files,
    }
    manifest["manifest_sha256"] = sha256_bytes(canonical_json(manifest))
    return manifest


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_snapshot(root: Path) -> dict[str, object]:
    status_lines = _git(root, "status", "--porcelain", "--untracked-files=all").splitlines()
    generated_release_prefix = "artifacts/release/"
    dirty_paths = [
        line
        for line in status_lines
        if not line[3:].replace("\\", "/").startswith(generated_release_prefix)
    ]
    return {
        "branch": _git(root, "branch", "--show-current"),
        "head": _git(root, "rev-parse", "HEAD"),
        "origin_main": _git(root, "rev-parse", "origin/main"),
        "dirty": bool(dirty_paths),
        "dirty_paths": dirty_paths,
    }


def load_policy(root: Path) -> dict[str, object]:
    path = root / DEFAULT_POLICY
    try:
        import yaml  # type: ignore[import-untyped]

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError(f"Could not load release policy {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Release policy must be an object: {path}")
    return value


def _lock_requirements(root: Path, relative: str) -> list[tuple[str, str]]:
    path = root / relative
    if not path.exists():
        raise FileNotFoundError(f"dependency lock is missing: {path}")
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9][A-Za-z0-9_.+-]*)",
            line,
        )
        if not match:
            raise ValueError(f"dependency lock contains a non-exact entry: {raw!r}")
        rows.append((match.group(1), match.group(2)))
    if not rows:
        raise ValueError(f"dependency lock is empty: {path}")
    return rows


def dependency_snapshot(root: Path, policy: dict[str, object]) -> dict[str, object]:
    lock_paths = [str(policy.get("dependency_lock", "requirements-release.txt"))]
    parser_lock = policy.get("parser_dependency_lock")
    if parser_lock:
        lock_paths.append(str(parser_lock))
    requirements: list[tuple[str, str, str]] = []
    for lock_path in lock_paths:
        requirements.extend((lock_path, name, version) for name, version in _lock_requirements(root, lock_path))
    installed: dict[str, str] = {}
    missing: list[str] = []
    mismatched: list[str] = []
    for _lock_path, name, expected in requirements:
        key = name.lower().replace("_", "-")
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
            continue
        installed[key] = actual
        if actual != expected:
            mismatched.append(f"{name}: expected {expected}, installed {actual}")
    payload: dict[str, object] = {
        "lock_path": lock_paths[0],
        "lock_sha256": sha256_bytes((root / lock_paths[0]).read_bytes()),
        "lock_files": [
            {"path": lock_path, "sha256": sha256_bytes((root / lock_path).read_bytes())}
            for lock_path in lock_paths
        ],
        "required": [{"lock_path": lock_path, "name": name, "version": version} for lock_path, name, version in requirements],
        "installed": dict(sorted(installed.items())),
        "missing": sorted(missing),
        "mismatched": sorted(mismatched),
        "profiles": {
            "release": {
                "required": True,
                "lock_path": lock_paths[0],
                "packages": sorted(
                    name for lock_path, name, _version in requirements if lock_path == lock_paths[0]
                ),
            },
            "parsers": {
                "required": bool(parser_lock),
                "status": "required" if parser_lock else "unavailable",
                "lock_path": str(parser_lock) if parser_lock else None,
                "packages": sorted(
                    name for lock_path, name, _version in requirements if parser_lock and lock_path == str(parser_lock)
                ),
            },
        },
    }
    return payload


_REQUIRED_RELEASE_TOOLS = (
    "exchange-calendars",
    "flet",
    "hypothesis",
    "mypy",
    "pytest",
    "ruff",
)


def parallel_pilot_evidence() -> dict[str, object]:
    """Describe the non-authoritative xdist pilot without executing it."""

    try:
        version = importlib.metadata.version("pytest-xdist")
    except importlib.metadata.PackageNotFoundError:
        version = None
    return {
        "schema_version": "pytest-parallel-pilot.v2",
        "mode": "report_only",
        "authority": "serial",
        "strategy": "full_serial_vs_two_phase_xdist",
        "phase_order": ["safe", "unsafe"],
        "selectors": {
            "full_serial": [],
            "safe": ["-m", "not serial"],
            "unsafe": ["-m", "serial"],
        },
        "available": version is not None,
        "status": "available" if version is not None else "unavailable",
        "version": version,
        "workers": 4,
        "commands": {
            "serial_collection": "python -m pytest --collect-only -q",
            "candidate_safe_collection": "python -m pytest -m \"not serial\" --collect-only -q",
            "candidate_unsafe_collection": "python -m pytest -m serial --collect-only -q",
            "candidate_safe_execution": "python -m pytest -m \"not serial\" -n 4 --dist loadfile -q",
            "candidate_unsafe_execution": "python -m pytest -m serial -q",
        },
        "collection_parity": {
            "required": True,
            "comparison": "ordered_nodeids",
            "status": "not_run",
        },
        "serial_groups": ["concurrency", "environment", "flet", "package", "ports", "sqlite"],
    }


def environment_check(root: Path, policy: dict[str, object], *, allow_dirty: bool) -> CheckResult:
    started = time.perf_counter()
    expected_python = str(policy.get("python_version", "3.12.10"))
    actual_python = platform.python_version()
    messages: list[str] = []
    if actual_python != expected_python:
        messages.append(f"python {actual_python} does not match pinned {expected_python}")
    snapshot = dependency_snapshot(root, policy)
    required = snapshot.get("required", [])
    required_names = {
        str(row["name"]).lower().replace("_", "-")
        for row in required
        if isinstance(row, dict) and "name" in row
    } if isinstance(required, list) else set()
    absent_from_lock = sorted(set(_REQUIRED_RELEASE_TOOLS) - required_names)
    if absent_from_lock:
        messages.append("required tooling absent from lock profile: " + ", ".join(absent_from_lock))
    missing = snapshot.get("missing", [])
    mismatched = snapshot.get("mismatched", [])
    if isinstance(missing, list) and missing:
        messages.append("missing locked packages: " + ", ".join(str(value) for value in missing))
    if isinstance(mismatched, list) and mismatched:
        messages.extend(str(value) for value in mismatched)
    dirty = bool(git_snapshot(root)["dirty"])
    if dirty and not allow_dirty:
        messages.append("working tree is dirty")
    return CheckResult(
        name="pinned_environment",
        status="passed" if not messages else "failed",
        required=True,
        command=f"python=={expected_python}; lock={snapshot['lock_path']}",
        exit_code=0 if not messages else 1,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        output=json.dumps(snapshot, sort_keys=True),
        failure="; ".join(messages),
    )


def environment_evidence(root: Path, policy: dict[str, object]) -> dict[str, object]:
    """Return a stable platform and dependency fingerprint plus CI run evidence."""

    dependencies = dependency_snapshot(root, policy)
    fingerprint_input = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "lock_files": dependencies["lock_files"],
        "installed": dependencies["installed"],
    }
    return {
        **fingerprint_input,
        "fingerprint_sha256": sha256_bytes(canonical_json(fingerprint_input)),
        "cache": {
            "pip_cache_dir": os.getenv("PIP_CACHE_DIR", ""),
            "setup_python_cache_hit": os.getenv("ETF_COCKPIT_SETUP_PYTHON_CACHE_HIT", "unknown"),
        },
        "retry": {
            "provider": "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local",
            "run_attempt": int(os.getenv("GITHUB_RUN_ATTEMPT", "1")),
            "automatic_test_retries": 0,
        },
        "parallel_pilot": parallel_pilot_evidence(),
    }


def _command_text(command: Iterable[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def run_command(
    root: Path,
    output_dir: Path,
    name: str,
    command: tuple[str, ...],
    *,
    required: bool = True,
) -> CheckResult:
    started = time.perf_counter()
    timeout_seconds = 3600 if name == "full_tests" or name.startswith("full_tests_") else 1800
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        output = (completed.stdout + completed.stderr).strip()
        (output_dir / f"{name}.log").write_text(output + ("\n" if output else ""), encoding="utf-8", newline="\n")
        return CheckResult(
            name=name,
            status="passed" if completed.returncode == 0 else "failed",
            required=required,
            command=_command_text(command),
            exit_code=completed.returncode,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            output=output[-4000:],
            failure="" if completed.returncode == 0 else f"exit code {completed.returncode}",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = str(exc)
        return CheckResult(
            name=name,
            status="failed",
            required=required,
            command=_command_text(command),
            exit_code=124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            failure=message,
        )


def _python_command(root: Path, *args: str) -> tuple[str, ...]:
    return (sys.executable, *args)


def _junit_path(output_dir: Path | str, filename: str) -> str:
    if isinstance(output_dir, Path):
        return str(output_dir / filename)
    return f"{output_dir.rstrip('/')}/{filename}"


def _full_test_commands(
    root: Path,
    output_dir: Path | str,
    xdist_workers: int,
    *,
    targets: tuple[str, ...] = (),
    parallel_junit: str = "junit-parallel.xml",
    serial_junit: str = "junit-serial.xml",
) -> tuple[tuple[str, ...], ...]:
    """Build the pytest command(s); ``targets`` and the xdist junit names let preflight reuse the phases."""

    if xdist_workers < 0:
        raise ValueError("xdist worker count must be zero or greater")
    pytest = _python_command(root, "-m", "pytest")
    if xdist_workers == 0:
        return (
            pytest
            + (
                "-q",
                "--durations=100",
                "--durations-min=0.25",
                f"--junitxml={_junit_path(output_dir, 'junit-full.xml')}",
            ),
        )
    common = ("-q", "--durations=100", "--durations-min=0.25")
    return (
        pytest
        + (
            "-m",
            "not serial",
            "-n",
            str(xdist_workers),
            "--dist",
            "worksteal",
            *common,
            f"--junitxml={_junit_path(output_dir, parallel_junit)}",
            *targets,
        ),
        pytest
        + (
            "-m",
            "serial",
            *common,
            f"--junitxml={_junit_path(output_dir, serial_junit)}",
            *targets,
        ),
    )


def _nodeids_from_collection(output: str) -> set[str]:
    nodeids: set[str] = set()
    for line in output.splitlines():
        nodeid = line.strip().replace("\\", "/")
        if nodeid.startswith("tests/") and "::" in nodeid:
            nodeids.add(nodeid)
    return nodeids


_PYTEST_NO_TESTS_COLLECTED = 5


def _collect_test_nodeids(
    root: Path, command: tuple[str, ...], *, allow_empty: bool = False
) -> tuple[set[str], float, str]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2400,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return set(), round((time.perf_counter() - started) * 1000, 3), str(exc)
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    output = completed.stdout + completed.stderr
    if allow_empty and completed.returncode == _PYTEST_NO_TESTS_COLLECTED:
        # A CI shard may hold no tests of one phase (e.g. no serial tests); parity still checks the union.
        return set(), elapsed, ""
    if completed.returncode != 0:
        detail = output.strip()[-1000:]
        return set(), elapsed, f"exit code {completed.returncode}" + (f": {detail}" if detail else "")
    nodeids = _nodeids_from_collection(completed.stdout)
    if not nodeids:
        return set(), elapsed, "collection produced no parseable tests node ids"
    return nodeids, elapsed, ""


def _junit_key(nodeid: str) -> tuple[str, str]:
    """Map a collected nodeid to pytest's JUnit (classname, name) identity."""

    nodeid = nodeid.replace("\\", "/")
    bracket = nodeid.find("[")
    base, parameters = (nodeid, "") if bracket < 0 else (nodeid[:bracket], nodeid[bracket:])
    parts = base.split("::")  # parameter ids may themselves contain "::"
    parts[-1] += parameters
    module = parts[0][:-3] if parts[0].endswith(".py") else parts[0]
    return ".".join([module.replace("/", "."), *parts[1:-1]]), parts[-1]


def _junit_execution_problems(reports: tuple[Path, ...], expected_nodeids: set[str]) -> list[str]:
    """Every collected test must appear exactly once across the phase reports."""

    executed: dict[tuple[str, str], int] = {}
    for report in reports:
        for case in ET.parse(report).getroot().iter("testcase"):
            error = case.find("error")
            if error is not None and (error.get("message") or "").startswith("failed on teardown"):
                continue  # pytest adds a second entry for a teardown error of an executed test
            # Same normalisation as _nodeids_from_collection, which maps every backslash to "/".
            key = (case.get("classname", "").replace("\\", "/"), case.get("name", "").replace("\\", "/"))
            executed[key] = executed.get(key, 0) + 1
    expected = {_junit_key(nodeid) for nodeid in expected_nodeids}
    missing = sorted(expected - executed.keys())
    unexpected = sorted(executed.keys() - expected)
    duplicated = sorted(key for key, count in executed.items() if count > 1)
    problems = []
    for label, keys in (("not executed", missing), ("not collected", unexpected), ("executed more than once", duplicated)):
        if keys:
            problems.append(f"{len(keys)} test(s) {label}: " + ", ".join("::".join(key) for key in keys[:3]))
    return problems


def _empty_phase(output_dir: Path, name: str, command: tuple[str, ...], junit_name: str) -> CheckResult:
    """A phase with no collected tests (possible in a CI shard): recorded, not executed."""

    (output_dir / junit_name).write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="0" failures="0" '
        'errors="0" skipped="0" /></testsuites>\n',
        encoding="utf-8",
    )
    return CheckResult(name, "passed", True, command=_command_text(command), exit_code=0, output="no tests collected in this shard")


def _merge_junit_reports(reports: tuple[Path, Path], destination: Path) -> dict[str, int]:
    suites: list[ET.Element] = []
    for report in reports:
        root = ET.parse(report).getroot()
        if root.tag == "testsuite":
            suites.append(root)
        elif root.tag == "testsuites":
            suites.extend(child for child in root if child.tag == "testsuite")
        else:
            raise ValueError(f"unsupported JUnit root element in {report}: {root.tag}")
    if not suites:
        raise ValueError("JUnit reports contain no testsuite elements")
    counts = {
        key: sum(int(suite.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    merged = ET.Element("testsuites", {key: str(value) for key, value in counts.items()})
    for suite in suites:
        merged.append(suite)
    ET.ElementTree(merged).write(destination, encoding="utf-8", xml_declaration=True)
    return counts


def _write_full_tests_log(output_dir: Path, summary: str, phases: tuple[CheckResult, ...] = ()) -> None:
    chunks = [summary]
    for phase in phases:
        chunks.extend([f"\n{phase.name}: {phase.status} (exit {phase.exit_code})", phase.output])
    (output_dir / "full_tests.log").write_text("\n".join(chunks).strip() + "\n", encoding="utf-8", newline="\n")


def full_tests(root: Path, output_dir: Path, xdist_workers: int = 0) -> CheckResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    commands = _full_test_commands(root, output_dir, xdist_workers)
    if xdist_workers == 0:
        return run_command(root, output_dir, "full_tests", commands[0])

    started = time.perf_counter()
    collection_commands = (
        _python_command(root, "-m", "pytest", "--collect-only", "--verbosity=-1"),
        _python_command(root, "-m", "pytest", "-m", "not serial", "--collect-only", "--verbosity=-1"),
        _python_command(root, "-m", "pytest", "-m", "serial", "--collect-only", "--verbosity=-1"),
    )
    # The three collections are independent read-only subprocesses; run them concurrently.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(collection_commands)) as pool:
        collected = list(
            pool.map(
                lambda indexed: _collect_test_nodeids(root, indexed[1], allow_empty=indexed[0] > 0),
                enumerate(collection_commands),
            )
        )
    full_nodes, phase_a_nodes, phase_b_nodes = (row[0] for row in collected)
    phase_union = phase_a_nodes | phase_b_nodes
    missing = full_nodes - phase_union
    extra = phase_union - full_nodes
    overlap = phase_a_nodes & phase_b_nodes
    collection_failures = [
        f"collection {name} failed: {row[2]}"
        for name, row in zip(("full", "phase A", "phase B"), collected, strict=True)
        if row[2]
    ]
    evidence: dict[str, object] = {
        "xdist_workers": xdist_workers,
        # CI shards partition the suite by file (tests/conftest.py); parity below holds within the shard.
        "test_shard": os.environ.get("ETF_COCKPIT_TEST_SHARD") or "all",
        "collection_node_counts": {
            "full": len(full_nodes),
            "phase_a": len(phase_a_nodes),
            "phase_b": len(phase_b_nodes),
        },
        "collection_duration_ms": {
            "full": collected[0][1],
            "phase_a": collected[1][1],
            "phase_b": collected[2][1],
        },
        "collection_missing_from_phases": sorted(missing)[:5],
        "collection_extra_in_phases": sorted(extra)[:5],
        "collection_overlap": sorted(overlap)[:5],
    }
    if missing or extra or overlap:
        collection_failures.append(
            "collection parity failed: "
            f"full={len(full_nodes)}, phase A={len(phase_a_nodes)}, phase B={len(phase_b_nodes)}; "
            f"missing={len(missing)} {sorted(missing)[:3]}, "
            f"extra={len(extra)} {sorted(extra)[:3]}, "
            f"overlap={len(overlap)} {sorted(overlap)[:3]}"
        )
    if collection_failures:
        reason = "; ".join(collection_failures)
        evidence["failure"] = reason
        summary = _FULL_TEST_EVIDENCE_PREFIX + json.dumps(evidence, sort_keys=True)
        _write_full_tests_log(output_dir, summary)
        return CheckResult(
            "full_tests",
            "failed",
            True,
            command="; ".join(_command_text(command) for command in collection_commands),
            exit_code=1,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            output=summary,
            failure=reason,
        )

    phase_names = ("full_tests_parallel", "full_tests_serial")
    phases = tuple(
        run_command(root, output_dir, name, command)
        if nodes
        else _empty_phase(output_dir, name, command, junit)
        for name, command, nodes, junit in zip(
            phase_names, commands, (phase_a_nodes, phase_b_nodes), ("junit-parallel.xml", "junit-serial.xml"), strict=True
        )
    )
    evidence["phase_duration_ms"] = {"phase_a": phases[0].duration_ms, "phase_b": phases[1].duration_ms}
    evidence["phase_status"] = {"phase_a": phases[0].status, "phase_b": phases[1].status}
    evidence["phase_exit_codes"] = {"phase_a": phases[0].exit_code, "phase_b": phases[1].exit_code}
    failures = [
        f"phase {'A' if index == 0 else 'B'} failed: {phase.failure or phase.status}"
        for index, phase in enumerate(phases)
        if phase.status != "passed"
    ]
    try:
        evidence["junit_counts"] = _merge_junit_reports(
            (output_dir / "junit-parallel.xml", output_dir / "junit-serial.xml"),
            output_dir / "junit-full.xml",
        )
        execution_problems = _junit_execution_problems(
            (output_dir / "junit-parallel.xml", output_dir / "junit-serial.xml"),
            full_nodes,
        )
        evidence["execution_parity"] = execution_problems or "every collected test executed exactly once"
        failures.extend(f"execution parity failed: {problem}" for problem in execution_problems)
    except (OSError, ET.ParseError, ValueError) as exc:
        failures.append(f"JUnit merge failed: {exc}")
    if failures:
        evidence["failure"] = "; ".join(failures)
    summary = _FULL_TEST_EVIDENCE_PREFIX + json.dumps(evidence, sort_keys=True)
    _write_full_tests_log(output_dir, summary, phases)
    return CheckResult(
        "full_tests",
        "failed" if failures else "passed",
        True,
        command="; ".join(_command_text(command) for command in commands),
        exit_code=1 if failures else 0,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        output=summary,
        failure="; ".join(failures),
    )


def _usable_cpu_count() -> int:
    if hasattr(os, "sched_getaffinity"):
        return max(1, len(os.sched_getaffinity(0)))
    return max(1, os.cpu_count() or 1)


def _auto_xdist_workers() -> int:
    """One worker per usable CPU, capped by ETF_COCKPIT_XDIST_MAX (default 16); 0 (serial) on one CPU."""

    cap = _nonnegative_int(os.environ.get(XDIST_MAX_ENV, "16"))
    workers = min(_usable_cpu_count(), cap)
    return workers if workers > 1 else 0


def xdist_available() -> bool:
    """True when pytest-xdist is installed (the two-phase strategy needs it)."""

    try:
        importlib.metadata.version("pytest-xdist")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def resolve_xdist_workers() -> int:
    """The ``--xdist-workers auto`` count for a pytest run, or 0 (serial) without pytest-xdist."""

    return _auto_xdist_workers() if xdist_available() else 0


def _nonnegative_int(value: str) -> int:
    if value.strip().lower() == "auto":
        return _auto_xdist_workers()
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("xdist worker count must be an integer") from exc
    if workers < 0:
        raise argparse.ArgumentTypeError("xdist worker count must be zero or greater")
    return workers


def _free_port() -> int:
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def package_command(root: Path, *, platform_name: str | None = None) -> tuple[str, ...]:
    if (platform_name or os.name) == "nt":
        return ("cmd", "/c", "scripts\\build_windows.bat")
    return _python_command(root, "-m", "build", "--outdir", "build/python-dist")


def _artifact_paths(root: Path, policy: dict[str, object]) -> list[Path]:
    roots = policy.get("artifact_roots", ["build"])
    paths: list[Path] = []
    for value in roots if isinstance(roots, list) else ["build"]:
        candidate = root / str(value)
        if candidate.is_dir():
            paths.extend(path for path in candidate.rglob("*") if path.is_file())
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def build_artifact_manifest(root: Path, policy: dict[str, object]) -> dict[str, object]:
    files = []
    for path in _artifact_paths(root, policy):
        relative = path.relative_to(root)
        files.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_bytes(path.read_bytes()),
            }
        )
    manifest: dict[str, object] = {"schema_version": SCHEMA_VERSION, "files": files}
    manifest["manifest_sha256"] = sha256_bytes(canonical_json(manifest))
    return manifest


def _package_root(root: Path, policy: dict[str, object]) -> Path | None:
    pointer = root / "build" / "portable_outdir.txt"
    if pointer.is_file():
        raw = pointer.read_text(encoding="utf-8").strip()
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else root / candidate
        candidate = candidate.resolve()
        build_root = (root / "build").resolve()
        if candidate.is_relative_to(build_root) and (candidate / "app" / "src").is_dir() and (candidate / "scripts" / "smoke_app.py").is_file():
            return candidate
    for path in reversed(_artifact_paths(root, policy)):
        if path.name != "smoke_app.py" or path.parent.name != "scripts":
            continue
        candidate = path.parent.parent
        if (candidate / "src").exists() or (candidate / "app" / "src").exists():
            return candidate
    return None


def _safe_extract_archive(artifact: Path, destination: Path) -> None:
    destination = destination.resolve()
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            zip_members = archive.infolist()
            for zip_member in zip_members:
                target = (destination / zip_member.filename).resolve()
                if not target.is_relative_to(destination):
                    raise ValueError(f"archive member escapes extraction root: {zip_member.filename}")
            archive.extractall(destination)
        return
    with tarfile.open(artifact, "r:*") as archive:
        tar_members = archive.getmembers()
        for tar_member in tar_members:
            target = (destination / tar_member.name).resolve()
            if not target.is_relative_to(destination) or tar_member.issym() or tar_member.islnk():
                raise ValueError(f"unsafe archive member: {tar_member.name}")
        archive.extractall(destination, members=tar_members, filter="data")


def prepare_package_artifact(
    root: Path,
    policy: dict[str, object],
    extraction_root: Path,
    *,
    platform_name: str | None = None,
) -> PreparedPackage | None:
    platform_value = platform_name or os.name
    if platform_value == "nt":
        portable = _package_root(root, policy)
        return (
            PreparedPackage(portable, "windows-portable", portable / "scripts" / "smoke_app.py")
            if portable is not None
            else None
        )
    archives = [
        path for path in _artifact_paths(root, policy)
        if path.name.endswith(".tar.gz") or path.suffix == ".whl"
    ]
    sdists = [path for path in archives if path.name.endswith(".tar.gz")]
    selected = sdists[-1] if sdists else archives[-1] if archives else None
    if selected is None:
        return None
    destination = extraction_root / "package"
    destination.mkdir(parents=True, exist_ok=True)
    _safe_extract_archive(selected, destination)
    if selected.name.endswith(".tar.gz"):
        roots = [path for path in destination.iterdir() if path.is_dir()]
        package_root = roots[0] if len(roots) == 1 else destination
        script = package_root / "scripts" / "smoke_app.py"
        return PreparedPackage(package_root, "sdist", script if script.is_file() else None)
    return PreparedPackage(destination, "wheel", None)


def _parity_mappings(package: PreparedPackage) -> tuple[tuple[Path, Path], ...]:
    if package.layout == "windows-portable":
        return ((Path("src"), Path("app/src")), (Path("configs"), Path("configs")))
    if package.layout == "sdist":
        return ((Path("src"), Path("src")), (Path("configs"), Path("configs")))
    if package.layout == "wheel":
        return ((Path("src/etf_cockpit"), Path("etf_cockpit")), (Path("configs"), Path("configs")))
    return ()


def source_package_parity(root: Path, package: PreparedPackage | None) -> CheckResult:
    """Compare source with the actual supported artifact layout."""
    if package is None:
        return CheckResult(
            "source_package_parity",
            "failed",
            True,
            failure="no supported packaged artifact was found",
        )
    mismatches: list[str] = []
    compared = 0
    for source_relative, packaged_relative in _parity_mappings(package):
        source = root / source_relative
        packaged = package.root / packaged_relative
        if not source.exists() or not packaged.exists():
            mismatches.append(f"{source_relative.as_posix()}->{packaged_relative.as_posix()} missing")
            continue
        source_paths = [source] if source.is_file() else sorted(
            path for path in source.rglob("*")
            if path.is_file() and not _excluded(path.relative_to(root))
        )
        for source_path in source_paths:
            child = source_path.relative_to(source) if source.is_dir() else Path()
            packaged_path = packaged / child if source.is_dir() else packaged
            compared += 1
            if not packaged_path.is_file() or normalised_file_bytes(source_path) != normalised_file_bytes(packaged_path):
                mismatches.append((source_relative / child).as_posix())
    return CheckResult(
        "source_package_parity",
        "passed" if not mismatches else "failed",
        True,
        command=f"compare source with {package.layout} artifact",
        output=f"compared {compared} deterministic files in {package.layout}",
        failure="mismatched or missing: " + ", ".join(mismatches[:20]) if mismatches else "",
    )


def build_sbom(
    root: Path,
    source_manifest: dict[str, object],
    policy: dict[str, object],
    *,
    artifact_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a deterministic CycloneDX 1.5 SBOM for the release gate inputs."""

    application_properties: list[dict[str, object]] = [
        {"name": "source-manifest-sha256", "value": str(source_manifest["manifest_sha256"])},
        {"name": "local-first", "value": "true"},
    ]
    components: list[dict[str, object]] = [
        {
            "type": "application",
            "name": "etf-ai-cockpit",
            "version": _project_version(root),
            "bom-ref": "etf-ai-cockpit",
            "properties": application_properties,
        }
    ]
    if artifact_manifest is not None:
        artifact_files = artifact_manifest.get("files", [])
        application_properties.extend(
            [
                {"name": "artifact-manifest-sha256", "value": str(artifact_manifest["manifest_sha256"])},
                {"name": "artifact-file-count", "value": str(len(artifact_files) if isinstance(artifact_files, list) else 0)},
            ]
        )
    lock_paths = [str(policy.get("dependency_lock", "requirements-release.txt"))]
    parser_lock = policy.get("parser_dependency_lock")
    if parser_lock:
        lock_paths.append(str(parser_lock))
    for lock_path in lock_paths:
        try:
            required = _lock_requirements(root, lock_path)
        except (FileNotFoundError, ValueError):
            required = []
        for name, expected in required:
            try:
                installed = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                installed = None
            properties: list[dict[str, str]] = [{"name": "release-lock", "value": lock_path}]
            component: dict[str, object] = {
                "type": "library",
                "name": name,
                "version": installed or expected,
                "bom-ref": f"pkg:pypi/{name.lower().replace('_', '-') }@{installed or expected}",
                "scope": "required",
                "properties": properties,
            }
            if installed != expected:
                properties.append({"name": "release-gate-status", "value": "missing-or-mismatched"})
            components.append(component)
    bom = {
        "$schema": "https://cyclonedx.org/schema/bom-1.5.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{str(source_manifest['manifest_sha256'])[:32]}",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "etf-ai-cockpit", "version": _project_version(root)}},
        "components": sorted(components, key=lambda item: str(item["bom-ref"])),
    }
    bom["bom_sha256"] = sha256_bytes(canonical_json(bom))
    return bom


def _project_version(root: Path) -> str:
    try:
        with (root / "pyproject.toml").open("rb") as handle:
            return str(tomllib.load(handle)["project"]["version"])
    except (KeyError, OSError, tomllib.TOMLDecodeError):
        return "unknown"


def sign_manifest(manifest_bytes: bytes, key: bytes, *, key_id: str) -> dict[str, object]:
    if len(key) < 16:
        raise ValueError("release signing key must contain at least 16 bytes")
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "HMAC-SHA256",
        "key_id": key_id,
        "payload_sha256": sha256_bytes(manifest_bytes),
        "signature": hmac.new(key, manifest_bytes, hashlib.sha256).hexdigest(),
    }


def verify_manifest_signature(manifest_bytes: bytes, signature: dict[str, object], key: bytes) -> bool:
    try:
        expected = sign_manifest(manifest_bytes, key, key_id=str(signature["key_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    return (
        hmac.compare_digest(str(expected["payload_sha256"]), str(signature.get("payload_sha256", "")))
        and hmac.compare_digest(str(expected["signature"]), str(signature.get("signature", "")))
    )


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json(value))


def _report_markdown(manifest: dict[str, object], state: GateState, signature: dict[str, object]) -> str:
    git = manifest.get("git")
    git_head = git.get("head", "") if isinstance(git, dict) else ""
    lines = [
        "# ETF AI Cockpit release gate",
        "",
        f"- Schema: `{manifest['schema_version']}`",
        f"- Git head: `{git_head}`",
        f"- Source manifest: `{manifest['source_manifest_sha256']}`",
        f"- Signature: `{signature.get('status', 'signed')}`",
        "",
        "## Mandatory checks",
        "",
        "| Check | Status | Exit | Duration |",
        "|---|---|---:|---:|",
    ]
    for check in state.checks:
        lines.append(f"| `{check.name}` | `{check.status}` | {check.exit_code if check.exit_code is not None else '-'} | {check.duration_ms:.3f} ms |")
    full_tests_check = next((check for check in state.checks if check.name == "full_tests"), None)
    if full_tests_check is not None and full_tests_check.output.startswith(_FULL_TEST_EVIDENCE_PREFIX):
        lines.extend(["", "## Full test execution evidence", "", f"- `{full_tests_check.output}`"])
    lines.extend(["", "## Failures", ""])
    lines.extend(f"- {failure}" for failure in state.failures) if state.failures else lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def run_gate(
    root: Path,
    *,
    output_dir: Path | None = None,
    skip_tests: bool = False,
    skip_package: bool = False,
    skip_smoke: bool = False,
    allow_unsigned: bool = False,
    allow_dirty: bool = False,
    xdist_workers: int = 0,
) -> GateResult:
    root = root.resolve()
    output = (output_dir or root / DEFAULT_OUTPUT).resolve()
    output.mkdir(parents=True, exist_ok=True)
    policy = load_policy(root)
    state = GateState()
    state.add(environment_check(root, policy, allow_dirty=allow_dirty))

    source = build_source_manifest(root, output_dir=output.relative_to(root) if output.is_relative_to(root) else None)
    source_path = output / "source-manifest.json"
    _write_json(source_path, source)

    if skip_tests:
        state.add(CheckResult("full_tests", "skipped", False, "pytest -q"))
    else:
        state.add(full_tests(root, output, xdist_workers))

    if skip_package:
        state.add(CheckResult("package_build", "skipped", False, _command_text(package_command(root))))
    else:
        state.add(run_command(root, output, "package_build", package_command(root)))

    artifacts = build_artifact_manifest(root, policy)
    _write_json(output / "artifact-manifest.json", artifacts)
    if not skip_package and not artifacts["files"]:
        state.add(CheckResult("package_artifacts", "failed", True, failure="no package artefacts were produced"))
    else:
        state.add(CheckResult("package_artifacts", "passed" if skip_package or artifacts["files"] else "failed", not skip_package))

    if skip_smoke:
        state.add(CheckResult("package_smoke", "skipped", False, "scripts/smoke_app.py --mode offline"))
    else:
        with tempfile.TemporaryDirectory(prefix="etf-cockpit-package-") as temporary:
            try:
                package = prepare_package_artifact(root, policy, Path(temporary))
            except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
                package = None
                state.add(CheckResult("package_prepare", "failed", True, failure=str(exc)))
            state.add(source_package_parity(root, package))
            if package is None or package.smoke_script is None or not package.smoke_script.is_file():
                state.add(CheckResult(
                    "package_smoke",
                    "failed",
                    True,
                    failure="supported artifact has no packaged smoke route; repository source fallback is forbidden",
                ))
            else:
                command = (
                    sys.executable,
                    str(package.smoke_script),
                    "--mode",
                    "offline",
                    "--port",
                    str(_free_port()),
                    "--timeout",
                    "30",
                )
                state.add(run_command(package.root, output, "package_smoke", command))

    if (root / "configs" / "performance_budgets.yaml").is_file():
        performance_report_dir = output / "performance"
        state.add(
            run_command(
                root,
                output,
                "performance_budgets",
                _python_command(
                    root,
                    "scripts/check_performance_budgets.py",
                    "--root",
                    str(root),
                    "--report-dir",
                    str(performance_report_dir),
                ),
            )
        )
    else:
        state.add(CheckResult("performance_budgets", "skipped", False, "no versioned performance policy present"))

    if (root / "configs" / "data_source_policy.yaml").is_file():
        source_policy_report_dir = output / "source_policy"
        state.add(
            run_command(
                root,
                output,
                "source_policy",
                _python_command(
                    root,
                    "scripts/check_source_policy.py",
                    "--root",
                    str(root),
                    "--report-dir",
                    str(source_policy_report_dir),
                ),
            )
        )
    else:
        state.add(CheckResult("source_policy", "skipped", False, "no versioned source policy present"))

    if (root / "src" / "etf_cockpit" / "data" / "bulk_cache.py").is_file():
        bulk_cache_report_dir = output / "bulk_cache"
        state.add(
            run_command(
                root,
                output,
                "bulk_cache",
                _python_command(
                    root,
                    "scripts/check_bulk_cache.py",
                    "--root",
                    str(root),
                    "--report-dir",
                    str(bulk_cache_report_dir),
                ),
            )
        )
    else:
        state.add(CheckResult("bulk_cache", "skipped", False, "no bulk cache implementation present"))

    if (root / "scripts" / "check_security_policy.py").is_file():
        security_report_dir = output / "security_policy"
        state.add(
            run_command(
                root,
                output,
                "security_policy",
                _python_command(
                    root,
                    "scripts/check_security_policy.py",
                    "--root",
                    str(root),
                    "--report-dir",
                    str(security_report_dir),
                ),
            )
        )
    else:
        state.add(CheckResult("security_policy", "skipped", False, "no versioned security policy present"))

    if (root / "scripts" / "check_privacy_backup.py").is_file():
        privacy_report_dir = output / "privacy_backup"
        state.add(
            run_command(
                root,
                output,
                "privacy_backup",
                _python_command(
                    root,
                    "scripts/check_privacy_backup.py",
                    "--root",
                    str(root),
                    "--report-dir",
                    str(privacy_report_dir),
                ),
            )
        )
    else:
        state.add(CheckResult("privacy_backup", "skipped", False, "no privacy backup validator present"))

    if (root / "scripts" / "check_legal_terms.py").is_file():
        legal_terms_report_dir = output / "legal_terms"
        state.add(
            run_command(
                root,
                output,
                "legal_terms",
                _python_command(
                    root,
                    "scripts/check_legal_terms.py",
                    "--root",
                    str(root),
                    "--report-dir",
                    str(legal_terms_report_dir),
                ),
            )
        )
    else:
        state.add(CheckResult("legal_terms", "skipped", False, "no legal terms validator present"))

    sbom = build_sbom(root, source, policy, artifact_manifest=artifacts)
    _write_json(output / "sbom.cdx.json", sbom)
    state.add(CheckResult("sbom", "passed", True, "CycloneDX 1.5 deterministic SBOM"))

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "git": git_snapshot(root),
        "python": sys.version.split()[0],
        "environment": environment_evidence(root, policy),
        "project_version": _project_version(root),
        "policy": policy,
        "source_manifest_sha256": source["manifest_sha256"],
        "artifact_manifest_sha256": artifacts["manifest_sha256"],
        "sbom_sha256": sbom["bom_sha256"],
        "checks": [asdict(check) for check in state.checks],
        "failures": list(state.failures),
        "evidence_paths": {
            "output_dir": str(output),
            "junit": str(output / "junit-full.xml"),
            "stage_logs": {
                check.name: str(output / f"{check.name}.log")
                for check in state.checks
                if (output / f"{check.name}.log").is_file()
            },
        },
    }
    manifest_path = output / "release-manifest.json"
    signing_key_text = os.getenv(str(policy.get("signing_key_env", SIGNING_KEY_ENV)), "")
    key_id = os.getenv(SIGNING_KEY_ID_ENV, "local-release-key")
    signature_path = output / "release-manifest.sig.json"
    signature: dict[str, object]
    if signing_key_text:
        state.add(CheckResult("signature", "passed", True, "HMAC-SHA256 detached release-manifest signature"))
    elif allow_unsigned:
        signature = {"schema_version": SCHEMA_VERSION, "algorithm": "HMAC-SHA256", "status": "unsigned", "reason": "no protected signing key supplied"}
        state.add(CheckResult("signature", "skipped", False, "HMAC-SHA256 detached release-manifest signature", failure="no protected signing key supplied"))
    else:
        signature = {"schema_version": SCHEMA_VERSION, "algorithm": "HMAC-SHA256", "status": "missing"}
        state.add(CheckResult("signature", "failed", True, failure=f"{SIGNING_KEY_ENV} is not set"))

    manifest["checks"] = [asdict(check) for check in state.checks]
    manifest["failures"] = list(state.failures)
    _write_json(manifest_path, manifest)
    if signing_key_text:
        signature = sign_manifest(manifest_path.read_bytes(), signing_key_text.encode("utf-8"), key_id=key_id)
        signature["status"] = "signed"
    _write_json(signature_path, signature)
    _write_json(output / "release-manifest.final.json", manifest)
    report_path = output / "release-report.md"
    report_path.write_text(_report_markdown(manifest, state, signature), encoding="utf-8", newline="\n")
    return GateResult(1 if state.failures else 0, output, manifest_path, report_path, tuple(state.checks))


def _planned_commands(root: Path) -> list[str]:
    serial_command = _full_test_commands(root, "<output>", 0)[0]
    parallel_commands = _full_test_commands(root, "<output>", 4)
    return [
        f"Serial full suite: {_command_text(serial_command)}",
        f"Two-phase xdist phase A (Linux, 4 workers after collection parity): {_command_text(parallel_commands[0])}",
        f"Two-phase xdist phase B (Linux after collection parity): {_command_text(parallel_commands[1])}",
        _command_text(package_command(root)),
        "python scripts/smoke_app.py --mode offline --port <free-port> --timeout 30",
        "python scripts/check_security_policy.py --root <root> --report-dir <output>/security_policy",
        "CycloneDX 1.5 SBOM",
        f"HMAC-SHA256 signature from ${SIGNING_KEY_ENV}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--skip-tests", action="store_true", help="diagnostic-only: do not run the full suite")
    parser.add_argument("--skip-package", action="store_true", help="diagnostic-only: do not build a package")
    parser.add_argument("--skip-smoke", action="store_true", help="diagnostic-only: do not launch the package")
    parser.add_argument("--allow-unsigned", action="store_true", help="allow unsigned pull-request evidence; never use for a release")
    parser.add_argument("--allow-dirty", action="store_true", help="allow a dirty worktree for local diagnostics")
    parser.add_argument(
        "--xdist-workers",
        type=_nonnegative_int,
        default=os.environ.get(XDIST_WORKERS_ENV, "0"),
        help=f"run the non-serial suite with pytest-xdist workers after collection parity (default: {XDIST_WORKERS_ENV} or 0)",
    )
    parser.add_argument(
        "--verify-environment",
        action="store_true",
        help="verify pinned Python and tier-required packages, then exit before tests",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the protected gate without executing it")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.verify_environment:
        try:
            policy = load_policy(root)
            check = environment_check(root, policy, allow_dirty=args.allow_dirty)
            print(
                json.dumps(
                    {
                        "check": asdict(check),
                        "environment": environment_evidence(root, policy),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if check.status == "passed" else 1
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "check": {
                            "name": "pinned_environment",
                            "status": "failed",
                            "required": True,
                            "exit_code": 2,
                            "failure": str(exc),
                        },
                        "environment": None,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
    if args.dry_run:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "root": str(root), "commands": _planned_commands(root)}, indent=2))
        return 0
    try:
        result = run_gate(
            root,
            output_dir=args.output,
            skip_tests=args.skip_tests,
            skip_package=args.skip_package,
            skip_smoke=args.skip_smoke,
            allow_unsigned=args.allow_unsigned,
            allow_dirty=args.allow_dirty,
            xdist_workers=args.xdist_workers,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"exit_code": result.exit_code, "output_dir": str(result.output_dir), "manifest": str(result.manifest_path), "report": str(result.report_path)}, indent=2))
    _print_failure_digest(root, result.output_dir)
    return result.exit_code


def _print_failure_digest(root: Path, output_dir: Path) -> None:
    """Print the compact failure digest (scripts/failure_digest.py); presentation only, never the verdict."""

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("failure_digest", Path(__file__).with_name("failure_digest.py"))
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        # @dataclass resolves cls.__module__ through sys.modules, so the module must be registered before exec.
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(spec.name, None)
            raise
        print("\n--- failure digest ---\n" + module.render([output_dir], root))
    except Exception as exc:  # noqa: BLE001 - the digest must never change the gate outcome
        print(f"failure digest unavailable: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
