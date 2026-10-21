"""Create deterministic software supply-chain evidence for a local release."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from scripts.release_gate import (
        _canonical_name,
        _lock_requirements,
        _tracked_paths,
        build_sbom,
        build_source_manifest,
        canonical_json,
        dependency_snapshot,
    )
except ImportError:  # also pywin32's top-level 'scripts' namespace
    from release_gate import (  # type: ignore[no-redef]
        _canonical_name,
        _lock_requirements,
        _tracked_paths,
        build_sbom,
        build_source_manifest,
        canonical_json,
        dependency_snapshot,
    )

from etf_cockpit.governance.supply_chain_intake import supply_chain_intake_report  # noqa: E402


POLICY_PATH = Path("configs/supply_chain_policy.yaml")
RELEASE_POLICY_PATH = Path("configs/release_policy.yaml")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----"),
    re.compile(r"\b(?:ghp|github_pat|AKIA)[A-Za-z0-9_]{16,}\b"),
    re.compile(r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9/+_.-]{20,}['\"]"),
)
# Binary payloads are skipped by suffix; every other tracked file (any suffix, or none) is scanned as text.
BINARY_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".webp", ".pdf", ".zip", ".gz", ".whl", ".exe", ".dll",
        ".so", ".pyd", ".parquet", ".duckdb", ".sqlite", ".db", ".ttf", ".otf", ".woff", ".woff2", ".mp3", ".mp4",
        ".bin", ".pt", ".safetensors", ".npy", ".npz", ".pkl", ".pyc",
    }
)
_LOCK_KEYS = ("dependency_lock", "parser_dependency_lock")
# Intake failures the policy may explicitly mark advisory (they never gate the exit code); all others block.
KNOWN_ADVISORY_INTAKE_FAILURES = frozenset(
    {
        "supply-chain registry review status is not approved",
        "one or more supply-chain components are not approved",
        "detached intake signature status is missing",
    }
)


def policy_locks(policy: dict[str, object]) -> list[str]:
    """Every release dependency lock the policy names (release lock first, then the parser lock)."""

    return [str(policy[key]) for key in _LOCK_KEYS if policy.get(key)]


def _policy(root: Path) -> dict[str, object]:
    import yaml

    value = yaml.safe_load((root / POLICY_PATH).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"supply-chain policy must be an object: {root / POLICY_PATH}")
    release_path = root / RELEASE_POLICY_PATH
    if release_path.is_file():
        release = yaml.safe_load(release_path.read_text(encoding="utf-8"))
        if isinstance(release, dict):
            uncovered = sorted(set(policy_locks(release)) - set(policy_locks(value)))
            if uncovered:
                raise ValueError(
                    "supply-chain policy does not scan release lock(s) named by the release policy: " + ", ".join(uncovered)
                )
    return value


def secret_findings(root: Path, source_manifest: dict[str, object]) -> list[dict[str, str]]:
    """Scan every tracked text file: the manifest plus tracked files its build-directory exclusions omit."""

    paths: dict[str, Path] = {}
    for row in source_manifest.get("files", []):
        if isinstance(row, dict):
            paths[str(row["path"])] = root / str(row["path"])
    for tracked in _tracked_paths(root):
        try:
            paths.setdefault(tracked.relative_to(root).as_posix(), tracked)
        except ValueError:
            continue
    findings: list[dict[str, str]] = []
    for relative, path in sorted(paths.items()):
        if relative.startswith("artifacts/release/") or path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        payload = path.read_bytes()
        if b"\x00" in payload:
            continue
        text = payload.decode("utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append({"path": relative, "pattern": pattern.pattern})
    return findings


def licence_inventory(root: Path, policy: dict[str, object]) -> dict[str, object]:
    snapshot = dependency_snapshot(root, policy)
    rows: list[dict[str, str]] = []
    missing: list[str] = []
    for row in snapshot["required"]:
        name = str(row["name"])
        try:
            metadata = importlib.metadata.metadata(name)
            licence = str(metadata.get("License") or metadata.get("License-Expression") or "").strip()
            if not licence:
                classifiers = metadata.get_all("Classifier") or []
                licence = next((str(value).removeprefix("License :: ") for value in classifiers if str(value).startswith("License :: ")), "")
        except importlib.metadata.PackageNotFoundError:
            licence = ""
        if not licence:
            missing.append(name)
        rows.append({"name": name, "version": str(row["version"]), "license": licence or "unavailable"})
    return {"components": rows, "missing_license_metadata": sorted(missing)}


def _mitigation_expiry(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _scoped_mitigations(policy: dict[str, object], today: dt.date) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Valid exemptions (id + package + version + unexpired); anything else is reported and never exempts."""

    valid: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    for item in policy.get("approved_mitigations") or []:
        if not isinstance(item, dict):
            invalid.append({"id": str(item), "reason": "mitigation must name id, package, version and expires_on"})
            continue
        label = str(item.get("id", ""))
        missing = [key for key in ("id", "package", "version", "expires_on") if not str(item.get(key) or "").strip()]
        expiry = None if missing else _mitigation_expiry(item.get("expires_on"))
        if missing:
            invalid.append({"id": label, "reason": "missing " + ", ".join(missing)})
        elif expiry is None:
            invalid.append({"id": label, "reason": "expires_on is not an ISO date"})
        elif expiry < today:
            invalid.append({"id": label, "reason": f"expired on {expiry.isoformat()}"})
        else:
            valid.append({"id": str(item["id"]), "package": _canonical_name(str(item["package"])), "version": str(item["version"])})
    return valid, invalid


def _mitigation_matches(vulnerability: object, mitigations: list[dict[str, str]]) -> bool:
    if not isinstance(vulnerability, dict):
        return False
    identifiers = {str(vulnerability.get("id") or "")} | {str(alias) for alias in vulnerability.get("aliases") or []}
    package = _canonical_name(str(vulnerability.get("package") or vulnerability.get("name") or ""))
    version = str(vulnerability.get("version") or "")
    return bool(package and version) and any(
        item["id"] in identifiers and item["package"] == package and item["version"] == version for item in mitigations
    )


def _audit_one_lock(root: Path, lock: str, *, allow_missing_tools: bool) -> dict[str, Any]:
    """Run pip-audit for one lock. Returns {unavailable} or {run, vulnerabilities, problems}."""

    command = (sys.executable, "-m", "pip_audit", "-r", lock, "--format", "json", "--progress-spinner", "off")
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"unavailable": {"status": "unavailable", "required": not allow_missing_tools, "command": " ".join(command), "error": str(exc)}}
    output = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0 and not output and "No module named pip_audit" in stderr:
        return {
            "unavailable": {
                "status": "unavailable",
                "required": not allow_missing_tools,
                "command": " ".join(command),
                "exit_code": completed.returncode,
                "error": stderr,
            }
        }
    run: dict[str, Any] = {
        "lock": lock,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "output": output[-4000:],
        "stderr": stderr[-4000:],
    }
    vulnerabilities: list[object] = []
    problems: list[str] = []
    payload: object = None
    parsed = False
    if not output:
        problems.append(f"pip-audit produced no output for {lock}")
    else:
        try:
            payload = json.loads(output)
            parsed = True
        except json.JSONDecodeError:
            problems.append(f"pip-audit output for {lock} is not valid JSON")
    dependency_rows: list[object] = []
    if parsed:
        if isinstance(payload, list):
            dependency_rows = payload
        elif isinstance(payload, dict) and isinstance(payload.get("dependencies"), list):
            dependency_rows = payload["dependencies"]
        else:
            problems.append(f"pip-audit output for {lock} has no dependency list")
        if (isinstance(payload, list) or isinstance(payload, dict)) and not dependency_rows and not problems:
            problems.append(f"pip-audit output for {lock} lists no dependencies")
    audited: dict[str, str] = {}
    for row in dependency_rows:
        if not isinstance(row, dict):
            continue
        row_vulnerabilities = row.get("vulns")
        if isinstance(row_vulnerabilities, list):
            audited[_canonical_name(str(row.get("name", "")))] = str(row.get("version", ""))
            for vulnerability in row_vulnerabilities:
                if isinstance(vulnerability, dict):
                    vulnerabilities.append({"package": row.get("name", ""), "version": row.get("version", ""), **vulnerability})
        elif row.get("id"):
            vulnerabilities.append(row)
    if dependency_rows:
        try:
            uncovered = sorted(
                f"{name}=={version}"
                for name, version in _lock_requirements(root, lock)
                if audited.get(_canonical_name(name)) != version
            )
        except (OSError, ValueError) as exc:
            problems.append(f"lock {lock} cannot be read for coverage: {exc}")
        else:
            if uncovered:
                problems.append(f"pip-audit output for {lock} does not cover: " + ", ".join(uncovered))
    return {"run": run, "vulnerabilities": vulnerabilities, "problems": problems}


def vulnerability_scan(
    root: Path, policy: dict[str, object], *, allow_missing_tools: bool, today: dt.date | None = None
) -> dict[str, object]:
    """Audit every release lock; output must be valid, non-empty and cover the lock, or the scan fails."""

    locks = policy_locks(policy) or ["requirements-release.txt"]
    mitigations, invalid_mitigations = _scoped_mitigations(policy, today or dt.date.today())
    vulnerabilities: list[object] = []
    blocking: list[object] = []
    approved: list[object] = []
    problems: list[str] = []
    runs: list[dict[str, Any]] = []
    exit_ok = True
    for lock in locks:
        audit = _audit_one_lock(root, lock, allow_missing_tools=allow_missing_tools)
        if "unavailable" in audit:
            return audit["unavailable"]
        run = audit["run"]
        runs.append(run)
        problems.extend(audit["problems"])
        found = audit["vulnerabilities"]
        vulnerabilities.extend(found)
        lock_blocking = [item for item in found if not _mitigation_matches(item, mitigations)]
        blocking.extend(lock_blocking)
        approved.extend(item for item in found if _mitigation_matches(item, mitigations))
        # Exit 1 is pip-audit's "vulnerabilities found": acceptable only when every finding is individually approved.
        if run["exit_code"] != 0 and not (run["exit_code"] == 1 and found and not lock_blocking):
            exit_ok = False
    return {
        "status": "passed" if exit_ok and not problems and not blocking else "failed",
        "required": True,
        "exit_code": max(int(run["exit_code"]) for run in runs),
        "command": " ; ".join(str(run["command"]) for run in runs),
        "duration_ms": round(sum(float(run["duration_ms"]) for run in runs), 3),
        "locks": locks,
        "runs": runs,
        "problems": problems,
        "vulnerabilities": vulnerabilities,
        "blocking_vulnerabilities": blocking,
        "approved_mitigations": approved,
        "invalid_mitigations": invalid_mitigations,
        "output": "\n".join(str(run["output"]) for run in runs)[-4000:],
        "stderr": "\n".join(str(run["stderr"]) for run in runs)[-4000:],
    }


def _advisory_intake_failures(policy: dict[str, object], intake: dict[str, Any]) -> set[str]:
    """Intake failures the policy explicitly lists as advisory, and which actually occurred."""

    declared = policy.get("advisory_intake_exceptions") or []
    if not isinstance(declared, list):
        raise ValueError("advisory_intake_exceptions must be a list of intake failure messages")
    unknown = sorted(str(item) for item in declared if str(item) not in KNOWN_ADVISORY_INTAKE_FAILURES)
    if unknown:
        raise ValueError("advisory_intake_exceptions names failures that cannot be advisory: " + "; ".join(unknown))
    return {str(item) for item in declared} & {str(failure) for failure in intake.get("failures", [])}


def write_report(root: Path, output_dir: Path, *, allow_missing_tools: bool = False) -> tuple[Path, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = _policy(root)
    source = build_source_manifest(root, output_dir=output_dir.relative_to(root) if output_dir.is_relative_to(root) else None)
    sbom = build_sbom(root, source, policy)
    licences = licence_inventory(root, policy)
    secrets = secret_findings(root, source)
    vulnerabilities = vulnerability_scan(root, policy, allow_missing_tools=allow_missing_tools)
    intake = supply_chain_intake_report(root)
    failures: list[str] = []
    if secrets:
        failures.append("secret scan found credential-like content")
    if licences["missing_license_metadata"]:
        failures.append("licence metadata missing for: " + ", ".join(licences["missing_license_metadata"]))
    if vulnerabilities.get("required") and vulnerabilities.get("status") != "passed":
        failures.append("vulnerability scan failed or was unavailable")
    failures.extend(f"intake: {failure}" for failure in intake.get("failures", []))
    advisory = _advisory_intake_failures(policy, intake)
    blocking_failures = [failure for failure in failures if not any(failure == f"intake: {item}" for item in advisory)]
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "policy": policy,
        "source_manifest_sha256": source["manifest_sha256"],
        "sbom_sha256": sbom["bom_sha256"],
        "secret_scan": {"status": "passed" if not secrets else "failed", "findings": secrets},
        "licence_scan": licences,
        "vulnerability_scan": vulnerabilities,
        "third_party_notices": "packaging/THIRD_PARTY_NOTICES.md",
        "intake": intake,
        "failures": failures,
        "advisory_intake_failures": sorted(advisory),
        "blocking_failures": blocking_failures,
    }
    report_path = output_dir / "supply-chain-report.json"
    report_path.write_bytes(canonical_json(report))
    markdown = [
        "# Supply-chain scan",
        "",
        f"- Status: `{'failed' if failures else 'passed'}`; release-blocking: `{'yes' if blocking_failures else 'no'}`",
        f"- SBOM: `{report['sbom_sha256']}`",
        f"- Intake: `{intake['status']}`; review `{intake['review_status']}`; signature `{intake['signature_status']}`",
        "",
        "## Failures",
        "",
    ]
    markdown.extend(
        f"- {failure}" + (" (advisory by policy)" if failure not in blocking_failures else "") for failure in failures
    ) if failures else markdown.append("- None")
    (output_dir / "supply-chain-report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8", newline="\n")
    (output_dir / "sbom.cdx.json").write_bytes(canonical_json(sbom))
    return report_path, 1 if blocking_failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("artifacts/supply-chain/latest"))
    parser.add_argument("--allow-missing-tools", action="store_true", help="local diagnostic mode only")
    args = parser.parse_args(argv)
    try:
        path, exit_code = write_report(args.root.resolve(), (args.root / args.output).resolve() if not args.output.is_absolute() else args.output.resolve(), allow_missing_tools=args.allow_missing_tools)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"report": str(path), "exit_code": exit_code}, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
