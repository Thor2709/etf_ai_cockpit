from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.bank_metric_facts import _financial_metric_facts
from etf_cockpit.analysis.financial_sector_adapters import (
    FinancialAdapterError,
    FinancialMetricEvidence,
    bank_metric_acceptance_report,
    build_financial_institution_projection,
    financial_adapter_definition,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.data.contracts import SourceAuthority
from tests.test_financial_sector_adapters import DECISION, _context

CUTOFF = "2025-03-01T00:00:00Z"
CONTEXT = SimpleNamespace(operating_country="NO")


def _row(metric: str, value: float, *, end: str = "2024-12-31", unit: str = "NOK", source_id: str | None = None, **extra: object) -> dict[str, object]:
    return {
        "canonical_metric": metric,
        "value": value,
        "unit": unit,
        "currency": "NOK" if unit == "NOK" else None,
        "end": end,
        "effective_at": end,
        "source_id": source_id or f"src:{metric}",
        "_effective": pd.Timestamp(end, tz="UTC"),
        "_known": pd.Timestamp("2025-02-15", tz="UTC"),
        **extra,
    }


def _by_metric(facts: list[FinancialMetricEvidence]) -> dict[str, FinancialMetricEvidence]:
    return {item.metric: item for item in facts}


def test_income_mix_uses_statement_income_lines_and_fails_closed() -> None:
    rows = [_row("net_interest_income", 800.0), _row("net_fee_income", 150.0), _row("other_operating_income", 50.0)]
    facts = _by_metric(_financial_metric_facts(rows, CONTEXT, CUTOFF))
    assert facts["fee_income_mix"].value == pytest.approx(0.15)
    assert facts["other_income_mix"].value == pytest.approx(0.05)

    missing = _by_metric(_financial_metric_facts(rows[:2], CONTEXT, CUTOFF))
    assert missing["fee_income_mix"].value is None
    assert "missing_input" in missing["fee_income_mix"].limitations

    zero = [_row("net_interest_income", 0.0), _row("net_fee_income", 0.0), _row("other_operating_income", 0.0)]
    invalid = _by_metric(_financial_metric_facts(zero, CONTEXT, CUTOFF))
    assert invalid["other_income_mix"].value is None
    assert "invalid_denominator" in invalid["other_income_mix"].limitations


def test_capital_headroom_derived_only_from_regulatory_cet1_requirement() -> None:
    rows = [
        _row("cet1_ratio", 0.183, unit="ratio", fact_category="pillar3"),
        _row("capital_requirement", 0.145, unit="ratio", fact_category="pillar3", capital_measure="cet1"),
    ]
    headroom = _by_metric(_financial_metric_facts(rows, CONTEXT, CUTOFF))["capital_headroom"]
    assert headroom.value == pytest.approx(0.038)
    assert headroom.fact_category == "pillar3"
    assert "src:cet1_ratio" in headroom.source_id and "src:capital_requirement" in headroom.source_id

    for override, reason in (
        ({"capital_measure": "total_capital"}, "requirement_basis_unspecified"),
        ({"fact_category": "ifrs"}, "regulatory_fact_required"),
        ({"unit": "percent"}, "unit_mismatch"),
        ({"end": "2023-12-31", "effective_at": "2023-12-31", "_effective": pd.Timestamp("2023-12-31", tz="UTC")}, "period_mismatch"),
    ):
        changed = [rows[0], {**rows[1], **override}]
        fact = _by_metric(_financial_metric_facts(changed, CONTEXT, CUTOFF))["capital_headroom"]
        assert fact.value is None and reason in fact.limitations, override

    only_ratio = _by_metric(_financial_metric_facts(rows[:1], CONTEXT, CUTOFF))["capital_headroom"]
    assert only_ratio.value is None and "missing_input" in only_ratio.limitations


def test_revised_disclosure_supersedes_and_conflicting_period_is_not_mixed() -> None:
    old = _row("net_fee_income", 100.0)
    revised = {**old, "value": 160.0, "_known": pd.Timestamp("2025-02-20", tz="UTC")}
    rows = [old, revised, _row("net_interest_income", 800.0), _row("other_operating_income", 40.0)]
    facts = _by_metric(_financial_metric_facts(rows, CONTEXT, CUTOFF, target_period="2024-12-31"))
    assert facts["fee_income_mix"].value == pytest.approx(160.0 / 1000.0)

    stale = [_row("net_fee_income", 100.0, end="2023-12-31"), *rows[2:]]
    mixed = _by_metric(_financial_metric_facts(stale, CONTEXT, CUTOFF, target_period="2024-12-31"))
    assert mixed["fee_income_mix"].value is None
    assert "period_mismatch" in mixed["fee_income_mix"].limitations


def test_acceptance_report_lists_available_unavailable_sources_and_inapplicable_ratios() -> None:
    context = _context("bank")
    registry = AdapterRegistry([financial_adapter_definition()])

    def evidence(metric: str, value: float | None, category: str, source: str) -> FinancialMetricEvidence:
        return FinancialMetricEvidence(
            metric=metric, value=value, unit="ratio", period="FY2024", reporting_standard="IFRS", jurisdiction="NO",
            business_model="bank", source_id=source, source_authority=SourceAuthority.OFFICIAL,
            as_of="2024-12-31T00:00:00Z", known_at="2025-02-15T00:00:00Z", fact_category=category, source=f"https://example.test/{source}",
        )

    projection = build_financial_institution_projection(
        context,
        (
            evidence("cet1_ratio", 0.183, "pillar3", "pillar3-report"),
            evidence("liquidity_coverage_ratio", None, "pillar3", "pillar3-report"),
            evidence("roic", 0.1, "ifrs", "annual-report"),
        ),
        registry=registry,
        decision_time=DECISION,
        shocks={},
    )
    report = bank_metric_acceptance_report(projection)
    assert report["available"]["cet1_ratio"]["source"] == "https://example.test/pillar3-report"
    assert report["available"]["cet1_ratio"]["fact_category"] == "pillar3"
    assert "missing_value" in report["unavailable"]["liquidity_coverage_ratio"]
    assert report["unavailable"]["net_stable_funding_ratio"] == "missing"
    assert "roic" in report["industrial_inapplicable"] and "roic" not in report["available"]
    assert report["execution_allowed"] is False

    tampered = {**projection.__dict__, "business_model": "insurer"}
    with pytest.raises(FinancialAdapterError):
        bank_metric_acceptance_report(tampered)
