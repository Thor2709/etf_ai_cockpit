from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_cockpit.application.ui_facade import load_financial_institution_projection
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority


DECISION = "2025-03-01T00:00:00Z"


def _context(decision: str = DECISION):
    values = {
        "instrument_type": "equity_certificate",
        "asset_class": "equity",
        "sector": "financials",
        "industry": "banks",
        "operating_country": "NO",
        "reporting_currency": "NOK",
        "entity_id": "937901003",
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"MING:{field}", instrument_id="MING", field=field,
            value=value, source="fixture", authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{field}", confidence=0.99,
            valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence, instrument_id="MING", effective_at="2024-12-31T00:00:00Z", decision_time=decision
    )


def _write_facts(root: Path, *, future_regulatory: bool = False, zero_deposits: bool = False) -> None:
    known = "2026-01-01T00:00:00Z" if future_regulatory else "2025-02-15T00:00:00Z"
    rows = [
        {"instrument_id": "MING", "canonical_metric": "net_interest_income", "value": 100.0, "unit": "NOK", "end": "2024-12-31", "known_at": known, "effective_at": "2024-12-31", "source_id": "esef_local_import:nim"},
        {"instrument_id": "MING", "canonical_metric": "operating_expenses", "value": 40.0, "unit": "NOK", "end": "2024-12-31", "known_at": known, "effective_at": "2024-12-31", "source_id": "esef_local_import:opex"},
        {"instrument_id": "MING", "canonical_metric": "loans_to_customers", "value": 800.0, "unit": "NOK", "end": "2024-12-31", "known_at": known, "effective_at": "2024-12-31", "source_id": "esef_local_import:loans"},
        {"instrument_id": "MING", "canonical_metric": "deposits_from_customers", "value": 0.0 if zero_deposits else 1000.0, "unit": "NOK", "end": "2024-12-31", "known_at": known, "effective_at": "2024-12-31", "source_id": "esef_local_import:deposits"},
        {"instrument_id": "MING", "canonical_metric": "cet1_ratio", "value": 0.18, "unit": "ratio", "end": "2024-12-31", "known_at": known, "effective_at": "2024-12-31", "source_id": "pillar3:cet1", "taxonomy": "pillar3"},
    ]
    pd.DataFrame(rows).to_parquet(root / "statement_facts.parquet", index=False)


def _metrics(payload):
    return {item["metric"]: item for item in payload["metrics"]}


def test_persisted_bank_route_builds_without_projection_injection(tmp_path: Path) -> None:
    _write_facts(tmp_path)
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    metrics = _metrics(payload)
    assert payload["business_model"] == "bank"
    assert metrics["cet1_ratio"]["fact_category"] == "pillar3"
    assert metrics["loan_deposit_ratio"]["value"] == 0.8


def test_missing_pillar3_is_explicitly_unavailable(tmp_path: Path) -> None:
    _write_facts(tmp_path, future_regulatory=True)
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    assert _metrics(payload)["cet1_ratio"]["status"] == "unavailable"
    assert "cet1_ratio:missing_value" in payload["limitations"]


def test_zero_denominator_never_becomes_zero_or_infinity(tmp_path: Path) -> None:
    _write_facts(tmp_path, zero_deposits=True)
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    metric = _metrics(payload)["loan_deposit_ratio"]
    assert metric["status"] == "unavailable" and metric["value"] is None
    assert "loan_deposit_ratio:invalid_denominator" in payload["limitations"]


def test_equity_certificate_identity_is_preserved(tmp_path: Path) -> None:
    _write_facts(tmp_path)
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    assert payload["share_class_identity"]["instrument_type"] == "equity_certificate"


def test_accounting_cet1_is_not_promoted_to_pillar3(tmp_path: Path) -> None:
    _write_facts(tmp_path)
    frame = pd.read_parquet(tmp_path / "statement_facts.parquet")
    frame.loc[frame["canonical_metric"].eq("cet1_ratio"), "source_id"] = "esef_local_import:accounting-cet1"
    frame.loc[frame["canonical_metric"].eq("cet1_ratio"), "taxonomy"] = "ifrs-full"
    frame.to_parquet(tmp_path / "statement_facts.parquet", index=False)
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    metric = _metrics(payload)["cet1_ratio"]
    assert metric["status"] == "unavailable" and "regulatory_fact_required" in metric["limitations"]


def test_currency_mismatch_blocks_calculated_ratio(tmp_path: Path) -> None:
    _write_facts(tmp_path)
    frame = pd.read_parquet(tmp_path / "statement_facts.parquet")
    frame.loc[frame["canonical_metric"].eq("deposits_from_customers"), "unit"] = "USD"
    frame.to_parquet(tmp_path / "statement_facts.parquet", index=False)
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    metric = _metrics(payload)["loan_deposit_ratio"]
    assert metric["status"] == "unavailable" and metric["value"] is None
    assert any("currency_mismatch" in item for item in payload["limitations"])


def test_share_count_alone_is_not_dilution_evidence(tmp_path: Path) -> None:
    _write_facts(tmp_path)
    frame = pd.read_parquet(tmp_path / "statement_facts.parquet")
    extra = frame.iloc[[0]].copy()
    extra["canonical_metric"], extra["value"], extra["unit"], extra["source_id"] = "shares_outstanding", 100.0, "shares", "esef_local_import:shares"
    pd.concat([frame, extra]).to_parquet(tmp_path / "statement_facts.parquet", index=False)
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    metric = _metrics(payload).get("issuance_dilution")
    assert metric is None or (metric["status"] == "unavailable" and metric["value"] is None)


def test_ec_revisions_are_selected_as_of_decision_time(tmp_path: Path) -> None:
    import json

    _write_facts(tmp_path)

    def revision(known_at: str, eierbrok: float) -> dict[str, object]:
        return {
            "instrument_id": "MING", "known_at": known_at, "filing_sha256": known_at,
            "facts": {"eierbrok": {"available": True, "value": eierbrok, "unit": "ratio", "period": "2024-12-31", "known_at": known_at}},
        }

    payload = {"instrument_id": "MING", "revisions": [revision("2025-02-01T00:00:00Z", 0.5), revision("2025-06-01T00:00:00Z", 0.6)]}
    (tmp_path / "ec_facts.json").write_text(json.dumps(payload), encoding="utf-8")
    early = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time=DECISION, context=_context())
    late = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time="2025-07-01T00:00:00Z", context=_context("2025-07-01T00:00:00Z"))
    assert early["share_class_identity"]["facts"]["eierbrok"]["value"] == 0.5
    assert late["share_class_identity"]["facts"]["eierbrok"]["value"] == 0.6
