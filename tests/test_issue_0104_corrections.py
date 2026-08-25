from __future__ import annotations

from datetime import date
import json
import inspect
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

import etf_cockpit.services as services
from etf_cockpit.app.selectors.instrument_detail import (
    InstrumentDetailViewModel,
    _SECTION_NAMES,
    _etf_structure_panel,
    _score_panel,
    build_etf_structure_panel,
)
from etf_cockpit.app.pages.instrument_detail import render_etf_structure_panel
from etf_cockpit.backtest.engine import BacktestReport, backtest_input_checksum, run_backtest
from etf_cockpit.backtest.metrics import performance_metrics
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.signals.quality_momentum import FRAME_COLUMNS, QUALITY_MOMENTUM_VERSION


@pytest.mark.parametrize("value", ["0.4%", "0.40 %", "0.4junk", "-0.4", "+0.4", "1e-1"])
def test_numeric_report_fields_require_a_complete_bare_decimal_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from etf_cockpit.parsers.etf_report import parse_etf_report

    class Page:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class Pdf:
        def __enter__(self) -> "Pdf":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @property
        def pages(self) -> list[Page]:
            return [Page(
                "ETF Prospectus\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026\n"
                "Legal structure: Irish UCITS investment company\n"
                f"Exposure: {value}\nCollateral fraction: {value}\nHaircut fraction: {value}\n"
                f"Concentration limit fraction: {value}"
            )]

    source = tmp_path / "report.pdf"
    source.write_bytes(b"numeric token")
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: Pdf()))

    result = parse_etf_report(source, "prospectus", expected_isin="IE00B4L5Y983")
    evidence = {item.field_name: item for item in result.records[0].field_evidence}

    assert result.success is True
    assert all(evidence[field].status == "malformed" for field in (
        "exposure", "collateral_fraction", "haircut_fraction", "concentration_limit_fraction",
    ))
    assert all(evidence[field].value is None for field in (
        "exposure", "collateral_fraction", "haircut_fraction", "concentration_limit_fraction",
    ))


def test_score_panel_prefers_current_structurally_capped_signal_confidence_including_zero() -> None:
    class Signal:
        blocked_by = []
        authority_decision = None
        total_score = 0.8
        canonical_score = None
        research_state = "available"
        reason_long = "Current signal evidence."
        warnings = []
        supporting_metrics = {"canonical_evidence_confidence_10": 0.0}

    panel = _score_panel(
        Signal(),
        {
            "canonical_evidence_confidence_10": 9.0,
            "final_label": "hold",
            "one_line_reason": "Current signal evidence.",
            "freshness_status": "fresh",
        },
        {"crowding": {}, "attribution": {}},
        {},
    )

    assert panel["canonical_evidence_confidence_10"] == 0.0


def test_instrument_detail_standard_loading_reaches_local_factsheet_and_holdings_structure(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector
    from etf_cockpit.data.fund_holdings import normalise_holdings

    registry = pd.DataFrame(
        [
            {
                "instrument_id": "ETF-1",
                "source_id": "factsheet-1",
                "document_type": "factsheet",
                "document_kind": "factsheet",
                "sha256": "a" * 64,
                "checksum": "a" * 64,
                "document_date": "2026-07-01",
                "known_at": "2026-07-02T00:00:00Z",
                "coverage_status": "available",
            },
            {
                "instrument_id": "ETF-1",
                "source_id": "holdings-1",
                "document_type": "holdings",
                "document_kind": "holdings",
                "sha256": "b" * 64,
                "checksum": "b" * 64,
                "document_date": "2026-07-01",
                "known_at": "2026-07-02T00:00:00Z",
                "coverage_status": "available",
            },
        ]
    )
    factsheet = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "factsheet-1", "document_type": "factsheet",
        "checksum": "a" * 64, "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z",
        "field_name": "replication_method", "value": "Physical", "page": 1, "confidence": "high", "status": "extracted",
    }])
    holdings = normalise_holdings(
        pd.DataFrame([{
            "security": "Synthetic holding", "ticker": "SYN", "weight": 1.0,
            "field_name": "replication_method", "value": "Synthetic swap", "page": 1,
            "confidence": "high", "status": "extracted",
        }]),
        "ETF-1",
        "2026-07-01",
        "issuer",
        today="2026-07-02",
    ).frame
    holdings.insert(0, "schema_version", 1)
    holdings["document_source_id"] = "holdings-1"
    holdings["document_type"] = "holdings"
    holdings["document_checksum"] = "b" * 64
    holdings["document_date"] = "2026-07-01"
    holdings["document_known_at"] = "2026-07-02T00:00:00Z"
    factsheet_path = tmp_path / "etf_metadata.parquet"
    holdings_path = tmp_path / "fund_holdings.parquet"
    factsheet.to_parquet(factsheet_path, index=False)
    holdings.to_parquet(holdings_path, index=False)
    monkeypatch.setattr(selector, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(selector, "FUND_HOLDINGS_PATH", holdings_path)

    projection = _etf_structure_panel(
        "ETF-1",
        document_registry=registry,
        report_records=pd.DataFrame(),
    )

    assert projection["fields"]["replication_method"]["status"] == "conflict"
    assert {projection["documents"][family]["status"] for family in ("factsheet", "holdings")} == {"available"}
    assert projection["execution_allowed"] is False


@pytest.mark.parametrize("corrupt_kind", ["factsheet", "holdings"])
def test_instrument_detail_malformed_canonical_structure_is_unavailable(tmp_path, monkeypatch, corrupt_kind: str) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    factsheet_path = tmp_path / "etf_metadata.parquet"
    holdings_path = tmp_path / "fund_holdings.parquet"
    corrupt_path = factsheet_path if corrupt_kind == "factsheet" else holdings_path
    corrupt_path.write_bytes(b"not a parquet file")
    monkeypatch.setattr(selector, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(selector, "FUND_HOLDINGS_PATH", holdings_path)

    projection = selector._etf_structure_panel(
        "ETF-1",
        document_registry=pd.DataFrame(),
        report_records=pd.DataFrame(),
        supplemental_rows=pd.DataFrame(),
        holdings=None,
    )

    assert projection["status"] == "unavailable"
    assert projection["flags"] == ["structure_evidence_invalid"]
    assert projection["evidence_confidence_cap"] == 0.0
    assert projection["execution_allowed"] is False


@pytest.mark.parametrize("corrupt_kind", ["factsheet", "holdings"])
def test_instrument_detail_schema_malformed_canonical_structure_is_unavailable(tmp_path, monkeypatch, corrupt_kind: str) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    factsheet_path = tmp_path / "etf_metadata.parquet"
    holdings_path = tmp_path / "fund_holdings.parquet"
    corrupt_path = factsheet_path if corrupt_kind == "factsheet" else holdings_path
    pd.DataFrame({"broken": [1]}).to_parquet(corrupt_path, index=False)
    monkeypatch.setattr(selector, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(selector, "FUND_HOLDINGS_PATH", holdings_path)

    projection = selector._etf_structure_panel(
        "ETF-1",
        document_registry=pd.DataFrame(),
        report_records=pd.DataFrame(),
        supplemental_rows=pd.DataFrame(),
        holdings=None,
    )

    assert projection["status"] == "unavailable"
    assert projection["execution_allowed"] is False


def test_missing_optional_holdings_preserves_valid_factsheet_evidence(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    factsheet_path = tmp_path / "etf_metadata.parquet"
    pd.DataFrame([{
        "instrument_id": "ETF-1",
        "source_id": "factsheet-1",
        "document_type": "factsheet",
        "checksum": "a" * 64,
        "document_date": "2026-07-01",
        "known_at": "2026-07-02T00:00:00Z",
        "field_name": "replication_method",
        "value": "Physical",
        "page": 1,
        "confidence": "high",
        "status": "extracted",
    }]).to_parquet(factsheet_path, index=False)
    monkeypatch.setattr(selector, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(selector, "FUND_HOLDINGS_PATH", tmp_path / "missing-holdings.parquet")
    registry = pd.DataFrame([{
        "instrument_id": "ETF-1",
        "source_id": "factsheet-1",
        "document_type": "factsheet",
        "document_kind": "factsheet",
        "sha256": "a" * 64,
        "checksum": "a" * 64,
        "document_date": "2026-07-01",
        "known_at": "2026-07-02T00:00:00Z",
    }])

    projection = selector._etf_structure_panel(
        "ETF-1",
        document_registry=registry,
        report_records=pd.DataFrame(),
        supplemental_rows=None,
        holdings=None,
    )

    assert projection["fields"]["replication_method"]["status"] == "resolved"
    assert projection["fields"]["replication_method"]["value"] == "Physical"
    assert projection["execution_allowed"] is False


def test_holdings_with_instrument_id_and_unrelated_columns_fail_closed_at_structural_root(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector
    from etf_cockpit.data.etf_structure import load_local_structural_evidence, structure_confidence_caps

    holdings_path = tmp_path / "fund_holdings.parquet"
    pd.DataFrame({"instrument_id": ["ETF-1"], "unrelated": ["not canonical holdings"]}).to_parquet(
        holdings_path, index=False
    )
    factsheet_path = tmp_path / "missing-factsheet.parquet"

    with pytest.raises(ValueError, match="missing required columns"):
        load_local_structural_evidence(
            registry_reader=pd.DataFrame,
            report_reader=pd.DataFrame,
            factsheet_path=factsheet_path,
            holdings_path=holdings_path,
        )

    monkeypatch.setattr(selector, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(selector, "FUND_HOLDINGS_PATH", holdings_path)
    projection = selector._etf_structure_panel(
        "ETF-1",
        document_registry=pd.DataFrame(),
        report_records=pd.DataFrame(),
        supplemental_rows=None,
        holdings=None,
    )

    assert projection["status"] == "unavailable"
    assert projection["evidence_confidence_cap"] == 0.0
    assert projection["execution_allowed"] is False
    caps = structure_confidence_caps(["ETF-1"], holdings=pd.DataFrame({"instrument_id": ["ETF-1"], "unrelated": ["x"]}))
    assert caps["ETF-1"] == 0.0


def test_holdings_with_complete_columns_but_invalid_row_fail_closed_at_structural_root(tmp_path) -> None:
    from etf_cockpit.data.etf_structure import load_local_structural_evidence

    holdings_path = tmp_path / "fund_holdings.parquet"
    pd.DataFrame([{
        "schema_version": 1,
        "security": "Holding A",
        "ticker": "A",
        "weight": 1.0,
        "instrument_id": "ETF-1",
        "as_of": "2026-07-01",
        "source": "",
        "source_id": "fundhold:invalid",
        "completeness": "full",
        "freshness": "fresh",
        "confidence": 1.0,
        "authority": "issuer",
        "score_eligible": True,
    }]).to_parquet(holdings_path, index=False)

    with pytest.raises(ValueError, match="missing row provenance=source"):
        load_local_structural_evidence(
            registry_reader=pd.DataFrame,
            report_reader=pd.DataFrame,
            factsheet_path=tmp_path / "missing-factsheet.parquet",
            holdings_path=holdings_path,
        )


def test_empty_existing_holdings_without_schema_fail_closed_at_structural_root(tmp_path) -> None:
    from etf_cockpit.data.etf_structure import load_local_structural_evidence

    holdings_path = tmp_path / "fund_holdings.parquet"
    pd.DataFrame(columns=["instrument_id"]).to_parquet(holdings_path, index=False)

    with pytest.raises(ValueError, match="missing required columns"):
        load_local_structural_evidence(
            registry_reader=pd.DataFrame,
            report_reader=pd.DataFrame,
            factsheet_path=tmp_path / "missing-factsheet.parquet",
            holdings_path=holdings_path,
        )


def test_real_canonical_writers_preserve_bindings_through_shared_projection_and_backtest(tmp_path) -> None:
    from etf_cockpit.backtest.engine import backtest_input_checksum, run_backtest
    from etf_cockpit.data.etf_structure import load_local_structural_evidence, project_etf_structure, structure_confidence_caps
    from etf_cockpit.data.fund_documents import import_etf_document
    from etf_cockpit.data.fund_holdings import import_etf_holdings_with_document
    from etf_cockpit.data.providers import ManualLocalFileProvider
    from etf_cockpit.data.reference_data import commit_reference_import

    registry_path = tmp_path / "fund_documents.parquet"
    factsheet_document = tmp_path / "factsheet.pdf"
    factsheet_document.write_bytes(b"issuer factsheet")
    registered_factsheet = import_etf_document(
        factsheet_document,
        instrument_id="ETF-1",
        document_type="factsheet",
        document_date="2026-07-10",
        destination=registry_path,
        configured_instrument_ids=["ETF-1"],
    )
    factsheet_source = tmp_path / "factsheet.csv"
    pd.DataFrame([{
        "as_of_date": "2026-07-10",
        "etf_id": "ETF-1",
        "source_id": registered_factsheet.source_id,
        "checksum": registered_factsheet.sha256,
        "document_date": registered_factsheet.document_date,
        "known_at": registered_factsheet.ingested_at,
        "page": 1,
        "status": "extracted",
        "confidence": "high",
        "field_name": "domicile",
        "value": "Ireland",
    }]).to_csv(factsheet_source, index=False)
    factsheet_result = ManualLocalFileProvider().import_file(factsheet_source, "etf_metadata")
    factsheet_path = tmp_path / "etf_metadata.parquet"
    commit_reference_import(factsheet_result, "etf_metadata", clean_path=factsheet_path, raw_dir=tmp_path / "raw", snapshots_dir=tmp_path / "snapshots")

    holdings_source = tmp_path / "holdings.csv"
    pd.DataFrame([
        {"security": "A", "ticker": "A", "weight": 0.6, "field_name": "legal_form", "value": "ICAV", "page": 2, "confidence": "high", "status": "extracted"},
        {"security": "B", "ticker": "B", "weight": 0.4, "field_name": "legal_form", "value": "ICAV", "page": 2, "confidence": "high", "status": "extracted"},
    ]).to_csv(holdings_source, index=False)
    holdings_path = tmp_path / "fund_holdings.parquet"
    import_etf_holdings_with_document(
        holdings_source,
        "ETF-1",
        "2026-07-10",
        holdings_destination=holdings_path,
        registry_destination=registry_path,
        today="2026-07-11",
    )
    registry = pd.read_parquet(registry_path)
    stored_holdings = pd.read_parquet(holdings_path)
    assert stored_holdings["source_id"].astype(str).str.startswith("fundhold:").all()
    assert stored_holdings["document_source_id"].nunique() == 1

    evidence = load_local_structural_evidence(
        registry_reader=lambda: registry,
        report_reader=pd.DataFrame,
        factsheet_path=factsheet_path,
        holdings_path=holdings_path,
    )
    projection = project_etf_structure(
        "ETF-1",
        document_registry=evidence.document_registry,
        report_records=evidence.report_records,
        supplemental_rows=evidence.supplemental_rows,
        holdings=evidence.holdings,
    )
    assert projection["fields"]["domicile"]["document_id"] == registered_factsheet.source_id
    assert projection["fields"]["legal_form"]["document_id"] == stored_holdings["document_source_id"].iloc[0]
    assert projection["execution_allowed"] is False

    caps = structure_confidence_caps(["ETF-1"], document_registry=registry, supplemental_rows=evidence.supplemental_rows, holdings=evidence.holdings)
    assert caps["ETF-1"] > 0.0
    assert caps.provenance["ETF-1"]["structure_provenance_hash"] != "unavailable"
    config = services.load_config()
    prices = generate_sample_prices(config, periods=260, end_date=date(2026, 7, 10))
    report = run_backtest(config, prices, structure_document_registry=registry, structure_supplemental_rows=evidence.supplemental_rows, structure_holdings=evidence.holdings)
    assert report.metadata["input_checksum"] == backtest_input_checksum(config, prices, pd.DataFrame(), structure_document_registry=registry, structure_supplemental_rows=evidence.supplemental_rows, structure_holdings=evidence.holdings)


def test_report_legal_form_conflict_is_cross_kind_and_not_temporally_invented() -> None:
    from etf_cockpit.data.parsed_disclosures import build_etf_report_conflicts

    rows = pd.DataFrame([
        {"instrument_id": "ETF-1", "source_id": "prospectus-1", "document_kind": "prospectus", "document_date": "2025-01-01", "imported_at": "2025-01-02", "legal_form": "ICAV", "verification_status": "verified"},
        {"instrument_id": "ETF-1", "source_id": "annual-1", "document_kind": "annual_report", "document_date": "2026-01-01", "imported_at": "2026-01-02", "legal_form": "Unit trust", "verification_status": "verified"},
    ])

    conflicts = build_etf_report_conflicts(rows)

    legal = conflicts.loc[conflicts["field_name"].eq("legal_form")]
    assert len(legal) == 1
    assert set(legal[["document_kind_a", "document_kind_b"]].iloc[0]) == {"prospectus", "annual_report"}
    assert legal.iloc[0]["reporting_period_end"] == ""


def test_cross_kind_stable_conflict_remains_unusable_in_canonical_projection() -> None:
    from etf_cockpit.data.etf_structure import project_etf_structure
    from etf_cockpit.data.parsed_disclosures import report_extraction_fingerprint

    checksum_a, checksum_b = "a" * 64, "b" * 64
    registry = pd.DataFrame([
        {"instrument_id": "ETF-1", "source_id": "prospectus-1", "document_type": "prospectus_report", "document_kind": "prospectus", "authority": "issuer_document", "sha256": checksum_a, "document_date": "2025-01-01", "known_at": "2025-01-02T00:00:00Z", "coverage_status": "available"},
        {"instrument_id": "ETF-1", "source_id": "annual-1", "document_type": "prospectus_report", "document_kind": "annual_report", "authority": "issuer_document", "sha256": checksum_b, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z", "coverage_status": "available"},
    ])

    def report(source_id: str, kind: str, checksum: str, value: str, document_date: str, known_at: str) -> dict[str, object]:
        evidence = [
            {"field_name": "fund_name", "value": "ETF One", "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
            {"field_name": "isin", "value": "IE00TEST0001", "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
            {"field_name": "document_date", "value": document_date, "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
            {"field_name": "legal_form", "value": value, "source_page": 2, "candidate_pages": [2], "confidence": "high", "status": "extracted"},
        ]
        if kind == "annual_report":
            evidence.append({"field_name": "reporting_period_end", "value": document_date, "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"})
        row = {
            "schema_version": 2.1,
            "instrument_id": "ETF-1", "source_id": source_id, "document_type": "prospectus_report", "document_kind": kind,
            "source_sha256": checksum, "source_authority": "issuer_document", "document_date": document_date, "known_at": known_at,
            "verification_status": "verified", "evidence_eligible": True, "extraction_sha256": "c" * 64,
            "stored_extraction_sha256": "c" * 64,
            "verified_by": "analyst", "verified_at": known_at, "review_note": "",
            "manual_review": False, "score_eligible": False, "execution_allowed": False,
            "extraction_status": "complete", "parse_success": True, "warnings": "[]",
            "review_history": json.dumps([{"decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": known_at, "extraction_sha256": "c" * 64}]),
            "field_evidence": json.dumps(evidence),
        }
        fingerprint = report_extraction_fingerprint(pd.Series(row))
        row["extraction_sha256"] = fingerprint
        row["stored_extraction_sha256"] = fingerprint
        row["review_history"] = json.dumps([{**item, "extraction_sha256": fingerprint} for item in json.loads(row["review_history"])])
        return row

    reports = pd.DataFrame([
        report("prospectus-1", "prospectus", checksum_a, "ICAV", "2025-01-01", "2025-01-02T00:00:00Z"),
        report("annual-1", "annual_report", checksum_b, "Unit trust", "2026-01-01", "2026-01-02T00:00:00Z"),
    ])

    projection = project_etf_structure("ETF-1", document_registry=registry, report_records=reports, decision_time="2026-02-01T00:00:00Z")

    assert projection["fields"]["legal_form"]["status"] == "conflict"
    assert projection["fields"]["legal_form"]["value"] is None
    assert projection["fields"]["legal_form"]["confidence"] == 0.0
    assert projection["evidence_confidence_cap"] == 0.0


def test_inconsistent_current_review_state_fails_closed_through_supplied_facade() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    checksum = "a" * 64
    registry = pd.DataFrame([{"instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus", "sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z", "coverage_status": "available"}])
    history = [{"decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": "2026-01-03T00:00:00Z", "extraction_sha256": "b" * 64}]
    reports = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus",
        "source_sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z",
        "verification_status": "rejected", "evidence_eligible": False, "extraction_sha256": "b" * 64, "stored_extraction_sha256": "b" * 64,
        "review_history": json.dumps(history),
        "field_evidence": json.dumps([{"field_name": "legal_form", "value": "ICAV", "source_page": 1, "confidence": "high", "status": "extracted"}]),
    }])

    projection = load_etf_structure_projection(
        "ETF-1", document_registry=registry, report_records=reports, decision_time="2026-01-04T00:00:00Z"
    )

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["fields"]["legal_form"]["value"] is None


def _valid_supplied_structure_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    from test_etf_structure import _registry, _report

    return _registry(), _report()


def test_supplied_facade_rejects_structural_field_mutation_without_fingerprint_update() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    registry, reports = _valid_supplied_structure_inputs()
    evidence = json.loads(reports.loc[0, "field_evidence"])
    next(item for item in evidence if item["field_name"] == "legal_form")["value"] = "Forged legal form"
    reports.loc[0, "field_evidence"] = json.dumps(evidence)

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["stress"]["status"] == "unavailable"
    assert projection["execution_allowed"] is False


def test_supplied_facade_rejects_numeric_quartet_mutation_without_fingerprint_update() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    registry, reports = _valid_supplied_structure_inputs()
    evidence = json.loads(reports.loc[0, "field_evidence"])
    next(item for item in evidence if item["field_name"] == "exposure")["value"] = "0.9"
    reports.loc[0, "field_evidence"] = json.dumps(evidence)

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=reports)

    assert projection["stress"]["status"] == "unavailable"
    assert projection["fields"]["replication_method"]["status"] == "unknown"
    assert projection["execution_allowed"] is False


def test_supplied_facade_rejects_malformed_review_authority_flags() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    registry, reports = _valid_supplied_structure_inputs()
    reports["score_eligible"] = reports["score_eligible"].astype(object)
    reports.loc[0, "score_eligible"] = "false"

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["evidence_confidence_cap"] == 0.0
    assert projection["execution_allowed"] is False


def test_supplied_facade_rejects_duplicate_report_source_ids() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    registry, reports = _valid_supplied_structure_inputs()
    reports = pd.concat([reports, reports], ignore_index=True)

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["evidence_confidence_cap"] == 0.0
    assert projection["execution_allowed"] is False


@pytest.mark.parametrize("mutation", ["manual_review", "unverifiable", "review_metadata"])
def test_supplied_facade_enforces_canonical_review_and_verifiability_semantics(mutation: str) -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection
    from test_etf_structure import _refresh_report_fingerprint

    registry, reports = _valid_supplied_structure_inputs()
    if mutation == "manual_review":
        reports.loc[0, "manual_review"] = True
    elif mutation == "unverifiable":
        reports.loc[0, "extraction_status"] = "incomplete"
        _refresh_report_fingerprint(reports)
    else:
        reports.loc[0, "verified_at"] = "2026-07-03T00:00:00+00:00"

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["evidence_confidence_cap"] == 0.0
    assert projection["execution_allowed"] is False


def test_duplicate_report_columns_fail_closed_before_projection_caps_and_cache_identity() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection
    from etf_cockpit.data.etf_structure import structure_confidence_caps, structure_input_checksum

    registry, reports = _valid_supplied_structure_inputs()
    valid_checksum = structure_input_checksum(document_registry=registry, report_records=reports)
    malformed = pd.concat([reports, reports[["field_evidence"]]], axis=1)

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=malformed)
    caps = structure_confidence_caps(["ETF-1"], document_registry=registry, report_records=malformed)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert caps["ETF-1"] == 0.0
    assert valid_checksum
    with pytest.raises(ValueError, match="duplicate columns"):
        structure_input_checksum(document_registry=registry, report_records=malformed)


def test_non_mapping_supplied_report_member_fails_closed_without_discarding_it() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection
    from etf_cockpit.data.etf_structure import structure_confidence_caps, structure_input_checksum

    registry, reports = _valid_supplied_structure_inputs()
    malformed = [*reports.to_dict("records"), "not-a-report-row"]

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=malformed)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert structure_confidence_caps(["ETF-1"], document_registry=registry, report_records=malformed)["ETF-1"] == 0.0
    with pytest.raises(ValueError, match="non-mapping member"):
        structure_input_checksum(document_registry=registry, report_records=malformed)


@pytest.mark.parametrize(
    ("registry_field", "replacement", "reason_code"),
    [
        ("document_kind", "annual_report", "candidate_document_kind_mismatch"),
        ("authority", "local_user_import", "candidate_source_authority_mismatch"),
    ],
)
def test_supplied_report_requires_exact_registry_kind_and_authority_binding(
    registry_field: str, replacement: str, reason_code: str
) -> None:
    from etf_cockpit.data.etf_structure import project_etf_structure

    registry, reports = _valid_supplied_structure_inputs()
    registry.loc[0, registry_field] = replacement

    projection = project_etf_structure("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert any(item["reason_code"] == reason_code for item in projection["rejected_candidates"])


@pytest.mark.parametrize("value", ["1e-1", "0.1%", "0.1 suffix", "0.1 trailing"])
def test_supplied_numeric_evidence_requires_complete_bare_decimal_grammar(value: str) -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection
    from test_etf_structure import _refresh_report_fingerprint

    registry, reports = _valid_supplied_structure_inputs()
    evidence = json.loads(reports.loc[0, "field_evidence"])
    next(item for item in evidence if item["field_name"] == "exposure")["value"] = value
    reports.loc[0, "field_evidence"] = json.dumps(evidence)
    _refresh_report_fingerprint(reports)

    projection = load_etf_structure_projection("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "resolved"
    assert projection["stress"]["status"] == "unavailable"
    assert projection["execution_allowed"] is False


def test_registry_source_id_duplicates_are_rejected_across_instruments() -> None:
    from etf_cockpit.data.etf_structure import project_etf_structure, structure_confidence_caps

    registry, reports = _valid_supplied_structure_inputs()
    other = registry.copy()
    other.loc[0, "instrument_id"] = "ETF-2"
    duplicate_registry = pd.concat([registry, other], ignore_index=True)

    projection = project_etf_structure("ETF-1", document_registry=duplicate_registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert any(item["reason_code"] == "duplicate_registry_source_id" for item in projection["rejected_candidates"])
    assert structure_confidence_caps(["ETF-1"], document_registry=duplicate_registry, report_records=reports)["ETF-1"] == 0.0


def test_real_report_numeric_fields_survive_parse_import_review_readback_and_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as disclosures
    from etf_cockpit.data.etf_structure import project_etf_structure
    from etf_cockpit.parsers.etf_report import parse_etf_report

    class Page:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class Pdf:
        def __init__(self, pages: list[str]) -> None:
            self.pages = [Page(page) for page in pages]

        def __enter__(self) -> "Pdf":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: Pdf([
        "ETF Prospectus\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026\nLegal structure: Irish UCITS investment company\nDomicile: Ireland\nLegal form: Investment company",
        "Replication method: Physical full replication\nDerivatives: None\nExposure: 0.4\nCollateral fraction: 0.8\nHaircut fraction: 0.1\nConcentration limit fraction: 0.25",
    ])))

    def real_child(path: Path, kind: str, **kwargs: object):
        return parse_etf_report(
            path, kind, expected_isin=kwargs.get("expected_isin"), expected_document_date=kwargs.get("expected_document_date"),
            max_file_bytes=int(kwargs["max_file_bytes"]), max_pages=int(kwargs["max_pages"]),
            max_page_chars=int(kwargs["max_page_chars"]), max_total_chars=int(kwargs["max_total_chars"]),
        )

    monkeypatch.setattr(disclosures, "parse_etf_report_in_child", real_child)
    source = tmp_path / "report.pdf"
    source.write_bytes(b"canonical report snapshot")
    report_path, registry_path, conflict_path = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    imported = disclosures.import_etf_report(disclosures.EtfReportImportRequest(
        "ETF-1", "prospectus", "issuer_document", source_path=source, expected_isin="IE00B4L5Y983",
        destination=report_path, registry_destination=registry_path, conflict_destination=conflict_path, raw_dir=tmp_path / "raw",
    ))
    pending = disclosures.read_etf_report_records(report_path).iloc[0]
    disclosures.review_etf_report(
        disclosures.EtfReportReviewRequest(imported.source_id, str(pending["extraction_sha256"]), "analyst", "verified"),
        destination=report_path, registry_destination=registry_path, conflict_destination=conflict_path,
    )
    readback = disclosures.read_etf_report_records(report_path)
    evidence = {item["field_name"]: item for item in json.loads(str(readback.iloc[0]["field_evidence"]))}
    projection = project_etf_structure(
        "ETF-1", document_registry=pd.read_parquet(registry_path), report_records=readback,
        decision_time="2099-01-01T00:00:00Z",
    )

    assert {field: evidence[field]["unit"] for field in ("exposure", "collateral_fraction", "haircut_fraction", "concentration_limit_fraction")} == {
        "exposure": "fraction_of_nav", "collateral_fraction": "fraction_of_exposure", "haircut_fraction": "scenario_haircut_fraction", "concentration_limit_fraction": "fraction_of_collateral",
    }
    assert evidence["exposure"]["source_page"] == 2
    assert readback.iloc[0]["source_sha256"] == imported.document.sha256
    assert projection["stress"]["status"] == "available"
    assert projection["stress"]["provenance"]["exposure"]["checksum"] == imported.document.sha256
    assert projection["stress"]["provenance"]["exposure"]["page"] == 2


@pytest.mark.parametrize("value", ["0.4%", "0.40 %"])
def test_percent_labelled_numeric_fields_remain_unavailable_through_real_report_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    import etf_cockpit.data.parsed_disclosures as disclosures
    from etf_cockpit.data.etf_structure import project_etf_structure
    from etf_cockpit.parsers.etf_report import parse_etf_report

    class Page:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class Pdf:
        def __enter__(self) -> "Pdf":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @property
        def pages(self) -> list[Page]:
            return [Page(
                "ETF Prospectus\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026\n"
                "Legal structure: Irish UCITS investment company\nDomicile: Ireland\nLegal form: Investment company\n"
                "Replication method: Physical full replication\nDerivatives: None\n"
                f"Exposure: {value}\nCollateral fraction: {value}\nHaircut fraction: {value}\n"
                f"Concentration limit fraction: {value}"
            )]

    def real_child(path: Path, kind: str, **kwargs: object):
        return parse_etf_report(
            path, kind, expected_isin=kwargs.get("expected_isin"), expected_document_date=kwargs.get("expected_document_date"),
            max_file_bytes=int(kwargs["max_file_bytes"]), max_pages=int(kwargs["max_pages"]),
            max_page_chars=int(kwargs["max_page_chars"]), max_total_chars=int(kwargs["max_total_chars"]),
        )

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: Pdf()))
    monkeypatch.setattr(disclosures, "parse_etf_report_in_child", real_child)
    source = tmp_path / "report.pdf"
    source.write_bytes(b"percent-labelled report")
    report_path, registry_path, conflict_path = (tmp_path / name for name in ("reports.parquet", "registry.parquet", "conflicts.parquet"))
    imported = disclosures.import_etf_report(disclosures.EtfReportImportRequest(
        "ETF-1", "prospectus", "issuer_document", source_path=source, expected_isin="IE00B4L5Y983",
        destination=report_path, registry_destination=registry_path, conflict_destination=conflict_path, raw_dir=tmp_path / "raw",
    ))
    pending = disclosures.read_etf_report_records(report_path).iloc[0]
    disclosures.review_etf_report(
        disclosures.EtfReportReviewRequest(imported.source_id, str(pending["extraction_sha256"]), "analyst", "verified"),
        destination=report_path, registry_destination=registry_path, conflict_destination=conflict_path,
    )
    readback = disclosures.read_etf_report_records(report_path)
    evidence = {item["field_name"]: item for item in json.loads(str(readback.iloc[0]["field_evidence"]))}
    projection = project_etf_structure(
        "ETF-1", document_registry=pd.read_parquet(registry_path), report_records=readback,
        decision_time="2026-08-04T00:00:00Z",
    )

    assert all(evidence[field]["value"] is None for field in (
        "exposure", "collateral_fraction", "haircut_fraction", "concentration_limit_fraction",
    ))
    assert projection["stress"]["status"] == "unavailable"
    assert projection["execution_allowed"] is False


@pytest.mark.parametrize("history", ["not-json", json.dumps({"decision": "verified"}), json.dumps(["verified"])])
def test_malformed_review_history_remains_unknown_in_structure_projection(history: str) -> None:
    from etf_cockpit.data.etf_structure import project_etf_structure

    checksum = "a" * 64
    registry = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus",
        "sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z", "coverage_status": "available",
    }])
    reports = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus",
        "source_sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z",
        "verification_status": "verified", "verified_by": "analyst", "verified_at": "2026-01-03T00:00:00Z", "review_note": "",
        "evidence_eligible": True, "extraction_sha256": "b" * 64, "stored_extraction_sha256": "b" * 64,
        "review_history": history,
        "field_evidence": json.dumps([{"field_name": "legal_form", "value": "ICAV", "source_page": 1, "confidence": "high", "status": "extracted"}]),
    }])

    projection = project_etf_structure("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["fields"]["legal_form"]["value"] is None
    assert projection["stress"]["status"] == "unavailable"


@pytest.mark.parametrize("history_mode", ["missing", "empty"])
def test_supplied_projection_requires_a_nonempty_review_history(history_mode: str) -> None:
    from etf_cockpit.data.etf_structure import project_etf_structure

    checksum = "a" * 64
    registry = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus",
        "sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z", "coverage_status": "available",
    }])
    reports = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus",
        "source_sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z",
        "verification_status": "verified", "verified_by": "analyst", "verified_at": "2026-01-03T00:00:00Z", "review_note": "",
        "evidence_eligible": True, "extraction_sha256": "b" * 64, "stored_extraction_sha256": "b" * 64,
        "field_evidence": json.dumps([{"field_name": "legal_form", "value": "ICAV", "source_page": 1, "confidence": "high", "status": "extracted"}]),
    }])
    if history_mode == "empty":
        reports.loc[0, "review_history"] = "[]"

    projection = project_etf_structure("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["stress"]["status"] == "unavailable"


@pytest.mark.parametrize("field", ["verified_by", "verified_at", "review_note", "extraction_sha256", "verification_status", "evidence_eligible"])
def test_current_review_metadata_mismatch_remains_unknown_in_structure_projection(field: str) -> None:
    from etf_cockpit.data.etf_structure import project_etf_structure

    checksum = "a" * 64
    history = [{
        "decision": "verified", "reviewer": "analyst", "note": "audited", "reviewed_at": "2026-01-03T00:00:00Z", "extraction_sha256": "b" * 64,
    }]
    registry = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus",
        "sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z", "coverage_status": "available",
    }])
    reports = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "report-1", "document_type": "prospectus_report", "document_kind": "prospectus",
        "source_sha256": checksum, "document_date": "2026-01-01", "known_at": "2026-01-02T00:00:00Z",
        "verification_status": "verified", "verified_by": "analyst", "verified_at": "2026-01-03T00:00:00Z", "review_note": "audited",
        "evidence_eligible": True, "extraction_sha256": "b" * 64, "stored_extraction_sha256": "b" * 64,
        "review_history": json.dumps(history),
        "field_evidence": json.dumps([{"field_name": "legal_form", "value": "ICAV", "source_page": 1, "confidence": "high", "status": "extracted"}]),
    }])
    replacements = {
        "verified_by": "forged-reviewer", "verified_at": "2026-01-04T00:00:00Z", "review_note": "forged-note",
        "extraction_sha256": "c" * 64, "verification_status": "rejected", "evidence_eligible": False,
    }
    reports.loc[0, field] = replacements[field]

    projection = project_etf_structure("ETF-1", document_registry=registry, report_records=reports)

    assert projection["fields"]["legal_form"]["status"] == "unknown"
    assert projection["fields"]["legal_form"]["value"] is None


def test_numeric_stress_does_not_mix_partial_quartets_across_report_revisions() -> None:
    from etf_cockpit.data.etf_structure import project_etf_structure
    from test_etf_structure import _refresh_report_fingerprint, _registry, _report

    checksum_b = "b" * 64
    registry_a = _registry(source_id="prospectus-1", document_date="2026-01-01", known_at="2026-01-02T00:00:00Z")
    registry_b = _registry(source_id="prospectus-2", document_date="2026-02-01", known_at="2026-02-02T00:00:00Z")
    registry_b.loc[0, ["sha256", "checksum"]] = checksum_b
    registry = pd.concat([registry_a, registry_b], ignore_index=True)
    report_a = _report(source_id="prospectus-1", document_date="2026-01-01", known_at="2026-01-02T00:00:00Z")
    report_b = _report(source_id="prospectus-2", document_date="2026-02-01", known_at="2026-02-02T00:00:00Z")
    report_b.loc[0, "source_sha256"] = checksum_b
    for report, excluded in (
        (report_a, {"haircut_fraction", "concentration_limit_fraction"}),
        (report_b, {"exposure", "collateral_fraction"}),
    ):
        evidence = [
            item for item in json.loads(report.loc[0, "field_evidence"])
            if item["field_name"] not in excluded
        ]
        report.loc[0, "field_evidence"] = json.dumps(evidence)
        _refresh_report_fingerprint(report)
    reports = pd.concat([report_a, report_b], ignore_index=True)

    projection = project_etf_structure("ETF-1", document_registry=registry, report_records=reports)

    assert projection["stress"]["status"] == "unavailable"
    assert "provenance" not in projection["stress"]


def test_instrument_detail_keeps_required_structure_section() -> None:
    model = InstrumentDetailViewModel(
        instrument_id="ETF-1",
        display_name="ETF 1",
        status="ready",
        identity={},
        sections={"etf_structure": {"status": "available", "execution_allowed": False}},
    )

    assert "etf_structure" in _SECTION_NAMES
    assert build_etf_structure_panel(model)["status"] == "available"
    assert build_etf_structure_panel(model)["execution_allowed"] is False


def test_instrument_detail_renders_complete_conflict_candidate_provenance() -> None:
    model = InstrumentDetailViewModel(
        instrument_id="ETF-1",
        display_name="ETF 1",
        status="ready",
        identity={},
        sections={
            "etf_structure": {
                "status": "conflict",
                "execution_allowed": False,
                "fields": {
                    "replication_method": {
                        "status": "conflict",
                        "value": None,
                        "document_id": "unavailable",
                        "document_date": "unavailable",
                        "page": None,
                        "confidence": 0.0,
                        "known_at": "unavailable",
                        "checksum": "unavailable",
                        "candidates": [
                            {
                                "value": "Physical",
                                "source_id": "source-a",
                                "document_id": "document-a",
                                "document_date": "2026-06-30",
                                "page": 4,
                                "confidence": 1.0,
                                "known_at": "2026-07-01T00:00:00+00:00",
                                "checksum": "a" * 64,
                            },
                            {
                                "value": "Synthetic swap",
                                "source_id": "source-b",
                                "document_id": "document-b",
                                "document_date": "2026-06-30",
                                "page": 8,
                                "confidence": 0.75,
                                "known_at": "2026-07-01T01:00:00+00:00",
                                "checksum": "b" * 64,
                            },
                        ],
                    },
                },
                "documents": {},
                "versions": [],
                "flags": [],
            }
        },
    )

    def text_values(node: object) -> list[str]:
        values: list[str] = []
        for attribute in ("value", "text"):
            value = getattr(node, attribute, None)
            if value:
                values.append(str(value))
        content = getattr(node, "content", None)
        if content is not None:
            values.extend(text_values(content))
        for attribute in ("controls", "rows", "cells"):
            for child in getattr(node, attribute, None) or []:
                values.extend(text_values(child))
        return values

    rendered = "\n".join(text_values(render_etf_structure_panel(model)))
    for expected in (
        "value=Physical", "source_id=source-a", "document_id=document-a", "date=2026-06-30",
        "page=4", "confidence=1.0", "known_at=2026-07-01T00:00:00+00:00", "checksum=" + "a" * 64,
        "value=Synthetic swap", "source_id=source-b", "document_id=document-b", "page=8",
        "confidence=0.75", "known_at=2026-07-01T01:00:00+00:00", "checksum=" + "b" * 64,
    ):
        assert expected in rendered


def test_real_backtest_signature_accepts_structural_holdings() -> None:
    parameters = inspect.signature(run_backtest).parameters

    assert "structure_holdings" in parameters
    assert parameters["structure_holdings"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    "invalid_id",
    [None, pd.NA, "", "nan", "None", "null", "<NA>", "UNCONFIGURED-ETF"],
)
def test_cached_structure_validation_rejects_invalid_or_unconfigured_instrument_ids(
    invalid_id: object,
) -> None:
    evidence = SimpleNamespace(
        document_registry=pd.DataFrame(),
        report_records=pd.DataFrame(),
        supplemental_rows=pd.DataFrame(),
        holdings=pd.DataFrame(),
    )
    signal_log = pd.DataFrame([{"date": "2026-07-10", "etf_id": invalid_id}])

    assert services._cached_structure_columns_match(
        signal_log,
        pd.Series([0.0]),
        pd.Series(["unavailable"]),
        evidence,
        ["ETF-1"],
    ) is False


def test_cached_structure_validation_batches_non_empty_evidence_by_decision_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Caps(dict[str, float]):
        provenance: dict[str, dict[str, str]]

    calls: list[tuple[tuple[str, ...], date]] = []

    def fake_structure_caps(
        instrument_ids: list[str],
        *,
        decision_time: date,
        **_kwargs: object,
    ) -> Caps:
        ids = tuple(instrument_ids)
        calls.append((ids, decision_time))
        result = Caps({instrument_id: 0.5 for instrument_id in ids})
        result.provenance = {
            instrument_id: {
                "structure_provenance_hash": f"{decision_time}:{instrument_id}"
            }
            for instrument_id in ids
        }
        return result

    monkeypatch.setattr(services, "structure_confidence_caps", fake_structure_caps)
    evidence = SimpleNamespace(
        document_registry=pd.DataFrame([{"source_id": "source-1"}]),
        report_records=pd.DataFrame(),
        supplemental_rows=pd.DataFrame(),
        holdings=pd.DataFrame(),
    )
    signal_log = pd.DataFrame(
        [
            {"date": "2026-07-10", "etf_id": "ETF-1"},
            {"date": "2026-07-10", "etf_id": "ETF-2"},
            {"date": "2026-07-11", "etf_id": "ETF-1"},
            {"date": "2026-07-11", "etf_id": "ETF-2"},
        ]
    )
    stored_caps = pd.Series([0.5] * len(signal_log))
    stored_hashes = pd.Series(
        [f"{row.date()}:{instrument_id}" for row, instrument_id in zip(pd.to_datetime(signal_log["date"]), signal_log["etf_id"], strict=True)]
    )

    assert services._cached_structure_columns_match(
        signal_log, stored_caps, stored_hashes, evidence, ["ETF-1", "ETF-2"]
    ) is True
    assert calls == [
        (("ETF-1", "ETF-2"), date(2026, 7, 10)),
        (("ETF-1", "ETF-2"), date(2026, 7, 11)),
    ]

    calls.clear()
    tampered_hashes = stored_hashes.copy()
    tampered_hashes.iloc[-1] = "tampered"
    assert services._cached_structure_columns_match(
        signal_log, stored_caps, tampered_hashes, evidence, ["ETF-1", "ETF-2"]
    ) is False
    assert calls == [
        (("ETF-1", "ETF-2"), date(2026, 7, 10)),
        (("ETF-1", "ETF-2"), date(2026, 7, 11)),
    ]


def test_cached_structure_validation_rejects_future_holdings_confidence() -> None:
    checksum = "a" * 64
    evidence = SimpleNamespace(
        document_registry=pd.DataFrame(
            [
                {
                    "instrument_id": "ETF-1",
                    "source_id": "holdings-1",
                    "document_type": "holdings",
                    "document_kind": "holdings",
                    "authority": "issuer_document",
                    "sha256": checksum,
                    "checksum": checksum,
                    "document_date": "2026-07-20",
                    "known_at": "2026-07-02T00:00:00Z",
                    "coverage_status": "available",
                    "document_version": "v1",
                }
            ]
        ),
        report_records=pd.DataFrame(),
        supplemental_rows=pd.DataFrame(),
        holdings=pd.DataFrame(
            [
                {
                    "instrument_id": "ETF-1",
                    "document_source_id": "holdings-1",
                    "document_type": "holdings",
                    "document_checksum": checksum,
                    "document_date": "2026-07-20",
                    "document_known_at": "2026-07-02T00:00:00Z",
                    "as_of": "2026-07-20",
                    "field_name": "replication_method",
                    "value": "Physical sampled",
                    "page": 3,
                    "structural_confidence": 1.0,
                    "status": "extracted",
                    "freshness": "fresh",
                    "completeness": "full",
                    "authority": "issuer",
                    "score_eligible": True,
                }
            ]
        ),
    )

    assert services._cached_structure_columns_match(
        pd.DataFrame([{"date": "2026-07-15", "etf_id": "ETF-1"}]),
        pd.Series([1.0]),
        pd.Series(["forged-future-confidence"]),
        evidence,
        ["ETF-1"],
    ) is False


def test_real_260_session_backtest_accepts_structural_holdings() -> None:
    from etf_cockpit.data.etf_structure import structure_confidence_caps

    config = services.load_config()
    prices = generate_sample_prices(config, periods=260, end_date=date(2026, 7, 10))
    holdings = pd.DataFrame([{
        "security": "Test holding", "weight": 0.4, "instrument_id": config.universe.enabled_ids[0],
        "as_of": "2026-07-10", "source": "test", "source_id": "holdings-1",
        "completeness": "complete", "freshness": "fresh", "confidence": 1.0,
        "authority": "issuer_document", "score_eligible": False,
    }])

    report = run_backtest(config, prices, structure_holdings=holdings)

    assert report.metadata["complete_price_rows"] == 260
    assert report.metadata["input_checksum"] == backtest_input_checksum(
        config, prices, pd.DataFrame(), structure_holdings=holdings
    )
    assert not report.signal_log.empty
    assert {"structural_confidence_cap", "structural_provenance_hash"}.issubset(report.signal_log.columns)
    assert report.signal_log["structural_confidence_cap"].between(0.0, 1.0).all()
    assert report.signal_log["structural_provenance_hash"].astype(str).str.len().gt(0).all()
    for row in report.signal_log.to_dict("records"):
        caps = structure_confidence_caps(
            [row["etf_id"]], holdings=holdings, decision_time=row["date"]
        )
        assert row["structural_confidence_cap"] == caps[row["etf_id"]]
        assert row["structural_provenance_hash"] == caps.provenance[row["etf_id"]][
            "structure_provenance_hash"
        ]


def test_backtest_service_reads_holdings_for_run_and_invalidates_cache(tmp_path, monkeypatch) -> None:
    from etf_cockpit.data.fund_holdings import normalise_holdings

    config = services.load_config()
    prices = pd.DataFrame([{"etf_id": config.universe.enabled_ids[0], "date": "2026-07-10", "adjusted_close": 100.0}])
    fundamentals = pd.DataFrame()
    registry = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "registry-1"}])
    reports = pd.DataFrame()
    holdings_path = tmp_path / "fund_holdings.parquet"
    holdings = normalise_holdings(
        pd.DataFrame([{"security": "Test holding", "ticker": "TEST", "weight": 0.4}]),
        config.universe.enabled_ids[0],
        "2026-07-10",
        "manual_unverified",
        today="2026-07-10",
    ).frame
    holdings.insert(0, "schema_version", 1)
    holdings.to_parquet(holdings_path, index=False)
    factsheet_path = tmp_path / "etf_metadata.parquet"
    factsheet = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "factsheet-1", "field_name": "domicile", "value": "IE"}])
    factsheet.to_parquet(factsheet_path, index=False)
    captured: dict[str, object] = {}

    def fake_run_backtest(
        config_arg,
        prices_arg,
        *,
        fundamentals=None,
        initial_value_eur=10000,
        rebalance_frequency_days=21,
        transaction_cost_bps=None,
        structure_document_registry=None,
        structure_report_records=None,
        structure_supplemental_rows=None,
        structure_holdings=None,
    ):
        captured["structure_holdings"] = structure_holdings.copy()
        captured["structure_supplemental_rows"] = structure_supplemental_rows.copy()
        evidence = pd.DataFrame(columns=FRAME_COLUMNS)
        checksum = backtest_input_checksum(
            config_arg,
            prices_arg,
            fundamentals,
            structure_document_registry=structure_document_registry,
            structure_report_records=structure_report_records,
            structure_supplemental_rows=structure_supplemental_rows,
            structure_holdings=structure_holdings,
        )
        structural_caps = services.structure_confidence_caps(
            [config_arg.universe.enabled_ids[0]],
            document_registry=structure_document_registry,
            report_records=structure_report_records,
            supplemental_rows=structure_supplemental_rows,
            holdings=structure_holdings,
            decision_time="2026-07-10",
        )
        structural_cap = structural_caps[config_arg.universe.enabled_ids[0]]
        structural_hash = structural_caps.provenance[config_arg.universe.enabled_ids[0]]["structure_provenance_hash"]
        captured["structural_cap"] = structural_cap
        captured["structural_hash"] = structural_hash
        strategies = ("momentum_only", "signal_strategy", "quality_momentum")
        equity_curves = pd.DataFrame(
            {strategy: [100.0, 99.0, 101.0] for strategy in strategies},
            index=pd.to_datetime(["2026-07-08", "2026-07-09", "2026-07-10"]),
        )
        results = pd.DataFrame(
            [
                {
                    **performance_metrics(equity_curves[strategy]),
                    "strategy_name": strategy,
                    "backtest_quality": "low",
                }
                for strategy in strategies
            ]
        )
        return BacktestReport(
            results=results,
            equity_curves=equity_curves,
            trade_log=pd.DataFrame(columns=["event"]),
            signal_log=pd.DataFrame([{
                "date": "2026-07-10",
                "etf_id": config_arg.universe.enabled_ids[0],
                "structural_confidence_cap": structural_cap,
                "structural_provenance_hash": structural_hash,
            }]),
            ai_added_value=False,
            quality_label="low",
            metadata={
                "input_checksum": checksum,
                "quality_momentum_strategy_version": QUALITY_MOMENTUM_VERSION,
                "quality_momentum_evidence_checksum": services.quality_momentum_evidence_checksum(evidence),
                "operational_evidence_rows": [],
            },
            quality_momentum_evidence=evidence,
        )

    def fake_settings_identity():
        return {"settings_revision": "settings-1"}

    def fake_settings_revision():
        return "settings-1"

    def fake_run_id(name, *, settings_identity):
        return "backtest-test"

    def fake_manifest(run_id, dependencies, *, settings_identity):
        return None

    def fake_append(path, event, payload):
        return None

    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path / "backtests")
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "absent-identity-root" / "data" / "clean" / "instrument_identity.parquet",
    )
    monkeypatch.setattr(services, "FUND_HOLDINGS_PATH", holdings_path)
    monkeypatch.setattr(services, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(services, "load_prices", lambda: prices)
    monkeypatch.setattr(services, "load_fundamental_evidence", lambda: fundamentals)
    monkeypatch.setattr(services, "read_document_registry", lambda: registry)
    monkeypatch.setattr(services, "read_etf_report_records", lambda: reports)
    monkeypatch.setattr(services, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(services, "current_settings_identity", fake_settings_identity)
    monkeypatch.setattr(services, "current_settings_revision", fake_settings_revision)
    monkeypatch.setattr(services, "settings_bound_run_id", fake_run_id)
    monkeypatch.setattr(services, "ensure_run_manifest", fake_manifest)
    monkeypatch.setattr(services, "append_jsonl", fake_append)

    service = services.BacktestService(config, universe_revision="universe-1")
    service.run_backtest()
    assert captured["structure_holdings"].equals(holdings)
    assert captured["structure_supplemental_rows"]["source_id"].tolist() == ["factsheet-1"]
    persisted_signal_log = pd.read_csv(services.BACKTESTS_DIR / "signal_log.csv")
    assert persisted_signal_log.loc[0, "structural_confidence_cap"] == captured["structural_cap"]
    assert persisted_signal_log.loc[0, "structural_provenance_hash"] == captured["structural_hash"]
    cached = service._load_cached_backtest()
    assert cached is not None
    assert cached.signal_log.loc[0, "structural_confidence_cap"] == captured["structural_cap"]
    assert cached.signal_log.loc[0, "structural_provenance_hash"] == captured["structural_hash"]

    tampered_cap = persisted_signal_log.copy()
    tampered_cap.loc[0, "structural_confidence_cap"] = float(captured["structural_cap"]) + 0.1
    tampered_cap.to_csv(services.BACKTESTS_DIR / "signal_log.csv", index=False)
    assert service._load_cached_backtest() is None

    tampered_hash = persisted_signal_log.copy()
    tampered_hash.loc[0, "structural_provenance_hash"] = "d" * 64
    tampered_hash.to_csv(services.BACKTESTS_DIR / "signal_log.csv", index=False)
    assert service._load_cached_backtest() is None

    missing_provenance = persisted_signal_log.drop(
        columns=["structural_confidence_cap", "structural_provenance_hash"]
    )
    missing_provenance.to_csv(services.BACKTESTS_DIR / "signal_log.csv", index=False)
    assert service._load_cached_backtest() is None
    persisted_signal_log.to_csv(services.BACKTESTS_DIR / "signal_log.csv", index=False)

    changed = holdings.copy()
    changed.loc[0, "weight"] = 0.6
    changed.to_parquet(holdings_path, index=False)
    assert service._load_cached_backtest() is None


def test_canonical_document_registry_fails_closed_on_duplicate_source_id(tmp_path) -> None:
    path = tmp_path / "fund_documents.parquet"
    pd.DataFrame(
        [
            {"instrument_id": "ETF-1", "source_id": "duplicate", "document_type": "factsheet", "sha256": "a" * 64},
            {"instrument_id": "ETF-1", "source_id": "duplicate", "document_type": "factsheet", "sha256": "b" * 64},
        ]
    ).to_parquet(path, index=False)

    with pytest.raises(ValueError, match="duplicate source_id"):
        read_document_registry(path=path)


def test_canonical_document_registry_fails_closed_on_corrupt_store(tmp_path) -> None:
    path = tmp_path / "fund_documents.parquet"
    path.write_bytes(b"not a parquet document registry")

    with pytest.raises(ValueError, match="registry is corrupt"):
        read_document_registry(path=path)


def test_backtest_cache_is_invalidated_when_structural_loader_raises(tmp_path, monkeypatch) -> None:
    config = services.load_config()
    prices = pd.DataFrame(
        [{"etf_id": config.universe.enabled_ids[0], "date": "2026-07-10", "adjusted_close": 100.0}]
    )
    fundamentals = pd.DataFrame()
    evidence = pd.DataFrame(columns=FRAME_COLUMNS)
    backtests = tmp_path / "backtests"
    backtests.mkdir()
    results = pd.DataFrame(
        [
            {
                "strategy_name": strategy,
                "calmar": 1.0,
                "backtest_quality": "low",
                "return_hit_rate": 0.5,
                "average_win_return": 0.1,
                "average_loss_return": -0.1,
                "payoff_ratio": 1.0,
                "expected_value_per_period": 0.0,
                "payoff_asymmetry_warning": "none",
            }
            for strategy in ("momentum_only", "signal_strategy", "quality_momentum")
        ]
    )
    monkeypatch.setattr(services, "BACKTESTS_DIR", backtests)
    monkeypatch.setattr(services, "load_prices", lambda: prices)
    monkeypatch.setattr(services, "load_fundamental_evidence", lambda: fundamentals)
    monkeypatch.setattr(services, "current_settings_revision", lambda: "settings-1")
    service = services.BacktestService(config, universe_revision="universe-1")
    reference_context = services._backtest_calculation_context(
        config, service.reference_context, prices
    )
    binding = services._reference_binding(reference_context)
    results["benchmark_strategy"] = binding["benchmark_strategy"]
    results.to_csv(backtests / "backtest_results.csv", index=False)
    pd.DataFrame({"signal_strategy": [100.0]}, index=pd.to_datetime(["2026-07-10"])).to_csv(
        backtests / "equity_curves.csv"
    )
    evidence.to_csv(backtests / "quality_momentum_evidence.csv", index=False)
    pd.DataFrame([{"event": "none"}]).to_csv(backtests / "trade_log.csv", index=False)
    pd.DataFrame(
        [{
            "date": "2026-07-10",
            "etf_id": config.universe.enabled_ids[0],
            "structural_confidence_cap": 0.0,
            "structural_provenance_hash": "unavailable",
        }]
    ).to_csv(backtests / "signal_log.csv", index=False)
    metadata = {
        "input_checksum": backtest_input_checksum(config, prices, fundamentals),
        "quality_momentum_strategy_version": QUALITY_MOMENTUM_VERSION,
        "quality_momentum_evidence_checksum": services.quality_momentum_evidence_checksum(evidence),
        **binding,
    }
    (backtests / "backtest_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    for filename in (
        "backtest_results.csv",
        "equity_curves.csv",
        "trade_log.csv",
        "signal_log.csv",
        "quality_momentum_evidence.csv",
        "backtest_metadata.json",
    ):
        services._write_universe_cache_metadata(
            backtests / filename,
            "universe-1",
            "settings-1",
            reference_identity=reference_context.identity,
        )

    loader_called = False

    def raise_structural_corruption():
        nonlocal loader_called
        loader_called = True
        raise ValueError("structural store is corrupt")

    monkeypatch.setattr(services, "_load_local_structural_evidence", raise_structural_corruption)

    assert service._load_cached_backtest() is None
    assert loader_called is True


def test_canonical_report_reader_fails_closed_on_duplicate_source_id(tmp_path) -> None:
    from etf_cockpit.data.parsed_disclosures import read_etf_report_records

    path = tmp_path / "etf_report_records.parquet"
    pd.DataFrame([
        {"schema_version": 2.1, "source_id": "duplicate"},
        {"schema_version": 2.1, "source_id": "duplicate"},
    ]).to_parquet(path, index=False)

    with pytest.raises(ValueError, match="duplicate source_id"):
        read_etf_report_records(path)


def test_yfinance_script_reuses_local_structural_evidence_for_signals_and_backtest(tmp_path, monkeypatch) -> None:
    from etf_cockpit.data.fund_holdings import normalise_holdings

    script_path = Path(__file__).parents[1] / "scripts" / "run_yfinance_analysis.py"
    spec = importlib.util.spec_from_file_location("issue_0104_run_yfinance_analysis", script_path)
    assert spec is not None and spec.loader is not None
    analysis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analysis)

    instrument = "VWCE"
    config = SimpleNamespace(universe=SimpleNamespace(enabled_ids=[instrument], etfs=[]))
    prices = pd.DataFrame([{"etf_id": instrument, "date": date(2026, 7, 10), "adjusted_close": 100.0}])
    report = SimpleNamespace(as_of_date=date(2026, 7, 10), issues=[], status="ok")
    registry = pd.DataFrame([{"source_id": "local-registry"}])
    reports = pd.DataFrame([{"source_id": "local-report"}])
    structural_holdings = normalise_holdings(
        pd.DataFrame([{"security": "Local holding", "ticker": "LOCAL", "weight": 1.0}]),
        instrument,
        "2026-07-10",
        "manual_unverified",
        today="2026-07-10",
    ).frame
    structural_holdings.insert(0, "schema_version", 1)
    structural_holdings_path = tmp_path / "fund_holdings.parquet"
    factsheet = pd.DataFrame([{"source_id": "local-factsheet", "field_name": "domicile", "value": "IE"}])
    factsheet_path = tmp_path / "etf_metadata.parquet"
    structural_holdings.to_parquet(structural_holdings_path, index=False)
    factsheet.to_parquet(factsheet_path, index=False)
    signal_call: dict[str, object] = {}
    backtest_call: dict[str, object] = {}
    caps_call: dict[str, object] = {}

    class Provider:
        def fetch_prices(self, symbols, start_date, end_date):
            return SimpleNamespace(ok=True, data=prices, message="prices loaded")

    def fake_validate_prices(prices_arg, *, as_of_date):
        return report

    def fake_compute_features(prices_arg, *, benchmark_etf_id):
        return pd.DataFrame()

    def fake_latest_features(features_arg, as_of_date):
        return pd.DataFrame()

    def fake_structure_caps(instrument_ids, *, document_registry, report_records, supplemental_rows, holdings, decision_time):
        caps_call.update(
            {
                "document_registry": document_registry,
                "report_records": report_records,
                "supplemental_rows": supplemental_rows,
                "holdings": holdings,
                "decision_time": decision_time,
            }
        )
        return {instrument: 0.5}

    def fake_generate_signals(
        config_arg,
        latest_arg,
        holdings_arg,
        data_report_arg,
        *,
        as_of_date,
        toto_available,
        timesfm_available,
        forecast_scores,
        structure_confidence_caps,
    ):
        signal_call.update({"structure_confidence_caps": structure_confidence_caps})
        return []

    def fake_run_backtest_for_script(
        config_arg,
        prices_arg,
        *,
        fundamentals=None,
        initial_value_eur=10000,
        rebalance_frequency_days=21,
        transaction_cost_bps=None,
        structure_document_registry=None,
        structure_report_records=None,
        structure_supplemental_rows=None,
        structure_holdings=None,
    ):
        backtest_call.update(
            {
                "structure_document_registry": structure_document_registry,
                "structure_report_records": structure_report_records,
                "structure_supplemental_rows": structure_supplemental_rows,
                "structure_holdings": structure_holdings,
            }
        )
        return SimpleNamespace(results=pd.DataFrame(), ai_added_value=False, quality_label="unavailable")

    monkeypatch.setattr(analysis, "load_config", lambda: config)
    monkeypatch.setattr(analysis.YFinanceProvider, "from_config", lambda _config: Provider())
    monkeypatch.setattr(analysis, "validate_prices", fake_validate_prices)
    monkeypatch.setattr(analysis, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(analysis, "compute_features", fake_compute_features)
    monkeypatch.setattr(analysis, "latest_features", fake_latest_features)
    monkeypatch.setattr(analysis, "write_features", lambda features_arg: None)
    monkeypatch.setattr(analysis, "model_availability", lambda _config: {"timesfm": False, "toto": False})
    monkeypatch.setattr(analysis, "forecast_component_maps", lambda _frame: {})
    monkeypatch.setattr(analysis, "target_policy_issues", lambda _config: [])
    monkeypatch.setattr(analysis, "read_document_registry", lambda: registry)
    monkeypatch.setattr(analysis, "read_etf_report_records", lambda: reports)
    monkeypatch.setattr(analysis, "FUND_HOLDINGS_PATH", structural_holdings_path)
    monkeypatch.setattr(analysis, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(analysis, "structure_confidence_caps", fake_structure_caps)
    monkeypatch.setattr(analysis, "generate_signals", fake_generate_signals)
    monkeypatch.setattr(analysis, "run_backtest", fake_run_backtest_for_script)
    monkeypatch.setattr(analysis, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(analysis.sys, "argv", ["run_yfinance_analysis.py", "--no-commit", "--skip-reference", "--skip-models", "--as-of", "2026-07-10"])

    assert analysis.main() == 0
    assert signal_call["structure_confidence_caps"] == {instrument: 0.5}
    assert backtest_call["structure_document_registry"].equals(registry)
    assert backtest_call["structure_report_records"].equals(reports)
    assert backtest_call["structure_supplemental_rows"]["source_id"].tolist() == ["local-factsheet"]
    assert backtest_call["structure_holdings"].equals(structural_holdings)
    assert caps_call["supplemental_rows"]["source_id"].tolist() == ["local-factsheet"]
    assert caps_call["holdings"].equals(structural_holdings)
