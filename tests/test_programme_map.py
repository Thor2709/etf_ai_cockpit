from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.application.programme_map import build_programme_map, load_programme_map


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "canonical_id": "ISSUE-0015",
        "title": "Programme map",
        "phase": "phase-01-governance-scope",
        "priority": "P1",
        "classification": "current_open_retained",
        "owner": "programme-governance",
        "ledger_state": "open",
        "programme_status": "planned",
        "package_status": "Open",
        "blocking_dependencies": ["ISSUE-0001"],
        "required_inputs": ["ISSUE-0002"],
        "activation_dependencies": [],
        "downstream_issues": ["ISSUE-0003"],
        "related_issues": ["ISSUE-0004"],
        "provenance": {},
        "verified_commit": "0" * 40,
        "verified_date": "2026-08-10",
        "acceptance_evidence": [],
        "capability_lane": "CORE_ANALYSIS",
        "release_blocking": True,
        "write_conflict_group": "programme-governance",
        "risk": {},
    }
    record.update(overrides)
    if "dependency_edge_evidence" not in overrides:
        record["dependency_edge_evidence"] = {
            dependency: {
                "schema_version": "1.0",
                "state": "unresolved",
                "evidence_references": [],
                "contract_reference": "",
                "reviewer": "",
                "reviewed_date": "",
            }
            for dependency in record.get("blocking_dependencies", [])
        }
    return record


def _registry(record: dict[str, object], decision: dict[str, object]) -> dict[str, object]:
    referenced = {
        dependency
        for field in (
            "blocking_dependencies",
            "required_inputs",
            "activation_dependencies",
            "downstream_issues",
            "related_issues",
        )
        for dependency in record.get(field, [])
    }
    supporting_records = [
        _record(
            canonical_id=dependency,
            blocking_dependencies=[],
            required_inputs=[],
            activation_dependencies=[],
            downstream_issues=[],
            related_issues=[],
        )
        for dependency in sorted(referenced)
        if dependency != record["canonical_id"]
    ]
    supporting_decisions = [
        {
            "issue_id": dependency["canonical_id"],
            "ready": True,
            "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
            "edges": [],
            "required_inputs": [],
            "activation_ready": True,
            "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
            "activation_edges": [],
            "execution_allowed": False,
        }
        for dependency in supporting_records
    ]
    all_records = [record, *supporting_records]
    expected_downstream = {item["canonical_id"]: set() for item in all_records}
    for item in all_records:
        for field in ("blocking_dependencies", "required_inputs", "activation_dependencies"):
            for dependency in item.get(field, []):
                if dependency in expected_downstream:
                    expected_downstream[dependency].add(item["canonical_id"])
    for item in all_records:
        item["downstream_issues"] = sorted(expected_downstream[item["canonical_id"]])
    return {
        "policy": {"execution_allowed": False},
        "records": all_records,
        "readiness": [decision, *supporting_decisions],
        "counts": {"package_records": len(all_records), "canonical_records": len(all_records)},
        "roadmap_phases": [
            {
                "phase": "phase-01-governance-scope",
                "issue_ids": [item["canonical_id"] for item in [record, *supporting_records]],
            }
        ],
    }


def test_programme_map_keeps_implementation_release_data_and_authority_separate() -> None:
    result = build_programme_map(
        _registry(
            _record(activation_dependencies=["ISSUE-0152"]),
            {
                "issue_id": "ISSUE-0015",
                "ready": False,
                "reason_codes": ["BLOCKED_UNRESOLVED_DEPENDENCY"],
                "edges": [
                    {
                        "dependency_id": "ISSUE-0001",
                        "resolved": False,
                        "reason_code": "EDGE_UNRESOLVED",
                        "evidence_state": "unresolved",
                    }
                ],
                "required_inputs": ["ISSUE-0002"],
                "activation_ready": False,
                "activation_reason_codes": ["ACTIVATION_BLOCKED_UNRESOLVED_DEPENDENCY"],
                "activation_edges": [
                    {
                        "dependency_id": "ISSUE-0152",
                        "resolved": False,
                        "reason_code": "ACTIVATION_EDGE_UNRESOLVED",
                    }
                ],
                "execution_allowed": False,
            },
        ),
        registry_sha256="abc123",
    )

    assert result.status == "loaded"
    assert result.registry_sha256 == "abc123"
    assert result.execution_allowed is False
    entry = result.entries[0]
    assert entry.implementation == "planned"
    assert entry.release == "Open"
    assert entry.data == "required_inputs_recorded"
    assert entry.model == "not_separately_recorded"
    assert entry.paper == "disabled_by_policy"
    assert entry.live == "disabled_by_policy"
    assert entry.execution_allowed is False
    assert entry.ready is False
    assert entry.readiness_reason_codes == ("BLOCKED_UNRESOLVED_DEPENDENCY",)
    assert entry.edge_reason_codes == ("ISSUE-0001:EDGE_UNRESOLVED",)
    assert entry.activation_ready is False
    assert entry.activation_dependencies == ("ISSUE-0152",)
    assert entry.blocking_dependencies == ("ISSUE-0001",)
    assert entry.required_inputs == ("ISSUE-0002",)
    assert entry.downstream_issues == ()
    assert entry.related_issues == ("ISSUE-0004",)


def test_programme_map_loads_registry_with_content_checksum(tmp_path: Path) -> None:
    path = tmp_path / "issue_registry.json"
    path.write_text(
        json.dumps(
            _registry(
                _record(package_status="", blocking_dependencies=[]),
                {
                    "issue_id": "ISSUE-0015",
                    "ready": True,
                    "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
                    "edges": [],
                    "required_inputs": ["ISSUE-0002"],
                    "activation_ready": True,
                    "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
                    "activation_edges": [],
                    "execution_allowed": False,
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = load_programme_map(tmp_path, path)

    assert result.status == "loaded"
    assert len(result.registry_sha256) == 64
    assert result.entries[0].release == "not_recorded"
    assert result.entries[0].readiness_reason_codes == ("READY_NO_BLOCKING_DEPENDENCIES",)


def test_programme_map_fails_closed_for_malformed_registry(tmp_path: Path) -> None:
    path = tmp_path / "issue_registry.json"
    path.write_text("[]", encoding="utf-8")

    result = load_programme_map(tmp_path, path)

    assert result.status == "blocked"
    assert result.entries == ()
    assert "root is not an object" in result.error


def test_programme_map_fails_closed_for_missing_or_partial_readiness() -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    with pytest.raises(ValueError, match="complete readiness list"):
        build_programme_map(
            {
                "policy": {"execution_allowed": False},
                "records": [record],
                "counts": {"package_records": 1, "canonical_records": 1},
                "roadmap_phases": [{"phase": "phase-01-governance-scope"}],
            }
        )
    with pytest.raises(ValueError, match="partial"):
        build_programme_map(
            {
                "policy": {"execution_allowed": False},
                "counts": {"package_records": 2, "canonical_records": 2},
                "roadmap_phases": [{"phase": "phase-01-governance-scope"}],
                "records": [
                    record,
                    _record(
                        canonical_id="ISSUE-0016",
                        blocking_dependencies=[],
                        required_inputs=[],
                        downstream_issues=[],
                        related_issues=[],
                    ),
                ],
                "readiness": [
                    {
                        "issue_id": "ISSUE-0015",
                        "ready": True,
                        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
                        "edges": [],
                        "required_inputs": [],
                        "activation_ready": True,
                        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
                        "activation_edges": [],
                        "execution_allowed": False,
                    }
                ],
            }
        )


def test_programme_map_rejects_malformed_edge_and_authority_evidence() -> None:
    record = _record(blocking_dependencies=[])
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    malformed = dict(decision, edges=["not an edge"])
    with pytest.raises(ValueError):
        build_programme_map(_registry(record, malformed))
    with pytest.raises(ValueError):
        build_programme_map(_registry(record, dict(decision, execution_allowed=True)))
    with pytest.raises(ValueError):
        build_programme_map(dict(_registry(record, decision), policy={"execution_allowed": True}))


def test_programme_map_cannot_overstate_readiness_over_unresolved_edge() -> None:
    record = _record(blocking_dependencies=["ISSUE-0001"])
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [
            {
                "dependency_id": "ISSUE-0001",
                "resolved": False,
                "reason_code": "EDGE_UNRESOLVED",
                "evidence_state": "unresolved",
            }
        ],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="inconsistent"):
        build_programme_map(_registry(record, decision))


def test_programme_map_rejects_flipped_edge_and_activation_closure_evidence() -> None:
    record = _record(
        blocking_dependencies=["ISSUE-0001"],
        activation_dependencies=["ISSUE-0152"],
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_BLOCKING_EDGES_RESOLVED"],
        "edges": [
            {
                "dependency_id": "ISSUE-0001",
                "resolved": True,
                "reason_code": "EDGE_UNRESOLVED",
                "evidence_state": "unresolved",
            }
        ],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_DEPENDENCIES_RESOLVED"],
        "activation_edges": [
            {
                "dependency_id": "ISSUE-0152",
                "resolved": True,
                "reason_code": "ACTIVATION_DEPENDENCY_LEDGER_CLOSED",
            }
        ],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="inconsistent"):
        build_programme_map(_registry(record, decision))


def test_programme_map_rejects_reviewed_edge_with_malformed_date() -> None:
    evidence = {
        "schema_version": "1.0",
        "state": "complete",
        "evidence_references": ["review/evidence.json"],
        "contract_reference": "EDGE-CONTRACT-1",
        "reviewer": "independent-reviewer",
        "reviewed_date": "not-a-date",
    }
    record = _record(
        blocking_dependencies=["ISSUE-0001"],
        dependency_edge_evidence={"ISSUE-0001": evidence},
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_BLOCKING_EDGES_RESOLVED"],
        "edges": [
            {
                "dependency_id": "ISSUE-0001",
                "resolved": True,
                "reason_code": "EDGE_EVIDENCE_COMPLETE",
                "evidence_state": "complete",
            }
        ],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="edge evidence is malformed"):
        build_programme_map(_registry(record, decision))


def test_programme_map_rejects_impossible_reviewed_edge_date() -> None:
    evidence = {
        "schema_version": "1.0",
        "state": "complete",
        "evidence_references": ["review/evidence.json"],
        "contract_reference": "EDGE-CONTRACT-1",
        "reviewer": "independent-reviewer",
        "reviewed_date": "2026-02-30",
    }
    record = _record(dependency_edge_evidence={"ISSUE-0001": evidence})
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_BLOCKING_EDGES_RESOLVED"],
        "edges": [
            {
                "dependency_id": "ISSUE-0001",
                "resolved": True,
                "reason_code": "EDGE_EVIDENCE_COMPLETE",
                "evidence_state": "complete",
            }
        ],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="edge evidence is malformed"):
        build_programme_map(_registry(record, decision))


def test_programme_map_load_blocks_surrounding_whitespace_in_canonical_id(tmp_path: Path) -> None:
    path = tmp_path / "issue_registry.json"
    record = _record(canonical_id=" ISSUE-0015 ", blocking_dependencies=[])
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    path.write_text(json.dumps(_registry(record, decision)), encoding="utf-8")

    result = load_programme_map(tmp_path, path)

    assert result.status == "blocked"
    assert result.entries == ()
    assert "canonical issue ID" in result.error


@pytest.mark.parametrize("canonical_id", ["BAD-ID", "ISSUE-999"])
def test_programme_map_load_blocks_noncanonical_ids(tmp_path: Path, canonical_id: str) -> None:
    path = tmp_path / "issue_registry.json"
    record = _record(
        canonical_id=canonical_id,
        blocking_dependencies=[],
        required_inputs=[],
        downstream_issues=[],
        related_issues=[],
    )
    decision = {
        "issue_id": canonical_id,
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    path.write_text(json.dumps(_registry(record, decision)), encoding="utf-8")

    result = load_programme_map(tmp_path, path)

    assert result.status == "blocked"
    assert result.entries == ()


def test_programme_map_rejects_unknown_dependency_and_missing_edge_evidence() -> None:
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": False,
        "reason_codes": ["BLOCKED_UNRESOLVED_DEPENDENCY"],
        "edges": [
            {
                "dependency_id": "ISSUE-9999",
                "resolved": False,
                "reason_code": "EDGE_UNRESOLVED",
                "evidence_state": "unresolved",
            }
        ],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    record = _record(
        blocking_dependencies=["ISSUE-9999"],
        required_inputs=[],
        downstream_issues=[],
        related_issues=[],
        dependency_edge_evidence={},
    )
    registry = _registry(record, decision)
    registry["records"] = [record]
    registry["readiness"] = [decision]
    registry["counts"] = {"package_records": 1, "canonical_records": 1}

    with pytest.raises(ValueError, match="unknown blocking_dependencies"):
        build_programme_map(registry)

    supporting = _record(
        canonical_id="ISSUE-9999",
        blocking_dependencies=[],
        required_inputs=[],
        downstream_issues=[],
        related_issues=[],
    )
    supporting["downstream_issues"] = ["ISSUE-0015"]
    registry["records"].append(supporting)
    registry["counts"] = {"package_records": 2, "canonical_records": 2}
    registry["readiness"].append(
        {
            "issue_id": "ISSUE-9999",
            "ready": True,
            "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
            "edges": [],
            "required_inputs": [],
            "activation_ready": True,
            "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
            "activation_edges": [],
            "execution_allowed": False,
        }
    )
    with pytest.raises(ValueError, match="edge evidence is malformed"):
        build_programme_map(registry)


def test_programme_map_rejects_local_only_closure_authority() -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    registry = _registry(record, decision)
    registry["local_only_records"] = [{"canonical_id": "ISSUE-0001", "ledger_state": "closed"}]

    with pytest.raises(ValueError, match="folded into canonical records"):
        build_programme_map(registry)


@pytest.mark.parametrize(
    "field",
    [
        "blocking_dependencies",
        "required_inputs",
        "activation_dependencies",
        "downstream_issues",
        "related_issues",
    ],
)
def test_programme_map_rejects_missing_dependency_fields(field: str) -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    registry = _registry(record, decision)
    registry["records"][0].pop(field)

    with pytest.raises(ValueError, match=f"{field} is required"):
        build_programme_map(registry)


def test_programme_map_rejects_normalized_or_duplicate_dependency_references() -> None:
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": False,
        "reason_codes": ["BLOCKED_UNRESOLVED_DEPENDENCY"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    for dependencies in ([" ISSUE-0001 "], ["ISSUE-0001", "ISSUE-0001"]):
        record = _record(
            blocking_dependencies=dependencies,
            required_inputs=[],
            downstream_issues=[],
            related_issues=[],
            dependency_edge_evidence={},
        )
        with pytest.raises(ValueError):
            build_programme_map(_registry(record, decision))


def test_programme_map_rejects_missing_programme_status() -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    record.pop("programme_status")
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="programme_status"):
        build_programme_map(_registry(record, decision))


@pytest.mark.parametrize("field", ["phase", "priority"])
def test_programme_map_rejects_missing_roadmap_status_fields(field: str) -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    registry = _registry(record, decision)
    registry["records"][0].pop(field)

    with pytest.raises(ValueError, match=field):
        build_programme_map(registry)


@pytest.mark.parametrize(
    "field",
    [
        "classification",
        "owner",
        "provenance",
        "verified_commit",
        "verified_date",
        "acceptance_evidence",
        "capability_lane",
        "release_blocking",
        "write_conflict_group",
        "risk",
    ],
)
def test_programme_map_rejects_missing_required_record_fields(field: str) -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    registry = _registry(record, decision)
    registry["records"][0].pop(field)

    with pytest.raises(ValueError, match=field):
        build_programme_map(registry)


def test_programme_map_rejects_malformed_unresolved_edge_evidence() -> None:
    record = _record()
    evidence = record["dependency_edge_evidence"]["ISSUE-0001"]
    evidence["evidence_references"] = [7]
    evidence["reviewer"] = "junk"
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": False,
        "reason_codes": ["BLOCKED_UNRESOLVED_DEPENDENCY"],
        "edges": [
            {
                "dependency_id": "ISSUE-0001",
                "resolved": False,
                "reason_code": "EDGE_UNRESOLVED",
                "evidence_state": "unresolved",
            }
        ],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="edge evidence is malformed"):
        build_programme_map(_registry(record, decision))


def test_programme_map_rejects_self_reference_cycle_and_reverse_link_drift() -> None:
    base_decision = {
        "issue_id": "ISSUE-0015",
        "ready": False,
        "reason_codes": ["BLOCKED_UNRESOLVED_DEPENDENCY"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    self_record = _record(
        blocking_dependencies=["ISSUE-0015"],
        required_inputs=[],
        downstream_issues=[],
        related_issues=[],
    )
    with pytest.raises(ValueError, match="self-reference"):
        build_programme_map(_registry(self_record, base_decision))

    first = _record(
        blocking_dependencies=["ISSUE-0016"],
        required_inputs=[],
        downstream_issues=["ISSUE-0016"],
        related_issues=[],
    )
    second = _record(
        canonical_id="ISSUE-0016",
        blocking_dependencies=["ISSUE-0015"],
        required_inputs=[],
        downstream_issues=["ISSUE-0015"],
        related_issues=[],
    )
    second_decision = dict(base_decision, issue_id="ISSUE-0016")
    cycle_registry = {
        "policy": {"execution_allowed": False},
        "records": [first, second],
        "readiness": [base_decision, second_decision],
        "counts": {"package_records": 2, "canonical_records": 2},
        "roadmap_phases": [{"phase": "phase-01-governance-scope"}],
    }
    with pytest.raises(ValueError, match="cycle"):
        build_programme_map(cycle_registry)

    valid = _registry(
        _record(blocking_dependencies=["ISSUE-0016"], required_inputs=[], related_issues=[]),
        base_decision,
    )
    dependency = next(item for item in valid["records"] if item["canonical_id"] == "ISSUE-0016")
    dependency["downstream_issues"] = []
    with pytest.raises(ValueError, match="downstream links"):
        build_programme_map(valid)


def test_programme_map_rejects_jointly_truncated_registry_and_readiness() -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    registry = _registry(record, decision)
    registry["counts"] = {"package_records": 202, "canonical_records": 202}

    with pytest.raises(ValueError, match="declared record count"):
        build_programme_map(registry)


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        ('"execution_allowed": false', '"execution_allowed": true, "execution_allowed": false'),
        ('"canonical_id": "ISSUE-0015"', '"canonical_id": "ISSUE-0001", "canonical_id": "ISSUE-0015"'),
        ('"issue_id": "ISSUE-0015"', '"issue_id": "ISSUE-0001", "issue_id": "ISSUE-0015"'),
    ],
)
def test_programme_map_load_rejects_duplicate_json_keys(
    tmp_path: Path, needle: str, replacement: str
) -> None:
    record = _record(
        blocking_dependencies=[], required_inputs=[], downstream_issues=[], related_issues=[]
    )
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": [],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }
    raw = json.dumps(_registry(record, decision))
    assert needle in raw
    path = tmp_path / "issue_registry.json"
    path.write_text(raw.replace(needle, replacement, 1), encoding="utf-8")

    result = load_programme_map(tmp_path, path)

    assert result.status == "blocked"
    assert result.entries == ()
    assert "duplicate key" in result.error


def test_programme_map_rejects_missing_ledger_state() -> None:
    record = _record(blocking_dependencies=[])
    record.pop("ledger_state")
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="ledger_state must be open or closed"):
        build_programme_map(_registry(record, decision))


def test_programme_map_rejects_unknown_ledger_state() -> None:
    record = _record(blocking_dependencies=[], ledger_state="unknown")
    decision = {
        "issue_id": "ISSUE-0015",
        "ready": True,
        "reason_codes": ["READY_NO_BLOCKING_DEPENDENCIES"],
        "edges": [],
        "required_inputs": ["ISSUE-0002"],
        "activation_ready": True,
        "activation_reason_codes": ["ACTIVATION_READY_NO_DEPENDENCIES"],
        "activation_edges": [],
        "execution_allowed": False,
    }

    with pytest.raises(ValueError, match="ledger_state must be open or closed"):
        build_programme_map(_registry(record, decision))
