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
    ".github/status-transition-guard-manifest.json",
    "issues/programme_control_state.json",
    "issues/issue_registry.json",
    "docs/product-completion/current_status.json",
    "docs/product-completion/progress.md",
    "docs/product-completion/programme/readiness.json",
    "docs/product-completion/programme/generation-manifest.json",
    "docs/product-completion/reconciliation/",
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
REUSABLE_EVIDENCE_KEYS = frozenset(
    {
        "base_sha",
        "head_sha",
        "source_sha256",
        "dependency_sha256",
        "product_tree_sha256",
        "policy_sha256",
        "artifact_manifest_sha256",
        "environment_sha256",
        "execution_allowed",
    }
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
    parsed_path = PurePosixPath(lowered)
    parts = set(parsed_path.parts)
    semantic_tokens = set(re.findall(r"[a-z0-9]+", lowered))
    if any(lowered.startswith(prefix) for prefix in CERTIFICATION_PREFIXES):
        return PathClassification(path, "C", "certification-evidence")
    if any(lowered.startswith(prefix.lower()) for prefix in EVIDENCE_PREFIXES):
        return PathClassification(path, "E", "allowlisted-semantic-event-or-projection")
    if (
        path in HIGH_RISK_NAMES
        or any(lowered.startswith(prefix.lower()) for prefix in HIGH_RISK_PREFIXES)
        or parsed_path.name.endswith("_store.py")
        or bool((parts | semantic_tokens) & HIGH_RISK_PARTS)
        or lowered.startswith("requirements")
    ):
        return PathClassification(path, "H", "protected-or-high-risk-surface")
    if any(lowered.startswith(prefix.lower()) for prefix in ORDINARY_PREFIXES):
        return PathClassification(path, "O", "ordinary-product-surface")
    return PathClassification(path, "H", "unknown-surface-fails-upward")


def _valid_reusable_evidence(
    value: object, expected: dict[str, object] | None
) -> bool:
    if not isinstance(value, dict) or set(value) != REUSABLE_EVIDENCE_KEYS:
        return False
    if value.get("execution_allowed") is not False:
        return False
    for key in REUSABLE_EVIDENCE_KEYS - {"execution_allowed"}:
        width = 40 if key in {"base_sha", "head_sha"} else 64
        if not isinstance(value.get(key), str) or not re.fullmatch(
            rf"[0-9a-f]{{{width}}}", str(value[key])
        ):
            return False
    return expected is not None and value == expected


def _git_identity(root: Path, ref: str, paths: tuple[str, ...]) -> str:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--full-tree", ref, "--", *paths],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return __import__("hashlib").sha256(result.stdout).hexdigest()


def derive_trusted_evidence(
    root: Path,
    *,
    base: str,
    head: str,
    artifact_manifest: str,
) -> dict[str, object] | None:
    """Recompute protected identities; unchanged exact evidence alone may reuse."""

    if not re.fullmatch(r"[0-9a-f]{40}", base) or not re.fullmatch(r"[0-9a-f]{40}", head):
        return None
    groups = {
        "source_sha256": ("src", "scripts"),
        "dependency_sha256": (
            "pyproject.toml",
            "requirements-release.txt",
            "requirements-release-parsers.txt",
        ),
        "product_tree_sha256": ("src", "configs"),
        "policy_sha256": ("AGENTS.md", ".github/workflows", "configs"),
        "environment_sha256": ("pyproject.toml", "requirements-release.txt", "requirements-release-parsers.txt"),
    }
    try:
        identities: dict[str, object] = {"base_sha": base, "head_sha": head}
        for key, paths in groups.items():
            base_digest = _git_identity(root, base, paths)
            head_digest = _git_identity(root, head, paths)
            if base_digest != head_digest:
                return None
            identities[key] = head_digest
        artifact = subprocess.check_output(
            ["git", "show", f"{base}:{artifact_manifest}"], cwd=root
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    identities["artifact_manifest_sha256"] = __import__("hashlib").sha256(artifact).hexdigest()
    identities["execution_allowed"] = False
    return identities


def build_report(
    paths: list[str],
    *,
    ordinary_issues_since_full_gate: int = 0,
    reusable_evidence: dict[str, object] | None = None,
    expected_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    classified = sorted((classify_path(path) for path in paths), key=lambda item: item.path)
    if not classified:
        classified = [PathClassification("<no-changes>", "H", "empty-change-set-fails-upward")]
    tier = max((item.tier for item in classified), key=TIER_ORDER.__getitem__)
    cadence_due = tier == "O" and ordinary_issues_since_full_gate >= 2
    evidence_reuse_authorized = tier == "E" and _valid_reusable_evidence(
        reusable_evidence, expected_evidence
    )
    package_gate_required = tier in {"H", "C"} or cadence_due or (
        tier == "E" and not evidence_reuse_authorized
    )
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
        "evidence_reuse": {
            "authorized": evidence_reuse_authorized,
            "reason": (
                "exact-identities-validated"
                if evidence_reuse_authorized
                else "absent-incomplete-or-inconsistent"
            ),
        },
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
    parser.add_argument("--reuse-evidence", type=Path)
    parser.add_argument("--artifact-manifest", default="artifacts/validation/reuse-manifest.json")
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
    reusable_evidence = None
    if args.reuse_evidence:
        try:
            reusable_evidence = json.loads(args.reuse_evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reusable_evidence = None
    expected_evidence = None
    if args.base and reusable_evidence:
        expected_evidence = derive_trusted_evidence(
            args.root.resolve(),
            base=args.base,
            head=args.head,
            artifact_manifest=args.artifact_manifest,
        )
    report = build_report(
        paths,
        ordinary_issues_since_full_gate=max(0, args.ordinary_issues_since_full_gate),
        reusable_evidence=reusable_evidence,
        expected_evidence=expected_evidence,
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
