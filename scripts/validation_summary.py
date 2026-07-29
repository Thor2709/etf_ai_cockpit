"""Build and validate the terminal cross-job validation evidence summary."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "validation-summary.v1"
IDENTITY_KEYS = {
    "environment",
    "source",
    "dependency",
    "product_tree",
    "policy",
}
JOB_KEYS = {"classifier", "preflight", "supply_chain", "release_windows", "release_linux"}


def validate_summary(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append("terminal summary schema mismatch")
    for key in ("base_sha", "head_sha"):
        if not isinstance(report.get(key), str) or not re.fullmatch(r"[0-9a-f]{40}", report[key]):
            errors.append(f"terminal summary {key} is invalid")
    if report.get("tier") not in {"E", "O", "H", "C"} or not report.get("reason"):
        errors.append("terminal summary tier/reason is absent")
    package = report.get("package_gate_required")
    if not isinstance(package, bool):
        errors.append("terminal summary package requirement is absent")
    jobs = report.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != JOB_KEYS:
        errors.append("terminal summary required/skipped jobs are incomplete")
    results = report.get("job_results")
    if (
        not isinstance(results, dict)
        or any(
            results.get(name) != "success"
            for name in ("classifier", "preflight", "supply_chain")
        )
        or (
            package is True
            and results.get("release") != "success"
        )
        or (
            package is False
            and results.get("release") != "skipped"
        )
    ):
        errors.append("terminal summary job results are inconsistent")
    identities = report.get("identities")
    if (
        not isinstance(identities, dict)
        or set(identities) != IDENTITY_KEYS
        or any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in identities.values())
    ):
        errors.append("terminal summary protected identities are incomplete")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list) or any(
        not isinstance(item, dict)
        or set(item) != {"path", "sha256", "present"}
        or item.get("present") is not True
        or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256")))
        for item in artifacts
    ):
        errors.append("terminal summary artifact presence/hashes are incomplete")
    junit = report.get("platform_junit")
    if package is True and (
        not isinstance(junit, dict)
        or set(junit) != {"windows", "linux"}
        or any(not isinstance(value, int) or value < 1 for value in junit.values())
    ):
        errors.append("terminal summary platform JUnit counts are required")
    artifact_paths = {
        str(item.get("path", ""))
        for item in artifacts
        if isinstance(item, dict)
    } if isinstance(artifacts, list) else set()
    if not any("classifier" in path for path in artifact_paths):
        errors.append("terminal summary classifier artifact is required")
    if package is True and (
        not any("windows" in path.lower() for path in artifact_paths)
        or not any("linux" in path.lower() for path in artifact_paths)
    ):
        errors.append("terminal summary platform artifacts are required")
    controls = report.get("controls")
    required_controls = {
        "guards_passed",
        "freshness_passed",
        "evidence_reuse_authorized",
        "automation_authority",
        "apply_authority",
    }
    if not isinstance(controls, dict) or set(controls) != required_controls:
        errors.append("terminal summary guard/freshness/authority controls are incomplete")
    elif (
        controls.get("guards_passed") is not True
        or controls.get("freshness_passed") is not True
        or controls.get("automation_authority") != "read-only"
        or controls.get("apply_authority") is not False
    ):
        errors.append("terminal summary authority or guard state is unsafe")
    return errors


def _tree_identity(root: Path, ref: str, paths: list[str]) -> str:
    payload = subprocess.check_output(
        ["git", "ls-tree", "-r", "--full-tree", ref, "--", *paths], cwd=root
    )
    return hashlib.sha256(payload).hexdigest()


def _junit_tests(node: ET.Element) -> int:
    child_suites = [
        child for child in node if child.tag.rsplit("}", 1)[-1] == "testsuite"
    ]
    if child_suites:
        return sum(_junit_tests(child) for child in child_suites)
    return int(node.attrib.get("tests", 0))


def collect_summary(
    root: Path,
    artifacts_root: Path,
    *,
    base: str,
    head: str,
    job_results: dict[str, str],
) -> dict[str, Any]:
    classifier_paths = list(artifacts_root.rglob("classifier.json"))
    if len(classifier_paths) != 1:
        raise ValueError("exactly one classifier artifact is required")
    classifier = json.loads(classifier_paths[0].read_text(encoding="utf-8"))
    tier = classifier.get("tier")
    package = bool(classifier.get("package_gate_required"))
    artifacts = [
        {
            "path": path.relative_to(artifacts_root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "present": True,
        }
        for path in sorted(artifacts_root.rglob("*"))
        if path.is_file()
    ]
    junit = {"windows": 0, "linux": 0}
    for path in artifacts_root.rglob("*.xml"):
        platform = "windows" if "windows" in path.as_posix().lower() else "linux"
        try:
            root_node = ET.parse(path).getroot()
            junit[platform] += _junit_tests(root_node)
        except (ET.ParseError, ValueError):
            continue
    groups = {
        "environment": ["pyproject.toml", "requirements-release.txt", "requirements-release-parsers.txt"],
        "source": ["src", "scripts"],
        "dependency": ["pyproject.toml", "requirements-release.txt", "requirements-release-parsers.txt"],
        "product_tree": ["src", "configs"],
        "policy": ["AGENTS.md", ".github/workflows", "configs"],
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "base_sha": base,
        "head_sha": head,
        "tier": tier,
        "package_gate_required": package,
        "reason": classifier.get("reasons"),
        "jobs": {
            "classifier": "required",
            "preflight": "required",
            "supply_chain": "required",
            "release_windows": "required" if package else "skipped",
            "release_linux": "required" if package else "skipped",
        },
        "job_results": job_results,
        "platform_junit": junit if package else {},
        "artifacts": artifacts,
        "identities": {key: _tree_identity(root, head, paths) for key, paths in groups.items()},
        "controls": {
            "guards_passed": job_results.get("preflight") == "success",
            "freshness_passed": job_results.get("classifier") == "success",
            "evidence_reuse_authorized": bool(classifier.get("evidence_reuse", {}).get("authorized")),
            "automation_authority": "read-only",
            "apply_authority": False,
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--artifacts-root", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--job-result", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.artifacts_root:
            results = dict(value.split("=", 1) for value in args.job_result)
            report = collect_summary(
                args.root.resolve(),
                args.artifacts_root,
                base=args.base,
                head=args.head,
                job_results=results,
            )
            if args.output:
                args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        elif args.input:
            report = json.loads(args.input.read_text(encoding="utf-8"))
        else:
            raise ValueError("--input or --artifacts-root is required")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"INVALID: {exc}")
        return 1
    failures = validate_summary(report)
    if failures:
        print("\n".join(failures))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
