from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.issue_registry_core import (
    build_registry,
    readiness_projection,
    validate_registry,
)
from scripts import validate_app


ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "452d44034197cd5d837c1854603eea030e02acf6"


def _registry() -> dict[str, object]:
    return build_registry(ROOT, baseline=BASE_SHA)


def _record(registry: dict[str, object], issue_id: str) -> dict[str, object]:
    return next(
        record
        for record in registry["records"]  # type: ignore[index]
        if record["canonical_id"] == issue_id
    )


def test_final_release_source_expands_registry_without_hard_coded_count() -> None:
    registry = _registry()
    records = registry["records"]
    assert len(records) == registry["counts"]["package_records"]  # type: ignore[index]
    assert {_record(registry, f"ISSUE-{number:04d}")["canonical_id"] for number in range(153, 177)} == {
        f"ISSUE-{number:04d}" for number in range(153, 177)
    }
    assert registry["source_of_truth"]["final_release_spec_sha256"] == (  # type: ignore[index]
        "7a1d122e0bdbcb68dcd2b202a6f628f33718b2b9ae81cc2305649a7016d95810"
    )
    assert [row["id"] for row in registry["release_acceptance_matrix"]] == [  # type: ignore[index]
        f"T-{number:02d}" for number in range(1, 56)
    ]
    assert {"AnalysisSnapshot", "FundVehicle", "FundSubFund", "FundShareClass"} <= set(
        registry["core_contracts"]  # type: ignore[arg-type,index]
    )
    assert all(
        _record(registry, f"ISSUE-{number:04d}")["contract_markdown"]
        for number in range(153, 177)
    )


def test_every_record_has_typed_final_release_contract_fields() -> None:
    registry = _registry()
    for record in registry["records"]:  # type: ignore[index]
        assert isinstance(record["activation_dependencies"], list)
        assert isinstance(record["dependency_edge_evidence"], dict)
        assert set(record["dependency_edge_evidence"]) == set(record["blocking_dependencies"])
        assert isinstance(record["provenance"], dict)
        assert record["verified_commit"] == BASE_SHA
        assert record["verified_date"] == "2026-07-21"
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
    assert decision["edges"][0]["reason_code"] == "EDGE_UNRESOLVED"


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


def test_validator_modes_compose_existing_release_gate_without_reimplementation() -> None:
    full = validate_app._checks_for_mode(ROOT, "full", {})
    packaged = validate_app._checks_for_mode(ROOT, "packaged", {})
    offline = validate_app._checks_for_mode(ROOT, "offline", {})

    assert full[0].name == "protected_release_gate"
    assert "scripts/release_gate.py" in full[0].command
    assert packaged[0].name == "packaged_release_gate"
    assert "--skip-tests" in packaged[0].command
    smoke = next(check for check in offline if check.name == "source_smoke")
    assert dict(smoke.environment) == {"ETF_COCKPIT_OFFLINE": "1"}


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
