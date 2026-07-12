from __future__ import annotations

import json
from pathlib import Path

from scripts.sync_github_issues import (
    MANAGED_END,
    MANAGED_START,
    MARKER_TEMPLATE,
    local_records,
    managed_body,
    merge_managed_body,
    normalise_body,
    remote_matches,
)


ROOT = Path(__file__).resolve().parents[2]


def test_local_issue_inventory_has_unique_stable_ids_and_source_checksums() -> None:
    payload = json.loads((ROOT / "issues" / "github_issue_map.json").read_text(encoding="utf-8"))
    records, contradictions = local_records(payload)

    assert len(records) == 98
    assert len({record["local_issue_id"] for record in records}) == len(records)
    assert {record["local_state"] for record in records} == {"open", "closed"}
    assert all(len(record["source_checksum"]) == 64 for record in records)
    assert isinstance(contradictions, list)


def test_managed_issue_body_contains_authority_marker_and_selected_state() -> None:
    payload = json.loads((ROOT / "issues" / "github_issue_map.json").read_text(encoding="utf-8"))
    record = local_records(payload)[0][0]

    body = managed_body(record)

    assert MARKER_TEMPLATE.format(issue_id=record["local_issue_id"]) in body
    assert MANAGED_START in body
    assert MANAGED_END in body
    assert "must not be closed independently" in body
    assert f"Local state: `{record['local_state']}`" in body


def test_managed_body_update_preserves_unmanaged_human_discussion() -> None:
    payload = json.loads((ROOT / "issues" / "github_issue_map.json").read_text(encoding="utf-8"))
    record = local_records(payload)[0][0]
    managed = managed_body(record)

    merged = merge_managed_body("Human discussion retained.", managed)

    assert merged.startswith("Human discussion retained.")
    assert managed in merged


def test_managed_body_update_removes_stale_duplicate_marker() -> None:
    payload = json.loads((ROOT / "issues" / "github_issue_map.json").read_text(encoding="utf-8"))
    record = local_records(payload)[0][0]
    managed = managed_body(record)
    marker = MARKER_TEMPLATE.format(issue_id=record["local_issue_id"])

    merged = merge_managed_body(f"{marker}\n\n{managed}\n\n{marker}", managed)

    assert merged == managed


def test_remote_duplicate_stable_markers_are_reported_without_guessing() -> None:
    remote = [
        {"number": 1, "title": "[ISSUE-0001] first", "body": "<!-- etf-ai-cockpit-local-issue-id: ISSUE-0001 -->"},
        {"number": 2, "title": "[ISSUE-0001] duplicate", "body": "<!-- etf-ai-cockpit-local-issue-id: ISSUE-0001 -->"},
    ]

    by_id, duplicates = remote_matches(remote)

    assert by_id["ISSUE-0001"]["number"] == 1
    assert duplicates == [
        {
            "local_issue_id": "ISSUE-0001",
            "issue_number": 2,
            "canonical_issue_number": 1,
            "reason": "duplicate_remote_match",
        }
    ]


def test_closed_duplicate_marker_is_resolved_without_relying_on_comment_body() -> None:
    remote = [
        {"number": 1, "title": "[ISSUE-0001] first", "state": "OPEN", "body": "<!-- etf-ai-cockpit-local-issue-id: ISSUE-0001 -->"},
        {"number": 2, "title": "[ISSUE-0001] duplicate", "state": "CLOSED", "body": "<!-- etf-ai-cockpit-local-issue-id: ISSUE-0001 -->"},
    ]

    by_id, duplicates = remote_matches(remote)

    assert by_id["ISSUE-0001"]["number"] == 1
    assert duplicates == []


def test_body_comparison_is_stable_across_github_newline_normalisation() -> None:
    assert normalise_body("line one\r\nline two\r\n") == "line one\nline two"
