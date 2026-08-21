from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
from threading import Barrier

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


def test_csv_validator_accepts_quoted_newlines_and_rejects_inconsistent_widths(
    tmp_path: Path,
) -> None:
    from etf_cockpit.data.parsed_disclosures import _validate_csv_file

    valid = tmp_path / "valid.csv"
    valid.write_text('source_id,notes\nsource-1,"line one\nline two"\n', encoding="utf-8")
    _validate_csv_file(valid)

    malformed = tmp_path / "malformed.csv"
    malformed.write_text("source_id,notes\nsource-1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inconsistent row widths"):
        _validate_csv_file(malformed)


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
def _v2_report_result(
    path: Path,
    *,
    kind: str = "prospectus",
    fund_name: str = "Evidence ETF",
    success: bool = True,
    parser_version: str = "2.0",
    template_version: str = "v1",
    legal_structure: str = "Irish UCITS investment company",
    document_date: str = "2026-07-14",
) -> ParseResult:
    from etf_cockpit.parsers.etf_report import EtfReportFieldEvidence, EtfReportRecord

    import hashlib

    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    values = {
        "fund_name": fund_name, "isin": "IE00B4L5Y983", "document_date": document_date,
        "reporting_period_end": "2026-06-30" if kind != "prospectus" else None,
        "legal_structure": legal_structure, "securities_lending": "Up to 50%",
        "collateral_policy": "Daily margining", "ongoing_costs": "0.22%", "holdings_count": "3612",
        "operational_risks": "Settlement risk",
    }
    evidence = tuple(EtfReportFieldEvidence(field, value, 1, "high", "extracted" if value is not None else "unknown", (value,) if value is not None else (), field, (1,) if value is not None else ()) for field, value in values.items())
    record = EtfReportRecord(kind, "en", "language.en.v1", f"template.{kind.replace('_', '-')}.english.{template_version}", document_date, values, evidence, (1,), "high" if success else "partial", () if success else ("required_field_missing",), checksum)
    return ParseResult((record,), (), "etf_report", parser_version, checksum, success)


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
    assert row["schema_version"] == 2.1
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


def test_review_with_future_known_at_is_rejected_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    source = tmp_path / "prospectus.pdf"
    source.write_bytes(b"future known-at review")
    monkeypatch.setattr(
        module,
        "parse_etf_report_in_child",
        lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind),
    )
    report_path = tmp_path / "reports.parquet"
    registry_path = tmp_path / "fund_documents.parquet"
    conflict_path = tmp_path / "conflicts.parquet"
    imported = module.import_etf_report(
        EtfReportImportRequest(
            "VWCE",
            "prospectus",
            "issuer_document",
            source_path=source,
            destination=report_path,
            registry_destination=registry_path,
            conflict_destination=conflict_path,
            raw_dir=tmp_path / "raw",
        )
    )

    future_known_at = "2099-01-01T00:00:00+00:00"
    reports = pd.read_parquet(report_path)
    reports.loc[reports["source_id"].eq(imported.source_id), "known_at"] = future_known_at
    reports.loc[reports["source_id"].eq(imported.source_id), "extraction_sha256"] = (
        module._row_extraction_fingerprint(reports.loc[reports["source_id"].eq(imported.source_id)].iloc[0])
    )
    reports.loc[reports["source_id"].eq(imported.source_id), "stored_extraction_sha256"] = reports.loc[
        reports["source_id"].eq(imported.source_id), "extraction_sha256"
    ]
    reports.to_parquet(report_path, index=False)

    registry = pd.read_parquet(registry_path)
    registry.loc[registry["source_id"].eq(imported.source_id), "known_at"] = future_known_at
    if "ingested_at" in registry.columns:
        registry.loc[registry["source_id"].eq(imported.source_id), "ingested_at"] = future_known_at
    registry.to_parquet(registry_path, index=False)

    paths = (
        report_path,
        report_path.with_suffix(".csv"),
        registry_path,
        registry_path.with_suffix(".csv"),
        conflict_path,
        conflict_path.with_suffix(".csv"),
    )
    prior = {path: path.read_bytes() for path in paths}
    row = reports.loc[reports["source_id"].eq(imported.source_id)].iloc[0]

    with pytest.raises(ValueError, match="known_at|future"):
        module.review_etf_report(
            EtfReportReviewRequest(
                imported.source_id,
                str(row["extraction_sha256"]),
                "analyst",
                "rejected",
            ),
            destination=report_path,
            registry_destination=registry_path,
            conflict_destination=conflict_path,
        )

    assert {path: path.read_bytes() for path in paths} == prior


def test_pre_21_report_fingerprint_loads_after_report_columns_expand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, import_etf_report, read_etf_report_records

    source = tmp_path / "legacy-report.pdf"
    source.write_bytes(b"legacy report")
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    reports = tmp_path / "reports.parquet"
    registry = tmp_path / "fund_documents.parquet"
    imported = import_etf_report(
        EtfReportImportRequest(
            "VWCE", "prospectus", "issuer_document", source_path=source, destination=reports,
            registry_destination=registry, conflict_destination=tmp_path / "conflicts.parquet", raw_dir=tmp_path / "raw",
        )
    )
    current = read_etf_report_records(reports)
    legacy = current.drop(columns=["known_at", "legal_form", "domicile", "replication_method", "derivatives", "counterparties", "collateral_terms", "concentration_limits", "lending_policy", "lending_revenue_split", "exposure", "collateral_fraction", "haircut_fraction", "concentration_limit_fraction"]).copy()
    legacy["schema_version"] = 2
    legacy_fingerprint = module._row_extraction_fingerprint(legacy.iloc[0], columns=module._LEGACY_REPORT_COLUMNS)
    assert legacy_fingerprint != module._row_extraction_fingerprint(legacy.iloc[0])
    legacy["extraction_sha256"] = legacy_fingerprint
    legacy["stored_extraction_sha256"] = legacy_fingerprint
    legacy.to_parquet(reports, index=False)

    loaded = read_etf_report_records(reports).iloc[0]
    assert loaded["source_id"] == imported.source_id
    assert loaded["stored_extraction_sha256"] == legacy_fingerprint
    assert loaded["known_at"]
    tampered = legacy.copy()
    tampered["legal_form"] = "tampered on disk"
    tampered.to_parquet(reports, index=False)
    with pytest.raises(ValueError, match="extraction store is corrupt"):
        read_etf_report_records(reports)


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


def test_canonical_conflict_visibility_is_point_in_time_for_projection_and_backtest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import etf_cockpit.data.fund_documents as fund_documents
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.backtest.engine import run_backtest
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data.etf_structure import project_etf_structure
    from etf_cockpit.data.fund_documents import read_document_registry
    from etf_cockpit.data.sample_data import generate_sample_prices
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    class FrozenDateTime(datetime):
        current = datetime(2026, 4, 1, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            value = cls.current
            return value if tz is None else value.astimezone(tz)

    config = load_config()
    instrument_id = config.universe.enabled_ids[0]
    reports, registry, conflicts = (
        tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet")
    )
    raw = tmp_path / "raw"
    prospectus = tmp_path / "prospectus.pdf"
    annual = tmp_path / "annual.pdf"
    prospectus.write_bytes(b"prospectus")
    annual.write_bytes(b"annual")

    def parse(path: Path, kind: str, **_kwargs):
        legal = "Irish UCITS investment company" if kind == "prospectus" else "Unit trust"
        return _v2_report_result(path, kind=kind, legal_structure=legal, document_date="2026-03-31")

    monkeypatch.setattr(module, "datetime", FrozenDateTime)
    monkeypatch.setattr(fund_documents, "datetime", FrozenDateTime)
    monkeypatch.setattr(module, "parse_etf_report_in_child", parse)

    first = module.import_etf_report(EtfReportImportRequest(
        instrument_id, "prospectus", "issuer_document", source_path=prospectus,
        destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw,
    ))
    FrozenDateTime.current = datetime(2026, 4, 2, tzinfo=timezone.utc)
    first_row = module.read_etf_report_records(reports).iloc[0]
    module.review_etf_report(
        EtfReportReviewRequest(first.source_id, str(first_row["extraction_sha256"]), "analyst", "verified"),
        destination=reports, registry_destination=registry, conflict_destination=conflicts,
    )
    before_reports = module.read_etf_report_records(reports)
    before_registry = read_document_registry(path=registry)
    before = project_etf_structure(
        instrument_id, document_registry=before_registry, report_records=before_reports,
        decision_time="2026-04-02T00:00:00Z",
    )

    FrozenDateTime.current = datetime(2026, 4, 10, tzinfo=timezone.utc)
    second = module.import_etf_report(EtfReportImportRequest(
        instrument_id, "annual_report", "issuer_document", source_path=annual,
        destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw,
    ))
    FrozenDateTime.current = datetime(2026, 4, 11, tzinfo=timezone.utc)
    current = module.read_etf_report_records(reports)
    second_row = current.loc[current["source_id"].eq(second.source_id)].iloc[0]
    module.review_etf_report(
        EtfReportReviewRequest(second.source_id, str(second_row["extraction_sha256"]), "analyst", "verified"),
        destination=reports, registry_destination=registry, conflict_destination=conflicts,
    )
    after_reports = module.read_etf_report_records(reports)
    after_registry = read_document_registry(path=registry)
    historical = project_etf_structure(
        instrument_id, document_registry=after_registry, report_records=after_reports,
        decision_time="2026-04-02T00:00:00Z",
    )
    after = project_etf_structure(
        instrument_id, document_registry=after_registry, report_records=after_reports,
        decision_time="2026-04-12T00:00:00Z",
    )

    assert before["fields"]["legal_form"]["status"] == "resolved"
    assert historical["fields"]["legal_form"] == before["fields"]["legal_form"]
    assert historical["structure_provenance_hash"] == before["structure_provenance_hash"]
    assert after["fields"]["legal_form"]["status"] == "conflict"
    assert after["fields"]["legal_form"]["value"] is None
    assert after["execution_allowed"] is False

    prices = generate_sample_prices(config, periods=260, end_date=datetime(2026, 8, 31).date())
    before_backtest = run_backtest(
        config, prices, structure_document_registry=before_registry,
        structure_report_records=before_reports,
    )
    after_backtest = run_backtest(
        config, prices, structure_document_registry=after_registry,
        structure_report_records=after_reports,
    )
    before_rows = before_backtest.signal_log.loc[
        before_backtest.signal_log["etf_id"].eq(instrument_id)
        & pd.to_datetime(before_backtest.signal_log["date"]).ge("2026-04-12")
    ]
    after_rows = after_backtest.signal_log.loc[
        after_backtest.signal_log["etf_id"].eq(instrument_id)
        & pd.to_datetime(after_backtest.signal_log["date"]).ge("2026-04-12")
    ]
    assert not before_rows.empty and not after_rows.empty
    assert before_rows["structural_confidence_cap"].max() > after_rows["structural_confidence_cap"].max()


def test_exact_report_reimport_preserves_review_registry_and_conflicts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind, fund_name="Annual" if kind == "annual_report" else "Prospectus"))
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    raw = tmp_path / "raw"
    prospectus = tmp_path / "prospectus.pdf"
    annual = tmp_path / "annual.pdf"
    prospectus.write_bytes(b"prospectus")
    annual.write_bytes(b"annual")
    request = EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=prospectus, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw)
    first = module.import_etf_report(request)
    row = module.read_etf_report_records(reports).iloc[0]
    module.review_etf_report(EtfReportReviewRequest(first.source_id, str(row["extraction_sha256"]), "analyst", "verified"), destination=reports, registry_destination=registry, conflict_destination=conflicts)
    module.import_etf_report(EtfReportImportRequest("VWCE", "annual_report", "issuer_document", source_path=annual, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw))
    before_row = module.read_etf_report_records(reports).loc[lambda frame: frame["source_id"].eq(first.source_id)].iloc[0].copy()
    before_registry = pd.read_parquet(registry).sort_values("source_id").reset_index(drop=True)
    before_conflicts = module.read_etf_report_conflicts(conflicts).copy()

    repeated = module.import_etf_report(request)

    after_row = module.read_etf_report_records(reports).loc[lambda frame: frame["source_id"].eq(first.source_id)].iloc[0]
    assert repeated.source_id == first.source_id
    assert after_row["extraction_sha256"] == before_row["extraction_sha256"]
    assert after_row["verification_status"] == before_row["verification_status"] == "verified"
    assert after_row["review_history"] == before_row["review_history"]
    pd.testing.assert_frame_equal(pd.read_parquet(registry).sort_values("source_id").reset_index(drop=True), before_registry)
    pd.testing.assert_frame_equal(module.read_etf_report_conflicts(conflicts), before_conflicts)


def test_reviewed_pre_21_same_source_reimport_migrates_fingerprint_with_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    source = tmp_path / "legacy-reimport.pdf"
    source.write_bytes(b"legacy reimport")
    request = EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=source, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=tmp_path / "raw")
    imported = module.import_etf_report(request)
    current = module.read_etf_report_records(reports)
    current_row = current.iloc[0]
    module.review_etf_report(EtfReportReviewRequest(imported.source_id, str(current_row["extraction_sha256"]), "analyst", "verified"), destination=reports, registry_destination=registry, conflict_destination=conflicts)
    reviewed = module.read_etf_report_records(reports).iloc[0]
    legacy = module.read_etf_report_records(reports).drop(columns=["known_at", "legal_form", "domicile", "replication_method", "derivatives", "counterparties", "collateral_terms", "concentration_limits", "lending_policy", "lending_revenue_split", "exposure", "collateral_fraction", "haircut_fraction", "concentration_limit_fraction"]).copy()
    legacy["schema_version"] = 2
    legacy_fingerprint = module._row_extraction_fingerprint(legacy.iloc[0], columns=module._LEGACY_REPORT_COLUMNS)
    legacy["extraction_sha256"] = legacy_fingerprint
    legacy["stored_extraction_sha256"] = legacy_fingerprint
    legacy["review_history"] = json.dumps([{**item, "extraction_sha256": legacy_fingerprint} for item in json.loads(str(reviewed["review_history"]))])
    legacy.to_parquet(reports, index=False)

    module.import_etf_report(request)
    after = module.read_etf_report_records(reports).iloc[0]
    after_history = json.loads(str(after["review_history"]))

    assert after["verification_status"] == "verified"
    assert after["stored_extraction_sha256"] != legacy_fingerprint
    assert after_history and {item["extraction_sha256"] for item in after_history} == {after["stored_extraction_sha256"]}


def test_multi_row_pre_21_reimport_migrates_reviewed_and_unreviewed_rows_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    raw = tmp_path / "raw"
    prospectus = tmp_path / "prospectus.pdf"
    annual = tmp_path / "annual.pdf"
    prospectus.write_bytes(b"multi-row prospectus")
    annual.write_bytes(b"multi-row annual")
    prospectus_request = EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=prospectus, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw)
    annual_request = EtfReportImportRequest("VWCE", "annual_report", "issuer_document", source_path=annual, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw)

    first = module.import_etf_report(prospectus_request)
    module.import_etf_report(annual_request)
    first_row = module.read_etf_report_records(reports).loc[lambda frame: frame["source_id"].eq(first.source_id)].iloc[0]
    module.review_etf_report(
        EtfReportReviewRequest(first.source_id, str(first_row["extraction_sha256"]), "analyst", "verified"),
        destination=reports,
        registry_destination=registry,
        conflict_destination=conflicts,
    )
    reviewed = module.read_etf_report_records(reports)
    legacy = reviewed.drop(columns=["known_at", "legal_form", "domicile", "replication_method", "derivatives", "counterparties", "collateral_terms", "concentration_limits", "lending_policy", "lending_revenue_split", "exposure", "collateral_fraction", "haircut_fraction", "concentration_limit_fraction"]).copy()
    legacy["schema_version"] = 2
    for index, row in legacy.iterrows():
        fingerprint = module._row_extraction_fingerprint(row, columns=module._LEGACY_REPORT_COLUMNS)
        legacy.at[index, "extraction_sha256"] = fingerprint
        legacy.at[index, "stored_extraction_sha256"] = fingerprint
        history = json.loads(str(row["review_history"]))
        legacy.at[index, "review_history"] = json.dumps([{**item, "extraction_sha256": fingerprint} for item in history])
    legacy.to_parquet(reports, index=False)

    module.import_etf_report(prospectus_request)
    migrated = module.read_etf_report_records(reports)

    assert len(migrated) == 2
    assert set(migrated["schema_version"]) == {module.REPORT_SCHEMA_VERSION}
    assert set(migrated["verification_status"]) == {"verified", "pending"}
    for _, row in migrated.iterrows():
        assert row["stored_extraction_sha256"] == module._row_extraction_fingerprint(row)
        history = json.loads(str(row["review_history"]))
        assert all(item["extraction_sha256"] == row["stored_extraction_sha256"] for item in history)


def test_parser_revision_reimport_retains_prior_review_as_separate_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    source = tmp_path / "prospectus.pdf"
    source.write_bytes(b"parser revision source")
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    request = EtfReportImportRequest(
        "VWCE",
        "prospectus",
        "issuer_document",
        source_path=source,
        destination=reports,
        registry_destination=registry,
        conflict_destination=conflicts,
        raw_dir=tmp_path / "raw",
    )
    revision = {"parser": "2.0", "template": "v1"}
    monkeypatch.setattr(
        module,
        "parse_etf_report_in_child",
        lambda path, kind, **_kwargs: _v2_report_result(
            path,
            kind=kind,
            parser_version=revision["parser"],
            template_version=revision["template"],
        ),
    )

    first = module.import_etf_report(request)
    first_row = module.read_etf_report_records(reports).iloc[0]
    module.review_etf_report(
        EtfReportReviewRequest(first.source_id, str(first_row["extraction_sha256"]), "analyst", "verified"),
        destination=reports,
        registry_destination=registry,
        conflict_destination=conflicts,
    )

    revision.update(parser="2.1", template="v2")
    second = module.import_etf_report(request)
    stored = module.read_etf_report_records(reports).set_index("source_id")

    assert second.source_id != first.source_id
    assert len(stored) == 2
    assert stored.loc[first.source_id, "verification_status"] == "verified"
    assert len(json.loads(str(stored.loc[first.source_id, "review_history"]))) == 1
    assert stored.loc[second.source_id, "verification_status"] == "pending"
    assert json.loads(str(stored.loc[second.source_id, "review_history"])) == []
    registry_ids = set(pd.read_parquet(registry)["source_id"].astype(str))
    assert {source_id for source_id in registry_ids if source_id.startswith("report:v2:")} == {
        first.source_id,
        second.source_id,
    }


@pytest.mark.parametrize("missing_counterpart", ["report", "registry"])
@pytest.mark.parametrize("revision_change", [False, True])
def test_same_revision_reimport_rejects_cross_store_identity_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_counterpart: str,
    revision_change: bool,
) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest

    source = tmp_path / "prospectus.pdf"
    source.write_bytes(b"cross-store identity")
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    request = EtfReportImportRequest(
        "VWCE",
        "prospectus",
        "issuer_document",
        source_path=source,
        destination=reports,
        registry_destination=registry,
        conflict_destination=conflicts,
        raw_dir=tmp_path / "raw",
    )
    extraction = {"fund_name": "Original", "parser": "2.0", "template": "v1"}
    monkeypatch.setattr(
        module,
        "parse_etf_report_in_child",
        lambda path, kind, **_kwargs: _v2_report_result(
            path,
            kind=kind,
            fund_name=extraction["fund_name"],
            parser_version=extraction["parser"],
            template_version=extraction["template"],
        ),
    )
    imported = module.import_etf_report(request)

    if missing_counterpart == "report":
        empty_reports = pd.DataFrame(columns=module.REPORT_COLUMNS)
        empty_reports.to_parquet(reports, index=False)
        empty_reports.to_csv(reports.with_suffix(".csv"), index=False)
    else:
        registry_frame = pd.read_parquet(registry)
        without_report = registry_frame.loc[~registry_frame["source_id"].astype(str).eq(imported.source_id)]
        without_report.to_parquet(registry, index=False)
        without_report.to_csv(registry.with_suffix(".csv"), index=False)
    prior = {
        path: path.read_bytes()
        for path in (
            reports,
            reports.with_suffix(".csv"),
            registry,
            registry.with_suffix(".csv"),
            conflicts,
            conflicts.with_suffix(".csv"),
        )
    }
    extraction["fund_name"] = "Drifted"
    if revision_change:
        extraction.update(parser="2.1", template="v2")

    with pytest.raises(ValueError, match="report and registry"):
        module.import_etf_report(request)

    assert {path: path.read_bytes() for path in prior} == prior


def test_same_revision_reimport_rejects_physical_registry_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest

    source = tmp_path / "prospectus.pdf"
    source.write_bytes(b"duplicate registry identity")
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    request = EtfReportImportRequest(
        "VWCE",
        "prospectus",
        "issuer_document",
        source_path=source,
        destination=reports,
        registry_destination=registry,
        conflict_destination=conflicts,
        raw_dir=tmp_path / "raw",
    )
    monkeypatch.setattr(
        module,
        "parse_etf_report_in_child",
        lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind),
    )
    imported = module.import_etf_report(request)
    registry_frame = pd.read_parquet(registry)
    report_row = registry_frame.loc[registry_frame["source_id"].astype(str).eq(imported.source_id)]
    duplicated = pd.concat([registry_frame, report_row], ignore_index=True)
    duplicated.to_parquet(registry, index=False)
    duplicated.to_csv(registry.with_suffix(".csv"), index=False)
    prior = {
        path: path.read_bytes()
        for path in (
            reports,
            reports.with_suffix(".csv"),
            registry,
            registry.with_suffix(".csv"),
            conflicts,
            conflicts.with_suffix(".csv"),
        )
    }

    with pytest.raises(ValueError, match="duplicate source_id"):
        module.import_etf_report(request)

    assert {path: path.read_bytes() for path in prior} == prior


def test_review_rejects_copied_registry_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    source = tmp_path / "report.pdf"
    source.write_bytes(b"report")
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    imported = module.import_etf_report(EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=source, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=tmp_path / "raw"))
    copied = tmp_path / "copied-registry.parquet"
    shutil.copy2(registry, copied)
    row = module.read_etf_report_records(reports).iloc[0]

    with pytest.raises(ValueError, match="registry_destination"):
        module.review_etf_report(EtfReportReviewRequest(imported.source_id, str(row["extraction_sha256"]), "analyst", "verified"), destination=reports, registry_destination=copied, conflict_destination=conflicts)


def test_snapshot_is_reasserted_if_mutated_after_registry_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest

    source = tmp_path / "report.pdf"
    expected = b"immutable snapshot"
    source.write_bytes(expected)
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    real_register = module._register_report_document

    def mutate_after_registration(path: Path, **kwargs):
        document = real_register(path, **kwargs)
        path.write_bytes(b"mutated after registration")
        return document

    monkeypatch.setattr(module, "_register_report_document", mutate_after_registration)
    result = module.import_etf_report(EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=source, destination=tmp_path / "reports.parquet", registry_destination=tmp_path / "registry.parquet", conflict_destination=tmp_path / "conflicts.parquet", raw_dir=tmp_path / "raw"))
    snapshot = tmp_path / "raw" / "etf_reports" / f"{result.document.sha256}.pdf"
    assert snapshot.read_bytes() == expected
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == result.document.sha256
    snapshot.write_bytes(b"corrupt retained snapshot")
    with pytest.raises(ValueError, match="snapshot is corrupt"):
        module.import_etf_report(EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=source, destination=tmp_path / "reports.parquet", registry_destination=tmp_path / "registry.parquet", conflict_destination=tmp_path / "conflicts.parquet", raw_dir=tmp_path / "raw"))


def test_report_atomic_group_rolls_back_report_registry_conflict_and_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.core import atomic_io
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest

    source = tmp_path / "report.pdf"
    source.write_bytes(b"atomic snapshot")
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    request = EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=source, destination=tmp_path / "reports.parquet", registry_destination=tmp_path / "registry.parquet", conflict_destination=tmp_path / "conflicts.parquet", raw_dir=tmp_path / "raw")
    imported = module.import_etf_report(request)
    snapshot = tmp_path / "raw" / "etf_reports" / f"{imported.document.sha256}.pdf"
    paths = (request.destination, request.destination.with_suffix(".csv"), request.registry_destination, request.registry_destination.with_suffix(".csv"), request.conflict_destination, request.conflict_destination.with_suffix(".csv"), snapshot)
    prior = {path: path.read_bytes() for path in paths}
    real_group = atomic_io.atomic_write_group

    def fail_snapshot_stage(requests, **kwargs):
        changed = []
        for item in tuple(requests):
            validator = (lambda _path: (_ for _ in ()).throw(OSError("snapshot validation failed"))) if item.destination.resolve() == snapshot.resolve() else item.validator
            changed.append(atomic_io.AtomicWriteRequest(item.destination, item.payload, validator))
        return real_group(tuple(changed), **kwargs)

    monkeypatch.setattr(module, "atomic_write_group", fail_snapshot_stage)
    with pytest.raises(OSError, match="snapshot validation failed"):
        module.import_etf_report(request)
    assert {path: path.read_bytes() for path in paths} == prior


def test_review_eligibility_remains_separate_from_conflict_and_rejection_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind, fund_name="Annual" if kind == "annual_report" else "Prospectus"))
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    raw = tmp_path / "raw"
    prospectus = tmp_path / "p.pdf"
    annual = tmp_path / "a.pdf"
    prospectus.write_bytes(b"p")
    annual.write_bytes(b"a")
    first = module.import_etf_report(EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=prospectus, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw))
    first_row = module.read_etf_report_records(reports).iloc[0]
    module.review_etf_report(EtfReportReviewRequest(first.source_id, str(first_row["extraction_sha256"]), "analyst", "verified"), destination=reports, registry_destination=registry, conflict_destination=conflicts)
    second = module.import_etf_report(EtfReportImportRequest("VWCE", "annual_report", "issuer_document", source_path=annual, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=raw))
    during = module.read_etf_report_records(reports).set_index("source_id")
    assert bool(during.loc[first.source_id, "evidence_eligible"]) is True
    assert bool(during.loc[second.source_id, "evidence_eligible"]) is False
    module.review_etf_report(EtfReportReviewRequest(second.source_id, str(during.loc[second.source_id, "extraction_sha256"]), "analyst", "rejected"), destination=reports, registry_destination=registry, conflict_destination=conflicts)
    after = module.read_etf_report_records(reports).set_index("source_id")
    assert bool(after.loc[first.source_id, "evidence_eligible"]) is True
    assert bool(after.loc[second.source_id, "evidence_eligible"]) is False


@pytest.mark.parametrize(
    ("corruption", "field", "value"),
    [
        ("out_of_order", None, None),
        ("predates_known_at", None, None),
        ("stale_fingerprint", None, None),
        ("top_level_mismatch", None, None),
        ("blank_reviewer", None, None),
        ("unsupported_decision", None, None),
        ("score_authority", "score_eligible", True),
        ("execution_authority", "execution_allowed", True),
        ("manual_review_authority", "manual_review", True),
        ("evidence_authority", "evidence_eligible", False),
    ],
)
def test_review_history_corruption_fails_closed_on_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str, field: str | None, value: object) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    source = tmp_path / "report.pdf"
    source.write_bytes(b"review")
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    reports, registry, conflicts = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    imported = module.import_etf_report(EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=source, destination=reports, registry_destination=registry, conflict_destination=conflicts, raw_dir=tmp_path / "raw"))
    row = module.read_etf_report_records(reports).iloc[0]
    module.review_etf_report(EtfReportReviewRequest(imported.source_id, str(row["extraction_sha256"]), "analyst", "verified"), destination=reports, registry_destination=registry, conflict_destination=conflicts)
    frame = pd.read_parquet(reports)
    history = json.loads(frame.at[0, "review_history"])
    if corruption == "out_of_order":
        earlier = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        history.append({**history[-1], "reviewed_at": earlier})
        frame.at[0, "review_history"] = json.dumps(history)
        frame.at[0, "verified_at"] = earlier
    elif corruption == "predates_known_at":
        known_at = datetime.fromisoformat(str(frame.at[0, "known_at"]).replace("Z", "+00:00"))
        earlier = (known_at - timedelta(seconds=1)).isoformat(timespec="seconds")
        history[-1]["reviewed_at"] = earlier
        frame.at[0, "review_history"] = json.dumps(history)
        frame.at[0, "verified_at"] = earlier
    elif corruption == "stale_fingerprint":
        history[-1]["extraction_sha256"] = "0" * 64
        frame.at[0, "review_history"] = json.dumps(history)
    elif corruption == "top_level_mismatch":
        frame.at[0, "verified_by"] = "forged-reviewer"
    elif corruption == "blank_reviewer":
        history[-1]["reviewer"] = ""
        frame.at[0, "review_history"] = json.dumps(history)
    elif corruption == "unsupported_decision":
        history[-1]["decision"] = "approved"
        frame.at[0, "review_history"] = json.dumps(history)
    else:
        assert field is not None
        frame.at[0, field] = value
    frame.to_parquet(reports, index=False)

    with pytest.raises(ValueError, match="corrupt"):
        module.read_etf_report_records(reports)


@pytest.mark.parametrize("legacy_kind", ["generic", "kid", "methodology", "holdings"])
def test_report_and_other_registry_writers_preserve_all_rows_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_kind: str) -> None:
    import etf_cockpit.data.parsed_disclosures as module
    from etf_cockpit.data.fund_documents import import_etf_document
    from etf_cockpit.data.parsed_disclosures import EtfReportImportRequest, EtfReportReviewRequest

    report_source = tmp_path / "report.pdf"
    other_source = tmp_path / ("other.csv" if legacy_kind == "holdings" else "other.pdf")
    report_source.write_bytes(b"report concurrent")
    other_source.write_bytes(b"other concurrent")
    monkeypatch.setattr(module, "parse_etf_report_in_child", lambda path, kind, **_kwargs: _v2_report_result(path, kind=kind))
    registry = tmp_path / "registry.parquet"
    report_request = EtfReportImportRequest("VWCE", "prospectus", "issuer_document", source_path=report_source, destination=tmp_path / "reports.parquet", registry_destination=registry, conflict_destination=tmp_path / "conflicts.parquet", raw_dir=tmp_path / "raw")
    imported = module.import_etf_report(report_request)
    initial = module.read_etf_report_records(report_request.destination).iloc[0]
    module.review_etf_report(EtfReportReviewRequest(imported.source_id, str(initial["extraction_sha256"]), "analyst", "verified"), destination=report_request.destination, registry_destination=registry, conflict_destination=report_request.conflict_destination)
    expected_history = module.read_etf_report_records(report_request.destination).iloc[0]["review_history"]
    barrier = Barrier(2)

    def report_writer() -> None:
        barrier.wait()
        module.import_etf_report(report_request)

    def other_writer() -> None:
        barrier.wait()
        if legacy_kind == "generic":
            import_etf_document(other_source, instrument_id="LYP6", document_type="factsheet", destination=registry)
        elif legacy_kind == "kid":
            module.persist_priips_kid_with_document(_kid_result(), "LYP6", other_source, destination=tmp_path / "kids.parquet", registry_destination=registry)
        elif legacy_kind == "methodology":
            module.persist_index_methodology_with_document(_methodology_result(), "LYP6", other_source, destination=tmp_path / "methods.parquet", registry_destination=registry)
        else:
            from etf_cockpit.data.fund_holdings import import_etf_holdings_with_document

            pd.DataFrame({"security": ["Concurrent"], "ticker": ["OTHER"], "weight": [1.0]}).to_csv(other_source, index=False)
            import_etf_holdings_with_document(
                other_source,
                "LYP6",
                "2026-08-01",
                holdings_destination=tmp_path / "holdings.parquet",
                registry_destination=registry,
                today="2026-08-02",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(report_writer), pool.submit(other_writer))
        for future in futures:
            future.result(timeout=20)
    stored = pd.read_parquet(registry)
    assert stored.loc[stored["source_id"].astype(str).str.startswith("report:v2:")].shape[0] == 1
    assert stored.loc[(stored["instrument_id"] == "LYP6") & (stored["coverage_status"] == "available")].shape[0] == 1
    retained = module.read_etf_report_records(report_request.destination).iloc[0]
    assert retained["verification_status"] == "verified"
    assert retained["review_history"] == expected_history
