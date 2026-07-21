from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.application.programme_map import build_programme_map, load_programme_map


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "canonical_id": "ISSUE-0015",
        "title": "Programme map",
        "phase": "phase-01-governance-scope",
        "priority": "P1",
        "programme_status": "planned",
        "package_status": "Open",
        "blocking_dependencies": ["ISSUE-0001"],
        "required_inputs": ["ISSUE-0002"],
        "downstream_issues": ["ISSUE-0003"],
        "related_issues": ["ISSUE-0004"],
    }
    record.update(overrides)
    return record


def test_programme_map_keeps_implementation_release_data_and_authority_separate() -> None:
    result = build_programme_map(
        {
            "records": [_record(activation_dependencies=["ISSUE-0152"])],
            "readiness": [
                {
                    "issue_id": "ISSUE-0015",
                    "ready": False,
                    "reason_codes": ["BLOCKED_UNRESOLVED_DEPENDENCY"],
                    "edges": [
                        {
                            "dependency_id": "ISSUE-0001",
                            "reason_code": "EDGE_UNRESOLVED",
                        }
                    ],
                    "activation_ready": False,
                    "activation_reason_codes": ["ACTIVATION_BLOCKED_UNRESOLVED_DEPENDENCY"],
                }
            ],
        },
        registry_sha256="abc123",
    )

    assert result.status == "loaded"
    assert result.registry_sha256 == "abc123"
    entry = result.entries[0]
    assert entry.implementation == "planned"
    assert entry.release == "Open"
    assert entry.data == "required_inputs_recorded"
    assert entry.model == "not_separately_recorded"
    assert entry.paper == "disabled_by_policy"
    assert entry.live == "disabled_by_policy"
    assert entry.ready is False
    assert entry.readiness_reason_codes == ("BLOCKED_UNRESOLVED_DEPENDENCY",)
    assert entry.edge_reason_codes == ("ISSUE-0001:EDGE_UNRESOLVED",)
    assert entry.activation_ready is False
    assert entry.activation_dependencies == ("ISSUE-0152",)
    assert entry.blocking_dependencies == ("ISSUE-0001",)
    assert entry.required_inputs == ("ISSUE-0002",)
    assert entry.downstream_issues == ("ISSUE-0003",)
    assert entry.related_issues == ("ISSUE-0004",)


def test_programme_map_loads_registry_with_content_checksum(tmp_path: Path) -> None:
    path = tmp_path / "issue_registry.json"
    path.write_text(json.dumps({"records": [_record(package_status="")]}) + "\n", encoding="utf-8")

    result = load_programme_map(tmp_path, path)

    assert result.status == "loaded"
    assert len(result.registry_sha256) == 64
    assert result.entries[0].release == "not_recorded"
    assert result.entries[0].readiness_reason_codes == ("READINESS_EVIDENCE_UNAVAILABLE",)


def test_programme_map_fails_closed_for_malformed_registry(tmp_path: Path) -> None:
    path = tmp_path / "issue_registry.json"
    path.write_text("[]", encoding="utf-8")

    result = load_programme_map(tmp_path, path)

    assert result.status == "blocked"
    assert result.entries == ()
    assert "root is not an object" in result.error
