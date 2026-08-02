from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning
from etf_cockpit.parsers.index_methodology import IndexMethodologyRecord
from etf_cockpit.parsers.priips_kid import PriipsKidRecord


def _kid_result() -> ParseResult[PriipsKidRecord]:
    record = PriipsKidRecord(
        product="Example ETF",
        isin="IE000Q4J3CW6",
        manufacturer="Vanguard",
        sri=4,
        cost_fields={"entry_costs": "EUR 0"},
        holding_period_years=5,
        scenarios=("moderate",),
        document_date="2026-04-14",
        extraction_confidence="high",
        warnings=(),
        source_sha256="a" * 64,
        source_pages=(1, 2),
        score_eligible=True,
    )
    return ParseResult((record,), (), "priips_kid", "2.0", "a" * 64, True)


def _methodology_result() -> ParseResult[IndexMethodologyRecord]:
    record = IndexMethodologyRecord(
        provider="FTSE Russell",
        index_series="FTSE Global Equity Index Series",
        version="14.2",
        document_date="July 2026",
        eligibility_rules=("Eligible securities",),
        weighting_rules=("Capitalisation weighting",),
        review_frequency="Quarterly review",
        caps=("5% cap",),
        source_pages=(1, 3),
        confidence="high",
        warnings=(),
        source_sha256="b" * 64,
        score_eligible=True,
    )
    return ParseResult((record,), (), "index_methodology", "2.0", "b" * 64, True)


def test_parsed_kid_persistence_is_versioned_checksum_keyed_and_idempotent(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_priips_kid_result, read_priips_kid_records

    destination = tmp_path / "priips_kid_records.parquet"
    persist_priips_kid_result(_kid_result(), "VWCE", destination=destination)
    persist_priips_kid_result(_kid_result(), "VWCE", destination=destination)

    frame = read_priips_kid_records(destination)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["schema_version"] == 2
    assert row["source_id"].startswith("parsed:kid:")
    assert row["source_sha256"] == "a" * 64
    assert row["source_pages"] == "[1, 2]"


def test_parsed_methodology_persistence_retains_warning_pages_and_manual_state(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_index_methodology_result, read_index_methodology_records

    warning = ParseWarning("methodology_holdings_conflict", "conflict", "warning", "page 3")
    result = ParseResult(
        (_methodology_result().records[0],),
        (warning,),
        "index_methodology",
        "2.0",
        "b" * 64,
        False,
    )
    destination = tmp_path / "index_methodology_records.parquet"
    persist_index_methodology_result(result, "VWCE", destination=destination)

    row = read_index_methodology_records(destination).iloc[0]
    assert row["provider"] == "FTSE Russell"
    assert row["source_pages"] == "[1, 3]"
    assert "methodology_holdings_conflict" in row["warnings"]
    assert bool(row["manual_review"]) is True


def test_methodology_persistence_attaches_real_holdings_conflict(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_index_methodology_result, read_index_methodology_records

    destination = tmp_path / "index_methodology_records.parquet"
    holdings = pd.DataFrame({"security": ["Large"], "weight": [0.08], "region": ["Developed Markets"]})
    persist_index_methodology_result(_methodology_result(), "VWCE", destination=destination, holdings=holdings)

    row = read_index_methodology_records(destination).iloc[0]
    assert "methodology_holdings_conflict" in row["warnings"]
    assert bool(row["manual_review"]) is True
    assert bool(row["score_eligible"]) is False


def test_methodology_holdings_unavailable_retains_source_document_provenance(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.data.fund_documents import read_document_registry

    source = tmp_path / "methodology.pdf"
    source.write_bytes(b"methodology source")
    registry = tmp_path / "fund_documents.parquet"
    parsed.persist_index_methodology_with_document(
        _methodology_result(),
        "VWCE",
        source,
        destination=tmp_path / "index_methodology_records.parquet",
        registry_destination=registry,
        holdings=pd.DataFrame(),
    )

    methodology = read_document_registry(path=registry).loc[lambda frame: frame["document_type"].eq("methodology")].iloc[0]
    assert methodology["coverage_status"] == "available"
    assert methodology["path"] == str(source)
    assert methodology["sha256"]


def test_combined_kid_import_publishes_parsed_store_and_registry_atomically(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed

    source = tmp_path / "kid.pdf"
    source.write_bytes(b"kid source")
    destination = tmp_path / "priips_kid_records.parquet"
    registry = tmp_path / "fund_documents.parquet"

    assert hasattr(parsed, "persist_priips_kid_with_document")
    parsed.persist_priips_kid_with_document(
        _kid_result(),
        "VWCE",
        source,
        destination=destination,
        registry_destination=registry,
    )

    assert len(pd.read_parquet(destination)) == 1
    registry_frame = pd.read_parquet(registry)
    assert set(registry_frame["document_type"]) >= {"kid"}


def test_failed_kid_import_is_unavailable_and_does_not_retain_ephemeral_path(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.data.fund_documents import read_document_registry

    source = tmp_path / "mismatched-kid.pdf"
    source.write_bytes(b"mismatched kid source")
    result = ParseResult(
        (),
        (ParseWarning("identity_mismatch", "KID identity does not match the configured instrument", "error", "page 1"),),
        "priips_kid",
        "2.0",
        "c" * 64,
        False,
    )
    destination = tmp_path / "priips_kid_records.parquet"
    registry = tmp_path / "fund_documents.parquet"

    parsed.persist_priips_kid_with_document(
        result,
        "VWCE",
        source,
        destination=destination,
        registry_destination=registry,
    )

    row = pd.read_parquet(destination).iloc[0]
    assert bool(row["manual_review"]) is True
    assert bool(row["success"]) is False
    registered = read_document_registry(path=registry)
    kid = registered.loc[registered["document_type"].eq("kid")].iloc[0]
    assert kid["coverage_status"] == "unavailable"
    assert kid["path"] == ""
    assert "identity_mismatch" in kid["warnings"]


def test_failed_kid_import_supersedes_preexisting_missing_inventory_row(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.data.fund_documents import build_document_inventory, read_document_registry, write_document_registry

    source = tmp_path / "mismatched-kid.pdf"
    source.write_bytes(b"mismatched kid source")
    registry = tmp_path / "fund_documents.parquet"
    write_document_registry(build_document_inventory(["VWCE"]), destination=registry)
    result = ParseResult(
        (),
        (ParseWarning("identity_mismatch", "KID identity does not match the configured instrument", "error", "page 1"),),
        "priips_kid",
        "2.0",
        "d" * 64,
        False,
    )

    parsed.persist_priips_kid_with_document(
        result,
        "VWCE",
        source,
        destination=tmp_path / "priips_kid_records.parquet",
        registry_destination=registry,
    )

    kid = read_document_registry(path=registry).loc[lambda frame: frame["document_type"].eq("kid")].iloc[0]
    assert kid["coverage_status"] == "unavailable"
    assert "identity_mismatch" in kid["warnings"]
    assert kid["path"] == ""


def test_combined_kid_import_rolls_back_when_registry_stage_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.core import atomic_io

    source = tmp_path / "kid.pdf"
    source.write_bytes(b"kid source")
    destination = tmp_path / "priips_kid_records.parquet"
    registry = tmp_path / "fund_documents.parquet"
    parsed.persist_priips_kid_with_document(_kid_result(), "VWCE", source, destination=destination, registry_destination=registry)
    prior = {
        path: path.read_bytes()
        for path in (destination, destination.with_suffix(".csv"), registry, registry.with_suffix(".csv"))
    }

    real_atomic_write_group = atomic_io.atomic_write_group

    def fail_registry_stage(requests, **kwargs):
        staged = []
        for request in tuple(requests):
            if request.destination.resolve() == registry.resolve():
                staged.append(atomic_io.AtomicWriteRequest(request.destination, request.payload, lambda _path: (_ for _ in ()).throw(OSError("registry validation failed"))))
            else:
                staged.append(request)
        return real_atomic_write_group(tuple(staged), **kwargs)

    monkeypatch.setattr(parsed, "atomic_write_group", fail_registry_stage)
    with pytest.raises(OSError, match="registry validation failed"):
        parsed.persist_priips_kid_with_document(_kid_result(), "LYP6", source, destination=destination, registry_destination=registry)

    assert {path: path.read_bytes() for path in prior} == prior


def test_corrupt_parsed_store_fails_closed_without_overwriting_prior_bytes(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_priips_kid_result

    destination = tmp_path / "corrupt.parquet"
    destination.write_bytes(b"corrupt parquet bytes")
    prior = destination.read_bytes()

    with pytest.raises(ValueError, match="corrupt"):
        persist_priips_kid_result(_kid_result(), "VWCE", destination=destination)

    assert destination.read_bytes() == prior
def _v2_report_result(path: Path, *, kind: str = "prospectus", fund_name: str = "Evidence ETF", success: bool = True) -> ParseResult:
    from etf_cockpit.parsers.etf_report import EtfReportFieldEvidence, EtfReportRecord

    import hashlib

    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    values = {
        "fund_name": fund_name, "isin": "IE00B4L5Y983", "document_date": "2026-07-14",
        "reporting_period_end": "2026-06-30" if kind != "prospectus" else None,
        "legal_structure": "Irish UCITS investment company", "securities_lending": "Up to 50%",
        "collateral_policy": "Daily margining", "ongoing_costs": "0.22%", "holdings_count": "3612",
        "operational_risks": "Settlement risk",
    }
    evidence = tuple(EtfReportFieldEvidence(field, value, 1, "high", "extracted" if value is not None else "unknown", (value,) if value is not None else (), field, (1,) if value is not None else ()) for field, value in values.items())
    record = EtfReportRecord(kind, "en", "language.en.v1", f"template.{kind.replace('_', '-')}.english.v1", "2026-07-14", values, evidence, (1,), "high" if success else "partial", () if success else ("required_field_missing",), checksum)
    return ParseResult((record,), (), "etf_report", "2.0", checksum, success)


def test_v2_import_is_typed_checksum_bound_and_review_time_is_store_generated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest, import_etf_report, read_etf_report_records, review_etf_report

    source = tmp_path / "prospectus.pdf"
    source.write_bytes(b"v2 source")
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    report_path = tmp_path / "reports.parquet"
    registry_path = tmp_path / "fund_documents.parquet"
    conflict_path = tmp_path / "conflicts.parquet"
    imported = import_etf_report(EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=source, destination=report_path, registry_destination=registry_path, conflict_destination=conflict_path, raw_dir=tmp_path / "raw"))
    row = read_etf_report_records(report_path).iloc[0]
    assert imported.source_id.startswith("report:v2:")
    assert row["source_sha256"] == imported.document.sha256
    assert row["verification_status"] == "pending"
    assert bool(row["evidence_eligible"]) is False
    with pytest.raises(ValueError, match="fingerprint"):
        review_etf_report(EtfReportReviewRequest(str(row["source_id"]), "0" * 64, "analyst", "verified"), destination=report_path, registry_destination=registry_path, conflict_destination=conflict_path)
    review_etf_report(EtfReportReviewRequest(str(row["source_id"]), str(row["extraction_sha256"]), "analyst", "verified"), destination=report_path, registry_destination=registry_path, conflict_destination=conflict_path)
    verified = read_etf_report_records(report_path).iloc[0]
    assert verified["verification_status"] == "verified"
    assert bool(verified["evidence_eligible"]) is True
    assert bool(verified["score_eligible"]) is False
    assert bool(verified["execution_allowed"]) is False
    assert "reviewed_at" in str(verified["review_history"])


def test_failed_v2_parse_remains_checksum_backed_but_never_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, import_etf_report

    source = tmp_path / "unsupported.pdf"
    source.write_bytes(b"unsupported")
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind, success=False))
    registry_path = tmp_path / "fund_documents.parquet"
    imported = import_etf_report(EtfReportImportRequest("VWCE", "annual_report", "official_regulator", source_path=source, destination=tmp_path / "reports.parquet", registry_destination=registry_path, conflict_destination=tmp_path / "conflicts.parquet", raw_dir=tmp_path / "raw"))
    registry = pd.read_parquet(registry_path)
    row = registry.loc[registry["source_id"].eq(imported.source_id)].iloc[0]
    assert row["sha256"]
    assert row["extraction_status"] == "incomplete"
    assert row["coverage_status"] != "available"


def test_v2_conflict_store_retains_both_sources_and_recomputes_after_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest, import_etf_report, read_etf_report_conflicts, read_etf_report_records, review_etf_report

    def parse(path: Path, kind: str, **_kwargs):
        return _v2_report_result(path, kind=kind, fund_name="Annual name" if kind == "annual_report" else "Prospectus name")

    monkeypatch.setattr(module, "parse_etf_report_in_child", parse)
    reports = tmp_path / "reports.parquet"
    registry = tmp_path / "registry.parquet"
    conflicts = tmp_path / "conflicts.parquet"
    for kind, payload in (("prospectus", b"p"), ("annual_report", b"a")):
        source = tmp_path / f"{kind}.pdf"
        source.write_bytes(payload)
        import_etf_report(EtfReportImportRequest("VWCE", kind, "issuer_document", source_path=source, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=tmp_path / "raw"))
    conflict_frame = read_etf_report_conflicts(conflicts)
    assert not conflict_frame.empty
    assert conflict_frame["value_a"].notna().all()
    assert conflict_frame["value_b"].notna().all()
    assert conflict_frame["canonical_value"].isna().all()
    annual = read_etf_report_records(reports).loc[lambda frame: frame["document_kind"].eq("annual_report")].iloc[0]
    review_etf_report(EtfReportReviewRequest(str(annual["source_id"]), str(annual["extraction_sha256"]), "analyst", "rejected", "conflicting source"), destination=reports, registry_destination=registry, conflict_destination=conflicts)
    assert read_etf_report_conflicts(conflicts).empty
