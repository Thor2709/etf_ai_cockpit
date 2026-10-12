from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data.etf_structure import project_etf_structure
from etf_cockpit.data.parsed_disclosures import report_extraction_fingerprint, validate_supplied_etf_report_records
from etf_cockpit.parsers.etf_report import parse_etf_report


CHECKSUM = "a" * 64
KNOWN_AT = "2026-07-02T00:00:00Z"


class _Page:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class _Pdf:
    def __init__(self, text: str) -> None:
        self.pages = [_Page(text)]

    def __enter__(self) -> _Pdf:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _registry() -> pd.DataFrame:
    return pd.DataFrame([{
        "instrument_id": "ETF-1",
        "source_id": "report:v2:one",
        "document_type": "prospectus_report",
        "document_kind": "prospectus",
        "authority": "issuer_document",
        "sha256": CHECKSUM,
        "checksum": CHECKSUM,
        "document_date": "2026-07-01",
        "known_at": KNOWN_AT,
        "coverage_status": "available",
        "document_version": "v1",
    }])


def _evidence(**overrides: str) -> list[dict[str, object]]:
    values = {
        "fund_name": "Evidence ETF",
        "isin": "IE00B4L5Y983",
        "document_date": "2026-07-01",
        "legal_form": "UCITS investment company",
        "domicile": "Ireland",
        "replication_method": "Physical",
        "derivatives": "No derivatives",
        "concentration_limits": "Single issuer limit 20%",
        "lending_policy": "No securities lending",
    }
    values.update(overrides)
    return [{
        "field_name": field,
        "value": value,
        "source_page": 1,
        "candidate_pages": [1],
        "confidence": "high",
        "status": "extracted",
    } for field, value in values.items()]


def _reviewed_report(evidence: list[dict[str, object]]) -> pd.DataFrame:
    row: dict[str, object] = {
        "schema_version": 2.1,
        "source_id": "report:v2:one",
        "instrument_id": "ETF-1",
        "document_type": "prospectus_report",
        "document_kind": "prospectus",
        "source_sha256": CHECKSUM,
        "source_authority": "issuer_document",
        "document_date": "2026-07-01",
        "known_at": KNOWN_AT,
        "extraction_status": "complete",
        "parse_success": True,
        "warnings": "[]",
        "field_evidence": json.dumps(evidence),
        "verification_status": "verified",
        "verified_by": "reviewer",
        "verified_at": KNOWN_AT,
        "review_note": "",
        "review_history": "[]",
        "evidence_eligible": True,
        "manual_review": False,
        "score_eligible": False,
        "execution_allowed": False,
    }
    frame = pd.DataFrame([row])
    fingerprint = report_extraction_fingerprint(frame.iloc[0])
    frame.loc[0, "extraction_sha256"] = fingerprint
    frame.loc[0, "stored_extraction_sha256"] = fingerprint
    frame.loc[0, "review_history"] = json.dumps([{
        "decision": "verified",
        "reviewer": "reviewer",
        "note": "",
        "reviewed_at": KNOWN_AT,
        "extraction_sha256": fingerprint,
    }])
    return frame


def test_report_parser_marks_explicit_disclosure_placeholder_unavailable(tmp_path, monkeypatch) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"synthetic report fixture")
    text = (
        "ETF Prospectus\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\n"
        "Document date: 14 July 2026\nLegal structure: Irish UCITS\n"
        "Counterparties: Bank A\nCollateral terms: Not disclosed by the issuer"
    )
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: _Pdf(text)))

    result = parse_etf_report(source, "prospectus", expected_isin="IE00B4L5Y983")

    assert result.success is True
    collateral = next(item for item in result.records[0].field_evidence if item.field_name == "collateral_terms")
    assert collateral.status == "unavailable"
    assert collateral.value is None
    assert collateral.candidates == ("Not disclosed by the issuer",)
    assert collateral.pages == (1,)


def test_report_persistence_rejects_extracted_placeholder_as_reviewable_evidence() -> None:
    evidence = _evidence(legal_form="Unknown")

    with pytest.raises(ValueError, match="incomplete report cannot be evidence eligible"):
        validate_supplied_etf_report_records(_reviewed_report(evidence))


def test_structure_projection_keeps_missing_collateral_and_stress_unavailable() -> None:
    evidence = _evidence(replication_method="Synthetic swap", derivatives="Total return swap")
    evidence.append({
        "field_name": "collateral_terms",
        "value": None,
        "source_page": 2,
        "candidate_pages": [2],
        "candidates": ["Not disclosed"],
        "confidence": "unknown",
        "status": "unavailable",
    })

    projection = project_etf_structure(
        "ETF-1", document_registry=_registry(), report_records=_reviewed_report(evidence),
        decision_time="2026-07-03T00:00:00Z",
    )

    collateral = projection["fields"]["collateral_terms"]
    assert collateral["status"] == "unusable"
    assert collateral["value"] is None
    assert "synthetic_collateral_evidence_missing_or_conflicted" in projection["flags"]
    assert projection["stress"]["status"] == "unavailable"
    assert projection["stress"]["reason_code"] == "numeric_evidence_not_supplied"
    assert projection["stress"]["unsecured_pct_nav"] is None


def test_nonapplicable_unknown_terms_do_not_make_projection_partial() -> None:
    projection = project_etf_structure(
        "ETF-1", document_registry=_registry(), report_records=_reviewed_report(_evidence()),
        decision_time="2026-07-03T00:00:00Z",
    )

    assert projection["status"] == "available"
    assert projection["fields"]["collateral_terms"]["status"] == "unknown"
    assert "collateral_terms" not in projection["applicable_fields"]
    assert projection["evidence_confidence_cap"] == 1.0


def test_unknown_derivative_and_lending_disclosures_remain_explicit() -> None:
    evidence = [item for item in _evidence() if item["field_name"] not in {"derivatives", "lending_policy"}]
    projection = project_etf_structure(
        "ETF-1", document_registry=_registry(), report_records=_reviewed_report(evidence),
        decision_time="2026-07-03T00:00:00Z",
    )

    assert projection["status"] == "partial"
    assert projection["fields"]["derivatives"]["status"] == "unknown"
    assert projection["fields"]["derivatives"]["value"] is None
    assert "derivative_exposure_unknown_or_conflicted" in projection["flags"]
    assert "securities_lending_status_unknown_or_conflicted" in projection["flags"]
