from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import validation_summary
from scripts.validation_summary import validate_summary


def _summary(tier: str) -> dict:
    package = tier in {"H", "C"}
    return {
        "schema_version": "validation-summary.v1",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "tier": tier,
        "package_gate_required": package,
        "reason": ["protected-control"] if package else ["exact-evidence"],
        "jobs": {
            "classifier": "required",
            "preflight": "required",
            "supply_chain": "required",
            "release_windows": "required" if package else "skipped",
            "release_linux": "required" if package else "skipped",
        },
        "platform_junit": {"windows": 4, "linux": 4} if package else {},
        "artifacts": [
            {"path": "classifier.json", "sha256": "c" * 64, "present": True},
            *(
                [
                    {"path": "release-windows/junit.xml", "sha256": "e" * 64, "present": True},
                    {"path": "release-linux/junit.xml", "sha256": "f" * 64, "present": True},
                ]
                if package
                else []
            ),
        ],
        "job_results": {
            "classifier": "success",
            "preflight": "success",
            "supply_chain": "success",
            "release": "success" if package else "skipped",
        },
        "identities": {key: "d" * 64 for key in ("environment", "source", "dependency", "product_tree", "policy")},
        "controls": {
            "guards_passed": True,
            "freshness_passed": True,
            "evidence_reuse_authorized": tier == "E",
            "automation_authority": "read-only",
            "apply_authority": False,
        },
    }


def test_e_and_h_terminal_summary_fixtures() -> None:
    assert validate_summary(_summary("E")) == []
    assert validate_summary(_summary("H")) == []


def test_terminal_summary_rejects_missing_and_forged_artifacts() -> None:
    missing = _summary("H")
    missing["platform_junit"].pop("windows")
    assert "terminal summary platform JUnit counts are required" in validate_summary(missing)
    forged = copy.deepcopy(_summary("E"))
    forged["artifacts"][0]["sha256"] = "forged"
    assert "terminal summary artifact presence/hashes are incomplete" in validate_summary(forged)
    absent_results = _summary("E")
    absent_results.pop("job_results")
    assert "terminal summary job results are inconsistent" in validate_summary(absent_results)


def test_terminal_collection_preserves_platform_artifact_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = tmp_path / "validation-evidence"
    classifier = artifacts / "validation-classifier-head" / "classifier.json"
    classifier.parent.mkdir(parents=True)
    classifier.write_text(
        json.dumps(
            {
                "tier": "H",
                "package_gate_required": True,
                "reasons": ["protected-control"],
                "paths": [
                    {
                        "path": "scripts/validation_summary.py",
                        "tier": "H",
                        "reason": "protected-or-high-risk-surface",
                    }
                ],
                "evidence_reuse": {"authorized": False},
            }
        ),
        encoding="utf-8",
    )
    for platform in ("linux", "windows"):
        junit = artifacts / f"release-gate-head-{platform}" / "junit-full.xml"
        junit.parent.mkdir(parents=True)
        junit.write_text(
            '<testsuites><testsuite tests="3" /></testsuites>\n',
            encoding="utf-8",
        )
    preflight = artifacts / "validation-preflight-head" / "junit-affected.xml"
    preflight.parent.mkdir(parents=True)
    preflight.write_text('<testsuite tests="126" />\n', encoding="utf-8")
    monkeypatch.setattr(validation_summary, "_tree_identity", lambda *_args: "d" * 64)

    report = validation_summary.collect_summary(
        tmp_path,
        artifacts,
        base="a" * 40,
        head="b" * 40,
        job_results={
            "classifier": "success",
            "preflight": "success",
            "supply_chain": "success",
            "release": "success",
        },
    )

    assert report["platform_junit"] == {"windows": 3, "linux": 3}
    assert validate_summary(report) == []


def _candidate_evidence() -> dict[str, object]:
    return {
        "schema_version": "etf-ai-cockpit.status-completion-evidence/1.0",
        "execution_allowed": False,
        "mode": "validate",
        "expected_parent_sha": "a" * 40,
        "expected_head_sha": "b" * 40,
        "authority_ref": "1" * 64,
        "remote_inventory_sha256": "c" * 64,
        "plan_semantic_sha256": "d" * 64,
        "candidate_blob_sha256": "e" * 64,
        "expected_update": {
            "stable_id": "ISSUE-0179",
            "from_status": "implemented_initially",
            "to_status": "integrated",
        },
        "action_scope": [
            {
                "kind": "update",
                "stable_id": "ISSUE-0179",
                "remote_number": 582,
                "managed_field_deltas": ["Programme status"],
            }
        ],
        "mutation": {
            "transport": "github_issue_comment_append",
            "authority_id": "2" * 64,
            "predecessor_event_id": "legacy:ISSUE-0179",
            "predecessor_event_sha256": "f" * 64,
            "candidate_blob_sha256": "e" * 64,
            "candidate_blob_oid": "3" * 40,
            "plan_sha256": "d" * 64,
        },
        "terminal_status": "validated",
        "zero_action_readback": None,
    }


def _candidate_artifacts(tmp_path: Path) -> Path:
    artifacts = tmp_path / "validation-evidence"
    classifier = artifacts / "validation-classifier-head" / "classifier.json"
    classifier.parent.mkdir(parents=True)
    classifier.write_text(
        json.dumps(
            {
                "tier": "E",
                "package_gate_required": False,
                "reasons": ["allowlisted-semantic-event-or-projection"],
                "paths": [
                    {
                        "path": ".github/issue-transitions/post-merge-control-candidate.json",
                        "tier": "E",
                        "reason": "allowlisted-semantic-event-or-projection",
                    }
                ],
                "evidence_reuse": {"authorized": True},
            }
        ),
        encoding="utf-8",
    )
    return artifacts


def _collect_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    monkeypatch.setattr(validation_summary, "_tree_identity", lambda *_args: "e" * 64)
    monkeypatch.setattr(
        validation_summary,
        "_committed_candidate_blob_sha256",
        lambda *_args: "e" * 64,
    )
    evidence = _candidate_evidence()
    monkeypatch.setattr(
        validation_summary,
        "_load_committed_candidate",
        lambda *_args: candidate
        or {
            key: evidence[key]
            for key in (
                "execution_allowed",
                "expected_parent_sha",
                "authority_ref",
                "remote_inventory_sha256",
                "plan_semantic_sha256",
                "expected_update",
            )
        },
    )
    return validation_summary.collect_summary(
        tmp_path,
        tmp_path / "validation-evidence",
        base="a" * 40,
        head="b" * 40,
        job_results={
            "classifier": "success",
            "preflight": "success",
            "supply_chain": "success",
            "release": "skipped",
        },
    )


def test_candidate_change_requires_valid_terminal_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    evidence = (
        artifacts
        / "validation-status-completion-candidate-head"
        / "status-completion-candidate.json"
    )
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps(_candidate_evidence()), encoding="utf-8")

    report = _collect_candidate(tmp_path, monkeypatch)

    assert validate_summary(report) == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda evidence: evidence.update(schema_version="wrong"), "schema mismatch"),
        (lambda evidence: evidence.update(terminal_status="failed"), "not terminally validated"),
        (lambda evidence: evidence.update(expected_parent_sha="f" * 40), "base SHA mismatch"),
        (lambda evidence: evidence.update(expected_head_sha="f" * 40), "head SHA mismatch"),
        (lambda evidence: evidence.update(plan_semantic_sha256="bad"), "semantic plan identity mismatch"),
        (lambda evidence: evidence.update(expected_update={}), "expected update identity mismatch"),
        (lambda evidence: evidence.pop("mutation"), "comment event identity is invalid"),
    ],
)
def test_candidate_change_rejects_invalid_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    message: str,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    payload = _candidate_evidence()
    mutation(payload)
    evidence = (
        artifacts
        / "validation-status-completion-candidate-head"
        / "status-completion-candidate.json"
    )
    evidence.parent.mkdir()
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        _collect_candidate(tmp_path, monkeypatch)


def test_candidate_change_rejects_missing_duplicate_and_malformed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        _collect_candidate(tmp_path, monkeypatch)

    first = (
        artifacts
        / "validation-status-completion-candidate-head-a"
        / "status-completion-candidate.json"
    )
    second = (
        artifacts
        / "validation-status-completion-candidate-head-b"
        / "status-completion-candidate.json"
    )
    first.parent.mkdir()
    second.parent.mkdir()
    payload = json.dumps(_candidate_evidence())
    first.write_text(payload, encoding="utf-8")
    second.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        _collect_candidate(tmp_path, monkeypatch)

    second.unlink()
    first.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        _collect_candidate(tmp_path, monkeypatch)


def test_candidate_unchanged_does_not_require_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    classifier = artifacts / "validation-classifier-head" / "classifier.json"
    payload = json.loads(classifier.read_text(encoding="utf-8"))
    payload["paths"] = [
        {
            "path": "docs/product-completion/PROGRESS.md",
            "tier": "E",
            "reason": "allowlisted-semantic-event-or-projection",
        }
    ]
    classifier.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_summary(_collect_candidate(tmp_path, monkeypatch)) == []


def test_candidate_evidence_rejects_wrong_artifact_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    evidence = artifacts / "validation-preflight-head" / "status-completion-candidate.json"
    evidence.parent.mkdir()
    evidence.write_text(json.dumps(_candidate_evidence()), encoding="utf-8")

    with pytest.raises(ValueError, match="provenance is invalid"):
        _collect_candidate(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "mutation",
    [
        "reversed",
        "dependency",
        "commit_mismatch",
        "prefix_mismatch",
        "wrong_source_status",
        "wrong_final_status",
        "unrelated_head_field",
    ],
)
def test_replay_candidate_summary_rejects_unsafe_contract(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    common = {
        "evidence_references": ["tests/replay.py"],
        "review_reference": "PR #633",
        "reviewer": "reviewer",
        "reviewed_date": "2026-08-02",
        "verified_commit": "9" * 40,
        "allow_downgrade": False,
    }
    prior = {"from": "planned", "to": "in_progress", **common}
    hops = [
        {"from": "in_progress", "to": "implemented_initially", **common},
        {"from": "implemented_initially", "to": "integrated", **common},
    ]
    prior_acceptance = {
        "status": "in_progress",
        **{key: common[key] for key in (
            "evidence_references", "review_reference", "reviewer", "reviewed_date"
        )},
    }
    acceptances = [
        {
            "status": hop["to"],
            **{key: hop[key] for key in (
                "evidence_references", "review_reference", "reviewer", "reviewed_date"
            )},
        }
        for hop in hops
    ]
    valid_hops = copy.deepcopy(hops)
    valid_acceptances = copy.deepcopy(acceptances)
    replay = {
        "stable_id": "ISSUE-0179",
        "issue_number": 179,
        "from_status": "in_progress",
        "to_status": "integrated",
        "reviewed_product_commit": "9" * 40,
        "transition_history_prefix": [prior],
        "transition_history_append": hops,
        "acceptance_evidence_prefix": [prior_acceptance],
        "acceptance_evidence_append": acceptances,
    }
    candidate = {
        "schema_version": validation_summary.CANDIDATE_REPLAY_SCHEMA,
        "execution_allowed": False,
        "expected_parent_sha": "a" * 40,
        "authority_ref": "a" * 64,
        "remote_inventory_sha256": "b" * 64,
        "plan_semantic_sha256": "c" * 64,
        "expected_replay": replay,
    }
    evidence = {
        **copy.deepcopy(candidate),
        "mode": "validate",
        "expected_head_sha": "b" * 40,
        "terminal_status": "validated",
        "zero_action_readback": None,
        "candidate_blob_sha256": "e" * 64,
        "action_scope": [{
            "kind": "update",
            "stable_id": "ISSUE-0179",
            "remote_number": 179,
            "managed_field_deltas": ["Programme status"],
        }],
        "mutation": {
            "transport": "github_issue_comment_append",
            "transport_contract": "one_aggregate_proposal_one_receipt",
            "replay_hops": copy.deepcopy(hops),
            "reviewed_product_commit": "9" * 40,
            "candidate_blob_sha256": "e" * 64,
            "plan_sha256": "c" * 64,
            "authority_id": "f" * 64,
            "candidate_blob_oid": "d" * 40,
        },
    }
    if mutation == "reversed":
        candidate["expected_replay"]["transition_history_append"].reverse()
        evidence["expected_replay"] = copy.deepcopy(candidate["expected_replay"])
    elif mutation == "dependency":
        candidate["expected_replay"]["transition_history_append"][0][
            "dependency_edge"
        ] = {"dependency": "ISSUE-0001", "evidence": {}}
        evidence["expected_replay"] = copy.deepcopy(candidate["expected_replay"])
    elif mutation == "commit_mismatch":
        candidate["expected_replay"]["reviewed_product_commit"] = "8" * 40
        evidence["expected_replay"] = copy.deepcopy(candidate["expected_replay"])
    else:
        candidate["expected_replay"]["transition_history_prefix"] = []
        evidence["expected_replay"] = copy.deepcopy(candidate["expected_replay"])
    monkeypatch.setattr(
        validation_summary, "_committed_candidate_blob_sha256", lambda *_a: "e" * 64
    )
    source = {
        "canonical_id": "ISSUE-0179",
        "programme_status": "in_progress",
        "transition_history": [prior],
        "acceptance_evidence": [prior_acceptance],
    }
    from scripts.apply_reviewed_status_completion import project_status_replay_record

    current = project_status_replay_record(source, valid_hops, valid_acceptances)
    if mutation == "wrong_source_status":
        source["programme_status"] = "blocked"
    elif mutation == "wrong_final_status":
        current["programme_status"] = "closed"
    elif mutation == "unrelated_head_field":
        current["owner"] = "unreviewed-owner"
    monkeypatch.setattr(
        validation_summary,
        "_registry_record_at",
        lambda _root, ref, _stable_id: source if ref == "a" * 40 else current,
    )

    with pytest.raises(ValueError, match=r"status[ _]replay"):
        validation_summary._validate_replay_candidate_evidence(
            evidence,
            candidate,
            root=Path("."),
            base="a" * 40,
            head="b" * 40,
        )


@pytest.mark.parametrize(
    "field",
    [
        "execution_allowed",
        "expected_parent_sha",
        "authority_ref",
        "remote_inventory_sha256",
        "plan_semantic_sha256",
        "expected_update",
    ],
)
def test_candidate_evidence_must_equal_committed_candidate_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    evidence_payload = _candidate_evidence()
    evidence = (
        artifacts
        / "validation-status-completion-candidate-head"
        / "status-completion-candidate.json"
    )
    evidence.parent.mkdir()
    evidence.write_text(json.dumps(evidence_payload), encoding="utf-8")
    candidate = {
        key: copy.deepcopy(evidence_payload[key])
        for key in (
            "execution_allowed",
            "expected_parent_sha",
            "authority_ref",
            "remote_inventory_sha256",
            "plan_semantic_sha256",
            "expected_update",
        )
    }
    candidate[field] = "different"

    with pytest.raises(ValueError, match="identity mismatch"):
        _collect_candidate(tmp_path, monkeypatch, candidate=candidate)


@pytest.mark.parametrize(
    "paths",
    [
        None,
        "not-a-list",
        [],
        [{}],
        [{"path": ".github/issue-transitions/post-merge-control-candidate.json"}],
        [
            {
                "path": ".github/issue-transitions/post-merge-control-candidate.json",
                "tier": "E",
                "reason": "allowlisted",
            },
            {
                "path": ".github/issue-transitions/post-merge-control-candidate.json",
                "tier": "E",
                "reason": "allowlisted",
            },
        ],
        [
            {
                "path": "docs/product-completion/PROGRESS.md",
                "tier": "E",
                "reason": "allowlisted",
            },
            {
                "path": "docs/product-completion/PROGRESS.md",
                "tier": "E",
                "reason": "allowlisted",
            },
        ],
        [
            {
                "path": "docs/product-completion/PROGRESS.md",
                "tier": "invalid",
                "reason": "allowlisted",
            }
        ],
        [
            {
                "path": "docs/product-completion/PROGRESS.md",
                "tier": "E",
                "reason": "",
            }
        ],
    ],
)
def test_classifier_paths_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paths: object,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    classifier = artifacts / "validation-classifier-head" / "classifier.json"
    payload = json.loads(classifier.read_text(encoding="utf-8"))
    if paths is None:
        payload.pop("paths")
    else:
        payload["paths"] = paths
    classifier.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="classifier"):
        _collect_candidate(tmp_path, monkeypatch)


def test_updatev2_candidate_identity_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _candidate_artifacts(tmp_path)
    payload = _candidate_evidence()
    payload["expected_update"] = {
        "stable_id": "UPDATEV2-0001",
        "from_status": "implemented_initially",
        "to_status": "integrated",
    }
    payload["action_scope"][0]["stable_id"] = "UPDATEV2-0001"  # type: ignore[index]
    evidence = (
        artifacts
        / "validation-status-completion-candidate-head"
        / "status-completion-candidate.json"
    )
    evidence.parent.mkdir()
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    candidate = {
        key: copy.deepcopy(payload[key])
        for key in (
            "execution_allowed",
            "expected_parent_sha",
            "authority_ref",
            "remote_inventory_sha256",
            "plan_semantic_sha256",
            "expected_update",
        )
    }

    assert validate_summary(
        _collect_candidate(tmp_path, monkeypatch, candidate=candidate)
    ) == []


def test_workflow_keeps_artifact_names_and_writes_failed_terminal_evidence() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-gate.yml"
    ).read_text(encoding="utf-8")

    assert "merge-multiple: true" not in workflow
    assert "head_sha: ${{ steps.classify.outputs.head_sha }}" in workflow
    assert "HEAD_SHA: ${{ needs.classifier.outputs.head_sha }}" in workflow
    build_step = workflow.index("- name: Build and validate authoritative terminal evidence")
    assert "if: always()" in workflow[build_step : build_step + 120]
