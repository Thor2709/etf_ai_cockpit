from copy import deepcopy

import pytest

from scripts import apply_reviewed_status_completion as completion
from scripts import issue_registry_core as core
from scripts import prepare_github_mutation_authority as preparation
from scripts import validation_summary as summary


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
        record = deepcopy(core.LEGACY_BOOTSTRAP_RECORDS[issue_id])

        assert core.is_issue0011_legacy_replay_source(issue_id, record)
        _validate_prefix(issue_id, record)
        _validate_prefix(issue_id, record, history=[])


def test_single_field_mutations_are_rejected() -> None:
    mutations = (
        ("acceptance_evidence", [{"status": "integrated"}]),
        ("dependency_edge_evidence", {"ISSUE-0001": {}}),
        ("phase", "phase-08-frontend-api"),
        ("programme_status", "ready"),
        (
            "status_transition",
            {
                "from": "in_progress",
                "review_reference": "B00 canonical import from audited programme state",
                "to": "in_progress",
            },
        ),
        ("verified_commit", "0" * 40),
        ("verified_date", "2026-07-22"),
    )
    for issue_id in ("ISSUE-0039", "ISSUE-0040"):
        for field, value in mutations:
            record = deepcopy(core.LEGACY_BOOTSTRAP_RECORDS[issue_id])
            record[field] = value
            assert not core.is_issue0011_legacy_replay_source(issue_id, record)
            with pytest.raises(ValueError, match="legacy bootstrap replay prefix"):
                _validate_prefix(issue_id, record)


def test_other_in_progress_issue_with_same_shape_is_rejected() -> None:
    record = deepcopy(core.LEGACY_BOOTSTRAP_RECORDS["ISSUE-0039"])

    assert not core.is_issue0011_legacy_replay_source("ISSUE-0041", record)
    with pytest.raises(ValueError, match="legacy bootstrap replay prefix"):
        _validate_prefix("ISSUE-0041", record)


def test_existing_b00_records_still_require_the_b00_transition() -> None:
    for issue_id in ("ISSUE-0011", "ISSUE-0012", "ISSUE-0014"):
        record = deepcopy(core.LEGACY_BOOTSTRAP_RECORDS[issue_id])

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
