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
from pathlib import Path
from typing import Any, Callable, Protocol


REPO = "Thor2709/etf_ai_cockpit"
AUTHORITY_PATH = Path(".github/issue-transitions/github-mutation-authority.jsonl")
AUTHORITY_SCHEMA = "etf-ai-cockpit.github-mutation-authority/1.0"
EVENT_PREFIX = "<!-- etf-ai-cockpit:status-event:v1 -->\n"
EVENT_RECEIPT_PREFIX = "<!-- etf-ai-cockpit:status-event-acceptance:v1 -->\n"
REPLAY_EVENT_PREFIX = "<!-- etf-ai-cockpit:status-replay:v1 -->\n"
REPLAY_RECEIPT_PREFIX = "<!-- etf-ai-cockpit:status-replay-acceptance:v1 -->\n"
CREATE_MARKER_TEMPLATE = "<!-- etf-ai-cockpit:create-mutation-id={} -->"
CREATE_RECEIPT_PREFIX = "<!-- etf-ai-cockpit:create-acceptance:v1 -->\n"
EVENT_SCHEMA = "etf-ai-cockpit.status-event/1.0"
REPLAY_EVENT_SCHEMA = "etf-ai-cockpit.status-replay/1.0"
STABLE_ID_RE = re.compile(r"(?:ISSUE|UPDATEV2)-\d{4}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
STATUS_RE = re.compile(r"^- Programme status: `([^`]+)`$", re.MULTILINE)
INFORMATIONAL_MARKER_RE = re.compile(
    r"^<!-- etf-ai-cockpit:fundamental-release-link=[1-9][0-9]* -->(?:\n|$)"
)
SINGLE_HOP_STATUS_TARGETS = frozenset({"ready", "in_progress", "integrated"})
RECOVERY_AUTHORITY_ID = (
    "db7622b54f8afd1ccdf24a6b356f3691aecb2e46b68c90136e8389aa2b9c08d8"
)
RECOVERY_SOURCE_SHA = "94e6376e1a81cdd11bc6c64adc1ebd6499c26bac"
RECOVERY_HEAD_SHA = "f4f6707d19e4de0d26144971f6c254750e44aaa2"
RECOVERY_STABLE_ID = "ISSUE-0018"
RECOVERY_EVENT_NAME = "workflow_dispatch"
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
    "run_id",
    "run_number",
    "workflow_ref",
    "repository",
    "event_payload_sha256",
    "authority_id",
    "authority_sequence",
    "ledger_blob_oid",
    "ledger_blob_sha256",
    "candidate_blob_oid",
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
    "authority_id",
    "authority_sequence",
    "source_sha",
    "ledger_blob_oid",
    "ledger_blob_sha256",
    "candidate_blob_oid",
}
REPLAY_EVENT_KEYS = {
    "schema_version",
    "execution_allowed",
    "stable_id",
    "issue_number",
    "database_id",
    "node_id",
    "from_status",
    "to_status",
    "reviewed_product_commit",
    "hops",
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
    "run_id",
    "run_number",
    "workflow_ref",
    "repository",
    "event_payload_sha256",
    "authority_id",
    "authority_sequence",
    "ledger_blob_oid",
    "ledger_blob_sha256",
    "candidate_blob_oid",
}
REPLAY_RECEIPT_KEYS = {
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
    "authority_id",
    "authority_sequence",
    "source_sha",
    "ledger_blob_oid",
    "ledger_blob_sha256",
    "candidate_blob_oid",
    "stable_id",
    "issue_number",
    "database_id",
    "node_id",
    "reviewed_product_commit",
    "hops_sha256",
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
    "authority_id",
    "authority_sequence",
    "source_sha",
    "head_sha",
    "ledger_blob_oid",
    "ledger_blob_sha256",
    "plan_sha256",
    "run_id",
    "run_number",
    "workflow_ref",
    "repository",
    "event_payload_sha256",
    "event_name",
    "event_ref",
    "run_attempt",
    "event_before",
    "event_after",
    "actor",
    "pusher",
}
AUTHORITY_KEYS = {
    "schema_version",
    "authority_type",
    "repository",
    "execution_allowed",
    "sequence",
    "previous_authority_id",
    "payload",
    "authority_id",
}
BOOTSTRAP_ISSUE_KEYS = {
    "stable_id",
    "issue_number",
    "database_id",
    "node_id",
    "initial_status",
}
STATUS_AUTHORITY_KEYS = {
    "stable_id",
    "issue_number",
    "database_id",
    "node_id",
    "source_sha",
    "from_status",
    "to_status",
    "candidate_path",
    "candidate_blob_oid",
    "candidate_blob_sha256",
    "candidate_authority_ref",
    "plan_sha256",
}
STATUS_REPLAY_AUTHORITY_KEYS = {
    "stable_id",
    "issue_number",
    "database_id",
    "node_id",
    "source_sha",
    "from_status",
    "to_status",
    "reviewed_product_commit",
    "hops",
    "candidate_path",
    "candidate_blob_oid",
    "candidate_blob_sha256",
    "candidate_authority_ref",
    "plan_sha256",
}
CREATE_AUTHORITY_KEYS = {
    "stable_id",
    "source_sha",
    "title",
    "managed_body",
    "claim_inventory_sha256",
    "plan_sha256",
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


def _validate_run_attestation(attestation: dict[str, str]) -> None:
    """Validate the immutable identity of the sole supported introducing run."""

    if (
        not attestation["run_id"].isdigit()
        or int(attestation["run_id"]) <= 0
        or not attestation["run_number"].isdigit()
        or int(attestation["run_number"]) <= 0
        or attestation["repository"] != REPO
        or attestation["workflow_ref"]
        != f"{REPO}/.github/workflows/programme-status-completion.yml@refs/heads/main"
        or not HASH_RE.fullmatch(attestation["event_payload_sha256"])
    ):
        raise ValueError("invalid_github_actions_run_attestation")


def _is_exact_recovery_event(value: dict[str, Any]) -> bool:
    return (
        value.get("event_name") == RECOVERY_EVENT_NAME
        and value.get("stable_id") == RECOVERY_STABLE_ID
        and value.get("authority_id") == RECOVERY_AUTHORITY_ID
        and value.get("source_sha") == RECOVERY_SOURCE_SHA
        and value.get("head_sha") == RECOVERY_HEAD_SHA
        and value.get("event_before") == RECOVERY_SOURCE_SHA
        and value.get("event_after") == RECOVERY_HEAD_SHA
    )


def _validate_single_hop_status_transition(
    from_status: object, to_status: object
) -> None:
    try:
        from scripts.issue_registry_core import CONTROL_ALLOWED_TRANSITIONS
    except ModuleNotFoundError:
        from issue_registry_core import CONTROL_ALLOWED_TRANSITIONS  # type: ignore[no-redef]
    if (
        not isinstance(from_status, str)
        or not isinstance(to_status, str)
        or to_status not in SINGLE_HOP_STATUS_TARGETS
        or to_status not in CONTROL_ALLOWED_TRANSITIONS.get(from_status, frozenset())
    ):
        raise ValueError("invalid_status_authority_transition")


def _authority_id(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("authority_id", None)
    return _sha256(_json_bytes(unsigned))


def candidate_authority_ref(payload: dict[str, Any]) -> str:
    """Return the non-circular semantic reference embedded in a candidate."""

    core = {
        key: payload[key]
        for key in (
            "stable_id",
            "issue_number",
            "database_id",
            "node_id",
            "source_sha",
            "from_status",
            "to_status",
            "plan_sha256",
        )
    }
    return _sha256(_json_bytes(core))


def replay_candidate_authority_ref(payload: dict[str, Any]) -> str:
    """Return the non-circular semantic reference for the bounded replay contract."""

    core = {
        key: payload[key]
        for key in (
            "stable_id",
            "issue_number",
            "database_id",
            "node_id",
            "source_sha",
            "from_status",
            "to_status",
            "reviewed_product_commit",
            "hops",
            "plan_sha256",
        )
    }
    return _sha256(_json_bytes(core))


def build_authority_record(
    authority_type: str,
    payload: dict[str, Any],
    *,
    sequence: int,
    previous_authority_id: str | None,
) -> dict[str, Any]:
    record = {
        "schema_version": AUTHORITY_SCHEMA,
        "authority_type": authority_type,
        "repository": REPO,
        "execution_allowed": False,
        "sequence": sequence,
        "previous_authority_id": previous_authority_id,
        "payload": payload,
    }
    record["authority_id"] = _authority_id(record)
    return record


def authority_ledger_bytes(records: list[dict[str, Any]]) -> bytes:
    return b"".join(_json_bytes(record) for record in records)


def parse_authority_ledger(data: bytes) -> list[dict[str, Any]]:
    """Validate the complete canonical, hash-chained authority history."""

    if not data or not data.endswith(b"\n"):
        raise ValueError("authority_ledger_must_be_nonempty_canonical_jsonl")
    records: list[dict[str, Any]] = []
    previous: str | None = None
    bootstrap_ids: set[str] = set()
    bootstrap_numbers: set[int] = set()
    bootstrap_database_ids: set[str] = set()
    bootstrap_node_ids: set[str] = set()
    issue_identities: dict[str, tuple[int, str, str]] = {}
    for index, raw in enumerate(data.splitlines(keepends=True)):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_authority_ledger_json") from exc
        if (
            not isinstance(record, dict)
            or set(record) != AUTHORITY_KEYS
            or raw != _json_bytes(record)
            or record.get("schema_version") != AUTHORITY_SCHEMA
            or record.get("repository") != REPO
            or record.get("execution_allowed") is not False
            or record.get("sequence") != index
            or record.get("previous_authority_id") != previous
            or record.get("authority_id") != _authority_id(record)
        ):
            raise ValueError("invalid_authority_ledger_record")
        kind = record.get("authority_type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("invalid_authority_payload")
        if index == 0:
            if kind != "legacy_bootstrap" or set(payload) != {"legacy_issues"}:
                raise ValueError("authority_ledger_missing_legacy_bootstrap")
            issues = payload["legacy_issues"]
            if not isinstance(issues, list) or not issues:
                raise ValueError("authority_legacy_bootstrap_is_empty")
            for issue in issues:
                if not isinstance(issue, dict) or set(issue) != BOOTSTRAP_ISSUE_KEYS:
                    raise ValueError("invalid_authority_legacy_issue")
                stable_id = str(issue.get("stable_id", ""))
                number = issue.get("issue_number")
                database_id = str(issue.get("database_id", ""))
                node_id = str(issue.get("node_id", ""))
                if (
                    (bool(stable_id) != bool(issue.get("initial_status")))
                    or (bool(stable_id) and not STABLE_ID_RE.fullmatch(stable_id))
                    or not isinstance(number, int)
                    or number <= 0
                    or not database_id
                    or not node_id
                    or (bool(stable_id) and stable_id in bootstrap_ids)
                    or number in bootstrap_numbers
                    or database_id in bootstrap_database_ids
                    or node_id in bootstrap_node_ids
                ):
                    raise ValueError("invalid_authority_legacy_issue_identity")
                if stable_id:
                    bootstrap_ids.add(stable_id)
                    issue_identities[stable_id] = (
                        number,
                        str(issue["database_id"]),
                        str(issue["node_id"]),
                    )
                bootstrap_numbers.add(number)
                bootstrap_database_ids.add(database_id)
                bootstrap_node_ids.add(node_id)
        elif kind == "status":
            if set(payload) != STATUS_AUTHORITY_KEYS:
                raise ValueError("invalid_status_authority_fields")
            _validate_single_hop_status_transition(
                payload.get("from_status"), payload.get("to_status")
            )
            for field in ("source_sha",):
                if not SHA_RE.fullmatch(str(payload.get(field, ""))):
                    raise ValueError(f"invalid_status_authority_{field}")
            for field in (
                "candidate_blob_sha256",
                "candidate_authority_ref",
                "plan_sha256",
            ):
                if not HASH_RE.fullmatch(str(payload.get(field, ""))):
                    raise ValueError(f"invalid_status_authority_{field}")
            if (
                payload.get("candidate_path") != AUTHORITY_CANDIDATE_PATH
                or not re.fullmatch(r"[0-9a-f]{40,64}", str(payload.get("candidate_blob_oid", "")))
                or payload.get("candidate_authority_ref")
                != candidate_authority_ref(payload)
            ):
                raise ValueError("invalid_status_authority_candidate_binding")
            _validate_issue_identity_payload(payload, bootstrap_ids)
            identity = (
                int(payload["issue_number"]),
                str(payload["database_id"]),
                str(payload["node_id"]),
            )
            prior_identity = issue_identities.get(str(payload["stable_id"]))
            if prior_identity is not None and prior_identity != identity:
                raise ValueError("status_authority_issue_identity_changed")
            if prior_identity is None and identity in issue_identities.values():
                raise ValueError("status_authority_issue_identity_reused")
            issue_identities[str(payload["stable_id"])] = identity
        elif kind == "status_replay":
            if set(payload) != STATUS_REPLAY_AUTHORITY_KEYS:
                raise ValueError("invalid_status_replay_authority_fields")
            for field in ("source_sha", "reviewed_product_commit"):
                if not SHA_RE.fullmatch(str(payload.get(field, ""))):
                    raise ValueError(f"invalid_status_replay_authority_{field}")
            for field in (
                "candidate_blob_sha256",
                "candidate_authority_ref",
                "plan_sha256",
            ):
                if not HASH_RE.fullmatch(str(payload.get(field, ""))):
                    raise ValueError(f"invalid_status_replay_authority_{field}")
            if (
                payload.get("candidate_path") != AUTHORITY_CANDIDATE_PATH
                or not re.fullmatch(
                    r"[0-9a-f]{40,64}", str(payload.get("candidate_blob_oid", ""))
                )
                or payload.get("candidate_authority_ref")
                != replay_candidate_authority_ref(payload)
                or payload.get("from_status") != "in_progress"
                or payload.get("to_status") != "integrated"
                or not isinstance(payload.get("hops"), list)
                or len(payload["hops"]) != 2
            ):
                raise ValueError("invalid_status_replay_authority_candidate_binding")
            _validate_replay_hops(
                payload["hops"],
                reviewed_product_commit=str(payload["reviewed_product_commit"]),
            )
            _validate_issue_identity_payload(payload, bootstrap_ids)
            identity = (
                int(payload["issue_number"]),
                str(payload["database_id"]),
                str(payload["node_id"]),
            )
            prior_identity = issue_identities.get(str(payload["stable_id"]))
            if prior_identity is not None and prior_identity != identity:
                raise ValueError("status_authority_issue_identity_changed")
            if prior_identity is None and identity in issue_identities.values():
                raise ValueError("status_authority_issue_identity_reused")
            issue_identities[str(payload["stable_id"])] = identity
        elif kind == "create":
            if set(payload) != CREATE_AUTHORITY_KEYS:
                raise ValueError("invalid_create_authority_fields")
            if (
                not STABLE_ID_RE.fullmatch(str(payload.get("stable_id", "")))
                or not SHA_RE.fullmatch(str(payload.get("source_sha", "")))
                or not HASH_RE.fullmatch(str(payload.get("claim_inventory_sha256", "")))
                or not HASH_RE.fullmatch(str(payload.get("plan_sha256", "")))
                or not payload.get("title")
                or not payload.get("managed_body")
                or str(payload["stable_id"]) in bootstrap_ids
            ):
                raise ValueError("invalid_create_authority")
            bootstrap_ids.add(str(payload["stable_id"]))
        else:
            raise ValueError("invalid_authority_type")
        previous = str(record["authority_id"])
        records.append(record)
    return records


AUTHORITY_CANDIDATE_PATH = (
    ".github/issue-transitions/post-merge-control-candidate.json"
)


def _validate_issue_identity_payload(
    payload: dict[str, Any], stable_ids: set[str]
) -> None:
    stable_id = str(payload.get("stable_id", ""))
    number = payload.get("issue_number")
    if (
        stable_id not in stable_ids
        or not isinstance(number, int)
        or number <= 0
        or not payload.get("database_id")
        or not payload.get("node_id")
        or not payload.get("from_status")
        or not payload.get("to_status")
    ):
        raise ValueError("invalid_status_authority_issue_identity")


def load_authority_ledger(root: Path) -> list[dict[str, Any]]:
    return parse_authority_ledger((root / AUTHORITY_PATH).read_bytes())


def _git_blob_bytes(root: Path, revision: str, path: Path) -> bytes | None:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{path.as_posix()}"],
        cwd=root,
        capture_output=True,
    )
    if completed.returncode:
        return None
    return completed.stdout


def validate_authority_git_transition(
    root: Path,
    *,
    event_before: str,
    event_after: str,
    main_ref: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Require one immutable ledger append for this exact main push."""

    if not SHA_RE.fullmatch(event_before) or not SHA_RE.fullmatch(event_after):
        raise MutationPolicyError(
            "invalid_authority_push_identity",
            _policy_evidence("invalid_authority_push_identity"),
        )
    if (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", event_before, event_after],
            cwd=root,
            check=False,
        ).returncode
        != 0
    ):
        raise MutationPolicyError(
            "authority_source_not_ancestor",
            _policy_evidence("authority_source_not_ancestor"),
        )
    checked_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if checked_head != event_after:
        raise MutationPolicyError(
            "authority_checkout_head_mismatch",
            _policy_evidence("authority_checkout_head_mismatch"),
        )
    if main_ref is not None:
        current_main = subprocess.check_output(
            ["git", "rev-parse", main_ref], cwd=root, text=True
        ).strip()
        if current_main != event_after:
            raise MutationPolicyError(
                "authority_superseded_on_main",
                _policy_evidence("authority_superseded_on_main"),
            )
    before_bytes = _git_blob_bytes(root, event_before, AUTHORITY_PATH) or b""
    after_bytes = _git_blob_bytes(root, event_after, AUTHORITY_PATH)
    if after_bytes is None:
        raise MutationPolicyError(
            "authority_ledger_missing_at_head",
            _policy_evidence("authority_ledger_missing_at_head"),
        )
    before_records = parse_authority_ledger(before_bytes) if before_bytes else []
    after_records = parse_authority_ledger(after_bytes)
    if (
        not after_bytes.startswith(before_bytes)
        or authority_ledger_bytes(after_records[:-1]) != before_bytes
        or len(after_records) != len(before_records) + 1
    ):
        raise MutationPolicyError(
            "authority_ledger_not_exactly_one_append",
            _policy_evidence("authority_ledger_not_exactly_one_append"),
        )
    authority = after_records[-1]
    if authority["authority_type"] != "legacy_bootstrap" and authority["payload"].get(
        "source_sha"
    ) != event_before:
        raise MutationPolicyError(
            "authority_event_before_mismatch",
            _policy_evidence("authority_event_before_mismatch"),
        )
    ledger_oid = subprocess.check_output(
        ["git", "rev-parse", f"{event_after}:{AUTHORITY_PATH.as_posix()}"],
        cwd=root,
        text=True,
    ).strip()
    binding = {
        "authority_id": authority["authority_id"],
        "authority_sequence": authority["sequence"],
        "authority_type": authority["authority_type"],
        "source_sha": event_before,
        "head_sha": event_after,
        "ledger_blob_oid": ledger_oid,
        "ledger_blob_sha256": _sha256(after_bytes),
    }
    return before_records, after_records, binding


def validate_recovery_authority_git_transition(
    root: Path,
    *,
    source_sha: str,
    head_sha: str,
    main_ref: str,
    authority_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Validate the one fixed authority whose original push is unretryable."""

    if (
        source_sha != RECOVERY_SOURCE_SHA
        or head_sha != RECOVERY_HEAD_SHA
        or authority_id != RECOVERY_AUTHORITY_ID
    ):
        raise MutationPolicyError(
            "status_recovery_contract_mismatch",
            _policy_evidence("status_recovery_contract_mismatch"),
        )
    current_main = subprocess.check_output(
        ["git", "rev-parse", main_ref], cwd=root, text=True
    ).strip()
    checked_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if checked_head != current_main:
        raise MutationPolicyError(
            "recovery_checkout_head_mismatch",
            _policy_evidence("recovery_checkout_head_mismatch"),
        )
    for ancestor, descendant, error in (
        (source_sha, head_sha, "authority_source_not_ancestor"),
        (head_sha, current_main, "recovery_head_not_on_current_main"),
    ):
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            check=False,
        ).returncode:
            raise MutationPolicyError(error, _policy_evidence(error))

    before_bytes = _git_blob_bytes(root, source_sha, AUTHORITY_PATH) or b""
    original_bytes = _git_blob_bytes(root, head_sha, AUTHORITY_PATH)
    current_bytes = _git_blob_bytes(root, current_main, AUTHORITY_PATH)
    if original_bytes is None or current_bytes != original_bytes:
        raise MutationPolicyError(
            "recovery_authority_ledger_changed",
            _policy_evidence("recovery_authority_ledger_changed"),
        )
    before_records = parse_authority_ledger(before_bytes) if before_bytes else []
    after_records = parse_authority_ledger(original_bytes)
    if (
        authority_ledger_bytes(after_records[:-1]) != before_bytes
        or len(after_records) != len(before_records) + 1
        or after_records[-1]["authority_id"] != authority_id
    ):
        raise MutationPolicyError(
            "authority_ledger_not_exactly_one_append",
            _policy_evidence("authority_ledger_not_exactly_one_append"),
        )
    ledger_oid = subprocess.check_output(
        ["git", "rev-parse", f"{head_sha}:{AUTHORITY_PATH.as_posix()}"],
        cwd=root,
        text=True,
    ).strip()
    binding = {
        "authority_id": authority_id,
        "authority_sequence": after_records[-1]["sequence"],
        "authority_type": after_records[-1]["authority_type"],
        "source_sha": source_sha,
        "head_sha": head_sha,
        "ledger_blob_oid": ledger_oid,
        "ledger_blob_sha256": _sha256(original_bytes),
    }
    return before_records, after_records, binding


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
    comments = issue.get("comments")
    if not isinstance(comments, list):
        comments = []
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
        "comments": [normalise_comment(row) for row in comments],
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


def _is_informational_comment(body: str) -> bool:
    """Recognise the one non-authority managed comment shape we preserve."""

    marker = INFORMATIONAL_MARKER_RE.match(body)
    if marker is None:
        return False
    return "<!-- etf-ai-cockpit:" not in body[marker.end() :]


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
    _validate_single_hop_status_transition(
        value.get("from_status"), value.get("to_status")
    )
    for field in ("source_sha", "head_sha"):
        if not SHA_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_event_{field}")
    if (
        not (
            value.get("event_name") == "push"
            or _is_exact_recovery_event(value)
        )
        or value.get("event_ref") != "refs/heads/main"
        or value.get("run_attempt") != "1"
        or value.get("event_before") != value.get("source_sha")
        or value.get("event_after") != value.get("head_sha")
        or not value.get("actor")
        or not value.get("pusher")
    ):
        raise ValueError("invalid_status_event_workflow_binding")
    _validate_run_attestation(
        {
            key: str(value.get(key, ""))
            for key in (
                "run_id",
                "run_number",
                "workflow_ref",
                "repository",
                "event_payload_sha256",
            )
        }
    )
    for field in (
        "candidate_blob_sha256",
        "plan_sha256",
        "mutation_id",
        "predecessor_event_sha256",
        "authority_id",
        "ledger_blob_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_event_{field}")
    if (
        not isinstance(value.get("authority_sequence"), int)
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("ledger_blob_oid", "")))
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("candidate_blob_oid", "")))
    ):
        raise ValueError("invalid_status_event_authority_binding")
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
        "authority_id",
        "ledger_blob_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_event_receipt_{field}")
    if not SHA_RE.fullmatch(str(value.get("head_sha", ""))):
        raise ValueError("invalid_status_event_receipt_head_sha")
    if (
        not SHA_RE.fullmatch(str(value.get("source_sha", "")))
        or not isinstance(value.get("authority_sequence"), int)
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("ledger_blob_oid", "")))
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("candidate_blob_oid", "")))
    ):
        raise ValueError("invalid_status_event_receipt_authority_binding")
    if not value.get("proposal_comment_id") or not value.get("proposal_comment_node_id"):
        raise ValueError("invalid_status_event_receipt_comment_identity")
    return value


def _validate_replay_hops(
    hops: Any, *, reviewed_product_commit: str | None = None
) -> list[dict[str, Any]]:
    if not isinstance(hops, list) or len(hops) != 2 or any(
        not isinstance(hop, dict) for hop in hops
    ):
        raise ValueError("status_replay_requires_exactly_two_hops")
    result = [dict(hop) for hop in hops]
    if (
        result[0].get("from") != "in_progress"
        or result[0].get("to") != "implemented_initially"
        or result[1].get("from") != "implemented_initially"
        or result[1].get("to") != "integrated"
    ):
        raise ValueError("status_replay_hops_are_not_the_required_ordered_path")
    if any(
        hop.get("event_type") == "dependency_edge_update"
        or "dependency_edge" in hop
        for hop in result
    ):
        raise ValueError("status_replay_dependency_edge_is_not_allowed")
    try:
        from scripts.issue_registry_core import validate_control_transition_event
    except ModuleNotFoundError:
        from issue_registry_core import validate_control_transition_event  # type: ignore[no-redef]
    previous = {
        "programme_status": "in_progress",
        "verified_commit": "0" * 40,
        "dependency_edge_evidence": {},
    }
    for hop in result:
        validate_control_transition_event("status-replay", previous, hop)
        previous["programme_status"] = hop["to"]
        previous["verified_commit"] = hop["verified_commit"]
    if result[0]["verified_commit"] != result[1]["verified_commit"]:
        raise ValueError("status_replay_hops_do_not_share_reviewed_product_commit")
    if (
        reviewed_product_commit is not None
        and result[0]["verified_commit"] != reviewed_product_commit
    ):
        raise ValueError("status_replay_hops_do_not_match_reviewed_product_commit")
    if any(
        result[0].get(field) != result[1].get(field)
        for field in (
            "review_reference",
            "evidence_references",
            "reviewer",
            "reviewed_date",
        )
    ):
        raise ValueError("status_replay_hops_do_not_share_review_evidence")
    return result


def parse_replay_event_comment(body: str) -> dict[str, Any] | None:
    if not body.startswith(REPLAY_EVENT_PREFIX):
        return None
    try:
        value = json.loads(body[len(REPLAY_EVENT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_status_replay_json") from exc
    if not isinstance(value, dict) or set(value) != REPLAY_EVENT_KEYS:
        raise ValueError("invalid_status_replay_fields")
    if body != REPLAY_EVENT_PREFIX + _json_bytes(value).decode():
        raise ValueError("noncanonical_status_replay")
    if (
        value.get("schema_version") != REPLAY_EVENT_SCHEMA
        or value.get("execution_allowed") is not False
        or value.get("from_status") != "in_progress"
        or value.get("to_status") != "integrated"
    ):
        raise ValueError("invalid_status_replay_authority")
    if not STABLE_ID_RE.fullmatch(str(value.get("stable_id", ""))):
        raise ValueError("invalid_status_replay_stable_id")
    if not isinstance(value.get("issue_number"), int) or value["issue_number"] <= 0:
        raise ValueError("invalid_status_replay_issue_number")
    for field in ("source_sha", "head_sha", "reviewed_product_commit"):
        if not SHA_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_replay_{field}")
    for field in (
        "candidate_blob_sha256",
        "plan_sha256",
        "mutation_id",
        "predecessor_event_sha256",
        "authority_id",
        "ledger_blob_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_replay_{field}")
    if (
        not value.get("database_id")
        or not value.get("node_id")
        or not isinstance(value.get("authority_sequence"), int)
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("ledger_blob_oid", "")))
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("candidate_blob_oid", "")))
    ):
        raise ValueError("invalid_status_replay_authority_binding")
    _validate_replay_hops(
        value.get("hops"),
        reviewed_product_commit=str(value.get("reviewed_product_commit", "")),
    )
    if (
        value.get("event_name") != "push"
        or value.get("event_ref") != "refs/heads/main"
        or value.get("run_attempt") != "1"
        or value.get("event_before") != value.get("source_sha")
        or value.get("event_after") != value.get("head_sha")
        or not value.get("actor")
        or not value.get("pusher")
    ):
        raise ValueError("invalid_status_replay_workflow_binding")
    _validate_run_attestation(
        {
            key: str(value.get(key, ""))
            for key in (
                "run_id",
                "run_number",
                "workflow_ref",
                "repository",
                "event_payload_sha256",
            )
        }
    )
    return value


def parse_replay_receipt(body: str) -> dict[str, Any] | None:
    if not body.startswith(REPLAY_RECEIPT_PREFIX):
        return None
    try:
        value = json.loads(body[len(REPLAY_RECEIPT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_status_replay_receipt_json") from exc
    if not isinstance(value, dict) or set(value) != REPLAY_RECEIPT_KEYS:
        raise ValueError("invalid_status_replay_receipt_fields")
    if body != REPLAY_RECEIPT_PREFIX + _json_bytes(value).decode():
        raise ValueError("noncanonical_status_replay_receipt")
    if (
        value.get("schema_version") != "etf-ai-cockpit.status-replay-acceptance/1.0"
        or value.get("execution_allowed") is not False
    ):
        raise ValueError("invalid_status_replay_receipt_authority")
    for field in (
        "receipt_mutation_id",
        "proposal_mutation_id",
        "proposal_body_sha256",
        "candidate_blob_sha256",
        "predecessor_event_sha256",
        "verified_postwrite_snapshot_sha256",
        "authority_id",
        "ledger_blob_sha256",
        "hops_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_replay_receipt_{field}")
    for field in ("head_sha", "source_sha", "reviewed_product_commit"):
        if not SHA_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_status_replay_receipt_{field}")
    if (
        not isinstance(value.get("issue_number"), int)
        or value["issue_number"] <= 0
        or not value.get("stable_id")
        or not value.get("database_id")
        or not value.get("node_id")
        or not isinstance(value.get("authority_sequence"), int)
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("ledger_blob_oid", "")))
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("candidate_blob_oid", "")))
        or not value.get("proposal_comment_id")
        or not value.get("proposal_comment_node_id")
    ):
        raise ValueError("invalid_status_replay_receipt_binding")
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
        "authority_id": proposal["authority_id"],
        "authority_sequence": proposal["authority_sequence"],
        "source_sha": proposal["source_sha"],
        "ledger_blob_oid": proposal["ledger_blob_oid"],
        "ledger_blob_sha256": proposal["ledger_blob_sha256"],
        "candidate_blob_oid": proposal["candidate_blob_oid"],
        "execution_allowed": False,
    }
    receipt = {
        "schema_version": "etf-ai-cockpit.status-event-acceptance/1.0",
        **identity,
        "receipt_mutation_id": _sha256(_json_bytes(identity)),
    }
    return receipt, EVENT_RECEIPT_PREFIX + _json_bytes(receipt).decode()


def build_replay_event(
    *,
    stable_id: str,
    issue_number: int,
    database_id: str,
    node_id: str,
    from_status: str,
    to_status: str,
    reviewed_product_commit: str,
    hops: list[dict[str, Any]],
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
    run_id: str,
    run_number: str,
    workflow_ref: str,
    repository: str,
    event_payload_sha256: str,
    authority_id: str,
    authority_sequence: int,
    ledger_blob_oid: str,
    ledger_blob_sha256: str,
    candidate_blob_oid: str,
) -> tuple[dict[str, Any], str]:
    identity = {
        "stable_id": stable_id,
        "issue_number": issue_number,
        "database_id": database_id,
        "node_id": node_id,
        "from_status": from_status,
        "to_status": to_status,
        "reviewed_product_commit": reviewed_product_commit,
        "hops": hops,
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
        "run_id": run_id,
        "run_number": run_number,
        "workflow_ref": workflow_ref,
        "repository": repository,
        "event_payload_sha256": event_payload_sha256,
        "authority_id": authority_id,
        "authority_sequence": authority_sequence,
        "ledger_blob_oid": ledger_blob_oid,
        "ledger_blob_sha256": ledger_blob_sha256,
        "candidate_blob_oid": candidate_blob_oid,
    }
    event = {
        "schema_version": REPLAY_EVENT_SCHEMA,
        **identity,
        "mutation_id": _sha256(_json_bytes(identity)),
    }
    return event, REPLAY_EVENT_PREFIX + _json_bytes(event).decode()


def build_replay_receipt(
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
        "authority_id": proposal["authority_id"],
        "authority_sequence": proposal["authority_sequence"],
        "source_sha": proposal["source_sha"],
        "ledger_blob_oid": proposal["ledger_blob_oid"],
        "ledger_blob_sha256": proposal["ledger_blob_sha256"],
        "candidate_blob_oid": proposal["candidate_blob_oid"],
        "stable_id": proposal["stable_id"],
        "issue_number": proposal["issue_number"],
        "database_id": proposal["database_id"],
        "node_id": proposal["node_id"],
        "reviewed_product_commit": proposal["reviewed_product_commit"],
        "hops_sha256": _sha256(_json_bytes(proposal["hops"])),
        "execution_allowed": False,
    }
    receipt = {
        "schema_version": "etf-ai-cockpit.status-replay-acceptance/1.0",
        **identity,
        "receipt_mutation_id": _sha256(_json_bytes(identity)),
    }
    return receipt, REPLAY_RECEIPT_PREFIX + _json_bytes(receipt).decode()


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
    authority_events: list[dict[str, Any]] = []

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
            if parse_replay_receipt(comment["body"]) is not None:
                raise ValueError("orphan_status_replay_receipt")
            if parse_event_receipt(comment["body"]) is not None:
                raise ValueError("orphan_status_event_receipt")
            replay_event = parse_replay_event_comment(comment["body"])
            if replay_event is not None:
                require_bot(comment)
                if (
                    replay_event["stable_id"] != stable_id
                    or replay_event["issue_number"] != snapshot["number"]
                    or replay_event["database_id"] != snapshot["id"]
                    or replay_event["node_id"] != snapshot["node_id"]
                    or replay_event["predecessor_event_id"] != predecessor_id
                    or replay_event["predecessor_event_sha256"] != predecessor_hash
                    or replay_event["from_status"] != status
                ):
                    raise ValueError("invalid_status_replay_predecessor_or_issue")
                if index + 1 >= len(comments):
                    raise ValueError("orphan_status_replay_proposal")
                receipt_comment = comments[index + 1]
                receipt = parse_replay_receipt(receipt_comment["body"])
                if receipt is None:
                    raise ValueError("orphan_status_replay_proposal")
                require_bot(receipt_comment, receipt=True)
                if (
                    receipt["proposal_mutation_id"] != replay_event["mutation_id"]
                    or receipt["proposal_comment_id"] != comment["id"]
                    or receipt["proposal_comment_node_id"] != comment["node_id"]
                    or receipt["proposal_body_sha256"] != _sha256(comment["body"])
                    or receipt["candidate_blob_sha256"]
                    != replay_event["candidate_blob_sha256"]
                    or receipt["head_sha"] != replay_event["head_sha"]
                    or receipt["predecessor_event_id"] != predecessor_id
                    or receipt["predecessor_event_sha256"] != predecessor_hash
                    or receipt["authority_id"] != replay_event["authority_id"]
                    or receipt["authority_sequence"]
                    != replay_event["authority_sequence"]
                    or receipt["source_sha"] != replay_event["source_sha"]
                    or receipt["ledger_blob_oid"] != replay_event["ledger_blob_oid"]
                    or receipt["ledger_blob_sha256"]
                    != replay_event["ledger_blob_sha256"]
                    or receipt["candidate_blob_oid"]
                    != replay_event["candidate_blob_oid"]
                    or receipt["stable_id"] != stable_id
                    or receipt["issue_number"] != snapshot["number"]
                    or receipt["database_id"] != snapshot["id"]
                    or receipt["node_id"] != snapshot["node_id"]
                    or receipt["reviewed_product_commit"]
                    != replay_event["reviewed_product_commit"]
                    or receipt["hops_sha256"]
                    != _sha256(_json_bytes(replay_event["hops"]))
                    or receipt["verified_postwrite_snapshot_sha256"]
                    != _acceptance_snapshot_sha256(snapshot, comments[: index + 1])
                ):
                    raise ValueError("invalid_status_replay_acceptance_pair")
                hops = _validate_replay_hops(
                    replay_event["hops"],
                    reviewed_product_commit=str(
                        replay_event["reviewed_product_commit"]
                    ),
                )
                status = str(replay_event["to_status"])
                predecessor_id = str(replay_event["mutation_id"])
                predecessor_hash = _sha256(comment["body"])
                event_count += len(hops)
                authority_events.append(
                    {
                        "authority_id": replay_event["authority_id"],
                        "authority_sequence": replay_event["authority_sequence"],
                        "source_sha": replay_event["source_sha"],
                        "head_sha": replay_event["head_sha"],
                        "candidate_blob_oid": replay_event["candidate_blob_oid"],
                        "candidate_blob_sha256": replay_event["candidate_blob_sha256"],
                        "plan_sha256": replay_event["plan_sha256"],
                        "ledger_blob_oid": replay_event["ledger_blob_oid"],
                        "ledger_blob_sha256": replay_event["ledger_blob_sha256"],
                        "proposal_comment_id": comment["id"],
                        "receipt_comment_id": receipt_comment["id"],
                        "receipt_mutation_id": receipt["receipt_mutation_id"],
                        "proposal_body_sha256": _sha256(comment["body"]),
                        "receipt_body_sha256": _sha256(receipt_comment["body"]),
                        "authority_kind": "status_replay",
                        "reviewed_product_commit": replay_event[
                            "reviewed_product_commit"
                        ],
                        "hops": hops,
                    }
                )
                index += 2
                continue
            event = parse_event_comment(comment["body"])
            if event is None:
                if _is_informational_comment(comment["body"]):
                    index += 1
                    continue
                if comment["body"].startswith("<!-- etf-ai-cockpit:"):
                    if (
                        parse_create_receipt(comment["body"]) is None
                        and parse_replay_receipt(comment["body"]) is None
                    ):
                        raise ValueError("unknown_or_malformed_managed_comment")
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
                or receipt["authority_id"] != event["authority_id"]
                or receipt["authority_sequence"] != event["authority_sequence"]
                or receipt["source_sha"] != event["source_sha"]
                or receipt["ledger_blob_oid"] != event["ledger_blob_oid"]
                or receipt["ledger_blob_sha256"] != event["ledger_blob_sha256"]
                or receipt["candidate_blob_oid"] != event["candidate_blob_oid"]
                or receipt["verified_postwrite_snapshot_sha256"]
                != _acceptance_snapshot_sha256(snapshot, comments[: index + 1])
            ):
                raise ValueError("invalid_status_event_acceptance_pair")
            status = str(event["to_status"])
            predecessor_id = str(event["mutation_id"])
            predecessor_hash = _sha256(comment["body"])
            event_count += 1
            authority_events.append(
                {
                    "authority_id": event["authority_id"],
                    "authority_sequence": event["authority_sequence"],
                    "source_sha": event["source_sha"],
                    "head_sha": event["head_sha"],
                    "candidate_blob_oid": event["candidate_blob_oid"],
                    "candidate_blob_sha256": event["candidate_blob_sha256"],
                    "plan_sha256": event["plan_sha256"],
                    "ledger_blob_oid": event["ledger_blob_oid"],
                    "ledger_blob_sha256": event["ledger_blob_sha256"],
                    "proposal_comment_id": comment["id"],
                    "receipt_comment_id": receipt_comment["id"],
                    "receipt_mutation_id": receipt["receipt_mutation_id"],
                    "proposal_body_sha256": _sha256(comment["body"]),
                    "receipt_body_sha256": _sha256(receipt_comment["body"]),
                }
            )
            index += 2
    except ValueError as exc:
        return {"accepted": False, "error": str(exc)}
    return {
        "accepted": True,
        "status": status,
        "head_event_id": predecessor_id,
        "head_event_sha256": predecessor_hash,
        "event_count": event_count,
        "authority_events": authority_events,
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
    run_id: str,
    run_number: str,
    workflow_ref: str,
    repository: str,
    event_payload_sha256: str,
    authority_id: str = "0" * 64,
    authority_sequence: int = 0,
    ledger_blob_oid: str = "0" * 40,
    ledger_blob_sha256: str = "0" * 64,
    candidate_blob_oid: str = "0" * 40,
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
        "run_id": run_id,
        "run_number": run_number,
        "workflow_ref": workflow_ref,
        "repository": repository,
        "event_payload_sha256": event_payload_sha256,
        "authority_id": authority_id,
        "authority_sequence": authority_sequence,
        "ledger_blob_oid": ledger_blob_oid,
        "ledger_blob_sha256": ledger_blob_sha256,
        "candidate_blob_oid": candidate_blob_oid,
    }
    event = {
        "schema_version": EVENT_SCHEMA,
        **identity,
        "mutation_id": _sha256(_json_bytes(identity)),
    }
    return event, EVENT_PREFIX + _json_bytes(event).decode()


def describe_status_event(
    reviewed_snapshot: dict[str, Any],
    **bindings: Any,
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
    issue: dict[str, Any],
    *,
    mutation_id: str,
    stable_id: str,
    authority_id: str = "0" * 64,
    authority_sequence: int = 0,
    source_sha: str = "0" * 40,
    head_sha: str = "0" * 40,
    ledger_blob_oid: str = "0" * 40,
    ledger_blob_sha256: str = "0" * 64,
    plan_sha256: str = "0" * 64,
    run_id: str = "1",
    run_number: str = "1",
    workflow_ref: str = f"{REPO}/.github/workflows/programme-status-completion.yml@refs/heads/main",
    repository: str = REPO,
    event_payload_sha256: str = "0" * 64,
    event_name: str = "push",
    event_ref: str = "refs/heads/main",
    run_attempt: str = "1",
    event_before: str = "0" * 40,
    event_after: str = "0" * 40,
    actor: str = "test",
    pusher: str = "test",
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
        "authority_id": authority_id,
        "authority_sequence": authority_sequence,
        "source_sha": source_sha,
        "head_sha": head_sha,
        "ledger_blob_oid": ledger_blob_oid,
        "ledger_blob_sha256": ledger_blob_sha256,
        "plan_sha256": plan_sha256,
        "run_id": run_id,
        "run_number": run_number,
        "workflow_ref": workflow_ref,
        "repository": repository,
        "event_payload_sha256": event_payload_sha256,
        "event_name": event_name,
        "event_ref": event_ref,
        "run_attempt": run_attempt,
        "event_before": event_before,
        "event_after": event_after,
        "actor": actor,
        "pusher": pusher,
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
        "authority_id",
        "ledger_blob_sha256",
        "plan_sha256",
    ):
        if not HASH_RE.fullmatch(str(value.get(field, ""))):
            raise ValueError(f"invalid_create_receipt_{field}")
    if (
        not isinstance(value.get("authority_sequence"), int)
        or not SHA_RE.fullmatch(str(value.get("source_sha", "")))
        or not SHA_RE.fullmatch(str(value.get("head_sha", "")))
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(value.get("ledger_blob_oid", "")))
    ):
        raise ValueError("invalid_create_receipt_authority_binding")
    _validate_run_attestation(
        {
            key: str(value.get(key, ""))
            for key in (
                "run_id",
                "run_number",
                "workflow_ref",
                "repository",
                "event_payload_sha256",
            )
        }
    )
    if (
        value.get("event_name") != "push"
        or value.get("event_ref") != "refs/heads/main"
        or value.get("run_attempt") != "1"
        or value.get("event_before") != value.get("source_sha")
        or value.get("event_after") != value.get("head_sha")
        or not value.get("actor")
        or not value.get("pusher")
    ):
        raise ValueError("invalid_create_receipt_workflow_binding")
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
        elif comment["body"].startswith("<!-- etf-ai-cockpit:"):
            if _is_informational_comment(comment["body"]):
                continue
            try:
                status_event = parse_event_comment(comment["body"])
                status_receipt = parse_event_receipt(comment["body"])
                replay_event = parse_replay_event_comment(comment["body"])
                replay_receipt = parse_replay_receipt(comment["body"])
            except ValueError as exc:
                return {"accepted": False, "error": str(exc)}
            if all(
                managed is None
                for managed in (
                    status_event,
                    status_receipt,
                    replay_event,
                    replay_receipt,
                )
            ):
                return {
                    "accepted": False,
                    "error": "unknown_or_malformed_managed_comment",
                }
    if not markers:
        return (
            {"accepted": False, "error": "orphan_create_receipt"}
            if receipts
            else {"accepted": True, "legacy": True}
        )
    if len(markers) != 1 or len(receipts) != 1 or receipts[0][0] != 0:
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
    return {
        "accepted": True,
        "legacy": False,
        "mutation_id": markers[0],
        "authority_id": receipt["authority_id"],
        "authority_sequence": receipt["authority_sequence"],
        "source_sha": receipt["source_sha"],
        "head_sha": receipt["head_sha"],
        "ledger_blob_oid": receipt["ledger_blob_oid"],
        "ledger_blob_sha256": receipt["ledger_blob_sha256"],
        "plan_sha256": receipt["plan_sha256"],
        "receipt_mutation_id": receipt["receipt_mutation_id"],
        "receipt_comment_id": comment["id"],
        "receipt_body_sha256": _sha256(comment["body"]),
    }


def _bootstrap_rows(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not records or records[0].get("authority_type") != "legacy_bootstrap":
        raise ValueError("authority_ledger_missing_legacy_bootstrap")
    return list(records[0]["payload"]["legacy_issues"])


def _status_authorities(
    records: list[dict[str, Any]], stable_id: str
) -> list[dict[str, Any]]:
    return [
        record
        for record in records[1:]
        if record["authority_type"] in {"status", "status_replay"}
        and record["payload"]["stable_id"] == stable_id
    ]


def validate_projected_git_binding(
    root: Path, record: dict[str, Any], projected: dict[str, Any]
) -> None:
    """Prove a projected event's reported head and blobs remain recoverable."""

    payload = record["payload"]
    source = str(projected.get("source_sha", ""))
    head = str(projected.get("head_sha", ""))
    if source != payload.get("source_sha") or not SHA_RE.fullmatch(head):
        raise ValueError("projected_authority_git_identity_mismatch")
    before = _git_blob_bytes(root, source, AUTHORITY_PATH)
    after = _git_blob_bytes(root, head, AUTHORITY_PATH)
    if before is None or after is None:
        raise ValueError("projected_authority_ledger_blob_unrecoverable")
    before_records = parse_authority_ledger(before)
    after_records = parse_authority_ledger(after)
    sequence = int(record["sequence"])
    if (
        len(before_records) != sequence
        or len(after_records) != sequence + 1
        or after_records[-1]["authority_id"] != record["authority_id"]
        or authority_ledger_bytes(after_records[:-1]) != before
        or projected.get("ledger_blob_sha256") != _sha256(after)
    ):
        raise ValueError("projected_authority_ledger_transition_mismatch")
    ledger_oid = subprocess.check_output(
        ["git", "rev-parse", f"{head}:{AUTHORITY_PATH.as_posix()}"],
        cwd=root,
        text=True,
    ).strip()
    if projected.get("ledger_blob_oid") != ledger_oid:
        raise ValueError("projected_authority_ledger_oid_mismatch")
    if record["authority_type"] in {"status", "status_replay"}:
        candidate_path = str(payload["candidate_path"])
        candidate_bytes = _git_blob_bytes(root, head, Path(candidate_path))
        if candidate_bytes is None:
            raise ValueError("projected_candidate_blob_unrecoverable")
        candidate_oid = subprocess.check_output(
            ["git", "rev-parse", f"{head}:{candidate_path}"],
            cwd=root,
            text=True,
        ).strip()
        if (
            candidate_oid != payload["candidate_blob_oid"]
            or projected.get("candidate_blob_oid") != candidate_oid
            or _sha256(candidate_bytes) != payload["candidate_blob_sha256"]
            or projected.get("candidate_blob_sha256")
            != payload["candidate_blob_sha256"]
        ):
            raise ValueError("projected_candidate_blob_mismatch")


def reconcile_authority_ledger(
    records: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Reconcile every durable authority; any missing projection fails closed."""

    normalised = [normalise_issue_snapshot(issue) for issue in issues]
    by_number = {issue["number"]: issue for issue in normalised}
    if len(by_number) != len(normalised):
        return {"accepted": False, "error": "duplicate_remote_issue_number"}
    projections: list[dict[str, Any]] = []
    try:
        canonical: dict[str, dict[str, Any]] = {}
        initial_statuses: dict[str, str] = {}
        create_acceptances: dict[str, dict[str, Any]] = {}
        for row in _bootstrap_rows(records):
            issue = by_number.get(int(row["issue_number"]))
            if issue is None:
                raise ValueError("legacy_authority_issue_deleted")
            if (
                issue["id"] != row["database_id"]
                or issue["node_id"] != row["node_id"]
            ):
                # Node IDs are opaque and may migrate; mismatch still needs new Git authority.
                raise ValueError("legacy_authority_issue_identity_mismatch")
            stable_id = str(row["stable_id"])
            if not stable_id:
                continue
            stable = re.findall(
                r"<!--\s*etf-ai-cockpit:stable-id=((?:ISSUE|UPDATEV2)-\d{4})\s*-->",
                issue["body"],
            )
            if stable != [stable_id]:
                raise ValueError("legacy_authority_stable_id_mismatch")
            canonical[stable_id] = issue
            initial_statuses[stable_id] = str(row["initial_status"])

        for record in records[1:]:
            if record["authority_type"] != "create":
                continue
            marker = CREATE_MARKER_TEMPLATE.format(record["authority_id"])
            matches = [issue for issue in normalised if marker in issue["body"]]
            if len(matches) != 1:
                raise ValueError("missing_or_duplicate_create_authority_projection")
            acceptance = validate_create_acceptance(matches[0])
            if (
                not acceptance.get("accepted")
                or acceptance.get("authority_id") != record["authority_id"]
                or acceptance.get("authority_sequence") != record["sequence"]
                or acceptance.get("source_sha") != record["payload"]["source_sha"]
                or acceptance.get("plan_sha256")
                != record["payload"]["plan_sha256"]
            ):
                raise ValueError("create_authority_projection_binding_mismatch")
            if root is not None:
                validate_projected_git_binding(root, record, acceptance)
            stable_id = str(record["payload"]["stable_id"])
            statuses = STATUS_RE.findall(matches[0]["body"])
            if len(statuses) != 1:
                raise ValueError("created_issue_programme_status_ambiguous")
            canonical[stable_id] = matches[0]
            initial_statuses[stable_id] = statuses[0]
            create_acceptances[stable_id] = acceptance

        for stable_id, issue in sorted(canonical.items()):
            projection = project_status_events(issue)
            if not projection.get("accepted"):
                raise ValueError(str(projection.get("error")))
            expected = _status_authorities(records, stable_id)
            actual = list(projection.get("authority_events", []))
            if len(actual) != len(expected):
                raise ValueError("missing_or_extra_status_authority_projection")
            for record, event in zip(expected, actual, strict=True):
                payload = record["payload"]
                if (
                    event["authority_id"] != record["authority_id"]
                    or event["authority_sequence"] != record["sequence"]
                    or (
                        record["authority_type"] == "status_replay"
                        and event.get("authority_kind") != "status_replay"
                    )
                    or (
                        record["authority_type"] == "status"
                        and event.get("authority_kind") not in {None, "status"}
                    )
                    or event["source_sha"] != payload["source_sha"]
                    or event["candidate_blob_oid"] != payload["candidate_blob_oid"]
                    or event["candidate_blob_sha256"]
                    != payload["candidate_blob_sha256"]
                    or event["plan_sha256"] != payload["plan_sha256"]
                    or (
                        record["authority_type"] == "status_replay"
                        and (
                            event.get("reviewed_product_commit")
                            != payload["reviewed_product_commit"]
                            or event.get("hops") != payload["hops"]
                        )
                    )
                ):
                    raise ValueError("status_authority_projection_binding_mismatch")
                if root is not None:
                    validate_projected_git_binding(root, record, event)
            effective = initial_statuses[stable_id]
            for record in expected:
                payload = record["payload"]
                if payload["from_status"] != effective:
                    raise ValueError("status_authority_history_discontinuity")
                effective = payload["to_status"]
            if projection["status"] != effective:
                raise ValueError("status_authority_effective_status_mismatch")
            projections.append(
                {
                    "stable_id": stable_id,
                    "issue_number": issue["number"],
                    "effective_status": effective,
                    "authority_count": len(expected)
                    + int(stable_id in create_acceptances),
                    "head_authority_id": (
                        expected[-1]["authority_id"]
                        if expected
                        else (
                            create_acceptances[stable_id]["authority_id"]
                            if stable_id in create_acceptances
                            else records[0]["authority_id"]
                        )
                    ),
                    "authority_events": actual,
                    "create_acceptance": create_acceptances.get(stable_id),
                }
            )
    except (IndexError, StopIteration, ValueError) as exc:
        return {"accepted": False, "error": str(exc), "projections": projections}
    return {
        "accepted": True,
        "authority_count": len(records),
        "bootstrap_issue_count": len(_bootstrap_rows(records)),
        "head_authority_id": records[-1]["authority_id"],
        "projections": sorted(projections, key=lambda row: row["stable_id"]),
    }


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


def validate_reviewed_create_authority(
    plan: dict[str, Any],
    *,
    approved_sha256: str,
    create_body: str | None,
    authority_record: dict[str, Any] | None,
    git_binding: dict[str, Any] | None,
    event_name: str,
    event_ref: str,
    run_attempt: str,
    event_before: str,
    event_after: str,
    actor: str,
    pusher: str,
    run_id: str,
    run_number: str,
    workflow_ref: str,
    repository: str,
    event_payload_sha256: str,
) -> dict[str, Any]:
    """Validate the exact create request shared by premerge and apply."""

    actions = _validate_plan_authority(plan, approved_sha256)
    if authority_record is None or git_binding is None:
        raise MutationPolicyError(
            "missing_committed_mutation_authority",
            _policy_evidence("missing_committed_mutation_authority", approved_sha256),
        )
    if len(actions) != 1:
        raise MutationPolicyError(
            "single_create_action_required",
            _policy_evidence("single_create_action_required", approved_sha256),
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
    title = str(action.get("title", ""))
    payload = authority_record.get("payload")
    attestation = {
        "run_id": run_id,
        "run_number": run_number,
        "workflow_ref": workflow_ref,
        "repository": repository,
        "event_payload_sha256": event_payload_sha256,
        "event_name": event_name,
        "event_ref": event_ref,
        "run_attempt": run_attempt,
        "event_before": event_before,
        "event_after": event_after,
        "actor": actor,
        "pusher": pusher,
    }
    try:
        _validate_run_attestation(
            {
                key: attestation[key]
                for key in (
                    "run_id",
                    "run_number",
                    "workflow_ref",
                    "repository",
                    "event_payload_sha256",
                )
            }
        )
    except ValueError as exc:
        raise MutationPolicyError(
            "invalid_github_actions_run_attestation",
            _policy_evidence(
                "invalid_github_actions_run_attestation", approved_sha256
            ),
        ) from exc
    if (
        authority_record.get("authority_type") != "create"
        or not isinstance(payload, dict)
        or authority_record.get("authority_id") != git_binding.get("authority_id")
        or authority_record.get("sequence") != git_binding.get("authority_sequence")
        or git_binding.get("authority_type") != "create"
        or git_binding.get("source_sha") != event_before
        or git_binding.get("head_sha") != event_after
        or not re.fullmatch(
            r"[0-9a-f]{40,64}", str(git_binding.get("ledger_blob_oid", ""))
        )
        or not HASH_RE.fullmatch(str(git_binding.get("ledger_blob_sha256", "")))
        or payload.get("stable_id") != stable_id
        or payload.get("title") != title
        or payload.get("managed_body") != create_body
        or payload.get("claim_inventory_sha256") != expected_inventory
        or payload.get("plan_sha256") != approved_sha256
        or payload.get("source_sha") != event_before
        or event_name != "push"
        or event_ref != "refs/heads/main"
        or run_attempt != "1"
        or not actor
        or not pusher
    ):
        raise MutationPolicyError(
            "create_request_authority_mismatch",
            _policy_evidence("create_request_authority_mismatch", approved_sha256),
        )
    return {
        "action": action,
        "stable_id": stable_id,
        "title": title,
        "expected_inventory": expected_inventory,
        "attestation": attestation,
    }


def apply_reviewed_plan(
    plan: dict[str, Any],
    *,
    approved_sha256: str,
    create_body: str | None = None,
    authority_record: dict[str, Any] | None = None,
    git_binding: dict[str, Any] | None = None,
    event_name: str = "",
    event_ref: str = "",
    run_attempt: str = "",
    event_before: str = "",
    event_after: str = "",
    actor: str = "",
    pusher: str = "",
    run_id: str = "",
    run_number: str = "",
    workflow_ref: str = "",
    repository: str = "",
    event_payload_sha256: str = "",
    transport: MutationTransport | None = None,
    authority_revalidator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    actions = _validate_plan_authority(plan, approved_sha256)
    if authority_record is None or git_binding is None:
        raise MutationPolicyError(
            "missing_committed_mutation_authority",
            _policy_evidence("missing_committed_mutation_authority", approved_sha256),
        )
    if not actions:
        return {
            **_policy_evidence("no_action", approved_sha256),
            "accepted": True,
            "terminal_status": "no_action",
        }
    validated = validate_reviewed_create_authority(
        plan,
        approved_sha256=approved_sha256,
        create_body=create_body,
        authority_record=authority_record,
        git_binding=git_binding,
        event_name=event_name,
        event_ref=event_ref,
        run_attempt=run_attempt,
        event_before=event_before,
        event_after=event_after,
        actor=actor,
        pusher=pusher,
        run_id=run_id,
        run_number=run_number,
        workflow_ref=workflow_ref,
        repository=repository,
        event_payload_sha256=event_payload_sha256,
    )
    expected_inventory = str(validated["expected_inventory"])
    stable_id = str(validated["stable_id"])
    stable_marker = f"<!-- etf-ai-cockpit:stable-id={stable_id} -->"
    title = str(validated["title"])
    attestation = dict(validated["attestation"])
    mutation_id = str(authority_record["authority_id"])
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
    if any(marker in str(issue.get("body") or "") for issue in before):
        evidence["terminal_status"] = "spent_authority_projection_exists"
        raise MutationGatewayError("spent_authority_projection_exists", evidence)
    if authority_revalidator is not None:
        authority_revalidator()

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
        created,
        mutation_id=mutation_id,
        stable_id=stable_id,
        authority_id=mutation_id,
        authority_sequence=int(authority_record["sequence"]),
        source_sha=event_before,
        head_sha=event_after,
        ledger_blob_oid=str(git_binding["ledger_blob_oid"]),
        ledger_blob_sha256=str(git_binding["ledger_blob_sha256"]),
        plan_sha256=approved_sha256,
        **attestation,
    )
    evidence["receipt_mutation_id"] = receipt["receipt_mutation_id"]
    if authority_revalidator is not None:
        authority_revalidator()
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
            event = parse_event_comment(comment["body"]) or parse_replay_event_comment(
                comment["body"]
            )
        except ValueError:
            continue
        if event is not None and event["mutation_id"] == mutation_id:
            result.append(comment)
    return result


def _receipt_comments(snapshot: dict[str, Any], mutation_id: str) -> list[dict[str, Any]]:
    result = []
    for comment in normalise_issue_snapshot(snapshot)["comments"]:
        try:
            receipt = parse_event_receipt(comment["body"]) or parse_replay_receipt(
                comment["body"]
            )
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
    run_id: str,
    run_number: str,
    workflow_ref: str,
    repository: str,
    event_payload_sha256: str,
    authority_record: dict[str, Any] | None = None,
    git_binding: dict[str, Any] | None = None,
    transport: MutationTransport | None = None,
    authority_revalidator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if authority_record is None or git_binding is None:
        raise MutationPolicyError(
            "missing_committed_mutation_authority",
            _policy_evidence("missing_committed_mutation_authority", plan_sha256),
        )
    payload = authority_record.get("payload")
    if (
        authority_record.get("authority_type") != "status"
        or not isinstance(payload, dict)
        or authority_record.get("authority_id") != git_binding.get("authority_id")
        or authority_record.get("sequence") != git_binding.get("authority_sequence")
        or payload.get("stable_id") != stable_id
        or payload.get("from_status") != from_status
        or payload.get("to_status") != to_status
        or payload.get("source_sha") != source_sha
        or payload.get("candidate_blob_sha256") != candidate_blob_sha256
        or payload.get("plan_sha256") != plan_sha256
    ):
        raise MutationPolicyError(
            "status_request_authority_mismatch",
            _policy_evidence("status_request_authority_mismatch", plan_sha256),
        )
    eligibility = {
        "event_name": event_name,
        "event_ref": event_ref,
        "run_attempt": run_attempt,
        "event_before": event_before,
        "event_after": event_after,
        "actor": actor,
        "pusher": pusher,
        "run_id": run_id,
        "run_number": run_number,
        "workflow_ref": workflow_ref,
        "repository": repository,
        "event_payload_sha256": event_payload_sha256,
    }
    recovery_event = (
        event_name == RECOVERY_EVENT_NAME
        and stable_id == RECOVERY_STABLE_ID
        and authority_record.get("authority_id") == RECOVERY_AUTHORITY_ID
        and source_sha == RECOVERY_SOURCE_SHA
        and head_sha == RECOVERY_HEAD_SHA
    )
    if (
        not (event_name == "push" or recovery_event)
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
    try:
        _validate_run_attestation(
            {
                key: eligibility[key]
                for key in (
                    "run_id",
                    "run_number",
                    "workflow_ref",
                    "repository",
                    "event_payload_sha256",
                )
            }
        )
    except ValueError as exc:
        evidence = _policy_evidence(
            "invalid_github_actions_run_attestation", plan_sha256
        )
        evidence["event_binding_sha256"] = _sha256(_json_bytes(eligibility))
        raise MutationPolicyError(
            "invalid_github_actions_run_attestation", evidence
        ) from exc
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
        authority_id=str(authority_record["authority_id"]),
        authority_sequence=int(authority_record["sequence"]),
        ledger_blob_oid=str(git_binding["ledger_blob_oid"]),
        ledger_blob_sha256=str(git_binding["ledger_blob_sha256"]),
        candidate_blob_oid=str(payload["candidate_blob_oid"]),
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
        authority_id=str(authority_record["authority_id"]),
        authority_sequence=int(authority_record["sequence"]),
        ledger_blob_oid=str(git_binding["ledger_blob_oid"]),
        ledger_blob_sha256=str(git_binding["ledger_blob_sha256"]),
        candidate_blob_oid=str(payload["candidate_blob_oid"]),
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
    if any(
        (
            parsed is not None
            and parsed.get("authority_id") == authority_record["authority_id"]
        )
        for comment in fresh["comments"]
        for parsed in [parse_event_comment(comment["body"])]
    ):
        evidence["terminal_status"] = "spent_authority_projection_exists"
        raise MutationGatewayError("spent_authority_projection_exists", evidence)
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


def append_status_replay(
    reviewed_snapshot: dict[str, Any],
    *,
    stable_id: str,
    issue_number: int,
    database_id: str,
    node_id: str,
    from_status: str,
    to_status: str,
    reviewed_product_commit: str,
    hops: list[dict[str, Any]],
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
    run_id: str,
    run_number: str,
    workflow_ref: str,
    repository: str,
    event_payload_sha256: str,
    authority_record: dict[str, Any] | None = None,
    git_binding: dict[str, Any] | None = None,
    transport: MutationTransport | None = None,
    authority_revalidator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Apply exactly one semantically atomic, two-hop status replay."""

    if authority_record is None or git_binding is None:
        raise MutationPolicyError(
            "missing_committed_mutation_authority",
            _policy_evidence("missing_committed_mutation_authority", plan_sha256),
        )
    payload = authority_record.get("payload")
    if (
        authority_record.get("authority_type") != "status_replay"
        or not isinstance(payload, dict)
        or authority_record.get("authority_id") != git_binding.get("authority_id")
        or authority_record.get("sequence") != git_binding.get("authority_sequence")
        or payload.get("stable_id") != stable_id
        or payload.get("issue_number") != issue_number
        or payload.get("database_id") != database_id
        or payload.get("node_id") != node_id
        or payload.get("from_status") != from_status
        or payload.get("to_status") != to_status
        or payload.get("reviewed_product_commit") != reviewed_product_commit
        or payload.get("hops") != hops
        or payload.get("source_sha") != source_sha
        or payload.get("candidate_blob_sha256") != candidate_blob_sha256
        or payload.get("plan_sha256") != plan_sha256
    ):
        raise MutationPolicyError(
            "status_replay_request_authority_mismatch",
            _policy_evidence("status_replay_request_authority_mismatch", plan_sha256),
        )
    _validate_replay_hops(hops, reviewed_product_commit=reviewed_product_commit)
    reviewed = normalise_issue_snapshot(reviewed_snapshot)
    if (
        reviewed["number"] != issue_number
        or reviewed["id"] != database_id
        or reviewed["node_id"] != node_id
    ):
        raise MutationPolicyError(
            "status_replay_issue_identity_mismatch",
            _policy_evidence("status_replay_issue_identity_mismatch", plan_sha256),
        )
    eligibility = {
        "event_name": event_name,
        "event_ref": event_ref,
        "run_attempt": run_attempt,
        "event_before": event_before,
        "event_after": event_after,
        "actor": actor,
        "pusher": pusher,
        "run_id": run_id,
        "run_number": run_number,
        "workflow_ref": workflow_ref,
        "repository": repository,
        "event_payload_sha256": event_payload_sha256,
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
        evidence = _policy_evidence("ineligible_status_replay_append_event", plan_sha256)
        evidence["event_binding_sha256"] = _sha256(_json_bytes(eligibility))
        raise MutationPolicyError("ineligible_status_replay_append_event", evidence)
    try:
        _validate_run_attestation(
            {
                key: eligibility[key]
                for key in (
                    "run_id",
                    "run_number",
                    "workflow_ref",
                    "repository",
                    "event_payload_sha256",
                )
            }
        )
    except ValueError as exc:
        evidence = _policy_evidence(
            "invalid_github_actions_run_attestation", plan_sha256
        )
        evidence["event_binding_sha256"] = _sha256(_json_bytes(eligibility))
        raise MutationPolicyError(
            "invalid_github_actions_run_attestation", evidence
        ) from exc
    projection = project_status_events(reviewed)
    if not projection.get("accepted") or projection.get("status") != from_status:
        raise MutationPolicyError(
            "invalid_reviewed_status_replay_projection",
            _policy_evidence("invalid_reviewed_status_replay_projection", plan_sha256),
        )
    event, body = build_replay_event(
        stable_id=stable_id,
        issue_number=issue_number,
        database_id=database_id,
        node_id=node_id,
        from_status=from_status,
        to_status=to_status,
        reviewed_product_commit=reviewed_product_commit,
        hops=hops,
        source_sha=source_sha,
        head_sha=head_sha,
        candidate_blob_sha256=candidate_blob_sha256,
        plan_sha256=plan_sha256,
        predecessor_event_id=str(projection["head_event_id"]),
        predecessor_event_sha256=str(projection["head_event_sha256"]),
        authority_id=str(authority_record["authority_id"]),
        authority_sequence=int(authority_record["sequence"]),
        ledger_blob_oid=str(git_binding["ledger_blob_oid"]),
        ledger_blob_sha256=str(git_binding["ledger_blob_sha256"]),
        candidate_blob_oid=str(payload["candidate_blob_oid"]),
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
        "transport_contract": "one_aggregate_proposal_one_receipt",
        "replay_hops": hops,
        "reviewed_product_commit": reviewed_product_commit,
        "reviewed_snapshot": snapshot_evidence(reviewed),
    }
    gateway = transport or GhMutationTransport()
    fresh = normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
    evidence["prewrite_snapshot"] = snapshot_evidence(fresh)
    if fresh != reviewed:
        evidence["terminal_status"] = "stale_before_write"
        raise MutationGatewayError("stale_before_write", evidence)
    if any(
        parsed is not None
        and parsed.get("authority_id") == authority_record["authority_id"]
        for comment in fresh["comments"]
        for parsed in [
            parse_replay_event_comment(comment["body"]),
            parse_event_comment(comment["body"]),
        ]
    ):
        evidence["terminal_status"] = "spent_authority_projection_exists"
        raise MutationGatewayError("spent_authority_projection_exists", evidence)
    if authority_revalidator is not None:
        authority_revalidator()
    try:
        evidence["transport_writes"] = 1
        gateway.append_comment(reviewed["number"], body)
    except BaseException as exc:
        if _is_ambiguous_write_error(exc):
            evidence["terminal_status"] = "ambiguous_indeterminate"
            raise MutationTransportError("ambiguous_indeterminate", evidence) from exc
        evidence["terminal_status"] = "write_failed"
        raise MutationTransportError("write_failed", evidence) from exc
    after = normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
    evidence["postwrite_snapshot"] = snapshot_evidence(after)
    if not _postwrite_matches(fresh, after, body):
        evidence["terminal_status"] = "conflict_after_write"
        return evidence
    proposal_comment = after["comments"][-1]
    receipt, receipt_body = build_replay_receipt(event, proposal_comment, after)
    evidence["receipt_mutation_id"] = receipt["receipt_mutation_id"]
    if authority_revalidator is not None:
        authority_revalidator()
    receipt_fresh = normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
    if receipt_fresh != after:
        evidence["terminal_status"] = "stale_before_receipt"
        return evidence
    try:
        evidence["transport_writes"] = 2
        gateway.append_comment(reviewed["number"], receipt_body)
    except BaseException as exc:
        if _is_ambiguous_write_error(exc):
            evidence["terminal_status"] = "receipt_ambiguous_indeterminate"
            raise MutationTransportError(
                "receipt_ambiguous_indeterminate", evidence
            ) from exc
        evidence["terminal_status"] = "receipt_write_failed"
        raise MutationTransportError("receipt_write_failed", evidence) from exc
    final = normalise_issue_snapshot(gateway.fetch_issue(reviewed["number"]))
    if not _postwrite_matches(after, final, receipt_body):
        evidence["terminal_status"] = "conflict_after_receipt"
        return evidence
    projected = project_status_events(final)
    if (
        not projected.get("accepted")
        or projected.get("status") != to_status
        or projected.get("head_event_id") != event["mutation_id"]
        or projected.get("event_count", 0) < 2
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


_TRANSIENT_READ_HTTP_STATUS = re.compile(
    r"\bHTTP(?:/\d+(?:\.\d+)?)?\s+(?:500|502|503|504)\b",
    re.IGNORECASE,
)
_TRANSIENT_READ_TRANSPORT_MARKERS = (
    "connection reset",
    "operation timed out",
    "operation/timed out",
    "context deadline exceeded",
    "temporary failure in name resolution",
    "temporary dns failure",
    "tls handshake timeout",
)


def _is_transient_read_error(exc: BaseException) -> bool:
    if not isinstance(exc, subprocess.CalledProcessError):
        return False
    stderr = f"{exc.stderr or ''}".lower()
    return _TRANSIENT_READ_HTTP_STATUS.search(stderr) is not None or any(
        marker in stderr for marker in _TRANSIENT_READ_TRANSPORT_MARKERS
    )


def _read_gh(args: list[str], *, attempts: int = 3) -> str:
    for attempt in range(attempts):
        try:
            return _run_gh(args)
        except subprocess.CalledProcessError as exc:
            if attempt + 1 == attempts or not _is_transient_read_error(exc):
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
