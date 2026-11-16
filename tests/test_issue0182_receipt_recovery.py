"""Focused checks for the one-off ISSUE-0182 receipt recovery."""

from __future__ import annotations

import copy
from pathlib import Path

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
        "id": "1234567",
        "node_id": "I_kw_TEST",
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
        ("id", ""),
        ("node_id", ""),
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
        event_name="workflow_dispatch",
        event_before=authority["payload"]["source_sha"],
        event_after=recovery.ORIGINAL_HEAD,
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


def test_dispatch_rejects_missing_github_actions_identity(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError, match="requires_first_party_dispatch"):
        recovery._attest_dispatch(lambda _run_id: {})


def test_parser_rejects_other_issues_using_recovery_dispatch():
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
        event_name="workflow_dispatch",
        event_before=authority["payload"]["source_sha"],
        event_after=recovery.ORIGINAL_HEAD,
    )
    with pytest.raises(ValueError, match="invalid_create_receipt_workflow_binding"):
        gateway.parse_create_receipt(body)
