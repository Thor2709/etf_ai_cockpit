"""Focused edge coverage for bug-hunt fix group W2."""

from __future__ import annotations

from scripts import github_mutation_gateway


def test_creation_acceptance_remains_bound_to_issue_identity() -> None:
    issue = {
        "number": 1,
        "id": "101",
        "node_id": "NODE_1",
        "title": "Issue 1",
        "state": "open",
        "labels": [],
        "comments": [],
        "body": (
            github_mutation_gateway.CREATE_MARKER_TEMPLATE.format("a" * 64)
            + "\r\n<!-- etf-ai-cockpit:stable-id=ISSUE-0001 -->"
        ),
    }
    _, receipt = github_mutation_gateway.build_create_receipt(
        issue, mutation_id="a" * 64, stable_id="ISSUE-0001"
    )
    issue["comments"] = [
        {
            "id": "C1",
            "body": receipt,
            "author": "github-actions[bot]",
            "author_id": github_mutation_gateway.GITHUB_ACTIONS_BOT_USER_ID,
            "author_type": "Bot",
            "app_slug": "github-actions",
            "app_id": github_mutation_gateway.GITHUB_ACTIONS_APP_ID,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z",
        }
    ]

    assert github_mutation_gateway.validate_create_acceptance(issue)["accepted"]

    issue["id"] = "102"

    assert not github_mutation_gateway.validate_create_acceptance(issue)["accepted"]
