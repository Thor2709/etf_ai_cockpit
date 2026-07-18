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
    result = build_programme_map({"records": [_record()]}, registry_sha256="abc123")

    assert result.status == "loaded"
    assert result.registry_sha256 == "abc123"
    entry = result.entries[0]
    assert entry.implementation == "planned"
    assert entry.release == "Open"
    assert entry.data == "required_inputs_recorded"
    assert entry.model == "not_separately_recorded"
    assert entry.paper == "disabled_by_policy"
    assert entry.live == "disabled_by_policy"
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


def test_programme_map_fails_closed_for_malformed_registry(tmp_path: Path) -> None:
    path = tmp_path / "issue_registry.json"
    path.write_text("[]", encoding="utf-8")

    result = load_programme_map(tmp_path, path)

    assert result.status == "blocked"
    assert result.entries == ()
    assert "root is not an object" in result.error
