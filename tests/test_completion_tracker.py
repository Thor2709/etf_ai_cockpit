from __future__ import annotations

import json

import pytest

from scripts import sync_github_issues as sync


def record(issue_id: str = "ISSUE-0070", *, state: str = "open") -> dict:
    return {
        "canonical_id": issue_id,
        "title": "Governance contract",
        "classification": "proposed_new",
        "ledger_state": state,
        "programme_status": "ready" if state == "open" else "closed",
        "priority": "P0/P1",
        "owner": "programme-governance",
        "phase": "phase-01-governance-scope",
        "blocking_dependencies": [],
        "related_issues": [],
    }


def registry(*records: dict) -> dict:
    return {"records": list(records), "local_only_records": []}


def remote(issue: dict, *, number: int = 1, state: str = "open", body: str | None = None) -> dict:
    return {
        "number": number,
        "title": issue["title"],
        "state": state,
        "body": body if body is not None else sync.managed_block(issue),
        "url": f"https://github.com/Thor2709/etf_ai_cockpit/issues/{number}",
    }


def test_managed_replacement_preserves_unmanaged_body() -> None:
    old = record()
    new = {**old, "programme_status": "in_progress"}
    body = "Historical context\n\n" + sync.managed_block(old) + "\n\nReviewer notes"
    replaced = sync.replace_managed_block(body, sync.managed_block(new))
    assert replaced.startswith("Historical context\n\n")
    assert replaced.endswith("\n\nReviewer notes")
    assert "`in_progress`" in replaced
    assert "`ready`" not in replaced


def test_duplicate_marker_is_blocked() -> None:
    issue = record()
    plan = sync.plan_actions(
        registry(issue),
        [remote(issue, number=1), remote(issue, number=2)],
    )
    assert plan["summary"]["blocked"] == 1
    assert plan["actions"][0]["reason"] == "duplicate_stable_marker"


def test_state_guard_allows_only_reviewed_reopen() -> None:
    ordinary = record("ISSUE-0070")
    ordinary_plan = sync.plan_actions(registry(ordinary), [remote(ordinary, state="closed")])
    assert any(action["reason"] == "unexpected_transition_closed_to_open" for action in ordinary_plan["actions"])

    reviewed = record("ISSUE-0067")
    reviewed_plan = sync.plan_actions(registry(reviewed), [remote(reviewed, state="closed")])
    assert reviewed_plan["summary"]["reopen"] == 1
    assert reviewed_plan["summary"]["blocked"] == 0


def test_legacy_unmanaged_match_is_not_edited_or_duplicated() -> None:
    issue = record()
    legacy = remote(issue, body="Old body mentioning ISSUE-0070")
    plan = sync.plan_actions(registry(issue), [legacy])
    assert plan["summary"]["blocked"] == 1
    assert plan["actions"][0]["reason"] == "legacy_unmanaged_match"


def test_missing_open_record_is_create_and_missing_closed_record_is_blocked() -> None:
    open_issue = record("ISSUE-0070")
    closed_issue = record("UPDATEV2-0010", state="closed")
    plan = sync.plan_actions(registry(open_issue, closed_issue), [])
    assert plan["summary"]["create"] == 1
    assert plan["summary"]["blocked"] == 1
    assert {action["reason"] for action in plan["actions"] if action["kind"] == "blocked"} == {"missing_closed_record"}


def test_plan_hash_is_required_before_apply() -> None:
    issue = record()
    plan = sync.plan_actions(registry(issue), [remote(issue)])
    with pytest.raises(ValueError, match="approved plan SHA-256"):
        sync.apply_actions(plan, approved_sha256="wrong")


def test_idempotent_managed_remote_has_no_actions() -> None:
    issue = record()
    plan = sync.plan_actions(registry(issue), [remote(issue)])
    assert plan["summary"] == {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
    assert plan["plan_sha256"] == sync.plan_sha256(plan)


def test_legacy_marker_migration_is_idempotent() -> None:
    issue = record()
    legacy_body = "\n".join(
        [
            "Human context",
            "<!-- etf-ai-cockpit-local-issue-id: ISSUE-0070 -->",
            sync.LEGACY_MANAGED_START,
            "legacy managed content",
            sync.LEGACY_MANAGED_END,
            "Reviewer note",
        ]
    )
    first = sync.plan_actions(registry(issue), [remote(issue, body=legacy_body)])
    update = next(action for action in first["actions"] if action["kind"] == "update")
    second_remote = remote(issue, body=update["body"])
    second = sync.plan_actions(registry(issue), [second_remote])
    assert second["summary"] == {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}


def test_cli_dry_run_writes_plan_only(tmp_path, monkeypatch) -> None:
    issue = record()
    registry_path = tmp_path / "issues" / "issue_registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text(json.dumps(registry(issue)), encoding="utf-8")
    snapshot = tmp_path / "remote.json"
    snapshot.write_text(json.dumps([remote(issue)]), encoding="utf-8")
    output = tmp_path / "plan.json"
    monkeypatch.setattr(sync, "REPO", "Thor2709/etf_ai_cockpit")
    assert sync.main(["--root", str(tmp_path), "--remote-snapshot", str(snapshot), "--plan-out", str(output)]) == 0
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["blocked"] == 0
