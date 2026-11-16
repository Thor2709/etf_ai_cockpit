"""One-off, receipt-only recovery of the previously created ISSUE-0182.

The original GitHub Actions writer created #1051 but returned
`conflict_after_write` before appending its acceptance receipt. This module
cannot create, edit or delete an issue; it can only append the missing receipt
for that exact issue, under a fresh authenticated GitHub Actions dispatch.

Remove this entry point after the recovery has been independently accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from scripts import apply_reviewed_status_completion as status
from scripts import github_mutation_gateway as gateway
from scripts import sync_github_issues as sync

TARGET = "ISSUE-0182"
ISSUE_NUMBER = 1051
ORIGINAL_WRITER_RUN = "43787208470"
ORIGINAL_HEAD = "a918030121b8043e7a8ace413b3fdfe7969d0fa6"
AUTHORITY_ID = "4710da2531f34e582a31f2b7578970f5b4bc21a0fe6ac8b7748b27750fee0b1c"
DISPATCH_INPUT = {"recover_issue_0182": "true"}


def validate_existing_issue(issue: dict[str, Any], authority: dict[str, Any]) -> str:
    """Return 'pending' or 'accepted'; fail closed on every other projection."""
    snapshot = gateway.normalise_issue_snapshot(issue)
    payload = authority["payload"]
    marker = gateway.CREATE_MARKER_TEMPLATE.format(AUTHORITY_ID)
    expected_body = marker + "\n" + payload["managed_body"]
    if (
        snapshot["number"] != ISSUE_NUMBER
        or snapshot["title"] != payload["title"]
        or snapshot["body"] != expected_body
        or snapshot["state"] != "open"
        or snapshot["labels"]
        or not snapshot["id"]
        or not snapshot["node_id"]
        or snapshot["url"] not in (
            f"https://api.github.com/repos/{gateway.REPO}/issues/{ISSUE_NUMBER}",
            f"https://github.com/{gateway.REPO}/issues/{ISSUE_NUMBER}",
        )
    ):
        raise ValueError("issue_0182_recovery_projection_mismatch")
    acceptance = gateway.validate_create_acceptance(issue)
    if acceptance.get("accepted") and not acceptance.get("legacy"):
        if (
            acceptance.get("authority_id") != AUTHORITY_ID
            or acceptance.get("authority_sequence") != authority["sequence"]
            or acceptance.get("source_sha") != payload["source_sha"]
            or acceptance.get("plan_sha256") != payload["plan_sha256"]
            or acceptance.get("head_sha") != ORIGINAL_HEAD
        ):
            raise ValueError("issue_0182_recovery_receipt_binding_mismatch")
        return "accepted"
    if snapshot["comments"]:
        raise ValueError("issue_0182_recovery_comments_conflict")
    if acceptance.get("error") != "orphan_or_duplicate_create_acceptance":
        raise ValueError("issue_0182_recovery_unexpected_acceptance_state")
    return "pending"


def _attest_dispatch(run_reader: Callable[[str], dict[str, Any]]) -> dict[str, str]:
    keys = (
        "GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA",
        "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID", "GITHUB_RUN_NUMBER",
        "GITHUB_WORKFLOW_REF", "GITHUB_REPOSITORY", "GITHUB_ACTOR",
        "GITHUB_EVENT_PATH",
    )
    env = {key: os.environ.get(key, "") for key in keys}
    event_path = Path(env["GITHUB_EVENT_PATH"])
    if (
        env["GITHUB_ACTIONS"] != "true"
        or env["GITHUB_EVENT_NAME"] != "workflow_dispatch"
        or env["GITHUB_REF"] != "refs/heads/main"
        or env["GITHUB_RUN_ATTEMPT"] != "1"
        or not gateway.SHA_RE.fullmatch(env["GITHUB_SHA"])
        or not event_path.is_file()
    ):
        raise ValueError("issue_0182_recovery_requires_first_party_dispatch")
    event_bytes = event_path.read_bytes()
    event = json.loads(event_bytes)
    if (
        not isinstance(event, dict)
        or event.get("ref") != "refs/heads/main"
        or event.get("inputs") not in (DISPATCH_INPUT, {"recover_issue_0182": True})
    ):
        raise ValueError("issue_0182_recovery_dispatch_input_mismatch")
    attestation = {
        "event_name": "workflow_dispatch",
        "event_ref": "refs/heads/main",
        "run_attempt": "1",
        "event_before": status._git(Path.cwd(), "rev-parse", ORIGINAL_HEAD + "^"),
        "event_after": ORIGINAL_HEAD,
        "actor": env["GITHUB_ACTOR"],
        "pusher": env["GITHUB_ACTOR"],
        "run_id": env["GITHUB_RUN_ID"],
        "run_number": env["GITHUB_RUN_NUMBER"],
        "workflow_ref": env["GITHUB_WORKFLOW_REF"],
        "repository": env["GITHUB_REPOSITORY"],
        "event_payload_sha256": hashlib.sha256(event_bytes).hexdigest(),
        "oidc_event_name": "workflow_dispatch",
        "oidc_ref": "refs/heads/main",
        "oidc_sha": env["GITHUB_SHA"],
        "oidc_workflow_sha": env["GITHUB_SHA"],
    }
    gateway._validate_run_attestation(attestation)
    status.validate_live_actions_run(attestation, run_reader)
    return attestation


def _original_authority(root: Path) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    if status._git(root, "rev-parse", "HEAD") != status._git(root, "rev-parse", "origin/main"):
        raise ValueError("issue_0182_recovery_not_exact_main")
    if not status._is_ancestor(root, ORIGINAL_HEAD, "origin/main"):
        raise ValueError("issue_0182_original_create_head_not_on_main")
    before = gateway._git_blob_bytes(root, ORIGINAL_HEAD + "^", gateway.AUTHORITY_PATH)
    after = gateway._git_blob_bytes(root, ORIGINAL_HEAD, gateway.AUTHORITY_PATH)
    current = gateway._git_blob_bytes(root, "HEAD", gateway.AUTHORITY_PATH)
    if before is None or after is None or current is None or not after.startswith(before):
        raise ValueError("issue_0182_original_authority_blob_invalid")
    old_records = gateway.parse_authority_ledger(before)
    intro_records = gateway.parse_authority_ledger(after)
    records = gateway.parse_authority_ledger(current)
    if (
        len(intro_records) != len(old_records) + 1
        or intro_records[-1].get("authority_id") != AUTHORITY_ID
        or intro_records[-1].get("authority_type") != "create"
        or intro_records[-1].get("sequence") != len(old_records)
        or intro_records[-1].get("payload", {}).get("stable_id") != TARGET
        or intro_records[-1].get("payload", {}).get("source_sha") != status._git(root, "rev-parse", ORIGINAL_HEAD + "^")
        or records[: len(intro_records)] != intro_records
    ):
        raise ValueError("issue_0182_original_create_authority_mismatch")
    binding = {
        "head_sha": ORIGINAL_HEAD,
        "source_sha": intro_records[-1]["payload"]["source_sha"],
        "ledger_blob_oid": status._git(root, "rev-parse", f"{ORIGINAL_HEAD}:{gateway.AUTHORITY_PATH}"),
        "ledger_blob_sha256": gateway._sha256(after),
    }
    gateway.validate_projected_git_binding(root, intro_records[-1], binding)
    return intro_records[-1], binding, records


def recover(
    root: Path,
    *,
    transport: gateway.MutationTransport | None = None,
    run_reader: Callable[[str], dict[str, Any]] = status.read_actions_run,
    proof_verifier: Callable[[dict[str, str]], None] | None = None,
    main_fetcher: Callable[[Path], None] = status.fetch_origin_main,
) -> dict[str, Any]:
    """Perform at most one receipt POST after verifying the original issue."""
    attestation = _attest_dispatch(run_reader)
    original_run = run_reader(ORIGINAL_WRITER_RUN)
    if (
        str(original_run.get("id")) != ORIGINAL_WRITER_RUN
        or original_run.get("event") != "push"
        or original_run.get("path") != status.WORKFLOW_PATH
        or original_run.get("head_sha") != ORIGINAL_HEAD
        or original_run.get("status") != "completed"
        or original_run.get("conclusion") != "failure"
        or str(original_run.get("run_attempt")) != "1"
        or original_run.get("repository", {}).get("full_name") != gateway.REPO
    ):
        raise ValueError("issue_0182_original_failed_run_not_verified")
    main_fetcher(root)
    authority, binding, records = _original_authority(root)
    client = transport or gateway.GhMutationTransport()
    expected_marker = gateway.CREATE_MARKER_TEMPLATE.format(AUTHORITY_ID)
    inventory = client.list_issues()
    if sum(expected_marker in str(row.get("body") or "") for row in inventory) != 1:
        raise ValueError("issue_0182_recovery_duplicate_or_missing_create_marker")
    issue = client.fetch_issue(ISSUE_NUMBER)
    state = validate_existing_issue(issue, authority)
    if state == "accepted":
        return {"accepted": True, "terminal_status": "already_accepted", "transport_writes": 0}

    if proof_verifier is None:
        used_jtis: set[str] = set()

        def proof_verifier(identity: dict[str, str]) -> None:
            status.verify_fresh_caller_proof(
                identity,
                run_reader=run_reader,
                check_reader=status.read_check_run,
                token_requester=status.request_actions_oidc_token,
                jwks_reader=status.read_oidc_jwks,
                used_jtis=used_jtis,
            )

    proof_verifier(attestation)
    main_fetcher(root)
    _original_authority(root)
    # Freshly read and compare the exact issue immediately before the one POST.
    fresh = client.fetch_issue(ISSUE_NUMBER)
    if gateway.normalise_issue_snapshot(fresh) != gateway.normalise_issue_snapshot(issue):
        raise ValueError("issue_0182_recovery_stale_before_receipt")
    receipt, receipt_body = gateway.build_create_receipt(
        fresh,
        mutation_id=AUTHORITY_ID,
        stable_id=TARGET,
        authority_id=AUTHORITY_ID,
        authority_sequence=int(authority["sequence"]),
        source_sha=authority["payload"]["source_sha"],
        head_sha=ORIGINAL_HEAD,
        ledger_blob_oid=binding["ledger_blob_oid"],
        ledger_blob_sha256=binding["ledger_blob_sha256"],
        plan_sha256=authority["payload"]["plan_sha256"],
        **{key: attestation[key] for key in (
            "event_name", "event_ref", "run_attempt", "event_before",
            "event_after", "actor", "pusher", "run_id", "run_number",
            "workflow_ref", "repository", "event_payload_sha256"
        )},
    )
    # Never retry an ambiguous POST, never generate a second issue.
    client.append_comment(ISSUE_NUMBER, receipt_body)
    final = client.fetch_issue(ISSUE_NUMBER)
    if not gateway._postwrite_matches(fresh, final, receipt_body):
        raise RuntimeError("issue_0182_recovery_conflict_after_receipt")
    if validate_existing_issue(final, authority) != "accepted":
        raise RuntimeError("issue_0182_recovery_receipt_not_accepted")
    # Independent reconciliation is required before the recovery is complete.
    remote = sync.gh_list_issues()
    reconciled = gateway.reconcile_authority_ledger(records, remote, root=root)
    if not reconciled.get("accepted"):
        raise RuntimeError("issue_0182_recovery_ledger_readback_failed")
    return {
        "accepted": True,
        "terminal_status": "receipt_written_and_reconciled",
        "transport_writes": 1,
        "issue_number": ISSUE_NUMBER,
        "authority_id": AUTHORITY_ID,
        "receipt_mutation_id": receipt["receipt_mutation_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    evidence = {
        "schema_version": "etf-ai-cockpit.issue-0182-create-recovery/1.0",
        "execution_allowed": False,
        "accepted": False,
        "terminal_status": "not_started",
    }
    try:
        if not args.apply:
            raise ValueError("issue_0182_receipt_recovery_requires_apply")
        evidence.update(recover(args.root.resolve()))
        if evidence["terminal_status"] == "already_accepted":
            print("ISSUE_0182_RECEIPT_ALREADY_ACCEPTED")
        else:
            print("ISSUE_0182_RECEIPT_RECOVERED")
    except Exception as exc:
        evidence["terminal_status"] = "blocked"
        evidence["failure_reason"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_out.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
