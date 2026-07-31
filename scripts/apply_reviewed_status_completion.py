"""Validate and apply one reviewed post-merge programme-status completion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import github_mutation_gateway as mutation_gateway
    from scripts import sync_github_issues as sync
    from scripts.issue_registry_core import CONTROL_ALLOWED_TRANSITIONS, REGISTRY_PATH
except ModuleNotFoundError:
    import github_mutation_gateway as mutation_gateway
    import sync_github_issues as sync
    from issue_registry_core import CONTROL_ALLOWED_TRANSITIONS, REGISTRY_PATH


SCHEMA_VERSION = "etf-ai-cockpit.status-completion-candidate/2.0"
DEFAULT_CANDIDATE = Path(".github/issue-transitions/post-merge-control-candidate.json")
ZERO_SUMMARY = {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
STATUS_RE = re.compile(r"^- Programme status: `([^`]+)`$", re.MULTILINE)
EXPECTED_KEYS = {
    "schema_version",
    "execution_allowed",
    "expected_parent_sha",
    "authority_ref",
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
    candidate_bytes: bytes,
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
    expected_bytes = subprocess.check_output(
        ["git", "cat-file", "blob", expected_blob],
        cwd=root,
    )
    if candidate_bytes != expected_bytes and candidate_bytes != expected_bytes.replace(
        b"\n", b"\r\n"
    ):
        raise ValueError("checked-out candidate bytes do not match expected head")


def _canonical_candidate_blob_sha256(root: Path, expected_head: str) -> str:
    blob = _git(root, "rev-parse", f"{expected_head}:{DEFAULT_CANDIDATE.as_posix()}")
    return hashlib.sha256(
        subprocess.check_output(["git", "cat-file", "blob", blob], cwd=root)
    ).hexdigest()


def load_candidate(candidate_bytes: bytes) -> dict[str, Any]:
    payload = json.loads(candidate_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("status-completion candidate must be a JSON object")
    return payload


def validate_git_bindings(
    root: Path,
    candidate: dict[str, Any],
    *,
    candidate_path: Path,
    candidate_bytes: bytes,
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
        candidate_bytes=candidate_bytes,
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
        if not _is_ancestor(root, expected_parent, expected_head):
            raise ValueError(
                "candidate expected parent/base is not an ancestor of head"
            )
        current_main = _git(root, "rev-parse", main_ref)
        if not _is_ancestor(root, expected_head, current_main):
            raise ValueError("status-completion trigger head is not on current main")
        changed = _git(
            root,
            "diff",
            "--name-only",
            expected_head,
            current_main,
            "--",
            DEFAULT_CANDIDATE.as_posix(),
            REGISTRY_PATH.as_posix(),
        )
        if changed:
            raise ValueError("status-completion authority was superseded on current main")


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
    if not HASH_RE.fullmatch(str(candidate.get("authority_ref", ""))):
        raise ValueError("candidate authority reference is invalid")
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
    mutation_transport: mutation_gateway.MutationTransport | None = None,
    event_name: str | None = None,
    event_ref: str | None = None,
    run_attempt: str | None = None,
    event_before: str | None = None,
    event_after: str | None = None,
    actor: str | None = None,
    pusher: str | None = None,
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
        if not apply and not event_before and not event_after:
            event_name = "push"
            event_ref = "refs/heads/main"
            run_attempt = "1"
            event_before = expected_parent
            event_after = expected_head
            actor = "offline-validator"
            pusher = "offline-validator"

        if (
            event_name != "push"
            or event_ref != "refs/heads/main"
            or run_attempt != "1"
            or event_before != expected_parent
            or event_after != expected_head
            or not actor
            or not pusher
        ):
            raise mutation_gateway.MutationPolicyError(
                "ineligible_authority_gateway_event",
                mutation_gateway._policy_evidence(
                    "ineligible_authority_gateway_event"
                ),
            )
        prior_records, records, git_binding = (
            mutation_gateway.validate_authority_git_transition(
                root,
                event_before=expected_parent,
                event_after=expected_head,
                main_ref=main_ref,
            )
        )
        authority = records[-1]
        evidence["authority"] = git_binding
        registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
        remote = remote_reader()
        map_path = root / sync.DEFAULT_MAP_PATH
        historical_map = (
            json.loads(map_path.read_text(encoding="utf-8"))
            if map_path.exists()
            else None
        )
        if prior_records:
            prior_reconciliation = mutation_gateway.reconcile_authority_ledger(
                prior_records, remote, root=root
            )
            if not prior_reconciliation.get("accepted"):
                raise ValueError(
                    "predecessor authority reconciliation failed: "
                    + str(prior_reconciliation.get("error"))
                )
        if authority["authority_type"] == "legacy_bootstrap":
            reconciliation = mutation_gateway.reconcile_authority_ledger(
                records, remote, root=None
            )
            if not reconciliation.get("accepted"):
                raise ValueError(
                    "legacy bootstrap reconciliation failed: "
                    + str(reconciliation.get("error"))
                )
            evidence["terminal_status"] = "bootstrap_validated"
            evidence["zero_action_readback"] = True
            print("VALIDATED_GITHUB_MUTATION_AUTHORITY_BOOTSTRAP")
            return

        plan = sync.plan_actions(
            registry,
            remote,
            historical_map=historical_map,
            authority_records=prior_records,
            authority_root=root,
        )
        payload = authority["payload"]
        if authority["authority_type"] == "status":
            candidate_bytes = candidate_path.read_bytes()
            candidate = load_candidate(candidate_bytes)
            validate_git_bindings(
                root,
                candidate,
                candidate_path=candidate_path,
                candidate_bytes=candidate_bytes,
                expected_parent=expected_parent,
                expected_head=expected_head,
                main_ref=main_ref,
            )
            validate_candidate(candidate, plan, remote)
            candidate_oid = _git(
                root,
                "rev-parse",
                f"{expected_head}:{DEFAULT_CANDIDATE.as_posix()}",
            )
            candidate_sha256 = _canonical_candidate_blob_sha256(root, expected_head)
            if (
                candidate.get("authority_ref") != payload["candidate_authority_ref"]
                or payload["candidate_authority_ref"]
                != mutation_gateway.candidate_authority_ref(payload)
                or payload["candidate_blob_oid"] != candidate_oid
                or payload["candidate_blob_sha256"] != candidate_sha256
                or payload["plan_sha256"] != candidate["plan_semantic_sha256"]
            ):
                raise ValueError("candidate does not bind the committed authority")
            expected_update = candidate["expected_update"]
            stable_id = str(expected_update["stable_id"])
            reviewed_matches = [
                issue
                for issue in remote
                if int(issue.get("number", 0)) == payload["issue_number"]
                and str(issue.get("id", "")) == payload["database_id"]
                and str(issue.get("node_id") or issue.get("nodeId") or "")
                == payload["node_id"]
            ]
            if len(reviewed_matches) != 1:
                raise ValueError("authority target issue identity mismatch")
            projection = mutation_gateway.project_status_events(reviewed_matches[0])
            evidence.update(
                {
                    "remote_inventory_sha256": candidate.get(
                        "remote_inventory_sha256"
                    ),
                    "plan_semantic_sha256": candidate.get("plan_semantic_sha256"),
                    "authority_ref": candidate.get("authority_ref"),
                    "expected_update": expected_update,
                    "candidate_blob_sha256": candidate_sha256,
                    "action_scope": sync.safe_plan_evidence(plan, remote)["actions"],
                    "mutation": {
                        "transport": "github_issue_comment_append",
                        "authority_id": authority["authority_id"],
                        "predecessor_event_id": projection.get("head_event_id"),
                        "predecessor_event_sha256": projection.get(
                            "head_event_sha256"
                        ),
                        "candidate_blob_oid": candidate_oid,
                        "candidate_blob_sha256": candidate_sha256,
                        "plan_sha256": candidate["plan_semantic_sha256"],
                    },
                }
            )
            if not apply:
                evidence["terminal_status"] = "validated"
                print("VALIDATED_STATUS_COMPLETION_CANDIDATE")
                return
            gateway_evidence = mutation_gateway.append_status_event(
                reviewed_matches[0],
                stable_id=stable_id,
                from_status=str(expected_update["from_status"]),
                to_status=str(expected_update["to_status"]),
                source_sha=expected_parent,
                head_sha=expected_head,
                candidate_blob_sha256=candidate_sha256,
                plan_sha256=str(candidate["plan_semantic_sha256"]),
                event_name=str(event_name),
                event_ref=str(event_ref),
                run_attempt=str(run_attempt),
                event_before=str(event_before),
                event_after=str(event_after),
                actor=str(actor),
                pusher=str(pusher),
                authority_record=authority,
                git_binding=git_binding,
                transport=mutation_transport,
                authority_revalidator=lambda: mutation_gateway.validate_authority_git_transition(
                    root,
                    event_before=expected_parent,
                    event_after=expected_head,
                    main_ref=main_ref,
                ),
            )
        elif authority["authority_type"] == "create":
            if not apply:
                evidence["action_scope"] = sync.safe_plan_evidence(plan, remote)[
                    "actions"
                ]
                evidence["terminal_status"] = "validated"
                print("VALIDATED_GITHUB_CREATE_AUTHORITY")
                return
            gateway_evidence = sync.apply_actions(
                plan,
                approved_sha256=str(payload["plan_sha256"]),
                mutation_transport=mutation_transport,
                authority_record=authority,
                git_binding=git_binding,
                event_name=str(event_name),
                event_ref=str(event_ref),
                run_attempt=str(run_attempt),
                event_before=str(event_before),
                event_after=str(event_after),
            )
        else:
            raise ValueError("unsupported GitHub mutation authority")
        evidence["mutation"] = gateway_evidence
        if not gateway_evidence.get("accepted"):
            raise RuntimeError(
                f"authority projection not accepted: {gateway_evidence['terminal_status']}"
            )
        readback_remote = remote_reader()
        reconciliation = mutation_gateway.reconcile_authority_ledger(
            records, readback_remote, root=root
        )
        readback = sync.plan_actions(
            registry,
            readback_remote,
            historical_map=historical_map,
            authority_records=records,
            authority_root=root,
        )
        if (
            not reconciliation.get("accepted")
            or readback.get("summary") != ZERO_SUMMARY
            or readback.get("actions") != []
        ):
            evidence["zero_action_readback"] = False
            raise RuntimeError("GitHub authority read-back is not fully reconciled")
        evidence["terminal_status"] = "applied_and_verified"
        evidence["zero_action_readback"] = True
        print("APPLIED_AND_VERIFIED_GITHUB_MUTATION_AUTHORITY")
        return
    except Exception as exc:
        if isinstance(exc, mutation_gateway.MutationGatewayError):
            evidence["mutation"] = exc.evidence
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
    parser.add_argument("--event-name")
    parser.add_argument("--event-ref")
    parser.add_argument("--run-attempt")
    parser.add_argument("--event-before")
    parser.add_argument("--event-after")
    parser.add_argument("--actor")
    parser.add_argument("--pusher")
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
        event_name=args.event_name,
        event_ref=args.event_ref,
        run_attempt=args.run_attempt,
        event_before=args.event_before,
        event_after=args.event_after,
        actor=args.actor,
        pusher=args.pusher,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
