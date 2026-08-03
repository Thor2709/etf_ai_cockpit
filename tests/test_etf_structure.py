from __future__ import annotations

import json

import pandas as pd
import pytest

from etf_cockpit.backtest.engine import backtest_input_checksum
from etf_cockpit.core.config import load_config
from etf_cockpit.data.etf_structure import (
    NumericEvidence,
    calculate_structural_stress,
    project_etf_structure,
    structure_confidence_caps,
)
from etf_cockpit.data.parsed_disclosures import report_extraction_fingerprint


CHECKSUM = "a" * 64


def _registry(*, source_id: str = "report:v2:one", document_type: str = "prospectus_report", document_kind: str = "prospectus", document_date: str = "2026-07-01", known_at: str = "2026-07-02T00:00:00Z") -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "instrument_id": "ETF-1",
            "source_id": source_id,
            "document_type": document_type,
            "document_kind": document_kind,
            "authority": "issuer_document",
            "sha256": CHECKSUM,
            "checksum": CHECKSUM,
            "document_date": document_date,
            "known_at": known_at,
            "coverage_status": "available",
            "document_version": "v1",
        }]
    )


def _required_report_evidence(document_date: str) -> list[dict[str, object]]:
    return [
        {"field_name": "fund_name", "value": "ETF One", "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
        {"field_name": "isin", "value": "IE00TEST0001", "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
        {"field_name": "document_date", "value": document_date, "source_page": 1, "candidate_pages": [1], "confidence": "high", "status": "extracted"},
    ]


def _report(source_id: str = "report:v2:one", *, replication: str = "Synthetic swap", document_date: str = "2026-07-01", known_at: str = "2026-07-02T00:00:00+00:00") -> pd.DataFrame:
    evidence = _required_report_evidence(document_date)
    values = {
        "replication_method": replication,
        "derivatives": "Total return swap",
        "counterparties": "Bank A",
        "collateral_terms": "102% daily margin",
        "lending_policy": "Not permitted",
        "lending_revenue_split": "unavailable",
        "domicile": "Ireland",
        "legal_form": "UCITS investment company",
        "concentration_limits": "10% counterparty limit",
    }
    for field, value in values.items():
        evidence.append({"field_name": field, "value": value, "source_page": 4, "candidate_pages": [4], "confidence": "high", "status": "extracted"})
    evidence.extend(
        {
            "field_name": field,
            "value": value,
            "unit": unit,
            "source_page": 4,
            "candidate_pages": [4],
            "confidence": "high",
            "status": "extracted",
        }
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    )
    frame = pd.DataFrame([{
        "schema_version": 2.1,
        "instrument_id": "ETF-1",
        "source_id": source_id,
        "document_type": "prospectus_report",
        "document_kind": "prospectus",
        "source_sha256": CHECKSUM,
        "source_authority": "issuer_document",
        "document_date": document_date,
        "known_at": known_at,
        "verification_status": "verified",
        "verified_by": "analyst",
        "verified_at": "2026-07-02T12:00:00+00:00",
        "review_note": "",
        "review_history": json.dumps([{
            "decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": "2026-07-02T12:00:00+00:00", "extraction_sha256": "b" * 64,
        }]),
        "extraction_sha256": "b" * 64,
        "stored_extraction_sha256": "b" * 64,
        "evidence_eligible": True,
        "manual_review": False,
        "score_eligible": False,
        "execution_allowed": False,
        "extraction_status": "complete",
        "parse_success": True,
        "warnings": "[]",
        "field_evidence": json.dumps(evidence),
    }])
    fingerprint = report_extraction_fingerprint(frame.iloc[0])
    frame.loc[0, "extraction_sha256"] = fingerprint
    frame.loc[0, "stored_extraction_sha256"] = fingerprint
    frame.loc[0, "review_history"] = json.dumps([{
        "decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": "2026-07-02T12:00:00+00:00", "extraction_sha256": fingerprint,
    }])
    return frame


def _refresh_report_fingerprint(frame: pd.DataFrame) -> pd.DataFrame:
    fingerprint = report_extraction_fingerprint(frame.iloc[0])
    frame.loc[0, "extraction_sha256"] = fingerprint
    frame.loc[0, "stored_extraction_sha256"] = fingerprint
    history = json.loads(frame.loc[0, "review_history"])
    frame.loc[0, "review_history"] = json.dumps([{**item, "extraction_sha256": fingerprint} for item in history])
    return frame


def test_projection_requires_exact_registry_binding_and_preserves_provenance() -> None:
    projection = project_etf_structure("ETF-1", document_registry=_registry(), report_records=_report(), decision_time="2026-07-03T00:00:00Z")

    field = projection["fields"]["replication_method"]
    assert field["status"] == "resolved"
    assert field["document_id"] == "report:v2:one"
    assert field["document_date"] == "2026-07-01"
    assert field["page"] == 4
    assert field["confidence"] == 1.0
    assert projection["documents"]["factsheet"]["status"] == "unknown"
    assert projection["documents"]["prospectus"]["status"] == "available"
    assert projection["documents"]["holdings"]["status"] == "unknown"
    assert projection["execution_allowed"] is False


def test_duplicate_registry_source_id_is_quarantined_instead_of_last_row_win() -> None:
    duplicate_registry = pd.concat(
        [_registry(), _registry()],
        ignore_index=True,
    )
    projection = project_etf_structure("ETF-1", document_registry=duplicate_registry, report_records=_report())

    assert projection["fields"]["replication_method"]["status"] == "unknown"
    assert projection["documents"]["prospectus"]["status"] == "unknown"
    assert any(item["reason_code"] == "duplicate_registry_source_id" for item in projection["rejected_candidates"])


def test_pending_report_rows_are_not_structural_evidence() -> None:
    pending = _report()
    pending.loc[0, "verification_status"] = "pending"
    pending.loc[0, "evidence_eligible"] = False
    pending.loc[0, "manual_review"] = True
    pending.loc[0, "verified_by"] = ""
    pending.loc[0, "verified_at"] = ""
    pending.loc[0, "review_note"] = ""
    pending.loc[0, "review_history"] = "[]"

    projection = project_etf_structure("ETF-1", document_registry=_registry(), report_records=pending)

    assert projection["fields"]["replication_method"]["status"] == "unknown"
    assert projection["evidence_confidence_cap"] == 0.0
    assert any(item["reason_code"] == "report_evidence_not_eligible" for item in projection["rejected_candidates"])


def test_unknown_structure_caps_confidence_without_stock_credit_fallback() -> None:
    unknown = project_etf_structure("ETF-1", document_registry=_registry(), report_records=pd.DataFrame([{"instrument_id": "ETF-1", "source_id": "report:v2:one", "field_evidence": "[]"}]))

    assert unknown["fields"]["replication_method"]["status"] == "unknown"
    assert unknown["evidence_confidence_cap"] == 0.0
    assert "replication_structure_unknown_or_conflicted" in unknown["flags"]
    assert unknown["alpha_eligible"] is False
    assert "stock_credit_metrics" not in str(unknown)


def test_physical_no_lending_does_not_require_synthetic_fields() -> None:
    values = {
        "replication_method": "Physical",
        "derivatives": "None used",
        "domicile": "Ireland",
        "legal_form": "UCITS investment company",
        "concentration_limits": "10% issuer limit",
        "lending_policy": "Not permitted",
    }
    evidence = _required_report_evidence("2026-07-01") + [
        {"field_name": field, "value": value, "source_page": 4, "candidate_pages": [4], "confidence": "high", "status": "extracted"}
        for field, value in values.items()
    ]
    report = _report()
    report.loc[0, "field_evidence"] = json.dumps(evidence)
    _refresh_report_fingerprint(report)
    projection = project_etf_structure("ETF-1", document_registry=_registry(), report_records=report)

    assert projection["applicable_fields"] == [
        "replication_method", "derivatives", "domicile", "legal_form", "concentration_limits", "lending_policy"
    ]
    assert projection["evidence_confidence_cap"] == 1.0
    assert "counterparties" not in projection["applicable_fields"]
    assert "lending_revenue_split" not in projection["applicable_fields"]


def test_synthetic_and_lending_applicability_requires_direct_terms() -> None:
    report = _report()
    evidence = json.loads(report.loc[0, "field_evidence"])
    evidence = [item for item in evidence if item["field_name"] not in {"counterparties", "collateral_terms", "lending_revenue_split", "lending_policy"}]
    evidence.append({"field_name": "lending_policy", "value": "Lending enabled up to 10%", "source_page": 4, "confidence": "high", "status": "extracted"})
    report.loc[0, "field_evidence"] = json.dumps(evidence)
    _refresh_report_fingerprint(report)
    projection = project_etf_structure("ETF-1", document_registry=_registry(), report_records=report)

    assert {"counterparties", "collateral_terms", "lending_revenue_split"}.issubset(projection["applicable_fields"])
    assert projection["fields"]["counterparties"]["status"] == "unknown"
    assert projection["fields"]["collateral_terms"]["status"] == "unknown"
    assert projection["fields"]["lending_revenue_split"]["status"] == "unknown"
    assert projection["evidence_confidence_cap"] < 1.0
    assert projection["coverage_evidence"]["method"] == "equal_weight_mean_of_applicable_direct_confidence"


def test_synthetic_and_lending_evidence_require_direct_terms() -> None:
    report = _report()
    evidence = json.loads(report.loc[0, "field_evidence"])
    evidence = [item for item in evidence if item["field_name"] not in {"counterparties", "collateral_terms"}]
    report.loc[0, "field_evidence"] = json.dumps(evidence)
    _refresh_report_fingerprint(report)
    projection = project_etf_structure("ETF-1", document_registry=_registry(), report_records=report)

    assert "synthetic_counterparty_evidence_missing_or_conflicted" in projection["flags"]
    assert "synthetic_collateral_evidence_missing_or_conflicted" in projection["flags"]


def test_factsheet_prospectus_and_holdings_conflicts_remain_visible() -> None:
    registry = pd.concat(
        [
            _registry(source_id="factsheet-1", document_type="factsheet", document_kind="factsheet"),
            _registry(source_id="prospectus-1"),
            _registry(source_id="holdings-1", document_type="holdings", document_kind="holdings"),
        ],
        ignore_index=True,
    )
    rows = pd.DataFrame(
        [
            {"instrument_id": "ETF-1", "source_id": "factsheet-1", "document_type": "factsheet", "checksum": CHECKSUM, "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z", "field_name": "replication_method", "value": "Physical", "page": 1, "confidence": "high"},
            {"instrument_id": "ETF-1", "source_id": "prospectus-1", "document_type": "prospectus_report", "checksum": CHECKSUM, "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z", "field_name": "replication_method", "value": "Synthetic swap", "page": 2, "confidence": "high"},
            {"instrument_id": "ETF-1", "source_id": "holdings-1", "document_type": "holdings", "checksum": CHECKSUM, "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z", "field_name": "replication_method", "value": "Physical sampled", "page": 3, "confidence": "high"},
        ]
    )

    projection = project_etf_structure("ETF-1", document_registry=registry, supplemental_rows=rows)

    assert projection["fields"]["replication_method"]["status"] == "conflict"
    assert len(projection["fields"]["replication_method"]["candidates"]) == 3
    assert {projection["documents"][family]["status"] for family in ("factsheet", "prospectus", "holdings")} == {"available"}


@pytest.mark.parametrize("document_type", ["factsheet", "holdings"])
@pytest.mark.parametrize("status", ["unknown", "conflict", "rejected", "quarantined"])
def test_non_usable_supplemental_statuses_never_resolve(document_type: str, status: str) -> None:
    source_id = f"{document_type}-1"
    registry = _registry(source_id=source_id, document_type=document_type, document_kind=document_type)
    rows = pd.DataFrame([{
        "instrument_id": "ETF-1",
        "source_id": source_id,
        "document_type": document_type,
        "checksum": CHECKSUM,
        "document_date": "2026-07-01",
        "known_at": "2026-07-02T00:00:00Z",
        "field_name": "replication_method",
        "value": "Physical",
        "page": 1,
        "confidence": "high",
        "status": status,
    }])
    projection = project_etf_structure(
        "ETF-1",
        document_registry=registry,
        supplemental_rows=rows if document_type == "factsheet" else None,
        holdings=rows if document_type == "holdings" else None,
    )

    assert projection["fields"]["replication_method"]["status"] != "resolved"
    assert any(item["reason_code"] == "candidate_unusable" for item in projection["rejected_candidates"])


def test_supplemental_rows_without_page_or_exact_identity_fail_closed() -> None:
    rows = pd.DataFrame([{
        "instrument_id": "ETF-1",
        "source_id": "report:v2:one",
        "document_type": "prospectus_report",
        "field_name": "replication_method",
        "value": "Physical",
        "confidence": "high",
    }])
    projection = project_etf_structure("ETF-1", document_registry=_registry(), supplemental_rows=rows)

    assert projection["fields"]["replication_method"]["status"] == "unusable"
    assert projection["fields"]["replication_method"]["value"] is None
    assert any(item["reason_code"] == "candidate_page_or_value_missing" for item in projection["rejected_candidates"])


def test_numeric_stress_uses_bound_fraction_nav_formulas_and_rejects_implicit_values() -> None:
    candidates = [
        NumericEvidence(
            value,
            unit,
            source_id="report:v2:one",
            document_date="2026-07-01",
            page=4,
            confidence="high",
            known_at="2026-07-02T00:00:00Z",
            checksum=CHECKSUM,
            instrument_id="ETF-1",
            field_name=field,
        )
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    ]
    evidence = {
        field: NumericEvidence(
            value,
            unit,
            source_id="report:v2:one",
            document_date="2026-07-01",
            page=4,
            confidence="high",
            known_at="2026-07-02T00:00:00Z",
            checksum=CHECKSUM,
            instrument_id="ETF-1",
            field_name=field,
        )
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    }
    stress = calculate_structural_stress(
        **evidence,
        registry=_registry(),
        report_records=_report(),
        candidates=candidates,
        decision_time="2026-07-03T00:00:00Z",
        instrument_id="ETF-1",
    )
    invalid = calculate_structural_stress(
        exposure=NumericEvidence("0.4", "fraction_of_nav"),
        collateral_fraction=NumericEvidence("0.8", "fraction_of_exposure"),
        haircut_fraction=NumericEvidence("0.1", "scenario_haircut_fraction"),
        concentration_limit_fraction=NumericEvidence("0.25", "fraction_of_collateral"),
        registry=_registry(),
        report_records=_report(),
        candidates=candidates,
    )

    assert stress["status"] == "available"
    assert stress["unsecured_pct_nav"] == 0.112
    assert stress["concentration_pct_nav"] == 0.008
    assert invalid["status"] == "unavailable"
    assert invalid["unsecured_pct_nav"] is None
    assert invalid["concentration_pct_nav"] is None


def test_numeric_stress_rejects_unbound_and_future_provenance() -> None:
    candidate = NumericEvidence("0.4", "fraction_of_nav", "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", "exposure")
    base = candidate
    future = NumericEvidence("0.4", "fraction_of_nav", "report:v2:one", "2026-07-01", 4, "high", "2026-07-10T00:00:00Z", CHECKSUM, "ETF-1", "exposure")
    invalid = calculate_structural_stress(
        exposure=base,
        collateral_fraction=base,
        haircut_fraction=base,
        concentration_limit_fraction=base,
        registry=_registry(),
        candidates=[candidate],
        decision_time="2026-07-03T00:00:00Z",
        instrument_id="ETF-1",
    )
    rejected_future = calculate_structural_stress(
        exposure=future,
        collateral_fraction=base,
        haircut_fraction=base,
        concentration_limit_fraction=base,
        registry=_registry(),
        candidates=[candidate],
        decision_time="2026-07-03T00:00:00Z",
        instrument_id="ETF-1",
    )
    assert invalid["status"] == "unavailable"
    assert rejected_future["status"] == "unavailable"


def test_numeric_stress_rejects_changed_value_unit_and_repurposed_textual_candidate() -> None:
    registry = _registry()
    valid = {
        field: NumericEvidence(value, unit, "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", field)
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    }
    altered = NumericEvidence(
        "0.5", "fraction_of_nav", "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", "exposure"
    )
    wrong_unit = NumericEvidence(
        "0.4", "percent", "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", "exposure"
    )
    repurposed = NumericEvidence(
        "0.4", "fraction_of_nav", "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", "collateral_terms"
    )

    for value in (altered, wrong_unit, repurposed):
        inputs = dict(valid)
        inputs["exposure"] = value
        stress = calculate_structural_stress(
            **inputs,
            registry=registry,
            report_records=_report(),
            candidates=list(valid.values()),
            instrument_id="ETF-1",
        )
        assert stress["status"] == "unavailable"


def test_structure_projection_identity_changes_with_evidence_and_cap_is_part_of_identity() -> None:
    first = project_etf_structure("ETF-1", document_registry=_registry(), report_records=_report())
    changed = _report()
    evidence = json.loads(changed.loc[0, "field_evidence"])
    evidence[0]["value"] = "Physical"
    changed.loc[0, "field_evidence"] = json.dumps(evidence)
    second = project_etf_structure("ETF-1", document_registry=_registry(), report_records=changed)

    assert first["structure_projection_version"] == "etf-structure-documents.v1"
    assert first["structure_provenance_hash"] != second["structure_provenance_hash"]
    assert first["structure_identity"]["structure_confidence_cap"] == first["evidence_confidence_cap"]


def test_latest_usable_prospectus_revision_is_selected_as_of_decision_time() -> None:
    old = _registry(source_id="old", document_date="2026-06-01", known_at="2026-06-02T00:00:00Z")
    new = _registry(source_id="new", document_date="2026-07-15", known_at="2026-07-16T00:00:00Z")
    registry = pd.concat([old, new], ignore_index=True)
    reports = pd.concat([
        _report("old", replication="Physical", document_date="2026-06-01", known_at="2026-06-02T00:00:00+00:00"),
        _report("new", replication="Synthetic", document_date="2026-07-15", known_at="2026-07-16T00:00:00+00:00"),
    ], ignore_index=True)

    projection = project_etf_structure("ETF-1", document_registry=registry, report_records=reports, decision_time="2026-07-10T00:00:00Z")
    assert projection["fields"]["replication_method"]["value"] == "Physical"
    assert projection["documents"]["prospectus"]["source_id"] == "old"


def test_cap_mapping_is_point_in_time_and_rejects_future_revision() -> None:
    old = _registry(source_id="old", document_date="2026-06-01", known_at="2026-06-02T00:00:00Z")
    new = _registry(source_id="new", document_date="2026-07-15", known_at="2026-07-16T00:00:00Z")
    registry = pd.concat([old, new], ignore_index=True)
    old_report = _report("old", replication="Physical", document_date="2026-06-01", known_at="2026-06-02T00:00:00+00:00")
    new_report = _report("new", replication="Synthetic", document_date="2026-07-15", known_at="2026-07-16T00:00:00+00:00")
    new_evidence = json.loads(new_report.loc[0, "field_evidence"])
    for item in new_evidence:
        if item["field_name"] == "counterparties":
            item["confidence"] = "low"
    new_report.loc[0, "field_evidence"] = json.dumps(new_evidence)
    _refresh_report_fingerprint(new_report)
    reports = pd.concat([old_report, new_report], ignore_index=True)

    before_import = structure_confidence_caps(
        ["ETF-1"], document_registry=registry, report_records=reports, decision_time="2026-07-10T00:00:00Z"
    )
    after_import = structure_confidence_caps(
        ["ETF-1"], document_registry=registry, report_records=reports, decision_time="2026-07-20T00:00:00Z"
    )

    assert before_import["ETF-1"] == 1.0
    assert after_import["ETF-1"] < before_import["ETF-1"]


def test_review_history_replays_before_verification_at_verification_and_after_rejection() -> None:
    report = _report()
    history = [
        {"decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": "2026-07-04T00:00:00Z", "extraction_sha256": "b" * 64},
        {"decision": "rejected", "reviewer": "auditor", "note": "recheck", "reviewed_at": "2026-07-06T00:00:00Z", "extraction_sha256": "b" * 64},
    ]
    fingerprint = report.loc[0, "stored_extraction_sha256"]
    history = [{**item, "extraction_sha256": fingerprint} for item in history]
    report.loc[0, "review_history"] = json.dumps(history)
    report.loc[0, "verified_by"] = "auditor"
    report.loc[0, "verified_at"] = "2026-07-06T00:00:00Z"
    report.loc[0, "review_note"] = "recheck"
    report.loc[0, "verification_status"] = "rejected"
    report.loc[0, "evidence_eligible"] = False
    report.loc[0, "manual_review"] = True

    before = project_etf_structure("ETF-1", document_registry=_registry(), report_records=report, decision_time="2026-07-03T00:00:00Z")
    verified = project_etf_structure("ETF-1", document_registry=_registry(), report_records=report, decision_time="2026-07-05T00:00:00Z")
    rejected = project_etf_structure("ETF-1", document_registry=_registry(), report_records=report, decision_time="2026-07-07T00:00:00Z")

    assert before["fields"]["replication_method"]["status"] == "unknown"
    assert verified["fields"]["replication_method"]["status"] == "resolved"
    assert verified["source_vintage"]["report:v2:one"]["reviewed_at"] == "2026-07-04T00:00:00Z"
    assert rejected["fields"]["replication_method"]["status"] == "unknown"


def test_review_history_same_timestamp_replays_append_order() -> None:
    for history, expected in (
        (
                [
                    {"decision": "rejected", "reviewer": "auditor", "note": "", "reviewed_at": "2026-07-04T00:00:00Z", "extraction_sha256": "b" * 64},
                    {"decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": "2026-07-04T00:00:00Z", "extraction_sha256": "b" * 64},
            ],
            "resolved",
        ),
        (
                [
                    {"decision": "verified", "reviewer": "analyst", "note": "", "reviewed_at": "2026-07-04T00:00:00Z", "extraction_sha256": "b" * 64},
                    {"decision": "rejected", "reviewer": "auditor", "note": "", "reviewed_at": "2026-07-04T00:00:00Z", "extraction_sha256": "b" * 64},
            ],
            "unknown",
        ),
    ):
        report = _report()
        fingerprint = report.loc[0, "stored_extraction_sha256"]
        history = [{**item, "extraction_sha256": fingerprint} for item in history]
        report.loc[0, "review_history"] = json.dumps(history)
        latest = history[-1]
        report.loc[0, "verification_status"] = latest["decision"]
        report.loc[0, "verified_by"] = latest["reviewer"]
        report.loc[0, "verified_at"] = latest["reviewed_at"]
        report.loc[0, "review_note"] = latest.get("note", "")
        report.loc[0, "evidence_eligible"] = latest["decision"] == "verified"
        report.loc[0, "manual_review"] = latest["decision"] != "verified"
        projection = project_etf_structure(
            "ETF-1",
            document_registry=_registry(),
            report_records=report,
            decision_time="2026-07-05T00:00:00Z",
        )

        assert projection["fields"]["replication_method"]["status"] == expected


def test_structure_projection_uses_distinct_numeric_candidates_and_rejects_input_status() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    numeric = {
        field: NumericEvidence(value, unit, "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", field)
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    }
    structural = project_etf_structure(
        "ETF-1", document_registry=_registry(), report_records=_report(),
        numeric_inputs=numeric, numeric_candidates=list(numeric.values()),
    )
    rejected_input = dict(numeric)
    rejected_input["exposure"] = NumericEvidence("0.4", "fraction_of_nav", "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", "exposure", status="rejected")
    rejected = project_etf_structure(
        "ETF-1", document_registry=_registry(), report_records=_report(),
        numeric_inputs=rejected_input, numeric_candidates=list(rejected_input.values()),
    )

    assert structural["stress"]["status"] == "available"
    assert rejected["stress"]["status"] == "unavailable"
    facade_projection = load_etf_structure_projection(
        "ETF-1", document_registry=_registry(), report_records=_report(),
        numeric_inputs=numeric, numeric_candidates=list(numeric.values()),
    )
    assert facade_projection["stress"]["status"] == "available"


def test_numeric_stress_does_not_authenticate_caller_created_candidates() -> None:
    numeric = {
        field: NumericEvidence(value, unit, "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", field)
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    }
    stress = calculate_structural_stress(
        **numeric,
        registry=_registry(),
        candidates=list(numeric.values()),
        decision_time="2026-07-03T00:00:00Z",
        instrument_id="ETF-1",
    )

    assert stress["status"] == "unavailable"


def test_numeric_stress_rejects_wrong_numeric_evidence_instrument() -> None:
    numeric = {
        field: NumericEvidence(value, unit, "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-1", field)
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    }
    numeric["exposure"] = NumericEvidence(
        "0.4", "fraction_of_nav", "report:v2:one", "2026-07-01", 4, "high", "2026-07-02T00:00:00Z", CHECKSUM, "ETF-2", "exposure"
    )

    stress = calculate_structural_stress(
        **numeric,
        registry=_registry(),
        report_records=_report(),
        candidates=list(numeric.values()),
        decision_time="2026-07-03T00:00:00Z",
        instrument_id="ETF-1",
    )

    assert stress["status"] == "unavailable"


def test_no_derivatives_and_no_securities_lending_do_not_activate_risk_branches() -> None:
    report = _report()
    evidence = json.loads(report.loc[0, "field_evidence"])
    for item in evidence:
        if item["field_name"] == "replication_method":
            item["value"] = "Physical"
        elif item["field_name"] == "derivatives":
            item["value"] = "No derivatives"
        elif item["field_name"] == "lending_policy":
            item["value"] = "No securities lending"
    report.loc[0, "field_evidence"] = json.dumps(evidence)
    projection = project_etf_structure("ETF-1", document_registry=_registry(), report_records=report)

    assert "counterparties" not in projection["applicable_fields"]
    assert "lending_revenue_split" not in projection["applicable_fields"]
    assert not any(flag.startswith(("synthetic_", "lending_")) for flag in projection["flags"])


def test_explicit_synthetic_and_derivative_negations_remain_negative_through_facade() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    report = _report()
    evidence = json.loads(report.loc[0, "field_evidence"])
    for item in evidence:
        if item["field_name"] == "replication_method":
            item["value"] = "Not synthetic"
        elif item["field_name"] == "derivatives":
            item["value"] = "No derivative exposure"
    report.loc[0, "field_evidence"] = json.dumps(evidence)
    _refresh_report_fingerprint(report)

    projection = load_etf_structure_projection("ETF-1", document_registry=_registry(), report_records=report)

    assert "counterparties" not in projection["applicable_fields"]
    assert "collateral_terms" not in projection["applicable_fields"]
    assert not any(flag.startswith("synthetic_") for flag in projection["flags"])


def test_report_document_family_mismatch_fails_closed() -> None:
    report = _report()
    report.loc[0, "document_type"] = "annual_report"
    _refresh_report_fingerprint(report)
    projection = project_etf_structure("ETF-1", document_registry=_registry(document_type="factsheet", document_kind="factsheet"), report_records=report)

    assert projection["fields"]["replication_method"]["status"] == "unknown"
    assert any(item["reason_code"] == "candidate_document_family_mismatch" for item in projection["rejected_candidates"])


def test_numeric_stress_requires_report_document_family_binding_through_facade() -> None:
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    numeric = {
        field: NumericEvidence(
            value,
            unit,
            "report:v2:one",
            "2026-07-01",
            4,
            "high",
            "2026-07-02T00:00:00Z",
            CHECKSUM,
            "ETF-1",
            field,
        )
        for field, value, unit in (
            ("exposure", "0.4", "fraction_of_nav"),
            ("collateral_fraction", "0.8", "fraction_of_exposure"),
            ("haircut_fraction", "0.1", "scenario_haircut_fraction"),
            ("concentration_limit_fraction", "0.25", "fraction_of_collateral"),
        )
    }
    report = _report()
    report.loc[0, "document_type"] = "factsheet"
    _refresh_report_fingerprint(report)

    projection = load_etf_structure_projection(
        "ETF-1",
        document_registry=_registry(),
        report_records=report,
        numeric_inputs=numeric,
        numeric_candidates=list(numeric.values()),
    )

    assert projection["stress"]["status"] == "unavailable"
    assert projection["execution_allowed"] is False


@pytest.mark.parametrize("parse_success", ["true", 1, None])
def test_parse_success_requires_stored_boolean_true_in_canonical_and_supplied_paths(parse_success: object) -> None:
    import etf_cockpit.data.parsed_disclosures as disclosures
    from etf_cockpit.application.ui_facade import load_etf_structure_projection

    report = _report()
    report["parse_success"] = report["parse_success"].astype(object)
    report.loc[0, "parse_success"] = parse_success
    _refresh_report_fingerprint(report)

    with pytest.raises(ValueError, match="incomplete report cannot be evidence eligible"):
        disclosures._read_report_frame_from_frame(report, validate_authority=False)

    projection = load_etf_structure_projection("ETF-1", document_registry=_registry(), report_records=report)
    caps = structure_confidence_caps(["ETF-1"], document_registry=_registry(), report_records=report)

    assert projection["status"] == "unusable"
    assert projection["fields"]["replication_method"]["status"] == "unknown"
    assert projection["evidence_confidence_cap"] == 0.0
    assert caps["ETF-1"] == 0.0
    assert projection["execution_allowed"] is False


def test_duplicate_registry_source_ids_fail_closed_for_structure_and_backtest_cache_identity() -> None:
    registry = _registry()
    duplicate = registry.copy()
    duplicate.loc[0, "instrument_id"] = "ETF-2"
    malformed_registry = pd.concat([registry, duplicate], ignore_index=True)
    config = load_config()
    prices = pd.DataFrame(
        {"date": ["2026-01-01"], "etf_id": [config.universe.enabled_ids[0]], "adjusted_close": [100.0]}
    )

    from etf_cockpit.data.etf_structure import structure_input_checksum

    with pytest.raises(ValueError, match="duplicate source_id"):
        structure_input_checksum(document_registry=malformed_registry, report_records=_report())
    with pytest.raises(ValueError, match="duplicate source_id"):
        backtest_input_checksum(
            config,
            prices,
            None,
            structure_document_registry=malformed_registry,
            structure_report_records=_report(),
        )


def test_backtest_input_checksum_includes_structural_evidence() -> None:
    config = load_config()
    prices = pd.DataFrame({"date": ["2026-01-01"], "etf_id": [config.universe.enabled_ids[0]], "adjusted_close": [100.0]})
    registry = _registry(document_date="2026-01-01", known_at="2026-01-02T00:00:00+00:00")
    registry.loc[0, "instrument_id"] = config.universe.enabled_ids[0]
    reports = _report(document_date="2026-01-01", known_at="2026-01-02T00:00:00+00:00")
    reports.loc[0, "instrument_id"] = config.universe.enabled_ids[0]
    _refresh_report_fingerprint(reports)
    changed = reports.copy()
    changed_evidence = json.loads(changed.loc[0, "field_evidence"])
    next(item for item in changed_evidence if item["field_name"] == "legal_form")["value"] = "UCITS trust"
    changed.loc[0, "field_evidence"] = json.dumps(changed_evidence)
    _refresh_report_fingerprint(changed)

    first = backtest_input_checksum(config, prices, None, structure_document_registry=registry, structure_report_records=reports)
    second = backtest_input_checksum(config, prices, None, structure_document_registry=registry, structure_report_records=changed)

    assert first != second

    holdings = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "holdings-1", "weight": 0.4}])
    changed_holdings = holdings.copy()
    changed_holdings.loc[0, "weight"] = 0.6
    holdings_first = backtest_input_checksum(
        config,
        prices,
        None,
        structure_document_registry=registry,
        structure_report_records=reports,
        structure_holdings=holdings,
    )
    holdings_second = backtest_input_checksum(
        config,
        prices,
        None,
        structure_document_registry=registry,
        structure_report_records=reports,
        structure_holdings=changed_holdings,
    )
    assert holdings_first != holdings_second
