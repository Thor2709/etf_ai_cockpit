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

EVIDENCE_PATHS = {
    ".github/status-transition-guard-manifest.json",
    "changelog.md",
    "issues/programme_control_state.json",
    "issues/issue_registry.json",
    "issues/open.md",
    "docs/product-completion/current_status.json",
    "docs/product-completion/progress.md",
    "docs/product-completion/programme/generation-manifest.json",
    "docs/product-completion/programme/git-workflow.md",
    "docs/product-completion/programme/implementation-order.md",
    "docs/product-completion/programme/prompt-2-handoff.md",
    "docs/product-completion/programme/readiness.json",
    "docs/product-completion/programme/roadmap.md",
    "docs/product-completion/programme/test-and-performance-strategy.md",
    "readme.md",
}
EVIDENCE_PREFIXES = (
    ".github/issue-transitions/",
    "docs/product-completion/programme/phases/",
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
PILOT_MECHANICS_PATHS = {
    "scripts/profile_parallel_pytest.py",
    "scripts/aggregate_parallel_pilot.py",
    "tests/test_issue_0180_parallel_pilot.py",
}
PROTECTED_POLICY_PATHS = {
    "docs/product-completion/delivery_workflow.md",
}
PILOT_PARTITION_NAMES = {
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "noxfile.py",
}
PILOT_ENVIRONMENT_NAMES = {
    ".python-version",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-release.txt",
    "requirements-release-parsers.txt",
    "poetry.lock",
    "pdm.lock",
    "uv.lock",
}
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
    if lowered in EVIDENCE_PATHS or any(
        lowered.startswith(prefix.lower()) for prefix in EVIDENCE_PREFIXES
    ):
        return PathClassification(path, "E", "allowlisted-semantic-event-or-projection")
    if (
        lowered in PROTECTED_POLICY_PATHS
        or path in HIGH_RISK_NAMES
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


def _git_text(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


def derive_ordinary_gate_cadence(
    root: Path, *, base: str, main_ref: str = "origin/main"
) -> dict[str, object]:
    """Derive O-tier cadence from the exact first-parent main history.

    The PR base must be the current main ref.  This deliberately rejects stale,
    shallow or malformed history because an unknown cadence must select the
    complete package gate rather than silently under-validate an ordinary PR.
    """

    unknown: dict[str, object] = {
        "known": False,
        "source": "exact-first-parent-origin-main",
        "issues_since_last_full_gate": None,
        "threshold": 2,
        "due": True,
        "reason": "cadence-unknown-fails-upward",
    }
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        return {**unknown, "reason": "malformed-base-sha"}
    try:
        if _git_text(root, "rev-parse", "--is-shallow-repository") == "true":
            return {**unknown, "reason": "shallow-history"}
        resolved_main = _git_text(root, "rev-parse", main_ref)
        if not re.fullmatch(r"[0-9a-f]{40}", resolved_main):
            return {**unknown, "reason": "malformed-main-ref"}
        if resolved_main != base:
            return {**unknown, "reason": "stale-pr-base"}
        commits = _git_text(root, "rev-list", "--first-parent", base).splitlines()
        if not commits or any(not re.fullmatch(r"[0-9a-f]{40}", commit) for commit in commits):
            return {**unknown, "reason": "missing-first-parent-history"}
        count = 0
        for commit in commits:
            parent = subprocess.run(
                ["git", "rev-parse", f"{commit}^1"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            if parent.returncode == 0:
                changed = _git_text(
                    root, "diff", "--name-only", "--diff-filter=ACMRTUXB", parent.stdout.strip(), commit
                ).splitlines()
            else:
                changed = _git_text(root, "ls-tree", "-r", "--name-only", commit).splitlines()
            if not changed:
                return {**unknown, "reason": "ambiguous-empty-commit-diff"}
            commit_tier = max(
                (classify_path(path).tier for path in changed), key=TIER_ORDER.__getitem__
            )
            if commit_tier in {"H", "C"}:
                return {
                    "known": True,
                    "source": "exact-first-parent-origin-main",
                    "issues_since_last_full_gate": count,
                    "threshold": 2,
                    # The history count excludes the current PR. One prior O
                    # merge therefore makes the current O issue the second.
                    "due": count + 1 >= 2,
                    "reason": "counted-first-parent-since-nearest-H-C",
                    "reset_commit": commit,
                }
            if commit_tier == "O":
                count += 1
            # E commits are intentionally ignored for cadence.
        return {**unknown, "reason": "missing-reset-boundary"}
    except (OSError, subprocess.CalledProcessError, ValueError):
        return unknown


def parallel_pilot_plan(
    paths: list[str], *, tier: str, trigger: str | None = None
) -> dict[str, object]:
    """Select the report-only pilot without changing serial gate authority."""

    normalised = {_normalise_path(path).lower() for path in paths}
    if trigger == "manual-full":
        return {
            "parallel_pilot_required": True,
            "parallel_pilot_repetitions": 2,
            "parallel_pilot_reason": "explicit-full-drift-sample",
        }
    if trigger in {"manual", "scheduled"}:
        return {
            "parallel_pilot_required": True,
            "parallel_pilot_repetitions": 1,
            "parallel_pilot_reason": f"explicit-{trigger}-drift-sample",
        }
    if tier == "C":
        return {
            "parallel_pilot_required": True,
            "parallel_pilot_repetitions": 2,
            "parallel_pilot_reason": "tier-C-certification",
        }
    if normalised & {path.lower() for path in PILOT_MECHANICS_PATHS}:
        return {
            "parallel_pilot_required": True,
            "parallel_pilot_repetitions": 2,
            "parallel_pilot_reason": "pilot-mechanics-or-ISSUE-0180-change",
        }
    for path in normalised:
        name = PurePosixPath(path).name
        if name in PILOT_PARTITION_NAMES or path == "pyproject.toml":
            return {
                "parallel_pilot_required": True,
                "parallel_pilot_repetitions": 2,
                "parallel_pilot_reason": "pytest-partition-or-collection-change",
            }
        if name in PILOT_ENVIRONMENT_NAMES:
            return {
                "parallel_pilot_required": True,
                "parallel_pilot_repetitions": 2,
                "parallel_pilot_reason": "release-dependency-or-python-environment-change",
            }
        if any(token in path for token in ("concurrency", "persistence", "windows", "atomic", "isolation")):
            return {
                "parallel_pilot_required": True,
                "parallel_pilot_repetitions": 2,
                "parallel_pilot_reason": "concurrency-persistence-sharing-atomic-or-isolation-change",
            }
    return {
        "parallel_pilot_required": False,
        "parallel_pilot_repetitions": 0,
        "parallel_pilot_reason": "no-pilot-trigger-for-this-change",
    }


def derive_trusted_evidence(
    root: Path,
    *,
    base: str,
    head: str,
    artifact_manifest: str,
    reusable_evidence: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Validate prior reviewed evidence against the current E change."""

    if not re.fullmatch(r"[0-9a-f]{40}", base) or not re.fullmatch(r"[0-9a-f]{40}", head):
        return None
    if not isinstance(reusable_evidence, dict):
        return None
    reviewed_base = reusable_evidence.get("base_sha")
    reviewed_head = reusable_evidence.get("head_sha")
    if not isinstance(reviewed_base, str) or not re.fullmatch(
        r"[0-9a-f]{40}", reviewed_base
    ):
        return None
    if not isinstance(reviewed_head, str) or not re.fullmatch(
        r"[0-9a-f]{40}", reviewed_head
    ):
        return None
    groups = {
        "source_sha256": ("src", "scripts"),
        "dependency_sha256": (
            "pyproject.toml",
            "requirements-release.txt",
            "requirements-release-parsers.txt",
        ),
        "product_tree_sha256": ("src", "configs"),
        "policy_sha256": (
            "AGENTS.md",
            ".github/workflows",
            "configs",
            "docs/product-completion/DELIVERY_WORKFLOW.md",
            artifact_manifest,
        ),
        "environment_sha256": ("pyproject.toml", "requirements-release.txt", "requirements-release-parsers.txt"),
    }
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", reviewed_base, reviewed_head],
            cwd=root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", reviewed_head, base],
            cwd=root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", base, head],
            cwd=root,
            check=True,
            capture_output=True,
        )
        identities: dict[str, object] = {
            "base_sha": reviewed_base,
            "head_sha": reviewed_head,
        }
        for key, paths in groups.items():
            digests = {
                _git_identity(root, ref, paths)
                for ref in (reviewed_head, base, head)
            }
            if len(digests) != 1:
                return None
            identities[key] = digests.pop()
        artifacts = [
            subprocess.check_output(
                ["git", "show", f"{ref}:{artifact_manifest}"], cwd=root
            )
            for ref in (reviewed_head, base, head)
        ]
        if len(set(artifacts)) != 1:
            return None
    except (OSError, subprocess.CalledProcessError):
        return None
    identities["artifact_manifest_sha256"] = (
        __import__("hashlib").sha256(artifacts[0]).hexdigest()
    )
    identities["execution_allowed"] = False
    return identities


def build_report(
    paths: list[str],
    *,
    ordinary_issues_since_full_gate: int | None = None,
    cadence: dict[str, object] | None = None,
    reusable_evidence: dict[str, object] | None = None,
    expected_evidence: dict[str, object] | None = None,
    pilot_trigger: str | None = None,
) -> dict[str, object]:
    classified = sorted((classify_path(path) for path in paths), key=lambda item: item.path)
    if not classified:
        classified = [PathClassification("<no-changes>", "H", "empty-change-set-fails-upward")]
    tier = max((item.tier for item in classified), key=TIER_ORDER.__getitem__)
    if cadence is None:
        cadence = (
            {
                "known": False,
                "source": "missing-library-cadence",
                "issues_since_last_full_gate": None,
                "threshold": 2,
                "due": True,
                "reason": "missing-cadence-fails-upward",
            }
            if ordinary_issues_since_full_gate is None
            else {
                "known": ordinary_issues_since_full_gate >= 0,
                "source": "explicit-test-or-library-input",
                "issues_since_last_full_gate": ordinary_issues_since_full_gate,
                "threshold": 2,
                "due": (
                    ordinary_issues_since_full_gate < 0
                    or ordinary_issues_since_full_gate >= 2
                ),
                "reason": (
                    "explicit-test-or-library-input"
                    if ordinary_issues_since_full_gate >= 0
                    else "malformed-negative-cadence-override"
                ),
            }
        )
    cadence_known = cadence.get("known") is True
    cadence_count = cadence.get("issues_since_last_full_gate")
    cadence_due = cadence.get("due") is True
    evidence_reuse_authorized = tier == "E" and _valid_reusable_evidence(
        reusable_evidence, expected_evidence
    )
    package_gate_required = (tier == "O" and (not cadence_known or cadence_due)) or tier in {"H", "C"} or (
        tier == "E" and not evidence_reuse_authorized
    )
    pilot = parallel_pilot_plan(paths, tier=tier, trigger=pilot_trigger)
    if pilot_trigger in {"manual", "manual-full", "scheduled"} and not paths:
        # A no-change drift sample is evidence-only. It exercises preflight,
        # supply-chain and the report-only pilot without invoking a signed
        # release or changing serial authority for any repository diff.
        package_gate_required = False
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "package_gate_required": package_gate_required,
        "ordinary_full_gate_cadence": {
            "source": cadence.get("source", "unknown"),
            "issues_since_last_full_gate": cadence_count,
            "threshold": cadence.get("threshold", 2),
            "due": cadence_due,
            "known": cadence_known,
            "reason": cadence.get("reason", "unknown"),
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
        **pilot,
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


def _load_base_reusable_evidence(
    root: Path, *, base: str, head: str, path: Path
) -> dict[str, object] | None:
    try:
        candidate = path if path.is_absolute() else root / path
        relative = candidate.resolve().relative_to(root).as_posix()
        base_payload = subprocess.check_output(
            ["git", "show", f"{base}:{relative}"], cwd=root
        )
        head_payload = subprocess.check_output(
            ["git", "show", f"{head}:{relative}"], cwd=root
        )
        if base_payload != head_payload:
            return None
        value = json.loads(base_payload)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError):
        return None
    return value if isinstance(value, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--ordinary-issues-since-full-gate", type=int)
    parser.add_argument("--pilot-trigger", choices=("manual", "manual-full", "scheduled"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reuse-evidence", type=Path)
    parser.add_argument(
        "--artifact-manifest",
        default=".github/issue-transitions/protected-evidence-manifest.json",
    )
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
    if args.reuse_evidence and args.base:
        reusable_evidence = _load_base_reusable_evidence(
            args.root.resolve(),
            base=args.base,
            head=args.head,
            path=args.reuse_evidence,
        )
    expected_evidence = None
    if args.base and reusable_evidence:
        expected_evidence = derive_trusted_evidence(
            args.root.resolve(),
            base=args.base,
            head=args.head,
            artifact_manifest=args.artifact_manifest,
            reusable_evidence=reusable_evidence,
        )
    cadence = (
        derive_ordinary_gate_cadence(
            args.root.resolve(), base=args.base, main_ref=args.main_ref
        )
        if args.ordinary_issues_since_full_gate is None
        else {
            "known": args.ordinary_issues_since_full_gate >= 0,
            "source": "explicit-cli-cadence",
            "issues_since_last_full_gate": args.ordinary_issues_since_full_gate,
            "threshold": 2,
            "due": (
                args.ordinary_issues_since_full_gate < 0
                or args.ordinary_issues_since_full_gate >= 2
            ),
            "reason": (
                "explicit-cli-cadence"
                if args.ordinary_issues_since_full_gate >= 0
                else "malformed-negative-cadence-override"
            ),
        }
    )
    report = build_report(
        paths,
        cadence=cadence,
        reusable_evidence=reusable_evidence,
        expected_evidence=expected_evidence,
        pilot_trigger=args.pilot_trigger,
    )
    if classification_error:
        report["classification_error"] = classification_error
        report["package_gate_required"] = True
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
