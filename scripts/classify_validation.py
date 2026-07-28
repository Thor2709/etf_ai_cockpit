"""Classify a change into the repository validation tiers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = "validation-classifier.v1"
TIERS = ("E", "O", "H", "C")
TIER_ORDER = {tier: index for index, tier in enumerate(TIERS)}

EVIDENCE_PREFIXES = (
    ".github/issue-transitions/",
    "docs/",
    "plans/",
)
ORDINARY_PREFIXES = ("src/", "tests/", "configs/ui_acceptance.yaml")
HIGH_RISK_PARTS = {
    "broker",
    "brokers",
    "concurrency",
    "credential",
    "credentials",
    "database",
    "execution",
    "finance",
    "financial",
    "migration",
    "migrations",
    "order",
    "orders",
    "persistence",
    "portfolio",
    "pricing",
    "release",
    "security",
    "sqlite",
}
HIGH_RISK_PREFIXES = (
    ".github/workflows/",
    ".github/status-transition-guard-manifest.json",
    "issues/",
    "packaging/",
    "scripts/",
)
HIGH_RISK_NAMES = {
    "AGENTS.md",
    "pyproject.toml",
    "requirements-release.txt",
    "requirements-release-parsers.txt",
}
CERTIFICATION_PREFIXES = (
    "docs/product-completion/certification/",
    "artifacts/certification/",
)


@dataclass(frozen=True)
class PathClassification:
    path: str
    tier: str
    reason: str


def _normalise_path(value: str) -> str:
    path = value.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return str(PurePosixPath(path)) if path else ""


def classify_path(value: str) -> PathClassification:
    path = _normalise_path(value)
    if not path or path == "." or path.startswith("../") or PurePosixPath(path).is_absolute():
        return PathClassification(path or value, "H", "ambiguous-or-invalid-path")
    lowered = path.lower()
    parts = set(PurePosixPath(lowered).parts)
    semantic_tokens = set(re.findall(r"[a-z0-9]+", lowered))
    if any(lowered.startswith(prefix) for prefix in CERTIFICATION_PREFIXES):
        return PathClassification(path, "C", "certification-evidence")
    if (
        path in HIGH_RISK_NAMES
        or any(lowered.startswith(prefix.lower()) for prefix in HIGH_RISK_PREFIXES)
        or bool((parts | semantic_tokens) & HIGH_RISK_PARTS)
        or lowered.startswith("requirements")
    ):
        return PathClassification(path, "H", "protected-or-high-risk-surface")
    if any(lowered.startswith(prefix.lower()) for prefix in EVIDENCE_PREFIXES) or lowered.endswith(".md"):
        return PathClassification(path, "E", "evidence-only-surface")
    if any(lowered.startswith(prefix.lower()) for prefix in ORDINARY_PREFIXES):
        return PathClassification(path, "O", "ordinary-product-surface")
    return PathClassification(path, "H", "unknown-surface-fails-upward")


def build_report(paths: list[str], *, ordinary_issues_since_full_gate: int = 0) -> dict[str, object]:
    classified = sorted((classify_path(path) for path in paths), key=lambda item: item.path)
    if not classified:
        classified = [PathClassification("<no-changes>", "H", "empty-change-set-fails-upward")]
    tier = max((item.tier for item in classified), key=TIER_ORDER.__getitem__)
    cadence_due = tier == "O" and ordinary_issues_since_full_gate >= 2
    package_gate_required = tier in {"H", "C"} or cadence_due
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "package_gate_required": package_gate_required,
        "ordinary_full_gate_cadence": {
            "issues_since_last_full_gate": ordinary_issues_since_full_gate,
            "threshold": 2,
            "due": cadence_due,
        },
        "paths": [
            {"path": item.path, "tier": item.tier, "reason": item.reason}
            for item in classified
        ],
        "reasons": sorted({item.reason for item in classified}),
    }


def validation_summary_failures(
    *,
    package_gate_required: bool,
    classifier: str,
    preflight: str,
    supply_chain: str,
    release_gate: str,
) -> list[str]:
    """Return deterministic failures for the terminal required check."""

    results = {
        "classifier": classifier,
        "preflight": preflight,
        "supply-chain": supply_chain,
    }
    failures = [
        f"{name} result was {result!r}, expected 'success'"
        for name, result in results.items()
        if result != "success"
    ]
    expected_release = "success" if package_gate_required else "skipped"
    if release_gate != expected_release:
        failures.append(
            f"release-gate result was {release_gate!r}, expected {expected_release!r}"
        )
    return failures


def _git_changed_paths(root: Path, base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", base, head, "--"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--ordinary-issues-since-full-gate", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    paths = list(args.changed_file)
    classification_error = ""
    if not paths:
        try:
            if not args.base:
                raise ValueError("--base is required when --changed-file is not supplied")
            paths = _git_changed_paths(args.root.resolve(), args.base, args.head)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            classification_error = str(exc)
            paths = ["<classification-error>"]
    report = build_report(
        paths,
        ordinary_issues_since_full_gate=max(0, args.ordinary_issues_since_full_gate),
    )
    if classification_error:
        report["classification_error"] = classification_error
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
