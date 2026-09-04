from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.sec_submissions import parse_submissions


FIXTURE = Path("tests/fixtures/official/sec_submissions/microsoft-submissions.json")


def _identity(cik: str = "789019") -> CanonicalIdentity:
    return CanonicalIdentity(
        "MSFT",
        "Microsoft Corporation",
        None,
        "needs_verification",
        "",
        None,
        None,
        "stock",
        {},
        "manual_review",
        (),
        cik,
    )


def _columns(*, accession: str = "0000789019-26-000001", form: str = "10-K", acceptance: object = "2026-01-02T03:04:05.000Z") -> dict[str, list[object]]:
    return {
        "accessionNumber": [accession],
        "filingDate": ["2026-01-02"],
        "reportDate": ["2025-12-31"],
        "acceptanceDateTime": [acceptance],
        "form": [form],
        "primaryDocument": ["annual.htm"],
        "unrecognisedField": ["retained"],
    }


def _payload(columns: dict[str, list[object]], *, cik: object = "0000789019", files: list[dict[str, object]] | None = None, name: object = "MICROSOFT CORP") -> dict[str, object]:
    return {"cik": cik, "name": name, "filings": {"recent": columns, "files": files or []}}


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_official_submissions_fixture_preserves_rows_dates_and_raw_evidence() -> None:
    result = parse_submissions(FIXTURE, _identity())

    assert result.success is True
    assert len(result.records) == 1004
    assert result.source_sha256 == "a33237dbec83fc5a6529a3ec92990322400b2cb0f386993a44d0d0be69ea5804"
    assert any(warning.code == "history_incomplete" for warning in result.warnings)
    record = result.records[0]
    assert record.instrument_id == "MSFT"
    assert record.cik == "0000789019"
    assert record.filing_date == "2026-07-02"
    assert record.accepted_at == "2026-07-02T16:31:40+00:00"
    assert record.available_at == record.accepted_at
    assert record.is_amendment is False
    assert record.source_sha256 == result.source_sha256
    assert record.source_id.startswith("sec_edgar:")
    assert record.raw_row["core_type"] == "PX14A6G"


def test_submissions_source_lineage_is_deterministic() -> None:
    first = parse_submissions(FIXTURE, _identity())
    second = parse_submissions(FIXTURE, _identity())

    assert first.source_sha256 == second.source_sha256
    assert [(row.source_id, row.raw_row) for row in first.records] == [(row.source_id, row.raw_row) for row in second.records]


def test_amendments_are_distinct_and_not_superseded(tmp_path: Path) -> None:
    columns = _columns()
    for key in columns:
        columns[key].append(columns[key][0])
    columns["accessionNumber"][1] = "0000789019-26-000002"
    columns["form"][1] = "10-K/A"
    columns["unrecognisedField"][1] = "amendment"
    path = _write(tmp_path / "submissions.json", _payload(columns))

    result = parse_submissions(path, _identity())

    assert result.success is True
    assert len(result.records) == 2
    assert result.records[0].is_amendment is False
    assert result.records[1].is_amendment is True
    assert result.records[0].source_id != result.records[1].source_id
    assert not any(warning.code == "conflicting_accession" for warning in result.warnings)


def test_invalid_or_missing_dates_remain_explicit_without_timestamp_guess(tmp_path: Path) -> None:
    columns = _columns(acceptance="2026-01-02T03:04:05")
    columns["filingDate"] = ["not-a-date"]
    columns["reportDate"] = [""]
    path = _write(tmp_path / "submissions.json", _payload(columns))

    result = parse_submissions(path, _identity())
    record = result.records[0]

    assert result.success is True
    assert record.filing_date is None
    assert record.report_date is None
    assert record.accepted_at is None
    assert record.available_at is None
    assert any(warning.code == "invalid_date" for warning in result.warnings)
    assert any(warning.code == "invalid_acceptance_timestamp" for warning in result.warnings)


def test_wrong_cik_fails_closed(tmp_path: Path) -> None:
    path = _write(tmp_path / "submissions.json", _payload(_columns(), cik="0000000001"))

    result = parse_submissions(path, _identity())

    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "identity_mismatch" for warning in result.warnings)


def test_parallel_column_length_mismatch_fails_closed(tmp_path: Path) -> None:
    columns = _columns()
    columns["form"].append("10-Q")
    path = _write(tmp_path / "submissions.json", _payload(columns))

    result = parse_submissions(path, _identity())

    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "column_length_mismatch" for warning in result.warnings)


def test_advertised_history_is_parsed_only_when_explicitly_supplied(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    current_path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": name, "filingCount": 1}]))
    history_path = _write(tmp_path / name, _columns(accession="0000789019-25-000001", form="10-Q"))

    result = parse_submissions(current_path, _identity(), history_paths={name: history_path})

    assert result.success is True
    assert [record.accession for record in result.records] == ["0000789019-26-000001", "0000789019-25-000001"]
    assert result.records[1].source_sha256 == hashlib.sha256(history_path.read_bytes()).hexdigest()
    assert not any(warning.code == "history_incomplete" for warning in result.warnings)


def test_advertised_history_not_supplied_is_explicitly_incomplete(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": name}]))

    result = parse_submissions(path, _identity())

    assert result.success is True
    assert len(result.records) == 1
    assert any(warning.code == "history_incomplete" for warning in result.warnings)


def test_duplicate_and_conflicting_accessions_remain_visible(tmp_path: Path) -> None:
    columns = _columns()
    for key in columns:
        columns[key].append(columns[key][0])
    columns["unrecognisedField"][1] = "different"
    path = _write(tmp_path / "submissions.json", _payload(columns))

    result = parse_submissions(path, _identity())

    assert len(result.records) == 2
    assert result.records[0].raw_row != result.records[1].raw_row
    assert any(warning.code == "conflicting_accession" for warning in result.warnings)


def test_exact_duplicate_accessions_remain_visible_with_warning(tmp_path: Path) -> None:
    columns = _columns()
    for key in columns:
        columns[key].append(columns[key][0])
    path = _write(tmp_path / "submissions.json", _payload(columns))

    result = parse_submissions(path, _identity())

    assert len(result.records) == 2
    assert result.records[0].raw_row == result.records[1].raw_row
    assert any(warning.code == "duplicate_accession" for warning in result.warnings)


def test_non_ascii_cik_fails_closed_without_numeric_coercion(tmp_path: Path) -> None:
    path = _write(tmp_path / "submissions.json", _payload(_columns(), cik="²"))

    result = parse_submissions(path, replace(_identity(), cik="²"))

    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "identity_missing" for warning in result.warnings)


def test_invalid_accession_is_not_accepted_as_a_canonical_record(tmp_path: Path) -> None:
    columns = _columns()
    columns["accessionNumber"] = ["not-an-accession"]
    path = _write(tmp_path / "submissions.json", _payload(columns))

    result = parse_submissions(path, _identity())

    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "invalid_accession" for warning in result.warnings)


def test_history_mapping_insertion_order_cannot_change_record_order(tmp_path: Path) -> None:
    first_name = "CIK0000789019-submissions-001.json"
    second_name = "CIK0000789019-submissions-002.json"
    current_path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": first_name, "filingCount": 1}, {"name": second_name, "filingCount": 1}]))
    first_path = _write(tmp_path / first_name, _columns(accession="0000789019-25-000001"))
    second_path = _write(tmp_path / second_name, _columns(accession="0000789019-24-000001"))

    first = parse_submissions(current_path, _identity(), history_paths={second_name: second_path, first_name: first_path})
    second = parse_submissions(current_path, _identity(), history_paths={first_name: first_path, second_name: second_path})

    assert [record.accession for record in first.records] == [record.accession for record in second.records]
    assert [record.accession for record in first.records] == ["0000789019-26-000001", "0000789019-25-000001", "0000789019-24-000001"]


def test_history_filing_count_mismatch_marks_incomplete_but_retains_rows(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    current_path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": name, "filingCount": 2}]))
    history_path = _write(tmp_path / name, _columns(accession="0000789019-25-000001"))

    result = parse_submissions(current_path, _identity(), history_paths={name: history_path})

    assert result.success is True
    assert len(result.records) == 2
    assert any(warning.code == "history_count_mismatch" for warning in result.warnings)
    assert any(warning.code == "history_incomplete" for warning in result.warnings)


def test_skipped_history_row_marks_incomplete_without_dropping_valid_rows(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    columns = _columns(accession="not-an-accession")
    columns["accessionNumber"].append("0000789019-25-000001")
    for key in columns:
        if key != "accessionNumber":
            columns[key].append(columns[key][0])
    current_path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": name}]))
    history_path = _write(tmp_path / name, columns)

    result = parse_submissions(current_path, _identity(), history_paths={name: history_path})

    assert result.success is True
    assert [record.accession for record in result.records] == ["0000789019-26-000001", "0000789019-25-000001"]
    assert any(warning.code == "invalid_accession" for warning in result.warnings)
    assert any(warning.code == "history_incomplete" for warning in result.warnings)


@pytest.mark.parametrize("filing_count", [True, -1, "2"])
def test_malformed_history_filing_count_is_explicit(tmp_path: Path, filing_count: object) -> None:
    name = "CIK0000789019-submissions-001.json"
    current_path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": name, "filingCount": filing_count}]))
    history_path = _write(tmp_path / name, _columns(accession="0000789019-25-000001"))

    result = parse_submissions(current_path, _identity(), history_paths={name: history_path})

    assert result.success is True
    assert any(warning.code == "history_count_invalid" for warning in result.warnings)
    assert any(warning.code == "history_incomplete" for warning in result.warnings)


@pytest.mark.parametrize("unsafe_name", ["../CIK0000789019-submissions-001.json", "CIK0000000001-submissions-001.json"])
def test_history_name_must_be_advertised_and_bound_to_cik(tmp_path: Path, unsafe_name: str) -> None:
    path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": unsafe_name}]))

    result = parse_submissions(path, _identity())

    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "history_name_invalid" for warning in result.warnings)


def test_history_path_with_unadvertised_name_fails_closed(tmp_path: Path) -> None:
    advertised = "CIK0000789019-submissions-001.json"
    path = _write(tmp_path / "current.json", _payload(_columns(), files=[{"name": advertised}]))
    extra = _write(tmp_path / "CIK0000789019-submissions-002.json", _columns())

    result = parse_submissions(path, _identity(), history_paths={extra.name: extra})

    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "history_not_advertised" for warning in result.warnings)


def test_missing_acceptance_timestamp_and_empty_input_are_explicit(tmp_path: Path) -> None:
    columns = _columns(acceptance=None)
    path = _write(tmp_path / "missing.json", _payload(columns))
    missing = parse_submissions(path, _identity())
    empty_columns = {key: [] for key in columns}
    empty = parse_submissions(_write(tmp_path / "empty.json", _payload(empty_columns)), _identity())

    assert missing.records[0].available_at is None
    assert any(warning.code == "missing_acceptance_timestamp" for warning in missing.warnings)
    assert empty.success is False
    assert empty.records == ()
    assert any(warning.code == "empty_history" for warning in empty.warnings)


def test_malformed_entity_and_no_network_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("submissions parser must not access the network")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected_network)
    path = _write(tmp_path / "malformed.json", _payload(_columns(), name=""))

    result = parse_submissions(path, _identity())

    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "entity_invalid" for warning in result.warnings)
