"""Bughunt B108 / B008 regression tests for the cyclical, real-asset, financial and innovation adapters."""

from __future__ import annotations

from dataclasses import replace

import pytest

from etf_cockpit.analysis.cyclical_sector_adapters import (
    CyclicalAdapterError,
    CyclicalMetricEvidence,
    CycleHistoryEvidence,
    build_cyclical_projection,
    cyclical_adapter_definitions,
)
from etf_cockpit.analysis.financial_sector_adapters import (
    FinancialAdapterError,
    FinancialMetricEvidence,
    build_financial_institution_projection,
    financial_adapter_definition,
    financial_formula_registry,
)
from etf_cockpit.analysis.innovation_sector_adapters import (
    InnovationMetricEvidence,
    build_innovation_projection,
    innovation_adapter_definitions,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.analysis.real_asset_sector_adapters import (
    RealAssetAdapterError,
    RealAssetMetricEvidence,
    build_real_asset_projection,
    real_asset_adapter_definitions,
)
from etf_cockpit.analysis.sparebank import analyse_sparebank_ec
from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.analysis.sparebank.valuation import valuation
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority


DECISION = "2025-03-01T00:00:00Z"
ASOF = "2024-12-31T00:00:00Z"
KNOWN = "2025-02-15T00:00:00Z"


def _context(model: str, sector: str, *, industry: str | None = None, country: str = "AU"):
    iid = f"{model}-1"
    values = {
        "instrument_type": "stock", "asset_class": "equity", "sector": sector,
        "industry": industry or model, "business_model_tag": model,
        "operating_country": country, "reporting_currency": "AUD", "entity_id": iid,
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{iid}:{field}", instrument_id=iid, field=field, value=value,
            source="fixture", authority=SourceAuthority.OFFICIAL, source_id=f"fixture:{field}",
            confidence=0.99, valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence, instrument_id=iid, effective_at=ASOF, decision_time=DECISION,
    )


# ---------------------------------------------------------------- cyclical (B108-N001)


def _cyc(metric, value, unit, *, as_of=ASOF, known_at=KNOWN):
    return CyclicalMetricEvidence(
        metric, value, unit, "FY2024", "IFRS", "AU", "industrials", f"issuer:{metric}",
        SourceAuthority.ISSUER, as_of, known_at,
    )


def _cyc_build(evidence):
    history = tuple(
        CycleHistoryEvidence(
            f"cycle-{i}", "trough_to_peak", f"{2010 + i * 5}-01-01T00:00:00Z",
            f"{2013 + i * 5}-12-31T00:00:00Z", "2025-02-01T00:00:00Z", f"issuer:cycle-{i}",
            SourceAuthority.ISSUER,
        )
        for i in range(2)
    )
    return build_cyclical_projection(
        _context("industrials", "industrials"), evidence, cycle_history=history,
        registry=AdapterRegistry(cyclical_adapter_definitions()), decision_time=DECISION,
        scenarios={},
    )


@pytest.mark.parametrize("metric", ["utilisation", "backlog_quality", "customer_concentration"])
def test_cyclical_percent_input_is_converted_not_rejected(metric):
    result = _cyc_build((_cyc(metric, 85.0, "percent"),))
    row = next(item for item in result.metrics if item.metric == metric)
    assert (row.status, row.unit) == ("available", "ratio")
    assert row.value == pytest.approx(0.85)


def test_cyclical_ratio_input_is_not_converted_twice_and_out_of_bounds_still_rejected():
    result = _cyc_build((_cyc("utilisation", 0.85, "ratio"),))
    assert next(i for i in result.metrics if i.metric == "utilisation").value == pytest.approx(0.85)
    with pytest.raises(CyclicalAdapterError, match="outside canonical bounds"):
        _cyc_build((_cyc("utilisation", 185.0, "percent"),))


# ---------------------------------------------------------------- as_of > known_at (B108-N002)


def _fin(metric="cet1_ratio", value=0.14, *, as_of=ASOF, known_at=KNOWN, unit="ratio", direction=None):
    return FinancialMetricEvidence(
        metric=metric, value=value, unit=unit, period="FY2024", reporting_standard="IFRS",
        jurisdiction="AU", business_model="bank", source_id=f"regulator:{metric}",
        source_authority=SourceAuthority.OFFICIAL, as_of=as_of, known_at=known_at,
        fact_category="pillar3" if metric in {"cet1_ratio", "total_capital_ratio", "capital_requirement", "capital_headroom"} else "ifrs",
        direction=direction,
    )


def _fin_build(evidence):
    return build_financial_institution_projection(
        _context("bank", "financials", industry="banks"), evidence,
        registry=AdapterRegistry([financial_adapter_definition()]),
        decision_time=DECISION, shocks={},
    )


def _ra(metric, value, *, unit="currency", period="FY2024", as_of=ASOF, known_at=KNOWN, model="reit"):
    return RealAssetMetricEvidence(
        metric=metric, value=value, unit=unit, period=period, reporting_standard="IFRS",
        jurisdiction="AU", business_model=model, source_id=f"issuer:{metric}",
        source_authority=SourceAuthority.ISSUER, as_of=as_of, known_at=known_at,
    )


def _ra_build(evidence, model="reit"):
    sector = {"reit": "real_estate", "utility": "utilities", "infrastructure": "industrials"}[model]
    return build_real_asset_projection(
        _context(model, sector), evidence,
        registry=AdapterRegistry(real_asset_adapter_definitions()),
        decision_time=DECISION, shocks={},
    )


def test_as_of_after_known_at_is_rejected_by_all_validators():
    future_as_of = "2025-02-20T00:00:00Z"  # after known_at, before decision
    with pytest.raises(FinancialAdapterError, match="lineage"):
        _fin_build((_fin(as_of=future_as_of),))
    with pytest.raises(RealAssetAdapterError, match="lineage"):
        _ra_build((_ra("net_debt", 300.0, as_of=future_as_of),))
    with pytest.raises(CyclicalAdapterError, match="lineage"):
        _cyc_build((_cyc("utilisation", 0.5, "ratio", as_of=future_as_of),))
    # the equal case stays valid
    assert _fin_build((_fin(as_of=KNOWN),)).metrics[0].status == "available"
    assert _ra_build((_ra("net_debt", 300.0, as_of=KNOWN),)).metrics


# ---------------------------------------------------------------- bank capital (B108-N003, B008)


def test_higher_capital_requirement_is_lower_is_better():
    direction = {r.metric: r.direction for r in financial_formula_registry() if r.business_model == "bank"}
    assert direction["capital_requirement"] == "lower_is_better"
    assert direction["capital_headroom"] == "higher_is_better"
    with pytest.raises(FinancialAdapterError, match="unit or direction"):
        _fin_build((_fin("capital_requirement", 0.10, direction="higher_is_better"),))
    result = _fin_build((_fin("capital_requirement", 0.10, direction="lower_is_better"),))
    assert result.metrics[0].direction == "lower_is_better"


def test_stale_cet1_is_unavailable_and_fresh_cet1_available():
    stale = _fin_build((_fin("cet1_ratio", as_of="2023-06-30T00:00:00Z", known_at="2023-08-15T00:00:00Z"),))
    row = stale.metrics[0]
    assert (row.status, row.value) == ("unavailable", None)
    assert "stale" in row.limitations
    assert stale.authority_status == "limited"
    assert _fin_build((_fin("cet1_ratio"),)).metrics[0].status == "available"


def test_bank_confidence_reflects_evidence_coverage():
    thin = _fin_build((_fin("cet1_ratio"), _fin("total_capital_ratio", 0.17)))
    full = _fin_build(tuple(
        _fin(r.metric, 100.0 if r.allowed_units[0] != "ratio" else 0.12,
             unit=r.allowed_units[0])
        for r in financial_formula_registry() if r.business_model == "bank"
    ))
    assert thin.aggregate_confidence < 0.2 < 0.8 <= full.aggregate_confidence
    assert thin.authority_status == "limited"


# ---------------------------------------------------------------- REIT (B108-N004, B008)


def _reit(**overrides):
    values = {
        "net_income": 100.0, "depreciation_amortisation": 40.0, "property_sale_gains": 10.0,
        "maintenance_capex": 20.0, "recurring_adjustments": 5.0, "distributions": 92.0,
        "net_debt": 300.0, "ebitda": 150.0, "interest_expense": 30.0, "nav": 400.0,
    }
    values.update(overrides)
    return tuple(_ra(name, value) for name, value in values.items())


def test_negative_affo_payout_is_unavailable():
    # FFO 130 - maintenance capex 200 + 5 = -65 -> negative AFFO
    result = _ra_build(_reit(maintenance_capex=200.0))
    payout = next(c for c in result.checks if c.check == "payout")
    assert (payout.status, payout.value) == ("unavailable", None)
    affo = next(m for m in result.metrics if m.metric == "affo")
    assert affo.value == -65.0
    healthy = next(c for c in _ra_build(_reit()).checks if c.check == "payout")
    assert healthy.status == "available" and healthy.value == pytest.approx(92.0 / 115.0)
    negative_distribution = next(c for c in _ra_build(_reit(distributions=-5.0)).checks if c.check == "payout")
    assert negative_distribution.status == "unavailable"


def test_ffo_inputs_from_mixed_periods_are_unavailable():
    evidence = tuple(
        replace(item, period="FY2023") if item.metric == "depreciation_amortisation" else item
        for item in _reit()
    )
    result = _ra_build(evidence)
    ffo = next(m for m in result.metrics if m.metric == "ffo")
    affo = next(m for m in result.metrics if m.metric == "affo")
    assert (ffo.status, ffo.value) == ("unavailable", None)
    assert "period_mismatch" in ffo.limitations
    assert affo.status == "unavailable"
    assert next(c for c in result.checks if c.check == "payout").status == "unavailable"
    consistent = _ra_build(_reit())
    assert next(m for m in consistent.metrics if m.metric == "ffo").value == 130.0


def test_real_asset_percent_ratio_is_converted_once():
    result = _ra_build(_reit() + (_ra("occupancy_rate", 95.0, unit="percent"), _ra("loan_to_value", 0.4, unit="ratio")))
    rows = {m.metric: m for m in result.metrics}
    assert (rows["occupancy_rate"].value, rows["occupancy_rate"].unit) == (pytest.approx(0.95), "ratio")
    assert rows["loan_to_value"].value == pytest.approx(0.4)


# ---------------------------------------------------------------- biotech runway (B008)


def _bio(metric, value, unit="currency", period="FY2024"):
    return InnovationMetricEvidence(
        metric=metric, value=value, unit=unit, period=period, reporting_standard="IFRS",
        jurisdiction="AU", business_model="biotech", source_id=f"issuer:{metric}",
        source_authority=SourceAuthority.ISSUER, as_of=ASOF, known_at=KNOWN,
    )


def test_biotech_runway_from_mixed_periods_is_unavailable():
    def build(burn_period):
        return build_innovation_projection(
            _context("biotech", "healthcare"),
            (
                _bio("cash_balance", 120.0),
                _bio("operating_cash_burn", 30.0, "currency_per_month", burn_period),
                _bio("cash_runway_months", 4.0, "months"),
            ),
            events=(), registry=AdapterRegistry(innovation_adapter_definitions()),
            decision_time=DECISION,
        )

    ok = next(m for m in build("FY2024").metrics if m.metric == "cash_runway_months")
    assert (ok.status, ok.value) == ("available", 4.0)
    mixed = build("FY2022")
    runway = next(m for m in mixed.metrics if m.metric == "cash_runway_months")
    assert (runway.status, runway.value) == ("unavailable", None)
    assert "cash_runway_reconciliation:period_mismatch" in mixed.limitations


def test_real_asset_net_cash_leverage_stays_available():
    result = _ra_build(_reit(net_debt=-50.0, ebitda=100.0))
    leverage = next(c for c in result.checks if c.check == "leverage")
    assert (leverage.status, leverage.value) == ("available", pytest.approx(-0.5))


# ---------------------------------------------------------------- sustainable ROE unit (B116)


def test_sustainable_roe_percent_and_ratio_value_identically():
    facts = {
        "ec_capital": {"available": True, "value": 100.0}, "overkursfond": {"available": True, "value": 50.0},
        "utjevningsfond": {"available": True, "value": 250.0}, "sparebankens_fond": {"available": True, "value": 600.0},
        "gavefond": {"available": True, "value": 0.0}, "registered_ec_count": {"available": True, "value": 4.0},
        "ec_attributable_result": {"available": True, "value": 48.0},
    }
    claim = build_claim_state({"facts": facts, "effective_at": "2024-12-31", "known_at": "2025-03-01T00:00:00Z", "source_url": "synthetic"})
    base = {"cost_of_equity": 0.09, "long_run_growth": 0.03}
    ratio = valuation(claim, price=150.0, assumptions={**base, "sustainable_roe": 0.12})
    percent = valuation(claim, price=150.0, assumptions={**base, "sustainable_roe_pct": 12})
    assert ratio["central_owner_value_per_ec"]["justified_pb"] == pytest.approx(1.5)
    assert percent["central_owner_value_per_ec"]["justified_pb"] == pytest.approx(1.5)
    assert percent["central_owner_value_per_ec"]["sustainable_roe"] == pytest.approx(0.12)


def test_sustainable_roe_percent_assumption_is_converted_before_the_owner_bridge():
    facts = {
        "ec_capital": {"available": True, "value": 100.0}, "overkursfond": {"available": True, "value": 50.0},
        "utjevningsfond": {"available": True, "value": 250.0}, "sparebankens_fond": {"available": True, "value": 600.0},
        "gavefond": {"available": True, "value": 0.0}, "registered_ec_count": {"available": True, "value": 4.0},
        "ec_attributable_result": {"available": True, "value": 48.0},
    }
    evidence = {"facts": facts, "effective_at": "2024-12-31", "known_at": "2025-03-01T00:00:00Z", "source_url": "synthetic"}
    out = {}
    for key, raw in (("sustainable_roe", 0.12), ("sustainable_roe_pct", 12)):
        analysis = analyse_sparebank_ec(
            evidence, decision_time="2025-03-02T00:00:00Z", price=150.0,
            valuation_assumptions={"cost_of_equity": 0.09, "long_run_growth": 0.03, key: raw},
        )
        out[key] = analysis.valuation["central_owner_value_per_ec"]
    assert out["sustainable_roe_pct"]["justified_pb"] == pytest.approx(out["sustainable_roe"]["justified_pb"]) == pytest.approx(1.5)
