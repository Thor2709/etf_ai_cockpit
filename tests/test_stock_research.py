from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages import stock_research as stock_research_page
from etf_cockpit.app.components import valuation_lab
from etf_cockpit.application import ui_facade, valuation_views
from etf_cockpit.data import stock_research as stock_research_data
from etf_cockpit.data.stock_research import (
    balance_sheet_analysis,
    build_stock_research_report,
    capital_efficiency_analysis,
    growth_analysis,
    load_optional_research_import,
    profitability_analysis,
    valuation_analysis,
)


def _statements() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = {
        2024: {"revenue": 100.0, "gross_profit": 35.0, "operating_income": 18.0, "net_income": 12.0, "assets": 120.0, "equity": 55.0, "debt": 35.0, "cash": 8.0, "cash_from_operations": 16.0, "current_assets": 45.0, "current_liabilities": 30.0, "receivables": 12.0, "interest_expense": 3.0, "exceptional_items": 1.0, "shares_outstanding": 10.0, "free_cash_flow": 14.0},
        2025: {"revenue": 110.0, "gross_profit": 40.0, "operating_income": 22.0, "net_income": 15.0, "assets": 125.0, "equity": 60.0, "debt": 32.0, "cash": 10.0, "cash_from_operations": 20.0, "current_assets": 50.0, "current_liabilities": 28.0, "receivables": 13.0, "interest_expense": 2.5, "exceptional_items": 0.5, "shares_outstanding": 10.0, "free_cash_flow": 18.0},
        2026: {"revenue": 120.0, "gross_profit": 48.0, "operating_income": 27.0, "net_income": 20.0, "assets": 130.0, "equity": 68.0, "debt": 30.0, "cash": 12.0, "cash_from_operations": 25.0, "current_assets": 56.0, "current_liabilities": 25.0, "receivables": 14.0, "interest_expense": 2.0, "exceptional_items": 0.2, "shares_outstanding": 10.0, "free_cash_flow": 23.0},
    }
    for year, metrics in values.items():
        for metric, value in metrics.items():
            rows.append(
                {
                    "instrument_id": "ACME",
                    "canonical_metric": metric,
                    "value": value,
                    "period_type": "annual",
                    "period_key": f"FY{year}",
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "source_id": f"filing-{year}",
                    "filed": f"{year + 1}-02-15",
                    "restatement_kind": "reported",
                }
            )
    return pd.DataFrame(rows)


def test_profitability_formulas_history_and_peer_percentiles_are_explicit() -> None:
    frame = _statements()
    peers = pd.DataFrame({"instrument_id": ["PEER-1", "PEER-2", "PEER-1", "PEER-2"], "canonical_metric": ["gross_profit", "gross_profit", "revenue", "revenue"], "value": [30.0, 60.0, 100.0, 100.0], "period_key": ["FY2026"] * 4, "period_end": ["2026-12-31"] * 4, "period_type": ["annual"] * 4})

    result = profitability_analysis(frame, instrument_id="ACME", peer_frame=peers)

    assert result["metrics"]["gross_margin"]["value"] == 0.4
    assert result["metrics"]["operating_margin"]["value"] == 0.225
    assert result["metrics"]["roa"]["value"] == 20.0 / 130.0
    assert result["metrics"]["cash_conversion"]["value"] == 1.25
    assert result["history"]["gross_margin"] == [0.35, 40.0 / 110.0, 0.4]
    assert 0.0 <= result["peer_percentiles"]["gross_margin"] <= 100.0
    assert result["metrics"]["gross_margin"]["formula"] == "gross_profit / revenue"
    assert result["execution_allowed"] is False


def test_profitability_distinguishes_missing_negative_and_inapplicable() -> None:
    frame = _statements()
    frame = frame[~frame["canonical_metric"].isin(["exceptional_items", "equity"])]
    frame.loc[frame["canonical_metric"].eq("net_income"), "value"] = -2.0

    result = profitability_analysis(frame, instrument_id="ACME", sector="bank")

    assert result["metrics"]["exceptional_item_dependence"]["status"] == "missing"
    assert result["metrics"]["net_margin"]["status"] == "negative"
    assert result["metrics"]["roic"]["status"] == "not_applicable"


def test_capital_efficiency_formulas_require_history_and_stable_denominators() -> None:
    result = capital_efficiency_analysis(_statements(), instrument_id="ACME", tax_rate=0.25, cost_of_capital=0.10)
    reported = result["reported"]

    assert reported["metrics"]["roic"]["value"] == 20.25 / 86.0
    assert reported["metrics"]["incremental_roic"]["value"] == 3.75 / 4.0
    assert reported["metrics"]["reinvestment_rate"]["value"] == 4.0 / 20.25
    assert reported["metrics"]["sales_to_capital"]["value"] == 120.0 / 86.0
    assert reported["metrics"]["asset_turns"]["value"] == 120.0 / 130.0
    assert reported["metrics"]["economic_profit_spread"]["value"] == 20.25 / 86.0 - 0.10
    assert len(reported["history"]) == 3
    assert reported["metrics"]["incremental_roic"]["minimum_periods"] == 3
    assert result["execution_allowed"] is False


def test_incremental_roic_rejects_an_immaterial_invested_capital_change() -> None:
    frame = _statements()
    frame.loc[(frame["canonical_metric"] == "equity") & (frame["fiscal_year"] == 2026), "value"] = 64.0

    result = capital_efficiency_analysis(frame, instrument_id="ACME", tax_rate=0.25)
    incremental = result["reported"]["metrics"]["incremental_roic"]

    assert incremental["value"] is None
    assert incremental["status"] == "unstable_denominator"
    assert "1%" in incremental["limitation"]


def test_intangible_adjustment_is_separate_transparent_and_exportable() -> None:
    frame = _statements()
    additions = []
    for year, research, advertising in ((2024, 10.0, 4.0), (2025, 12.0, 5.0), (2026, 14.0, 6.0)):
        template = frame[frame["fiscal_year"] == year].iloc[0].to_dict()
        for metric, value in (("research_and_development", research), ("advertising_expense", advertising)):
            additions.append({**template, "canonical_metric": metric, "value": value})
    frame = pd.concat([frame, pd.DataFrame(additions)], ignore_index=True)

    result = capital_efficiency_analysis(
        frame,
        instrument_id="ACME",
        tax_rate=0.25,
        intangible_assumptions={"enabled": True, "research_years": 3, "advertising_years": 2, "research_capitalisation_rate": 1.0, "advertising_capitalisation_rate": 0.5},
    )

    assert result["reported"]["metrics"]["roic"]["value"] == 20.25 / 86.0
    assert result["adjusted"]["status"] == "available"
    assert result["adjusted"]["latest_bridge"]["intangible_asset"] > 0
    assert result["adjusted"]["latest_bridge"]["adjusted_operating_income"] > 27.0
    assert result["adjusted"]["assumptions"]["research_years"] == 3
    assert len(result["assumption_sensitivity"]) >= 3
    assert all(item["execution_allowed"] is False for item in result["assumption_sensitivity"])


def test_intangible_adjustment_rejects_invalid_assumptions_and_false_text_stays_disabled() -> None:
    disabled = capital_efficiency_analysis(_statements(), instrument_id="ACME", tax_rate=0.25, intangible_assumptions={"enabled": "false"})
    assert disabled["adjusted"]["status"] == "disabled"

    invalid = capital_efficiency_analysis(
        _statements(),
        instrument_id="ACME",
        tax_rate=0.25,
        intangible_assumptions={"enabled": True, "research_years": 2.5, "research_capitalisation_rate": 1.2},
    )
    assert invalid["adjusted"]["status"] == "invalid_assumptions"
    assert "whole number" in invalid["adjusted"]["reason"]
    assert "between 0 and 1" in invalid["adjusted"]["reason"]


def test_capital_history_prefers_comparable_annual_periods() -> None:
    frame = _statements()
    quarter = frame[frame["fiscal_year"] == 2026].copy()
    quarter["period_type"] = "quarterly"
    quarter["period_key"] = "Q3-2026"
    quarter["period_end"] = "2026-09-30"
    quarter["end"] = "2026-09-30"
    quarter["value"] = quarter["value"] * 10

    result = capital_efficiency_analysis(pd.concat([frame, quarter], ignore_index=True), instrument_id="ACME", tax_rate=0.25)

    assert len(result["reported"]["history"]) == 3
    assert result["reported"]["history"][-1]["period_end"] == "2026-12-31"
    assert result["calculation_inputs"]["tax_rate_basis"] == "explicit_assumption"


def test_business_quality_proxies_require_disclosed_source_evidence() -> None:
    frame = _statements()
    template = frame[frame["fiscal_year"] == 2026].iloc[0].to_dict()
    disclosed = pd.DataFrame([
        {**template, "canonical_metric": "recurring_revenue", "value": 72.0},
        {**template, "canonical_metric": "customer_concentration", "value": 0.28},
    ])
    result = capital_efficiency_analysis(pd.concat([frame, disclosed], ignore_index=True), instrument_id="ACME", tax_rate=0.25)
    proxies = result["business_quality_proxies"]

    assert proxies["recurring_revenue_share"]["value"] == 0.6
    assert proxies["recurring_revenue_share"]["source_ids"] == ("filing-2026",)
    assert proxies["customer_concentration"]["value"] == 0.28
    assert proxies["supplier_concentration"]["status"] == "unavailable"
    assert proxies["capital_return_persistence"]["coverage"]["observed_periods"] == 3
    assert result["proxy_authority"] == "descriptive_only"


def test_capital_efficiency_is_inapplicable_to_financials_and_peer_context_is_descriptive() -> None:
    financial = capital_efficiency_analysis(_statements(), instrument_id="ACME", sector="bank", tax_rate=0.25)
    assert financial["reported"]["metrics"]["roic"]["status"] == "not_applicable"
    assert financial["adjusted"]["status"] == "disabled"

    peers = pd.concat([_statements().assign(instrument_id="PEER-1"), _statements().assign(instrument_id="PEER-2", value=lambda frame: frame["value"] * 1.2)], ignore_index=True)
    industrial = capital_efficiency_analysis(_statements(), instrument_id="ACME", peer_frame=peers, tax_rate=0.25)
    assert industrial["sector_relative"]["status"] == "available"
    assert industrial["sector_relative"]["peer_count"] == 2
    assert industrial["sector_relative"]["authority"] == "descriptive_only"


def test_balance_sheet_formulas_and_stress_fail_closed_without_commitment_data() -> None:
    result = balance_sheet_analysis(_statements(), instrument_id="ACME", sector="industrial")

    assert result["metrics"]["net_debt"]["value"] == 18.0
    assert result["metrics"]["current_ratio"]["value"] == 56.0 / 25.0
    assert result["metrics"]["quick_ratio"]["value"] == (12.0 + 14.0) / 25.0
    assert result["metrics"]["interest_coverage"]["value"] == 13.5
    assert result["stress_scenarios"]["revenue_down_20"]["status"] == "available"
    assert result["maturity_timeline"]["status"] == "missing"
    assert result["execution_allowed"] is False

    financial = balance_sheet_analysis(_statements(), instrument_id="BANK", sector="bank")
    assert financial["metrics"]["altman_like_distress"]["status"] == "not_applicable"


def test_valuation_scenarios_reconcile_and_are_monotonic() -> None:
    market = {
        "market_cap": 300.0,
        "enterprise_value": 318.0,
        "share_price": 30.0,
        "dividend_per_share": 0.6,
        "currency": "EUR",
    }
    assumptions = {
        "forecast_years": 5,
        "discount_rate": 0.10,
        "terminal_growth": 0.02,
        "scenarios": {
            "bear": {"growth": 0.01, "margin": 0.18},
            "base": {"growth": 0.05, "margin": 0.225},
            "bull": {"growth": 0.08, "margin": 0.27},
        },
    }

    result = valuation_analysis(_statements(), instrument_id="ACME", market_inputs=market, assumptions=assumptions)

    assert result["relative_metrics"]["ev_to_sales"]["value"] == 318.0 / 120.0
    scenarios = result["intrinsic_value"]["scenarios"]
    assert scenarios["bull"]["per_share"] > scenarios["base"]["per_share"] > scenarios["bear"]["per_share"]
    assert result["reverse_dcf"]["status"] == "available"
    assert result["residual_income"]["status"] == "available"
    assert result["intrinsic_value"]["execution_allowed"] is False


def test_valuation_fails_closed_when_cash_flow_inputs_are_unavailable() -> None:
    frame = _statements()
    frame = frame[~frame["canonical_metric"].isin(["free_cash_flow", "equity", "net_income"])]
    result = valuation_analysis(frame, instrument_id="ACME", market_inputs={"market_cap": 100.0}, assumptions={})

    assert result["intrinsic_value"]["status"] == "unavailable"
    assert result["intrinsic_value"]["confidence"] == "low"
    assert result["relative_metrics"]["price_to_earnings"]["status"] == "missing"


def test_valuation_bank_routing_uses_residual_income_and_suppresses_ev_multiples() -> None:
    frame = _statements()
    template = frame.loc[(frame["canonical_metric"] == "equity") & (frame["fiscal_year"] == 2026)].iloc[0].to_dict()
    template.update({"currency": "EUR", "consolidation_scope": "consolidated"})
    frame = pd.concat(
        [frame, pd.DataFrame([{**template, "canonical_metric": "tangible_book_value", "value": 42.0}])],
        ignore_index=True,
    )
    frame = frame.loc[~frame["canonical_metric"].isin(["equity", "net_income"])].copy()

    report = build_stock_research_report(
        frame,
        instrument_id="ACME",
        sector="bank",
        market_inputs={"market_cap": 300.0, "shares_outstanding": 10.0, "net_debt": 18.0, "reporting_currency": "EUR", "share_count_period_end": "2026-12-31"},
        assumptions={"forecast_years": 5, "cost_of_equity": 0.10, "terminal_growth": 0.02, "sustainable_roe": 0.12},
        financial_projection=SimpleNamespace(
            status="available",
            instrument_id="ACME",
            execution_allowed=False,
            lineage={"decision_time": "2027-02-15T00:00:00Z", "sources": ("filing-2026",)},
            metrics=(
                SimpleNamespace(metric="net_profit_attributable", status="available", value=20.0, unit="currency", period="2026-12-31", reporting_standard="IFRS", jurisdiction="NO", business_model="bank", scope="consolidated", source_id="filing-2026", source_authority="official", as_of="2026-12-31T00:00:00Z", known_at="2027-02-15T00:00:00Z", execution_allowed=False),
                SimpleNamespace(metric="closing_equity", status="available", value=68.0, unit="currency", period="2026-12-31", reporting_standard="IFRS", jurisdiction="NO", business_model="bank", scope="consolidated", source_id="filing-2026", source_authority="official", as_of="2026-12-31T00:00:00Z", known_at="2027-02-15T00:00:00Z", execution_allowed=False),
                SimpleNamespace(metric="tangible_book_value", status="available", value=42.0, unit="currency", period="2026-12-31", reporting_standard="IFRS", jurisdiction="NO", business_model="bank", scope="consolidated", source_id="filing-2026", source_authority="official", as_of="2026-12-31T00:00:00Z", known_at="2027-02-15T00:00:00Z", execution_allowed=False),
            ),
        ),
    )
    result = report["valuation"]

    assert result["bank_route"]["path"] == "ISSUE-0099_fundamental_release"
    assert result["relative_metrics"]["ev_to_ebitda"]["status"] == "not_applicable"
    assert result["relative_metrics"]["ev_to_sales"]["status"] == "not_applicable"
    assert result["relative_metrics"]["price_to_tangible_book"]["status"] == "available"
    assert result["relative_metrics"]["price_to_tangible_book"]["value"] == 300.0 / 42.0
    assert result["intrinsic_value"]["status"] == "not_applicable"
    assert result["reverse_dcf"]["status"] == "not_applicable"
    assert result["residual_income"]["status"] == "available"


def test_valuation_bank_residual_income_rejects_mixed_projection_lineage() -> None:
    def projected_metric(metric: str, value: float, period: str) -> SimpleNamespace:
        return SimpleNamespace(
            metric=metric,
            status="available",
            value=value,
            unit="currency",
            period=period,
            reporting_standard="IFRS",
            jurisdiction="NO",
            business_model="bank",
            scope="consolidated",
            source_id="filing-2026",
            source_authority="official",
            as_of=f"{period}T00:00:00Z",
            known_at="2027-02-15T00:00:00Z",
            execution_allowed=False,
        )

    projection = SimpleNamespace(
        status="available",
        instrument_id="ACME",
        execution_allowed=False,
        lineage={"decision_time": "2027-02-15T00:00:00Z", "sources": ("filing-2026",)},
        metrics=(
            projected_metric("closing_equity", 68.0, "2026-12-31"),
            projected_metric("tangible_book_value", 42.0, "2025-12-31"),
        ),
    )

    result = valuation_analysis(
        _statements(),
        instrument_id="ACME",
        sector="bank",
        market_inputs={"market_cap": 300.0, "shares_outstanding": 10.0},
        assumptions={"forecast_years": 5, "cost_of_equity": 0.10, "terminal_growth": 0.02, "sustainable_rote": 0.12},
        financial_projection=projection,
        as_known_at="2027-02-15T00:00:00Z",
        strict_comparability=True,
    )

    assert result["residual_income"]["status"] == "unavailable"
    assert "mixed period" in result["residual_income"]["reason"]


def test_valuation_reverse_dcf_out_of_bound_target_is_unavailable() -> None:
    result = valuation_analysis(
        _statements(),
        instrument_id="ACME",
        market_inputs={"market_cap": 1e100, "net_debt": 18.0},
        assumptions={"forecast_years": 5, "discount_rate": 0.10, "terminal_growth": 0.02},
    )

    assert result["reverse_dcf"]["status"] == "unavailable"
    assert "outside the bounded growth search" in result["reverse_dcf"]["reason"]


def test_valuation_page_receives_market_inputs_from_snapshot(monkeypatch) -> None:
    context = {
        "statements": _statements().assign(
            available_at="2027-02-16T00:00:00Z",
            currency="EUR",
            consolidation_scope="consolidated",
        ),
        "sector": "industrial",
        "classification": {"sector": "industrial"},
        "classification_status": "available",
        "decision_time": "2028-01-02T00:00:00Z",
        "valuation_market_inputs": {
            "status": "available",
            "valuation_date": "2028-01-02",
            "price_timestamp": "2027-01-01",
            "price_currency": "EUR",
            "reporting_currency": "EUR",
            "market_cap": 300.0,
            "enterprise_value": 318.0,
            "net_debt": 18.0,
            "net_debt_period_end": "2026-12-31",
            "share_count_period_end": "2026-12-31",
            "enterprise_value_adjustments": {"status": "available"},
            "share_price": 30.0,
            "risk_free_reference": {"status": "available", "rate": 0.03},
            "filing_vintage": ["2027-01-01"],
        },
    }
    monkeypatch.setattr(stock_research_page, "load_stock_research_context", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(stock_research_page, "load_optional_research_import", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(stock_research_page, "load_capital_allocation_analysis", lambda *_args, **_kwargs: {})
    original = stock_research_page.build_stock_research_report
    reports = []

    def capture_report(statements, **kwargs):
        report = original(statements, **kwargs)
        reports.append((report, kwargs))
        return report

    monkeypatch.setattr(stock_research_page, "build_stock_research_report", capture_report)
    stock_research_page._fundamentals(
        None,
        SimpleNamespace(
            selected_etf="ACME",
            snapshot=SimpleNamespace(benchmark_reference_decision_time="2028-01-02T00:00:00Z"),
        ),
        "ACME",
        "Statements",
    )

    assert reports[0][1]["market_inputs"]["market_cap"] == 300.0
    assert reports[0][0]["valuation"]["relative_metrics"]["ev_to_sales"]["value"] == 318.0 / 120.0
    summary = valuation_lab._valuation_summary(reports[0][0]["valuation"])
    assert "2.65" in summary.controls[1].content.value
    assert "calculated from underlying facts" in summary.controls[1].content.value


def test_combined_report_keeps_research_sections_and_provenance_boundary() -> None:
    report = build_stock_research_report(_statements(), instrument_id="ACME", market_inputs={"market_cap": 300.0}, assumptions={})

    assert report["schema_version"] == "stock_research.v2"
    assert set(report) >= {"profitability", "capital_efficiency", "balance_sheet", "valuation", "growth", "expectations", "execution_allowed", "source_lineage"}
    assert report["execution_allowed"] is False
    assert report["source_lineage"]["statement_view"] == "latest_restated"


def test_profitability_production_wiring_injects_sector_and_peers(monkeypatch) -> None:
    known_at = "2026-12-31T00:00:00Z"
    decision_time = "2027-01-02T00:00:00Z"
    target = _statements().assign(
        instrument_id="ACME", currency="EUR", consolidation_scope="consolidated", known_at=known_at
    )
    peers = _statements().assign(
        instrument_id="PEER-1",
        value=lambda frame: frame["value"] * 1.2,
        currency="EUR",
        consolidation_scope="consolidated",
        known_at=known_at,
    )
    facts = pd.concat([target, peers], ignore_index=True)
    classification = {
        "status": "available",
        "classification": {
            "instrument_id": "ACME",
            "sector": "industrial",
            "industry": "manufacturing",
            "reporting_currency": "EUR",
            "accounting_standard": "IFRS",
            "effective_at": "2026-12-31T00:00:00Z",
            "decision_time": decision_time,
        },
        "execution_allowed": False,
    }
    peer_projection = {
        "status": "available",
        "instrument_id": "ACME",
        "decision_time": decision_time,
        "cohort": {"members": ["PEER-1"]},
        "execution_allowed": False,
    }
    monkeypatch.setattr(valuation_views, "load_classification_projection", lambda instrument_id: classification)
    monkeypatch.setattr(valuation_views, "load_peer_cohort_projection", lambda instrument_id, decision_time=None: peer_projection)
    monkeypatch.setattr(stock_research_data, "load_stock_research_frame", lambda path, instrument_id=None, as_known_at=None: facts.copy())
    monkeypatch.setattr(stock_research_page, "load_optional_research_import", lambda path, instrument_id=None: pd.DataFrame())

    context = ui_facade.load_stock_research_context("ACME", statements_path=ui_facade.STATEMENT_FACTS_PATH)
    captured = []
    report_builder = stock_research_page.build_stock_research_report

    def capture_report(*args, **kwargs):
        report = report_builder(*args, **kwargs)
        captured.append(report)
        return report

    monkeypatch.setattr(ui_facade, "load_stock_research_context", lambda instrument_id, statements_path=None, **_kwargs: context)
    monkeypatch.setattr(stock_research_page, "build_stock_research_report", capture_report)
    monkeypatch.setattr(stock_research_page, "load_capital_allocation_analysis", lambda *_args, **_kwargs: {})
    stock_research_page._fundamentals(None, SimpleNamespace(selected_etf="ACME"), "ACME", "Statements")

    result = captured[0]["profitability"]
    assert result["sector"] == "industrial"
    assert result["classification_context"]["reporting_currency"] == "EUR"
    assert result["peer_context"]["cohort"]["members"] == ["PEER-1"]
    assert result["peer_comparisons"]["gross_margin"]["status"] == "available"
    assert 0.0 <= result["peer_percentiles"]["gross_margin"] <= 100.0
    assert result["history_comparability"]["gross_margin"]["status"] == "available"
    assert result["history"]["roa"]
    assert captured[0]["growth"]["series"]["aggregate"]["revenue"]["comparability"]["status"] == "available"


def test_profitability_bank_delegation_suppresses_industrial_metrics(monkeypatch) -> None:
    classification = {
        "status": "available",
        "classification": {"sector": "banking", "business_model_tags": ["deposit_taking"], "effective_at": "2026-12-31T00:00:00Z", "decision_time": "2027-01-01T00:00:00Z"},
    }
    peer_projection = {"status": "unavailable", "reason_code": "peer_cohort_evidence_unavailable"}
    facts = _statements().assign(instrument_id="MING")
    adapter_calls = []
    adapter_result = {"status": "available", "business_model": "bank", "metrics": {}, "execution_allowed": False}
    monkeypatch.setattr(valuation_views, "load_classification_projection", lambda instrument_id: classification)
    monkeypatch.setattr(valuation_views, "load_peer_cohort_projection", lambda instrument_id, decision_time=None: peer_projection)
    monkeypatch.setattr(stock_research_data, "load_stock_research_frame", lambda path, instrument_id=None, as_known_at=None: facts.copy())
    monkeypatch.setattr(valuation_views, "load_financial_institution_projection", lambda instrument_id, **kwargs: adapter_calls.append((instrument_id, kwargs)) or adapter_result)

    context = ui_facade.load_stock_research_context("MING", statements_path=ui_facade.STATEMENT_FACTS_PATH)
    report = build_stock_research_report(
        context["statements"],
        instrument_id="MING",
        sector=context["sector"],
        classification_context=context["classification"],
        financial_projection=context["financial_projection"],
    )
    profitability = report["profitability"]["metrics"]
    balance = report["balance_sheet"]["metrics"]

    assert adapter_calls and adapter_calls[0][0] == "MING"
    assert report["financial_institutions"]["business_model"] == "bank"
    for metric in ("gross_margin", "roic"):
        assert profitability[metric]["status"] == "not_applicable"
    for metric in ("current_ratio", "quick_ratio", "altman_like_distress"):
        assert balance[metric]["status"] == "not_applicable"

    unclassified = build_stock_research_report(_statements(), instrument_id="ACME")
    assert unclassified["profitability"]["metrics"]["gross_margin"]["status"] == "unavailable"
    assert unclassified["profitability"]["metrics"]["gross_margin"]["value"] is None
    assert unclassified["balance_sheet"]["metrics"]["current_ratio"]["status"] == "unavailable"


def test_profitability_rejects_mixed_currency_peer_frame() -> None:
    target = _statements().assign(currency="USD", consolidation_scope="consolidated")
    peers = _statements().assign(instrument_id="PEER-1", currency="EUR", consolidation_scope="consolidated")

    result = profitability_analysis(target, instrument_id="ACME", sector="industrial", peer_frame=peers, strict_comparability=True)

    assert result["peer_comparisons"]["gross_margin"]["status"] == "unavailable"
    assert result["peer_comparisons"]["gross_margin"]["reason"] == "peer_currency_mismatch"
    assert "gross_margin" not in result["peer_percentiles"]
    mixed_scope = peers.assign(currency="USD", consolidation_scope="unconsolidated")
    scope_result = profitability_analysis(target, instrument_id="ACME", sector="industrial", peer_frame=mixed_scope, strict_comparability=True)
    assert scope_result["peer_comparisons"]["gross_margin"]["reason"] == "peer_accounting_scope_mismatch"


def test_balance_sheet_separates_leases_from_contractual_debt() -> None:
    frame = _statements()
    template = frame[frame["canonical_metric"].eq("debt") & frame["fiscal_year"].eq(2026)].iloc[0].to_dict()
    additions = pd.DataFrame([
        {**template, "canonical_metric": "contractual_debt", "value": 27.0, "source_id": "filing-2026-contractual-debt"},
        {**template, "canonical_metric": "lease_liabilities", "value": 3.0, "source_id": "filing-2026-leases"},
        {**template, "canonical_metric": "restricted_cash", "value": 2.0, "source_id": "filing-2026-restricted-cash"},
    ])
    result = balance_sheet_analysis(pd.concat([frame, additions], ignore_index=True), instrument_id="ACME")
    breakdown = result["net_debt_breakdown"]

    assert breakdown["contractual_debt"]["value"] == 27.0
    assert breakdown["lease_liabilities"]["value"] == 3.0
    assert breakdown["lease_adjustment"]["included_in_net_debt"] is False
    assert breakdown["restricted_cash"]["value"] == 2.0

    absent = balance_sheet_analysis(frame, instrument_id="ACME")["net_debt_breakdown"]
    assert absent["lease_liabilities"]["status"] == "unavailable"
    assert any("Lease liabilities are unavailable" in item for item in absent["coverage_limitations"])


def test_balance_sheet_missing_maturities_sets_coverage_limitation() -> None:
    result = balance_sheet_analysis(_statements(), instrument_id="ACME")
    maturity = result["maturity_timeline"]

    assert maturity["status"] == "missing"
    assert maturity["buckets"] == {}
    assert "not treated as zero" in maturity["limitation"]
    assert maturity["coverage_limitations"]
    assert result["coverage_limitations"]
def test_stock_research_page_uses_snapshot_decision_time(monkeypatch) -> None:
    decision_time = "2026-12-31T00:00:00Z"
    state = SimpleNamespace(
        selected_etf="ACME",
        snapshot=SimpleNamespace(
            config=SimpleNamespace(ui=SimpleNamespace(default_etf="ACME")),
            benchmark_reference_decision_time=decision_time,
        ),
    )
    seen_decision_times: list[str | None] = []

    monkeypatch.setattr(
        stock_research_page,
        "load_stock_research_context",
        lambda *_args, **kwargs: {"statements": _statements(), "decision_time": kwargs.get("decision_time")},
    )
    monkeypatch.setattr(stock_research_page, "load_optional_research_import", lambda *_args, **_kwargs: pd.DataFrame())

    def load_capital_allocation(_statements, **kwargs):
        seen_decision_times.append(kwargs["decision_time"])
        return {}

    monkeypatch.setattr(stock_research_page, "load_capital_allocation_analysis", load_capital_allocation)

    page = stock_research_page._fundamentals(None, state, "ACME", "Statements")

    assert page is not None
    assert seen_decision_times == [decision_time]


def test_growth_keeps_aggregate_and_per_share_series_period_aligned() -> None:
    result = growth_analysis(_statements(), instrument_id="ACME")

    revenue = result["series"]["aggregate"]["revenue"]
    eps = result["series"]["per_share"]["earnings_per_share"]
    fcf_per_share = result["series"]["per_share"]["free_cash_flow_per_share"]

    assert revenue["basis"] == "aggregate"
    assert revenue["latest_growth"]["value"] == 120.0 / 110.0 - 1.0
    assert eps["basis"] == "per_share"
    assert eps["history"][-1]["value"] == 2.0
    assert eps["latest_growth"]["value"] == 2.0 / 1.5 - 1.0
    assert fcf_per_share["history"][-1]["value"] == 2.3
    assert fcf_per_share["latest_growth"]["value"] == 2.3 / 1.8 - 1.0
    assert result["execution_allowed"] is False


def test_growth_marks_zero_and_negative_bases_without_inventing_percentages() -> None:
    frame = _statements()
    frame.loc[(frame["canonical_metric"] == "revenue") & (frame["fiscal_year"] == 2025), "value"] = 0.0
    result = growth_analysis(frame, instrument_id="ACME")
    latest = result["series"]["aggregate"]["revenue"]["latest_growth"]

    assert latest["status"] == "base_effect"
    assert latest["base_effect"] == "prior_zero"
    assert latest["value"] is None


def test_growth_uses_latest_restatement_for_the_same_period() -> None:
    frame = _statements()
    amended = frame[(frame["canonical_metric"] == "revenue") & (frame["fiscal_year"] == 2025)].copy()
    amended.loc[:, "value"] = 130.0
    amended.loc[:, "filed"] = "2026-02-15"
    amended.loc[:, "source_id"] = "filing-2025-amended"
    amended.loc[:, "restatement_kind"] = "amended"

    result = growth_analysis(pd.concat([frame, amended], ignore_index=True), instrument_id="ACME")

    latest = result["series"]["aggregate"]["revenue"]["latest_growth"]
    assert latest["base_period_key"].endswith(":FY")
    assert latest["value"] == 120.0 / 130.0 - 1.0
    assert "filing-2025-amended" in latest["source_ids"]


def test_growth_does_not_bridge_an_unavailable_intermediate_period() -> None:
    frame = _statements()
    frame = frame[~((frame["canonical_metric"] == "revenue") & (frame["fiscal_year"] == 2025))]

    result = growth_analysis(frame, instrument_id="ACME")
    revenue = result["series"]["aggregate"]["revenue"]

    latest = revenue["latest_growth"]
    assert latest["period_key"].endswith("2026-12-31:FY")
    assert latest["status"] == "missing"
    assert latest["base_effect"] == "missing_period"
    assert latest["value"] is None


def test_growth_marks_a_negative_current_value_as_a_base_effect() -> None:
    frame = _statements()
    frame.loc[(frame["canonical_metric"] == "revenue") & (frame["fiscal_year"] == 2026), "value"] = -10.0

    latest = growth_analysis(frame, instrument_id="ACME")["series"]["aggregate"]["revenue"]["latest_growth"]

    assert latest["status"] == "available"
    assert latest["base_effect"] == "current_negative"
    assert latest["value"] == -10.0 / 110.0 - 1.0


def test_growth_keeps_organic_and_acquisition_evidence_separate() -> None:
    frame = _statements()
    organic_rows = frame[frame["canonical_metric"] == "revenue"].copy()
    organic_rows.loc[:, "canonical_metric"] = "organic_revenue"
    organic_rows.loc[:, "value"] = organic_rows["value"] - 5.0
    organic_rows.loc[:, "acquisition_flag"] = [False, True, True]
    acquisition_rows = organic_rows.copy()
    acquisition_rows.loc[:, "canonical_metric"] = "acquisition_revenue"
    acquisition_rows.loc[:, "value"] = 5.0

    result = growth_analysis(pd.concat([frame, organic_rows, acquisition_rows], ignore_index=True), instrument_id="ACME")
    organic = result["organic_inorganic"]

    assert organic["status"] == "available"
    assert organic["organic_growth"]["latest_growth"]["value"] == 115.0 / 105.0 - 1.0
    assert organic["inorganic_growth"]["latest_growth"]["value"] == 0.0
    assert organic["acquisition_flags"]


def test_expectations_require_point_in_time_authorised_evidence_and_reject_current_fields() -> None:
    report = build_stock_research_report(
        _statements(),
        instrument_id="ACME",
        expectation_evidence=[{"metric": "revenue", "period_key": "FY2026", "value": 125.0}],
        guidance_evidence=[{"metric": "revenue", "period_key": "FY2026", "value": 125.0, "review_status": "draft"}],
    )

    assert report["expectations"]["consensus"]["status"] == "unavailable"
    assert report["expectations"]["guidance"]["status"] == "unavailable"
    assert report["expectations"]["consensus"]["rejected_records"]
    assert report["expectations"]["guidance"]["rejected_records"]


def test_expectations_are_cutoff_safe_and_record_revision_surprise_and_staleness() -> None:
    statements = _statements().assign(available_at="2026-01-15T00:00:00Z")
    evidence = [
        {"metric": "revenue", "period_key": "FY2026", "value": 118.0, "available_at": "2026-01-20", "source_id": "user-estimate-1", "source_authority": "user_owned", "source_checksum": "a" * 64},
        {"metric": "revenue", "period_key": "FY2026", "value": 121.0, "available_at": "2026-01-30", "source_id": "user-estimate-1", "source_authority": "user_owned", "source_checksum": "a" * 64},
        {"metric": "revenue", "period_key": "FY2026", "value": 999.0, "available_at": "2026-03-01", "source_id": "user-estimate-future", "source_authority": "user_owned", "source_checksum": "a" * 64},
        {"metric": "revenue", "period_key": "FY2026", "value": 999.0, "available_at": "2026-01-25", "source_id": "yahoo-current", "source_authority": "user_owned", "source_checksum": "a" * 64},
    ]

    report = build_stock_research_report(statements, instrument_id="ACME", expectation_evidence=evidence, as_known_at="2026-02-01")
    item = report["expectations"]["consensus"]["metrics"]["revenue"]["FY2026"]

    assert item["latest_value"] == 121.0
    assert item["revision"]["value"] == 3.0
    assert item["dispersion"]["status"] == "not_available"
    assert item["surprise"]["value"] == -1.0
    assert item["staleness"]["days"] == 2
    assert any("after_as_known_cutoff" in reason for reason in report["expectations"]["consensus"]["rejected_records"])
    assert any("current_or_restricted_provider_rejected" in reason for reason in report["expectations"]["consensus"]["rejected_records"])


def test_guidance_requires_source_and_review_metadata() -> None:
    report = build_stock_research_report(
        _statements(),
        instrument_id="ACME",
        guidance_evidence=[
            {"metric": "revenue", "period_key": "FY2026", "lower": 118.0, "upper": 123.0, "guidance_text": "Official range", "available_at": "2026-02-01", "source_id": "issuer-release-1", "source_authority": "official", "source_checksum": "b" * 64, "review_status": "structured"},
        ],
    )

    item = report["expectations"]["guidance"]["items"][0]
    assert report["expectations"]["guidance"]["status"] == "available"
    assert item["lower"] == 118.0
    assert item["upper"] == 123.0
    assert item["review_status"] == "structured"
    assert item["source_id"] == "issuer-release-1"


def test_expectations_reject_malformed_dates_and_forged_current_analyst_authority() -> None:
    report = build_stock_research_report(
        _statements(),
        instrument_id="ACME",
        expectation_evidence=[
            {"metric": "revenue", "period_key": "FY2026", "value": 121.0, "available_at": pd.NaT, "source_id": "import-1", "source_authority": "user_owned", "source_checksum": "a" * 64},
            {"metric": "revenue", "period_key": "FY2026", "value": 121.0, "available_at": "2026-01-30", "source_id": "forged-analyst", "source_authority": "official", "source_kind": "current_analyst", "source_checksum": "b" * 64},
        ],
    )

    assert report["expectations"]["consensus"]["status"] == "unavailable"
    rejected = report["expectations"]["consensus"]["rejected_records"]
    assert any("missing_or_unlicensed_provenance" in reason for reason in rejected)
    assert any("current_or_restricted_provider_rejected" in reason for reason in rejected)


def test_optional_consensus_import_is_instrument_scoped_and_file_checksummed(tmp_path: Path) -> None:
    path = tmp_path / "consensus.csv"
    pd.DataFrame([
        {"instrument_id": "ACME", "metric": "revenue", "period_key": "FY2026", "value": 121.0, "available_at": "2026-01-30", "source_id": "licensed-import", "source_authority": "broker_licensed"},
        {"instrument_id": "OTHER", "metric": "revenue", "period_key": "FY2026", "value": 999.0, "available_at": "2026-01-30", "source_id": "other-import", "source_authority": "broker_licensed"},
    ]).to_csv(path, index=False)

    evidence = load_optional_research_import(path, instrument_id="ACME")
    report = build_stock_research_report(_statements(), instrument_id="ACME", expectation_evidence=evidence, as_known_at="2026-02-01")

    assert evidence["instrument_id"].tolist() == ["ACME"]
    assert len(evidence.loc[0, "source_checksum"]) == 64
    item = report["expectations"]["consensus"]["metrics"]["revenue"]["FY2026"]
    assert item["latest_value"] == 121.0
    assert item["license_statuses"] == ["broker_licensed"]


def test_shared_optional_import_without_instrument_identity_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "guidance.csv"
    pd.DataFrame([{"metric": "revenue", "period_key": "FY2026", "lower": 118.0, "upper": 123.0, "available_at": "2026-02-01", "source_id": "issuer-release", "source_authority": "official", "review_status": "structured"}]).to_csv(path, index=False)

    evidence = load_optional_research_import(path, instrument_id="ACME")
    report = build_stock_research_report(_statements(), instrument_id="ACME", guidance_evidence=evidence)

    assert evidence.empty
    assert evidence.attrs["import_status"] == "rejected"
    assert report["expectations"]["guidance"]["rejected_records"] == ["import:missing_instrument_id"]


def test_consensus_and_guidance_authority_classes_do_not_cross() -> None:
    common = {"metric": "revenue", "period_key": "FY2026", "value": 121.0, "available_at": "2026-01-30", "source_id": "evidence", "source_checksum": "a" * 64}
    report = build_stock_research_report(_statements(), instrument_id="ACME", expectation_evidence=[{**common, "source_authority": "official"}], guidance_evidence=[{**common, "source_authority": "user_owned", "review_status": "human_reviewed"}])

    assert report["expectations"]["consensus"]["status"] == "unavailable"
    assert report["expectations"]["guidance"]["status"] == "unavailable"
    assert all("missing_or_unlicensed_provenance" in reason for reason in report["expectations"]["consensus"]["rejected_records"])
    assert all("missing_or_unlicensed_provenance" in reason for reason in report["expectations"]["guidance"]["rejected_records"])


def test_optional_evidence_rejects_missing_periods_and_incoherent_guidance_ranges() -> None:
    consensus = {"metric": "revenue", "value": 121.0, "available_at": "2026-01-30", "source_id": "licensed-import", "source_authority": "user_owned", "source_checksum": "a" * 64}
    guidance = {"metric": "revenue", "period_key": "FY2026", "lower": 125.0, "upper": 120.0, "available_at": "2026-01-30", "source_id": "issuer-release", "source_authority": "official", "source_checksum": "b" * 64, "review_status": "structured"}

    report = build_stock_research_report(_statements(), instrument_id="ACME", expectation_evidence=[consensus], guidance_evidence=[guidance])

    assert report["expectations"]["consensus"]["rejected_records"] == ["row_0:missing_metric_period_or_value"]
    assert report["expectations"]["guidance"]["rejected_records"] == ["row_0:invalid_guidance_range"]


def test_optional_evidence_rejects_missing_guidance_period_and_unlicensed_consensus() -> None:
    common = {"metric": "revenue", "value": 121.0, "available_at": "2026-01-30", "source_id": "evidence", "source_checksum": "a" * 64}
    report = build_stock_research_report(
        _statements(),
        instrument_id="ACME",
        expectation_evidence=[{**common, "period_key": "FY2026", "source_authority": "user_owned", "license_status": "unlicensed"}],
        guidance_evidence=[{**common, "source_authority": "official", "review_status": "structured"}],
    )

    assert report["expectations"]["consensus"]["rejected_records"] == ["row_0:missing_or_unlicensed_provenance"]
    assert report["expectations"]["guidance"]["rejected_records"] == ["row_0:missing_guidance_period"]


def test_optional_evidence_handles_pandas_missing_scalars_without_truthiness_errors() -> None:
    evidence = pd.DataFrame([
        {
            "metric": "revenue",
            "period_key": "FY2026",
            "value": 121.0,
            "available_at": pd.NA,
            "source_id": pd.NA,
            "source_authority": "user_owned",
            "source_checksum": "a" * 64,
        }
    ])

    report = build_stock_research_report(_statements(), instrument_id="ACME", expectation_evidence=evidence)

    assert report["expectations"]["consensus"]["rejected_records"] == ["row_0:missing_or_unlicensed_provenance"]
