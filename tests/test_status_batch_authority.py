"""Reviewed status batches: one push appending several status authorities."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import apply_reviewed_status_completion as completion
from scripts import github_mutation_gateway as gateway
from scripts import prepare_github_mutation_authority as prepare
from scripts import sync_github_issues as sync

ISSUES = (("ISSUE-0179", 179), ("ISSUE-0180", 180))
RUN_ATTESTATION = {
    "run_id": "12345",
    "run_number": "7",
    "workflow_ref": (
        f"{gateway.REPO}/.github/workflows/"
        "programme-status-completion.yml@refs/heads/main"
    ),
    "repository": gateway.REPO,
    "event_payload_sha256": "d" * 64,
}


def _record(stable_id: str, status: str) -> dict[str, object]:
    return {
        "canonical_id": stable_id,
        "title": f"Batch fixture {stable_id}",
        "classification": "proposed_new",
        "ledger_state": "open",
        "programme_status": status,
        "priority": "P1",
        "owner": "programme-governance",
        "phase": "phase-01-governance-scope",
        "blocking_dependencies": [],
        "required_inputs": [],
        "activation_dependencies": [],
        "capability_lane": "CORE_ANALYSIS",
        "release_blocking": True,
        "downstream_issues": [],
        "related_issues": [],
    }


def _remote(status: str = "implemented_initially") -> list[dict[str, Any]]:
    return [
        {
            "id": f"4{number}",
            "node_id": f"ISSUE_NODE_{number}",
            "number": number,
            "title": f"Batch fixture {stable_id}",
            "body": sync.managed_block(_record(stable_id, status)),
            "state": "OPEN",
            "url": f"https://example.invalid/issues/{number}",
            "comments": [],
        }
        for stable_id, number in ISSUES
    ]


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _commit_all(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    return _git(root, "rev-parse", "HEAD")


def _registry(status: str) -> dict[str, object]:
    return {"records": [_record(stable_id, status) for stable_id, _number in ISSUES]}


def _repo(tmp_path: Path) -> tuple[Path, str, dict[str, Any]]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
    bootstrap = gateway.build_authority_record(
        "legacy_bootstrap",
        {
            "legacy_issues": [
                {
                    "stable_id": stable_id,
                    "issue_number": number,
                    "database_id": f"4{number}",
                    "node_id": f"ISSUE_NODE_{number}",
                    "initial_status": "implemented_initially",
                }
                for stable_id, number in ISSUES
            ]
        },
        sequence=0,
        previous_authority_id=None,
    )
    ledger = root / gateway.AUTHORITY_PATH
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap]))
    registry = root / completion.REGISTRY_PATH
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(_registry("implemented_initially")), encoding="utf-8")
    source = _commit_all(root, "bootstrap")
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", source], cwd=root, check=True
    )
    return root, source, bootstrap


def _plan(root: Path, remote: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    return sync.plan_actions(
        _registry("integrated"),
        remote,
        historical_map=None,
        authority_records=records,
        authority_root=root,
    )


def _prepared_head(tmp_path: Path) -> tuple[Path, str, str, dict[str, Any], list[dict[str, Any]]]:
    """Prepare a two-issue status batch and commit it exactly as a lifecycle PR would."""

    root, source, bootstrap = _repo(tmp_path)
    remote = _remote()
    plan = _plan(root, remote, [bootstrap])
    candidate_bytes, ledger_bytes, manifest = prepare.prepare(
        root, plan, remote, source_sha=source, mode="status_batch"
    )
    again = prepare.prepare(root, plan, remote, source_sha=source, mode="status_batch")
    assert again == (candidate_bytes, ledger_bytes, manifest)
    assert candidate_bytes is not None
    candidate_path = root / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_bytes(candidate_bytes)
    (root / gateway.AUTHORITY_PATH).write_bytes(ledger_bytes)
    (root / completion.REGISTRY_PATH).write_text(
        json.dumps(_registry("integrated")), encoding="utf-8"
    )
    head = _commit_all(root, "status batch")
    return root, source, head, plan, remote


def test_prepare_status_batch_is_deterministic_chained_and_binds_batch_bytes(
    tmp_path: Path,
) -> None:
    root, source, head, plan, _remote_rows = _prepared_head(tmp_path)

    candidate_bytes = (root / completion.DEFAULT_CANDIDATE).read_bytes()
    candidate = json.loads(candidate_bytes)
    records = gateway.parse_authority_ledger((root / gateway.AUTHORITY_PATH).read_bytes())
    appended = records[1:]
    assert candidate["schema_version"] == completion.BATCH_SCHEMA_VERSION
    assert candidate["execution_allowed"] is False
    assert [entry["expected_update"]["stable_id"] for entry in candidate["entries"]] == [
        "ISSUE-0179",
        "ISSUE-0180",
    ]
    assert [record["authority_type"] for record in appended] == ["status", "status"]
    assert [record["sequence"] for record in appended] == [1, 2]
    assert appended[0]["previous_authority_id"] == records[0]["authority_id"]
    assert appended[1]["previous_authority_id"] == appended[0]["authority_id"]
    assert gateway.is_status_batch(appended)
    blob_oid = _git(root, "rev-parse", f"{head}:{completion.DEFAULT_CANDIDATE.as_posix()}")
    for record, entry in zip(appended, candidate["entries"], strict=True):
        payload = record["payload"]
        assert payload["candidate_blob_oid"] == blob_oid
        assert payload["candidate_blob_sha256"] == gateway._sha256(candidate_bytes)
        assert payload["candidate_authority_ref"] == entry["authority_ref"]
        assert payload["plan_sha256"] == plan["plan_sha256"] == entry["plan_semantic_sha256"]
        assert (payload["from_status"], payload["to_status"]) == (
            "implemented_initially",
            "integrated",
        )

    one = {
        **plan,
        "summary": dict(completion.ONE_UPDATE_SUMMARY),
        "actions": plan["actions"][:1],
    }
    one["plan_sha256"] = sync.plan_sha256(one)
    subprocess.run(["git", "checkout", "-q", source], cwd=root, check=True)
    with pytest.raises(ValueError, match="at least two reviewed actions"):
        prepare.prepare(root, one, _remote(), source_sha=source, mode="status_batch")


def test_status_batch_git_transition_and_projected_binding_accept_only_batches(
    tmp_path: Path,
) -> None:
    root, source, head, _plan_rows, _remote_rows = _prepared_head(tmp_path)

    before, after, binding = gateway.validate_authority_git_transition(
        root, event_before=source, event_after=head, main_ref=None
    )
    assert len(before) == 1 and len(after) == 3
    assert binding["authority_id"] == after[-1]["authority_id"]
    for record in after[1:]:
        gateway.validate_projected_git_binding(
            root,
            record,
            {
                "source_sha": source,
                "head_sha": head,
                "ledger_blob_oid": binding["ledger_blob_oid"],
                "ledger_blob_sha256": binding["ledger_blob_sha256"],
                "candidate_blob_oid": record["payload"]["candidate_blob_oid"],
                "candidate_blob_sha256": record["payload"]["candidate_blob_sha256"],
            },
        )

    first, second = after[1], after[2]
    create = gateway.build_authority_record(
        "create",
        {
            "stable_id": "ISSUE-0181",
            "source_sha": source,
            "title": "Batch fixture ISSUE-0181",
            "managed_body": sync.managed_block(_record("ISSUE-0181", "planned")),
            "claim_inventory_sha256": "4" * 64,
            "plan_sha256": "2" * 64,
        },
        sequence=2,
        previous_authority_id=str(first["authority_id"]),
    )
    duplicate = copy.deepcopy(second)
    duplicate["payload"]["stable_id"] = first["payload"]["stable_id"]
    other_plan = copy.deepcopy(second)
    other_plan["payload"]["plan_sha256"] = "3" * 64
    assert not gateway.is_status_batch([first])
    assert not gateway.is_status_batch([first, create])
    assert not gateway.is_status_batch([first, duplicate])
    assert not gateway.is_status_batch([first, other_plan])

    subprocess.run(["git", "checkout", "-q", source], cwd=root, check=True)
    (root / gateway.AUTHORITY_PATH).write_bytes(
        gateway.authority_ledger_bytes([before[0], first, create])
    )
    mixed = _commit_all(root, "mixed append")
    with pytest.raises(gateway.MutationPolicyError, match="exactly_one_append"):
        gateway.validate_authority_git_transition(
            root, event_before=source, event_after=mixed, main_ref=None
        )


def test_status_batch_run_validates_real_head_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    root, source, head, plan, remote = _prepared_head(tmp_path)
    evidence_path = tmp_path / "evidence.json"

    completion.run(
        root,
        root / completion.DEFAULT_CANDIDATE,
        expected_parent=source,
        expected_head=head,
        main_ref=None,
        apply=False,
        evidence_out=evidence_path,
        remote_reader=lambda: remote,
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == "validated"
    assert [row["stable_id"] for row in evidence["status_batch"]] == [
        "ISSUE-0179",
        "ISSUE-0180",
    ]

    records = gateway.parse_authority_ledger((root / gateway.AUTHORITY_PATH).read_bytes())
    candidate = json.loads((root / completion.DEFAULT_CANDIDATE).read_bytes())
    oid = _git(root, "rev-parse", f"{head}:{completion.DEFAULT_CANDIDATE.as_posix()}")
    digest = completion._canonical_candidate_blob_sha256(root, head)

    def check(mutated: dict[str, Any], batch_plan: dict[str, Any], authorities: list[dict[str, Any]]) -> None:
        completion.validate_status_batch(
            root,
            mutated,
            batch_plan,
            remote,
            authorities,
            expected_parent=source,
            expected_head=head,
            candidate_oid=oid,
            candidate_sha256=digest,
        )

    check(candidate, plan, records[1:])
    reordered = {**candidate, "entries": candidate["entries"][::-1]}
    with pytest.raises(ValueError, match="one-to-one"):
        check(reordered, plan, records[1:])
    with pytest.raises(ValueError, match="do not match the appended authorities"):
        check({**candidate, "entries": candidate["entries"][:1]}, plan, records[1:])
    with pytest.raises(ValueError, match="not in candidate order"):
        check(candidate, plan, records[1:][::-1])
    extra = {**plan, "summary": {**completion.ZERO_SUMMARY, "update": 3}}
    with pytest.raises(ValueError, match="exactly one update per entry"):
        check(candidate, extra, records[1:])
    tampered = copy.deepcopy(candidate)
    tampered["entries"][1]["plan_semantic_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="differs from the batch envelope"):
        check(tampered, plan, records[1:])
    rebound = copy.deepcopy(candidate)
    rebound["entries"][0]["authority_ref"] = rebound["entries"][1]["authority_ref"]
    with pytest.raises(ValueError):
        check(rebound, plan, records[1:])


def test_status_batch_apply_appends_each_issue_in_order_and_stops_on_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source, head, plan, remote = _prepared_head(tmp_path)
    records = gateway.parse_authority_ledger((root / gateway.AUTHORITY_PATH).read_bytes())
    calls: list[dict[str, Any]] = []
    verdicts: list[bool] = []

    def fake_append(reviewed_snapshot: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        record = kwargs["authority_record"]
        binding = kwargs["git_binding"]
        assert binding["authority_id"] == record["authority_id"]
        assert binding["authority_sequence"] == record["sequence"]
        assert binding["authority_type"] == "status"
        assert reviewed_snapshot["number"] == record["payload"]["issue_number"]
        calls.append({"stable_id": kwargs["stable_id"], "sequence": record["sequence"]})
        accepted = verdicts.pop(0)
        return {"accepted": accepted, "terminal_status": "accepted" if accepted else "conflict"}

    monkeypatch.setattr(completion.mutation_gateway, "append_status_event", fake_append)
    monkeypatch.setattr(
        completion.mutation_gateway,
        "reconcile_authority_ledger",
        lambda *_a, **_k: {"accepted": True, "projections": []},
    )

    def run_apply(evidence_path: Path) -> None:
        completion.run(
            root,
            root / completion.DEFAULT_CANDIDATE,
            expected_parent=source,
            expected_head=head,
            main_ref=None,
            apply=True,
            evidence_out=evidence_path,
            remote_reader=lambda: remote,
            event_name="push",
            event_ref="refs/heads/main",
            run_attempt="1",
            event_before=source,
            event_after=head,
            actor="merger",
            pusher="merger",
            **RUN_ATTESTATION,
            caller_proof_verifier=lambda: None,
        )

    plans = iter([plan, {"summary": dict(completion.ZERO_SUMMARY), "actions": []}])
    monkeypatch.setattr(completion.sync, "plan_actions", lambda *_a, **_k: next(plans))
    verdicts.extend([True, True])
    run_apply(tmp_path / "applied.json")
    assert calls == [
        {"stable_id": "ISSUE-0179", "sequence": records[1]["sequence"]},
        {"stable_id": "ISSUE-0180", "sequence": records[2]["sequence"]},
    ]
    applied = json.loads((tmp_path / "applied.json").read_text(encoding="utf-8"))
    assert applied["terminal_status"] == "applied_and_verified"
    assert applied["zero_action_readback"] is True

    calls.clear()
    monkeypatch.setattr(completion.sync, "plan_actions", lambda *_a, **_k: plan)
    verdicts.extend([False, True])
    with pytest.raises(RuntimeError, match="not accepted: conflict"):
        run_apply(tmp_path / "rejected.json")
    assert [call["stable_id"] for call in calls] == ["ISSUE-0179"]
    rejected = json.loads((tmp_path / "rejected.json").read_text(encoding="utf-8"))
    assert rejected["mutation"]["accepted"] is False
    assert len(rejected["mutation"]["batch"]) == 1
