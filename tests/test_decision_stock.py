from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.decision.contracts import DecisionDriver, DomainSlot
from etf_cockpit.analysis.decision.opportunity import build_opportunity_results
from etf_cockpit.analysis.decision import shadow_run
from etf_cockpit.analysis.decision.stock import (
    compose_stock_decision,
    load_stock_decision_map,
)
from etf_cockpit.analysis.financial_sector_adapters import (
    FINANCIAL_ADAPTER_CONTRACT,
    FINANCIAL_ADAPTER_ID,
)
from etf_cockpit.analysis.sparebank.models import CONTRACT_ID as SPAREBANK_ANALYSIS_CONTRACT
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.stock_research import (
    build_stock_research_report,
    valuation_analysis,
)


DECISION_TIME = "2027-12-31T00:00:00Z"
_DOMAIN_IDS = (
    "profitability_economic_returns",
    "earnings_cash_quality",
    "financial_resilience",
    "growth_reinvestment_quality",
    "capital_allocation_shareholder_treatment",
    "durability",
)


def _context(
    instrument: str,
    *,
    sector: str = "industrial",
    issuer_type: str | None = None,
    domicile: str | None = None,
    subtype: str | None = None,
    business_model: str = "software",
):
    labels = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": sector,
        "industry": "software" if sector == "industrial" else "commercial bank",
        "business_model_tag": business_model,
    }
    if issuer_type:
        labels["issuer_type"] = issuer_type
    if domicile:
        labels["legal_domicile"] = domicile
        labels["regulatory_country"] = domicile
    if subtype:
        labels["instrument_subtype"] = subtype
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument}:{field}",
            instrument_id=instrument,
            field=field,
            value=value,
            source="DA-002 test fixture",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{instrument}:{field}",
            confidence=0.95,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in labels.items()
    )
    return resolve_instrument_context(
        evidence,
        instrument_id=instrument,
        effective_at="2026-12-31T00:00:00Z",
        decision_time=DECISION_TIME,
    )


def _statement_rows(*, exact_timing: bool = True) -> pd.DataFrame:
    annual = {
        2024: {
            "gross_profit": 35.0,
            "revenue": 100.0,
            "net_income": 10.0,
            "cash_from_operations": 13.0,
            "assets": 120.0,
            "equity": 50.0,
            "debt": 35.0,
            "cash": 8.0,
            "operating_income": 16.0,
            "interest_expense": 4.0,
            "income_before_tax": 13.0,
            "tax_expense": 3.0,
            "free_cash_flow": 10.0,
            "diluted_shares_outstanding": 10.0,
        },
        2025: {
            "gross_profit": 40.0,
            "revenue": 110.0,
            "net_income": 13.0,
            "cash_from_operations": 17.0,
            "assets": 125.0,
            "equity": 58.0,
            "debt": 32.0,
            "cash": 10.0,
            "operating_income": 20.0,
            "interest_expense": 3.0,
            "income_before_tax": 17.0,
            "tax_expense": 4.0,
            "free_cash_flow": 14.0,
            "diluted_shares_outstanding": 10.0,
        },
        2026: {
            "gross_profit": 48.0,
            "revenue": 120.0,
            "net_income": 17.0,
            "cash_from_operations": 22.0,
            "assets": 130.0,
            "equity": 68.0,
            "debt": 30.0,
            "cash": 12.0,
            "operating_income": 25.0,
            "interest_expense": 2.0,
            "income_before_tax": 22.0,
            "tax_expense": 5.0,
            "free_cash_flow": 19.0,
            "diluted_shares_outstanding": 10.0,
        },
    }
    rows: list[dict[str, object]] = []
    for year, metrics in annual.items():
        for name, value in metrics.items():
            row: dict[str, object] = {
                "instrument_id": "ACME",
                "canonical_metric": name,
                "value": value,
                "period_type": "annual",
                "period_key": f"FY{year}",
                "period_end": f"{year}-12-31",
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "fiscal_year": year,
                "fiscal_period": "FY",
                "currency": "EUR",
                "consolidation_scope": "consolidated",
                "source_id": f"{name}:{year}",
                "filed": f"{year + 1}-02-15T00:00:00Z",
                "effective_at": f"{year}-12-31",
            }
            if exact_timing:
                row["known_at"] = f"{year + 1}-02-15T00:00:00Z"
                row["available_at"] = row["known_at"]
            rows.append(row)
    return pd.DataFrame(rows)


def _report(*, exact_timing: bool = True) -> dict[str, object]:
    return build_stock_research_report(
        _statement_rows(exact_timing=exact_timing),
        instrument_id="ACME",
        sector="industrial",
        classification_context={"classification_status": "resolved"},
        as_known_at=DECISION_TIME if exact_timing else None,
        strict_comparability=True,
    )


def _valuation_rows() -> pd.DataFrame:
    rows = []
    values = {
        "free_cash_flow": 19.0,
        "diluted_shares_outstanding": 10.0,
        "debt": 30.0,
        "cash": 12.0,
        "equity": 68.0,
        "net_income": 17.0,
    }
    for metric, value in values.items():
        rows.append(
            {
                "instrument_id": "ACME",
                "canonical_metric": metric,
                "value": value,
                "period_type": "annual",
                "period_key": "FY2026",
                "period_end": "2026-12-31",
                "start": "2026-01-01",
                "end": "2026-12-31",
                "fiscal_year": 2026,
                "fiscal_period": "FY",
                "currency": "EUR",
                "consolidation_scope": "consolidated",
                "source_id": f"{metric}:2026",
                "effective_at": "2026-12-31",
                "known_at": "2027-02-15T00:00:00Z",
                "available_at": "2027-02-15T00:00:00Z",
            }
        )
    return pd.DataFrame(rows)


def _valuation_inputs(*, price_known_at: str | None = "2027-01-02T00:00:00Z"):
    market = {
        "share_price": 8.0,
        "share_price_source_id": "market:ACME:close",
        "price_timestamp": "2026-12-31T00:00:00Z",
        "price_known_at": price_known_at,
    }
    assumptions = {
        "forecast_years": 5,
        "discount_rate": 0.10,
        "cost_of_equity": 0.11,
        "terminal_growth": 0.02,
        "scenarios": {"base": {"growth": 0.04}},
        "source_provenance": {
            "dcf": [
                {
                    "source_id": "assumption:dcf-v1",
                    "effective_at": "2026-12-31T00:00:00Z",
                    "known_at": "2027-01-02T00:00:00Z",
                }
            ],
            "residual_income": [
                {
                    "source_id": "assumption:ri-v1",
                    "effective_at": "2026-12-31T00:00:00Z",
                    "known_at": "2027-01-02T00:00:00Z",
                }
            ],
        },
    }
    return market, assumptions


def test_stock_mapping_declares_six_equal_underwriting_questions() -> None:
    stock_map = load_stock_decision_map()

    assert tuple(item["domain"] for item in stock_map.domains) == _DOMAIN_IDS
    assert {item["weight"] for item in stock_map.domains} == {1.0}
    assert stock_map.registry.version == "stock-decision-v1.0.0"
    assert stock_map.rank_authority is True
    assert stock_map.stock_sources["gross_margin"] == "profitability.metrics.gross_margin"


def test_generic_stock_composes_six_domains_and_keeps_other_evidence_separate() -> None:
    context = _context("ACME")
    report = _report()

    result = compose_stock_decision("ACME", context, DECISION_TIME, report)

    assert result["route"] == "generic_stock"
    assert tuple(slot.domain for slot in result["underwriting_domains"]) == _DOMAIN_IDS
    assert result["valuation"]["dcf"] == report["valuation"]["intrinsic_value"]
    assert result["expectations"] == report["expectations"]
    assert result["execution_allowed"] is False

    biotech = compose_stock_decision(
        "BIO",
        _context("BIO", sector="healthcare", business_model="biotechnology"),
        DECISION_TIME,
        {
            "profitability": {
                "metrics": {"net_income": {"status": "unavailable", "value": None}}
            },
            "valuation": {},
        },
    )
    assert biotech["valuation"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert biotech["valuation"]["reason_code"] == "NO_DEFENSIBLE_VALUATION_COMPONENT"


def test_expectations_and_one_price_family_vote_do_not_change_underwriting() -> None:
    context = _context("ACME")
    report = _report()
    plain = compose_stock_decision("ACME", context, DECISION_TIME, report)
    enriched = compose_stock_decision(
        "ACME",
        context,
        DECISION_TIME,
        report,
        tactical_evidence={
            "momentum": {"status": "available", "value": 0.7},
            "trend": {"status": "available", "value": 0.4},
            "relative_strength": {"status": "available", "value": 0.6},
            "earnings_momentum": {"status": "available", "value": 0.8},
            "model_evidence": {"status": "available", "value": 0.2},
        },
    )
    report["expectations"] = {"status": "available", "agreement": 0.5}
    expectations_changed = compose_stock_decision(
        "ACME", context, DECISION_TIME, report
    )

    assert plain["underwriting_domains"] == enriched["underwriting_domains"]
    assert plain["underwriting_domains"] == expectations_changed["underwriting_domains"]
    assert enriched["tactical"]["price_family"]["vote_count"] == 1
    assert enriched["tactical"]["price_family"]["combined_value"] is None
    assert set(enriched["tactical"]) >= {"price_family", "earnings_momentum", "model_evidence"}


def test_missing_exact_metric_known_at_is_unavailable_not_report_lineage() -> None:
    context = _context("ACME")
    report = _report(exact_timing=False)

    result = compose_stock_decision("ACME", context, DECISION_TIME, report)
    gross_margin = result["underwriting_input_evidence"]["gross_margin"]

    assert gross_margin["value"] == 0.4
    assert gross_margin["decision_status"] == "UNAVAILABLE"
    assert gross_margin["reason_code"] == "EXACT_SOURCE_TIMING_UNAVAILABLE"
    assert gross_margin["source_provenance"]
    assert all(item["known_at"] is None for item in gross_margin["source_provenance"])

    missing_value = compose_stock_decision(
        "ACME",
        _context("ACME"),
        DECISION_TIME,
        _report(),
        capital_allocation={
            "metrics": {
                "shareholder_yield": {
                    "value": None,
                    "status": "missing",
                    "source_timing_status": "available",
                    "source_provenance": [
                        {
                            "source_id": "payout-2026",
                            "effective_at": "2026-12-31",
                            "known_at": "2027-02-15T00:00:00Z",
                        }
                    ],
                }
            }
        },
    )
    missing_yield = missing_value["underwriting_input_evidence"]["shareholder_yield"]
    assert missing_yield["decision_status"] == "UNAVAILABLE"
    assert missing_yield["reason_code"] == "METRIC_VALUE_UNAVAILABLE"


def test_margin_of_safety_is_per_model_and_uses_canonical_price_provenance() -> None:
    market, assumptions = _valuation_inputs()
    market.update(
        market_cap=165.0,
        market_cap_source_id="market:ACME:market-cap",
        market_cap_effective_at="2026-12-31T00:00:00Z",
        market_cap_known_at="2027-01-02T00:00:00Z",
    )
    assumptions["reverse_dcf_reference"] = {
        "growth": 0.25,
        "source_provenance": [
            {
                "source_id": "reference-growth-v1",
                "effective_at": "2026-12-31T00:00:00Z",
                "known_at": "2027-01-02T00:00:00Z",
            }
        ],
    }

    result = valuation_analysis(
        _valuation_rows(),
        instrument_id="ACME",
        market_inputs=market,
        assumptions=assumptions,
    )
    mos = result["margin_of_safety"]["models"]

    assert mos["dcf:base"]["status"] == "available"
    assert mos["residual_income"]["status"] == "available"
    assert mos["dcf:base"]["value"] == (mos["dcf:base"]["per_share_value"] - 8.0) / 8.0
    assert mos["residual_income"]["value"] == (mos["residual_income"]["per_share_value"] - 8.0) / 8.0
    assert mos["dcf:base"]["value"] != mos["residual_income"]["value"]
    reverse_gap = result["reverse_dcf_gap"]
    assert result["reverse_dcf"]["status"] == "available"
    assert reverse_gap["status"] == "available"
    assert reverse_gap["value"] == (
        reverse_gap["reference_growth"] - reverse_gap["implied_growth"]
    )
    assert reverse_gap["formula"] == "explicit_reference_growth - reverse_dcf_implied_growth"
    composed = compose_stock_decision(
        "ACME",
        _context("ACME"),
        DECISION_TIME,
        {"valuation": result},
    )
    assert composed["valuation"]["status"] == "AVAILABLE"


def test_margin_of_safety_fails_closed_for_missing_price_timing_or_nonpositive_price() -> None:
    market, assumptions = _valuation_inputs(price_known_at=None)
    missing_timing = valuation_analysis(
        _valuation_rows(),
        instrument_id="ACME",
        market_inputs=market,
        assumptions=assumptions,
    )
    market["share_price"] = 0.0
    nonpositive = valuation_analysis(
        _valuation_rows(),
        instrument_id="ACME",
        market_inputs=market,
        assumptions=assumptions,
    )

    assert missing_timing["margin_of_safety"]["models"]["dcf:base"]["status"] == "unavailable"
    assert "price_source_timing_unavailable" in missing_timing["margin_of_safety"]["models"]["dcf:base"]["reason_codes"]
    assert nonpositive["margin_of_safety"]["models"]["residual_income"]["status"] == "unavailable"
    assert "positive_current_price_unavailable" in nonpositive["margin_of_safety"]["models"]["residual_income"]["reason_codes"]


def test_financial_institution_uses_financial_adapter_metrics_not_generic_stock_metrics() -> None:
    context = _context(
        "BANK",
        sector="financials",
        issuer_type="bank",
        business_model="bank",
    )
    row = SimpleNamespace(
        metric="roe",
        status="available",
        value=0.12,
        unit="ratio",
        direction="higher_is_better",
        period="FY2026",
        business_model="bank",
        source_id="bank-filing-2026",
        as_of="2026-12-31T00:00:00Z",
        known_at="2027-02-15T00:00:00Z",
        confidence=0.9,
    )
    projection = SimpleNamespace(
        status="available",
        contract=FINANCIAL_ADAPTER_CONTRACT,
        instrument_id="BANK",
        adapter_id=FINANCIAL_ADAPTER_ID,
        execution_allowed=False,
        metrics=(row,),
    )

    result = compose_stock_decision(
        "BANK",
        context,
        DECISION_TIME,
        {"expectations": {}, "valuation": {}},
        financial_projection=projection,
    )

    assert result["route"] == "financial_sector_adapter"
    assert result["route_status"] == "available"
    assert len(result["underwriting_domains"]) == 6
    assert "financial:profitability_economic_returns:roe" in result["underwriting_input_evidence"]
    assert "gross_margin" not in result["underwriting_input_evidence"]

    insurer_context = _context(
        "INSURER",
        sector="financials",
        issuer_type="insurer",
        business_model="insurer",
    )
    solvency = SimpleNamespace(
        metric="solvency_capital_ratio",
        status="available",
        value=175.0,
        unit="percent",
        direction="higher_is_better",
        period="FY2026",
        business_model="insurer",
        source_id="insurer-filing-2026",
        as_of="2026-12-31T00:00:00Z",
        known_at="2027-02-15T00:00:00Z",
        confidence=0.9,
    )
    insurer_projection = SimpleNamespace(
        status="available",
        contract=FINANCIAL_ADAPTER_CONTRACT,
        instrument_id="INSURER",
        adapter_id=FINANCIAL_ADAPTER_ID,
        execution_allowed=False,
        metrics=(solvency,),
    )
    insurer_result = compose_stock_decision(
        "INSURER",
        insurer_context,
        DECISION_TIME,
        {"valuation": {}},
        financial_projection=insurer_projection,
    )
    solvency_id = "financial:financial_resilience:solvency_capital_ratio"
    solvency_evidence = insurer_result["underwriting_input_evidence"][solvency_id]
    assert insurer_result["route"] == "financial_sector_adapter"
    assert solvency_evidence["value"] == 175.0
    assert solvency_evidence["metric_shape"] == "threshold_or_plateau"
    assert solvency_evidence["decision_status"] == "UNAVAILABLE"
    assert solvency_evidence["reason_code"] == "VERSIONED_PLATEAU_THRESHOLD_UNAVAILABLE"
    assert not any(
        driver.metric_id == solvency_id
        for driver in insurer_result["underwriting"].drivers
    )


def test_confirmed_norwegian_ec_bypasses_generic_and_requires_native_result() -> None:
    context = _context(
        "EC1",
        sector="financials",
        issuer_type="savings_bank",
        domicile="Norway",
        subtype="equity_certificate",
        business_model="savings_bank",
    )
    native_valuation = {"status": "resolved", "owner_pb": 1.2, "owner_eps": 0.5}
    native_tactical = {
        "status": "available",
        "evidence": {"native_spbk_signal": {"status": "available", "value": 0.4}},
        "affects_underwriting": False,
    }
    report = {
        "expectations": {"status": "available", "consensus": "generic-only"},
        "valuation": {"intrinsic_value": {"status": "available", "per_share": 999.0}},
    }
    native = SimpleNamespace(
        contract=SPAREBANK_ANALYSIS_CONTRACT,
        routing=SimpleNamespace(applies=True),
        execution_allowed=False,
        valuation=native_valuation,
        scorecard=SimpleNamespace(tactical=native_tactical),
    )

    routed = compose_stock_decision(
        "EC1",
        context,
        DECISION_TIME,
        report,
        native_spbk_result=native,
        tactical_evidence={"momentum": {"status": "available", "value": 1.0}},
    )
    missing = compose_stock_decision("EC1", context, DECISION_TIME, report)

    assert routed["route"] == "norwegian_ec_native_spbk"
    assert routed["assessment"] is native
    assert routed["underwriting"] is None
    assert routed["underwriting_domains"] == ()
    assert routed["valuation"] == native_valuation
    assert routed["expectations"]["status"] == "unavailable"
    assert routed["expectations"]["reason_code"] == "NATIVE_SPBK_EXPECTATIONS_NOT_EXPOSED"
    assert "consensus" not in routed["expectations"]
    assert routed["tactical"] == native_tactical
    assert missing["route_status"] == "unavailable"
    assert missing["route_reason"] == "NATIVE_SPBK_RESULT_MISSING"
    assert missing["underwriting"] is None
    assert missing["valuation"]["status"] == "unavailable"
    assert missing["expectations"]["status"] == "unavailable"
    assert missing["tactical"]["status"] == "unavailable"


def test_stock_composer_exposes_point_in_time_valuation_domain_score() -> None:
    result = compose_stock_decision(
        "ACME",
        _context("ACME"),
        DECISION_TIME,
        _report(),
    )

    valuation_domain = result["valuation_domain"]
    assert valuation_domain.domain == "valuation"
    assert valuation_domain.status == "UNAVAILABLE"
    assert valuation_domain.reason_code
    assert result["valuation_z_score"] is None
    assert isinstance(result["valuation_drivers"], tuple)


def test_shadow_routes_equity_certificate_through_stock_composer(monkeypatch) -> None:
    instrument = "CERT"
    config = SimpleNamespace(
        universe=SimpleNamespace(
            etfs=(SimpleNamespace(id=instrument, instrument_type="equity_certificate"),),
            enabled_ids=(instrument,),
        )
    )
    stock_calls: list[str] = []
    monkeypatch.setattr(
        shadow_run,
        "read_instrument_context",
        lambda *args, **kwargs: SimpleNamespace(instrument_type=None),
    )
    monkeypatch.setattr(shadow_run, "load_etf_economics_records", lambda: ())
    monkeypatch.setattr(
        shadow_run,
        "_prepare_stock_candidate",
        lambda identity, *args: (
            stock_calls.append(identity)
            or {"instrument": identity, "asset_type": "stock", "peer_id": "unavailable"}
        ),
    )
    monkeypatch.setattr(
        shadow_run,
        "_prepare_etf_candidate",
        lambda *args, **kwargs: pytest.fail("equity certificate used ETF route"),
    )
    monkeypatch.setattr(
        shadow_run,
        "_compose_stock_candidate",
        lambda prepared, *args: {**prepared, "route": "stock"},
    )

    rows = shadow_run._compose_universe(
        config, (), datetime.now(timezone.utc), latest_features=None
    )

    assert stock_calls == [instrument]
    assert rows[0]["route"] == "stock"


def test_stock_shadow_candidate_includes_valuation_negative_drivers(monkeypatch) -> None:
    underwriting_driver = DecisionDriver(
        "quality_metric", "AVAILABLE", 1.0, "ratio", 2.0, "AVAILABLE"
    )
    valuation_driver = DecisionDriver(
        "valuation_metric", "AVAILABLE", 20.0, "ratio", -3.0, "AVAILABLE"
    )
    assessment = SimpleNamespace(
        eligibility_results=(),
        gate_results=(),
        drivers=(underwriting_driver,),
        source_vintage_hash="source:test",
    )
    composed = {
        "assessment": assessment,
        "underwriting_domains": (
            DomainSlot("Underwriting", "AVAILABLE", 2.0, 2.0, 1.0, 0.8, "AVAILABLE"),
        ),
        "underwriting_domain_labels": {},
        "underwriting_z_score": 2.0,
        "valuation_domain": DomainSlot(
            "valuation", "AVAILABLE", -3.0, -3.0, 1.0, 0.8, "AVAILABLE"
        ),
        "valuation_z_score": -3.0,
        "critical_underwriting_domains": (),
        "valuation_drivers": (valuation_driver,),
    }
    monkeypatch.setattr(
        shadow_run, "compose_stock_decision", lambda *args, **kwargs: composed
    )
    candidate = shadow_run._compose_stock_candidate(
        {"instrument": "ACME", "context": object(), "research": {}},
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        (),
        minimum_support=3,
    )

    result = build_opportunity_results(
        (candidate,), decision_time="2026-01-01T00:00:00Z"
    )["ACME"]

    assert {driver.metric_id for driver in candidate["drivers"]} == {
        "quality_metric",
        "valuation_metric",
    }
    assert any(
        driver.metric_id == "valuation_metric"
        for driver in result.negative_drivers
    )
