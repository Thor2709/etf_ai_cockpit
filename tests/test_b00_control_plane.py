from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scripts import (
    generate_completion_documents,
    generate_issue_registry,
    issue_registry_core,
    release_gate,
    update_programme_control,
    update_programme_status,
    validate_app,
    validate_issue_registry,
)
from scripts.issue_registry_core import (
    build_registry,
    parse_final_release_new_issues,
    readiness_projection,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "452d44034197cd5d837c1854603eea030e02acf6"


def _registry() -> dict[str, object]:
    return build_registry(ROOT)


def _record(registry: dict[str, object], issue_id: str) -> dict[str, object]:
    return next(
        record
        for record in registry["records"]  # type: ignore[index]
        if record["canonical_id"] == issue_id
    )


def _planned_issue0154_control() -> dict[str, object]:
    control = json.loads(
        (ROOT / issue_registry_core.CONTROL_STATE_PATH).read_text(encoding="utf-8")
    )
    record = control["records"]["ISSUE-0154"]
    record["programme_status"] = "planned"
    record["status_transition"] = {
        "from": "planned",
        "review_reference": "B00 canonical import from audited programme state",
        "to": "planned",
    }
    record["acceptance_evidence"] = [
        item
        for item in record["acceptance_evidence"]
        if item.get("status") != "ready"
    ]
    record["transition_history"] = [
        item
        for item in record.get("transition_history", [])
        if not (item.get("from") == "planned" and item.get("to") == "ready")
    ]
    return control


def test_final_release_source_expands_registry_without_hard_coded_count() -> None:
    registry = _registry()
    records = registry["records"]
    assert len(records) == registry["counts"]["package_records"]  # type: ignore[index]
    source_text = (ROOT / issue_registry_core.FINAL_RELEASE_SOURCE).read_text(encoding="utf-8")
    declared_ids = {row["issue_id"] for row in parse_final_release_new_issues(source_text)}
    actual_ids = {
        record["canonical_id"]
        for record in records
        if record["source_kind"] == "final_release"
    }
    assert actual_ids == declared_ids
    assert registry["source_of_truth"]["final_release_spec_sha256"] == (  # type: ignore[index]
        "7a1d122e0bdbcb68dcd2b202a6f628f33718b2b9ae81cc2305649a7016d95810"
    )
    assert [row["id"] for row in registry["release_acceptance_matrix"]] == [  # type: ignore[index]
        f"T-{number:02d}" for number in range(1, 56)
    ]
    assert {"AnalysisSnapshot", "FundVehicle", "FundSubFund", "FundShareClass"} <= set(
        registry["core_contracts"]  # type: ignore[arg-type,index]
    )
    assert all(_record(registry, issue_id)["contract_markdown"] for issue_id in declared_ids)


def test_all_ledger_only_records_are_canonical_typed_records() -> None:
    registry = _registry()
    local = [record for record in registry["records"] if record["source_kind"] == "local"]  # type: ignore[index]
    assert len(local) == 14
    assert any(record["canonical_id"] == "ISSUE-0067" for record in local)
    assert registry["local_only_records"] == []  # type: ignore[index]
    assert registry["counts"]["canonical_records"] == len(registry["records"])  # type: ignore[index]


def test_reviewed_control_state_round_trips_and_invalid_transition_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = _planned_issue0154_control()
    record = control["records"]["ISSUE-0154"]
    record["dependency_edge_evidence"]["ISSUE-0153"] = {
        "schema_version": "1.0",
        "state": "partial_interface",
        "evidence_references": ["tests/contracts/fixed-income-interface.json"],
        "contract_reference": "B03/fixed-income-interface-v1",
        "reviewer": "independent-reviewer",
        "reviewed_date": "2026-07-21",
    }
    path = tmp_path / "programme_control_state.json"
    path.write_text(json.dumps(control), encoding="utf-8")
    monkeypatch.setattr(issue_registry_core, "CONTROL_STATE_PATH", path)
    generated = build_registry(ROOT, verify_base=False)
    assert _record(generated, "ISSUE-0154")["dependency_edge_evidence"] == record["dependency_edge_evidence"]

    record["programme_status"] = "integrated"
    path.write_text(json.dumps(control), encoding="utf-8")
    with pytest.raises(ValueError, match="transition is not allowlisted"):
        build_registry(ROOT, verify_base=False)


def test_guarded_transition_rejects_skip_downgrade_and_wrong_expected_then_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = _planned_issue0154_control()
    common = {
        "review_reference": "B00-R/transition-review",
        "evidence_references": ["tests/contracts/fixed-income-interface.json"],
        "reviewer": "independent-reviewer",
        "reviewed_date": "2026-07-21",
        "verified_commit": BASE_SHA,
    }
    with pytest.raises(ValueError, match="transition is not allowed"):
        update_programme_control.apply_transition(
            copy.deepcopy(control), issue_id="ISSUE-0154", expected_from="planned",
            to_status="integrated", **common,
        )
    with pytest.raises(ValueError, match="expected-from"):
        update_programme_control.apply_transition(
            copy.deepcopy(control), issue_id="ISSUE-0154", expected_from="ready",
            to_status="in_progress", **common,
        )
    integrated = copy.deepcopy(control)
    integrated["records"]["ISSUE-0154"]["programme_status"] = "integrated"
    with pytest.raises(ValueError, match="transition is not allowed"):
        update_programme_control.apply_transition(
            integrated, issue_id="ISSUE-0154", expected_from="integrated",
            to_status="planned", **common,
        )
    reviewed_downgrade = update_programme_control.apply_transition(
        copy.deepcopy(integrated), issue_id="ISSUE-0154", expected_from="integrated",
        to_status="planned", allow_downgrade=True, **common,
    )
    assert reviewed_downgrade["records"]["ISSUE-0154"]["transition_history"][-1]["allow_downgrade"] is True
    transitioned = update_programme_control.apply_transition(
        copy.deepcopy(control), issue_id="ISSUE-0154", expected_from="planned",
        to_status="ready", edge_dependency="ISSUE-0153", edge_state="partial_interface",
        contract_reference="B03/fixed-income-interface-v1", **common,
    )
    path = tmp_path / "control.json"
    path.write_text(json.dumps(transitioned), encoding="utf-8")
    monkeypatch.setattr(issue_registry_core, "CONTROL_STATE_PATH", path)
    generated = build_registry(ROOT, verify_base=False)
    record = _record(generated, "ISSUE-0154")
    assert record["programme_status"] == "ready"
    assert record["dependency_edge_evidence"]["ISSUE-0153"]["state"] == "partial_interface"


def test_control_authority_accepts_exact_transition_and_rejects_extra_manual_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _planned_issue0154_control()
    transitioned = update_programme_control.apply_transition(
        copy.deepcopy(prior),
        issue_id="ISSUE-0154",
        expected_from="planned",
        to_status="ready",
        review_reference="B00-R/transition-review",
        evidence_references=["tests/contracts/fixed-income-interface.json"],
        reviewer="independent-reviewer",
        reviewed_date="2026-07-21",
        verified_commit=BASE_SHA,
        edge_dependency="ISSUE-0153",
        edge_state="partial_interface",
        contract_reference="B03/fixed-income-interface-v1",
    )
    monkeypatch.setattr(
        issue_registry_core.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(prior).encode("utf-8"),
    )
    issue_registry_core.validate_control_authority(ROOT, transitioned)
    transitioned["records"]["ISSUE-0154"]["title"] = "manual unreviewed edit"
    with pytest.raises(ValueError, match="outside the reviewed transition"):
        issue_registry_core.validate_control_authority(ROOT, transitioned)


def _extension_definition(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "title": "Reviewed registry extension",
        "priority": "P1",
        "owner": "programme-governance",
        "phase": "phase-01-governance-scope",
        "blocking_dependencies": ["ISSUE-0001"],
        "required_inputs": [],
        "activation_dependencies": [],
        "related_issues": [],
        "capability_lane": "PROGRAMME_CONTROL",
        "release_blocking": True,
        "objective": "Generate the reviewed canonical intake.",
        "scope": ["Registry generation", "Programme control"],
        "exclusions": ["Broker writes"],
        "acceptance_criteria": [
            {"id": "AC-01", "text": "The canonical record is generated."}
        ],
        "validation": {"tests": ["focused registry generation"]},
        "rollback": "Remove only through a later reviewed migration.",
    }
    value.update(overrides)
    return value


def _write_extension_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    added_ids: list[str],
    definition: dict[str, object] | None = None,
) -> None:
    control = json.loads((ROOT / issue_registry_core.CONTROL_STATE_PATH).read_text(encoding="utf-8"))
    control["records"] = {
        issue_id: record
        for issue_id, record in control["records"].items()
        if "canonical_definition" not in record
    }
    issue_id = "ISSUE-0998"
    canonical_definition = definition or _extension_definition()
    control["records"][issue_id] = {
        "programme_status": "planned",
        "status_transition": {
            "from": "planned",
            "to": "planned",
            "review_reference": "reviewed canonical import",
        },
        "dependency_edge_evidence": issue_registry_core._unresolved_edge_evidence(
            canonical_definition["blocking_dependencies"]
        ),
        "acceptance_evidence": [],
        "transition_history": [],
        "verified_commit": BASE_SHA,
        "verified_date": "2026-07-28",
        "canonical_definition": canonical_definition,
    }
    control_path = tmp_path / "control.json"
    control_path.write_text(json.dumps(control), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "schema_version": "1.1",
            "registry_migration": {
                "mode": "canonical_schema_and_intake",
                "generator": "scripts/generate_issue_registry.py",
                "added_issue_ids": added_ids,
                "removed_issue_ids": [],
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(issue_registry_core, "CONTROL_STATE_PATH", control_path)
    monkeypatch.setattr(issue_registry_core, "STATUS_GUARD_MANIFEST", manifest_path)


def test_reviewed_control_extension_preserves_explicit_canonical_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_extension_inputs(tmp_path, monkeypatch, added_ids=["ISSUE-0998"])

    registry = build_registry(ROOT, verify_base=False)
    record = _record(registry, "ISSUE-0998")

    assert record["classification"] == "proposed_new"
    assert record["ledger_state"] == "open"
    assert record["programme_status"] == "planned"
    assert record["capability_lane"] == "PROGRAMME_CONTROL"
    assert record["release_blocking"] is True
    assert record["objective"] == "Generate the reviewed canonical intake."
    assert record["scope"] == ["Registry generation", "Programme control"]
    assert record["exclusions"] == ["Broker writes"]
    assert record["acceptance_criteria"] == [
        {"id": "AC-01", "text": "The canonical record is generated."}
    ]
    assert record["validation"] == {"tests": ["focused registry generation"]}
    assert record["rollback"] == "Remove only through a later reviewed migration."
    assert record["blocking_dependencies"] == ["ISSUE-0001"]
    assert record["source_kind"] == "control_extension"
    reconciliation = [
        item
        for item in registry["dependency_reconciliation"]
        if item["source_id"] == "ISSUE-0998"
    ]
    assert reconciliation == [{
        "source_id": "ISSUE-0998",
        "dependency": "ISSUE-0001",
        "candidate_type": "blocking",
        "resolved_as": "blocking_dependencies",
        "reason": "proposed programme prerequisite",
    }]


def test_persisted_control_extensions_do_not_require_reauthorisation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "unrelated-status-manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": "1.2"}), encoding="utf-8")
    monkeypatch.setattr(issue_registry_core, "STATUS_GUARD_MANIFEST", manifest_path)

    registry = build_registry(ROOT, verify_base=False)

    assert {
        record["canonical_id"]
        for record in registry["records"]
        if record["source_kind"] == "control_extension"
    } == {"ISSUE-0177", "ISSUE-0178", "ISSUE-0179", "ISSUE-0180", "ISSUE-0181"}


def test_persisted_control_extension_accepts_reviewed_lifecycle_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = json.loads((ROOT / issue_registry_core.CONTROL_STATE_PATH).read_text(encoding="utf-8"))
    control["records"]["ISSUE-0178"]["programme_status"] = "in_progress"
    control["records"]["ISSUE-0178"]["status_transition"] = {
        "from": "planned",
        "to": "in_progress",
        "review_reference": "reviewed persisted-extension lifecycle",
    }
    control_path = tmp_path / "control.json"
    control_path.write_text(json.dumps(control), encoding="utf-8")
    monkeypatch.setattr(issue_registry_core, "CONTROL_STATE_PATH", control_path)

    registry = build_registry(ROOT, verify_base=False)

    assert _record(registry, "ISSUE-0178")["programme_status"] == "in_progress"


@pytest.mark.parametrize("added_ids", [[], ["ISSUE-0997"], ["ISSUE-0998", "ISSUE-0997"]])
def test_control_extension_requires_exact_manifest_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, added_ids: list[str]
) -> None:
    _write_extension_inputs(tmp_path, monkeypatch, added_ids=added_ids)
    with pytest.raises(ValueError, match="exactly match authorised"):
        build_registry(ROOT, verify_base=False)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"priority": "P9"}, "invalid priority"),
        ({"phase": "unknown-phase"}, "unknown phase"),
        ({"blocking_dependencies": ["ISSUE-9999"]}, "unknown or self dependency"),
        ({"scope": "not-a-list"}, "scope must be a unique string list"),
        ({"acceptance_criteria": [{"id": "AC-01"}, {"id": "AC-01"}]}, "contains duplicates"),
        ({"validation": []}, "validation must be an object"),
        ({"unsupported_authority": True}, "unsupported or missing fields"),
    ],
)
def test_control_extension_rejects_invalid_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, object],
    message: str,
) -> None:
    _write_extension_inputs(
        tmp_path,
        monkeypatch,
        added_ids=["ISSUE-0998"],
        definition=_extension_definition(**override),
    )
    with pytest.raises(ValueError, match=message):
        build_registry(ROOT, verify_base=False)


def test_dependency_edge_update_keeps_status_and_acceptance_unchanged_and_replays_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = json.loads((ROOT / issue_registry_core.CONTROL_STATE_PATH).read_text(encoding="utf-8"))
    prior["records"]["ISSUE-0154"]["dependency_edge_evidence"]["ISSUE-0153"] = {
        "contract_reference": "",
        "evidence_references": [],
        "reviewed_date": "",
        "reviewer": "",
        "schema_version": "1.0",
        "state": "unresolved",
    }
    before = copy.deepcopy(prior["records"]["ISSUE-0154"])

    updated = update_programme_control.apply_dependency_edge_update(
        copy.deepcopy(prior),
        issue_id="ISSUE-0154",
        dependency_id="ISSUE-0153",
        edge_state="partial_interface",
        review_reference="B00-R/dependency-edge-review",
        evidence_references=["tests/contracts/fixed-income-interface.json"],
        contract_reference="B03/fixed-income-interface-v1",
        reviewer="independent-reviewer",
        reviewed_date="2026-07-22",
        verified_commit="ad783e517be68882934300df73106891ae6e3c05",
    )
    after = updated["records"]["ISSUE-0154"]

    assert after["programme_status"] == before["programme_status"]
    assert after["status_transition"] == before["status_transition"]
    assert after["acceptance_evidence"] == before["acceptance_evidence"]
    assert after["transition_history"][-1]["event_type"] == "dependency_edge_update"
    assert after["dependency_edge_evidence"]["ISSUE-0153"]["state"] == "partial_interface"
    monkeypatch.setattr(
        issue_registry_core.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(prior).encode("utf-8"),
    )
    issue_registry_core.validate_control_authority(
        ROOT,
        updated,
        allowed_dependency_edge_update=("ISSUE-0154", "ISSUE-0153"),
    )

    tampered = copy.deepcopy(updated)
    tampered["records"]["ISSUE-0154"]["acceptance_evidence"].append({"status": "planned"})
    with pytest.raises(ValueError, match="outside the reviewed dependency-edge update"):
        issue_registry_core.validate_control_authority(
            ROOT,
            tampered,
            allowed_dependency_edge_update=("ISSUE-0154", "ISSUE-0153"),
        )


def test_control_authority_replays_two_same_consumer_edges_from_one_immutable_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = json.loads((ROOT / issue_registry_core.CONTROL_STATE_PATH).read_text(encoding="utf-8"))
    record = prior["records"]["ISSUE-0154"]
    record["blocking_dependencies"] = ["ISSUE-0153", "ISSUE-0001"]
    record["dependency_edge_evidence"] = {
        dependency: {
            "contract_reference": "",
            "evidence_references": [],
            "reviewed_date": "",
            "reviewer": "",
            "schema_version": "1.0",
            "state": "unresolved",
        }
        for dependency in record["blocking_dependencies"]
    }
    updated = update_programme_control.apply_dependency_edge_updates(
        copy.deepcopy(prior),
        issue_id="ISSUE-0154",
        updates=[
            {
                "dependency_id": dependency,
                "edge_state": "partial_interface",
                "review_reference": f"B00-R/{dependency}",
                "evidence_references": [f"tests/contracts/{dependency}.json"],
                "contract_reference": f"contracts/{dependency}",
                "reviewer": "independent-reviewer",
                "reviewed_date": "2026-07-22",
            }
            for dependency in record["blocking_dependencies"]
        ],
        verified_commit="ad783e517be68882934300df73106891ae6e3c05",
    )

    monkeypatch.setattr(
        issue_registry_core.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(prior).encode("utf-8"),
    )

    issue_registry_core.validate_control_authority(
        ROOT,
        updated,
        allowed_dependency_edge_update=[
            ("ISSUE-0154", "ISSUE-0153"),
            ("ISSUE-0154", "ISSUE-0001"),
        ],
    )

    forged = copy.deepcopy(updated)
    forged["records"]["ISSUE-0154"]["transition_history"][-1]["dependency_edge"][
        "dependency"
    ] = "ISSUE-0002"
    with pytest.raises(ValueError):
        issue_registry_core.validate_control_authority(
            ROOT,
            forged,
            allowed_dependency_edge_update=[
                ("ISSUE-0154", "ISSUE-0153"),
                ("ISSUE-0154", "ISSUE-0001"),
            ],
        )

    metadata_drift = copy.deepcopy(updated)
    metadata_drift["metadata"]["unreviewed_operator"] = "forged"
    with pytest.raises(ValueError, match="metadata changed outside"):
        issue_registry_core.validate_control_authority(
            ROOT,
            metadata_drift,
            allowed_dependency_edge_update=("ISSUE-0154", "ISSUE-0153"),
        )

    authority_drift = copy.deepcopy(updated)
    authority_drift["execution_allowed"] = True
    with pytest.raises(ValueError, match="top-level fields changed"):
        issue_registry_core.validate_control_authority(
            ROOT,
            authority_drift,
            allowed_dependency_edge_update=("ISSUE-0154", "ISSUE-0153"),
        )

    extra_event = copy.deepcopy(updated)
    other = extra_event["records"]["ISSUE-0083"]
    dependency = "ISSUE-0082"
    edge = copy.deepcopy(other["dependency_edge_evidence"][dependency])
    other.setdefault("transition_history", []).append(
        {
            "event_type": "dependency_edge_update",
            "dependency_edge": {"dependency": dependency, "evidence": edge},
            "review_reference": edge["contract_reference"],
            "evidence_references": edge["evidence_references"],
            "reviewer": edge["reviewer"],
            "reviewed_date": edge["reviewed_date"],
            "verified_commit": other["verified_commit"],
        }
    )
    with pytest.raises(ValueError, match="must change reviewed evidence"):
        issue_registry_core.validate_control_authority(
            ROOT,
            extra_event,
            allowed_dependency_edge_update=("ISSUE-0154", "ISSUE-0153"),
        )


def test_one_merged_head_replays_distinct_lifecycle_events_to_integrated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _planned_issue0154_control()
    merged = copy.deepcopy(prior)
    commit = "ad783e517be68882934300df73106891ae6e3c05"
    for source, target in (
        ("planned", "in_progress"),
        ("in_progress", "implemented_initially"),
        ("implemented_initially", "integrated"),
    ):
        merged = update_programme_control.apply_transition(
            merged,
            issue_id="ISSUE-0154",
            expected_from=source,
            to_status=target,
            review_reference=f"post-merge/{source}-to-{target}",
            evidence_references=[f"merged-head:{commit}", "ci:protected-gate"],
            reviewer="convergence-automation-read-only",
            reviewed_date="2026-07-22",
            verified_commit=commit,
        )
    monkeypatch.setattr(
        issue_registry_core.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(prior).encode("utf-8"),
    )

    issue_registry_core.validate_control_authority(ROOT, merged)
    record = merged["records"]["ISSUE-0154"]
    assert record["programme_status"] == "integrated"
    assert [event["to"] for event in record["transition_history"][-3:]] == [
        "in_progress",
        "implemented_initially",
        "integrated",
    ]
    assert '"execution_allowed": true' not in json.dumps(merged).lower()


def _handcrafted_control_transition(
    prior: dict[str, object], issue_id: str, event: dict[str, object]
) -> dict[str, object]:
    current = copy.deepcopy(prior)
    record = current["records"][issue_id]  # type: ignore[index]
    record.setdefault("transition_history", []).append(event)
    record["programme_status"] = event.get("to")
    record["status_transition"] = {
        "from": event.get("from"),
        "to": event.get("to"),
        "review_reference": event.get("review_reference"),
    }
    record["verified_commit"] = event.get("verified_commit")
    record["verified_date"] = event.get("reviewed_date")
    record.setdefault("acceptance_evidence", []).append({
        "status": event.get("to"),
        "evidence_references": event.get("evidence_references"),
        "review_reference": event.get("review_reference"),
        "reviewer": event.get("reviewer"),
        "reviewed_date": event.get("reviewed_date"),
    })
    edge_change = event.get("dependency_edge")
    if isinstance(edge_change, dict) and isinstance(edge_change.get("dependency"), str):
        record["dependency_edge_evidence"][edge_change["dependency"]] = edge_change.get("evidence")
    return current


@pytest.mark.parametrize(
    ("case", "issue_id", "expected_error"),
    [
        ("skip", "ISSUE-0010", "transition is not allowed"),
        ("unreviewed_downgrade", "ISSUE-0071", "transition is not allowed"),
        ("invalid_date", "ISSUE-0010", "valid YYYY-MM-DD"),
        ("invalid_commit", "ISSUE-0010", "full lowercase Git SHA"),
        ("missing_reviewer", "ISSUE-0010", "requires reviewer"),
        ("missing_evidence", "ISSUE-0010", "requires non-blank evidence"),
        ("malformed_edge", "ISSUE-0071", "unsupported edge evidence schema"),
    ],
)
def test_registry_entrypoint_rejects_handcrafted_invalid_transition_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    issue_id: str,
    expected_error: str,
) -> None:
    prior = json.loads((ROOT / issue_registry_core.CONTROL_STATE_PATH).read_text(encoding="utf-8"))
    skip_targets = {
        "planned": "implemented_initially",
        "ready": "implemented_initially",
        "in_progress": "integrated",
        "implemented_initially": "closed",
    }
    if case == "skip":
        issue_id = next(
            candidate
            for candidate, record in sorted(prior["records"].items())
            if record["programme_status"] in skip_targets
        )
    source = prior["records"][issue_id]["programme_status"]
    if case == "skip":
        assert skip_targets[source] not in issue_registry_core.CONTROL_ALLOWED_TRANSITIONS.get(
            source, frozenset()
        )
    legal_target = {
        "planned": "ready",
        "ready": "in_progress",
        "in_progress": "implemented_initially",
        "implemented_initially": "integrated",
        "integrated": "closed",
    }[source]
    event: dict[str, object] = {
        "from": source,
        "to": legal_target,
        "review_reference": "B00-R/adversarial-review",
        "evidence_references": ["tests/contracts/adversarial.json"],
        "reviewer": "independent-reviewer",
        "reviewed_date": "2026-07-21",
        "verified_commit": BASE_SHA,
        "allow_downgrade": False,
    }
    if case == "skip":
        event["to"] = skip_targets[source]
    elif case == "unreviewed_downgrade":
        event["to"] = "planned"
    elif case == "invalid_date":
        event["reviewed_date"] = "2026-99-99"
    elif case == "invalid_commit":
        event["verified_commit"] = "not-a-commit"
    elif case == "missing_reviewer":
        del event["reviewer"]
    elif case == "missing_evidence":
        event["evidence_references"] = []
    elif case == "malformed_edge":
        event["dependency_edge"] = {
            "dependency": "ISSUE-0070",
            "evidence": {
                "schema_version": "forged",
                "state": "complete",
                "evidence_references": event["evidence_references"],
                "contract_reference": "B00-R/contract",
                "reviewer": event["reviewer"],
                "reviewed_date": event["reviewed_date"],
            },
        }
    current = _handcrafted_control_transition(prior, issue_id, event)
    path = tmp_path / "control.json"
    path.write_text(json.dumps(current), encoding="utf-8")
    monkeypatch.setattr(issue_registry_core, "CONTROL_STATE_PATH", path)

    def authoritative(command, *args, **kwargs):
        if list(command[:2]) == ["git", "rev-parse"]:
            return prior["metadata"]["generation_base_commit"] + "\n"
        return json.dumps(prior).encode("utf-8")

    monkeypatch.setattr(issue_registry_core.subprocess, "check_output", authoritative)
    with pytest.raises(ValueError, match=expected_error):
        build_registry(ROOT)
    assert generate_issue_registry.main(["--root", str(ROOT), "--check"]) == 1
    assert validate_issue_registry.main(["--root", str(ROOT)]) == 1


def test_unreachable_generation_base_fails_every_canonical_check(monkeypatch: pytest.MonkeyPatch) -> None:
    real = issue_registry_core.subprocess.check_output

    def stale(command, *args, **kwargs):
        if list(command[:3]) == ["git", "merge-base", "--is-ancestor"]:
            raise subprocess.CalledProcessError(1, command)
        return real(command, *args, **kwargs)

    monkeypatch.setattr(issue_registry_core.subprocess, "check_output", stale)
    assert generate_issue_registry.main(["--root", str(ROOT), "--check"]) == 1
    assert validate_issue_registry.main(["--root", str(ROOT)]) == 1
    assert generate_completion_documents.main(["--root", str(ROOT), "--check"]) == 1
    assert update_programme_status.main(["--root", str(ROOT), "--check"]) == 1


def test_generation_base_remains_valid_after_two_consecutive_main_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def reachable(command, *args, **kwargs):
        calls.append(tuple(command))
        return ""

    monkeypatch.setattr(issue_registry_core.subprocess, "check_output", reachable)
    control = issue_registry_core.load_control_state(ROOT)
    issue_registry_core.verify_generation_base(ROOT, control)
    issue_registry_core.verify_generation_base(ROOT, control)

    expected = control["metadata"]["generation_base_commit"]
    assert calls == [
        ("git", "merge-base", "--is-ancestor", expected, "origin/main"),
        ("git", "merge-base", "--is-ancestor", expected, "origin/main"),
    ]


def test_every_record_has_typed_final_release_contract_fields() -> None:
    registry = _registry()
    for record in registry["records"]:  # type: ignore[index]
        assert isinstance(record["activation_dependencies"], list)
        assert isinstance(record["dependency_edge_evidence"], dict)
        assert set(record["dependency_edge_evidence"]) == set(record["blocking_dependencies"])
        assert isinstance(record["provenance"], dict)
        assert re.fullmatch(r"[0-9a-f]{40}", record["verified_commit"])
        assert date.fromisoformat(record["verified_date"]).isoformat() == record["verified_date"]
        assert isinstance(record["acceptance_evidence"], list)
        assert isinstance(record["capability_lane"], str) and record["capability_lane"]
        assert isinstance(record["release_blocking"], bool)
        assert isinstance(record["write_conflict_group"], str) and record["write_conflict_group"]
        assert record["risk"]["level"] in {"normal", "medium", "high"}


@pytest.mark.parametrize(
    "status",
    ["planned", "ready", "implemented_initially", "integrated", "hardening_required", "closed"],
)
def test_programme_status_cannot_resolve_an_unresolved_blocking_edge(status: str) -> None:
    registry = _registry()
    consumer = _record(registry, "ISSUE-0154")
    dependency = _record(registry, "ISSUE-0153")
    dependency["ledger_state"] = "open"
    dependency["programme_status"] = status
    consumer["dependency_edge_evidence"]["ISSUE-0153"]["state"] = "unresolved"  # type: ignore[index]

    decision = next(
        item for item in readiness_projection(registry) if item["issue_id"] == "ISSUE-0154"
    )

    assert decision["ready"] is False
    assert decision["reason_codes"] == ["BLOCKED_UNRESOLVED_DEPENDENCY"]
    edge = next(
        item for item in decision["edges"] if item["dependency_id"] == "ISSUE-0153"
    )
    assert edge["reason_code"] == "EDGE_UNRESOLVED"


@pytest.mark.parametrize("state", ["complete", "partial_interface", "waived"])
def test_reviewed_edge_specific_evidence_resolves_only_that_edge(state: str) -> None:
    registry = _registry()
    consumer = _record(registry, "ISSUE-0154")
    consumer["blocking_dependencies"] = ["ISSUE-0153"]
    consumer["dependency_edge_evidence"] = {
        "ISSUE-0153": {
            "schema_version": "1.0",
            "state": state,
            "evidence_references": ["tests/contracts/fixed-income-terms.json"],
            "contract_reference": "B03-FIXED-INCOME/terms-v1",
            "reviewer": "independent-reviewer",
            "reviewed_date": "2026-07-21",
        }
    }

    decision = next(
        item for item in readiness_projection(registry) if item["issue_id"] == "ISSUE-0154"
    )

    assert decision["ready"] is True
    assert decision["edges"][0]["reason_code"] == f"EDGE_EVIDENCE_{state.upper()}"


def test_invalid_or_non_declared_edge_evidence_fails_registry_validation() -> None:
    registry = _registry()
    invalid = copy.deepcopy(registry)
    consumer = _record(invalid, "ISSUE-0154")
    consumer["dependency_edge_evidence"]["ISSUE-0007"] = {  # type: ignore[index]
        "schema_version": "1.0",
        "state": "complete",
        "evidence_references": [],
        "contract_reference": "",
        "reviewer": "",
        "reviewed_date": "",
    }

    errors = validate_registry(invalid, open_ids=set(), closed_ids=set())

    assert any("evidence for non-declared blocking edge ISSUE-0007" in error for error in errors)


def test_missing_duplicate_and_cyclic_records_fail_deterministically() -> None:
    registry = _registry()
    missing = copy.deepcopy(registry)
    missing["records"].pop()  # type: ignore[union-attr]
    assert any(
        "source-derived package record count mismatch" in error
        for error in validate_registry(missing, open_ids=set(), closed_ids=set())
    )

    duplicate = copy.deepcopy(registry)
    duplicate["records"].append(copy.deepcopy(duplicate["records"][0]))  # type: ignore[index,union-attr]
    assert "canonical IDs are not unique" in validate_registry(
        duplicate, open_ids=set(), closed_ids=set()
    )

    cyclic = copy.deepcopy(registry)
    first = _record(cyclic, "ISSUE-0153")
    second = _record(cyclic, "ISSUE-0154")
    first["blocking_dependencies"] = ["ISSUE-0154"]
    first["dependency_edge_evidence"] = {
        "ISSUE-0154": {
            "schema_version": "1.0",
            "state": "unresolved",
            "evidence_references": [],
            "contract_reference": "",
            "reviewer": "",
            "reviewed_date": "",
        }
    }
    second["blocking_dependencies"] = ["ISSUE-0153"]
    assert any(
        "blocking dependency cycle" in error
        for error in validate_registry(cyclic, open_ids=set(), closed_ids=set())
    )


def test_required_inputs_do_not_block_and_activation_is_reported_separately() -> None:
    registry = _registry()
    issue = _record(registry, "ISSUE-0070")
    assert issue["required_inputs"]
    issue["blocking_dependencies"] = []
    issue["dependency_edge_evidence"] = {}
    issue["activation_dependencies"] = ["ISSUE-0152"]

    decision = next(
        item for item in readiness_projection(registry) if item["issue_id"] == "ISSUE-0070"
    )

    assert decision["ready"] is True
    assert decision["activation_ready"] is False
    assert decision["activation_reason_codes"] == ["ACTIVATION_BLOCKED_UNRESOLVED_DEPENDENCY"]
    assert registry["policy"]["execution_allowed"] is False  # type: ignore[index]


def test_checked_in_registry_remains_deterministic_json() -> None:
    checked_in = json.loads((ROOT / "issues" / "issue_registry.json").read_text(encoding="utf-8"))
    assert checked_in["policy"]["execution_allowed"] is False
    readiness = json.loads(
        (ROOT / "docs" / "product-completion" / "programme" / "readiness.json").read_text(
            encoding="utf-8"
        )
    )
    assert readiness["decisions"] == checked_in["readiness"]
    assert readiness["execution_allowed"] is False
    assert "<!-- BEGIN GENERATED FINAL RELEASE PROGRAMME -->" in (
        ROOT / "README.md"
    ).read_text(encoding="utf-8")
    assert "<!-- BEGIN GENERATED FINAL RELEASE ISSUES -->" in (
        ROOT / "issues" / "open.md"
    ).read_text(encoding="utf-8")


def test_committed_sync_files_are_safe_evidence_not_apply_plans() -> None:
    recon = ROOT / "docs" / "product-completion" / "reconciliation" / "2026-07-21-452d440"
    first_path = recon / "github-sync-evidence.json"
    second_path = recon / "github-sync-evidence-repeat.json"
    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))
    assert first == second
    assert first["schema_version"] == "etf-ai-cockpit.safe-sync-evidence/1.0"
    assert first["summary"] == {"blocked": 0, "close": 0, "create": 24, "reopen": 0, "update": 173}
    updates = [action for action in first["actions"] if action["kind"] == "update"]
    assert len(updates) == 173 and all(action["managed_field_deltas"] for action in updates)
    assert all("body" not in action for action in first["actions"])
    for path in (first_path, second_path):
        digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        assert (path.with_suffix(path.suffix + ".sha256")).read_text(encoding="utf-8").split()[0] == digest


def test_validator_modes_compose_existing_release_gate_without_reimplementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert validate_app.REPORT_DIRECTORY == Path("artifacts/validation")
    full = validate_app._checks_for_mode(ROOT, "full", {})
    packaged = validate_app._checks_for_mode(ROOT, "packaged", {})
    offline = validate_app._checks_for_mode(ROOT, "offline", {})
    monkeypatch.setattr(validate_app, "_changed_test_paths", lambda _root: ["tests/test_sample.py"])
    changed = validate_app._checks_for_mode(ROOT, "changed", {})

    assert full[0].name == "protected_release_gate"
    assert "scripts/release_gate.py" in full[0].command
    assert packaged[0].name == "packaged_release_gate"
    assert "--skip-tests" not in packaged[0].command
    smoke = next(check for check in offline if check.name == "source_smoke")
    assert dict(smoke.environment) == {"ETF_COCKPIT_OFFLINE": "1"}
    changed_tests = next(check for check in changed if check.name == "changed_tests")
    assert changed_tests.timeout_seconds == validate_app.CHANGED_TEST_TIMEOUT_SECONDS == 360


def test_package_parity_detects_mismatch(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "configs").mkdir()
    (tmp_path / "src" / "sample.py").write_text("source\n", encoding="utf-8")
    (tmp_path / "configs" / "sample.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    package = tmp_path / "package"
    (package / "src").mkdir(parents=True)
    (package / "configs").mkdir()
    (package / "src" / "sample.py").write_text("different\n", encoding="utf-8")
    (package / "configs" / "sample.json").write_text("{}\n", encoding="utf-8")
    (package / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    result = release_gate.source_package_parity(
        tmp_path,
        release_gate.PreparedPackage(package, "sdist", package / "scripts" / "smoke_app.py"),
    )
    assert result.status == "failed"
    assert "src/sample.py" in result.failure


def test_completion_document_check_is_offline_and_fresh() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/generate_completion_documents.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "FRESH" in completed.stdout


def test_registry_generation_is_identical_for_lf_and_crlf_text_inputs(tmp_path: Path) -> None:
    lf = tmp_path / "lf"
    crlf = tmp_path / "crlf"
    for target in (lf, crlf):
        shutil.copytree(ROOT / "issues", target / "issues")
        shutil.copytree(
            ROOT / "docs" / "product-completion" / "sources",
            target / "docs" / "product-completion" / "sources",
        )
        manifest_target = target / issue_registry_core.STATUS_GUARD_MANIFEST
        manifest_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / issue_registry_core.STATUS_GUARD_MANIFEST, manifest_target)
    exact = issue_registry_core.FINAL_RELEASE_SOURCE.as_posix()
    for path in crlf.rglob("*"):
        relative = path.relative_to(crlf).as_posix()
        if not path.is_file() or relative == exact:
            continue
        if path.suffix.lower() in {".json", ".csv", ".md", ".sha256", ".txt"}:
            payload = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            path.write_bytes(payload.replace(b"\n", b"\r\n"))
    lf_registry = build_registry(lf, verify_base=False)
    crlf_registry = build_registry(crlf, verify_base=False)
    assert issue_registry_core.deterministic_json(lf_registry) == issue_registry_core.deterministic_json(crlf_registry)


def test_report_only_never_converts_a_mandatory_failure_to_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = validate_app._Check(
        "mandatory_failure",
        (__import__("sys").executable, "-c", "raise SystemExit(7)"),
    )
    monkeypatch.setattr(validate_app, "_checks_for_mode", lambda *_args: [failure])

    result = validate_app.run_validation(
        ROOT,
        mode="quick",
        report_root=tmp_path,
        report_only=True,
    )

    assert result.exit_code == 1
    assert result.report.report_only is True
    assert result.report.failures == ["mandatory_failure: exit code 7"]
