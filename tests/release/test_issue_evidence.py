from pathlib import Path

from etf_cockpit.core.closure import load_closure_matrix


def test_new_data05_record_does_not_rewrite_the_historic_41_baseline() -> None:
    matrix = load_closure_matrix(Path("configs/closure_matrix.yaml"))

    assert matrix.programme_schema_version == 2
    assert matrix.historic_baseline_count == 41
    assert len(matrix) == 42
    assert matrix.record_for("DATA-05").status == "still_open"


def test_data05_requires_every_approved_closure_gate() -> None:
    matrix = load_closure_matrix(Path("configs/closure_matrix.yaml"))
    record = matrix.record_for("DATA-05")

    required_gates = {
        gate
        for criterion in record.criteria
        for gate in criterion.required_gates
    }
    assert required_gates == {
        "source",
        "schema",
        "tests",
        "ui",
        "audit",
        "package",
        "browser",
    }
