from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.governance.release_certification import (
    CERTIFICATION_SCHEMA_VERSION,
    release_certification_report,
    write_release_certification_report,
)


def _write_registry(root: Path, records: list[dict[str, object]]) -> None:
    path = root / "issues" / "issue_registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"records": records}, sort_keys=True), encoding="utf-8")


def test_release_certification_is_fail_closed_for_unresolved_programme(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        [
            {"canonical_id": "ISSUE-0149", "programme_status": "hardening_required", "priority": "P0"},
            {"canonical_id": "ISSUE-0152", "programme_status": "blocked", "priority": "P0"},
            {"canonical_id": "ISSUE-0200", "programme_status": "planned", "priority": "P2"},
        ],
    )

    report = release_certification_report(tmp_path)

    assert report["schema_version"] == CERTIFICATION_SCHEMA_VERSION
    assert report["status"] == "blocked"
    assert report["network_calls"] is False
    assert report["execution_allowed"] is False
    assert report["counts"]["unresolved_records"] == 1
    assert report["counts"]["high_priority_unresolved_records"] == 0
    assert any("canonical programme is not closed" in item for item in report["blockers"])
    assert any("signed ISSUE-0152 release manifest" in item for item in report["blockers"])
    assert any("ISSUE-0149 remains hardening_required" in item for item in report["blockers"])


def test_release_certification_fails_closed_when_registry_is_missing(tmp_path: Path) -> None:
    report = release_certification_report(tmp_path)

    assert report["status"] == "blocked"
    assert report["registry_sha256"] == "unavailable"
    assert report["checks"][0]["check_id"] == "canonical_issue_registry"


def test_release_certification_report_writes_json_and_markdown(tmp_path: Path) -> None:
    _write_registry(tmp_path, [{"canonical_id": "ISSUE-0152", "programme_status": "blocked", "priority": "P0"}])
    report = release_certification_report(tmp_path)
    json_path = tmp_path / "report" / "release-certification.json"
    markdown_path = tmp_path / "report" / "release-certification.md"

    write_release_certification_report(report, json_path, markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "blocked"
    assert "# Release certification report" in markdown_path.read_text(encoding="utf-8")
