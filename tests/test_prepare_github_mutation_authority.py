from __future__ import annotations

import json
import copy
import subprocess
from pathlib import Path

import pytest

from scripts import apply_reviewed_status_completion as completion
from scripts import github_mutation_gateway as gateway
from scripts.issue_registry_core import (
    control_state_record,
    load_control_state,
    load_control_state_at,
    validate_status_replay_prefix_shape,
)
from scripts import prepare_github_mutation_authority as prepare
from scripts import sync_github_issues as sync


def _record(status: str = "integrated") -> dict[str, object]:
    return {
        "canonical_id": "ISSUE-0179",
        "title": "Atomic programme generation",
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


def _remote() -> list[dict[str, object]]:
    return [
        {
            "id": "4179",
            "node_id": "ISSUE_NODE_179",
            "number": 179,
            "title": "Atomic programme generation",
            "body": sync.managed_block(_record("implemented_initially")),
            "state": "OPEN",
            "url": "https://example.invalid/issues/179",
            "comments": [],
        }
    ]


def _bootstrap(initial_status: str = "implemented_initially") -> dict[str, object]:
    return gateway.build_authority_record(
        "legacy_bootstrap",
        {
            "legacy_issues": [
                {
                    "stable_id": "ISSUE-0179",
                    "issue_number": 179,
                    "database_id": "4179",
                    "node_id": "ISSUE_NODE_179",
                    "initial_status": initial_status,
                }
            ]
        },
        sequence=0,
        previous_authority_id=None,
    )


def _repo(
    tmp_path: Path, *, initial_status: str = "implemented_initially"
) -> tuple[Path, str, dict[str, object]]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    bootstrap = _bootstrap(initial_status)
    ledger = root / gateway.AUTHORITY_PATH
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap]))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "bootstrap"], cwd=root, check=True)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", source],
        cwd=root,
        check=True,
    )
    return root, source, bootstrap


def _control_state(record: dict[str, object], generation_base: str) -> dict[str, object]:
    return {
        "metadata": {
            "bootstrap": False,
            "bootstrap_reason": "",
            "generation_base_commit": generation_base,
            "generation_base_ref": "origin/main",
            "verified_date": "2026-08-02",
        },
        "phase_definitions": [
            {
                "order": 1,
                "phase": "phase-01-governance-scope",
                "title": "Governance, scope and completion contract",
            }
        ],
        "records": {"ISSUE-0179": record},
        "schema_version": "1.0",
    }


def test_status_preparation_command_is_deterministic_and_repository_read_only(
    tmp_path: Path,
) -> None:
    root, source, bootstrap = _repo(tmp_path)
    remote = _remote()
    plan = sync.plan_actions(
        {"records": [_record()]},
        remote,
        historical_map={},
        authority_records=[bootstrap],
    )
    plan_path = tmp_path / "reviewed-plan.json"
    remote_path = tmp_path / "live-snapshot.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    remote_path.write_text(json.dumps(remote), encoding="utf-8")

    outputs = [tmp_path / "prepared-one", tmp_path / "prepared-two"]
    for output in outputs:
        assert (
            prepare.main(
                [
                    "--root",
                    str(root),
                    "--plan",
                    str(plan_path),
                    "--remote-snapshot",
                    str(remote_path),
                    "--source-sha",
                    source,
                    "--mode",
                    "status",
                    "--output-dir",
                    str(output),
                ]
            )
            == 0
        )

    first_candidate = (outputs[0] / completion.DEFAULT_CANDIDATE).read_bytes()
    second_candidate = (outputs[1] / completion.DEFAULT_CANDIDATE).read_bytes()
    first_ledger = (outputs[0] / gateway.AUTHORITY_PATH).read_bytes()
    second_ledger = (outputs[1] / gateway.AUTHORITY_PATH).read_bytes()
    assert first_candidate == second_candidate
    assert first_ledger == second_ledger
    records = gateway.parse_authority_ledger(first_ledger)
    assert len(records) == 2
    assert records[-1]["authority_type"] == "status"
    assert records[-1]["payload"]["candidate_blob_sha256"] == __import__(
        "hashlib"
    ).sha256(first_candidate).hexdigest()
    assert json.loads(first_candidate)["execution_allowed"] is False
    assert subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ) == ""


@pytest.mark.parametrize(
    ("source_status", "target_status"),
    [("planned", "ready"), ("ready", "in_progress")],
)
def test_status_preparation_accepts_one_legal_pending_hop(
    tmp_path: Path, source_status: str, target_status: str
) -> None:
    root, source, bootstrap = _repo(tmp_path, initial_status=source_status)
    remote = [
        {
            **_remote()[0],
            "body": sync.managed_block(_record(source_status)),
        }
    ]
    plan = sync.plan_actions(
        {"records": [_record(target_status)]},
        remote,
        historical_map={},
        authority_records=[bootstrap],
    )

    candidate_bytes, ledger_bytes, _manifest = prepare.prepare(
        root, plan, remote, source_sha=source, mode="status"
    )

    assert candidate_bytes is not None
    candidate = json.loads(candidate_bytes)
    assert candidate["expected_update"] == {
        "stable_id": "ISSUE-0179",
        "from_status": source_status,
        "to_status": target_status,
    }
    records = gateway.parse_authority_ledger(ledger_bytes)
    assert records[-1]["authority_type"] == "status"
    assert records[-1]["payload"]["to_status"] == target_status


def test_create_preparation_emits_one_safe_append_without_candidate(
    tmp_path: Path,
) -> None:
    root, source, bootstrap = _repo(tmp_path)
    remote = _remote()
    new_record = _record("planned")
    new_record["canonical_id"] = "ISSUE-0180"
    new_record["title"] = "Parallel validation pilot"
    plan = sync.plan_actions(
        {"records": [_record("implemented_initially"), new_record]},
        remote,
        historical_map={},
        authority_records=[bootstrap],
    )

    candidate, ledger, manifest = prepare.prepare(
        root,
        plan,
        remote,
        source_sha=source,
        mode="create",
    )

    assert candidate is None
    records = gateway.parse_authority_ledger(ledger)
    assert len(records) == 2
    assert records[-1]["authority_type"] == "create"
    assert records[-1]["payload"]["stable_id"] == "ISSUE-0180"
    assert manifest["execution_allowed"] is False


def test_status_replay_preparation_is_deterministic_and_exactly_two_hops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, source, _bootstrap_record = _repo(tmp_path)
    bootstrap = gateway.build_authority_record(
        "legacy_bootstrap",
        {
            "legacy_issues": [
                {
                    "stable_id": "ISSUE-0179",
                    "issue_number": 179,
                    "database_id": "4179",
                    "node_id": "ISSUE_NODE_179",
                    "initial_status": "in_progress",
                }
            ]
        },
        sequence=0,
        previous_authority_id=None,
    )
    ledger = root / gateway.AUTHORITY_PATH
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap]))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "bootstrap status"], cwd=root, check=True)

    common = {
        "evidence_references": ["tests/test_status_replay.py"],
        "review_reference": "PR #replay",
        "reviewer": "reviewer",
        "reviewed_date": "2026-08-02",
        "verified_commit": "9" * 40,
        "allow_downgrade": False,
    }
    hops = [
        {"from": "in_progress", "to": "implemented_initially", **common},
        {"from": "implemented_initially", "to": "integrated", **common},
    ]
    prior = {"from": "planned", "to": "in_progress", **common}
    prior_acceptance = {
        "status": "in_progress",
        **{
            key: common[key]
            for key in (
                "evidence_references",
                "review_reference",
                "reviewer",
                "reviewed_date",
            )
        },
    }
    source_record = {
        "acceptance_evidence": [prior_acceptance],
        "dependency_edge_evidence": {},
        "phase": "phase-01-governance-scope",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "planned",
            "to": "in_progress",
            "review_reference": "PR #replay",
        },
        "transition_history": [prior],
        "verified_commit": "9" * 40,
        "verified_date": "2026-08-02",
    }
    registry_path = root / "issues/issue_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({"records": [_record("in_progress")]}), encoding="utf-8"
    )
    control_path = root / "issues/programme_control_state.json"
    control_path.write_text(
        json.dumps(_control_state(source_record, source)), encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "source status"], cwd=root, check=True)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", source],
        cwd=root,
        check=True,
    )

    record = dict(source_record)
    record.update(
        {
            "programme_status": "integrated",
            "verified_commit": "9" * 40,
            "verified_date": "2026-08-02",
            "status_transition": {
                "from": "implemented_initially",
                "to": "integrated",
                "review_reference": "PR #replay",
            },
            "transition_history": [prior, *hops],
            "acceptance_evidence": [
                prior_acceptance,
                *[
                    {
                        "status": event["to"],
                        "evidence_references": event["evidence_references"],
                        "review_reference": event["review_reference"],
                        "reviewer": event["reviewer"],
                        "reviewed_date": event["reviewed_date"],
                    }
                    for event in hops
                ],
            ],
        }
    )
    current_control = _control_state(record, source)
    registry_path.write_text(
        json.dumps({"records": [_record("integrated")]}), encoding="utf-8"
    )
    control_path.write_text(json.dumps(current_control), encoding="utf-8")
    remote = [dict(_remote()[0], body=sync.managed_block(_record("in_progress")))]
    plan = sync.plan_actions(
        {"records": [_record("integrated")]},
        remote,
        historical_map={},
        authority_records=[bootstrap],
    )

    first = prepare.prepare(root, plan, remote, source_sha=source, mode="status_replay")
    second = prepare.prepare(root, plan, remote, source_sha=source, mode="status_replay")

    assert first == second
    candidate, ledger_bytes, manifest = first
    assert candidate is not None
    assert json.loads(candidate)["schema_version"] == completion.REPLAY_SCHEMA_VERSION
    assert len(json.loads(candidate)["expected_replay"]["transition_history_append"]) == 2
    assert gateway.parse_authority_ledger(ledger_bytes)[-1]["authority_type"] == "status_replay"
    assert manifest["execution_allowed"] is False

    malformed_source = copy.deepcopy(source_record)
    malformed_source["transition_history"] = ["not-an-event"]
    malformed_current = copy.deepcopy(record)
    malformed_current["transition_history"] = ["not-an-event", *hops]
    monkeypatch.setattr(
        prepare,
        "load_control_state_at",
        lambda *_args: _control_state(malformed_source, source),
    )
    monkeypatch.setattr(
        prepare,
        "load_control_state",
        lambda *_args: _control_state(malformed_current, source),
    )
    with pytest.raises(ValueError, match="transition history"):
        prepare.prepare(root, plan, remote, source_sha=source, mode="status_replay")

    malformed_acceptance = {
        "status": "in_progress",
        "evidence_references": ["tests/test_status_replay.py"],
        "review_reference": "PR #replay source",
        "reviewer": "reviewer",
        "reviewed_date": "2026-02-30",
    }
    malformed_source = copy.deepcopy(source_record)
    malformed_source["acceptance_evidence"] = [malformed_acceptance]
    malformed_current = copy.deepcopy(record)
    malformed_current["acceptance_evidence"] = [
        malformed_acceptance,
        *record["acceptance_evidence"],
    ]
    monkeypatch.setattr(
        prepare,
        "load_control_state_at",
        lambda *_args: _control_state(malformed_source, source),
    )
    monkeypatch.setattr(
        prepare,
        "load_control_state",
        lambda *_args: _control_state(malformed_current, source),
    )
    with pytest.raises(ValueError, match="acceptance evidence prefix reviewed_date"):
        prepare.prepare(root, plan, remote, source_sha=source, mode="status_replay")

    edge_evidence = {
        "schema_version": "1.0",
        "state": "complete",
        "evidence_references": common["evidence_references"],
        "contract_reference": "tests/test_status_replay.py#dependency",
        "reviewer": "different reviewer",
        "reviewed_date": common["reviewed_date"],
    }
    prior_with_edge = {
        "from": "planned",
        "to": "in_progress",
        **common,
        "dependency_edge": {
            "dependency": "ISSUE-0001",
            "evidence": copy.deepcopy(edge_evidence),
        },
    }
    prior_acceptance = {
        "status": "in_progress",
        **{
            key: common[key]
            for key in (
                "evidence_references",
                "review_reference",
                "reviewer",
                "reviewed_date",
            )
        },
    }
    malformed_source = copy.deepcopy(source_record)
    malformed_source.update(
        {
            "transition_history": [prior_with_edge],
            "acceptance_evidence": [prior_acceptance],
            "dependency_edge_evidence": {"ISSUE-0001": edge_evidence},
        }
    )
    malformed_current = copy.deepcopy(record)
    malformed_current.update(
        {
            "transition_history": [prior_with_edge, *hops],
            "acceptance_evidence": [prior_acceptance, *record["acceptance_evidence"]],
            "dependency_edge_evidence": {"ISSUE-0001": edge_evidence},
        }
    )
    monkeypatch.setattr(
        prepare,
        "load_control_state_at",
        lambda *_args: _control_state(malformed_source, source),
    )
    monkeypatch.setattr(
        prepare,
        "load_control_state",
        lambda *_args: _control_state(malformed_current, source),
    )
    with pytest.raises(ValueError, match="dependency evidence is inconsistent"):
        prepare.prepare(root, plan, remote, source_sha=source, mode="status_replay")


def test_authoritative_control_state_fixture_has_history_and_fails_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    control = json.loads(
        (root / "issues/programme_control_state.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (root / "issues/issue_registry.json").read_text(encoding="utf-8")
    )
    registry_record = next(
        record for record in registry["records"] if record["canonical_id"] == "ISSUE-0101"
    )
    authoritative = control_state_record(control, "ISSUE-0101", context="fixture")
    assert "transition_history" not in registry_record
    assert len(authoritative["transition_history"]) >= 2
    assert authoritative["programme_status"] == "integrated"
    assert [
        (event.get("from"), event.get("to"))
        for event in authoritative["transition_history"][-2:]
    ] == [
        ("in_progress", "implemented_initially"),
        ("implemented_initially", "integrated"),
    ]
    validate_status_replay_prefix_shape(
        "ISSUE-0101",
        authoritative["transition_history"],
        authoritative["acceptance_evidence"],
        programme_status=authoritative["programme_status"],
        dependency_edge_evidence=authoritative["dependency_edge_evidence"],
        verified_commit=authoritative["verified_commit"],
        verified_date=authoritative["verified_date"],
        status_transition=authoritative["status_transition"],
    )

    malformed_edge_history = copy.deepcopy(authoritative["transition_history"])
    dependency_event = next(
        event
        for event in malformed_edge_history
        if event.get("event_type") == "dependency_edge_update"
    )
    dependency_event["dependency_edge"]["evidence"]["unexpected"] = True
    with pytest.raises(ValueError, match="dependency evidence is malformed"):
        validate_status_replay_prefix_shape(
            "ISSUE-0101",
            malformed_edge_history,
            authoritative["acceptance_evidence"],
            programme_status=authoritative["programme_status"],
            dependency_edge_evidence=authoritative["dependency_edge_evidence"],
            verified_commit=authoritative["verified_commit"],
            verified_date=authoritative["verified_date"],
            status_transition=authoritative["status_transition"],
        )

    missing = copy.deepcopy(control)
    missing["records"].pop("ISSUE-0101")
    with pytest.raises(ValueError, match="missing or ambiguous"):
        control_state_record(missing, "ISSUE-0101", context="fixture")

    malformed = copy.deepcopy(control)
    malformed["records"]["ISSUE-0101"] = []
    with pytest.raises(ValueError, match="missing or ambiguous"):
        control_state_record(malformed, "ISSUE-0101", context="fixture")


def test_status_replay_prefix_accepts_unchanged_unresolved_dependency_without_event() -> None:
    root = Path(__file__).resolve().parents[1]
    control = json.loads(
        (root / "issues/programme_control_state.json").read_text(encoding="utf-8")
    )
    authoritative = control_state_record(control, "ISSUE-0103", context="fixture")

    assert authoritative["programme_status"] == "in_progress"
    assert authoritative["dependency_edge_evidence"]["UPDATEV2-0015"]["state"] == "unresolved"
    assert all(
        event.get("dependency_edge", {}).get("dependency") != "UPDATEV2-0015"
        for event in authoritative["transition_history"]
    )
    validate_status_replay_prefix_shape(
        "ISSUE-0103",
        authoritative["transition_history"],
        authoritative["acceptance_evidence"],
        programme_status=authoritative["programme_status"],
        dependency_edge_evidence=authoritative["dependency_edge_evidence"],
        verified_commit=authoritative["verified_commit"],
        verified_date=authoritative["verified_date"],
        status_transition=authoritative["status_transition"],
    )


def test_control_state_loaders_reject_duplicate_nested_keys(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "codex@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Codex"], cwd=tmp_path, check=True
    )
    path = tmp_path / "issues/programme_control_state.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":"1.0","metadata":{"generation_base_commit":"'
        + "a" * 40
        + '"},"phase_definitions":[{"phase":"phase-01"}],'
        '"records":{"ISSUE-0101":{"programme_status":"in_progress"},'
        '"ISSUE-0101":{"programme_status":"integrated"}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate key"):
        load_control_state(tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "duplicate fixture"], cwd=tmp_path, check=True)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    with pytest.raises(ValueError, match="unavailable or malformed"):
        load_control_state_at(tmp_path, revision)


def test_control_state_revision_rejects_symbolic_ref(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full lowercase Git SHA"):
        load_control_state_at(tmp_path, "HEAD")
