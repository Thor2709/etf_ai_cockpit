"""Focused checks for the one-off ISSUE-0182 receipt recovery."""

from __future__ import annotations

import copy
import subprocess

import pytest

from scripts import github_mutation_gateway as gateway
from scripts import recover_issue_0182_receipt as recovery


def _authority():
    return {
        "authority_id": recovery.AUTHORITY_ID,
        "sequence": 194,
        "payload": {
            "source_sha": "8b1ff6738ed0c8284799bab2d8b1c1ac92079180",
            "title": "Point-in-time cross-sectional panel (from #1022)",
            "managed_body": "<!-- etf-ai-cockpit:managed:start -->\n"
            "<!-- etf-ai-cockpit:stable-id=ISSUE-0182 -->\n"
            "<!-- etf-ai-cockpit:managed:end -->",
            "plan_sha256": "2" * 64,
        },
    }


def _issue(authority):
    return {
        "id": gateway.CREATE_RECEIPT_RECOVERY_ISSUE_ID,
        "node_id": gateway.CREATE_RECEIPT_RECOVERY_NODE_ID,
        "number": recovery.ISSUE_NUMBER,
        "title": authority["payload"]["title"],
        "body": gateway.CREATE_MARKER_TEMPLATE.format(recovery.AUTHORITY_ID)
        + "\n"
        + authority["payload"]["managed_body"],
        "state": "open",
        "labels": [],
        "url": (
            f"https://api.github.com/repos/{gateway.REPO}/issues/"
            f"{recovery.ISSUE_NUMBER}"
        ),
        "comments": [],
    }


def test_accepts_only_exact_pending_original_issue():
    authority = _authority()
    assert recovery.validate_existing_issue(_issue(authority), authority) == "pending"


@pytest.mark.parametrize(
    "field,value",
    [
        ("number", 1052),
        ("title", "different title"),
        ("body", "altered body"),
        ("state", "closed"),
        ("labels", ["other"]),
        ("id", "1234567"),
        ("node_id", "I_kw_TEST"),
        ("url", "https://example.com/unrelated"),
    ],
)
def test_rejects_identity_or_body_drift(field, value):
    authority = _authority()
    issue = _issue(authority)
    issue[field] = value
    with pytest.raises(ValueError, match="projection_mismatch"):
        recovery.validate_existing_issue(issue, authority)


def test_rejects_existing_untrusted_comment():
    authority = _authority()
    issue = _issue(authority)
    issue["comments"] = [{"id": 1, "body": "human edit", "user": {"login": "someone"}}]
    with pytest.raises(ValueError, match="comments_conflict"):
        recovery.validate_existing_issue(issue, authority)


def test_recognises_exact_valid_receipt_as_idempotent_no_op():
    authority = _authority()
    issue = _issue(authority)
    _, receipt_body = gateway.build_create_receipt(
        issue,
        mutation_id=recovery.AUTHORITY_ID,
        stable_id=recovery.TARGET,
        authority_id=recovery.AUTHORITY_ID,
        authority_sequence=194,
        source_sha=authority["payload"]["source_sha"],
        head_sha=recovery.ORIGINAL_HEAD,
        ledger_blob_oid="1" * 40,
        ledger_blob_sha256="1" * 64,
        plan_sha256=authority["payload"]["plan_sha256"],
        event_before=recovery.ORIGINAL_HEAD,
        event_after="a" * 40,
    )
    issue["comments"] = [{
        "id": 999,
        "node_id": "IC_test",
        "body": receipt_body,
        "user": {"id": int(gateway.GITHUB_ACTIONS_BOT_USER_ID),
                 "login": "github-actions[bot]", "type": "Bot"},
        "performed_via_github_app": {"slug": "github-actions",
                                      "id": gateway.GITHUB_ACTIONS_APP_ID},
        "created_at": "2026-11-16T02:00:00Z",
        "updated_at": "2026-11-16T02:00:00Z",
    }]
    assert recovery.validate_existing_issue(issue, authority) == "accepted"
    tampered = copy.deepcopy(issue)
    tampered["body"] += "changed"
    with pytest.raises(ValueError, match="projection_mismatch"):
        recovery.validate_existing_issue(tampered, authority)


def test_recovery_rejects_missing_github_actions_identity(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(gateway.MutationPolicyError):
        recovery.recover(tmp_path)


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
    monkeypatch.setattr(gateway, "CREATE_RECEIPT_RECOVERY_HEAD_SHA", base)
    git("commit", "--allow-empty", "-qm", "early change")
    path = tmp_path / gateway.CREATE_RECEIPT_RECOVERY_PATH
    path.parent.mkdir()
    path.write_text("# recovery\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "reviewed recovery")
    candidate = git("rev-parse", "HEAD")
    gateway.validate_create_receipt_recovery_push(tmp_path, base, candidate, validating_candidate=True)
    with pytest.raises(ValueError, match="push_not_authorised"):
        gateway.validate_create_receipt_recovery_push(tmp_path, base, candidate)
    git("switch", "--detach", base)
    git("merge", "--no-ff", "-qm", "reviewed merge", candidate)
    gateway.validate_create_receipt_recovery_push(tmp_path, base, git("rev-parse", "HEAD"))


def test_parser_rejects_other_issues_using_recovery_push():
    authority = _authority()
    issue = _issue(authority)
    _, body = gateway.build_create_receipt(
        issue,
        mutation_id="9" * 64,
        stable_id="ISSUE-0183",
        authority_id="9" * 64,
        authority_sequence=195,
        source_sha=authority["payload"]["source_sha"],
        head_sha=recovery.ORIGINAL_HEAD,
        ledger_blob_oid="1" * 40,
        ledger_blob_sha256="1" * 64,
        plan_sha256=authority["payload"]["plan_sha256"],
        event_before=recovery.ORIGINAL_HEAD,
        event_after="a" * 40,
    )
    with pytest.raises(ValueError, match="invalid_create_receipt_workflow_binding"):
        gateway.parse_create_receipt(body)


@pytest.mark.parametrize("lost_response", [False, True])
def test_recover_appends_once_and_valid_receipt_is_noop(tmp_path, monkeypatch, lost_response):
    authority = _authority()
    authority["payload"]["claim_inventory_sha256"] = gateway.claim_inventory_sha256([])
    issue = _issue(authority)
    activation = "a" * 40
    binding = {"ledger_blob_oid": "1" * 40, "ledger_blob_sha256": "1" * 64}
    attestation = {
        "event_name": "push", "event_ref": "refs/heads/main", "run_attempt": "1",
        "event_before": recovery.ORIGINAL_HEAD, "event_after": activation,
        "actor": "owner", "pusher": "owner", "run_id": "9", "run_number": "3",
        "workflow_ref": f"{gateway.REPO}/{recovery.status.WORKFLOW_PATH}@refs/heads/main",
        "repository": gateway.REPO, "event_payload_sha256": "a" * 64,
    }
    calls = []

    class Transport:
        def list_issues(self):
            return [{**issue, "comments": len(issue["comments"])}]

        def fetch_issue(self, number):
            assert number == recovery.ISSUE_NUMBER
            return copy.deepcopy(issue)

        def append_comment(self, number, body):
            assert number == recovery.ISSUE_NUMBER and calls[-1] == "proof"
            calls.append("append")
            issue["comments"].append({
                "id": 999, "node_id": "IC_test", "body": body,
                "user": {"id": int(gateway.GITHUB_ACTIONS_BOT_USER_ID),
                         "login": "github-actions[bot]", "type": "Bot"},
                "performed_via_github_app": {"slug": "github-actions",
                                             "id": gateway.GITHUB_ACTIONS_APP_ID},
                "created_at": "2026-11-16T02:00:00Z", "updated_at": "2026-11-16T02:00:00Z",
            })
            if lost_response:
                raise TimeoutError("receipt response lost")

        def create_open_issue(self, *_args):
            pytest.fail("receipt recovery cannot create an issue")

    def original_run(run_id):
        assert run_id == recovery.ORIGINAL_WRITER_RUN
        return {"id": run_id, "event": "push", "path": recovery.status.WORKFLOW_PATH,
                "head_sha": recovery.ORIGINAL_HEAD, "status": "completed", "conclusion": "failure",
                "run_attempt": 1, "repository": {"full_name": gateway.REPO}}

    def verify_push(_root, parent, head, *, validating_candidate=False):
        assert not validating_candidate
        assert parent == recovery.ORIGINAL_HEAD and head == activation

    def verify_readback(_root, records, remote):
        assert records == [authority] and gateway.validate_create_acceptance(remote[0])["accepted"]
        calls.append("readback")

    monkeypatch.setattr(recovery.status, "github_actions_push_attestation", lambda _reader: attestation)
    monkeypatch.setattr(recovery.status, "_git", lambda *_args: activation)
    monkeypatch.setattr(recovery, "_original_authority", lambda _root: (authority, binding, [authority]))
    monkeypatch.setattr(gateway, "validate_create_receipt_recovery_push", verify_push)
    monkeypatch.setattr(gateway, "reconcile_authority_ledger", lambda *args, **kwargs: {"accepted": True})
    monkeypatch.setattr(recovery, "_readback", verify_readback)
    inputs = {
        "run_reader": original_run, "main_fetcher": lambda _root: None, "transport": Transport(),
        "proof_verifier": lambda _attestation: calls.append("proof"),
        "remote_reader": lambda: [copy.deepcopy(issue)],
    }
    assert recovery.recover(tmp_path, **inputs)["zero_action_readback"]
    assert recovery.recover(tmp_path, **inputs)["transport_writes"] == 0
    assert calls == ["proof", "append", "readback", "readback"]
