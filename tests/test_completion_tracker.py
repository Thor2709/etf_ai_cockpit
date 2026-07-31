from __future__ import annotations

import json

import pytest

from scripts import github_mutation_gateway as gateway
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
        "required_inputs": ["ISSUE-0008"],
        "activation_dependencies": [],
        "capability_lane": "CORE_ANALYSIS",
        "release_blocking": True,
        "downstream_issues": ["ISSUE-0071"],
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


def test_reviewed_duplicate_map_selects_newest_and_retains_closed_legacy_issue() -> None:
    issue = record()
    older = remote(issue, number=1, state="closed")
    newer = remote(issue, number=2, state="open")
    historical_map = {
        "mappings": {
            "ISSUE-0070": {
                "selected_remote_number": 2,
                "remote_numbers": [1, 2],
                "selection_basis": "reviewed test map",
            }
        },
        "map_sha256": "test",
    }
    plan = sync.plan_actions(registry(issue), [older, newer], historical_map=historical_map)
    assert plan["summary"] == {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
    assert plan["legacy_duplicates"][0]["retained_closed_remote_numbers"] == [1]


def test_duplicate_map_cannot_select_while_older_duplicate_is_open() -> None:
    issue = record()
    older = remote(issue, number=1, state="open")
    newer = remote(issue, number=2, state="open")
    historical_map = {
        "mappings": {
            "ISSUE-0070": {
                "selected_remote_number": 2,
                "remote_numbers": [1, 2],
            }
        }
    }
    plan = sync.plan_actions(registry(issue), [older, newer], historical_map=historical_map)
    assert plan["summary"]["blocked"] == 1
    assert plan["actions"][0]["reason"] == "duplicate_stable_marker"


def test_state_guard_allows_only_reviewed_reopen() -> None:
    ordinary = record("ISSUE-0070")
    ordinary_plan = sync.plan_actions(registry(ordinary), [remote(ordinary, state="closed")])
    assert any(action["reason"] == "unexpected_transition_closed_to_open" for action in ordinary_plan["actions"])

    for stable_id in ("ISSUE-0048", "ISSUE-0067", "ISSUE-0122"):
        reviewed = record(stable_id)
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


def test_create_action_contains_canonical_managed_fields() -> None:
    issue = record()
    plan = sync.plan_actions(registry(issue), [])
    action = next(action for action in plan["actions"] if action["kind"] == "create")
    body = sync.managed_block(action)
    assert "Classification: `proposed_new`" in body
    assert "Programme status: `ready`" in body
    assert "Owner: `programme-governance`" in body
    assert "Required inputs: `ISSUE-0008`" in body
    assert "Activation dependencies: None" in body
    assert "Capability lane: `CORE_ANALYSIS`" in body
    assert "Downstream issues: `ISSUE-0071`" in body


def test_plan_hash_is_required_before_apply() -> None:
    issue = record()
    plan = sync.plan_actions(registry(issue), [remote(issue)])
    with pytest.raises(gateway.MutationPolicyError) as captured:
        sync.apply_actions(plan, approved_sha256="wrong")
    assert captured.value.code == "approved_plan_sha256_mismatch"
    assert captured.value.evidence["transport_writes"] == 0


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
    inventory = tmp_path / "inventory.json"
    review = tmp_path / "review.md"
    monkeypatch.setattr(sync, "REPO", "Thor2709/etf_ai_cockpit")
    assert sync.main(
        [
            "--root",
            str(tmp_path),
            "--remote-snapshot",
            str(snapshot),
            "--plan-out",
            str(output),
            "--inventory-out",
            str(inventory),
            "--review-out",
            str(review),
        ]
    ) == 0
    assert output.exists()
    assert inventory.exists()
    assert "not an apply plan" in review.read_text(encoding="utf-8")
    assert "No GitHub issue was mutated" in review.read_text(encoding="utf-8")
    safe_inventory = json.loads(inventory.read_text(encoding="utf-8"))
    assert safe_inventory["inventory_sha256"] == json.loads(output.read_text(encoding="utf-8"))["remote_inventory_sha256"]
    assert all("body" not in row for row in safe_inventory["issues"])
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["blocked"] == 0


def test_cli_prohibits_remote_snapshot_apply() -> None:
    with pytest.raises(SystemExit, match="remote_snapshot_apply_prohibited"):
        sync.main(
            [
                "--remote-snapshot",
                "untrusted.json",
                "--apply",
                "--approved-plan-sha256",
                "0" * 64,
            ]
        )


def test_status_event_projection_produces_zero_action_convergence() -> None:
    desired = record()
    desired["programme_status"] = "integrated"
    value = remote({**desired, "programme_status": "implemented_initially"})
    projection = gateway.project_status_events(value)
    _event, body = gateway.build_status_event(
        stable_id="ISSUE-0070",
        from_status="implemented_initially",
        to_status="integrated",
        source_sha="a" * 40,
        head_sha="b" * 40,
        candidate_blob_sha256="c" * 64,
        plan_sha256="d" * 64,
        predecessor_event_id=projection["head_event_id"],
        predecessor_event_sha256=projection["head_event_sha256"],
        event_name="push",
        event_ref="refs/heads/main",
        run_attempt="1",
        event_before="a" * 40,
        event_after="b" * 40,
        actor="merger",
        pusher="merger",
    )
    value["comments"] = [
        {
            "id": "event-1",
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
            "createdAt": "2026-07-31T00:00:00Z",
            "updatedAt": "2026-07-31T00:00:00Z",
        }
    ]

    plan = sync.plan_actions(registry(desired), [value])

    assert plan["actions"] == []
    assert plan["summary"] == {
        "create": 0,
        "update": 0,
        "close": 0,
        "reopen": 0,
        "blocked": 0,
    }

    non_status_drift = {**desired, "priority": "P9"}
    drift_plan = sync.plan_actions(registry(non_status_drift), [value])
    assert drift_plan["summary"]["update"] == 1
    assert drift_plan["actions"][0]["kind"] == "update"
