from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import apply_reviewed_status_completion as completion
from scripts import issue_registry_core as core
from scripts import prepare_github_mutation_authority as preparation
from scripts import validation_summary as summary


EXPECTED_LEGACY_BOOTSTRAP_RECORDS = {
    "ISSUE-0011": {
        "acceptance_evidence": [],
        "dependency_edge_evidence": {},
        "phase": "phase-08-frontend-api",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "in_progress",
            "review_reference": "B00 canonical import from audited programme state",
            "to": "in_progress",
        },
        "verified_commit": "452d44034197cd5d837c1854603eea030e02acf6",
        "verified_date": "2026-07-21",
    },
    "ISSUE-0012": {
        "acceptance_evidence": [],
        "dependency_edge_evidence": {},
        "phase": "phase-01-governance-scope",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "in_progress",
            "review_reference": "B00 canonical import from audited programme state",
            "to": "in_progress",
        },
        "verified_commit": "452d44034197cd5d837c1854603eea030e02acf6",
        "verified_date": "2026-07-21",
    },
    "ISSUE-0014": {
        "acceptance_evidence": [],
        "dependency_edge_evidence": {},
        "phase": "phase-01-governance-scope",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "in_progress",
            "review_reference": "B00 canonical import from audited programme state",
            "to": "in_progress",
        },
        "verified_commit": "452d44034197cd5d837c1854603eea030e02acf6",
        "verified_date": "2026-07-21",
    },
    "ISSUE-0039": {
        "acceptance_evidence": [],
        "dependency_edge_evidence": {},
        "phase": "phase-01-governance-scope",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "in_progress",
            "review_reference": "B00 canonical import from audited programme state",
            "to": "in_progress",
        },
        "verified_commit": "452d44034197cd5d837c1854603eea030e02acf6",
        "verified_date": "2026-07-21",
    },
    "ISSUE-0040": {
        "acceptance_evidence": [],
        "dependency_edge_evidence": {},
        "phase": "phase-01-governance-scope",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "in_progress",
            "review_reference": "B00 canonical import from audited programme state",
            "to": "in_progress",
        },
        "verified_commit": "452d44034197cd5d837c1854603eea030e02acf6",
        "verified_date": "2026-07-21",
    },
    "ISSUE-0045": {
        "acceptance_evidence": [],
        "dependency_edge_evidence": {},
        "phase": "phase-08-frontend-api",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "in_progress",
            "review_reference": "B00 canonical import from audited programme state",
            "to": "in_progress",
        },
        "verified_commit": "452d44034197cd5d837c1854603eea030e02acf6",
        "verified_date": "2026-07-21",
    },
    "UPDATEV2-0027": {
        "acceptance_evidence": [],
        "dependency_edge_evidence": {},
        "phase": "phase-08-frontend-api",
        "programme_status": "in_progress",
        "status_transition": {
            "from": "in_progress",
            "review_reference": "B00 canonical import from audited programme state",
            "to": "in_progress",
        },
        "verified_commit": "452d44034197cd5d837c1854603eea030e02acf6",
        "verified_date": "2026-07-21",
    },
}


@pytest.fixture(autouse=True)
def allowlist_matches_audited_records() -> None:
    assert core.LEGACY_BOOTSTRAP_RECORDS == EXPECTED_LEGACY_BOOTSTRAP_RECORDS


def _validate_prefix(issue_id: str, record: dict[str, object], *, history: object = None) -> None:
    core.validate_status_replay_prefix_shape(
        issue_id,
        history,
        record["acceptance_evidence"],
        programme_status=record["programme_status"],
        dependency_edge_evidence=record["dependency_edge_evidence"],
        verified_commit=record["verified_commit"],
        verified_date=record["verified_date"],
        status_transition=record["status_transition"],
        allow_legacy_bootstrap_origin=True,
        phase=record["phase"],
    )


def test_b1_records_are_recognised_and_prefix_validates() -> None:
    for issue_id in ("ISSUE-0039", "ISSUE-0040"):
        record = deepcopy(EXPECTED_LEGACY_BOOTSTRAP_RECORDS[issue_id])

        assert core.is_issue0011_legacy_replay_source(issue_id, record)
        _validate_prefix(issue_id, record)
        _validate_prefix(issue_id, record, history=[])


def test_b2_records_are_recognised_and_prefix_validates() -> None:
    for issue_id in ("ISSUE-0045", "UPDATEV2-0027"):
        record = deepcopy(EXPECTED_LEGACY_BOOTSTRAP_RECORDS[issue_id])

        assert core.is_issue0011_legacy_replay_source(issue_id, record)
        _validate_prefix(issue_id, record)
        _validate_prefix(issue_id, record, history=[])


def _assert_control_state_record_matches_allowance(
    issue_id: str, record: dict[str, object]
) -> None:
    legacy_record = core.LEGACY_BOOTSTRAP_RECORDS[issue_id]
    if record == legacy_record:
        assert core.is_issue0011_legacy_replay_source(issue_id, record)
        _validate_prefix(issue_id, record)
        return

    assert not core.is_issue0011_legacy_replay_source(issue_id, record)
    legacy_status_order = core.CONTROL_STATUS_ORDER[legacy_record["programme_status"]]
    record_status_order = core.CONTROL_STATUS_ORDER.get(str(record.get("programme_status")))
    assert record_status_order is not None and record_status_order > legacy_status_order, (
        f"{issue_id} must have a later lifecycle status than its legacy bootstrap record"
    )
    assert record.get("status_transition") != legacy_record["status_transition"], (
        f"{issue_id} must retain its replay status transition"
    )


def test_control_state_records_are_recognised_by_allowance() -> None:
    control_state = json.loads(
        Path("issues/programme_control_state.json").read_text(encoding="utf-8")
    )
    for issue_id in (
        "ISSUE-0039",
        "ISSUE-0040",
        "ISSUE-0045",
        "UPDATEV2-0027",
    ):
        record = control_state["records"][issue_id]
        if issue_id in ("ISSUE-0045", "UPDATEV2-0027"):
            assert "transition_history" not in record
        _assert_control_state_record_matches_allowance(
            issue_id, record
        )


def test_single_field_mutations_are_rejected_for_all_records() -> None:
    mutations = (
        ("acceptance_evidence", [{"status": "integrated"}]),
        ("dependency_edge_evidence", {"ISSUE-0001": {}}),
        ("programme_status", "ready"),
        ("status_transition", None),
        ("verified_commit", "0" * 40),
        ("verified_date", "2026-07-22"),
    )
    for issue_id, expected in EXPECTED_LEGACY_BOOTSTRAP_RECORDS.items():
        wrong_phase = (
            "phase-01-governance-scope"
            if expected["phase"] != "phase-01-governance-scope"
            else "phase-08-frontend-api"
        )
        for field, value in (*mutations, ("phase", wrong_phase)):
            record = deepcopy(expected)
            record[field] = value
            assert not core.is_issue0011_legacy_replay_source(issue_id, record)
            with pytest.raises(ValueError, match="legacy bootstrap replay prefix"):
                _validate_prefix(issue_id, record)


def test_other_in_progress_issue_with_same_shape_is_rejected() -> None:
    record = deepcopy(EXPECTED_LEGACY_BOOTSTRAP_RECORDS["ISSUE-0039"])

    assert not core.is_issue0011_legacy_replay_source("ISSUE-0041", record)
    with pytest.raises(ValueError, match="legacy bootstrap replay prefix"):
        _validate_prefix("ISSUE-0041", record)


def test_existing_b00_records_still_require_the_b00_transition() -> None:
    for issue_id in ("ISSUE-0011", "ISSUE-0012", "ISSUE-0014"):
        record = deepcopy(EXPECTED_LEGACY_BOOTSTRAP_RECORDS[issue_id])

        assert core.is_issue0011_legacy_replay_source(issue_id, record)
        _validate_prefix(issue_id, record)
        record["status_transition"] = None
        assert not core.is_issue0011_legacy_replay_source(issue_id, record)
        with pytest.raises(ValueError, match="legacy bootstrap replay prefix"):
            _validate_prefix(issue_id, record)


def test_consumers_resolve_the_shared_allowlist() -> None:
    assert completion.LEGACY_BOOTSTRAP_RECORDS is core.LEGACY_BOOTSTRAP_RECORDS
    assert preparation.LEGACY_BOOTSTRAP_RECORDS is core.LEGACY_BOOTSTRAP_RECORDS
    assert summary.LEGACY_BOOTSTRAP_RECORDS is core.LEGACY_BOOTSTRAP_RECORDS
