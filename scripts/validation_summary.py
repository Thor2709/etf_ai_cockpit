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

try:
    from scripts.issue_registry_core import (
        control_state_record,
        load_control_state_at,
        validate_status_replay_prefix_shape,
    )
except ModuleNotFoundError:
    from issue_registry_core import (  # type: ignore[no-redef]
        control_state_record,
        load_control_state_at,
        validate_status_replay_prefix_shape,
    )


SCHEMA_VERSION = "validation-summary.v1"
IDENTITY_KEYS = {
    "environment",
    "source",
    "dependency",
    "product_tree",
    "policy",
}
JOB_KEYS = {"classifier", "preflight", "supply_chain", "release_windows", "release_linux"}
CANDIDATE_PATH = ".github/issue-transitions/post-merge-control-candidate.json"
CANDIDATE_EVIDENCE_SCHEMA = "etf-ai-cockpit.status-completion-evidence/1.0"
CANDIDATE_REPLAY_SCHEMA = "etf-ai-cockpit.status-replay-candidate/3.0"
CANDIDATE_UPDATE_KEYS = {"stable_id", "from_status", "to_status"}
CANDIDATE_ARTIFACT_PREFIX = "validation-status-completion-candidate-"
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
STABLE_ID_RE = re.compile(r"(?:ISSUE|UPDATEV2)-[0-9]{4}")
CLASSIFIER_TIERS = {"E", "O", "H", "C"}


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


def _candidate_changed(classifier: dict[str, Any]) -> bool:
    paths = classifier.get("paths")
    if not isinstance(paths, list) or not paths:
        raise ValueError("classifier paths are missing or malformed")
    seen_paths: set[str] = set()
    for item in paths:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or item.get("tier") not in CLASSIFIER_TIERS
            or not isinstance(item.get("reason"), str)
            or not item["reason"]
        ):
            raise ValueError("classifier paths are missing or malformed")
        if item["path"] in seen_paths:
            raise ValueError("classifier contains duplicate paths")
        seen_paths.add(item["path"])
    return CANDIDATE_PATH in seen_paths


def _load_committed_candidate(root: Path, head: str) -> dict[str, Any]:
    try:
        payload = subprocess.check_output(
            ["git", "show", f"{head}:{CANDIDATE_PATH}"],
            cwd=root,
            text=True,
        )
        candidate = json.loads(payload)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise ValueError("committed status-completion candidate is unavailable or malformed") from exc
    if not isinstance(candidate, dict):
        raise ValueError("committed status-completion candidate must be a JSON object")
    return candidate


def _committed_candidate_blob_sha256(root: Path, head: str) -> str:
    payload = subprocess.check_output(
        ["git", "show", f"{head}:{CANDIDATE_PATH}"], cwd=root
    )
    return hashlib.sha256(payload).hexdigest()


def _control_state_record_at(root: Path, ref: str, stable_id: str) -> dict[str, Any]:
    return control_state_record(
        load_control_state_at(root, ref), stable_id, context="validation"
    )


def _validate_candidate_evidence(
    root: Path,
    artifacts_root: Path,
    *,
    base: str,
    head: str,
) -> None:
    paths = list(artifacts_root.rglob("status-completion-candidate.json"))
    if len(paths) != 1:
        raise ValueError("exactly one status-completion candidate evidence artifact is required")
    evidence_path = paths[0]
    if (
        evidence_path.parent.parent != artifacts_root
        or not evidence_path.parent.name.startswith(CANDIDATE_ARTIFACT_PREFIX)
        or evidence_path.parent.name == CANDIDATE_ARTIFACT_PREFIX
    ):
        raise ValueError("status-completion candidate evidence artifact provenance is invalid")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("status-completion candidate evidence is malformed") from exc
    if not isinstance(evidence, dict):
        raise ValueError("status-completion candidate evidence must be a JSON object")
    if evidence.get("schema_version") != CANDIDATE_EVIDENCE_SCHEMA:
        raise ValueError("status-completion candidate evidence schema mismatch")
    candidate = _load_committed_candidate(root, head)
    if candidate.get("schema_version") == CANDIDATE_REPLAY_SCHEMA:
        _validate_replay_candidate_evidence(
            evidence, candidate, root=root, base=base, head=head
        )
        return
    if (
        evidence.get("mode") != "validate"
        or evidence.get("execution_allowed") is not False
        or evidence.get("terminal_status") != "validated"
        or evidence.get("zero_action_readback") is not None
    ):
        raise ValueError("status-completion candidate evidence is not terminally validated")
    if evidence.get("expected_parent_sha") != base:
        raise ValueError("status-completion candidate evidence base SHA mismatch")
    if evidence.get("expected_head_sha") != head:
        raise ValueError("status-completion candidate evidence head SHA mismatch")
    candidate_bindings = {
        "execution_allowed": "execution authority",
        "expected_parent_sha": "expected parent",
        "authority_ref": "authority reference",
        "remote_inventory_sha256": "remote inventory",
        "plan_semantic_sha256": "semantic plan",
        "expected_update": "expected update",
    }
    for key, label in candidate_bindings.items():
        if evidence.get(key) != candidate.get(key):
            raise ValueError(f"status-completion candidate {label} identity mismatch")
    if not HASH_RE.fullmatch(str(evidence.get("remote_inventory_sha256", ""))):
        raise ValueError("status-completion candidate remote inventory identity is invalid")
    if not HASH_RE.fullmatch(str(evidence.get("plan_semantic_sha256", ""))):
        raise ValueError("status-completion candidate plan identity is invalid")
    if not HASH_RE.fullmatch(str(evidence.get("authority_ref", ""))):
        raise ValueError("status-completion candidate authority identity is invalid")
    candidate_blob_sha256 = str(evidence.get("candidate_blob_sha256", ""))
    if (
        not HASH_RE.fullmatch(candidate_blob_sha256)
        or candidate_blob_sha256 != _committed_candidate_blob_sha256(root, head)
    ):
        raise ValueError("status-completion candidate canonical blob identity is invalid")
    expected_update = evidence.get("expected_update")
    if (
        not isinstance(expected_update, dict)
        or set(expected_update) != CANDIDATE_UPDATE_KEYS
        or not STABLE_ID_RE.fullmatch(str(expected_update.get("stable_id", "")))
        or not isinstance(expected_update.get("from_status"), str)
        or not expected_update.get("from_status")
        or expected_update.get("to_status") != "integrated"
    ):
        raise ValueError("status-completion candidate expected update identity is invalid")
    action_scope = evidence.get("action_scope")
    if (
        not isinstance(action_scope, list)
        or len(action_scope) != 1
        or not isinstance(action_scope[0], dict)
        or action_scope[0].get("kind") != "update"
        or action_scope[0].get("stable_id") != expected_update["stable_id"]
        or action_scope[0].get("managed_field_deltas") != ["Programme status"]
        or not isinstance(action_scope[0].get("remote_number"), int)
    ):
        raise ValueError("status-completion candidate action scope identity is invalid")
    mutation = evidence.get("mutation")
    if (
        not isinstance(mutation, dict)
        or mutation.get("transport") != "github_issue_comment_append"
        or mutation.get("candidate_blob_sha256") != candidate_blob_sha256
        or not HASH_RE.fullmatch(str(mutation.get("authority_id", "")))
        or not re.fullmatch(
            r"[0-9a-f]{40,64}", str(mutation.get("candidate_blob_oid", ""))
        )
        or mutation.get("plan_sha256") != evidence.get("plan_semantic_sha256")
        or not isinstance(mutation.get("predecessor_event_id"), str)
        or not mutation.get("predecessor_event_id")
        or not HASH_RE.fullmatch(str(mutation.get("predecessor_event_sha256", "")))
    ):
        raise ValueError("status-completion candidate comment event identity is invalid")


def _validate_replay_candidate_evidence(
    evidence: dict[str, Any],
    candidate: dict[str, Any],
    *,
    root: Path,
    base: str,
    head: str,
) -> None:
    if (
        evidence.get("mode") != "validate"
        or evidence.get("execution_allowed") is not False
        or evidence.get("terminal_status") != "validated"
        or evidence.get("zero_action_readback") is not None
        or evidence.get("expected_parent_sha") != base
        or evidence.get("expected_head_sha") != head
    ):
        raise ValueError("status replay candidate evidence is not terminally validated")
    for key in (
        "execution_allowed",
        "expected_parent_sha",
        "authority_ref",
        "remote_inventory_sha256",
        "plan_semantic_sha256",
        "expected_replay",
    ):
        if evidence.get(key) != candidate.get(key):
            raise ValueError(f"status replay candidate {key} identity mismatch")
    replay = candidate.get("expected_replay")
    if (
        not isinstance(replay, dict)
        or set(replay)
        != {
            "stable_id",
            "issue_number",
            "from_status",
            "to_status",
            "reviewed_product_commit",
            "transition_history_prefix",
            "transition_history_append",
            "acceptance_evidence_prefix",
            "acceptance_evidence_append",
        }
        or replay.get("from_status") != "in_progress"
        or replay.get("to_status") != "integrated"
        or not isinstance(replay.get("transition_history_append"), list)
        or len(replay["transition_history_append"]) != 2
        or not isinstance(replay.get("acceptance_evidence_append"), list)
        or len(replay["acceptance_evidence_append"]) != 2
        or not SHA_RE.fullmatch(str(replay.get("reviewed_product_commit", "")))
    ):
        raise ValueError("status replay candidate canonical contract is invalid")
    try:
        from scripts.github_mutation_gateway import _validate_replay_hops
    except ModuleNotFoundError:
        from github_mutation_gateway import _validate_replay_hops  # type: ignore[no-redef]
    hops = _validate_replay_hops(
        replay["transition_history_append"],
        reviewed_product_commit=str(replay["reviewed_product_commit"]),
    )
    stable_id = str(replay["stable_id"])
    source_record = _control_state_record_at(root, base, stable_id)
    current_record = _control_state_record_at(root, head, stable_id)
    validate_status_replay_prefix_shape(
        stable_id,
        replay.get("transition_history_prefix"),
        replay.get("acceptance_evidence_prefix"),
        programme_status=replay.get("from_status"),
        dependency_edge_evidence=source_record.get("dependency_edge_evidence"),
        verified_commit=source_record.get("verified_commit"),
        verified_date=source_record.get("verified_date"),
        status_transition=source_record.get("status_transition"),
    )
    validate_status_replay_prefix_shape(
        stable_id,
        source_record.get("transition_history"),
        source_record.get("acceptance_evidence"),
        programme_status=source_record.get("programme_status"),
        dependency_edge_evidence=source_record.get("dependency_edge_evidence"),
        verified_commit=source_record.get("verified_commit"),
        verified_date=source_record.get("verified_date"),
        status_transition=source_record.get("status_transition"),
    )
    validate_status_replay_prefix_shape(
        stable_id,
        current_record.get("transition_history"),
        current_record.get("acceptance_evidence"),
        programme_status=current_record.get("programme_status"),
        dependency_edge_evidence=current_record.get("dependency_edge_evidence"),
        verified_commit=current_record.get("verified_commit"),
        verified_date=current_record.get("verified_date"),
        status_transition=current_record.get("status_transition"),
    )
    if (
        replay["transition_history_prefix"] != source_record.get("transition_history")
        or replay["acceptance_evidence_prefix"]
        != source_record.get("acceptance_evidence")
        or current_record.get("transition_history")
        != replay["transition_history_prefix"] + hops
        or current_record.get("acceptance_evidence")
        != replay["acceptance_evidence_prefix"]
        + replay["acceptance_evidence_append"]
    ):
        raise ValueError("status replay candidate source-bound append is invalid")
    for hop, acceptance in zip(
        hops, replay["acceptance_evidence_append"], strict=True
    ):
        if (
            not isinstance(acceptance, dict)
            or set(acceptance)
            != {
                "status",
                "evidence_references",
                "review_reference",
                "reviewer",
                "reviewed_date",
            }
            or acceptance.get("status") != hop["to"]
            or any(
                acceptance.get(key) != hop.get(key)
                for key in (
                    "evidence_references",
                    "review_reference",
                    "reviewer",
                    "reviewed_date",
                )
            )
        ):
            raise ValueError("status replay candidate acceptance evidence is invalid")
    try:
        from scripts.apply_reviewed_status_completion import project_status_replay_record
    except ModuleNotFoundError:
        from apply_reviewed_status_completion import (  # type: ignore[no-redef]
            project_status_replay_record,
        )
    if project_status_replay_record(
        source_record,
        hops,
        replay["acceptance_evidence_append"],
        stable_id=str(replay["stable_id"]),
    ) != current_record:
        raise ValueError("status replay candidate complete canonical projection is invalid")
    candidate_blob_sha256 = str(evidence.get("candidate_blob_sha256", ""))
    if (
        not HASH_RE.fullmatch(candidate_blob_sha256)
        or candidate_blob_sha256 != _committed_candidate_blob_sha256(root, head)
    ):
        raise ValueError("status replay candidate canonical blob identity is invalid")
    action_scope = evidence.get("action_scope")
    if (
        not isinstance(action_scope, list)
        or len(action_scope) != 1
        or not isinstance(action_scope[0], dict)
        or action_scope[0].get("kind") != "update"
        or action_scope[0].get("stable_id") != replay["stable_id"]
        or action_scope[0].get("managed_field_deltas") != ["Programme status"]
        or action_scope[0].get("remote_number") != replay["issue_number"]
    ):
        raise ValueError("status replay candidate action scope identity is invalid")
    mutation = evidence.get("mutation")
    if (
        not isinstance(mutation, dict)
        or mutation.get("transport") != "github_issue_comment_append"
        or mutation.get("transport_contract") != "one_aggregate_proposal_one_receipt"
        or mutation.get("replay_hops") != replay["transition_history_append"]
        or mutation.get("reviewed_product_commit") != replay["reviewed_product_commit"]
        or mutation.get("candidate_blob_sha256") != evidence.get("candidate_blob_sha256")
        or mutation.get("plan_sha256") != evidence.get("plan_semantic_sha256")
        or not HASH_RE.fullmatch(str(mutation.get("authority_id", "")))
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(mutation.get("candidate_blob_oid", "")))
    ):
        raise ValueError("status replay candidate mutation identity is invalid")


def collect_summary(
    root: Path,
    artifacts_root: Path,
    *,
    base: str,
    head: str,
    job_results: dict[str, str],
) -> dict[str, Any]:
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        raise ValueError("validation summary base and head must be full lowercase Git SHAs")
    classifier_paths = list(artifacts_root.rglob("classifier.json"))
    if len(classifier_paths) != 1:
        raise ValueError("exactly one classifier artifact is required")
    classifier = json.loads(classifier_paths[0].read_text(encoding="utf-8"))
    if _candidate_changed(classifier):
        _validate_candidate_evidence(root, artifacts_root, base=base, head=head)
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
        artifact_name = path.relative_to(artifacts_root).parts[0].lower()
        if not artifact_name.startswith("release-gate-"):
            continue
        if "windows" in artifact_name:
            platform = "windows"
        elif "linux" in artifact_name:
            platform = "linux"
        else:
            continue
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
