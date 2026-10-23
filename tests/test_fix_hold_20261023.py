from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json

import pandas as pd

from etf_cockpit.data.etf_structure import project_etf_structure
from etf_cockpit.data.fund_holdings import (
    holdings_splits,
    normalise_holdings,
    select_holdings_as_of,
    write_holdings_records,
)
from etf_cockpit.data.ishares_holdings import COLUMNS, parse_ishares_csv
from etf_cockpit.data.market_calendar import ListingCalendarEvidence
from etf_cockpit.data.parsed_disclosures import report_extraction_fingerprint
from etf_cockpit.data.esef_provider import parse_reported_shares


CHECKSUM = "a" * 64


def test_write_holdings_preserves_other_funds(tmp_path) -> None:
    destination = tmp_path / "fund_holdings.parquet"
    first = normalise_holdings(
        pd.DataFrame({"security": ["AAA"], "ticker": ["AAA"], "weight": [1.0]}),
        "ETF-A", "2026-10-20", "issuer", today="2026-10-21",
    )
    second = normalise_holdings(
        pd.DataFrame({"security": ["BBB"], "ticker": ["BBB"], "weight": [1.0]}),
        "ETF-B", "2026-10-20", "issuer", today="2026-10-21",
    )

    write_holdings_records(first, destination=destination)
    write_holdings_records(second, destination=destination)

    stored = pd.read_parquet(destination)
    assert set(stored["instrument_id"]) == {"ETF-A", "ETF-B"}


def test_select_holdings_uses_document_known_at() -> None:
    frame = pd.DataFrame([{
        "instrument_id": "ETF-A", "as_of": "2026-10-20", "document_known_at": "2026-10-21T00:00:00Z",
        "weight": 0.98, "country": "GB", "sector": "Technology", "authority": "issuer",
        "source_id": "holdings:one",
    }])

    selected = select_holdings_as_of(frame, "ETF-A", "2026-10-21T12:00:00Z")

    assert len(selected) == 1
    assert holdings_splits(selected)["reason"] is None
    assert holdings_splits(pd.DataFrame({"weight": [1.0]}))["reason"] == "holdings_no_dated_source"


def test_structural_rows_use_coverage_status_alias(tmp_path) -> None:
    from etf_cockpit.data.etf_structure import load_local_structural_evidence

    factsheet_path = tmp_path / "factsheet.parquet"
    pd.DataFrame([{
        "instrument_id": "ETF-1", "registered_source_id": "factsheet-1",
        "source_sha256": CHECKSUM, "document_date": "2026-07-01",
        "document_known_at": "2026-07-02T00:00:00Z", "document_page": 2,
        "coverage_status": "extracted", "field_name": "replication_method",
        "value": "Physical", "confidence": 0.9,
    }]).to_parquet(factsheet_path, index=False)
    registry = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "factsheet-1", "document_type": "factsheet",
        "document_kind": "factsheet", "authority": "issuer_document", "sha256": CHECKSUM,
        "checksum": CHECKSUM, "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z",
        "coverage_status": "available",
    }])
    evidence = load_local_structural_evidence(
        registry_reader=lambda: registry,
        report_reader=lambda: pd.DataFrame(),
        factsheet_path=factsheet_path,
        holdings_path=tmp_path / "missing-holdings.parquet",
    )

    projection = project_etf_structure(
        "ETF-1", document_registry=registry, supplemental_rows=evidence.supplemental_rows,
        decision_time="2026-07-03T00:00:00Z",
    )

    assert projection["fields"]["replication_method"]["status"] == "resolved"


def _registry_row(source_id: str, document_type: str, document_kind: str, document_date: str, known_at: str, checksum: str) -> dict[str, object]:
    return {
        "instrument_id": "ETF-1", "source_id": source_id, "document_type": document_type,
        "document_kind": document_kind, "authority": "issuer_document", "sha256": checksum,
        "checksum": checksum, "document_date": document_date, "known_at": known_at,
        "coverage_status": "available", "document_version": "v1",
    }


def _numeric_only_reviewed_report() -> pd.DataFrame:
    document_date = "2026-07-01"
    known_at = "2026-07-02T00:00:00Z"
    evidence = [
        {"field_name": "fund_name", "value": "ETF One", "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
        {"field_name": "isin", "value": "IE00TEST0001", "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
        {"field_name": "document_date", "value": document_date, "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
    ]
    evidence.extend(
        {"field_name": field, "value": value, "unit": unit, "source_page": 4,
         "candidate_pages": [4], "confidence": "high", "status": "extracted"}
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    )
    frame = pd.DataFrame([{
        "schema_version": 2.1, "instrument_id": "ETF-1", "source_id": "annual-1",
        "document_type": "annual_report", "document_kind": "annual_report", "source_sha256": CHECKSUM,
        "source_authority": "issuer_document", "document_date": document_date, "known_at": known_at,
        "verification_status": "verified", "verified_by": "analyst", "verified_at": known_at,
        "review_note": "", "review_history": "[]", "extraction_sha256": "b" * 64,
        "stored_extraction_sha256": "b" * 64, "evidence_eligible": True, "manual_review": False,
        "score_eligible": False, "execution_allowed": False, "extraction_status": "complete",
        "parse_success": True, "warnings": "[]", "field_evidence": json.dumps(evidence),
    }])
    fingerprint = report_extraction_fingerprint(frame.iloc[0])
    frame.loc[0, "extraction_sha256"] = fingerprint
    frame.loc[0, "stored_extraction_sha256"] = fingerprint
    frame.loc[0, "review_history"] = json.dumps([{
        "decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": known_at,
        "extraction_sha256": fingerprint,
    }])
    return frame


def test_numeric_report_source_is_selected() -> None:
    factsheet_checksum = "c" * 64
    registry = pd.DataFrame([
        _registry_row("annual-1", "annual_report", "annual_report", "2026-07-01", "2026-07-02T00:00:00Z", CHECKSUM),
        _registry_row("factsheet-1", "factsheet", "factsheet", "2026-07-01", "2026-07-02T00:00:00Z", factsheet_checksum),
    ])
    factsheet_row = {
        "instrument_id": "ETF-1", "source_id": "factsheet-1", "document_type": "factsheet",
        "document_source_id": "factsheet-1", "source_sha256": factsheet_checksum,
        "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z", "page": 2,
        "field_name": "replication_method", "value": "Physical", "confidence": 0.9,
        "status": "extracted",
    }

    projection = project_etf_structure(
        "ETF-1", document_registry=registry, report_records=_numeric_only_reviewed_report(),
        supplemental_rows=pd.DataFrame([factsheet_row]), decision_time="2026-07-03T00:00:00Z",
    )

    assert projection["stress"]["status"] == "available"


def test_ishares_cash_offset_completeness() -> None:
    listing = ListingCalendarEvidence(
        listing_id="synthetic-listing", instrument_id="ETF-1", mic="XLON", calendar_id="XLON",
        timezone="Europe/London", source_id="synthetic-calendar-evidence",
        source_checksum=hashlib.sha256(b"synthetic calendar binding").hexdigest(),
        valid_from=date(2020, 1, 1), known_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fund Holdings as of", "20/Oct/2026"])
    writer.writerow(COLUMNS)
    writer.writerow(["AAA", "Synthetic equity", "Technology", "Equity", "985", "98.50", "985", "10", "98.5", "GB", "XLON", "GBP"])
    writer.writerow(["CASH", "Synthetic cash", "Cash and/or Derivatives", "Cash", "15", "1.50", "15", "15", "1", "-", "-", "GBP"])

    parsed = parse_ishares_csv(
        output.getvalue().encode("utf-8"), instrument_id="ETF-1", source_url="synthetic-source",
        listing=listing, known_at="2026-10-21T00:00:00Z",
    )

    assert parsed["holdings"][0]["weight"] == 0.985
    assert parsed["holdings"][0]["completeness"] == "full"


def _share_fact(taxonomy: str, concept: str, value: int, source_id: str) -> dict[str, object]:
    return {
        "taxonomy": taxonomy, "concept": concept, "unit": "shares", "value": value,
        "start": None, "end": "2025-12-31", "instant": "2025-12-31", "dimensions": "",
        "consolidation_scope": "consolidated", "known_at": "2026-02-10T12:00:00Z",
        "filed": "2026-02-10T12:00:00Z", "filing_version": "package-1", "source_id": source_id,
    }


def test_reported_shares_subtracts_treasury() -> None:
    outstanding = _share_fact("ifrs-full", "NumberOfSharesOutstanding", 100_000_000, "ifrs-outstanding")
    treasury = _share_fact("ifrs-full", "TreasuryShares", 5_000_000, "ifrs-treasury")

    fallback = parse_reported_shares(pd.DataFrame([outstanding, treasury]), source_ref="test")
    preferred = parse_reported_shares(pd.DataFrame([
        outstanding, treasury, _share_fact("dei", "EntityCommonStockSharesOutstanding", 95_000_000, "dei-shares"),
    ]), source_ref="test")
    conflict = parse_reported_shares(pd.DataFrame([
        outstanding, treasury, _share_fact("dei", "EntityCommonStockSharesOutstanding", 95_000_000, "dei-one"),
        _share_fact("dei", "EntityCommonStockSharesOutstanding", 96_000_000, "dei-two"),
    ]), source_ref="test")
    missing_treasury = parse_reported_shares(pd.DataFrame([outstanding]), source_ref="test")

    assert fallback[0]["shares_outstanding"] == 95_000_000
    assert preferred[0]["shares_outstanding"] == 95_000_000
    assert preferred[0]["source_ref"] == "dei-shares"
    assert conflict[0]["shares_outstanding"] is None
    assert missing_treasury[0]["shares_outstanding"] is None


def test_official_holdings_and_date_cutoff() -> None:
    registry = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "nport-1", "document_type": "holdings",
        "document_kind": "holdings", "authority": "official", "sha256": CHECKSUM,
        "checksum": CHECKSUM, "document_date": "2025-03-31", "known_at": "2025-03-31T12:00:00Z",
        "coverage_status": "available",
    }])
    holding = pd.DataFrame([{
        "instrument_id": "ETF-1", "document_source_id": "nport-1", "source_id": "holdings:one",
        "document_type": "holdings", "source_sha256": CHECKSUM, "document_date": "2025-03-31",
        "known_at": "2025-03-31T12:00:00Z", "page": 1, "field_name": "replication_method",
        "value": "Physical", "confidence": 0.9, "status": "extracted", "freshness": "fresh",
        "completeness": "full", "authority": "official", "score_eligible": True,
    }])

    projection = project_etf_structure(
        "ETF-1", document_registry=registry, holdings=holding, decision_time="2025-03-31",
    )

    assert projection["fields"]["replication_method"]["status"] == "resolved"
