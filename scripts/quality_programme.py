"""Run the bounded local quality programme and write release evidence.

The first quality slice is intentionally hermetic and local-first.  It covers
source-level user journeys, UI contracts, performance budgets, recovery and
deterministic fault handling.  Packaged browser baselines, long-duration soak
runs and live-broker chaos remain explicit hardening scope.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


SCHEMA_VERSION = "quality-programme.v1"
DEFAULT_OUTPUT = Path("artifacts/quality/latest")
DEFAULT_TIMEOUT_SECONDS = 300
OUTPUT_LIMIT = 4000
SECRET_RE = re.compile(
    r"(?i)(api[_ -]?key|secret(?:[_ -]?key)?|password|token|authorization)\s*[:=]\s*[^\s,;]+"
)


@dataclass(frozen=True)
class Suite:
    suite_id: str
    title: str
    paths: tuple[str, ...]
    required: bool = True


SUITES: tuple[Suite, ...] = (
    Suite(
        "visual_e2e",
        "Deterministic source workflow and UI contracts",
        ("tests/test_e2e_workflow.py", "tests/test_frontend_design_system.py", "tests/test_accessibility_contracts.py"),
    ),
    Suite(
        "load",
        "Local performance budgets and bounded dataset measurements",
        ("tests/test_performance_budgets.py", "tests/test_performance_contracts.py"),
    ),
    Suite(
        "soak",
        "Bounded workflow, event and recovery repetition",
        ("tests/test_workflow_runtime.py", "tests/operations/test_event_store.py", "tests/operations/test_recovery.py"),
    ),
    Suite(
        "fault_injection",
        "Provider, parser, file and state failure handling",
        ("tests/test_error_recovery.py", "tests/operations/test_transactions.py"),
    ),
    Suite(
        "chaos_sandbox",
        "Fail-closed local sandbox and safety-boundary checks",
        ("tests/operations/test_recovery.py", "tests/scope_boundary/test_execution_boundary.py"),
    ),
)


@dataclass(frozen=True)
class SuiteResult:
    suite_id: str
    title: str
    command: str
    status: str
    required: bool
    exit_code: int
    duration_ms: float
    output: str = ""
    failure: str = ""


@dataclass
class QualityReport:
    schema_version: str
    generated_at: str
    status: str
    duration_ms: float
    suites: list[dict[str, object]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    scope: dict[str, object] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    environment: dict[str, object] = field(default_factory=dict)
    report_paths: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class QualityRun:
    report: QualityReport
    json_path: Path
    markdown_path: Path
    exit_code: int


Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_programme(
    root: Path,
    *,
    output_dir: Path | None = None,
    suite_ids: Iterable[str] = (),
    runner: Runner = subprocess.run,
    python: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> QualityRun:
    """Run selected quality suites and persist JSON and Markdown evidence."""

    root = Path(root).resolve()
    destination = (output_dir or root / DEFAULT_OUTPUT).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    selected_ids = tuple(str(value).strip() for value in suite_ids if str(value).strip())
    known = {suite.suite_id: suite for suite in SUITES}
    unknown = sorted(set(selected_ids) - set(known))
    if unknown:
        raise ValueError(f"unknown quality suite(s): {', '.join(unknown)}")
    selected = tuple(known[value] for value in selected_ids) if selected_ids else SUITES
    python_executable = python or sys.executable
    started = time.perf_counter()
    results = [
        _run_suite(root, suite, python_executable, runner=runner, timeout_seconds=timeout_seconds)
        for suite in selected
    ]
    failures = [
        f"{result.suite_id}: {result.failure or result.output or 'suite failed'}"
        for result in results
        if result.required and result.status != "passed"
    ]
    finished = _utc_now()
    json_path = destination / "quality-programme.json"
    markdown_path = destination / "quality-programme.md"
    report = QualityReport(
        schema_version=SCHEMA_VERSION,
        generated_at=finished,
        status="failed" if failures else "passed",
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        suites=[asdict(result) for result in results],
        failures=failures,
        scope={
            "mode": "bounded_local_first",
            "suite_ids": [suite.suite_id for suite in selected],
            "network_calls": False,
            "live_orders": False,
        },
        limitations=[
            "Packaged browser journeys and reviewed visual baselines remain hardening_required.",
            "Soak coverage is bounded by deterministic fixtures; long-duration memory and file-descriptor runs remain hardening_required.",
            "Fault injection is local and sandboxed; live broker, network and infrastructure chaos are not enabled.",
        ],
        environment={
            "python": platform.python_version(),
            "platform": platform.platform(),
            "root": str(root),
        },
        report_paths={
            "json": _report_path(root, json_path),
            "markdown": _report_path(root, markdown_path),
        },
    )
    json_path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    markdown_path.write_text(_markdown(report), encoding="utf-8", newline="\n")
    return QualityRun(report, json_path, markdown_path, 1 if failures else 0)


def _run_suite(
    root: Path,
    suite: Suite,
    python: str,
    *,
    runner: Runner,
    timeout_seconds: int,
) -> SuiteResult:
    command = (python, "-m", "pytest", "-q", *suite.paths)
    command_text = _display_command(command)
    started = time.perf_counter()
    try:
        completed = runner(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        output = _redact((completed.stdout + completed.stderr).strip())[-OUTPUT_LIMIT:]
        return SuiteResult(
            suite_id=suite.suite_id,
            title=suite.title,
            command=command_text,
            status="passed" if completed.returncode == 0 else "failed",
            required=suite.required,
            exit_code=int(completed.returncode),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            output=output,
            failure="" if completed.returncode == 0 else f"exit code {completed.returncode}",
        )
    except subprocess.TimeoutExpired as exc:
        return SuiteResult(
            suite_id=suite.suite_id,
            title=suite.title,
            command=command_text,
            status="failed",
            required=suite.required,
            exit_code=124,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            output=_redact(str(exc))[-OUTPUT_LIMIT:],
            failure=f"timed out after {timeout_seconds} seconds",
        )
    except OSError as exc:
        return SuiteResult(
            suite_id=suite.suite_id,
            title=suite.title,
            command=command_text,
            status="failed",
            required=suite.required,
            exit_code=127,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            output=_redact(str(exc))[-OUTPUT_LIMIT:],
            failure=str(exc),
        )


def _markdown(report: QualityReport) -> str:
    lines = [
        "# ETF AI Cockpit quality programme",
        "",
        f"- Schema: `{report.schema_version}`",
        f"- Status: `{report.status}`",
        f"- Generated: `{report.generated_at}`",
        f"- Duration: `{report.duration_ms:.3f} ms`",
        "- Network calls: `false`",
        "- Live orders: `false`",
        "",
        "## Suites",
        "",
        "| Suite | Status | Exit | Duration | Required |",
        "|---|---|---:|---:|---|",
    ]
    for suite in report.suites:
        lines.append(
            f"| `{suite['suite_id']}` | `{suite['status']}` | {suite['exit_code']} | {suite['duration_ms']} ms | {suite['required']} |"
        )
    lines.extend(["", "## Failures", ""])
    lines.extend(f"- {failure}" for failure in report.failures) if report.failures else lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.extend(["", "## Scope", "", "```json", json.dumps(report.scope, indent=2, sort_keys=True), "```", ""])
    return "\n".join(lines)


def _redact(value: str) -> str:
    return SECRET_RE.sub(lambda match: f"{match.group(1)}=***redacted***", value)


def _display_command(command: tuple[str, ...]) -> str:
    return " ".join(json.dumps(part) if any(char.isspace() for char in part) else part for part in command)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _report_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--suite", action="append", dest="suite_ids", default=[], choices=[suite.suite_id for suite in SUITES])
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("ERROR: --timeout must be greater than zero", file=sys.stderr)
        return 2
    try:
        run = run_programme(
            args.root.resolve(),
            output_dir=args.output,
            suite_ids=args.suite_ids,
            timeout_seconds=args.timeout,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(run.report.as_dict(), indent=2, sort_keys=True))
    return run.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
