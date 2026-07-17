"""Run the protected, reproducible release gate and write closure evidence.

The gate is deliberately local-first.  It runs the repository test command,
builds the Windows package, smoke-tests the built source package, creates a
CycloneDX SBOM and signs the resulting manifest with a key supplied by the
protected environment.  Every mandatory failure is retained in the report and
causes a non-zero exit code.
"""

from __future__ import annotations

import argparse
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
import time
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "1.0"
DEFAULT_POLICY = Path("configs/release_policy.yaml")
DEFAULT_OUTPUT = Path("artifacts/release/latest")
SIGNING_KEY_ENV = "ETF_COCKPIT_RELEASE_SIGNING_KEY"
SIGNING_KEY_ID_ENV = "ETF_COCKPIT_RELEASE_SIGNING_KEY_ID"
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
    return {
        "branch": _git(root, "branch", "--show-current"),
        "head": _git(root, "rev-parse", "HEAD"),
        "origin_main": _git(root, "rev-parse", "origin/main"),
        "dirty": bool(_git(root, "status", "--porcelain")),
    }


def load_policy(root: Path) -> dict[str, object]:
    path = root / DEFAULT_POLICY
    try:
        import yaml

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
    payload = {
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
    }
    return payload


def environment_check(root: Path, policy: dict[str, object], *, allow_dirty: bool) -> CheckResult:
    started = time.perf_counter()
    expected_python = str(policy.get("python_version", "3.12.10"))
    actual_python = platform.python_version()
    messages: list[str] = []
    if actual_python != expected_python:
        messages.append(f"python {actual_python} does not match pinned {expected_python}")
    snapshot = dependency_snapshot(root, policy)
    if snapshot["missing"]:
        messages.append("missing locked packages: " + ", ".join(snapshot["missing"]))
    if snapshot["mismatched"]:
        messages.extend(str(value) for value in snapshot["mismatched"])
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


def _command_text(command: Iterable[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def run_command(root: Path, output_dir: Path, name: str, command: tuple[str, ...], *, required: bool = True) -> CheckResult:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
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
    for path in reversed(_artifact_paths(root, policy)):
        if path.name != "smoke_app.py" or path.parent.name != "scripts":
            continue
        candidate = path.parent.parent
        if (candidate / "src").exists() or (candidate / "app" / "src").exists():
            return candidate
    return None


def build_sbom(
    root: Path,
    source_manifest: dict[str, object],
    policy: dict[str, object],
    *,
    artifact_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a deterministic CycloneDX 1.5 SBOM for the release gate inputs."""

    components: list[dict[str, object]] = [
        {
            "type": "application",
            "name": "etf-ai-cockpit",
            "version": _project_version(root),
            "bom-ref": "etf-ai-cockpit",
            "properties": [
                {"name": "source-manifest-sha256", "value": str(source_manifest["manifest_sha256"])},
                {"name": "local-first", "value": "true"},
            ],
        }
    ]
    if artifact_manifest is not None:
        components[0]["properties"] = [
            *list(components[0].get("properties", [])),
            {"name": "artifact-manifest-sha256", "value": str(artifact_manifest["manifest_sha256"])},
            {"name": "artifact-file-count", "value": str(len(artifact_manifest.get("files", [])))},
        ]
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
    lines = [
        "# ETF AI Cockpit release gate",
        "",
        f"- Schema: `{manifest['schema_version']}`",
        f"- Git head: `{manifest['git']['head']}`",
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
        state.add(run_command(root, output, "full_tests", _python_command(root, "-m", "pytest", "-q")))

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
        package_root = _package_root(root, policy)
        smoke_root = package_root or root
        smoke_script = smoke_root / "scripts" / "smoke_app.py"
        command = (sys.executable, str(smoke_script), "--mode", "offline", "--port", str(_free_port()), "--timeout", "30")
        state.add(run_command(smoke_root, output, "package_smoke", command))

    sbom = build_sbom(root, source, policy, artifact_manifest=artifacts)
    _write_json(output / "sbom.cdx.json", sbom)
    state.add(CheckResult("sbom", "passed", True, "CycloneDX 1.5 deterministic SBOM"))

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "git": git_snapshot(root),
        "python": sys.version.split()[0],
        "project_version": _project_version(root),
        "policy": policy,
        "source_manifest_sha256": source["manifest_sha256"],
        "artifact_manifest_sha256": artifacts["manifest_sha256"],
        "sbom_sha256": sbom["bom_sha256"],
        "checks": [asdict(check) for check in state.checks],
        "failures": list(state.failures),
    }
    manifest_path = output / "release-manifest.json"
    signing_key_text = os.getenv(str(policy.get("signing_key_env", SIGNING_KEY_ENV)), "")
    key_id = os.getenv(SIGNING_KEY_ID_ENV, "local-release-key")
    signature_path = output / "release-manifest.sig.json"
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
    return [
        _command_text(_python_command(root, "-m", "pytest", "-q")),
        _command_text(package_command(root)),
        "python scripts/smoke_app.py --mode offline --port <free-port> --timeout 30",
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
    parser.add_argument("--dry-run", action="store_true", help="print the protected gate without executing it")
    args = parser.parse_args(argv)
    root = args.root.resolve()
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
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"exit_code": result.exit_code, "output_dir": str(result.output_dir), "manifest": str(result.manifest_path), "report": str(result.report_path)}, indent=2))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
