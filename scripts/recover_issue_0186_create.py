"""One-off recovery that applies the ISSUE-0186 create authority exactly once.

The original GitHub Actions writer (run 44312065417) failed while reading the issue list, before
any write: neither the issue nor its receipt exists, and a rerun of the spent create authority is
refused. Every later authority push fails closed on that missing projection. Under the
authenticated first push to main that introduces this module it creates the one issue, appends its
receipt and requires the readback to reconcile. It never retries a write and never compensates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from scripts import apply_reviewed_status_completion as status
from scripts import github_mutation_gateway as gateway
from scripts import sync_github_issues as sync

TARGET = "ISSUE-0186"
RECOVERY = gateway.CREATE_RECEIPT_RECOVERIES[TARGET]
ORIGINAL_HEAD = RECOVERY["head_sha"]
AUTHORITY_ID = RECOVERY["authority_id"]
ZERO_SUMMARY = status.ZERO_SUMMARY
CREATE_MARKER = gateway.CREATE_MARKER_TEMPLATE.format(AUTHORITY_ID)
STABLE_MARKER = f"<!-- etf-ai-cockpit:stable-id={TARGET} -->"
ATTESTATION_KEYS = (
    "event_name", "event_ref", "run_attempt", "event_before", "event_after", "actor", "pusher",
    "run_id", "run_number", "workflow_ref", "repository", "event_payload_sha256",
)


def _carries(issues: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
    return [row for row in issues if marker in str(row.get("body") or "")]


def _by_actions_bot(issue: dict[str, Any]) -> bool:
    """The issue was opened by the GitHub Actions bot (same identity as a receipt's author)."""
    author = gateway.normalise_comment(issue)
    return (
        author["author"] in gateway.BOT_AUTHORS
        and author["author_type"] == "Bot"
        and author["author_id"] == gateway.GITHUB_ACTIONS_BOT_USER_ID
    )


def _accepted(issue: dict[str, Any], authority: dict[str, Any]) -> bool:
    """True only for the exact created issue carrying a valid receipt bound to this authority."""
    payload = authority["payload"]
    snapshot = gateway.normalise_issue_snapshot(issue)
    acceptance = gateway.validate_create_acceptance(issue)
    return (
        snapshot["title"] == payload["title"]
        and snapshot["body"] == CREATE_MARKER + "\n" + payload["managed_body"]
        and snapshot["state"] == "open"
        and bool(acceptance.get("accepted"))
        and not acceptance.get("legacy")
        and acceptance.get("authority_id") == AUTHORITY_ID
        and acceptance.get("authority_sequence") == authority["sequence"]
        and acceptance.get("source_sha") == payload["source_sha"]
        and acceptance.get("plan_sha256") == payload["plan_sha256"]
        and acceptance.get("head_sha") == ORIGINAL_HEAD
    )


def _original_authority(root: Path) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    if not status._is_ancestor(root, ORIGINAL_HEAD, "origin/main"):
        raise ValueError("issue_0186_original_create_head_not_on_main")
    before = gateway._git_blob_bytes(root, ORIGINAL_HEAD + "^", gateway.AUTHORITY_PATH)
    after = gateway._git_blob_bytes(root, ORIGINAL_HEAD, gateway.AUTHORITY_PATH)
    current = gateway._git_blob_bytes(root, "HEAD", gateway.AUTHORITY_PATH)
    if before is None or after is None or current != after or not after.startswith(before):
        raise ValueError("issue_0186_original_authority_blob_invalid")
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
        raise ValueError("issue_0186_original_create_authority_mismatch")
    binding = {
        "head_sha": ORIGINAL_HEAD,
        "source_sha": intro_records[-1]["payload"]["source_sha"],
        "ledger_blob_oid": status._git(root, "rev-parse", f"{ORIGINAL_HEAD}:{gateway.AUTHORITY_PATH.as_posix()}"),
        "ledger_blob_sha256": gateway._sha256(after),
    }
    gateway.validate_projected_git_binding(root, intro_records[-1], binding)
    return intro_records[-1], binding, intro_records


def _plan(root: Path, records: list[dict[str, Any]], remote: list[dict[str, Any]]) -> dict[str, Any]:
    registry = json.loads((root / sync.REGISTRY_PATH).read_bytes())
    history = root / sync.DEFAULT_MAP_PATH
    return sync.plan_actions(
        registry, remote,
        historical_map=json.loads(history.read_bytes()) if history.exists() else None,
        authority_records=records, authority_root=root,
    )


def _readback(
    root: Path, records: list[dict[str, Any]], remote: list[dict[str, Any]],
    deferred: list[dict[str, Any]] | None = None,
) -> dict[str, bool]:
    """Only the reviewed, still-deferred creates may remain pending (as in the normal create path)."""
    plan = _plan(root, records, remote)
    rows = plan["actions"] if deferred is None else deferred
    counts = {kind: sum(a.get("kind") == kind for a in rows) for kind in ("create", "update")}
    pending = sum(counts.values())
    if plan["summary"] != {**ZERO_SUMMARY, **counts} or (
        deferred is not None and plan["actions"] != deferred
    ):
        raise ValueError("issue_0186_recovery_readback_failed")
    return {"zero_action_readback": not pending, "only_reviewed_pending_creates_remain": bool(pending)}


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
    """Validate the candidate or, on its first push, create the issue and append its receipt once."""
    applying = expected_parent is None and expected_head is None
    attestation = status.github_actions_push_attestation(run_reader) if applying else {}
    parent = attestation.get("event_before", expected_parent or "")
    head = attestation.get("event_after", expected_head or "")
    if applying:
        main_fetcher(root)
    if status._git(root, "rev-parse", "HEAD") != head or (
        applying and status._git(root, "rev-parse", "origin/main") != head
    ):
        raise ValueError("issue_0186_recovery_head_mismatch")
    gateway.validate_create_receipt_recovery_push(root, parent, head, stable_id=TARGET, validating_candidate=not applying)
    authority, binding, records = _original_authority(root)
    payload = authority["payload"]

    remote = remote_reader()
    holders = _carries(remote, CREATE_MARKER)
    claimed = _carries(remote, STABLE_MARKER)
    if len(holders) > 1 or {row["number"] for row in claimed} != {row["number"] for row in holders}:
        raise ValueError("issue_0186_recovery_duplicate_or_foreign_claim")
    if holders:
        if not _accepted(holders[0], authority):
            raise ValueError("issue_0186_recovery_marker_without_receipt")
        return {"accepted": True, "terminal_status": "already_accepted", "transport_writes": 0,
                **_readback(root, records, remote)}
    if gateway.claim_inventory_sha256(remote) != payload["claim_inventory_sha256"] or not (
        gateway.reconcile_authority_ledger(records[:-1], remote, root=root).get("accepted")
    ):
        raise ValueError("issue_0186_recovery_other_claims_changed")
    scoped = sync.scope_admitted_intake_plan(
        root, payload["source_sha"], _plan(root, records[:-1], remote), create_id=TARGET,
    )
    action = scoped["actions"][0]
    if (
        scoped["plan_sha256"] != payload["plan_sha256"]
        or action.get("title") != payload["title"]
        or sync.managed_block(action) != payload["managed_body"]
    ):
        raise ValueError("issue_0186_recovery_plan_mismatch")
    deferred = scoped.get("deferred_intake_creates", [])
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
        raise ValueError("issue_0186_recovery_head_mismatch")
    gateway.validate_create_receipt_recovery_push(root, parent, head, stable_id=TARGET)
    client = transport or gateway.GhMutationTransport()
    # Freshly read the whole claim inventory immediately before the one create.
    if gateway.claim_inventory_sha256(client.list_issues()) != gateway.claim_inventory_sha256(remote):
        raise ValueError("issue_0186_recovery_stale_before_create")
    proof_verifier(attestation)
    title, body = payload["title"], CREATE_MARKER + "\n" + payload["managed_body"]
    evidence = {"transport_writes": 1, "zero_action_readback": False}
    try:
        number: int | None = None
        try:
            number = client.create_open_issue(title, body)
        except Exception as exc:
            if not gateway._is_ambiguous_write_error(exc):
                raise
        after = gateway._list_after_write(client, number, CREATE_MARKER)
        created = _carries(after, CREATE_MARKER)
        if (
            len(created) != 1
            or (number is not None and int(created[0]["number"]) != number)
            or len(_carries(after, STABLE_MARKER)) != 1
            or gateway.claim_inventory_sha256([row for row in after if row is not created[0]])
            != gateway.claim_inventory_sha256(remote)
        ):
            raise RuntimeError("issue_0186_recovery_create_unresolved")
        issue_number = int(created[0]["number"])
        issue = client.fetch_issue(issue_number)
        snapshot = gateway.normalise_issue_snapshot(issue)
        if (
            snapshot["title"] != title
            or snapshot["body"] != body
            or snapshot["state"] != "open"
            or snapshot["comments"]
            or not snapshot["id"]
            or not snapshot["node_id"]
        ):
            raise RuntimeError("issue_0186_recovery_create_unresolved")
        if number is None and not _by_actions_bot(issue):  # a lost response: never receipt a lookalike
            raise RuntimeError("issue_0186_recovery_creator_not_actions_bot")
        receipt, receipt_body = gateway.build_create_receipt(
            issue,
            mutation_id=AUTHORITY_ID,
            stable_id=TARGET,
            authority_id=AUTHORITY_ID,
            authority_sequence=int(authority["sequence"]),
            source_sha=payload["source_sha"],
            head_sha=ORIGINAL_HEAD,
            ledger_blob_oid=binding["ledger_blob_oid"],
            ledger_blob_sha256=binding["ledger_blob_sha256"],
            plan_sha256=payload["plan_sha256"],
            **{key: attestation[key] for key in ATTESTATION_KEYS},
        )
        evidence["transport_writes"] = 2
        try:
            client.append_comment(issue_number, receipt_body)
        except Exception as exc:
            if not gateway._is_ambiguous_write_error(exc):
                raise
        final = client.fetch_issue(issue_number)
        if not gateway._postwrite_matches(issue, final, receipt_body) or not _accepted(final, authority):
            raise RuntimeError("issue_0186_recovery_receipt_unresolved")
        readback = _readback(root, records, remote_reader(), deferred)
    except Exception as exc:
        raise gateway.MutationTransportError(str(exc), evidence) from exc
    return {
        "accepted": True,
        "terminal_status": "created_and_receipt_written",
        "transport_writes": 2,
        "issue_number": issue_number,
        "authority_id": AUTHORITY_ID,
        "receipt_mutation_id": receipt["receipt_mutation_id"],
        **readback,
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
        "transport_writes": 0,
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
