from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.governance.supply_chain_intake import (
    load_supply_chain_intake,
    sign_supply_chain_registry,
    supply_chain_intake_report,
    write_supply_chain_intake_report,
)


def test_supply_chain_intake_registry_has_explicit_boundaries() -> None:
    registry = load_supply_chain_intake()

    assert registry["schema_version"] == "supply-chain-intake.v1"
    assert registry["policy"]["copied_code_requires_approved_record"] is True
    assert registry["policy"]["dependency_preferred_over_copying"] is True
    assert registry["components"][0]["copied_files"] == []
    assert registry["components"][-1]["copied_files"]
    assert all(row["licence_class"] in registry["policy"]["allowed_licence_classes"] for row in registry["components"])
    assert all(row["integration_boundary"] in registry["policy"]["allowed_boundaries"] for row in registry["components"])


def test_supply_chain_intake_report_is_local_and_traceable() -> None:
    report = supply_chain_intake_report(Path.cwd())

    assert report["schema_version"] == "supply-chain-intake.v1"
    assert report["network_calls"] is False
    assert report["execution_allowed"] is False
    assert report["registry_sha256"]
    assert report["third_party_notices"] == "packaging/THIRD_PARTY_NOTICES.md"
    assert report["dependency_count"] > 0
    assert report["review_status"] == "hardening_required"
    assert report["signature_status"] in {"missing", "unverifiable"}
    assert all("licence_class" in row for row in report["dependencies"])


def test_supply_chain_intake_report_writes_machine_and_human_evidence(tmp_path: Path) -> None:
    report = supply_chain_intake_report(Path.cwd())
    json_path = tmp_path / "supply-chain-intake.json"
    markdown_path = tmp_path / "supply-chain-intake.md"

    write_supply_chain_intake_report(report, json_path, markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["network_calls"] is False
    assert "# Supply-chain intake report" in markdown_path.read_text(encoding="utf-8")


def test_supply_chain_intake_signature_is_detached_and_keyed() -> None:
    signature = sign_supply_chain_registry("a" * 64, b"local-test-key-1234", key_id="test")

    assert signature["status"] == "signed"
    assert signature["algorithm"] == "HMAC-SHA256"
    assert signature["key_id"] == "test"
    assert "local-test-key" not in json.dumps(signature)
