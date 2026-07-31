"""Validate and apply one reviewed post-merge programme-status completion."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import sync_github_issues as sync
    from scripts.issue_registry_core import CONTROL_ALLOWED_TRANSITIONS, REGISTRY_PATH
except ModuleNotFoundError:
    import sync_github_issues as sync
    from issue_registry_core import CONTROL_ALLOWED_TRANSITIONS, REGISTRY_PATH


SCHEMA_VERSION = "etf-ai-cockpit.status-completion-candidate/1.0"
DEFAULT_CANDIDATE = Path(".github/issue-transitions/post-merge-control-candidate.json")
ZERO_SUMMARY = {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
STATUS_RE = re.compile(r"^- Programme status: `([^`]+)`$", re.MULTILINE)
EXPECTED_KEYS = {
    "schema_version",
    "execution_allowed",
    "expected_parent_sha",
    "remote_inventory_sha256",
    "plan_semantic_sha256",
    "expected_update",
}
EXPECTED_UPDATE_KEYS = {"stable_id", "from_status", "to_status"}


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            check=False,
        ).returncode
        == 0
    )


def _validate_candidate_blob(
    root: Path,
    *,
    candidate_path: Path,
    expected_head: str,
) -> None:
    candidate_relative = DEFAULT_CANDIDATE.as_posix()
    if candidate_path.resolve() != (root / DEFAULT_CANDIDATE).resolve():
        raise ValueError("candidate path must be the canonical status-completion path")
    try:
        expected_blob = _git(root, "rev-parse", f"{expected_head}:{candidate_relative}")
    except subprocess.CalledProcessError as exc:
        raise ValueError("expected head does not contain the candidate path") from exc
    if _git(root, "cat-file", "-t", expected_blob) != "blob":
        raise ValueError("expected head candidate is not a Git blob")
    try:
        _git(root, "ls-files", "--error-unmatch", "--", candidate_relative)
    except subprocess.CalledProcessError as exc:
        raise ValueError("candidate path is not tracked") from exc
    if _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        candidate_relative,
    ):
        raise ValueError("candidate path has staged, unstaged, or untracked changes")
    worktree_blob = _git(
        root,
        "hash-object",
        f"--path={candidate_relative}",
        str(candidate_path),
    )
    if worktree_blob != expected_blob:
        raise ValueError(
            "checked-out candidate canonical blob does not match expected head"
        )


def load_candidate(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("status-completion candidate must be a JSON object")
    return payload


def validate_git_bindings(
    root: Path,
    candidate: dict[str, Any],
    *,
    candidate_path: Path,
    expected_parent: str,
    expected_head: str,
    main_ref: str | None,
) -> None:
    if not SHA_RE.fullmatch(expected_parent) or not SHA_RE.fullmatch(expected_head):
        raise ValueError("expected parent and head must be full commit SHAs")
    if candidate.get("expected_parent_sha") != expected_parent:
        raise ValueError("candidate expected parent/base SHA mismatch")
    checked_head = _git(root, "rev-parse", "HEAD")
    _validate_candidate_blob(
        root,
        candidate_path=candidate_path,
        expected_head=expected_head,
    )
    if main_ref is None:
        if not _is_ancestor(root, expected_parent, expected_head):
            raise ValueError(
                "candidate expected parent/base is not an ancestor of head"
            )
        if checked_head != expected_head and not _is_ancestor(
            root, expected_head, checked_head
        ):
            raise ValueError(
                "expected head is not the checked-out validation commit or its ancestor"
            )
    else:
        if checked_head != expected_head:
            raise ValueError("status-completion head does not equal checked-out HEAD")
        parents = _git(root, "rev-list", "--parents", "-n", "1", expected_head).split()[
            1:
        ]
        if expected_parent not in parents:
            raise ValueError(
                "candidate expected parent/base is not a direct parent of head"
            )
        if _git(root, "rev-parse", main_ref) != expected_head:
            raise ValueError("status-completion requires exact fresh main")


def _programme_status(body: str) -> str:
    matches = STATUS_RE.findall(body)
    if len(matches) != 1:
        raise ValueError("remote issue has ambiguous programme status")
    return matches[0]


def validate_candidate(
    candidate: dict[str, Any],
    plan: dict[str, Any],
    remote: list[dict[str, Any]],
) -> None:
    if set(candidate) != EXPECTED_KEYS:
        raise ValueError("candidate envelope fields are not narrowly bounded")
    if candidate.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("candidate schema version mismatch")
    if candidate.get("execution_allowed") is not False:
        raise ValueError("candidate must preserve execution_allowed=false")
    if not SHA_RE.fullmatch(str(candidate.get("expected_parent_sha", ""))):
        raise ValueError("candidate expected parent/base SHA is invalid")
    inventory = str(candidate.get("remote_inventory_sha256", ""))
    semantic = str(candidate.get("plan_semantic_sha256", ""))
    if not HASH_RE.fullmatch(inventory) or inventory != plan.get(
        "remote_inventory_sha256"
    ):
        raise ValueError("candidate remote inventory SHA mismatch")
    if not HASH_RE.fullmatch(semantic) or semantic != plan.get("plan_sha256"):
        raise ValueError("candidate semantic plan SHA mismatch")

    expected = candidate.get("expected_update")
    if not isinstance(expected, dict) or set(expected) != EXPECTED_UPDATE_KEYS:
        raise ValueError("candidate expected update is not narrowly bounded")
    stable_id = str(expected.get("stable_id", ""))
    if not sync.MARKER_RE.fullmatch(f"<!-- etf-ai-cockpit:stable-id={stable_id} -->"):
        raise ValueError("candidate stable ID is invalid")
    if expected.get("to_status") != "integrated":
        raise ValueError("candidate may only transition to integrated")
    from_status = str(expected.get("from_status", ""))
    if "integrated" not in CONTROL_ALLOWED_TRANSITIONS.get(from_status, frozenset()):
        raise ValueError(
            "candidate status transition is not a canonical direct transition"
        )

    summary = plan.get("summary")
    if summary != {"create": 0, "update": 1, "close": 0, "reopen": 0, "blocked": 0}:
        raise ValueError("current plan is not exactly one update")
    actions = plan.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise ValueError("current plan must contain exactly one action")
    action = actions[0]
    if action.get("kind") != "update" or action.get("stable_id") != stable_id:
        raise ValueError("current plan update does not match candidate stable ID")
    if action.get("programme_status") != "integrated":
        raise ValueError("current plan contains a non-integrated status update")

    normalised = [sync.normalise_remote_issue(issue) for issue in remote]
    matching = [
        issue
        for issue in normalised
        if stable_id in set(sync.MARKER_RE.findall(issue["body"]))
    ]
    if len(matching) != 1 or matching[0]["number"] != action.get("remote_number"):
        raise ValueError("candidate remote issue identity is ambiguous")
    if action.get("title") != matching[0]["title"]:
        raise ValueError("current plan contains a non-status delta")
    if _programme_status(matching[0]["body"]) != from_status:
        raise ValueError("candidate from status does not match remote issue")
    evidence = sync.safe_plan_evidence(plan, normalised)
    if evidence["actions"][0].get("managed_field_deltas") != ["Programme status"]:
        raise ValueError("current plan contains a non-status delta")


def run(
    root: Path,
    candidate_path: Path,
    *,
    expected_parent: str,
    expected_head: str,
    main_ref: str | None,
    apply: bool,
    evidence_out: Path | None = None,
    remote_reader: Callable[[], list[dict[str, Any]]] = sync.gh_list_issues,
) -> None:
    evidence: dict[str, Any] = {
        "schema_version": "etf-ai-cockpit.status-completion-evidence/1.0",
        "execution_allowed": False,
        "mode": "apply" if apply else "validate",
        "expected_parent_sha": expected_parent,
        "expected_head_sha": expected_head,
        "terminal_status": "failed",
        "zero_action_readback": None,
    }
    try:
        canonical_candidate = (root / DEFAULT_CANDIDATE).resolve()
        if candidate_path.resolve() != canonical_candidate:
            raise ValueError(
                "candidate path must be the canonical status-completion path"
            )
        candidate = load_candidate(candidate_path)
        evidence.update(
            {
                "remote_inventory_sha256": candidate.get("remote_inventory_sha256"),
                "plan_semantic_sha256": candidate.get("plan_semantic_sha256"),
                "expected_update": candidate.get("expected_update"),
            }
        )
        validate_git_bindings(
            root,
            candidate,
            candidate_path=candidate_path,
            expected_parent=expected_parent,
            expected_head=expected_head,
            main_ref=main_ref,
        )
        registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
        remote = remote_reader()
        map_path = root / sync.DEFAULT_MAP_PATH
        historical_map = (
            json.loads(map_path.read_text(encoding="utf-8"))
            if map_path.exists()
            else None
        )
        plan = sync.plan_actions(registry, remote, historical_map=historical_map)
        validate_candidate(candidate, plan, remote)
        evidence["action_scope"] = sync.safe_plan_evidence(plan, remote)["actions"]
        if not apply:
            evidence["terminal_status"] = "validated"
            print("VALIDATED_STATUS_COMPLETION_CANDIDATE")
            return
        sync.apply_actions(plan, approved_sha256=str(candidate["plan_semantic_sha256"]))
        for attempt in range(4):
            readback = sync.plan_actions(
                registry,
                remote_reader(),
                historical_map=historical_map,
            )
            if (
                readback.get("summary") == ZERO_SUMMARY
                and readback.get("actions") == []
            ):
                evidence["terminal_status"] = "applied_and_verified"
                evidence["zero_action_readback"] = True
                print("APPLIED_AND_VERIFIED_STATUS_COMPLETION")
                return
            if attempt < 3:
                time.sleep(2**attempt)
        evidence["zero_action_readback"] = False
        raise RuntimeError("status-completion GitHub read-back is not idempotent")
    except Exception as exc:
        evidence["failure_reason"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if evidence_out is not None:
            evidence_out.parent.mkdir(parents=True, exist_ok=True)
            evidence_out.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--expected-parent", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--main-ref")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    candidate = args.candidate
    if not candidate.is_absolute():
        candidate = root / candidate
    evidence_out = args.evidence_out
    if evidence_out is not None and not evidence_out.is_absolute():
        evidence_out = root / evidence_out
    run(
        root,
        candidate,
        expected_parent=args.expected_parent,
        expected_head=args.expected_head,
        main_ref=args.main_ref,
        apply=args.apply,
        evidence_out=evidence_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
