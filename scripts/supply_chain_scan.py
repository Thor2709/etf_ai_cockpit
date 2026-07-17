"""Create deterministic software supply-chain evidence for a local release."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from scripts.release_gate import build_sbom, build_source_manifest, canonical_json, dependency_snapshot
except ModuleNotFoundError:
    from release_gate import build_sbom, build_source_manifest, canonical_json, dependency_snapshot


POLICY_PATH = Path("configs/supply_chain_policy.yaml")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----"),
    re.compile(r"\b(?:ghp|github_pat|AKIA)[A-Za-z0-9_]{16,}\b"),
    re.compile(r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9/+_.-]{20,}['\"]"),
)


def _policy(root: Path) -> dict[str, object]:
    import yaml

    value = yaml.safe_load((root / POLICY_PATH).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"supply-chain policy must be an object: {root / POLICY_PATH}")
    return value


def secret_findings(root: Path, source_manifest: dict[str, object]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for row in source_manifest.get("files", []):
        if not isinstance(row, dict):
            continue
        relative = str(row["path"])
        path = root / relative
        if path.suffix.lower() not in {".py", ".pyi", ".bat", ".ps1", ".toml", ".yaml", ".yml", ".json", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
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


def vulnerability_scan(root: Path, policy: dict[str, object], *, allow_missing_tools: bool) -> dict[str, object]:
    command = (sys.executable, "-m", "pip_audit", "-r", str(policy["dependency_lock"]), "--format", "json", "--progress-spinner", "off")
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "required": not allow_missing_tools, "command": " ".join(command), "error": str(exc)}
    output = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0 and not output and "No module named pip_audit" in stderr:
        return {
            "status": "unavailable",
            "required": not allow_missing_tools,
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "error": stderr,
        }
    try:
        payload: object = json.loads(output) if output else []
    except json.JSONDecodeError:
        payload = {"raw": output[-4000:]}
    dependency_rows: list[object]
    if isinstance(payload, list):
        dependency_rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("dependencies"), list):
        dependency_rows = payload["dependencies"]
    else:
        dependency_rows = [payload]
    vulnerabilities: list[object] = []
    for row in dependency_rows:
        if not isinstance(row, dict):
            continue
        row_vulnerabilities = row.get("vulns")
        if isinstance(row_vulnerabilities, list):
            for vulnerability in row_vulnerabilities:
                if isinstance(vulnerability, dict):
                    vulnerabilities.append({"package": row.get("name", ""), **vulnerability})
        elif row.get("id"):
            vulnerabilities.append(row)
    approved_ids: set[str] = set()
    for item in policy.get("approved_mitigations", []):
        if isinstance(item, str):
            approved_ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            approved_ids.add(str(item["id"]))
    blocking: list[object] = []
    approved: list[object] = []
    for vulnerability in vulnerabilities:
        if isinstance(vulnerability, dict):
            identifier = str(vulnerability.get("id") or vulnerability.get("name") or "")
            if identifier in approved_ids:
                approved.append(vulnerability)
                continue
        blocking.append(vulnerability)
    return {
        "status": "passed" if completed.returncode == 0 and not blocking or (completed.returncode == 1 and vulnerabilities and not blocking) else "failed",
        "required": True,
        "exit_code": completed.returncode,
        "command": " ".join(command),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "vulnerabilities": vulnerabilities,
        "blocking_vulnerabilities": blocking,
        "approved_mitigations": approved,
        "output": output[-4000:],
        "stderr": stderr[-4000:],
    }


def write_report(root: Path, output_dir: Path, *, allow_missing_tools: bool = False) -> tuple[Path, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = _policy(root)
    source = build_source_manifest(root, output_dir=output_dir.relative_to(root) if output_dir.is_relative_to(root) else None)
    sbom = build_sbom(root, source, policy)
    licences = licence_inventory(root, policy)
    secrets = secret_findings(root, source)
    vulnerabilities = vulnerability_scan(root, policy, allow_missing_tools=allow_missing_tools)
    failures: list[str] = []
    if secrets:
        failures.append("secret scan found credential-like content")
    if licences["missing_license_metadata"]:
        failures.append("licence metadata missing for: " + ", ".join(licences["missing_license_metadata"]))
    if vulnerabilities.get("required") and vulnerabilities.get("status") != "passed":
        failures.append("vulnerability scan failed or was unavailable")
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "policy": policy,
        "source_manifest_sha256": source["manifest_sha256"],
        "sbom_sha256": sbom["bom_sha256"],
        "secret_scan": {"status": "passed" if not secrets else "failed", "findings": secrets},
        "licence_scan": licences,
        "vulnerability_scan": vulnerabilities,
        "third_party_notices": "packaging/THIRD_PARTY_NOTICES.md",
        "failures": failures,
    }
    report_path = output_dir / "supply-chain-report.json"
    report_path.write_bytes(canonical_json(report))
    markdown = ["# Supply-chain scan", "", f"- Status: `{'failed' if failures else 'passed'}`", f"- SBOM: `{report['sbom_sha256']}`", "", "## Failures", ""]
    markdown.extend(f"- {failure}" for failure in failures) if failures else markdown.append("- None")
    (output_dir / "supply-chain-report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8", newline="\n")
    (output_dir / "sbom.cdx.json").write_bytes(canonical_json(sbom))
    return report_path, 1 if failures else 0


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
