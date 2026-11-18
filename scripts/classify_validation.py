"""Classify a change into the repository validation tiers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


try:
    from scripts import select_focused_tests as focused_selection
    from scripts.git_change_paths import changed_paths
    from scripts.validation_identity import DEFAULT_ARTIFACT_MANIFEST, identity_groups
except ImportError:  # also pywin32's top-level 'scripts' namespace
    import select_focused_tests as focused_selection  # type: ignore[no-redef]
    from git_change_paths import changed_paths  # type: ignore[no-redef]
    from validation_identity import DEFAULT_ARTIFACT_MANIFEST, identity_groups  # type: ignore[no-redef]


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
HIGH_RISK_EXACT_PATHS = {
    "src/etf_cockpit/data/market_adjustments.py",
    "src/etf_cockpit/audit/thesis_diary.py",
    "src/etf_cockpit/data/universe_import.py",
}
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
    "requirements-quant.txt",
}
CERTIFICATION_PREFIXES = (
    "docs/product-completion/certification/",
    "artifacts/certification/",
)
PROTECTED_POLICY_PATHS = {
    "docs/product-completion/delivery_workflow.md",
}
# Prose is documentation: tier O, unless a policy identity path or a protected prefix holds it.
PROSE_SUFFIXES = {".md", ".rst", ".txt"}
PROTECTED_PROSE_PREFIXES = (
    "artifacts/",
    "docs/architecture/decisions/",
    "docs/codex-config/",
    "docs/product-completion/",
)
# Risk words name product code. Tests and UI pages cannot change a financial result alone.
TOKEN_EXEMPT_PREFIXES = ("tests/", "src/etf_cockpit/app/")
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
    if (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or ".." in PurePosixPath(path).parts
            or not path or path == "." or path.startswith("../") or PurePosixPath(path).is_absolute()):
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
    policy = [item.lower() for item in identity_groups()["policy"]]
    # The two plans/ entry point files stay in the policy identity hash, but their prose is tier O.
    prose = parsed_path.suffix in PROSE_SUFFIXES and not any(
        (lowered == item and not item.startswith("plans/")) or lowered.startswith(item + "/") for item in policy
    ) and not lowered.startswith(PROTECTED_PROSE_PREFIXES) and not parsed_path.name.lower().startswith("adr-")
    risk_words = not prose and not lowered.startswith(TOKEN_EXEMPT_PREFIXES)
    if (
        lowered in PROTECTED_POLICY_PATHS
        or lowered in HIGH_RISK_EXACT_PATHS
        or path in HIGH_RISK_NAMES
        or any(lowered.startswith(prefix.lower()) for prefix in HIGH_RISK_PREFIXES)
        or (parsed_path.name.endswith("_store.py") and not lowered.startswith("tests/"))
        or (risk_words and bool((parts | semantic_tokens) & HIGH_RISK_PARTS))
        or lowered.startswith("requirements")
    ):
        return PathClassification(path, "H", "protected-or-high-risk-surface")
    if prose:
        return PathClassification(path, "O", "prose-documentation")
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
    reusable_evidence: dict[str, object] | None = None,
    diagnostics: list[str] | None = None,
) -> dict[str, object] | None:
    """Validate prior reviewed evidence against the current E change.

    Optional diagnostics explain rejection without creating another authority.
    """
    def reject(reason: str) -> dict[str, object] | None:
        if diagnostics is not None:
            diagnostics.append(reason)
        return None

    if not re.fullmatch(r"[0-9a-f]{40}", base) or not re.fullmatch(r"[0-9a-f]{40}", head):
        return reject("malformed_current_base_or_head")
    if not isinstance(reusable_evidence, dict):
        return reject("missing_reusable_evidence")
    reviewed_base = reusable_evidence.get("base_sha")
    reviewed_head = reusable_evidence.get("head_sha")
    if not isinstance(reviewed_base, str) or not re.fullmatch(
        r"[0-9a-f]{40}", reviewed_base
    ):
        return reject("malformed_reviewed_base")
    if not isinstance(reviewed_head, str) or not re.fullmatch(
        r"[0-9a-f]{40}", reviewed_head
    ):
        return reject("malformed_reviewed_head")
    groups = {f"{key}_sha256": paths for key, paths in identity_groups(artifact_manifest).items()}
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
                return reject("protected_identity_changed:" + key)
            identities[key] = digests.pop()
        artifacts = [
            subprocess.check_output(
                ["git", "show", f"{ref}:{artifact_manifest}"], cwd=root
            )
            for ref in (reviewed_head, base, head)
        ]
        if len(set(artifacts)) != 1:
            return reject("protected_artifact_manifest_changed")
        # The base-approved catalogue must identify the source actually certified,
        # not merely contain an unrelated old green run and a self-consistent hash.
        manifest = json.loads(artifacts[0])
        artifact = manifest.get("artifact_identity") if isinstance(manifest, dict) else None
        if (not isinstance(artifact, dict)
                or manifest.get("schema_version") != "protected-evidence-manifest.v1"
                or manifest.get("execution_allowed") is not False
                or artifact.get("terminal_result") != "success"
                or not isinstance(artifact.get("reviewed_head_sha"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", artifact["reviewed_head_sha"])
                or any(type(artifact.get(key)) is not int or artifact[key] < 1 for key in
                       ("release_gate_run_id", "release_gate_attempt", "linux_junit_tests", "windows_junit_tests"))):
            return reject("unverifiable_certified_artifact_identity")
        certified_head = artifact["reviewed_head_sha"]
        subprocess.run(["git", "merge-base", "--is-ancestor", certified_head, reviewed_head],
                       cwd=root, check=True, capture_output=True)
        for key, paths in groups.items():
            # The evidence catalogue is necessarily written after its certified
            # commit. Exclude only that catalogue for this additional comparison;
            # ALL existing reviewed/base/head equality checks above remain intact.
            source_paths = tuple(path for path in paths if path != artifact_manifest)
            if _git_identity(root, certified_head, source_paths) != _git_identity(root, reviewed_head, source_paths):
                return reject("certified_artifact_source_identity_changed:" + key)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return reject("ancestry_or_required_git_object_unverifiable")
    identities["artifact_manifest_sha256"] = (
        __import__("hashlib").sha256(artifacts[0]).hexdigest()
    )
    identities["execution_allowed"] = False
    return identities


def certification_candidate(
    root: Path, base: str, head: str, artifact_manifest: str = DEFAULT_ARTIFACT_MANIFEST
) -> str | None:
    """Return the merged pull request head that introduced the protected identity of ``head``.

    The exact-head package gate of that head is the only run that can certify this source. The
    artifact manifest is evidence written after certification, so it is excluded, as in
    ``derive_trusted_evidence``. The workflow confirms the run through the GitHub API.
    """
    paths = tuple(sorted({path for group in identity_groups(artifact_manifest).values()
                          for path in group if path != artifact_manifest}))
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=root, check=True, capture_output=True)
        target = _git_identity(root, head, paths)
        commit = base
        if _git_identity(root, commit, paths) != target:
            return None
        for _ in range(50):
            parents = subprocess.check_output(
                ["git", "rev-list", "--parents", "-n1", commit], cwd=root, text=True
            ).split()[1:]
            if not parents:
                return None
            if _git_identity(root, parents[0], paths) != target:
                # This merge introduced the identity: its merged head carries the certifying run.
                if len(parents) == 2 and _git_identity(root, parents[1], paths) == target:
                    return parents[1]
                return None
            commit = parents[0]
    except (OSError, subprocess.CalledProcessError):
        return None
    return None


def build_report(
    paths: list[str],
    *,
    reusable_evidence: dict[str, object] | None = None,
    expected_evidence: dict[str, object] | None = None,
    whole_suite_selection: bool = False,
    certified_run: dict[str, object] | None = None,
) -> dict[str, object]:
    classified = sorted((classify_path(path) for path in paths), key=lambda item: item.path)
    if not classified:
        classified = [PathClassification("<no-changes>", "H", "empty-change-set-fails-upward")]
    tier = max((item.tier for item in classified), key=TIER_ORDER.__getitem__)
    sidecar_reuse = tier == "E" and _valid_reusable_evidence(
        reusable_evidence, expected_evidence
    )
    # A run passed here was verified by the workflow and bound to certification_candidate by main().
    certified_reuse = tier == "E" and not sidecar_reuse and certified_run is not None
    evidence_reuse_authorized = sidecar_reuse or certified_reuse
    # Tier O runs the focused tests, or the gate when that selection is the whole suite.
    # The scheduled run on main has no changed paths, so it fails upward to the full gate.
    package_gate_required = tier in {"H", "C"} or (tier == "E" and not evidence_reuse_authorized)
    reasons = {item.reason for item in classified}
    if tier == "O" and whole_suite_selection:
        package_gate_required = True
        reasons.add("whole-suite-focused-selection")
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "package_gate_required": package_gate_required,
        "paths": [
            {"path": item.path, "tier": item.tier, "reason": item.reason}
            for item in classified
        ],
        "reasons": sorted(reasons),
        "evidence_reuse": {
            "authorized": evidence_reuse_authorized,
            "reason": (
                "exact-identities-validated" if sidecar_reuse
                else "certified-run-identity-validated" if certified_reuse
                else "absent-incomplete-or-inconsistent"
            ),
            "certified_run": certified_run if certified_reuse else None,
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
    return changed_paths(root, base, head)


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
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reuse-evidence", type=Path)
    parser.add_argument(
        "--artifact-manifest",
        default=".github/issue-transitions/protected-evidence-manifest.json",
    )
    parser.add_argument("--certification-candidate", action="store_true",
                        help="print the head whose green package gate can certify --head, then exit")
    parser.add_argument("--certified-run", type=Path,
                        help='workflow-verified {"head_sha", "run_id"} of a green package gate')
    args = parser.parse_args(argv)

    candidate = None
    if args.base and (args.certification_candidate or args.certified_run):
        candidate = certification_candidate(args.root.resolve(), args.base, args.head, args.artifact_manifest)
    if args.certification_candidate:
        print(candidate or "")
        return 0
    certified_run = None
    if args.certified_run and candidate:
        try:
            value = json.loads(args.certified_run.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = None
        try:  # The manifest is excluded from the identity, but never from execution_allowed=false.
            manifest = json.loads(subprocess.check_output(
                ["git", "show", f"{args.head}:{args.artifact_manifest}"], cwd=args.root.resolve()))
        except (OSError, ValueError, subprocess.CalledProcessError):
            manifest = None
        if (isinstance(value, dict) and set(value) == {"head_sha", "run_id"}
                and value["head_sha"] == candidate
                and type(value["run_id"]) is int and value["run_id"] > 0
                and isinstance(manifest, dict) and manifest.get("execution_allowed") is False):
            certified_run = value

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
    report = build_report(
        paths,
        reusable_evidence=reusable_evidence,
        expected_evidence=expected_evidence,
        certified_run=certified_run,
    )
    if classification_error:
        report["classification_error"] = classification_error
        report["package_gate_required"] = True
    elif report["tier"] == "O" and args.base:
        # A selection of more than LARGE_SELECTION files runs the whole suite: run it as the
        # sharded package gate on both platforms, not on one focused runner.  Fails upward.
        try:
            selected = focused_selection.select_tests(args.root.resolve(), paths)
            whole_suite = len(selected) > focused_selection.LARGE_SELECTION
        except (OSError, focused_selection.SelectionError):
            whole_suite = True
        if whole_suite:
            report = build_report(
                paths,
                reusable_evidence=reusable_evidence,
                expected_evidence=expected_evidence,
                whole_suite_selection=True,
            )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
