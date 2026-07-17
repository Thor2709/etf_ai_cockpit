from __future__ import annotations

import pandas as pd

from etf_cockpit.data.stock_research import (
    balance_sheet_analysis,
    build_stock_research_report,
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


def test_combined_report_keeps_three_sections_and_provenance_boundary() -> None:
    report = build_stock_research_report(_statements(), instrument_id="ACME", market_inputs={"market_cap": 300.0}, assumptions={})

    assert set(report) >= {"profitability", "balance_sheet", "valuation", "execution_allowed", "source_lineage"}
    assert report["execution_allowed"] is False
    assert report["source_lineage"]["statement_view"] == "latest_restated"
