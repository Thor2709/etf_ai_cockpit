from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import supply_chain_scan


def test_secret_scan_reports_credential_like_source_content(tmp_path: Path) -> None:
    source = tmp_path / "settings.py"
    key_name = "api" + "_key"
    value = "not-a-real-but-credential-shaped-value"
    source.write_text(f'{key_name} = "{value}"\n', encoding="utf-8")

    findings = supply_chain_scan.secret_findings(
        tmp_path,
        {"files": [{"path": "settings.py"}]},
    )

    assert findings and findings[0]["path"] == "settings.py"


def test_vulnerability_scan_blocks_unapproved_findings(monkeypatch, tmp_path: Path) -> None:
    policy = {"dependency_lock": "requirements-release.txt", "approved_mitigations": []}
    completed = subprocess.CompletedProcess(
        args=["pip-audit"],
        returncode=1,
        stdout=json.dumps([{"id": "CVE-TEST-0001", "fix_versions": ["9.9.9"]}]),
        stderr="",
    )
    monkeypatch.setattr(supply_chain_scan.subprocess, "run", lambda *args, **kwargs: completed)

    result = supply_chain_scan.vulnerability_scan(tmp_path, policy, allow_missing_tools=False)

    assert result["status"] == "failed"
    assert result["blocking_vulnerabilities"] == [{"id": "CVE-TEST-0001", "fix_versions": ["9.9.9"]}]


def test_vulnerability_scan_allows_only_explicit_mitigation(monkeypatch, tmp_path: Path) -> None:
    policy = {"dependency_lock": "requirements-release.txt", "approved_mitigations": [{"id": "CVE-TEST-0001", "reason": "temporary vendor hold"}]}
    completed = subprocess.CompletedProcess(
        args=["pip-audit"],
        returncode=1,
        stdout=json.dumps([{"id": "CVE-TEST-0001"}]),
        stderr="",
    )
    monkeypatch.setattr(supply_chain_scan.subprocess, "run", lambda *args, **kwargs: completed)

    result = supply_chain_scan.vulnerability_scan(tmp_path, policy, allow_missing_tools=False)

    assert result["status"] == "passed"
    assert result["blocking_vulnerabilities"] == []
    assert result["approved_mitigations"] == [{"id": "CVE-TEST-0001"}]


def test_vulnerability_scan_does_not_treat_clean_dependency_rows_as_findings(monkeypatch, tmp_path: Path) -> None:
    policy = {"dependency_lock": "requirements-release.txt", "approved_mitigations": []}
    completed = subprocess.CompletedProcess(
        args=["pip-audit"],
        returncode=0,
        stdout=json.dumps([{"name": "pytest", "version": "9.1.1", "vulns": []}]),
        stderr="",
    )
    monkeypatch.setattr(supply_chain_scan.subprocess, "run", lambda *args, **kwargs: completed)

    result = supply_chain_scan.vulnerability_scan(tmp_path, policy, allow_missing_tools=False)

    assert result["status"] == "passed"
    assert result["vulnerabilities"] == []


def test_vulnerability_scan_can_report_missing_tool_in_local_diagnostic_mode(monkeypatch, tmp_path: Path) -> None:
    policy = {"dependency_lock": "requirements-release.txt", "approved_mitigations": []}
    completed = subprocess.CompletedProcess(args=["pip-audit"], returncode=1, stdout="", stderr="No module named pip_audit")
    monkeypatch.setattr(supply_chain_scan.subprocess, "run", lambda *args, **kwargs: completed)

    result = supply_chain_scan.vulnerability_scan(tmp_path, policy, allow_missing_tools=True)

    assert result["status"] == "unavailable"
    assert result["required"] is False


def test_settings_page_exposes_update_verification_and_notices() -> None:
    from etf_cockpit.app.pages.settings import settings_page

    source = __import__("inspect").getsource(settings_page)
    assert "settings.update-verification" in source
    assert "settings.update-version" in source
    assert "settings.third-party-notices" in source
