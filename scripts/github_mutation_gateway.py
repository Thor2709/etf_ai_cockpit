"""Fail-closed gateway for the repository's only permitted GitHub mutation.

The gateway intentionally does not claim server-side compare-and-swap.  It
performs an exact pre-request snapshot check, appends one deterministic status
event without retrying the write, and then verifies the observable result.
Concurrent changes in the unavoidable final network gap are reported as
conflicts and the appended event is not accepted as authoritative.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol


REPO = "Thor2709/etf_ai_cockpit"
EVENT_PREFIX = "<!-- etf-ai-cockpit:status-event:v1 -->\n"
EVENT_RECEIPT_PREFIX = "<!-- etf-ai-cockpit:status-event-acceptance:v1 -->\n"
COMPENSATION_PREFIX = "<!-- etf-ai-cockpit:status-compensation:v1 -->\n"
CREATE_MARKER_TEMPLATE = "<!-- etf-ai-cockpit:create-mutation-id={} -->"
CREATE_RECEIPT_PREFIX = "<!-- etf-ai-cockpit:create-acceptance:v1 -->\n"
EVENT_SCHEMA = "etf-ai-cockpit.status-event/1.0"
STABLE_ID_RE = re.compile(r"(?:ISSUE|UPDATEV2)-\d{4}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
STATUS_RE = re.compile(r"^- Programme status: `([^`]+)`$", re.MULTILINE)
BOT_AUTHORS = frozenset({"github-actions[bot]"})
GITHUB_ACTIONS_BOT_USER_ID = "41898282"
GITHUB_ACTIONS_APP_ID = "15368"
EVENT_KEYS = {
    "schema_version",
    "execution_allowed",
    "stable_id",
    "from_status",
    "to_status",
    "source_sha",
    "head_sha",
    "candidate_blob_sha256",
    "plan_sha256",
    "mutation_id",
    "predecessor_event_id",
    "predecessor_event_sha256",
    "event_name",
    "event_ref",
    "run_attempt",
    "event_before",
    "event_after",
    "actor",
    "pusher",
}
EVENT_RECEIPT_KEYS = {
    "schema_version",
    "execution_allowed",
    "receipt_mutation_id",
    "proposal_mutation_id",
    "proposal_comment_id",
    "proposal_comment_node_id",
    "proposal_body_sha256",
    "candidate_blob_sha256",
    "head_sha",
    "predecessor_event_id",
    "predecessor_event_sha256",
    "verified_postwrite_snapshot_sha256",
}
CREATE_RECEIPT_KEYS = {
    "schema_version",
    "execution_allowed",
    "receipt_mutation_id",
    "create_mutation_id",
    "stable_id",
    "issue_id",
    "issue_node_id",
    "title_sha256",
    "body_sha256",
    "verified_snapshot_sha256",
}


class MutationGatewayError(ValueError):
    """A fail-closed gateway decision with privacy-safe machine evidence."""

    def __init__(self, code: str, evidence: dict[str, Any]) -> None:
        self.code = code
        self.evidence = evidence
        super().__init__(code)


class MutationPolicyError(MutationGatewayError):
    """The requested mutation is outside the allowlist."""


class MutationTransportError(MutationGatewayError):
    """The single write could not be reconciled safely."""


class MutationTransport(Protocol):
    def list_issues(self) -> list[dict[str, Any]]: ...

    def fetch_issue(self, number: int) -> dict[str, Any]: ...

    def append_comment(self, number: int, body: str) -> None: ...

    def create_open_issue(self, title: str, body: str) -> None: ...


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _author_login(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("login", ""))
    return str(value or "")


def normalise_comment(comment: dict[str, Any]) -> dict[str, Any]:
    author = comment.get("author") or comment.get("user")
    app = comment.get("performedViaGithubApp") or comment.get(
        "performed_via_github_app"
    )
    return {
        "id": str(comment.get("id") or comment.get("databaseId") or ""),
        "node_id": str(comment.get("node_id") or comment.get("nodeId") or ""),
        "body": str(comment.get("body") or ""),
        "author": _author_login(author),
        "author_id": str(
            author.get("id", "")
            if isinstance(author, dict)
            else comment.get("author_id", "")
        ),
        "author_type": str(
            author.get("type", "")
            if isinstance(author, dict)
            else comment.get("author_type", "")
        ),
        "app_slug": str(
            app.get("slug", "")
            if isinstance(app, dict) and app
            else comment.get("app_slug", "")
        ),
        "app_id": str(
            app.get("id", "")
            if isinstance(app, dict) and app
            else comment.get("app_id", "")
        ),
        "created_at": str(comment.get("createdAt") or comment.get("created_at") or ""),
        "updated_at": str(comment.get("updatedAt") or comment.get("updated_at") or ""),
        "url": str(comment.get("url") or comment.get("html_url") or ""),
    }


def normalise_issue_snapshot(issue: dict[str, Any]) -> dict[str, Any]:
    labels = issue.get("labels") or []
    normalised_labels = sorted(
        str(label.get("name", "") if isinstance(label, dict) else label)
        for label in labels
    )
    return {
        "id": str(issue.get("id") or ""),
        "node_id": str(issue.get("node_id") or issue.get("nodeId") or ""),
        "number": int(issue.get("number", 0)),
        "title": str(issue.get("title") or ""),
        "body": str(issue.get("body") or ""),
        "state": str(issue.get("state") or "OPEN").lower(),
        "url": str(issue.get("url") or issue.get("html_url") or ""),
        "labels": normalised_labels,
        "comments": [normalise_comment(row) for row in issue.get("comments") or []],
        # This is diagnostic revision metadata for ABA detection, not CAS.
        "updated_at": str(issue.get("updatedAt") or issue.get("updated_at") or ""),
    }


def snapshot_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = normalise_issue_snapshot(snapshot)
    return {
        "snapshot_sha256": _sha256(_json_bytes(value)),
        "body_sha256": _sha256(value["body"]),
        "body_length": len(value["body"].encode()),
        "comment_count": len(value["comments"]),
        "comments_sha256": _sha256(_json_bytes(value["comments"])),
        "updated_at_sha256": _sha256(value["updated_at"]),
    }


def _claim_inventory(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "number": int(issue.get("number", 0)),
                "title": str(issue.get("title") or ""),
                "body": str(issue.get("body") or ""),
                "state": str(issue.get("state") or "OPEN").lower(),
                "url": str(issue.get("url") or issue.get("html_url") or ""),
            }
            for issue in issues
        ),
        key=lambda row: row["number"],
    )


def claim_inventory_sha256(issues: list[dict[str, Any]]) -> str:
    return _sha256(_json_bytes(_claim_inventory(issues)))


def _legacy_anchor(stable_id: str, status: str) -> tuple[str, str]:
    event_id = f"legacy:{stable_id}"
    digest = _sha256(_json_bytes({"stable_id": stable_id, "status": status}))
    return event_id, digest


def parse_event_comment(body: str) -> dict[str, Any] | None:
    if not body.startswith(EVENT_PREFIX):
        return None
    try:
        value = json.loads(body[len(EVENT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_status_event_json") from exc
    if not isinstance(value, dict) or set(value) != EVENT_KEYS:
        raise ValueError("invalid_status_event_fields")
    if body != EVENT_PREFIX + _json_bytes(value).decode():
        raise ValueError("noncanonical_status_event")
    if value.get("schema_version") != EVENT_SCHEMA:
        raise ValueError("invalid_status_event_schema")
    if value.get("execution_allowed") is not False:
        raise ValueError("status_event_execution_authority")
    if not STABLE_ID_RE.fullmatch(str(value.get("stable_id", ""))):
        raise ValueError("invalid_status_event_stable_id")
    for field in ("source_sha", "head_sha"):
        if not SHA_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_event_{field}")
    if (
        value.get("event_name") != "push"
        or value.get("event_ref") != "refs/heads/main"
        or value.get("run_attempt") != "1"
        or value.get("event_before") != value.get("source_sha")
        or value.get("event_after") != value.get("head_sha")
        or not value.get("actor")
        or not value.get("pusher")
    ):
        raise ValueError("invalid_status_event_workflow_binding")
    for field in (
        "candidate_blob_sha256",
        "plan_sha256",
        "mutation_id",
        "predecessor_event_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_event_{field}")
    return value


def parse_event_receipt(body: str) -> dict[str, Any] | None:
    if not body.startswith(EVENT_RECEIPT_PREFIX):
        return None
    try:
        value = json.loads(body[len(EVENT_RECEIPT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_status_event_receipt_json") from exc
    if not isinstance(value, dict) or set(value) != EVENT_RECEIPT_KEYS:
        raise ValueError("invalid_status_event_receipt_fields")
    if body != EVENT_RECEIPT_PREFIX + _json_bytes(value).decode():
        raise ValueError("noncanonical_status_event_receipt")
    if (
        value.get("schema_version")
        != "etf-ai-cockpit.status-event-acceptance/1.0"
        or value.get("execution_allowed") is not False
    ):
        raise ValueError("invalid_status_event_receipt_authority")
    for field in (
        "receipt_mutation_id",
        "proposal_mutation_id",
        "proposal_body_sha256",
        "candidate_blob_sha256",
        "predecessor_event_sha256",
        "verified_postwrite_snapshot_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_event_receipt_{field}")
    if not SHA_RE.fullmatch(str(value.get("head_sha", ""))):
        raise ValueError("invalid_status_event_receipt_head_sha")
    if not value.get("proposal_comment_id") or not value.get("proposal_comment_node_id"):
        raise ValueError("invalid_status_event_receipt_comment_identity")
    return value


def _acceptance_snapshot_sha256(
    snapshot: dict[str, Any], comments: list[dict[str, Any]] | None = None
) -> str:
    value = normalise_issue_snapshot(snapshot)
    protected = {
        key: value[key]
        for key in ("number", "title", "body", "state", "url", "labels")
    }
    protected["comments"] = comments if comments is not None else value["comments"]
    return _sha256(_json_bytes(protected))


def build_event_receipt(
    proposal: dict[str, Any],
    proposal_comment: dict[str, Any],
    proposal_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    identity = {
        "proposal_mutation_id": proposal["mutation_id"],
        "proposal_comment_id": proposal_comment["id"],
        "proposal_comment_node_id": proposal_comment["node_id"],
        "proposal_body_sha256": _sha256(proposal_comment["body"]),
        "candidate_blob_sha256": proposal["candidate_blob_sha256"],
        "head_sha": proposal["head_sha"],
        "predecessor_event_id": proposal["predecessor_event_id"],
        "predecessor_event_sha256": proposal["predecessor_event_sha256"],
        "verified_postwrite_snapshot_sha256": _acceptance_snapshot_sha256(
            proposal_snapshot
        ),
        "execution_allowed": False,
    }
    receipt = {
        "schema_version": "etf-ai-cockpit.status-event-acceptance/1.0",
        **identity,
        "receipt_mutation_id": _sha256(_json_bytes(identity)),
    }
    return receipt, EVENT_RECEIPT_PREFIX + _json_bytes(receipt).decode()


def project_status_events(issue: dict[str, Any]) -> dict[str, Any]:
    snapshot = normalise_issue_snapshot(issue)
    matches = STATUS_RE.findall(snapshot["body"])
    if len(matches) != 1:
        return {"accepted": False, "error": "ambiguous_legacy_programme_status"}
    stable_ids = re.findall(
        r"<!--\s*etf-ai-cockpit:stable-id=((?:ISSUE|UPDATEV2)-\d{4})\s*-->",
        snapshot["body"],
    )
    if len(set(stable_ids)) != 1:
        return {"accepted": False, "error": "ambiguous_legacy_stable_id"}
    stable_id = stable_ids[0]
    status = matches[0]
    predecessor_id, predecessor_hash = _legacy_anchor(stable_id, status)
    event_count = 0

    def require_bot(comment: dict[str, Any], *, receipt: bool = False) -> None:
        label = "status_event_receipt" if receipt else "status_event"
        if comment["author"] not in BOT_AUTHORS:
            raise ValueError(f"{label}_not_bot_authored")
        if comment["author_type"] != "Bot" or comment["app_slug"] != "github-actions":
            raise ValueError(f"{label}_bot_provenance_invalid")
        if (
            comment["author_id"] != GITHUB_ACTIONS_BOT_USER_ID
            or comment["app_id"] != GITHUB_ACTIONS_APP_ID
        ):
            raise ValueError(f"{label}_bot_attribution_mismatch")
        if comment["created_at"] != comment["updated_at"]:
            raise ValueError(f"edited_{label}")

    try:
        index = 0
        comments = snapshot["comments"]
        while index < len(comments):
            comment = comments[index]
            if comment["body"].startswith(COMPENSATION_PREFIX):
                try:
                    compensation = json.loads(
                        comment["body"][len(COMPENSATION_PREFIX) :]
                    )
                except json.JSONDecodeError as exc:
                    raise ValueError("invalid_status_compensation") from exc
                if (
                    not isinstance(compensation, dict)
                    or compensation.get("schema_version")
                    != "etf-ai-cockpit.status-compensation/1.0"
                    or compensation.get("execution_allowed") is not False
                    or not HASH_RE.fullmatch(
                        str(compensation.get("anomalous_event_sha256", ""))
                    )
                ):
                    raise ValueError("invalid_status_compensation")
                index += 1
                continue
            if parse_event_receipt(comment["body"]) is not None:
                raise ValueError("orphan_status_event_receipt")
            event = parse_event_comment(comment["body"])
            if event is None:
                index += 1
                continue
            require_bot(comment)
            if event["stable_id"] != stable_id:
                raise ValueError("status_event_stable_id_mismatch")
            if index + 1 >= len(comments):
                raise ValueError("orphan_status_event_proposal")
            receipt_comment = comments[index + 1]
            receipt = parse_event_receipt(receipt_comment["body"])
            if receipt is None:
                raise ValueError("orphan_status_event_proposal")
            require_bot(receipt_comment, receipt=True)
            if (
                event["predecessor_event_id"] != predecessor_id
                or event["predecessor_event_sha256"] != predecessor_hash
                or event["from_status"] != status
                or receipt["proposal_mutation_id"] != event["mutation_id"]
                or receipt["proposal_comment_id"] != comment["id"]
                or receipt["proposal_comment_node_id"] != comment["node_id"]
                or receipt["proposal_body_sha256"] != _sha256(comment["body"])
                or receipt["candidate_blob_sha256"] != event["candidate_blob_sha256"]
                or receipt["head_sha"] != event["head_sha"]
                or receipt["predecessor_event_id"] != predecessor_id
                or receipt["predecessor_event_sha256"] != predecessor_hash
                or receipt["verified_postwrite_snapshot_sha256"]
                != _acceptance_snapshot_sha256(snapshot, comments[: index + 1])
            ):
                raise ValueError("invalid_status_event_acceptance_pair")
            status = str(event["to_status"])
            predecessor_id = str(event["mutation_id"])
            predecessor_hash = _sha256(comment["body"])
            event_count += 1
            index += 2
    except ValueError as exc:
        return {"accepted": False, "error": str(exc)}
    return {
        "accepted": True,
        "status": status,
        "head_event_id": predecessor_id,
        "head_event_sha256": predecessor_hash,
        "event_count": event_count,
    }


def build_status_event(
    *,
    stable_id: str,
    from_status: str,
    to_status: str,
    source_sha: str,
    head_sha: str,
    candidate_blob_sha256: str,
    plan_sha256: str,
    predecessor_event_id: str,
    predecessor_event_sha256: str,
    event_name: str,
    event_ref: str,
    run_attempt: str,
    event_before: str,
    event_after: str,
    actor: str,
    pusher: str,
) -> tuple[dict[str, Any], str]:
    identity = {
        "stable_id": stable_id,
        "from_status": from_status,
        "to_status": to_status,
        "source_sha": source_sha,
        "head_sha": head_sha,
        "candidate_blob_sha256": candidate_blob_sha256,
        "plan_sha256": plan_sha256,
        "predecessor_event_id": predecessor_event_id,
        "predecessor_event_sha256": predecessor_event_sha256,
        "execution_allowed": False,
        "event_name": event_name,
        "event_ref": event_ref,
        "run_attempt": run_attempt,
        "event_before": event_before,
        "event_after": event_after,
        "actor": actor,
        "pusher": pusher,
    }
    event = {
        "schema_version": EVENT_SCHEMA,
        **identity,
        "mutation_id": _sha256(_json_bytes(identity)),
    }
    return event, EVENT_PREFIX + _json_bytes(event).decode()


def describe_status_event(
    reviewed_snapshot: dict[str, Any],
    **bindings: str,
) -> dict[str, Any]:
    """Return privacy-safe deterministic identity for the reviewed append."""

    projection = project_status_events(reviewed_snapshot)
    if not projection.get("accepted") or projection.get("status") != bindings.get(
        "from_status"
    ):
        raise MutationPolicyError(
            "invalid_reviewed_status_projection",
            _policy_evidence(
                "invalid_reviewed_status_projection", bindings.get("plan_sha256", "")
            ),
        )
    event, body = build_status_event(
        **bindings,
        predecessor_event_id=str(projection["head_event_id"]),
        predecessor_event_sha256=str(projection["head_event_sha256"]),
    )
    return {
        "transport": "github_issue_comment_append",
        "mutation_id": event["mutation_id"],
        "event_sha256": _sha256(body),
        "event_length": len(body.encode()),
        "predecessor_event_id": projection["head_event_id"],
        "predecessor_event_sha256": projection["head_event_sha256"],
        "candidate_blob_sha256": bindings["candidate_blob_sha256"],
        "plan_sha256": bindings["plan_sha256"],
    }


def _policy_evidence(code: str, plan_sha256: str = "") -> dict[str, Any]:
    return {
        "schema_version": "etf-ai-cockpit.github-mutation-evidence/1.0",
        "execution_allowed": False,
        "accepted": False,
        "terminal_status": "policy_rejected",
        "policy_code": code,
        "plan_sha256": plan_sha256,
        "transport_writes": 0,
    }


def build_create_receipt(
    issue: dict[str, Any], *, mutation_id: str, stable_id: str
) -> tuple[dict[str, Any], str]:
    snapshot = normalise_issue_snapshot(issue)
    identity = {
        "create_mutation_id": mutation_id,
        "stable_id": stable_id,
        "issue_id": snapshot["id"],
        "issue_node_id": snapshot["node_id"],
        "title_sha256": _sha256(snapshot["title"]),
        "body_sha256": _sha256(snapshot["body"]),
        "verified_snapshot_sha256": _acceptance_snapshot_sha256(snapshot),
        "execution_allowed": False,
    }
    receipt = {
        "schema_version": "etf-ai-cockpit.create-acceptance/1.0",
        **identity,
        "receipt_mutation_id": _sha256(_json_bytes(identity)),
    }
    return receipt, CREATE_RECEIPT_PREFIX + _json_bytes(receipt).decode()


def parse_create_receipt(body: str) -> dict[str, Any] | None:
    if not body.startswith(CREATE_RECEIPT_PREFIX):
        return None
    try:
        value = json.loads(body[len(CREATE_RECEIPT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_create_receipt_json") from exc
    if not isinstance(value, dict) or set(value) != CREATE_RECEIPT_KEYS:
        raise ValueError("invalid_create_receipt_fields")
    if body != CREATE_RECEIPT_PREFIX + _json_bytes(value).decode():
        raise ValueError("noncanonical_create_receipt")
    if (
        value.get("schema_version") != "etf-ai-cockpit.create-acceptance/1.0"
        or value.get("execution_allowed") is not False
    ):
        raise ValueError("invalid_create_receipt_authority")
    for field in (
        "receipt_mutation_id",
        "create_mutation_id",
        "title_sha256",
        "body_sha256",
        "verified_snapshot_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_create_receipt_{field}")
    return value


def validate_create_acceptance(issue: dict[str, Any]) -> dict[str, Any]:
    snapshot = normalise_issue_snapshot(issue)
    markers = re.findall(
        r"<!-- etf-ai-cockpit:create-mutation-id=([0-9a-f]{64}) -->",
        snapshot["body"],
    )
    receipts = []
    for index, comment in enumerate(snapshot["comments"]):
        try:
            receipt = parse_create_receipt(comment["body"])
        except ValueError as exc:
            return {"accepted": False, "error": str(exc)}
        if receipt is not None:
            receipts.append((index, receipt, comment))
    if not markers:
        return (
            {"accepted": False, "error": "orphan_create_receipt"}
            if receipts
            else {"accepted": True, "legacy": True}
        )
    if len(markers) != 1 or len(receipts) != 1:
        return {"accepted": False, "error": "orphan_or_duplicate_create_acceptance"}
    index, receipt, comment = receipts[0]
    stable = re.findall(
        r"<!--\s*etf-ai-cockpit:stable-id=((?:ISSUE|UPDATEV2)-\d{4})\s*-->",
        snapshot["body"],
    )
    if (
        len(set(stable)) != 1
        or receipt["create_mutation_id"] != markers[0]
        or receipt["stable_id"] != stable[0]
        or receipt["issue_id"] != snapshot["id"]
        or receipt["issue_node_id"] != snapshot["node_id"]
        or receipt["title_sha256"] != _sha256(snapshot["title"])
        or receipt["body_sha256"] != _sha256(snapshot["body"])
        or receipt["verified_snapshot_sha256"]
        != _acceptance_snapshot_sha256(snapshot, snapshot["comments"][:index])
        or comment["author"] != "github-actions[bot]"
        or comment["author_id"] != GITHUB_ACTIONS_BOT_USER_ID
        or comment["author_type"] != "Bot"
        or comment["app_slug"] != "github-actions"
        or comment["app_id"] != GITHUB_ACTIONS_APP_ID
        or comment["created_at"] != comment["updated_at"]
    ):
        return {"accepted": False, "error": "invalid_create_acceptance"}
    return {"accepted": True, "legacy": False, "mutation_id": markers[0]}


def _validate_plan_authority(plan: dict[str, Any], approved_sha256: str) -> list[dict[str, Any]]:
    from scripts.issue_registry_core import deterministic_json

    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    actual = _sha256(deterministic_json(unsigned))
    if approved_sha256 != plan.get("plan_sha256") or approved_sha256 != actual:
        raise MutationPolicyError(
            "approved_plan_sha256_mismatch", _policy_evidence("approved_plan_sha256_mismatch")
        )
    actions = plan.get("actions")
    if not isinstance(actions, list):
        raise MutationPolicyError("invalid_action_plan", _policy_evidence("invalid_action_plan"))
    return actions


def apply_reviewed_plan(
    plan: dict[str, Any],
    *,
    approved_sha256: str,
    create_body: str | None = None,
    transport: MutationTransport | None = None,
) -> dict[str, Any]:
    actions = _validate_plan_authority(plan, approved_sha256)
    if not actions:
        return {
            **_policy_evidence("no_action", approved_sha256),
            "accepted": True,
            "terminal_status": "no_action",
        }
    if len(actions) != 1:
        raise MutationPolicyError(
            "multi_action_plan_prohibited",
            _policy_evidence("multi_action_plan_prohibited", approved_sha256),
        )
    action = actions[0]
    kind = str(action.get("kind", ""))
    if (
        kind != "create"
        or action.get("desired_state") != "open"
        or not STABLE_ID_RE.fullmatch(str(action.get("stable_id", "")))
        or not isinstance(create_body, str)
    ):
        code = f"unsafe_action_plan:{kind}"
        raise MutationPolicyError(code, _policy_evidence(code, approved_sha256))

    expected_inventory = str(plan.get("claim_inventory_sha256", ""))
    if not HASH_RE.fullmatch(expected_inventory):
        raise MutationPolicyError(
            "missing_claim_inventory_authority",
            _policy_evidence("missing_claim_inventory_authority", approved_sha256),
        )
    stable_id = str(action["stable_id"])
    stable_marker = f"<!-- etf-ai-cockpit:stable-id={stable_id} -->"
    title = str(action.get("title", ""))
    identity = {
        "operation": "create_open_issue",
        "stable_id": stable_id,
        "title_sha256": _sha256(title),
        "managed_body_sha256": _sha256(create_body),
        "claim_inventory_sha256": expected_inventory,
        "plan_sha256": approved_sha256,
        "execution_allowed": False,
    }
    mutation_id = _sha256(_json_bytes(identity))
    marker = CREATE_MARKER_TEMPLATE.format(mutation_id)
    body = f"{marker}\n{create_body}"
    evidence = {
        "schema_version": "etf-ai-cockpit.github-mutation-evidence/1.0",
        "execution_allowed": False,
        "accepted": False,
        "terminal_status": "failed",
        "transport": "github_issue_create",
        "mutation_id": mutation_id,
        "stable_id": stable_id,
        "body_sha256": _sha256(body),
        "body_length": len(body.encode()),
        "transport_writes": 0,
    }
    gateway = transport or GhMutationTransport()
    before = gateway.list_issues()
    if claim_inventory_sha256(before) != expected_inventory:
        evidence["terminal_status"] = "stale_before_write"
        raise MutationGatewayError("stale_before_write", evidence)
    if any(stable_marker in str(issue.get("body") or "") for issue in before):
        evidence["terminal_status"] = "duplicate_stable_id_claim"
        raise MutationGatewayError("duplicate_stable_id_claim", evidence)

    reconciled: list[dict[str, Any]] | None = None
    try:
        evidence["transport_writes"] = 1
        gateway.create_open_issue(title, body)
    except BaseException as exc:
        if not _is_ambiguous_write_error(exc):
            evidence["terminal_status"] = "write_failed"
            raise MutationTransportError("write_failed", evidence) from exc
        reconciled = gateway.list_issues()
        exact = [issue for issue in reconciled if marker in str(issue.get("body") or "")]
        if len(exact) != 1:
            evidence["terminal_status"] = (
                "conflict_after_write" if len(exact) > 1 else "ambiguous_indeterminate"
            )
            raise MutationTransportError(
                str(evidence["terminal_status"]), evidence
            ) from exc

    after = reconciled or gateway.list_issues()
    prior = _claim_inventory(before)
    current = _claim_inventory(after)
    new_rows = [row for row in current if row not in prior]
    if (
        any(row not in current for row in prior)
        or len(new_rows) != 1
        or new_rows[0]["title"] != title
        or new_rows[0]["body"] != body
        or new_rows[0]["state"] != "open"
        or sum(marker in row["body"] for row in current) != 1
        or sum(stable_marker in row["body"] for row in current) != 1
    ):
        evidence["terminal_status"] = "conflict_after_write"
        return evidence
    created = normalise_issue_snapshot(gateway.fetch_issue(new_rows[0]["number"]))
    if (
        created["title"] != title
        or created["body"] != body
        or created["state"] != "open"
        or created["comments"]
        or not created["id"]
        or not created["node_id"]
    ):
        evidence["terminal_status"] = "conflict_after_write"
        return evidence
    receipt, receipt_body = build_create_receipt(
        created, mutation_id=mutation_id, stable_id=stable_id
    )
    evidence["receipt_mutation_id"] = receipt["receipt_mutation_id"]
    receipt_reconciled: dict[str, Any] | None = None
    try:
        evidence["transport_writes"] = 2
        gateway.append_comment(created["number"], receipt_body)
    except BaseException as exc:
        if not _is_ambiguous_write_error(exc):
            evidence["terminal_status"] = "receipt_write_failed"
            raise MutationTransportError("receipt_write_failed", evidence) from exc
        receipt_reconciled = normalise_issue_snapshot(
            gateway.fetch_issue(created["number"])
        )
        matches = [
            comment
            for comment in receipt_reconciled["comments"]
            if (
                (parsed := parse_create_receipt(comment["body"])) is not None
                and parsed["receipt_mutation_id"] == receipt["receipt_mutation_id"]
            )
        ]
        if len(matches) != 1:
            evidence["terminal_status"] = "receipt_ambiguous_indeterminate"
            raise MutationTransportError(
                "receipt_ambiguous_indeterminate", evidence
            ) from exc
    final = receipt_reconciled or normalise_issue_snapshot(
        gateway.fetch_issue(created["number"])
    )
    if not _postwrite_matches(created, final, receipt_body):
        evidence["terminal_status"] = "conflict_after_receipt"
        return evidence
    acceptance = validate_create_acceptance(final)
    if not acceptance.get("accepted"):
        evidence["terminal_status"] = "invalid_create_acceptance"
        return evidence
    evidence["accepted"] = True
    evidence["terminal_status"] = "accepted"
    return evidence


def _is_ambiguous_write_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, KeyboardInterrupt)):
        return True
    if isinstance(exc, subprocess.CalledProcessError):
        text = f"{exc.stdout or ''}\n{exc.stderr or ''}"
        return any(value in text for value in ("500", "502", "503", "504", "timeout"))
    return False


def _mutation_comments(snapshot: dict[str, Any], mutation_id: str) -> list[dict[str, Any]]:
    result = []
    for comment in normalise_issue_snapshot(snapshot)["comments"]:
        try:
            event = parse_event_comment(comment["body"])
        except ValueError:
            continue
        if event is not None and event["mutation_id"] == mutation_id:
            result.append(comment)
    return result


def _receipt_comments(snapshot: dict[str, Any], mutation_id: str) -> list[dict[str, Any]]:
    result = []
    for comment in normalise_issue_snapshot(snapshot)["comments"]:
        try:
            receipt = parse_event_receipt(comment["body"])
        except ValueError:
            continue
        if receipt is not None and receipt["receipt_mutation_id"] == mutation_id:
            result.append(comment)
    return result


def _postwrite_matches(
    before: dict[str, Any], after: dict[str, Any], body: str
) -> bool:
    before_n = normalise_issue_snapshot(before)
    after_n = normalise_issue_snapshot(after)
    for field in ("number", "title", "body", "state", "url", "labels"):
        if before_n[field] != after_n[field]:
            return False
    prior = before_n["comments"]
    if after_n["comments"][: len(prior)] != prior:
        return False
    appended = after_n["comments"][len(prior) :]
    return len(appended) == 1 and appended[0]["body"] == body


def append_status_event(
    reviewed_snapshot: dict[str, Any],
    *,
    stable_id: str,
    from_status: str,
    to_status: str,
    source_sha: str,
    head_sha: str,
    candidate_blob_sha256: str,
    plan_sha256: str,
    event_name: str,
    event_ref: str,
    run_attempt: str,
    event_before: str,
    event_after: str,
    actor: str,
    pusher: str,
    transport: MutationTransport | None = None,
    authority_revalidator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    eligibility = {
        "event_name": event_name,
        "event_ref": event_ref,
        "run_attempt": run_attempt,
        "event_before": event_before,
        "event_after": event_after,
        "actor": actor,
        "pusher": pusher,
    }
    if (
        event_name != "push"
        or event_ref != "refs/heads/main"
        or run_attempt != "1"
        or event_before != source_sha
        or event_after != head_sha
        or not actor
        or not pusher
    ):
        evidence = _policy_evidence("ineligible_status_append_event", plan_sha256)
        evidence["event_binding_sha256"] = _sha256(_json_bytes(eligibility))
        raise MutationPolicyError("ineligible_status_append_event", evidence)
    gateway = transport or GhMutationTransport()
    reviewed = normalise_issue_snapshot(reviewed_snapshot)
    identity = describe_status_event(
        reviewed,
        stable_id=stable_id,
        from_status=from_status,
        to_status=to_status,
        source_sha=source_sha,
        head_sha=head_sha,
        candidate_blob_sha256=candidate_blob_sha256,
        plan_sha256=plan_sha256,
        **eligibility,
    )
    projection = project_status_events(reviewed)
    event, body = build_status_event(
        stable_id=stable_id,
        from_status=from_status,
        to_status=to_status,
        source_sha=source_sha,
        head_sha=head_sha,
        candidate_blob_sha256=candidate_blob_sha256,
        plan_sha256=plan_sha256,
        predecessor_event_id=str(projection["head_event_id"]),
        predecessor_event_sha256=str(projection["head_event_sha256"]),
        **eligibility,
    )
    evidence = {
        "schema_version": "etf-ai-cockpit.github-mutation-evidence/1.0",
        "execution_allowed": False,
        "accepted": False,
        "terminal_status": "failed",
        "mutation_id": event["mutation_id"],
        "plan_sha256": plan_sha256,
        "event_sha256": _sha256(body),
        "event_length": len(body.encode()),
        "transport_writes": 0,
        **identity,
        "reviewed_snapshot": snapshot_evidence(reviewed),
    }
    fresh = normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
    evidence["prewrite_snapshot"] = snapshot_evidence(fresh)
    if fresh != reviewed:
        evidence["terminal_status"] = "stale_before_write"
        raise MutationGatewayError("stale_before_write", evidence)
    if authority_revalidator is not None:
        authority_revalidator()

    reconciled: dict[str, Any] | None = None
    try:
        evidence["transport_writes"] = 1
        gateway.append_comment(reviewed["number"], body)
    except BaseException as exc:
        if not _is_ambiguous_write_error(exc):
            evidence["terminal_status"] = "write_failed"
            raise MutationTransportError("write_failed", evidence) from exc
        reconciled = normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
        matches = _mutation_comments(reconciled, str(event["mutation_id"]))
        evidence["ambiguous_reconciliation_count"] = len(matches)
        if len(matches) != 1:
            evidence["terminal_status"] = "ambiguous_indeterminate"
            raise MutationTransportError("ambiguous_indeterminate", evidence) from exc

    after = reconciled or normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
    evidence["postwrite_snapshot"] = snapshot_evidence(after)
    if not _postwrite_matches(fresh, after, body):
        evidence["terminal_status"] = "conflict_after_write"
        return evidence
    proposal_comment = after["comments"][-1]
    receipt, receipt_body = build_event_receipt(event, proposal_comment, after)
    evidence["receipt_mutation_id"] = receipt["receipt_mutation_id"]
    if authority_revalidator is not None:
        authority_revalidator()
    receipt_fresh = normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
    if receipt_fresh != after:
        evidence["terminal_status"] = "stale_before_receipt"
        return evidence
    receipt_reconciled: dict[str, Any] | None = None
    try:
        evidence["transport_writes"] = 2
        gateway.append_comment(reviewed["number"], receipt_body)
    except BaseException as exc:
        if not _is_ambiguous_write_error(exc):
            evidence["terminal_status"] = "receipt_write_failed"
            raise MutationTransportError("receipt_write_failed", evidence) from exc
        receipt_reconciled = normalise_issue_snapshot(
            gateway.fetch_issue(reviewed["number"])
        )
        matches = _receipt_comments(
            receipt_reconciled, str(receipt["receipt_mutation_id"])
        )
        evidence["receipt_ambiguous_reconciliation_count"] = len(matches)
        if len(matches) != 1:
            evidence["terminal_status"] = "receipt_ambiguous_indeterminate"
            raise MutationTransportError(
                "receipt_ambiguous_indeterminate", evidence
            ) from exc
    final = receipt_reconciled or normalise_issue_snapshot(
        gateway.fetch_issue(reviewed["number"])
    )
    if not _postwrite_matches(after, final, receipt_body):
        evidence["terminal_status"] = "conflict_after_receipt"
        return evidence
    projected = project_status_events(final)
    if (
        not projected.get("accepted")
        or projected.get("status") != to_status
        or projected.get("head_event_id") != event["mutation_id"]
    ):
        evidence["terminal_status"] = "conflict_after_write"
        return evidence
    evidence["accepted"] = True
    evidence["terminal_status"] = "accepted"
    return evidence


def _run_gh(args: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["gh", *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode:
        raise subprocess.CalledProcessError(
            completed.returncode,
            ["gh", *args],
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed.stdout


def _read_gh(args: list[str], *, attempts: int = 3) -> str:
    for attempt in range(attempts):
        try:
            return _run_gh(args)
        except subprocess.CalledProcessError as exc:
            text = f"{exc.stdout or ''}\n{exc.stderr or ''}"
            if attempt + 1 == attempts or "503" not in text:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


@dataclass
class GhMutationTransport:
    repository: str = REPO

    def _pages(self, endpoint: str) -> list[dict[str, Any]]:
        pages = json.loads(
            _read_gh(
                [
                    "api",
                    endpoint,
                    "--paginate",
                    "--slurp",
                    "-H",
                    "X-GitHub-Api-Version: 2026-03-10",
                ]
            )
        )
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError("GitHub REST pagination payload is malformed")
        return [row for page in pages for row in page]

    def list_issues(self) -> list[dict[str, Any]]:
        return [
            issue
            for issue in self._pages(
                f"repos/{self.repository}/issues?state=all&per_page=100"
            )
            if "pull_request" not in issue
        ]

    def fetch_issue(self, number: int) -> dict[str, Any]:
        issue = json.loads(
            _read_gh(
                [
                    "api",
                    f"repos/{self.repository}/issues/{number}",
                    "-H",
                    "X-GitHub-Api-Version: 2026-03-10",
                ]
            )
        )
        comments = self._pages(
            f"repos/{self.repository}/issues/{number}/comments?per_page=100"
        )
        if not isinstance(issue, dict):
            raise ValueError("GitHub REST issue snapshot is malformed")
        issue["comments"] = comments
        return issue

    def append_comment(self, number: int, body: str) -> None:
        # This is deliberately the only repository-authored write subprocess.
        _run_gh(
            [
                "api",
                f"repos/{self.repository}/issues/{number}/comments",
                "--method",
                "POST",
                "--input",
                "-",
                "-H",
                "X-GitHub-Api-Version: 2026-03-10",
            ],
            input_text=json.dumps({"body": body}),
        )

    def create_open_issue(self, title: str, body: str) -> None:
        _run_gh(
            [
                "api",
                f"repos/{self.repository}/issues",
                "--method",
                "POST",
                "--input",
                "-",
                "-H",
                "X-GitHub-Api-Version: 2026-03-10",
            ],
            input_text=json.dumps({"title": title, "body": body}),
        )
