from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from scripts.validate_completion_package import EXPECTED_MEMBERS, validate_package


def _package_bytes(*, unsafe_name: str | None = None, malformed_json: bool = False,
                   new_ids: tuple[str, ...] = ("ISSUE-0070",),
                   new_markdown_title: str | None = None,
                   secret_text: str = "") -> dict[str, bytes]:
    current = {
        "issue_id": "ISSUE-0007",
        "title": "Current issue",
        "status": "Open",
        "priority": "P2",
        "current_gap": "gap",
        "required_change": "change",
        "why": "why",
        "dependencies": "",
        "completion_evidence": "evidence",
        "free_no_quota_policy": "local",
    }
    proposed = [
        {
            "issue_id": issue_id,
            "title": f"New issue {issue_id}",
            "epic": "Foundation",
            "priority": "P0",
            "evidence_grade": "High",
            "problem": "problem",
            "why": "why",
            "implementation": "implementation",
            "data_and_dependencies": "dependencies",
            "acceptance_criteria": "acceptance",
            "tests_required": "tests",
            "ui_requirement": "none",
            "security_and_audit": "audit",
            "dependencies": "",
            "free_no_quota_policy": "local",
        }
        for issue_id in new_ids
    ]

    def csv_bytes(rows: list[dict[str, str]]) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8")

    current_csv = csv_bytes([current])
    proposed_csv = csv_bytes(proposed)
    registry = {
        "schema_version": "1.0",
        "generated_at": "2026-07-15",
        "repository": "Thor2709/etf_ai_cockpit",
        "reviewed_commit": "e149db50945401fb014955f0f79794a909796a75",
        "current_open_issue_count": 1,
        "new_issue_count": len(proposed),
        "combined_completion_programme_count": len(proposed) + 1,
        "policy": {"mandatory_core": "local", "optional_providers": "optional", "execution": "disabled"},
        "current_open_issues": [current],
        "proposed_new_issues": proposed,
        "sources": [],
    }
    current_title = "Current issue"
    proposed_lines = [f"## {row['issue_id']} — {row['title']}" for row in proposed]
    if new_markdown_title is not None:
        proposed_lines[0] = f"## {proposed[0]['issue_id']} — {new_markdown_title}"
    members = {
        "ETF_AI_Cockpit_Completion_Blueprint.md": b"# Blueprint\n" + secret_text.encode(),
        "ETF_AI_Cockpit_Completion_Programme_Index.md": ("# Index\n" + "\n".join(proposed_lines) + "\n").encode(),
        "ETF_AI_Cockpit_Current_Open_Issues_Audit.md": f"# Audit\n## ISSUE-0007 — {current_title}\n".encode(),
        "ETF_AI_Cockpit_Current_Open_Issues_Audit.csv": current_csv,
        "ETF_AI_Cockpit_New_Issues_Ready_To_Append.md": ("# New\n" + "\n".join(proposed_lines) + "\n").encode(),
        "ETF_AI_Cockpit_New_Issues.csv": proposed_csv,
        "ETF_AI_Cockpit_Master_Issue_Registry.json": (
            b"not json" if malformed_json else json.dumps(registry).encode("utf-8")
        ),
        "ETF_AI_Cockpit_Research_Sources.md": b"# Sources\n",
        "ETF_AI_Cockpit_Research_Sources.csv": b"category,name,url,use,quality\n",
    }
    if unsafe_name:
        members[unsafe_name] = b"unsafe"
    return members


def _write_package(tmp_path: Path, members: dict[str, bytes]) -> Path:
    path = tmp_path / "package.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


def test_valid_package_is_parsed_and_cross_checked(tmp_path: Path) -> None:
    path = _write_package(tmp_path, _package_bytes())

    report = validate_package(path, expected_counts=(1, 1))

    assert report.errors == []
    assert report.current_open_issue_count == 1
    assert report.new_issue_count == 1
    assert set(report.member_hashes) == EXPECTED_MEMBERS


def test_rejects_unsafe_zip_entry_before_extraction(tmp_path: Path) -> None:
    path = _write_package(tmp_path, _package_bytes(unsafe_name="../evil.txt"))

    report = validate_package(path, expected_counts=(1, 1))

    assert any("unsafe" in error for error in report.errors)


def test_rejects_malformed_json(tmp_path: Path) -> None:
    path = _write_package(tmp_path, _package_bytes(malformed_json=True))

    report = validate_package(path, expected_counts=(1, 1))

    assert any("JSON" in error for error in report.errors)


def test_reports_count_and_new_id_continuity_mismatch(tmp_path: Path) -> None:
    path = _write_package(tmp_path, _package_bytes(new_ids=("ISSUE-0070", "ISSUE-0072")))

    report = validate_package(path, expected_counts=(1, 2))

    assert any("continuous" in error for error in report.errors)


def test_reports_member_hash_mismatch(tmp_path: Path) -> None:
    path = _write_package(tmp_path, _package_bytes())
    expected = {name: "0" * 64 for name in EXPECTED_MEMBERS}

    report = validate_package(path, expected_counts=(1, 1), expected_member_hashes=expected)

    assert any("hash mismatch" in error for error in report.errors)


def test_reports_markdown_csv_json_disagreement(tmp_path: Path) -> None:
    path = _write_package(tmp_path, _package_bytes(new_markdown_title="Wrong title"))

    report = validate_package(path, expected_counts=(1, 1))

    assert any("title mismatch" in error for error in report.errors)


def test_reports_common_credential_patterns(tmp_path: Path) -> None:
    key_name = "API" + "_KEY"
    path = _write_package(tmp_path, _package_bytes(secret_text=f'{key_name} = "abcdefghijklmnopqrstuvwxyz"\n'))

    report = validate_package(path, expected_counts=(1, 1))

    assert any("secret pattern" in error for error in report.errors)
