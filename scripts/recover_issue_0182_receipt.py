"""One-off, receipt-only recovery of the previously created ISSUE-0182.

The original GitHub Actions writer created #1051 but returned
`conflict_after_write` before appending its acceptance receipt. This module
cannot create, edit or delete an issue; it can only append the missing receipt
for that exact issue, under the authenticated first push introducing the recovery.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from scripts import apply_reviewed_status_completion as status
from scripts import github_mutation_gateway as gateway
from scripts import sync_github_issues as sync

TARGET = "ISSUE-0182"
ISSUE_NUMBER = 1051
ORIGINAL_WRITER_RUN = "43787208470"
ORIGINAL_HEAD = gateway.CREATE_RECEIPT_RECOVERY_HEAD_SHA
AUTHORITY_ID = gateway.CREATE_RECEIPT_RECOVERY_AUTHORITY_ID
ZERO_SUMMARY = status.ZERO_SUMMARY


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
        or snapshot["id"] != gateway.CREATE_RECEIPT_RECOVERY_ISSUE_ID
        or snapshot["node_id"] != gateway.CREATE_RECEIPT_RECOVERY_NODE_ID
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


def _original_authority(root: Path) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    if not status._is_ancestor(root, ORIGINAL_HEAD, "origin/main"):
        raise ValueError("issue_0182_original_create_head_not_on_main")
    before = gateway._git_blob_bytes(root, ORIGINAL_HEAD + "^", gateway.AUTHORITY_PATH)
    after = gateway._git_blob_bytes(root, ORIGINAL_HEAD, gateway.AUTHORITY_PATH)
    current = gateway._git_blob_bytes(root, "HEAD", gateway.AUTHORITY_PATH)
    if before is None or after is None or current != after or not after.startswith(before):
        raise ValueError("issue_0182_original_authority_blob_invalid")
    old_records = gateway.parse_authority_ledger(before)
    intro_records = gateway.parse_authority_ledger(after)
    if (
        len(intro_records) != len(old_records) + 1
        or intro_records[-1].get("authority_id") != AUTHORITY_ID
        or intro_records[-1].get("authority_type") != "create"
        or intro_records[-1].get("sequence") != len(old_records)
        or intro_records[-1].get("payload", {}).get("stable_id") != TARGET
        or intro_records[-1].get("payload", {}).get("source_sha") != status._git(root, "rev-parse", ORIGINAL_HEAD + "^")
    ):
        raise ValueError("issue_0182_original_create_authority_mismatch")
    binding = {
        "head_sha": ORIGINAL_HEAD,
        "source_sha": intro_records[-1]["payload"]["source_sha"],
        "ledger_blob_oid": status._git(root, "rev-parse", f"{ORIGINAL_HEAD}:{gateway.AUTHORITY_PATH}"),
        "ledger_blob_sha256": gateway._sha256(after),
    }
    gateway.validate_projected_git_binding(root, intro_records[-1], binding)
    return intro_records[-1], binding, intro_records


def _readback(root: Path, records: list[dict[str, Any]], remote: list[dict[str, Any]]) -> None:
    registry = json.loads((root / sync.REGISTRY_PATH).read_bytes())
    history = root / sync.DEFAULT_MAP_PATH
    plan = sync.plan_actions(
        registry, remote,
        historical_map=json.loads(history.read_bytes()) if history.exists() else None,
        authority_records=records, authority_root=root,
    )
    if plan["summary"] != ZERO_SUMMARY:
        raise ValueError("issue_0182_recovery_zero_action_readback_failed")


def recover(
    root: Path,
    *,
    transport: gateway.MutationTransport | None = None,
    run_reader: Callable[[str], dict[str, Any]] = status.read_actions_run,
    proof_verifier: Callable[[dict[str, str]], None] | None = None,
    main_fetcher: Callable[[Path], None] = status.fetch_origin_main,
    remote_reader: Callable[[], list[dict[str, Any]]] = sync.gh_list_issues,
    expected_parent: str | None = None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """Validate the candidate or append one missing receipt on its first push."""
    applying = expected_parent is None and expected_head is None
    attestation = status.github_actions_push_attestation(run_reader) if applying else {}
    parent = attestation.get("event_before", expected_parent or "")
    head = attestation.get("event_after", expected_head or "")
    if applying:
        main_fetcher(root)
    if status._git(root, "rev-parse", "HEAD") != head or (
        applying and status._git(root, "rev-parse", "origin/main") != head
    ):
        raise ValueError("issue_0182_recovery_head_mismatch")
    gateway.validate_create_receipt_recovery_push(root, parent, head)
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
    authority, binding, records = _original_authority(root)
    client = transport or gateway.GhMutationTransport()
    expected_marker = gateway.CREATE_MARKER_TEMPLATE.format(AUTHORITY_ID)
    stable_marker = f"<!-- etf-ai-cockpit:stable-id={TARGET} -->"
    remote = remote_reader()
    matches = [row for row in remote if int(row["number"]) == ISSUE_NUMBER]
    if len(matches) != 1 or any(
        sum(marker in str(row.get("body") or "") for row in remote) != 1
        for marker in (expected_marker, stable_marker)
    ):
        raise ValueError("issue_0182_recovery_duplicate_or_missing_create_marker")
    issue = matches[0]
    state = validate_existing_issue(issue, authority)
    if state == "accepted":
        _readback(root, records, remote)
        return {"accepted": True, "terminal_status": "already_accepted",
                "transport_writes": 0, "zero_action_readback": True}
    others = [row for row in remote if row is not issue]
    if (
        gateway.claim_inventory_sha256(others) != authority["payload"]["claim_inventory_sha256"]
        or not gateway.reconcile_authority_ledger(records[:-1], others, root=root).get("accepted")
    ):
        raise ValueError("issue_0182_recovery_other_claims_changed")
    if not applying:
        return {"accepted": False, "terminal_status": "validated", "transport_writes": 0}

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

    main_fetcher(root)
    if status._git(root, "rev-parse", "origin/main") != head:
        raise ValueError("issue_0182_recovery_head_mismatch")
    gateway.validate_create_receipt_recovery_push(root, parent, head)
    # Freshly read and compare the exact issue immediately before the one POST.
    if gateway.claim_inventory_sha256(client.list_issues()) != gateway.claim_inventory_sha256(remote):
        raise ValueError("issue_0182_recovery_stale_before_receipt")
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
    proof_verifier(attestation)
    evidence = {"transport_writes": 1, "zero_action_readback": False}
    try:
        try:
            client.append_comment(ISSUE_NUMBER, receipt_body)
        except Exception as exc:
            if not gateway._is_ambiguous_write_error(exc):
                raise
        final = client.fetch_issue(ISSUE_NUMBER)
        if (
            not gateway._postwrite_matches(fresh, final, receipt_body)
            or validate_existing_issue(final, authority) != "accepted"
        ):
            raise RuntimeError("issue_0182_recovery_receipt_unresolved")
        _readback(root, records, remote_reader())
    except Exception as exc:
        raise gateway.MutationTransportError(str(exc), evidence) from exc
    return {
        "accepted": True,
        "terminal_status": "receipt_written_and_reconciled",
        "transport_writes": 1,
        "zero_action_readback": True,
        "issue_number": ISSUE_NUMBER,
        "authority_id": AUTHORITY_ID,
        "receipt_mutation_id": receipt["receipt_mutation_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-parent")
    parser.add_argument("--expected-head")
    args = parser.parse_args()
    if (args.apply and (args.expected_parent or args.expected_head)) or (
        not args.apply and not (args.expected_parent and args.expected_head)
    ):
        parser.error("use --apply or provide both expected commit identities to validate")
    evidence = {
        "schema_version": "etf-ai-cockpit.status-completion-evidence/1.0",
        "expected_parent_sha": args.expected_parent,
        "expected_head_sha": args.expected_head,
        "execution_allowed": False,
        "accepted": False,
        "terminal_status": "not_started",
    }
    try:
        evidence.update(recover(
            args.root.resolve(), expected_parent=args.expected_parent, expected_head=args.expected_head,
        ))
        print(evidence["terminal_status"])
    except Exception as exc:
        if isinstance(exc, gateway.MutationGatewayError):
            evidence.update(exc.evidence)
        evidence["terminal_status"] = "blocked"
        evidence["failure_reason"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_out.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
