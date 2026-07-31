from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts import github_mutation_gateway as gateway
from scripts import generate_github_convergence_report as convergence
from scripts import generate_github_issue_map as issue_map
from scripts import sync_github_issues as sync


SOURCE = "a" * 40
HEAD = "b" * 40
BLOB = "c" * 64
PLAN = "d" * 64
RUN_ATTESTATION = {
    "run_id": "12345",
    "run_number": "7",
    "workflow_ref": (
        f"{gateway.REPO}/.github/workflows/"
        "programme-status-completion.yml@refs/heads/main"
    ),
    "repository": gateway.REPO,
    "event_payload_sha256": "e" * 64,
}


def issue(status: str = "implemented_initially") -> dict[str, Any]:
    record = {
        "canonical_id": "ISSUE-0179",
        "title": "Atomic programme generation",
        "programme_status": status,
    }
    return {
        "id": "4179",
        "node_id": "ISSUE_NODE_179",
        "number": 179,
        "title": record["title"],
        "body": sync.managed_block(record),
        "state": "OPEN",
        "url": "https://example.invalid/issues/179",
        "labels": [{"name": "programme"}],
        "comments": [
            {
                "id": "human-1",
                "body": "Keep this human note",
                "author": {"login": "reviewer"},
                "createdAt": "2026-07-31T00:00:00Z",
                "updatedAt": "2026-07-31T00:00:00Z",
                "url": "https://example.invalid/comments/1",
            }
        ],
        "updatedAt": "2026-07-31T00:00:00Z",
    }


class MemoryTransport:
    def __init__(
        self,
        value: dict[str, Any],
        *,
        before_append: Callable[[dict[str, Any]], None] | None = None,
        ambiguous: str | None = None,
    ) -> None:
        self.value = copy.deepcopy(value)
        self.before_append = before_append
        self.ambiguous = ambiguous
        self.writes = 0
        self.fetches = 0

    def fetch_issue(self, number: int) -> dict[str, Any]:
        assert number == 179
        self.fetches += 1
        return copy.deepcopy(self.value)

    def append_comment(self, number: int, body: str) -> None:
        assert number == 179
        self.writes += 1
        if self.before_append:
            self.before_append(self.value)
        if self.ambiguous != "zero":
            count = 2 if self.ambiguous == "multiple" else 1
            for index in range(count):
                self.value["comments"].append(
                    {
                        "id": f"bot-{self.writes}-{index}",
                        "node_id": f"NODE-{self.writes}-{index}",
                        "body": body,
                        "author": {"login": "github-actions[bot]"},
                        "performed_via_github_app": {
                            "slug": "github-actions",
                            "id": int(gateway.GITHUB_ACTIONS_APP_ID),
                        },
                        "createdAt": "2026-07-31T00:00:01Z",
                        "updatedAt": "2026-07-31T00:00:01Z",
                        "url": f"https://example.invalid/comments/bot-{index}",
                    }
                )
                self.value["comments"][-1]["author"]["type"] = "Bot"
                self.value["comments"][-1]["author"]["id"] = int(
                    gateway.GITHUB_ACTIONS_BOT_USER_ID
                )
            self.value["updatedAt"] = "2026-07-31T00:00:01Z"
        if self.ambiguous:
            raise TimeoutError("ambiguous transport result")


def _status_authority(
    previous_authority_id: str = "f" * 64,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "stable_id": "ISSUE-0179",
        "issue_number": 179,
        "database_id": "4179",
        "node_id": "ISSUE_NODE_179",
        "source_sha": SOURCE,
        "from_status": "implemented_initially",
        "to_status": "integrated",
        "candidate_path": gateway.AUTHORITY_CANDIDATE_PATH,
        "candidate_blob_oid": "e" * 40,
        "candidate_blob_sha256": BLOB,
        "candidate_authority_ref": "",
        "plan_sha256": PLAN,
    }
    payload["candidate_authority_ref"] = gateway.candidate_authority_ref(payload)
    authority = gateway.build_authority_record(
        "status", payload, sequence=1, previous_authority_id=previous_authority_id
    )
    binding = {
        "authority_id": authority["authority_id"],
        "authority_sequence": 1,
        "head_sha": HEAD,
        "ledger_blob_oid": "1" * 40,
        "ledger_blob_sha256": "2" * 64,
    }
    return authority, binding


def append(
    reviewed: dict[str, Any],
    transport: MemoryTransport,
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    authority, binding = (
        (authority, {
            "authority_id": authority["authority_id"],
            "authority_sequence": authority["sequence"],
            "head_sha": HEAD,
            "ledger_blob_oid": "1" * 40,
            "ledger_blob_sha256": "2" * 64,
        })
        if authority is not None
        else _status_authority()
    )
    return gateway.append_status_event(
        reviewed,
        stable_id="ISSUE-0179",
        from_status="implemented_initially",
        to_status="integrated",
        source_sha=SOURCE,
        head_sha=HEAD,
        candidate_blob_sha256=BLOB,
        plan_sha256=PLAN,
        event_name="push",
        event_ref="refs/heads/main",
        run_attempt="1",
        event_before=SOURCE,
        event_after=HEAD,
        actor="merger",
        pusher="merger",
        **RUN_ATTESTATION,
        authority_record=authority,
        git_binding=binding,
        transport=transport,
    )


def test_append_preserves_snapshot_and_projects_status() -> None:
    reviewed = issue()
    transport = MemoryTransport(reviewed)

    evidence = append(reviewed, transport)

    assert evidence["accepted"] is True
    assert transport.writes == 2
    assert transport.value["body"] == reviewed["body"]
    assert transport.value["title"] == reviewed["title"]
    assert transport.value["labels"] == reviewed["labels"]
    assert transport.value["comments"][0] == reviewed["comments"][0]
    projection = gateway.project_status_events(transport.value)
    assert projection["accepted"] is True
    assert projection["status"] == "integrated"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(body=value["body"] + "\nhuman edit"),
        lambda value: value.update(title="human title"),
        lambda value: value.update(updatedAt="2026-07-31T00:00:02Z"),
    ],
)
def test_stale_or_aba_snapshot_aborts_before_transport(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    reviewed = issue()
    transport = MemoryTransport(reviewed)
    mutation(transport.value)

    with pytest.raises(gateway.MutationGatewayError) as captured:
        append(reviewed, transport)

    assert captured.value.code == "stale_before_write"
    assert captured.value.evidence["transport_writes"] == 0
    assert transport.writes == 0


def test_human_edit_in_final_network_gap_is_preserved_and_conflicted() -> None:
    reviewed = issue()
    transport = MemoryTransport(
        reviewed,
        before_append=lambda value: value.update(body=value["body"] + "\nhuman edit"),
    )

    evidence = append(reviewed, transport)

    assert evidence["accepted"] is False
    assert evidence["terminal_status"] == "conflict_after_write"
    assert transport.value["body"].endswith("human edit")
    assert transport.writes == 1


def test_two_sessions_accept_at_most_one_event() -> None:
    reviewed = issue()
    shared = MemoryTransport(reviewed)

    first = append(reviewed, shared)
    with pytest.raises(gateway.MutationGatewayError) as second:
        append(reviewed, shared)

    assert first["accepted"] is True
    assert second.value.code == "stale_before_write"
    assert shared.writes == 2


def test_threaded_competing_sessions_accept_at_most_one_pair() -> None:
    reviewed = issue()

    class BarrierTransport(MemoryTransport):
        def __init__(self, value: dict[str, Any]) -> None:
            super().__init__(value)
            self.barrier = threading.Barrier(2)
            self.lock = threading.Lock()

        def fetch_issue(self, number: int) -> dict[str, Any]:
            with self.lock:
                return copy.deepcopy(self.value)

        def append_comment(self, number: int, body: str) -> None:
            self.barrier.wait(timeout=5)
            with self.lock:
                self.writes += 1
                self.value["comments"].append(
                    {
                        "id": f"race-{self.writes}",
                        "node_id": f"RACE-NODE-{self.writes}",
                        "body": body,
                        "author": {
                            "login": "github-actions[bot]",
                            "type": "Bot",
                            "id": int(gateway.GITHUB_ACTIONS_BOT_USER_ID),
                        },
                        "performed_via_github_app": {
                            "slug": "github-actions",
                            "id": int(gateway.GITHUB_ACTIONS_APP_ID),
                        },
                        "createdAt": "2026-07-31T00:00:01Z",
                        "updatedAt": "2026-07-31T00:00:01Z",
                    }
                )
            self.barrier.wait(timeout=5)

    transport = BarrierTransport(reviewed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: append(reviewed, transport), range(2)))

    assert sum(result["accepted"] is True for result in results) <= 1
    assert all(result["terminal_status"] == "conflict_after_write" for result in results)
    assert transport.writes == 2


@pytest.mark.parametrize("outcome", ["zero", "multiple"])
def test_ambiguous_write_is_not_retried_and_indeterminate(outcome: str) -> None:
    reviewed = issue()
    transport = MemoryTransport(reviewed, ambiguous=outcome)

    with pytest.raises(gateway.MutationTransportError) as captured:
        append(reviewed, transport)

    assert captured.value.code == "ambiguous_indeterminate"
    assert transport.writes == 1
    assert transport.fetches == 2


def test_ambiguous_single_mutation_id_is_reconciled_without_retry() -> None:
    reviewed = issue()
    transport = MemoryTransport(reviewed, ambiguous="single")

    evidence = append(reviewed, transport)

    assert evidence["accepted"] is True
    assert evidence["ambiguous_reconciliation_count"] == 1
    assert transport.writes == 2
    assert transport.fetches == 4


def test_cancelled_or_rerun_authority_cannot_append_again() -> None:
    reviewed = issue()
    transport = MemoryTransport(reviewed, ambiguous="single")
    assert append(reviewed, transport)["accepted"] is True

    authority, binding = _status_authority()
    with pytest.raises(gateway.MutationPolicyError) as captured:
        gateway.append_status_event(
            reviewed,
            stable_id="ISSUE-0179",
            from_status="implemented_initially",
            to_status="integrated",
            source_sha=SOURCE,
            head_sha=HEAD,
            candidate_blob_sha256=BLOB,
            plan_sha256=PLAN,
            event_name="push",
            event_ref="refs/heads/main",
            run_attempt="2",
            event_before=SOURCE,
            event_after=HEAD,
            actor="merger",
            pusher="merger",
            **RUN_ATTESTATION,
            authority_record=authority,
            git_binding=binding,
            transport=transport,
        )

    assert captured.value.code == "ineligible_status_append_event"
    assert transport.writes == 2


@pytest.mark.parametrize("kind", ["update", "close", "reopen", "labels", "state"])
def test_unsafe_general_actions_are_policy_rejected(kind: str) -> None:
    plan = {"actions": [{"kind": kind}]}
    plan["plan_sha256"] = sync.plan_sha256(plan)

    with pytest.raises(gateway.MutationPolicyError) as captured:
        sync.apply_actions(plan, approved_sha256=plan["plan_sha256"])

    assert captured.value.evidence["transport_writes"] == 0
    assert captured.value.evidence["terminal_status"] == "policy_rejected"


class CreateTransport:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.issues: list[dict[str, Any]] = []
        self.writes = 0
        self.ambiguous = ambiguous

    def list_issues(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.issues)

    def create_open_issue(self, title: str, body: str) -> None:
        self.writes += 1
        self.issues.append(
            {
                "id": 1001,
                "node_id": "ISSUE_NODE_1",
                "number": 1,
                "title": title,
                "body": body,
                "state": "open",
                "url": "https://example.invalid/issues/1",
                "comments": [],
            }
        )
        if self.ambiguous:
            raise TimeoutError("response lost")

    def fetch_issue(self, number: int) -> dict[str, Any]:
        assert number == 1
        return copy.deepcopy(self.issues[0])

    def append_comment(self, number: int, body: str) -> None:
        assert number == 1
        self.writes += 1
        self.issues[0]["comments"].append(
            {
                "id": 2001,
                "node_id": "COMMENT_NODE_1",
                "body": body,
                "author": {
                    "login": "github-actions[bot]",
                    "type": "Bot",
                    "id": int(gateway.GITHUB_ACTIONS_BOT_USER_ID),
                },
                "performed_via_github_app": {
                    "slug": "github-actions",
                    "id": int(gateway.GITHUB_ACTIONS_APP_ID),
                },
                "created_at": "2026-07-31T00:00:01Z",
                "updated_at": "2026-07-31T00:00:01Z",
            }
        )


def _create_plan() -> dict[str, Any]:
    action = {
        "kind": "create",
        "stable_id": "ISSUE-0179",
        "title": "Atomic programme generation",
        "desired_state": "open",
    }
    plan: dict[str, Any] = {
        "actions": [action],
        "claim_inventory_sha256": gateway.claim_inventory_sha256([]),
    }
    plan["plan_sha256"] = sync.plan_sha256(plan)
    return plan


def _create_authority(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    action = plan["actions"][0]
    payload = {
        "stable_id": action["stable_id"],
        "source_sha": SOURCE,
        "title": action["title"],
        "managed_body": sync.managed_block(action),
        "claim_inventory_sha256": plan["claim_inventory_sha256"],
        "plan_sha256": plan["plan_sha256"],
    }
    authority = gateway.build_authority_record(
        "create", payload, sequence=1, previous_authority_id="f" * 64
    )
    binding = {
        "authority_id": authority["authority_id"],
        "authority_sequence": 1,
        "head_sha": HEAD,
        "ledger_blob_oid": "1" * 40,
        "ledger_blob_sha256": "2" * 64,
    }
    return authority, binding


def _apply_create(
    plan: dict[str, Any],
    transport: CreateTransport,
    *,
    authority_revalidator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    authority, binding = _create_authority(plan)
    return sync.apply_actions(
        plan,
        approved_sha256=plan["plan_sha256"],
        mutation_transport=transport,
        authority_record=authority,
        git_binding=binding,
        event_name="push",
        event_ref="refs/heads/main",
        run_attempt="1",
        event_before=SOURCE,
        event_after=HEAD,
        actor="merger",
        pusher="merger",
        **RUN_ATTESTATION,
        authority_revalidator=authority_revalidator,
    )


@pytest.mark.parametrize("ambiguous", [False, True])
def test_single_open_create_is_verified_without_retry(ambiguous: bool) -> None:
    plan = _create_plan()
    transport = CreateTransport(ambiguous=ambiguous)

    evidence = _apply_create(plan, transport)

    assert evidence["accepted"] is True
    assert transport.writes == 2
    assert "create-mutation-id=" in transport.issues[0]["body"]
    assert "stable-id=ISSUE-0179" in transport.issues[0]["body"]


def test_multi_action_and_closed_create_fail_before_transport() -> None:
    for mutate in (
        lambda plan: plan["actions"].append(copy.deepcopy(plan["actions"][0])),
        lambda plan: plan["actions"][0].update(desired_state="closed"),
    ):
        plan = _create_plan()
        mutate(plan)
        plan["plan_sha256"] = sync.plan_sha256(plan)
        transport = CreateTransport()
        with pytest.raises(gateway.MutationPolicyError):
            _apply_create(plan, transport)
        assert transport.writes == 0


@pytest.mark.parametrize("outcome", ["zero", "multiple"])
def test_create_ambiguity_never_retries_or_emits_receipt(outcome: str) -> None:
    plan = _create_plan()
    transport = CreateTransport()

    def ambiguous_create(title: str, body: str) -> None:
        transport.writes += 1
        if outcome == "multiple":
            for number in (1, 2):
                transport.issues.append(
                    {
                        "id": 1000 + number,
                        "node_id": f"ISSUE_NODE_{number}",
                        "number": number,
                        "title": title,
                        "body": body,
                        "state": "open",
                        "url": f"https://example.invalid/issues/{number}",
                        "comments": [],
                    }
                )
        raise TimeoutError("ambiguous create")

    transport.create_open_issue = ambiguous_create  # type: ignore[method-assign]
    with pytest.raises(gateway.MutationTransportError):
        _apply_create(plan, transport)

    assert transport.writes == 1
    assert all(not item["comments"] for item in transport.issues)


@pytest.mark.parametrize("superseded_at", [1, 2])
def test_create_revalidates_git_authority_immediately_before_each_post(
    superseded_at: int,
) -> None:
    plan = _create_plan()
    transport = CreateTransport()
    calls = 0

    def revalidate() -> None:
        nonlocal calls
        calls += 1
        if calls == superseded_at:
            raise gateway.MutationPolicyError(
                "authority_superseded_on_main",
                gateway._policy_evidence("authority_superseded_on_main"),
            )

    with pytest.raises(gateway.MutationPolicyError, match="authority_superseded"):
        _apply_create(
            plan,
            transport,
            authority_revalidator=revalidate,
        )

    assert transport.writes == superseded_at - 1


def test_orphan_create_marker_and_orphan_receipt_block_planning() -> None:
    plan = _create_plan()
    transport = CreateTransport()

    def interrupted_create(title: str, body: str) -> None:
        transport.writes += 1
        transport.issues.append(
            {
                "id": 1001,
                "node_id": "ISSUE_NODE_1",
                "number": 1,
                "title": title + " (human changed)",
                "body": body,
                "state": "open",
                "url": "https://example.invalid/issues/1",
                "comments": [],
            }
        )
        raise TimeoutError("cancelled after create")

    transport.create_open_issue = interrupted_create  # type: ignore[method-assign]
    rejected = _apply_create(plan, transport)
    assert rejected["accepted"] is False
    registry = {
        "records": [
            {
                "canonical_id": "ISSUE-0179",
                "title": "Atomic programme generation",
                "ledger_state": "open",
                "programme_status": "planned",
            }
        ]
    }
    orphan_plan = sync.plan_actions(registry, transport.issues)
    assert orphan_plan["summary"]["blocked"] == 1
    assert orphan_plan["actions"][0]["reason"] == "orphan_or_duplicate_create_acceptance"

    legacy = issue("planned")
    receipt, receipt_body = gateway.build_create_receipt(
        legacy, mutation_id="a" * 64, stable_id="ISSUE-0179"
    )
    legacy["comments"].append(
        {
            "id": receipt["receipt_mutation_id"],
            "node_id": "RECEIPT_NODE",
            "body": receipt_body,
        }
    )
    assert gateway.validate_create_acceptance(legacy)["accepted"] is False


def test_direct_write_helper_has_no_bypass() -> None:
    with pytest.raises(gateway.MutationPolicyError):
        sync.gh_command(["issue", "edit", "179", "--body", "unsafe"])


def test_repository_authored_github_post_subprocess_is_gateway_only() -> None:
    root = Path(__file__).resolve().parents[1]
    owners = []
    for path in (root / "scripts").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if '"--method"' in text and '"POST"' in text and '"gh"' in text:
            owners.append(path.name)
    assert owners == ["github_mutation_gateway.py"]


def _event_comment(
    predecessor_id: str,
    predecessor_hash: str,
    *,
    to_status: str = "integrated",
    author: str = "github-actions[bot]",
    edited: bool = False,
) -> dict[str, Any]:
    event, body = gateway.build_status_event(
        stable_id="ISSUE-0179",
        from_status="implemented_initially",
        to_status=to_status,
        source_sha=SOURCE,
        head_sha=HEAD,
        candidate_blob_sha256=BLOB,
        plan_sha256=PLAN,
        predecessor_event_id=predecessor_id,
        predecessor_event_sha256=predecessor_hash,
        event_name="push",
        event_ref="refs/heads/main",
        run_attempt="1",
        event_before=SOURCE,
        event_after=HEAD,
        actor="merger",
        pusher="merger",
        **RUN_ATTESTATION,
    )
    return {
        "id": event["mutation_id"],
        "body": body,
        "author": {
            "login": author,
            "type": "Bot" if author == "github-actions[bot]" else "User",
            "id": int(gateway.GITHUB_ACTIONS_BOT_USER_ID),
        },
        "performed_via_github_app": {
            "slug": "github-actions",
            "id": int(gateway.GITHUB_ACTIONS_APP_ID),
        },
        "createdAt": "2026-07-31T00:00:01Z",
        "updatedAt": "2026-07-31T00:00:02Z" if edited else "2026-07-31T00:00:01Z",
    }


@pytest.mark.parametrize("variant", ["edited", "human", "duplicate", "fork", "orphan"])
def test_invalid_status_events_do_not_advance_projection(variant: str) -> None:
    value = issue()
    root = gateway.project_status_events(value)
    comment = _event_comment(root["head_event_id"], root["head_event_sha256"])
    if variant == "edited":
        comment["updatedAt"] = "2026-07-31T00:00:02Z"
    elif variant == "human":
        comment["author"] = {"login": "reviewer"}
    elif variant == "orphan":
        comment = _event_comment("missing", "e" * 64)
    value["comments"].append(comment)
    if variant in {"duplicate", "fork"}:
        other = copy.deepcopy(comment)
        if variant == "fork":
            payload = json.loads(other["body"][len(gateway.EVENT_PREFIX) :])
            payload["to_status"] = "closed"
            payload["mutation_id"] = "f" * 64
            other["body"] = gateway.EVENT_PREFIX + json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ) + "\n"
        value["comments"].append(other)

    projection = gateway.project_status_events(value)

    assert projection["accepted"] is False
    assert "status" not in projection


def test_document_only_compensation_never_restores_invalid_chain() -> None:
    value = issue()
    root = gateway.project_status_events(value)
    edited = _event_comment(root["head_event_id"], root["head_event_sha256"], edited=True)
    compensation = {
        "schema_version": "etf-ai-cockpit.status-compensation/1.0",
        "execution_allowed": False,
        "anomalous_event_sha256": "f" * 64,
    }
    value["comments"].extend(
        [
            edited,
            {
                "body": "<!-- etf-ai-cockpit:status-compensation:v1 -->\n"
                + json.dumps(compensation, sort_keys=True, separators=(",", ":"))
                + "\n",
                "author": {"login": "reviewer", "type": "User", "id": 1},
                "createdAt": "2026-07-31T00:00:03Z",
                "updatedAt": "2026-07-31T00:00:03Z",
            },
        ]
    )

    assert gateway.project_status_events(value)["accepted"] is False


@pytest.mark.parametrize("field", ["user_id", "app_id", "app_slug"])
def test_status_event_requires_pinned_bot_and_app_attribution(field: str) -> None:
    value = issue()
    root = gateway.project_status_events(value)
    comment = _event_comment(root["head_event_id"], root["head_event_sha256"])
    if field == "user_id":
        comment["author"]["id"] = 1
    elif field == "app_id":
        comment["performed_via_github_app"]["id"] = 1
    else:
        comment["performed_via_github_app"]["slug"] = "foreign-app"
    value["comments"].append(comment)

    assert gateway.project_status_events(value)["accepted"] is False


def test_rest_comment_snapshot_flattens_more_than_one_hundred_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comments = [
        {
            "id": index,
            "body": f"comment {index}",
            "user": {"login": "reviewer", "type": "User", "id": 1},
            "created_at": "2026-07-31T00:00:00Z",
            "updated_at": "2026-07-31T00:00:00Z",
        }
        for index in range(101)
    ]
    responses = iter(
        [
            json.dumps(issue()),
            json.dumps([comments[:100], comments[100:]]),
        ]
    )
    observed: list[list[str]] = []

    def fake_read(args: list[str], **_kwargs: object) -> str:
        observed.append(args)
        return next(responses)

    monkeypatch.setattr(gateway, "_read_gh", fake_read)

    snapshot = gateway.GhMutationTransport().fetch_issue(179)

    assert len(snapshot["comments"]) == 101
    assert "--paginate" in observed[1]
    assert "--slurp" in observed[1]
    assert "per_page=100" in observed[1][1]


def test_evidence_contains_hashes_and_lengths_not_remote_content() -> None:
    reviewed = issue()
    evidence = append(reviewed, MemoryTransport(reviewed))
    serialised = json.dumps(evidence)

    assert "Keep this human note" not in serialised
    assert reviewed["body"] not in serialised
    assert "body_sha256" in evidence["reviewed_snapshot"]
    assert "body_length" in evidence["reviewed_snapshot"]


def test_issue_map_identity_is_unaffected_by_status_comments() -> None:
    first = issue()
    second = copy.deepcopy(first)
    second["comments"].append({"body": "a status comment"})

    assert issue_map.build_map([first]) == issue_map.build_map([second])


def test_safe_inventory_exposes_only_redacted_projection() -> None:
    value = issue()
    inventory = sync.safe_remote_inventory([value])
    serialised = json.dumps(inventory)

    assert "Keep this human note" not in serialised
    assert "comments" not in inventory["issues"][0]
    assert inventory["issues"][0]["effective_programme_status"] == (
        "implemented_initially"
    )
    assert inventory["issues"][0]["status_event_validation"] == "accepted"


def test_convergence_report_requires_actions_empty_and_valid_chain(tmp_path: Path) -> None:
    zero = {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
    approved = tmp_path / "approved.json"
    final = tmp_path / "final.json"
    mapping = tmp_path / "map.json"
    output = tmp_path / "report.json"
    approved.write_text(json.dumps({"summary": zero}), encoding="utf-8")
    mapping.write_text(json.dumps({}), encoding="utf-8")
    payload = {
        "summary": zero,
        "actions": [],
        "status_event_projections": [{"accepted": True}],
        "authority_reconciliation": {"accepted": True},
    }
    final.write_text(json.dumps(payload), encoding="utf-8")

    assert convergence.main(
        [
            "--approved-plan",
            str(approved),
            "--final-plan",
            str(final),
            "--map",
            str(mapping),
            "--output",
            str(output),
        ]
    ) == 0

    payload["actions"] = [{"kind": "update"}]
    final.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="zero summary, actions=\\[\\]"):
        convergence.main(
            [
                "--approved-plan",
                str(approved),
                "--final-plan",
                str(final),
                "--map",
                str(mapping),
                "--output",
                str(output),
            ]
        )


def test_convergence_report_redacts_plan_bodies_and_unmanaged_content(
    tmp_path: Path,
) -> None:
    secret = "private unmanaged reviewer note"
    plan = {
        "actions": [
            {
                "kind": "update",
                "stable_id": "ISSUE-0179",
                "title": "Sensitive title",
                "body": f"managed\n{secret}",
            }
        ]
    }

    summary = convergence.plan_summary(plan)
    serialised = json.dumps(summary)

    assert secret not in serialised
    assert "Sensitive title" not in serialised
    assert summary["actions"][0]["body_length"] == len(
        f"managed\n{secret}".encode()
    )
    assert "body_sha256" in summary["actions"][0]


def _bootstrap_record() -> dict[str, Any]:
    return gateway.build_authority_record(
        "legacy_bootstrap",
        {
            "legacy_issues": [
                {
                    "stable_id": "ISSUE-0179",
                    "issue_number": 179,
                    "database_id": "4179",
                    "node_id": "ISSUE_NODE_179",
                    "initial_status": "implemented_initially",
                }
            ]
        },
        sequence=0,
        previous_authority_id=None,
    )


def test_authority_ledger_is_canonical_hash_chained_and_tamper_evident() -> None:
    bootstrap = _bootstrap_record()
    status, _binding = _status_authority(str(bootstrap["authority_id"]))
    data = gateway.authority_ledger_bytes([bootstrap, status])

    assert gateway.parse_authority_ledger(data) == [bootstrap, status]
    with pytest.raises(ValueError, match="invalid_authority_ledger_record"):
        gateway.parse_authority_ledger(data.replace(b"integrated", b"integrateD"))
    with pytest.raises(ValueError, match="canonical_jsonl"):
        gateway.parse_authority_ledger(data.rstrip(b"\n"))


def test_authority_ledger_is_pinned_lf_and_crlf_input_fails_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    attributes = (root / ".gitattributes").read_text(encoding="utf-8")
    assert (
        ".github/issue-transitions/github-mutation-authority.jsonl text eol=lf"
        in attributes
    )
    data = gateway.authority_ledger_bytes([_bootstrap_record()])
    with pytest.raises(ValueError, match="invalid_authority_ledger_record"):
        gateway.parse_authority_ledger(data.replace(b"\n", b"\r\n"))


def test_all_authorities_reconcile_and_complete_pair_deletion_blocks() -> None:
    bootstrap = _bootstrap_record()
    authority, _binding = _status_authority(str(bootstrap["authority_id"]))
    reviewed = issue()
    transport = MemoryTransport(reviewed)
    assert append(reviewed, transport, authority)["accepted"] is True
    assert gateway.reconcile_authority_ledger(
        [bootstrap, authority], [transport.value]
    )["accepted"] is True

    transport.value["comments"] = transport.value["comments"][:-2]
    blocked = gateway.reconcile_authority_ledger(
        [bootstrap, authority], [transport.value]
    )
    assert blocked["error"] == "missing_or_extra_status_authority_projection"


def test_trailing_human_comment_is_allowed_but_interposed_comment_blocks() -> None:
    bootstrap = _bootstrap_record()
    authority, _binding = _status_authority(str(bootstrap["authority_id"]))
    transport = MemoryTransport(issue())
    assert append(issue(), transport, authority)["accepted"] is True
    human = {
        "id": "human-tail",
        "node_id": "HUMAN_TAIL",
        "body": "ordinary review note",
        "author": {"login": "reviewer", "type": "User", "id": 7},
        "createdAt": "2026-07-31T00:00:02Z",
        "updatedAt": "2026-07-31T00:00:02Z",
    }
    transport.value["comments"].append(human)
    assert gateway.reconcile_authority_ledger(
        [bootstrap, authority], [transport.value]
    )["accepted"] is True
    receipt = transport.value["comments"].pop(-2)
    transport.value["comments"].append(receipt)
    assert gateway.reconcile_authority_ledger(
        [bootstrap, authority], [transport.value]
    )["accepted"] is False


def test_deleted_baseline_or_whole_created_issue_blocks() -> None:
    bootstrap = _bootstrap_record()
    assert gateway.reconcile_authority_ledger([bootstrap], [])["error"] == (
        "legacy_authority_issue_deleted"
    )
    create = gateway.build_authority_record(
        "create",
        {
            "stable_id": "ISSUE-0180",
            "source_sha": SOURCE,
            "title": "Parallel validation pilot",
            "managed_body": "managed",
            "claim_inventory_sha256": "1" * 64,
            "plan_sha256": "2" * 64,
        },
        sequence=1,
        previous_authority_id=str(bootstrap["authority_id"]),
    )
    blocked = gateway.reconcile_authority_ledger([bootstrap, create], [issue()])
    assert blocked["error"] == "missing_or_duplicate_create_authority_projection"
