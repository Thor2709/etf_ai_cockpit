from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from scripts.verify_issue import compute_environment_hash, compute_source_hash
except ModuleNotFoundError:  # direct ``python scripts/dev_finish_check.py`` execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.verify_issue import compute_environment_hash, compute_source_hash


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
EVIDENCE_POLICY_VERSION = "1.0"
BASE_GATES = ("focused", "full")
PARSER_GATES = ("fixtures", "export", "build", "browser", "computer_use")
RUNTIME_PATH_PREFIXES = (
    "src/",
    "scripts/",
    "configs/",
    "requirements",
    "pyproject.toml",
    "etf_ai_cockpit.spec",
    "*.bat",
)
SENSITIVE_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token)\b\s*([:=])\s*([^\s,;]+)"
)


class FinishGateError(ValueError):
    """Raised when a requested finish-check configuration is unsafe."""


@dataclass(frozen=True)
class GateCommand:
    gate: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class FinishGatePlan:
    changed_paths: tuple[Path, ...]
    issue_ids: tuple[str, ...]
    gates: tuple[str, ...]
    commands: tuple[GateCommand, ...]
    no_build: bool = False


@dataclass(frozen=True)
class FinishGateResult:
    gate: str
    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    status: str
    source_hash: str = ""
    environment_hash: str = ""
    evidence_policy_version: str = EVIDENCE_POLICY_VERSION


@dataclass(frozen=True)
class FinishGateReport:
    plan: FinishGatePlan
    results: tuple[FinishGateResult, ...]
    passed: bool
    generated_at: float
    source_hash: str = ""
    environment_hash: str = ""
    evidence_policy_version: str = EVIDENCE_POLICY_VERSION


def verification_metadata(
    *,
    root: Path = ROOT,
    issue_ids: Collection[str] = (),
) -> dict[str, object]:
    """Return source/environment-bound metadata for a finish-check package."""

    return {
        "source_hash": compute_source_hash(Path(root)),
        "environment_hash": compute_environment_hash(Path(root), PYTHON),
        "verification_policy_version": EVIDENCE_POLICY_VERSION,
        "issue_ids": tuple(sorted({str(issue).strip() for issue in issue_ids if str(issue).strip()})),
        "tracker_mutated": False,
    }


def select_gates(changed_paths: Collection[Path], issue_ids: Collection[str]) -> FinishGatePlan:
    """Select closure gates using path and issue rules with stable ordering."""
    paths = tuple(sorted((Path(path) for path in changed_paths), key=lambda path: _path_key(path)))
    issues = tuple(sorted({issue.strip() for issue in issue_ids if issue.strip()}))
    gates: set[str] = set(BASE_GATES)
    path_keys = {_path_key(path) for path in paths}

    if "UPDATEV2-0013" in issues or any(key.startswith("src/etf_cockpit/parsers/") for key in path_keys):
        gates.update(PARSER_GATES)
    if "UPDATEV2-0029" in issues:
        gates.update(("build", "browser", "computer_use"))
    if any(_is_runtime_or_package_path(key) for key in path_keys):
        gates.add("build")
    if any(key.startswith("src/etf_cockpit/app/") for key in path_keys):
        gates.update(("browser", "computer_use"))
    if any("export" in key or "audit" in key for key in path_keys):
        gates.add("export")

    ordered_gates = tuple(gate for gate in (*BASE_GATES, *PARSER_GATES) if gate in gates)
    return FinishGatePlan(paths, issues, ordered_gates, _commands_for(ordered_gates, paths))


def build_cli_plan(
    *, changed: Sequence[str], no_build: bool, issue_ids: Collection[str] = ()
) -> FinishGatePlan:
    plan = select_gates({Path(item) for item in changed if item.strip()}, issue_ids)
    if no_build and "build" in plan.gates:
        raise FinishGateError("--no-build is unsafe because a runtime or package path requires the build gate.")
    if not no_build:
        return plan
    gates = tuple(gate for gate in plan.gates if gate != "build")
    return FinishGatePlan(plan.changed_paths, plan.issue_ids, gates, _commands_for(gates, plan.changed_paths), no_build=True)


def run_finish_gates(plan: FinishGatePlan, evidence_dir: Path) -> FinishGateReport:
    """Run executable gates without a shell and capture redacted local evidence."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    source_hash = compute_source_hash(ROOT)
    environment_hash = compute_environment_hash(ROOT, PYTHON)
    results: list[FinishGateResult] = []
    for command in plan.commands:
        started = time.monotonic()
        completed = subprocess.run(
            list(command.argv),
            cwd=ROOT,
            env=_command_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        duration_s = time.monotonic() - started
        results.append(
            FinishGateResult(
                gate=command.gate,
                argv=command.argv,
                exit_code=completed.returncode,
                stdout=redact_text(completed.stdout),
                stderr=redact_text(completed.stderr),
                duration_s=round(duration_s, 3),
                status="passed" if completed.returncode == 0 else "failed",
                source_hash=source_hash,
                environment_hash=environment_hash,
            )
        )
    completed_gates = {result.gate for result in results}
    for gate in plan.gates:
        if gate not in completed_gates:
            results.append(
                FinishGateResult(
                    gate=gate,
                    argv=(),
                    exit_code=None,
                    stdout="",
                    stderr="",
                    duration_s=0.0,
                    status="pending_external_verification",
                    source_hash=source_hash,
                    environment_hash=environment_hash,
                )
            )
    passed = bool(results) and all(result.status == "passed" for result in results)
    return FinishGateReport(
        plan,
        tuple(results),
        passed,
        time.time(),
        source_hash=source_hash,
        environment_hash=environment_hash,
    )


def redact_text(value: str) -> str:
    return SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)


def write_json_report(report: FinishGateReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    payload["verification_policy"] = {
        "version": report.evidence_policy_version,
        "tracker_mutated": False,
        "source_hash": report.source_hash,
        "environment_hash": report.environment_hash,
    }
    payload["environment"] = {name: "[REDACTED]" for name in _command_environment() if _is_sensitive_name(name)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic ETF AI Cockpit finish gates.")
    parser.add_argument("--issues", nargs="+", default=[])
    parser.add_argument("--changed-paths-file", type=Path, required=True)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--json-report", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true", help="Write the selected gate plan without running commands.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        changed = _read_changed_paths(args.changed_paths_file)
        plan = build_cli_plan(changed=changed, no_build=args.no_build, issue_ids=_split_issue_ids(args.issues))
    except (FinishGateError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.plan_only:
        report = FinishGateReport(
            plan,
            (),
            False,
            time.time(),
            source_hash=compute_source_hash(ROOT),
            environment_hash=compute_environment_hash(ROOT, PYTHON),
        )
    else:
        report = run_finish_gates(plan, args.json_report.parent)
    write_json_report(report, args.json_report)
    print(f"finish_check planned_gates={','.join(plan.gates)} executed={not args.plan_only} report={args.json_report}")
    return 0 if args.plan_only or report.passed else 1


def _commands_for(gates: tuple[str, ...], changed_paths: tuple[Path, ...]) -> tuple[GateCommand, ...]:
    focused_tests = _focused_tests(changed_paths)
    commands: list[GateCommand] = []
    if "focused" in gates:
        commands.append(GateCommand("focused", (str(PYTHON), "-m", "pytest", *focused_tests, "-q")))
    if "full" in gates:
        commands.append(GateCommand("full", (str(PYTHON), "-m", "pytest", "tests", "-q")))
    if "fixtures" in gates:
        commands.append(GateCommand("fixtures", (str(PYTHON), "-m", "pytest", "tests/test_official_fixture_manifest.py", "-q")))
    if "export" in gates:
        commands.append(GateCommand("export", (str(PYTHON), "-m", "pytest", "tests/test_trust_critical_artifacts.py", "-q")))
    if "build" in gates:
        commands.append(GateCommand("build", ("cmd.exe", "/d", "/c", "scripts\\build_windows.bat")))
    return tuple(commands)


def _focused_tests(changed_paths: tuple[Path, ...]) -> tuple[str, ...]:
    tests: set[str] = set()
    for path in changed_paths:
        key = _path_key(path)
        if key.startswith("src/etf_cockpit/parsers/"):
            tests.add("tests/test_official_fixture_manifest.py")
        elif key.startswith("src/etf_cockpit/app/"):
            tests.add("tests/test_flet_startup.py")
        elif key.startswith("scripts/") or key.endswith(".bat"):
            tests.add("tests/test_launcher_workflow.py")
        elif key.startswith("tests/"):
            tests.add(key)
    return tuple(sorted(tests)) or ("tests/test_finish_check.py",)


def _path_key(path: Path) -> str:
    value = path.as_posix().replace("\\", "/").lower()
    root = ROOT.as_posix().replace("\\", "/").lower().rstrip("/")
    return value.removeprefix(f"{root}/").lstrip("./")


def _is_runtime_or_package_path(path: str) -> bool:
    return path.startswith(RUNTIME_PATH_PREFIXES[:3]) or path in RUNTIME_PATH_PREFIXES[3:5] or path.endswith(".bat")


def _command_environment() -> dict[str, str]:
    return os.environ.copy()


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(fragment in lowered for fragment in ("token", "secret", "password", "api_key", "apikey", "authorization"))


def _read_changed_paths(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _split_issue_ids(values: Sequence[str]) -> list[str]:
    return [issue.strip() for value in values for issue in value.split(",") if issue.strip()]


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"Cannot serialise {type(value).__name__} in a finish-check report.")


if __name__ == "__main__":
    raise SystemExit(main())
