import hashlib
from pathlib import Path

import pytest

from etf_cockpit.core.closure import (
    ClosureCriterion,
    IssueClosureRecord,
    evaluate_issue,
    load_closure_matrix,
)


EXPECTED_41_IDS = {
    "UPDATEV2-0029",
    "ISSUE-0013",
    "ISSUE-0014",
    "ISSUE-0045",
    "ISSUE-0069",
    "UPDATEV2-0027",
    "ISSUE-0011",
    "ISSUE-0012",
    "ISSUE-0040",
    "ISSUE-0039",
    "UPDATEV2-0010",
    "UPDATEV2-0011",
    "UPDATEV2-0021",
    "UPDATEV2-0022",
    "ISSUE-0035",
    "ISSUE-0068",
    "ISSUE-0018",
    "ISSUE-0017",
    "ISSUE-0056",
    "UPDATEV2-0012",
    "UPDATEV2-0013",
    "UPDATEV2-0015",
    "UPDATEV2-0016",
    "UPDATEV2-0017",
    "UPDATEV2-0019",
    "ISSUE-0023",
    "ISSUE-0025",
    "ISSUE-0054",
    "ISSUE-0055",
    "ISSUE-0067",
    "ISSUE-0047",
    "ISSUE-0052",
    "ISSUE-0059",
    "ISSUE-0064",
    "ISSUE-0034",
    "ISSUE-0019",
    "ISSUE-0036",
    "ISSUE-0042",
    "ISSUE-0044",
    "ISSUE-0041",
    "UPDATEV2-0028",
}


def write_evidence(root: Path, relative_path: str, content: bytes = b"verified") -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.with_name(target.name + ".sha256").write_text(
        hashlib.sha256(content).hexdigest() + "\n",
        encoding="ascii",
    )


def test_closure_matrix_preserves_reviewed_41_ids_and_adds_data05_separately():
    matrix = load_closure_matrix(Path("configs/closure_matrix.yaml"))
    records = tuple(matrix)

    assert matrix.programme_schema_version == 2
    assert matrix.historic_baseline_count == 41
    assert len(records) == 42
    assert {record.issue_id for record in records} == EXPECTED_41_IDS | {"DATA-05"}
    assert {record.issue_id for record in records if record.issue_id != "DATA-05"} == EXPECTED_41_IDS
    assert matrix.record_for("DATA-05").status == "still_open"
    assert all(record.criteria for record in records)
    assert all(
        not criterion.text.lstrip().startswith("- ")
        for record in records
        for criterion in record.criteria
    )
    assert all(
        ";" not in criterion.text
        for record in records
        for criterion in record.criteria
    )
    assert sum(len(record.criteria) for record in records) >= 450
    criterion_ids = [
        criterion.criterion_id
        for record in records
        for criterion in record.criteria
    ]
    assert len(criterion_ids) == len(set(criterion_ids))


def test_required_gate_cannot_be_marked_ready_without_evidence_file(tmp_path):
    for relative_path in ("source/implementation.txt", "tests/results.txt"):
        write_evidence(tmp_path, relative_path)
    record = IssueClosureRecord(
        issue_id="ISSUE-TEST",
        title="Required UI evidence",
        wave=1,
        status="still_open",
        criteria=(
            ClosureCriterion(
                criterion_id="ISSUE-TEST-01",
                text="The UI is verified.",
                required_gates=("source", "tests", "ui"),
                evidence_paths=(
                    "source/implementation.txt",
                    "tests/results.txt",
                ),
            ),
        ),
    )

    evaluation = evaluate_issue(record, tmp_path)

    assert evaluation.ready is False
    assert evaluation.missing_gates == ("ui",)


def test_issue_is_ready_only_when_every_criterion_gate_has_evidence(tmp_path):
    paths = (
        "source/implementation.txt",
        "tests/results.txt",
        "browser/smoke.png",
    )
    for relative_path in paths:
        write_evidence(tmp_path, relative_path)
    record = IssueClosureRecord(
        issue_id="ISSUE-TEST",
        title="Complete evidence",
        wave=1,
        status="still_open",
        criteria=(
            ClosureCriterion(
                criterion_id="ISSUE-TEST-01",
                text="All gates are verified.",
                required_gates=("source", "tests", "browser"),
                evidence_paths=paths,
            ),
        ),
    )

    evaluation = evaluate_issue(record, tmp_path)

    assert evaluation.ready is True
    assert evaluation.missing_gates == ()
    assert evaluation.evidence_paths == paths


def test_missing_or_mismatched_checksum_cannot_satisfy_gate(tmp_path):
    path = "source/implementation.txt"
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text("unverified", encoding="utf-8")
    record = IssueClosureRecord(
        issue_id="ISSUE-TEST",
        title="Checksummed evidence",
        wave=1,
        criteria=(
            ClosureCriterion("ISSUE-TEST-01", "Require a checksum.", ("source",), (path,)),
        ),
    )

    assert evaluate_issue(record, tmp_path).missing_gates == ("source",)
    target.with_name(target.name + ".sha256").write_text("0" * 64, encoding="ascii")
    assert evaluate_issue(record, tmp_path).missing_gates == ("source",)


def test_symlinked_evidence_cannot_escape_root(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "source" / "linked.txt"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError:
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda value: value == link or original_is_symlink(value))
    link.with_name(link.name + ".sha256").write_text(
        hashlib.sha256(outside.read_bytes()).hexdigest(),
        encoding="ascii",
    )
    record = IssueClosureRecord(
        issue_id="ISSUE-TEST",
        title="Contained evidence",
        wave=1,
        criteria=(
            ClosureCriterion("ISSUE-TEST-01", "Keep evidence local.", ("source",), ("source/linked.txt",)),
        ),
    )

    assert evaluate_issue(record, tmp_path).missing_gates == ("source",)


@pytest.mark.parametrize("unsafe_path", ["../outside.txt", "/absolute.txt", "C:/absolute.txt"])
def test_matrix_rejects_unsafe_evidence_paths(tmp_path, unsafe_path):
    matrix = tmp_path / "matrix.yaml"
    matrix.write_text(
        f"""
issues:
  - issue_id: ISSUE-TEST
    title: Unsafe evidence
    wave: 1
    criteria:
      - criterion_id: ISSUE-TEST-01
        text: Reject unsafe paths.
        required_gates: [source]
        evidence_paths: ['{unsafe_path}']
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="relative"):
        load_closure_matrix(matrix)


def test_matrix_rejects_non_positive_wave(tmp_path):
    matrix = tmp_path / "matrix.yaml"
    matrix.write_text(
        """
issues:
  - issue_id: ISSUE-TEST
    title: Invalid wave
    wave: 0
    criteria:
      - criterion_id: ISSUE-TEST-01
        text: Wave must be positive.
        required_gates: [source]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="positive integer"):
        load_closure_matrix(matrix)
