"""Guard canonical programme status changes against an explicit JSON manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.issue_registry_core import (
        PROGRESS_PATH,
        PROGRAMME_STATUSES,
        REGISTRY_PATH,
        SOURCE_MANIFEST,
        STATUS_PATH,
        sha256_text_file,
        deterministic_json,
    )
    from scripts.update_programme_status import (
        deterministic_text,
        progress_markdown,
        status_payload,
    )
except ModuleNotFoundError:
    from issue_registry_core import (  # type: ignore[no-redef]
        PROGRESS_PATH,
        PROGRAMME_STATUSES,
        REGISTRY_PATH,
        SOURCE_MANIFEST,
        STATUS_PATH,
        sha256_text_file,
        deterministic_json,
    )
    from update_programme_status import (  # type: ignore[no-redef]
        deterministic_text,
        progress_markdown,
        status_payload,
    )


ISSUE_ID_RE = re.compile(r"^(?:ISSUE|UPDATEV2)-\d{4}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MANIFEST_KEYS = {
    "schema_version",
    "base_commit",
    "branch",
    "issue_ids",
    "allowed_status_transitions",
    "allow_other_status_changes",
    "allow_downgrades",
    "allow_downgrade",
    "reason",
}
TRANSITION_KEYS = {"issue_id", "from", "to"}

# This is deliberately conservative: only a forward movement through the
# normal programme lifecycle is non-downgrading. Other statuses are treated as
# lower-authority states when moving from an implemented or terminal state.
STATUS_ORDER = {
    "planned": 10,
    "ready": 20,
    "in_progress": 30,
    "implemented": 40,
    "implemented_initially": 40,
    "hardening_required": 50,
    "integrated": 60,
    "closed": 70,
}
HIGH_STATUS = {
    "implemented",
    "implemented_initially",
    "hardening_required",
    "integrated",
    "closed",
}


def _error(errors: list[str], message: str) -> None:
    if message not in errors:
        errors.append(message)


def _issue_map(registry: Mapping[str, Any], label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    records = registry.get("records")
    if not isinstance(records, list):
        _error(errors, f"{label} registry records must be a list")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            _error(errors, f"{label} registry record {index} is not an object")
            continue
        issue_id = record.get("canonical_id")
        if not isinstance(issue_id, str) or not ISSUE_ID_RE.fullmatch(issue_id):
            _error(errors, f"{label} registry has invalid issue ID at record {index}")
            continue
        if issue_id in result:
            _error(errors, f"{label} registry has duplicate issue ID: {issue_id}")
            continue
        result[issue_id] = record
    return result


def _is_downgrade(previous: str, proposed: str) -> bool:
    if previous in STATUS_ORDER and proposed in STATUS_ORDER:
        return STATUS_ORDER[proposed] < STATUS_ORDER[previous]
    return previous in HIGH_STATUS and proposed not in HIGH_STATUS


def _manifest_errors(manifest: Mapping[str, Any]) -> tuple[list[str], set[str], dict[str, dict[str, str]]]:
    errors: list[str] = []
    if set(manifest) - MANIFEST_KEYS:
        _error(errors, "manifest contains unsupported keys")
    if manifest.get("schema_version") != "1.0":
        _error(errors, "manifest schema_version must be '1.0'")
    base_commit = manifest.get("base_commit")
    if not isinstance(base_commit, str) or not COMMIT_RE.fullmatch(base_commit):
        _error(errors, "manifest base_commit must be a 40-character commit SHA")
    branch = manifest.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        _error(errors, "manifest branch must be non-blank")

    issue_ids_value = manifest.get("issue_ids")
    issue_ids: set[str] = set()
    if not isinstance(issue_ids_value, list):
        _error(errors, "manifest issue_ids must be a list")
    else:
        for issue_id in issue_ids_value:
            if not isinstance(issue_id, str) or not ISSUE_ID_RE.fullmatch(issue_id):
                _error(errors, "manifest issue_ids contains an invalid issue ID")
            elif issue_id in issue_ids:
                _error(errors, f"manifest issue_ids contains duplicate issue ID: {issue_id}")
            else:
                issue_ids.add(issue_id)

    transitions_value = manifest.get("allowed_status_transitions")
    transitions: dict[str, dict[str, str]] = {}
    if not isinstance(transitions_value, list):
        _error(errors, "manifest allowed_status_transitions must be a list")
    else:
        for transition in transitions_value:
            if not isinstance(transition, dict) or set(transition) != TRANSITION_KEYS:
                _error(errors, "manifest transition must contain only issue_id, from and to")
                continue
            issue_id = transition.get("issue_id")
            previous = transition.get("from")
            proposed = transition.get("to")
            if (
                not isinstance(issue_id, str)
                or not ISSUE_ID_RE.fullmatch(issue_id)
                or not isinstance(previous, str)
                or not isinstance(proposed, str)
            ):
                _error(errors, "manifest transition contains invalid values")
                continue
            if issue_id in transitions:
                _error(errors, f"manifest transitions contain duplicate issue ID: {issue_id}")
                continue
            transitions[issue_id] = {"from": previous, "to": proposed}
    if set(transitions) != issue_ids:
        _error(errors, "manifest issue_ids and allowed_status_transitions must match exactly")

    if manifest.get("allow_other_status_changes") is not False:
        _error(errors, "manifest allow_other_status_changes must be false")
    if manifest.get("allow_downgrades") is not False:
        _error(errors, "manifest allow_downgrades must be false")
    allow_downgrade = manifest.get("allow_downgrade", False)
    if allow_downgrade not in (False, True):
        _error(errors, "manifest allow_downgrade must be true when present")
    if allow_downgrade is True:
        reason = manifest.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            _error(errors, "manifest reason must be non-blank when allow_downgrade is true")
    elif "reason" in manifest:
        _error(errors, "manifest reason requires allow_downgrade=true")
    for issue_id, transition in transitions.items():
        if transition["from"] not in PROGRAMME_STATUSES or transition["to"] not in PROGRAMME_STATUSES:
            _error(errors, f"manifest transition has an unknown status: {issue_id}")
    return errors, issue_ids, transitions


def guard_proposal(
    *,
    base_registry: Mapping[str, Any],
    latest_registry: Mapping[str, Any],
    proposed_registry: Mapping[str, Any],
    manifest: Mapping[str, Any],
    current_status: Mapping[str, Any],
    current_progress: bytes,
    source_manifest_sha256: str | None = None,
    expected_base_commit: str | None = None,
    latest_commit: str | None = None,
    branch: str | None = None,
    actual_head_commit: str | None = None,
    expected_head_commit: str | None = None,
    base_is_ancestor: bool | None = None,
) -> list[str]:
    """Return deterministic validation errors for one proposed registry."""

    errors, manifest_issue_ids, transitions = _manifest_errors(manifest)
    manifest_base = manifest.get("base_commit")
    if expected_base_commit is not None and expected_base_commit != manifest_base:
        _error(errors, "manifest base commit does not match the requested base commit")
    if latest_commit is not None and latest_commit != manifest_base:
        _error(errors, "stale origin/base mismatch: latest origin is not the manifest base")
    manifest_branch = manifest.get("branch")
    if branch is not None and branch != manifest_branch:
        _error(errors, "manifest branch does not match the proposed branch")
    if expected_head_commit is not None and actual_head_commit != expected_head_commit:
        _error(errors, "checked-out head does not match the proposed head commit")
    if base_is_ancestor is False:
        _error(errors, "stale branch/base mismatch: manifest base is not an ancestor of head")

    base_errors: list[str] = []
    latest_errors: list[str] = []
    proposed_errors: list[str] = []
    base_by_id = _issue_map(base_registry, "base", base_errors)
    latest_by_id = _issue_map(latest_registry, "latest origin", latest_errors)
    proposed_by_id = _issue_map(proposed_registry, "proposed", proposed_errors)
    for message in [*base_errors, *latest_errors, *proposed_errors]:
        _error(errors, message)
    if base_registry != latest_registry:
        _error(errors, "stale origin registry: latest origin registry differs from base registry")

    base_ids = set(base_by_id)
    latest_ids = set(latest_by_id)
    proposed_ids = set(proposed_by_id)
    if base_ids != latest_ids:
        _error(errors, "base and latest origin issue IDs differ")
    if base_ids != proposed_ids:
        for issue_id in sorted(base_ids - proposed_ids):
            _error(errors, f"proposed registry is missing issue ID: {issue_id}")
        for issue_id in sorted(proposed_ids - base_ids):
            _error(errors, f"proposed registry has unexpected issue ID: {issue_id}")
    if manifest_issue_ids - base_ids:
        for issue_id in sorted(manifest_issue_ids - base_ids):
            _error(errors, f"manifest references missing issue ID: {issue_id}")

    changed_statuses: dict[str, tuple[str, str]] = {}
    comparable_ids = base_ids & proposed_ids
    for issue_id in sorted(comparable_ids):
        base_record = base_by_id[issue_id]
        proposed_record = proposed_by_id[issue_id]
        base_status = base_record.get("programme_status")
        proposed_status = proposed_record.get("programme_status")
        if base_status != proposed_status:
            changed_statuses[issue_id] = (str(base_status), str(proposed_status))
        base_comparable = dict(base_record)
        proposed_comparable = dict(proposed_record)
        proposed_comparable["programme_status"] = base_status
        if base_comparable != proposed_comparable:
            _error(errors, f"non-allowlisted registry change: {issue_id}")
    base_top_level = {key: value for key, value in base_registry.items() if key != "records"}
    proposed_top_level = {key: value for key, value in proposed_registry.items() if key != "records"}
    for top_level in (base_top_level, proposed_top_level):
        source_of_truth = top_level.get("source_of_truth")
        if isinstance(source_of_truth, dict):
            source_of_truth = dict(source_of_truth)
            source_of_truth.pop("source_manifest_sha256", None)
            top_level["source_of_truth"] = source_of_truth
    if base_top_level != proposed_top_level:
        _error(errors, "non-allowlisted registry change: top-level registry data")

    changed_issue_ids = set(changed_statuses)
    if changed_issue_ids != manifest_issue_ids:
        if changed_issue_ids - manifest_issue_ids:
            for issue_id in sorted(changed_issue_ids - manifest_issue_ids):
                _error(errors, f"status change is not allow-listed: {issue_id}")
        if manifest_issue_ids - changed_issue_ids:
            for issue_id in sorted(manifest_issue_ids - changed_issue_ids):
                _error(errors, f"allow-listed issue has no status change: {issue_id}")

    allow_downgrade = manifest.get("allow_downgrade") is True
    for issue_id, (previous, proposed) in changed_statuses.items():
        transition = transitions.get(issue_id)
        if transition is None:
            continue
        if transition["from"] != previous or transition["to"] != proposed:
            _error(errors, f"manifest transition from/to mismatch: {issue_id}")
        if _is_downgrade(previous, proposed) and not allow_downgrade:
            _error(errors, f"unapproved downgrade: {issue_id} {previous}->{proposed}")

    try:
        expected_status = status_payload(dict(proposed_registry))
        expected_progress = deterministic_text(progress_markdown(expected_status, dict(proposed_registry)))
        expected_registry_sha256 = hashlib.sha256(deterministic_json(proposed_registry)).hexdigest()
    except Exception as exc:  # malformed proposals must fail as JSON validation, not crash
        expected_status = None
        expected_progress = b""
        expected_registry_sha256 = ""
        _error(errors, f"cannot generate deterministic programme status: {exc}")

    if expected_status is not None:
        actual_checksum = current_status.get("source_registry_sha256")
        if actual_checksum != expected_registry_sha256:
            _error(errors, "source-registry checksum mismatch")
        if current_status.get("counts") != expected_status.get("counts"):
            _error(errors, "generated CURRENT_STATUS counts mismatch")
        if current_status.get("phase_counts") != expected_status.get("phase_counts"):
            _error(errors, "generated CURRENT_STATUS phase counts mismatch")
        if deterministic_json(current_status) != deterministic_json(expected_status):
            _error(errors, "generated CURRENT_STATUS.json is stale")
        if current_progress != expected_progress:
            _error(errors, "generated PROGRESS.md is stale")
    if source_manifest_sha256 is not None:
        source_truth = proposed_registry.get("source_of_truth")
        actual_source_manifest_sha256 = (
            source_truth.get("source_manifest_sha256")
            if isinstance(source_truth, dict)
            else None
        )
        if actual_source_manifest_sha256 != source_manifest_sha256:
            _error(errors, "source manifest checksum mismatch")
    return sorted(errors)


def _path(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()


def _git_json(root: Path, revision: str, path: Path) -> dict[str, Any]:
    payload = subprocess.check_output(
        ["git", "show", f"{revision}:{path.as_posix()}"],
        cwd=root,
    )
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} at {revision} must be a JSON object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=Path(".github/status-transition-guard-manifest.json"))
    parser.add_argument("--base-commit", help="expected manifest base commit; defaults to the manifest value")
    parser.add_argument("--latest-ref", default="origin/main", help="latest origin ref to compare with the handoff base")
    parser.add_argument("--branch", help="proposed branch name; defaults to the current branch")
    parser.add_argument("--head-commit", help="expected checked-out head commit")
    parser.add_argument("--status", type=Path, default=STATUS_PATH)
    parser.add_argument("--progress", type=Path, default=PROGRESS_PATH)
    parser.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST)
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        manifest = _load_json(_path(root, args.manifest))
        manifest_base = manifest.get("base_commit")
        requested_base = args.base_commit or manifest_base
        if not isinstance(requested_base, str):
            raise ValueError("manifest does not provide a usable base commit")
        latest_commit = _git(root, "rev-parse", args.latest_ref)
        actual_head_commit = _git(root, "rev-parse", "HEAD")
        branch = args.branch or _git(root, "branch", "--show-current")
        if not branch:
            raise ValueError("current branch is detached; pass --branch explicitly")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", requested_base, "HEAD"],
            cwd=root,
            check=False,
        ).returncode == 0
        base_registry = _git_json(root, requested_base, REGISTRY_PATH)
        latest_registry = _git_json(root, args.latest_ref, REGISTRY_PATH)
        proposed_registry = _load_json(root / REGISTRY_PATH)
        current_status = _load_json(_path(root, args.status))
        current_progress = _path(root, args.progress).read_bytes()
        source_manifest_sha256 = sha256_text_file(_path(root, args.source_manifest))
        errors = guard_proposal(
            base_registry=base_registry,
            latest_registry=latest_registry,
            proposed_registry=proposed_registry,
            manifest=manifest,
            current_status=current_status,
            current_progress=current_progress,
            source_manifest_sha256=source_manifest_sha256,
            expected_base_commit=requested_base,
            latest_commit=latest_commit,
            branch=branch,
            actual_head_commit=actual_head_commit,
            expected_head_commit=args.head_commit,
            base_is_ancestor=ancestor,
        )
        result: dict[str, Any] = {
            "base_commit": requested_base,
            "branch": branch,
            "errors": errors,
            "head_commit": actual_head_commit,
            "latest_commit": latest_commit,
            "result": "PASS" if not errors else "FAIL",
        }
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        result = {"errors": [str(exc)], "result": "FAIL"}
    print(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
