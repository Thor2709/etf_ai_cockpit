import pytest
from pydantic import ValidationError

from etf_cockpit.operations.models import ClosureEvidenceRecord, VerificationRun


def test_verification_run_records_reproducible_result_metadata() -> None:
    record = VerificationRun(
        verification_run_id="vr-1",
        verification_type="focused_tests",
        command="python -m pytest tests/operations -q",
        source_hash="a" * 64,
        result="pass",
        exit_code=0,
        output_paths=["tests/task-1.txt"],
        output_checksums=["b" * 64],
        issue_ids=["DATA-05"],
    )

    assert record.result == "pass"
    assert record.issue_ids == ["DATA-05"]


def test_verification_run_rejects_unknown_result() -> None:
    with pytest.raises(ValidationError, match="result"):
        VerificationRun(
            verification_run_id="vr-1",
            verification_type="focused_tests",
            command="python -m pytest tests/operations -q",
            source_hash="a" * 64,
            result="unknown",
            exit_code=1,
            output_paths=[],
            output_checksums=[],
            issue_ids=["DATA-05"],
        )


def test_closure_evidence_rejects_builder_as_required_independent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-1",
            issue_id="DATA-05",
            requirement_version="2026-07-11",
            verification_run_ids=["vr-1"],
            builder="implementer",
            independent_reviewer="implementer",
            review_result="approved",
            evidence_hash="a" * 64,
        )


def test_approved_closure_evidence_rejects_blank_independent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-blank-reviewer",
            issue_id="DATA-05",
            requirement_version="2026-07-11",
            verification_run_ids=["vr-1"],
            builder="implementer",
            independent_reviewer="  ",
            review_result="approved",
            evidence_hash="a" * 64,
        )


def test_approved_closure_evidence_rejects_whitespace_equivalent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-whitespace-reviewer",
            issue_id="DATA-05",
            requirement_version="2026-07-11",
            verification_run_ids=["vr-1"],
            builder=" implementer ",
            independent_reviewer="implementer",
            review_result="approved",
            evidence_hash="a" * 64,
        )


def test_approved_closure_evidence_stores_normalised_actor_ids() -> None:
    record = ClosureEvidenceRecord(
        closure_evidence_id="ce-normalised-actors",
        issue_id="DATA-05",
        requirement_version="2026-07-11",
        verification_run_ids=["vr-1"],
        builder=" implementer ",
        independent_reviewer=" reviewer ",
        review_result="approved",
        evidence_hash="a" * 64,
    )

    assert record.builder == "implementer"
    assert record.independent_reviewer == "reviewer"


def test_rejected_closure_evidence_may_record_the_builder_as_reviewer() -> None:
    record = ClosureEvidenceRecord(
        closure_evidence_id="ce-2",
        issue_id="DATA-05",
        requirement_version="2026-07-11",
        verification_run_ids=["vr-1"],
        builder="implementer",
        independent_reviewer="implementer",
        review_result="rejected",
        evidence_hash="a" * 64,
    )

    assert record.review_result == "rejected"
