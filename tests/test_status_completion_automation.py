from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts import apply_reviewed_status_completion as completion
from scripts import sync_github_issues as sync


PARENT = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40


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


def _remote(status: str = "implemented_initially") -> list[dict[str, object]]:
    record = _record(status)
    body = sync.managed_block(record)
    return [
        {
            "number": 179,
            "title": record["title"],
            "body": body,
            "state": "OPEN",
            "url": "https://example.invalid/issues/179",
        }
    ]


def _plan_and_candidate() -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    remote = _remote()
    plan = sync.plan_actions({"records": [_record()]}, remote, historical_map={})
    candidate = {
        "schema_version": completion.SCHEMA_VERSION,
        "execution_allowed": False,
        "expected_parent_sha": PARENT,
        "remote_inventory_sha256": plan["remote_inventory_sha256"],
        "plan_semantic_sha256": plan["plan_sha256"],
        "expected_update": {
            "stable_id": "ISSUE-0179",
            "from_status": "implemented_initially",
            "to_status": "integrated",
        },
    }
    return remote, plan, candidate


def test_happy_apply_uses_approved_plan_and_requires_zero_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate_path = tmp_path / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    registry = tmp_path / sync.REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"records": [_record()]}), encoding="utf-8")
    observed: list[str] = []
    monkeypatch.setattr(
        completion,
        "validate_git_bindings",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        completion.sync,
        "apply_actions",
        lambda value, *, approved_sha256: observed.append(approved_sha256)
        if value == plan
        else pytest.fail("unexpected plan"),
    )
    readbacks = iter([remote, _remote("integrated")])
    evidence_path = tmp_path / "artifacts/evidence.json"

    completion.run(
        tmp_path,
        candidate_path,
        expected_parent=PARENT,
        expected_head=HEAD,
        main_ref="origin/main",
        apply=True,
        evidence_out=evidence_path,
        remote_reader=lambda: next(readbacks),
    )

    assert observed == [plan["plan_sha256"]]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == "applied_and_verified"
    assert evidence["zero_action_readback"] is True
    assert "body" not in json.dumps(evidence).lower()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("remote_inventory_sha256", "0" * 64, "inventory"),
        ("plan_semantic_sha256", "0" * 64, "semantic"),
        ("expected_parent_sha", "0" * 40, "parent"),
    ],
)
def test_candidate_rejects_wrong_bindings(
    field: str, value: str, message: str
) -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate[field] = value

    if field == "expected_parent_sha":
        with pytest.raises(ValueError, match=message):
            completion.validate_git_bindings(
                Path("."),
                candidate,
                candidate_path=Path("."),
                expected_parent=PARENT,
                expected_head=HEAD,
                main_ref=None,
            )
    else:
        with pytest.raises(ValueError, match=message):
            completion.validate_candidate(candidate, plan, remote)


def test_premerge_accepts_synthetic_merge_and_rejects_candidate_byte_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _remote_rows, _plan, candidate = _plan_and_candidate()
    candidate_path = tmp_path / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    expected_bytes = candidate_path.read_bytes()
    monkeypatch.setattr(
        completion,
        "_git",
        lambda _root, *args: MERGE if args == ("rev-parse", "HEAD") else pytest.fail(str(args)),
    )
    monkeypatch.setattr(completion, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(
        completion.subprocess,
        "check_output",
        lambda *_args, **_kwargs: expected_bytes,
    )

    completion.validate_git_bindings(
        tmp_path,
        candidate,
        candidate_path=candidate_path,
        expected_parent=PARENT,
        expected_head=HEAD,
        main_ref=None,
    )

    monkeypatch.setattr(
        completion.subprocess,
        "check_output",
        lambda *_args, **_kwargs: b"different candidate",
    )
    with pytest.raises(ValueError, match="candidate bytes"):
        completion.validate_git_bindings(
            tmp_path,
            candidate,
            candidate_path=candidate_path,
            expected_parent=PARENT,
            expected_head=HEAD,
            main_ref=None,
        )


def test_candidate_rejects_disallowed_direct_status_transition() -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate["expected_update"]["from_status"] = "planned"  # type: ignore[index]
    remote = _remote("planned")
    plan = sync.plan_actions({"records": [_record()]}, remote, historical_map={})
    candidate["remote_inventory_sha256"] = plan["remote_inventory_sha256"]
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="canonical direct transition"):
        completion.validate_candidate(candidate, plan, remote)


def test_failure_evidence_is_privacy_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote, _plan, candidate = _plan_and_candidate()
    remote[0]["body"] = str(remote[0]["body"]) + "\nPRIVATE REMOTE BODY"
    candidate["remote_inventory_sha256"] = "0" * 64
    candidate_path = tmp_path / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    registry = tmp_path / sync.REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"records": [_record()]}), encoding="utf-8")
    evidence_path = tmp_path / "artifacts/failure.json"
    monkeypatch.setattr(completion, "validate_git_bindings", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="inventory"):
        completion.run(
            tmp_path,
            candidate_path,
            expected_parent=PARENT,
            expected_head=HEAD,
            main_ref=None,
            apply=False,
            evidence_out=evidence_path,
            remote_reader=lambda: remote,
        )

    evidence_text = evidence_path.read_text(encoding="utf-8")
    assert "PRIVATE REMOTE BODY" not in evidence_text
    assert json.loads(evidence_text)["terminal_status"] == "failed"


def test_candidate_rejects_wrong_id_and_non_status_delta() -> None:
    remote, plan, candidate = _plan_and_candidate()
    wrong_id = copy.deepcopy(candidate)
    wrong_id["expected_update"]["stable_id"] = "ISSUE-0180"  # type: ignore[index]
    with pytest.raises(ValueError, match="stable ID"):
        completion.validate_candidate(wrong_id, plan, remote)

    changed = copy.deepcopy(plan)
    changed["actions"][0]["title"] = "Changed title"
    changed["plan_sha256"] = sync.plan_sha256(changed)
    changed_candidate = copy.deepcopy(candidate)
    changed_candidate["plan_semantic_sha256"] = changed["plan_sha256"]
    with pytest.raises(ValueError, match="non-status delta"):
        completion.validate_candidate(changed_candidate, changed, remote)


@pytest.mark.parametrize("kind", ["create", "close", "reopen", "blocked"])
def test_candidate_rejects_non_update_actions(kind: str) -> None:
    remote, plan, candidate = _plan_and_candidate()
    plan["actions"][0]["kind"] = kind
    plan["summary"] = dict(completion.ZERO_SUMMARY)
    plan["summary"][kind] = 1
    plan["plan_sha256"] = sync.plan_sha256(plan)
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="exactly one update"):
        completion.validate_candidate(candidate, plan, remote)


def test_candidate_rejects_multiple_actions() -> None:
    remote, plan, candidate = _plan_and_candidate()
    plan["actions"].append(copy.deepcopy(plan["actions"][0]))
    plan["summary"]["update"] = 2
    plan["plan_sha256"] = sync.plan_sha256(plan)
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="exactly one update"):
        completion.validate_candidate(candidate, plan, remote)


def test_workflow_permissions_trigger_and_convergence_deferral() -> None:
    root = Path(__file__).resolve().parents[1]
    status_text = (root / ".github/workflows/programme-status-completion.yml").read_text(
        encoding="utf-8"
    )
    convergence = (root / ".github/workflows/programme-convergence.yml").read_text(
        encoding="utf-8"
    )
    release = (root / ".github/workflows/release-gate.yml").read_text(encoding="utf-8")
    status_workflow = yaml.safe_load(status_text)

    assert status_workflow["permissions"] == {"contents": "read", "issues": "write"}
    assert status_workflow[True]["push"]["branches"] == ["main"]
    assert status_workflow[True]["push"]["paths"] == [
        ".github/issue-transitions/post-merge-control-candidate.json"
    ]
    assert "--apply" in status_text and "--main-ref origin/main" in status_text
    assert "--evidence-out artifacts/programme-status-completion/evidence.json" in status_text
    assert "if: always()" in status_text
    assert "actions/upload-artifact@v4" in status_text
    assert "--control-candidate" not in convergence
    assert "deferring to programme-status-completion" in convergence
    assert "issues: read" in release
    assert "needs.classifier.outputs.tier == 'H'" in release
    assert "--evidence-out artifacts/validation/status-completion-candidate.json" in release
