from __future__ import annotations

import json

from scripts import supply_chain_scan as scan


def test_supply_chain_scan_allows_pending_intake_only_for_dev_exit(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scan, "_policy", lambda root: {})
    monkeypatch.setattr(scan, "build_source_manifest", lambda *args, **kwargs: {"manifest_sha256": "fixture", "files": []})
    monkeypatch.setattr(scan, "build_sbom", lambda *args, **kwargs: {"bom_sha256": "fixture"})
    monkeypatch.setattr(scan, "licence_inventory", lambda *args, **kwargs: {"components": [], "missing_license_metadata": []})
    monkeypatch.setattr(scan, "secret_findings", lambda *args, **kwargs: [])
    monkeypatch.setattr(scan, "vulnerability_scan", lambda *args, **kwargs: {"status": "passed", "required": True})
    intake = {
        "status": "failed",
        "review_status": "pending",
        "signature_status": "missing",
        "components": [{"review_status": "hardening_required"}],
        "failures": [
            "supply-chain registry review status is not approved",
            "one or more supply-chain components are not approved",
            "detached intake signature status is missing",
        ],
    }
    monkeypatch.setattr(scan, "supply_chain_intake_report", lambda root: intake)

    report_path, exit_code = scan.write_report(tmp_path, tmp_path / "pending", allow_missing_tools=True)

    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["failures"] == [f"intake: {item}" for item in intake["failures"]]

    intake.update(
        status="failed",
        review_status="approved",
        signature_status="invalid",
        components=[{"review_status": "approved"}],
        failures=["detached intake signature status is invalid"],
    )
    _, invalid_signature_exit = scan.write_report(tmp_path, tmp_path / "invalid", allow_missing_tools=True)
    assert invalid_signature_exit == 1
