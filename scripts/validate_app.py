"""Run bounded local validation checks and persist one machine-readable report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, cast


SCHEMA_VERSION = "1.0"
REPORT_DIRECTORY = Path("artifacts/validation")
OPTIONAL_COMPONENTS = ("torch", "timesfm", "toto")
MODES = ("quick", "changed", "issue", "phase", "full", "offline", "packaged")


@dataclass
class CheckResult:
    name: str
    command: str
    exit_code: int
    duration_ms: float
    status: str
    required: bool = True
    output: str = ""
    failure: str = ""


@dataclass
class ValidationReport:
    schema_version: str
    mode: str
    generated_at: str
    started_at: str
    finished_at: str
    duration_ms: float
    checks: list[dict[str, object]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    unavailable_optional_components: list[str] = field(default_factory=list)
    environment: dict[str, object] = field(default_factory=dict)
    git: dict[str, object] = field(default_factory=dict)
    log_paths: list[str] = field(default_factory=list)
    execution_evidence: dict[str, object] = field(default_factory=dict)
    scope: dict[str, object] = field(default_factory=dict)
    report_only: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationRun:
    report: ValidationReport
    report_json: Path
    report_markdown: Path
    exit_code: int


@dataclass(frozen=True)
class _Check:
    name: str
    command: tuple[str, ...]
    required: bool = True
    environment: tuple[tuple[str, str], ...] = ()
    timeout_seconds: int = 120


def run_validation(
    root: Path,
    *,
    mode: str = "quick",
    issue_ids: Iterable[str] = (),
    phase_ids: Iterable[str] = (),
    report_root: Path | None = None,
    report_only: bool = False,
) -> ValidationRun:
    """Run a local validation scope and write ``latest/validation.{json,md}`."""

    root = Path(root).resolve()
    mode = str(mode).strip().lower()
    if mode not in MODES:
        raise ValueError(f"unsupported validation mode: {mode}")
    target_root = (report_root or root / REPORT_DIRECTORY).resolve()
    latest = target_root / "latest"
    latest.mkdir(parents=True, exist_ok=True)

    started = _utc_now()
    started_clock = time.perf_counter()
    checks: list[CheckResult] = []
    failures: list[str] = []
    scope: dict[str, object] = {
        "issue_ids": sorted({str(value) for value in issue_ids if str(value).strip()}),
        "phase_ids": sorted({str(value) for value in phase_ids if str(value).strip()}),
    }

    scope_check = _validate_scope(root, mode, scope)
    if scope_check is not None:
        checks.append(scope_check)
        if scope_check.required and scope_check.status != "passed":
            failures.append(f"{scope_check.name}: {scope_check.failure or scope_check.output or 'check failed'}")

    for check in _checks_for_mode(root, mode, scope, latest):
        result = _run_check(root, check)
        checks.append(result)
        if result.required and result.status != "passed":
            failures.append(f"{result.name}: {result.failure or result.output or 'check failed'}")

    unavailable = [
        component
        for component in OPTIONAL_COMPONENTS
        if _module_available(component) is False
    ]
    finished = _utc_now()
    report = ValidationReport(
        schema_version=SCHEMA_VERSION,
        mode=mode,
        generated_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=round((time.perf_counter() - started_clock) * 1000, 3),
        checks=[asdict(check) for check in checks],
        failures=failures,
        unavailable_optional_components=unavailable,
        environment=_environment(root, offline_requested=mode == "offline"),
        git=_git_state(root),
        log_paths=_existing_log_paths(root, report_dir=latest),
        execution_evidence=_execution_evidence(),
        scope=scope,
        report_only=report_only,
    )
    report_json = latest / "validation.json"
    report_markdown = latest / "validation.md"
    report_json.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report_markdown.write_text(_markdown(report), encoding="utf-8", newline="\n")
    return ValidationRun(report, report_json, report_markdown, 1 if failures else 0)


def _checks_for_mode(
    root: Path,
    mode: str,
    scope: dict[str, object],
    report_dir: Path | None = None,
) -> list[_Check]:
    python = sys.executable
    if mode == "full":
        return [
            _Check(
                "protected_release_gate",
                (
                    python,
                    "scripts/release_gate.py",
                    "--root",
                    ".",
                    "--output",
                    "artifacts/release/latest",
                ),
                timeout_seconds=3600,
            )
        ]
    if mode == "packaged":
        return [
            _Check(
                "packaged_release_gate",
                (
                    python,
                    "scripts/release_gate.py",
                    "--root",
                    ".",
                    "--output",
                    "artifacts/release/latest",
                ),
                timeout_seconds=3600,
            )
        ]
    registry = (python, "scripts/validate_issue_registry.py")
    compile_source = (python, "-m", "compileall", "-q", "src", "scripts")
    offline_smoke = (
        python,
        "scripts/smoke_app.py",
        "--mode",
        "offline",
        "--port",
        str(_free_local_port()),
        "--timeout",
        "30",
    )
    checks = [
        _Check("issue_registry", registry),
        _Check("source_compile", compile_source),
        _Check(
            "source_smoke",
            offline_smoke,
            environment=(("ETF_COCKPIT_OFFLINE", "1"),) if mode == "offline" else (),
        ),
    ]
    if mode == "changed":
        changed_tests = _changed_test_paths(root)
        if changed_tests:
            junit = (report_dir or root / REPORT_DIRECTORY / "latest") / "junit-affected.xml"
            checks.append(
                _Check(
                    "changed_tests",
                    (
                        python,
                        "-m",
                        "pytest",
                        "-q",
                        "--durations=100",
                        "--durations-min=0.25",
                        f"--junitxml={junit}",
                        *changed_tests,
                    ),
                )
            )
        else:
            checks.append(_Check("changed_scope", (python, "-c", "print('No changed test paths detected')")))
    return checks


def _validate_scope(root: Path, mode: str, scope: dict[str, object]) -> CheckResult | None:
    if mode not in {"issue", "phase"}:
        return None
    started = time.perf_counter()
    registry_path = root / "issues" / "issue_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        records = registry.get("records", [])
        issue_ids = {str(record.get("canonical_id")) for record in records}
        phase_ids = {str(phase.get("phase")) for phase in registry.get("roadmap_phases", [])}
        selected = scope["issue_ids"] if mode == "issue" else scope["phase_ids"]
        selected_values = [str(value) for value in cast(Iterable[object], selected)]
        if not selected_values:
            raise ValueError(f"{mode} mode requires at least one --{mode} value")
        valid_values = issue_ids if mode == "issue" else phase_ids
        invalid = sorted(set(selected_values) - valid_values)
        if invalid:
            raise ValueError(f"unknown {mode} ID(s): {', '.join(invalid)}")
        output = f"Validated {mode} scope: {', '.join(selected_values)}"
        return CheckResult(
            name="scope_selection",
            command=f"registry scope {mode}",
            exit_code=0,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            status="passed",
            output=output,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return CheckResult(
            name="scope_selection",
            command=f"registry scope {mode}",
            exit_code=1,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            status="failed",
            output=str(exc),
            failure=str(exc),
        )


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_check(root: Path, check: _Check) -> CheckResult:
    command_text = _display_command(check.command)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(check.command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=check.timeout_seconds,
            check=False,
            env={**os.environ, **dict(check.environment)},
        )
        output = (completed.stdout + completed.stderr).strip()
        status = "passed" if completed.returncode == 0 else "failed"
        return CheckResult(
            name=check.name,
            command=command_text,
            exit_code=completed.returncode,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            status=status,
            required=check.required,
            output=output[-4000:],
            failure="" if completed.returncode == 0 else f"exit code {completed.returncode}",
        )
    except subprocess.TimeoutExpired as exc:
        return CheckResult(
            name=check.name,
            command=command_text,
            exit_code=124,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            status="failed",
            required=check.required,
            output=str(exc),
            failure=f"timed out after {check.timeout_seconds} seconds",
        )
    except OSError as exc:
        return CheckResult(
            name=check.name,
            command=command_text,
            exit_code=127,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            status="failed",
            required=check.required,
            output=str(exc),
            failure=str(exc),
        )


def _environment(root: Path, *, offline_requested: bool = False) -> dict[str, object]:
    fingerprint = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
    }
    return {
        **fingerprint,
        "fingerprint_sha256": hashlib.sha256(
            (json.dumps(fingerprint, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        ).hexdigest(),
        "root": str(root),
        "offline_requested": offline_requested or os.getenv("ETF_COCKPIT_OFFLINE", "") == "1",
    }


def _execution_evidence() -> dict[str, object]:
    return {
        "cache": {
            "pip_cache_dir": os.getenv("PIP_CACHE_DIR", ""),
            "setup_python_cache_hit": os.getenv("ETF_COCKPIT_SETUP_PYTHON_CACHE_HIT", "unknown"),
        },
        "retry": {
            "provider": "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local",
            "run_attempt": int(os.getenv("GITHUB_RUN_ATTEMPT", "1")),
            "automatic_test_retries": 0,
        },
    }


def _git_state(root: Path) -> dict[str, object]:
    return {
        "branch": _git(root, "branch", "--show-current"),
        "head": _git(root, "rev-parse", "HEAD"),
        "origin_main": _git(root, "rev-parse", "origin/main"),
        "dirty": bool(_git(root, "status", "--porcelain")),
    }


def _existing_log_paths(root: Path, *, report_dir: Path | None = None) -> list[str]:
    validation_latest = report_dir or root / REPORT_DIRECTORY / "latest"
    candidates = [
        *(root / "logs").glob("*.jsonl"),
        *validation_latest.glob("*.xml"),
        *validation_latest.glob("*.log"),
    ]
    paths: list[str] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            paths.append(str(path.relative_to(root)))
        except ValueError:
            paths.append(str(path.resolve()))
    return sorted(paths)


def _changed_paths(root: Path) -> list[str]:
    output = _git(root, "status", "--porcelain")
    if output:
        return [line[3:] for line in output.splitlines() if len(line) > 3]
    base = os.getenv("ETF_COCKPIT_VALIDATION_BASE_SHA", "").strip()
    head = os.getenv("ETF_COCKPIT_VALIDATION_HEAD_SHA", "").strip()
    if not base and not head:
        return []
    if not re.fullmatch(r"[0-9a-f]{40}", base) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("explicit validation base/head must both be 40-character lowercase Git SHAs")
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", base, head, "--"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"cannot resolve explicit validation base/head: {base}..{head}") from exc
    return completed.stdout.splitlines()


def _changed_test_paths(root: Path) -> list[str]:
    return sorted(
        path
        for path in _changed_paths(root)
        if path.startswith("tests/") and path.endswith(".py")
    )


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _module_available(name: str) -> bool:
    try:
        from importlib.util import find_spec

        return find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _display_command(command: tuple[str, ...]) -> str:
    return " ".join(json.dumps(part) if any(char.isspace() for char in part) else part for part in command)


def _markdown(report: ValidationReport) -> str:
    lines = [
        "# ETF AI Cockpit validation report",
        "",
        f"- Schema: `{report.schema_version}`",
        f"- Mode: `{report.mode}`",
        f"- Generated: `{report.generated_at}`",
        f"- Duration: `{report.duration_ms:.3f} ms`",
        "",
        "## Checks",
        "",
        "| Check | Status | Exit code | Duration | Required |",
        "|---|---|---:|---:|---|",
    ]
    for check in report.checks:
        lines.append(
            f"| `{check['name']}` | `{check['status']}` | {check['exit_code']} | {check['duration_ms']} ms | {check['required']} |"
        )
    lines.extend(["", "## Failures", ""])
    if report.failures:
        lines.extend(f"- {failure}" for failure in report.failures)
    else:
        lines.append("- None")
    lines.extend(["", "## Optional components unavailable", ""])
    if report.unavailable_optional_components:
        lines.extend(f"- `{name}`" for name in report.unavailable_optional_components)
    else:
        lines.append("- None")
    lines.extend(["", "## Scope", "", "```json", json.dumps(report.scope, indent=2, sort_keys=True), "```", ""])
    return "\n".join(lines)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for mode in ("quick", "changed", "full", "offline", "packaged"):
        parser.add_argument(f"--{mode}", action="store_true", help=f"run the {mode} validation scope")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="record evidence without promotion actions; mandatory failures remain non-zero",
    )
    parser.add_argument("--issue", action="append", default=[], help="scope validation to a canonical issue ID")
    parser.add_argument("--phase", action="append", default=[], help="scope validation to a roadmap phase")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def _mode_from_args(args: argparse.Namespace) -> str:
    selected = [mode for mode in MODES if getattr(args, mode.replace("-", "_"), False)]
    if len(selected) > 1:
        raise ValueError("choose only one validation mode")
    if selected:
        return selected[0]
    if args.issue:
        return "issue"
    if args.phase:
        return "phase"
    return "quick"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        mode = _mode_from_args(args)
        run = run_validation(
            args.root.resolve(),
            mode=mode,
            issue_ids=args.issue,
            phase_ids=args.phase,
            report_only=args.report_only,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(run.report.as_dict(), indent=2, sort_keys=True))
    return run.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
