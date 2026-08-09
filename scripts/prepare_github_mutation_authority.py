"""Prepare one deterministic, repository-only GitHub issue mutation authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast

try:
    from scripts import apply_reviewed_status_completion as completion
    from scripts import github_mutation_gateway as gateway
    from scripts import sync_github_issues as sync
    from scripts.issue_registry_core import (
        control_state_record,
        is_issue0011_legacy_replay_source,
        load_control_state,
        load_control_state_at,
        validate_status_replay_prefix_shape,
    )
except ModuleNotFoundError:
    import apply_reviewed_status_completion as completion
    import github_mutation_gateway as gateway
    import sync_github_issues as sync
    from issue_registry_core import (  # type: ignore[no-redef]
        control_state_record,
        is_issue0011_legacy_replay_source,
        load_control_state,
        load_control_state_at,
        validate_status_replay_prefix_shape,
    )


MANIFEST_NAME = "github-mutation-authority-preparation.json"
SHA_RE = re.compile(r"[0-9a-f]{40}")


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=root,
        input=input_bytes,
    ).decode().strip()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _load_list(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{path} must contain one JSON object list")
    return value


def verify_exact_main(root: Path, source_sha: str, main_ref: str) -> None:
    if not SHA_RE.fullmatch(source_sha):
        raise ValueError("source SHA must be one full commit identity")
    if _git(root, "rev-parse", "HEAD") != source_sha:
        raise ValueError("source SHA does not equal the checked-out exact main head")
    if _git(root, "rev-parse", main_ref) != source_sha:
        raise ValueError("source SHA does not equal the reviewed main ref")


def _validate_reviewed_inputs(
    root: Path,
    plan: dict[str, Any],
    remote: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plan_sha = str(plan.get("plan_sha256", ""))
    gateway._validate_plan_authority(plan, plan_sha)
    if (
        plan.get("remote_inventory_sha256") != sync.inventory_sha256(remote)
        or plan.get("claim_inventory_sha256")
        != gateway.claim_inventory_sha256(remote)
    ):
        raise ValueError("reviewed plan does not match the exact remote snapshot")
    records = gateway.load_authority_ledger(root)
    reconciliation = gateway.reconcile_authority_ledger(records, remote, root=root)
    if not reconciliation.get("accepted"):
        raise ValueError(
            "existing authority ledger is not reconciled: "
            + str(reconciliation.get("error"))
        )
    actions = plan.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise ValueError("preparation requires exactly one reviewed action")
    return records, actions[0]


def prepare(
    root: Path,
    plan: dict[str, Any],
    remote: list[dict[str, Any]],
    *,
    source_sha: str,
    mode: str,
) -> tuple[bytes | None, bytes, dict[str, Any]]:
    """Return candidate bytes, the next full ledger, and a safe manifest."""

    if not SHA_RE.fullmatch(source_sha):
        raise ValueError("source SHA must be one full commit identity")
    records, action = _validate_reviewed_inputs(root, plan, remote)
    plan_sha = str(plan["plan_sha256"])
    candidate_bytes: bytes | None = None
    if mode == "status_replay":
        if (
            action.get("kind") != "update"
            or action.get("programme_status") != "integrated"
            or plan.get("summary")
            != {"create": 0, "update": 1, "close": 0, "reopen": 0, "blocked": 0}
        ):
            raise ValueError("status replay preparation requires exactly one integrated update")
        number = int(action.get("remote_number", 0))
        matches = [
            sync.normalise_remote_issue(issue)
            for issue in remote
            if int(issue.get("number", 0)) == number
        ]
        if len(matches) != 1:
            raise ValueError("status replay preparation target identity is ambiguous")
        target = matches[0]
        safe_action = sync.safe_plan_evidence(plan, remote)["actions"][0]
        if safe_action.get("managed_field_deltas") != ["Programme status"]:
            raise ValueError("status replay preparation action is not status-only")
        stable_id = str(action["stable_id"])
        source_record = control_state_record(
            load_control_state_at(root, source_sha), stable_id, context="source"
        )
        current_record = control_state_record(
            load_control_state(root), stable_id, context="current"
        )
        source_history = source_record.get("transition_history")
        source_evidence = source_record.get("acceptance_evidence")
        current_history = current_record.get("transition_history")
        current_evidence = current_record.get("acceptance_evidence")
        legacy_bootstrap = is_issue0011_legacy_replay_source(stable_id, source_record)
        validate_status_replay_prefix_shape(
            stable_id,
            source_history,
            source_evidence,
            programme_status=source_record.get("programme_status"),
            dependency_edge_evidence=source_record.get("dependency_edge_evidence"),
            verified_commit=source_record.get("verified_commit"),
            verified_date=source_record.get("verified_date"),
            status_transition=source_record.get("status_transition"),
            allow_legacy_bootstrap_origin=legacy_bootstrap,
        )
        validate_status_replay_prefix_shape(
            stable_id,
            current_history,
            current_evidence,
            programme_status=current_record.get("programme_status"),
            dependency_edge_evidence=current_record.get("dependency_edge_evidence"),
            verified_commit=current_record.get("verified_commit"),
            verified_date=current_record.get("verified_date"),
            status_transition=current_record.get("status_transition"),
            allow_legacy_bootstrap_origin=legacy_bootstrap,
        )
        if legacy_bootstrap:
            source_history = []
        if not all(
            isinstance(value, list)
            for value in (
                source_history,
                source_evidence,
                current_history,
                current_evidence,
            )
        ):
            raise ValueError("status replay canonical history/evidence is malformed")
        source_history = cast(list[dict[str, Any]], source_history)
        source_evidence = cast(list[dict[str, Any]], source_evidence)
        current_history = cast(list[dict[str, Any]], current_history)
        current_evidence = cast(list[dict[str, Any]], current_evidence)
        history_prefix = source_history
        evidence_prefix = source_evidence
        history_append = current_history[len(source_history) :]
        evidence_append = current_evidence[len(source_evidence) :]
        if (
            current_history[: len(source_history)] != source_history
            or current_evidence[: len(source_evidence)] != source_evidence
            or len(history_append) != 2
            or len(evidence_append) != 2
        ):
            raise ValueError("status replay canonical change is not exactly two appended entries")
        reviewed_commit = str(history_append[0].get("verified_commit", ""))
        if any(
            not isinstance(event, dict)
            or event.get("verified_commit") != reviewed_commit
            for event in history_append
        ):
            raise ValueError("status replay hops must share one reviewed product commit")
        core = {
            "stable_id": stable_id,
            "issue_number": number,
            "database_id": str(target["id"]),
            "node_id": str(target["node_id"]),
            "source_sha": source_sha,
            "from_status": "in_progress",
            "to_status": "integrated",
            "reviewed_product_commit": reviewed_commit,
            "hops": history_append,
            "plan_sha256": plan["plan_sha256"],
        }
        candidate = {
            "schema_version": completion.REPLAY_SCHEMA_VERSION,
            "execution_allowed": False,
            "expected_parent_sha": source_sha,
            "authority_ref": gateway.replay_candidate_authority_ref(core),
            "remote_inventory_sha256": plan["remote_inventory_sha256"],
            "plan_semantic_sha256": plan["plan_sha256"],
            "expected_replay": {
                "stable_id": stable_id,
                "issue_number": number,
                "from_status": "in_progress",
                "to_status": "integrated",
                "reviewed_product_commit": reviewed_commit,
                "transition_history_prefix": history_prefix,
                "transition_history_append": history_append,
                "acceptance_evidence_prefix": evidence_prefix,
                "acceptance_evidence_append": evidence_append,
            },
        }
        completion.validate_candidate(
            candidate,
            plan,
            remote,
            source_record=source_record,
            current_record=current_record,
        )
        candidate_bytes = gateway._json_bytes(candidate)
        payload = {
            **core,
            "candidate_path": gateway.AUTHORITY_CANDIDATE_PATH,
            "candidate_blob_oid": _git(
                root, "hash-object", "--stdin", input_bytes=candidate_bytes
            ),
            "candidate_blob_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "candidate_authority_ref": candidate["authority_ref"],
        }
    elif mode == "status":
        if (
            action.get("kind") != "update"
            or plan.get("summary")
            != completion.ONE_UPDATE_SUMMARY
            or action.get("desired_state") != "open"
        ):
            raise ValueError("status preparation requires exactly one open status update")
        number = int(action.get("remote_number", 0))
        matches = [
            sync.normalise_remote_issue(issue)
            for issue in remote
            if int(issue.get("number", 0)) == number
        ]
        if len(matches) != 1:
            raise ValueError("status preparation target identity is ambiguous")
        target, from_status = completion._accepted_remote_status_projection(matches[0])
        to_status = action.get("programme_status")
        completion.validate_single_hop_status_transition(from_status, to_status)
        safe_action = sync.safe_plan_evidence(plan, remote)["actions"][0]
        if safe_action.get("managed_field_deltas") != ["Programme status"]:
            raise ValueError("status preparation action is not status-only")
        core = {
            "stable_id": str(action["stable_id"]),
            "issue_number": number,
            "database_id": str(target["id"]),
            "node_id": str(target["node_id"]),
            "source_sha": source_sha,
            "from_status": from_status,
            "to_status": str(to_status),
            "plan_sha256": plan_sha,
        }
        candidate = {
            "schema_version": completion.SCHEMA_VERSION,
            "execution_allowed": False,
            "expected_parent_sha": source_sha,
            "authority_ref": gateway.candidate_authority_ref(core),
            "remote_inventory_sha256": plan["remote_inventory_sha256"],
            "plan_semantic_sha256": plan_sha,
            "expected_update": {
                "stable_id": core["stable_id"],
                "from_status": from_status,
                "to_status": str(to_status),
            },
        }
        candidate_bytes = gateway._json_bytes(candidate)
        payload = {
            **core,
            "candidate_path": gateway.AUTHORITY_CANDIDATE_PATH,
            "candidate_blob_oid": _git(
                root, "hash-object", "--stdin", input_bytes=candidate_bytes
            ),
            "candidate_blob_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "candidate_authority_ref": candidate["authority_ref"],
        }
    elif mode == "create":
        if (
            action.get("kind") != "create"
            or action.get("desired_state") != "open"
            or plan.get("summary")
            != {"create": 1, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
        ):
            raise ValueError("create preparation requires exactly one open issue create")
        payload = {
            "stable_id": str(action["stable_id"]),
            "source_sha": source_sha,
            "title": str(action["title"]),
            "managed_body": sync.managed_block(action),
            "claim_inventory_sha256": plan["claim_inventory_sha256"],
            "plan_sha256": plan_sha,
        }
    else:
        raise ValueError("preparation mode must be status, status_replay, or create")

    record = gateway.build_authority_record(
        mode,
        payload,
        sequence=len(records),
        previous_authority_id=str(records[-1]["authority_id"]),
    )
    ledger_bytes = gateway.authority_ledger_bytes([*records, record])
    if not ledger_bytes.startswith(gateway.authority_ledger_bytes(records)):
        raise ValueError("prepared ledger is not append-only")
    gateway.parse_authority_ledger(ledger_bytes)
    manifest = {
        "schema_version": "etf-ai-cockpit.github-mutation-preparation/1.0",
        "execution_allowed": False,
        "repository": gateway.REPO,
        "mode": mode,
        "source_sha": source_sha,
        "plan_sha256": plan_sha,
        "authority_id": record["authority_id"],
        "authority_sequence": record["sequence"],
        "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "candidate_sha256": (
            hashlib.sha256(candidate_bytes).hexdigest()
            if candidate_bytes is not None
            else None
        ),
    }
    return candidate_bytes, ledger_bytes, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--remote-snapshot", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--mode", choices=("status", "status_replay", "create"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    output = args.output_dir.resolve()
    if output == root or output.is_relative_to(root):
        parser.error("--output-dir must be outside the read-only source repository")
    verify_exact_main(root, args.source_sha, args.main_ref)
    candidate, ledger, manifest = prepare(
        root,
        _load_object(args.plan.resolve()),
        _load_list(args.remote_snapshot.resolve()),
        source_sha=args.source_sha,
        mode=args.mode,
    )
    authority_path = output / gateway.AUTHORITY_PATH
    authority_path.parent.mkdir(parents=True, exist_ok=True)
    authority_path.write_bytes(ledger)
    if candidate is not None:
        candidate_path = output / completion.DEFAULT_CANDIDATE
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes(candidate)
    (output / MANIFEST_NAME).write_bytes(gateway._json_bytes(manifest))
    print(f"PREPARED: {manifest['authority_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
