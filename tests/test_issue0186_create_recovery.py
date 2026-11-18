"""Focused checks for the one-off ISSUE-0186 create recovery."""

from __future__ import annotations

import copy
import subprocess

import pytest

from scripts import github_mutation_gateway as gateway
from scripts import recover_issue_0186_create as recovery

ACTIVATION = "a" * 40
PLAN_SHA = "2" * 64
ACTION = {"kind": "create", "stable_id": "ISSUE-0186", "title": "Earnings surprise and filing reaction (from #1026)"}
DEFERRED = [{"kind": "create", "stable_id": f"ISSUE-{number}", "title": f"Deferred {number}"} for number in ("0187", "0188")]
MARKER = gateway.CREATE_MARKER_TEMPLATE.format(recovery.AUTHORITY_ID)
ACTIONS_BOT = {"login": "github-actions[bot]", "id": int(gateway.GITHUB_ACTIONS_BOT_USER_ID), "type": "Bot"}
LOOKALIKE_CREATOR = {"login": "someone", "id": 1, "type": "User"}
BINDING = {"ledger_blob_oid": "1" * 40, "ledger_blob_sha256": "1" * 64}
ATTESTATION = {
    "event_name": "push", "event_ref": "refs/heads/main", "run_attempt": "1",
    "event_before": recovery.ORIGINAL_HEAD, "event_after": ACTIVATION,
    "actor": "owner", "pusher": "owner", "run_id": "9", "run_number": "3",
    "workflow_ref": f"{gateway.REPO}/{recovery.status.WORKFLOW_PATH}@refs/heads/main",
    "repository": gateway.REPO, "event_payload_sha256": "a" * 64,
}


def _issue(number, body, *, issue_id="1", node_id="I_1", title="Other", comments=()):
    return {
        "id": issue_id, "node_id": node_id, "number": number, "title": title, "body": body,
        "state": "open", "labels": [], "comments": list(comments),
        "url": f"https://api.github.com/repos/{gateway.REPO}/issues/{number}",
    }


OTHER = _issue(7, "<!-- etf-ai-cockpit:stable-id=ISSUE-0001 -->")


def _authority():
    return {
        "authority_id": recovery.AUTHORITY_ID, "authority_type": "create", "sequence": 201,
        "payload": {
            "stable_id": "ISSUE-0186", "source_sha": recovery.RECOVERY["source_sha"],
            "title": ACTION["title"], "managed_body": recovery.sync.managed_block(ACTION),
            "plan_sha256": PLAN_SHA, "claim_inventory_sha256": gateway.claim_inventory_sha256([OTHER]),
        },
    }


def _bot_comment(body):
    return {
        "id": 999, "node_id": "IC_test", "body": body,
        "user": {"id": int(gateway.GITHUB_ACTIONS_BOT_USER_ID), "login": "github-actions[bot]", "type": "Bot"},
        "performed_via_github_app": {"slug": "github-actions", "id": gateway.GITHUB_ACTIONS_APP_ID},
        "created_at": "2026-11-18T14:00:00Z", "updated_at": "2026-11-18T14:00:00Z",
    }


class Transport:
    """GitHub stand-in that records every write in the shared `calls` list."""

    def __init__(self, issues, calls, *, create_error=None, lands=True, lag=0, creator=ACTIONS_BOT):
        self.issues, self.calls, self.create_error, self.lands, self.lag = issues, calls, create_error, lands, lag
        self.creator = creator

    def list_issues(self):
        hide = bool(self.lag) and "create" in self.calls  # the list lags: the created issue is not shown yet
        self.lag -= hide
        return [
            {**copy.deepcopy(issue), "comments": len(issue["comments"])}
            for issue in self.issues if not (hide and issue["number"] == 1071)
        ]

    def fetch_issue(self, number):
        return copy.deepcopy(next(issue for issue in self.issues if issue["number"] == number))

    def create_open_issue(self, title, body):
        self.calls.append("create")
        if self.lands:
            created = _issue(1071, body, issue_id="6500000001", node_id="I_kwNEW", title=title)
            self.issues.append({**created, "user": self.creator})
        if self.create_error:
            raise self.create_error
        return 1071

    def append_comment(self, number, body):
        self.calls.append("append")
        next(issue for issue in self.issues if issue["number"] == number)["comments"].append(_bot_comment(body))


def _setup(monkeypatch, issues, *, create_error=None, lands=True, lag=0, creator=ACTIONS_BOT):
    calls: list[str] = []
    authority = _authority()

    def verify_push(_root, parent, head, *, stable_id, validating_candidate=False):
        assert stable_id == recovery.TARGET and parent == recovery.ORIGINAL_HEAD and head == ACTIVATION

    def plan(_root, records, _remote):
        actions = [ACTION, *DEFERRED] if len(records) == 1 else list(DEFERRED)  # one record fewer: before the create
        return {"actions": actions, "summary": {**recovery.ZERO_SUMMARY, "create": len(actions)}, "plan_sha256": "3" * 64}

    def scope(_root, source_sha, plan, *, create_id):
        assert source_sha == authority["payload"]["source_sha"] and create_id == recovery.TARGET
        return {**plan, "actions": [ACTION], "deferred_intake_creates": DEFERRED, "plan_sha256": PLAN_SHA}

    monkeypatch.setattr(recovery.status, "github_actions_push_attestation", lambda _reader: ATTESTATION)
    monkeypatch.setattr(recovery.status, "_git", lambda *_args: ACTIVATION)
    monkeypatch.setattr(recovery, "_original_authority", lambda _root: (authority, BINDING, [{"authority_id": "p"}, authority]))
    monkeypatch.setattr(gateway, "validate_create_receipt_recovery_push", verify_push)
    monkeypatch.setattr(gateway, "reconcile_authority_ledger", lambda *_args, **_kwargs: {"accepted": True})
    monkeypatch.setattr(recovery, "_plan", plan)
    monkeypatch.setattr(recovery.sync, "scope_admitted_intake_plan", scope)
    transport = Transport(issues, calls, create_error=create_error, lands=lands, lag=lag, creator=creator)
    return calls, transport, {
        "run_reader": lambda _run_id: pytest.fail("no run lookup is needed"),
        "main_fetcher": lambda _root: None, "transport": transport,
        "proof_verifier": lambda _attestation: calls.append("proof"),
        "remote_reader": lambda: copy.deepcopy(transport.issues),
    }


def test_creates_the_issue_and_receipt_once_with_pending_creates_remaining(tmp_path, monkeypatch):
    calls, transport, inputs = _setup(monkeypatch, [copy.deepcopy(OTHER)])
    result = recovery.recover(tmp_path, **inputs)
    assert calls == ["proof", "create", "append"]
    assert result["terminal_status"] == "created_and_receipt_written" and result["transport_writes"] == 2
    assert result["zero_action_readback"] is False and result["only_reviewed_pending_creates_remain"] is True
    created = transport.fetch_issue(1071)
    assert created["body"] == MARKER + "\n" + recovery.sync.managed_block(ACTION)
    acceptance = gateway.validate_create_acceptance(created)
    assert acceptance["accepted"] and acceptance["authority_id"] == recovery.AUTHORITY_ID
    assert acceptance["head_sha"] == recovery.ORIGINAL_HEAD and acceptance["recovery_push"] == ACTIVATION
    again = recovery.recover(tmp_path, **inputs)  # a valid receipt already exists: read-only no-op
    assert again["terminal_status"] == "already_accepted" and again["transport_writes"] == 0
    assert calls == ["proof", "create", "append"]


def test_validate_mode_performs_no_write(tmp_path, monkeypatch):
    calls, _transport, inputs = _setup(monkeypatch, [copy.deepcopy(OTHER)])
    result = recovery.recover(
        tmp_path, expected_parent=recovery.ORIGINAL_HEAD, expected_head=ACTIVATION,
        main_fetcher=inputs["main_fetcher"], remote_reader=inputs["remote_reader"],
    )
    assert result == {"accepted": False, "terminal_status": "validated", "transport_writes": 0} and calls == []


@pytest.mark.parametrize(
    "extra,reason",
    [
        (_issue(8, MARKER + "\n" + recovery.sync.managed_block(ACTION), title=ACTION["title"]), "marker_without_receipt"),
        (_issue(8, recovery.sync.managed_block(ACTION), title=ACTION["title"]), "duplicate_or_foreign_claim"),
        (_issue(8, "<!-- etf-ai-cockpit:stable-id=ISSUE-0002 -->"), "other_claims_changed"),
    ],
)
def test_refuses_existing_claim_or_changed_inventory_with_zero_writes(tmp_path, monkeypatch, extra, reason):
    calls, _transport, inputs = _setup(monkeypatch, [copy.deepcopy(OTHER), extra])
    with pytest.raises(ValueError, match=reason):
        recovery.recover(tmp_path, **inputs)
    assert calls == []


def test_refuses_when_the_list_changed_before_the_create(tmp_path, monkeypatch):
    calls, transport, inputs = _setup(monkeypatch, [copy.deepcopy(OTHER)])
    transport.list_issues = lambda: []  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="stale_before_create"):
        recovery.recover(tmp_path, **inputs)
    assert calls == []


@pytest.mark.parametrize(
    "lands,lag,delays,creator,refusal",
    [
        (True, 0, [], ACTIONS_BOT, None),
        (True, 1, [2], ACTIONS_BOT, None),
        (False, 0, [2, 4, 8, 16], ACTIONS_BOT, "create_unresolved"),
        (True, 0, [], LOOKALIKE_CREATOR, "creator_not_actions_bot"),
    ],
)
def test_ambiguous_create_rereads_and_never_posts_twice(tmp_path, monkeypatch, lands, lag, delays, creator, refusal):
    slept: list[int] = []
    monkeypatch.setattr(gateway.time, "sleep", slept.append)
    calls, _transport, inputs = _setup(
        monkeypatch, [copy.deepcopy(OTHER)], create_error=TimeoutError("lost"), lands=lands, lag=lag, creator=creator,
    )
    if refusal is None:  # the marker shows on the first or second re-read: one create, one receipt
        assert recovery.recover(tmp_path, **inputs)["transport_writes"] == 2
        assert calls == ["proof", "create", "append"]
    else:  # it never shows, or a lookalike made by someone else shows: fail closed, no receipt
        with pytest.raises(gateway.MutationTransportError, match=refusal) as raised:
            recovery.recover(tmp_path, **inputs)
        assert raised.value.evidence["transport_writes"] == 1 and calls == ["proof", "create"]
    assert slept == delays


def test_original_authority_names_git_revisions_with_forward_slashes(tmp_path, monkeypatch):
    revisions = []
    intro = {"authority_id": recovery.AUTHORITY_ID, "authority_type": "create", "sequence": 1,
             "payload": {"stable_id": "ISSUE-0186", "source_sha": "s" * 40}}

    def git(_root, *args):
        revisions.extend(args)
        return "s" * 40

    monkeypatch.setattr(recovery.status, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(recovery.status, "_git", git)
    monkeypatch.setattr(gateway, "_git_blob_bytes", lambda _root, rev, _path: b"old" if rev.endswith("^") else b"old+new")
    monkeypatch.setattr(gateway, "parse_authority_ledger", lambda data: [{}] if data == b"old" else [{}, intro])
    monkeypatch.setattr(gateway, "validate_projected_git_binding", lambda *_args: None)
    authority, binding, _records = recovery._original_authority(tmp_path)
    assert authority is intro and binding["head_sha"] == recovery.ORIGINAL_HEAD
    assert any(gateway.AUTHORITY_PATH.as_posix() in arg for arg in revisions)  # a git rev such as <sha>:<path>
    assert not any("\\" in arg for arg in revisions)


def test_recovery_rejects_missing_github_actions_identity(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(gateway.MutationPolicyError):
        recovery.recover(tmp_path)


def test_issue_identity_is_bound_by_the_receipt_only_for_the_entry_that_declares_it():
    issue = _issue(1071, MARKER, issue_id="6500000001", node_id="I_kwNEW")

    def receipt(stable_id, authority_id, source_sha, head_sha, snapshot):
        value, _body = gateway.build_create_receipt(
            snapshot, mutation_id=authority_id, stable_id=stable_id, authority_id=authority_id,
            source_sha=source_sha, head_sha=head_sha, event_before=head_sha, event_after=ACTIVATION,
        )
        return value

    spec = recovery.RECOVERY
    assert spec["issue_id"] is None and spec["node_id"] is None
    assert gateway._is_create_receipt_recovery(receipt("ISSUE-0186", spec["authority_id"], spec["source_sha"], spec["head_sha"], issue))
    assert not gateway._is_create_receipt_recovery(
        receipt("ISSUE-0186", spec["authority_id"], spec["source_sha"], spec["head_sha"], {**issue, "id": ""})
    )
    spent = gateway.CREATE_RECEIPT_RECOVERIES["ISSUE-0183"]
    spent_args = ("ISSUE-0183", spent["authority_id"], spent["source_sha"], spent["head_sha"])
    assert not gateway._is_create_receipt_recovery(receipt(*spent_args, issue))  # a pinned entry still pins its issue
    assert gateway._is_create_receipt_recovery(
        receipt(*spent_args, {**issue, "id": spent["issue_id"], "node_id": spent["node_id"]})
    )


def test_reviewed_candidate_can_have_multiple_commits_but_apply_requires_merge_parent(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    ledger = tmp_path / gateway.AUTHORITY_PATH
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b"original ledger\n")
    git("add", ".")
    git("commit", "-qm", "spent create")
    base = git("rev-parse", "HEAD")
    monkeypatch.setitem(recovery.RECOVERY, "head_sha", base)
    git("commit", "--allow-empty", "-qm", "early change")
    path = tmp_path / recovery.RECOVERY["path"]
    path.parent.mkdir()
    path.write_text("# recovery\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "reviewed recovery")
    candidate = git("rev-parse", "HEAD")
    gateway.validate_create_receipt_recovery_push(tmp_path, base, candidate, stable_id=recovery.TARGET, validating_candidate=True)
    with pytest.raises(ValueError, match="issue_0186_recovery_push_not_authorised"):
        gateway.validate_create_receipt_recovery_push(tmp_path, base, candidate, stable_id=recovery.TARGET)
    git("switch", "--detach", base)
    git("merge", "--no-ff", "-qm", "reviewed merge", candidate)
    gateway.validate_create_receipt_recovery_push(tmp_path, base, git("rev-parse", "HEAD"), stable_id=recovery.TARGET)


def test_parser_rejects_other_issues_using_recovery_push():
    _, body = gateway.build_create_receipt(
        _issue(1071, MARKER, issue_id="6500000001", node_id="I_kwNEW"),
        mutation_id="9" * 64, stable_id="ISSUE-0184", authority_id="9" * 64, authority_sequence=199,
        source_sha=recovery.RECOVERY["source_sha"], head_sha=recovery.ORIGINAL_HEAD,
        event_before=recovery.ORIGINAL_HEAD, event_after=ACTIVATION,
    )
    with pytest.raises(ValueError, match="invalid_create_receipt_workflow_binding"):
        gateway.parse_create_receipt(body)
