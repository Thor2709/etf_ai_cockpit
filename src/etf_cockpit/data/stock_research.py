"""Transparent stock research analytics over canonical statement evidence.

The functions in this module deliberately return evidence dictionaries rather
than an action score. Every value carries a formula, period, source coverage
and confidence boundary. Missing inputs remain missing and structurally
inapplicable sectors are not forced through industrial formulas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import math
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import RAW_DIR
from etf_cockpit.data.capital_efficiency import capital_efficiency_analysis
from etf_cockpit.data.statement_normalisation import statement_coverage, statement_view


STOCK_RESEARCH_SCHEMA_VERSION = "stock_research.v2"
STOCK_RESEARCH_IMPORT_DIR = RAW_DIR / "stock_research"
CONSENSUS_IMPORT_PATH = STOCK_RESEARCH_IMPORT_DIR / "consensus.csv"
GUIDANCE_IMPORT_PATH = STOCK_RESEARCH_IMPORT_DIR / "guidance.csv"
_SPECIAL_SECTORS = frozenset({"bank", "banks", "banking", "savings_bank", "savings banks", "deposit_taking", "deposit-taking", "insurance", "insurer", "financial", "financials", "financial_institution", "financial institution", "financial_services", "financial services"})
_METRIC_ALIASES = {
    "lease_liability": "lease_liabilities",
    "operating_lease_liabilities": "lease_liabilities",
    "restricted_cash_and_cash_equivalents": "restricted_cash",
    "diluted_shares": "diluted_shares_outstanding",
}
_CONSENSUS_SOURCE_AUTHORITIES = frozenset(
    {
        "broker licensed",
        "broker_licensed",
        "licensed vendor",
        "licensed_vendor",
        "user supplied",
        "user-supplied",
        "user owned",
        "user_owned",
        "user-owned",
        "broker-licensed",
    }
)
_GUIDANCE_SOURCE_AUTHORITIES = frozenset({"company", "company official", "company_official", "official", "issuer"})
_REVIEWED_GUIDANCE_STATUSES = frozenset({"approved", "human_reviewed", "reviewed", "structured", "verified"})
_REJECTED_LICENCE_MARKERS = frozenset({"denied", "expired", "prohibited", "restricted", "unlicensed", "unknown"})
_GROWTH_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales"),
    "operating_profit": ("operating_profit", "operating_income", "ebit"),
    "free_cash_flow": ("free_cash_flow",),
    "net_income": ("net_income", "net_profit"),
    "shares_outstanding": ("shares_outstanding", "weighted_average_shares"),
    "diluted_shares_outstanding": ("diluted_shares_outstanding", "diluted_shares"),
    "earnings_per_share": ("earnings_per_share", "eps", "basic_eps", "diluted_eps"),
    "organic_revenue": ("organic_revenue", "organic_sales"),
    "acquisition_revenue": ("acquisition_revenue", "inorganic_revenue", "acquired_revenue"),
}


@dataclass(frozen=True)
class MetricEvidence:
    name: str
    value: float | None
    status: str
    formula: str
    period: str
    source_ids: tuple[str, ...]
    confidence: str
    applicability: str = "applicable"
    limitation: str = ""


def profitability_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    peer_frame: pd.DataFrame | None = None,
    classification_context: Mapping[str, object] | None = None,
    peer_context: Mapping[str, object] | None = None,
    strict_comparability: bool = False,
    tax_rate: float | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    peer_frame = _statement_frame(peer_frame, None, as_known_at=as_known_at) if isinstance(peer_frame, pd.DataFrame) else None
    sector = sector or _text((classification_context or {}).get("sector"))
    latest = _latest_values(frame)
    histories = _histories(frame)
    metrics: dict[str, dict[str, object]] = {}
    sector_known = _classification_is_known(sector, classification_context)
    special = sector_known and _is_special_sector(sector, classification_context)
    revenue = latest.get("revenue")
    gross_profit = latest.get("gross_profit")
    operating_income = latest.get("operating_income")
    net_income = latest.get("net_income")
    assets = latest.get("assets")
    equity = latest.get("equity")
    debt = latest.get("debt")
    cash = latest.get("cash")
    cfo = latest.get("cash_from_operations")
    tax = tax_rate if tax_rate is not None else _tax_rate(latest)

    metrics["gross_margin"] = _ratio_metric(
        "gross_margin", gross_profit, revenue, "gross_profit / revenue", frame, "revenue",
        applicability="not_applicable" if special else "applicable",
        limitation="Financial-institution profitability is delegated to the financial-sector adapter." if special else "",
    )
    metrics["operating_margin"] = _ratio_metric("operating_margin", operating_income, revenue, "operating_income / revenue", frame, "revenue")
    metrics["net_margin"] = _ratio_metric("net_margin", net_income, revenue, "net_income / revenue", frame, "revenue")
    metrics["roa"] = _ratio_metric("roa", net_income, assets, "net_income / assets", frame, "assets")
    metrics["roe"] = _ratio_metric("roe", net_income, equity, "net_income / equity", frame, "equity")
    invested_capital = _sum_if_present(equity, debt, -cash if cash is not None else None)
    roic = None if special else (None if operating_income is None or tax is None else operating_income * (1.0 - tax))
    metrics["roic"] = _ratio_metric(
        "roic",
        roic,
        invested_capital,
        "(operating_income * (1 - tax_rate)) / (equity + debt - cash)",
        frame,
        "equity",
        applicability="not_applicable" if special else "applicable",
        limitation="Financial-institution profitability is delegated to the financial-sector adapter." if special else "",
    )
    metrics["cash_conversion"] = _ratio_metric(
        "cash_conversion", cfo, net_income, "cash_from_operations / net_income", frame,
        "cash_from_operations", applicability="not_applicable" if special else "applicable",
        limitation="Industrial cash-conversion analysis is not applicable to financial institutions." if special else "",
        zero_denominator_status="not_applicable",
    )
    accrual_numerator = None if net_income is None or cfo is None else net_income - cfo
    metrics["accrual_ratio"] = _ratio_metric(
        "accrual_ratio", accrual_numerator, assets, "(net_income - cash_from_operations) / assets", frame, "assets",
        applicability="not_applicable" if special else "applicable",
        limitation="Industrial cash-flow accrual analysis is not applicable to financial institutions." if special else "",
    )
    exceptional = latest.get("exceptional_items")
    metrics["exceptional_item_dependence"] = _ratio_metric("exceptional_item_dependence", exceptional, net_income, "exceptional_items / net_income", frame, "exceptional_items", zero_denominator_status="not_applicable")
    if strict_comparability:
        history_specs = {
            "gross_margin": ("gross_profit", "revenue"),
            "operating_margin": ("operating_income", "revenue"),
            "net_margin": ("net_income", "revenue"),
            "roa": ("net_income", "assets"),
            "roe": ("net_income", "equity"),
            "cash_conversion": ("cash_from_operations", "net_income"),
            "accrual_ratio": ("net_income", "cash_from_operations", "assets"),
            "exceptional_item_dependence": ("exceptional_items", "net_income"),
        }
        comparable_history = (
            {name: {"status": "not_applicable", "reason": "financial-institution adapter required", "values": []} for name in history_specs}
            if special
            else {name: _comparable_ratio_history(frame, components) for name, components in history_specs.items()}
        )
        trend_histories = {name: item["values"] for name, item in comparable_history.items()}
    else:
        trend_histories = {
            "gross_margin": _derived_history(histories, "gross_profit", "revenue"),
            "operating_margin": _derived_history(histories, "operating_income", "revenue"),
            "net_margin": _derived_history(histories, "net_income", "revenue"),
        }
        comparable_history = {}
    margins = [] if special else trend_histories.get("gross_margin", [])
    metrics["margin_stability"] = _metric(
        "margin_stability",
        None if len(margins) < 2 else float(pd.Series(margins).std(ddof=0)),
        "population standard deviation of gross_margin history",
        frame,
        status_override="not_applicable" if special else "missing" if len(margins) == 0 else "not_applicable" if len(margins) == 1 else None,
        limitation="Financial-institution profitability is delegated to the financial-sector adapter." if special else "At least two comparable periods are required." if len(margins) < 2 else "",
    )
    if strict_comparability and not special:
        current_specs = {
            "gross_margin": ("gross_profit", "revenue"),
            "operating_margin": ("operating_income", "revenue"),
            "net_margin": ("net_income", "revenue"),
            "roa": ("net_income", "assets"),
            "roe": ("net_income", "equity"),
            "cash_conversion": ("cash_from_operations", "net_income"),
            "accrual_ratio": ("net_income", "cash_from_operations", "assets"),
            "exceptional_item_dependence": ("exceptional_items", "net_income"),
            "roic": ("operating_income", "equity", "debt", "cash", "income_before_tax", "tax_expense"),
        }
        for name, metric_components in current_specs.items():
            comparable_value, reason = _latest_comparable_value(frame, name, metric_components)
            evidence = metrics[name]
            observed_value = _float(evidence.get("value"))
            if comparable_value is None or observed_value is None or not math.isclose(comparable_value, observed_value, rel_tol=1e-9, abs_tol=1e-12):
                evidence["value"] = None
                evidence["status"] = "unavailable"
                evidence["confidence"] = "low"
                evidence["limitation"] = f"Currency, reporting period and accounting scope must align for calculated values; {reason or 'selected inputs do not share a comparable period.'}"
    if strict_comparability and not sector_known:
        limitation = "Classification is unavailable or unresolved; industrial applicability cannot be established."
        for name in ("gross_margin", "roic", "cash_conversion", "accrual_ratio", "margin_stability"):
            _mark_metric_unavailable(metrics[name], limitation)
        for name in ("gross_margin", "cash_conversion", "accrual_ratio"):
            history = comparable_history.get(name)
            if isinstance(history, dict):
                history.update({"status": "unavailable", "reason": "classification_unavailable", "values": []})
                trend_histories[name] = []

    peer_percentiles: dict[str, float] = {}
    peer_comparisons: dict[str, dict[str, object]] = {}
    for name, evidence in metrics.items():
        if evidence.get("value") is None or special:
            continue
        if strict_comparability:
            comparison = _comparable_peer_percentile(name, evidence.get("value"), frame, peer_frame)
            peer_comparisons[name] = comparison
            if comparison.get("status") == "available" and comparison.get("percentile") is not None:
                peer_percentiles[name] = float(comparison["percentile"])
        else:
            percentile = _peer_percentile(name, evidence.get("value"), peer_frame)
            if percentile is not None:
                peer_percentiles[name] = percentile
            peer_comparisons[name] = {
                "status": "available" if percentile is not None else "unavailable",
                "reason": "legacy_peer_frame" if percentile is not None else "peer_evidence_unavailable",
            }
    components = _quality_components(latest, histories)
    if strict_comparability and not special:
        debt_history = _comparable_metric_history(frame, "debt")
        gross_history = comparable_history.get("gross_margin", {})
        gross_values = gross_history.get("values", []) if isinstance(gross_history, Mapping) else []
        components["lower_leverage"] = {
            "value": _trend(debt_history.get("values", []), descending=True),
            "status": "available" if debt_history.get("status") == "available" else "unavailable",
            "comparability": debt_history,
            "execution_allowed": False,
        }
        components["improving_gross_margin"] = {
            "value": _trend(gross_values, descending=False),
            "status": "available" if isinstance(gross_history, Mapping) and gross_history.get("status") == "available" else "unavailable",
            "comparability": gross_history,
            "execution_allowed": False,
        }
    elif special:
        for name in ("lower_leverage", "improving_gross_margin", "positive_cash_from_operations"):
            components[name] = {"value": None, "status": "not_applicable", "execution_allowed": False}
    if strict_comparability and not sector_known:
        for name in ("lower_leverage", "improving_gross_margin", "positive_cash_from_operations"):
            components[name] = {"value": None, "status": "unavailable", "limitation": "Classification is unavailable or unresolved.", "execution_allowed": False}
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "metrics": metrics,
        "history": {name: values for name, values in trend_histories.items()},
        "history_comparability": comparable_history,
        "peer_percentiles": peer_percentiles,
        "peer_comparisons": peer_comparisons,
        "classification_context": dict(classification_context or {}),
        "peer_context": dict(peer_context or {}),
        "statement_context": _statement_context(frame),
        "quality_components": components,
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def balance_sheet_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    classification_context: Mapping[str, object] | None = None,
    strict_comparability: bool = False,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    sector = sector or _text((classification_context or {}).get("sector"))
    latest = _latest_values(frame)
    metrics: dict[str, dict[str, object]] = {}
    debt = latest.get("contractual_debt", latest.get("debt"))
    cash = latest.get("cash")
    equity = latest.get("equity")
    current_assets = latest.get("current_assets")
    current_liabilities = latest.get("current_liabilities")
    receivables = latest.get("receivables")
    operating_income = latest.get("operating_income")
    interest_expense = latest.get("interest_expense")
    sector_known = _classification_is_known(sector, classification_context)
    special = sector_known and _is_special_sector(sector, classification_context)
    industrial_reason = "Industrial-company balance-sheet analysis is delegated to the financial-sector adapter."
    debt_name = "contractual_debt" if "contractual_debt" in latest else "debt"
    metrics["net_debt"] = _metric("net_debt", None if special or debt is None or cash is None else debt - cash, f"reported {debt_name} - reported cash; lease and restricted-cash treatment is separate", frame, status_override="not_applicable" if special else None, limitation=industrial_reason if special else "")
    metrics["debt_to_equity"] = _ratio_metric("debt_to_equity", debt, equity, f"{debt_name} / equity", frame, debt_name, applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "")
    metrics["current_ratio"] = _ratio_metric("current_ratio", current_assets, current_liabilities, "current_assets / current_liabilities", frame, "current_assets", applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "")
    quick_assets = _sum_if_present(cash, receivables)
    metrics["quick_ratio"] = _ratio_metric("quick_ratio", quick_assets, current_liabilities, "(cash + receivables) / current_liabilities", frame, "cash", applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "")
    metrics["working_capital"] = _metric("working_capital", None if special or current_assets is None or current_liabilities is None else current_assets - current_liabilities, "current_assets - current_liabilities", frame, status_override="not_applicable" if special else None, limitation=industrial_reason if special else "")
    metrics["interest_coverage"] = _ratio_metric("interest_coverage", operating_income, interest_expense, "operating_income / interest_expense", frame, "operating_income", applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "", zero_denominator_status="not_applicable")

    distress = _distress_metric(latest, frame, special)
    metrics["altman_like_distress"] = distress
    maturity = (
        {"status": "not_applicable", "buckets": {}, "formula": "sector adapter required", "source_ids": [], "confidence": "low", "limitation": industrial_reason, "coverage_limitations": [industrial_reason], "execution_allowed": False}
        if special else _maturity_timeline(latest, frame)
    )
    stress = (
        {name: {"status": "not_applicable", "value": None, "reason": industrial_reason, "execution_allowed": False} for name in ("revenue_down_20", "margin_down_5pp")}
        if special else _stress_scenarios(latest, frame)
    )
    if strict_comparability and not special:
        balance_specs = {
            "net_debt": (debt_name, "cash"),
            "debt_to_equity": (debt_name, "equity"),
            "current_ratio": ("current_assets", "current_liabilities"),
            "quick_ratio": ("cash", "receivables", "current_liabilities"),
            "working_capital": ("current_assets", "current_liabilities"),
            "interest_coverage": ("operating_income", "interest_expense"),
            "altman_like_distress": ("current_assets", "current_liabilities", "assets", "retained_earnings", "operating_income", "equity", "liabilities", "revenue"),
        }
        for name, metric_components in balance_specs.items():
            evidence = metrics[name]
            observed_value = _float(evidence.get("value"))
            if observed_value is None:
                continue
            comparable_value, reason = _latest_comparable_value(frame, name, metric_components)
            if comparable_value is None or not math.isclose(comparable_value, observed_value, rel_tol=1e-9, abs_tol=1e-12):
                evidence["value"] = None
                evidence["status"] = "unavailable"
                evidence["confidence"] = "low"
                evidence["limitation"] = f"Currency, reporting period and accounting scope must align for calculated values; {reason or 'selected inputs do not share a comparable period.'}"
        stress_observations, stress_reason = _period_observations(frame, ("revenue", "operating_income", "debt", "interest_expense"))
        if stress_reason or not stress_observations:
            reason = f"Currency, reporting period and accounting scope must align for calculated stress evidence; {stress_reason or 'no comparable period.'}"
            stress = {name: {"status": "unavailable", "value": None, "limitation": reason, "execution_allowed": False} for name in ("revenue_down_20", "margin_down_5pp")}
    if strict_comparability and not sector_known:
        limitation = "Classification is unavailable or unresolved; industrial balance-sheet applicability cannot be established."
        for name in ("net_debt", "debt_to_equity", "current_ratio", "quick_ratio", "working_capital", "interest_coverage", "altman_like_distress"):
            _mark_metric_unavailable(metrics[name], limitation)
        stress = {name: {"status": "unavailable", "value": None, "limitation": limitation, "execution_allowed": False} for name in ("revenue_down_20", "margin_down_5pp")}
    debt_cash_breakdown = _debt_cash_breakdown(latest, frame)
    coverage_limitations = list(debt_cash_breakdown["coverage_limitations"]) + list(maturity.get("coverage_limitations", []))
    if strict_comparability and not sector_known:
        coverage_limitations.append("Classification is unavailable or unresolved; industrial balance-sheet applicability cannot be established.")
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "metrics": metrics,
        "net_debt_breakdown": debt_cash_breakdown,
        "maturity_timeline": maturity,
        "coverage_limitations": coverage_limitations,
        "stress_scenarios": stress,
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def valuation_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    market_inputs: Mapping[str, object] | None = None,
    assumptions: Mapping[str, object] | None = None,
    as_known_at: str | date | None = None,
    strict_comparability: bool = False,
    sector: str = "",
    classification_context: Mapping[str, object] | None = None,
    peer_frame: pd.DataFrame | None = None,
    peer_market_inputs: Mapping[str, Mapping[str, object]] | None = None,
    financial_projection: object | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    latest = _latest_values(frame)
    market = {str(key): _float(value) for key, value in (market_inputs or {}).items()}
    assumption_values = {str(key): value for key, value in (assumptions or {}).items()}
    values = {**latest, **{key: value for key, value in market.items() if value is not None}}
    for input_name in ("shares_outstanding", "market_cap", "net_debt", "enterprise_value"):
        if input_name in market:
            values[input_name] = market[input_name]
    if "diluted_shares_outstanding" in latest:
        values["shares_outstanding"] = latest["diluted_shares_outstanding"]
    if values.get("enterprise_value") is None and values.get("market_cap") is not None and values.get("net_debt") is not None:
        adjustments = _float(market.get("other_enterprise_value_adjustments"))
        if adjustments is not None:
            values["enterprise_value"] = values["market_cap"] + values["net_debt"] + adjustments
    if "net_debt" not in market and values.get("net_debt") is None and values.get("debt") is not None and values.get("cash") is not None:
        values["net_debt"] = values["debt"] - values["cash"]
        adjustments = _float(market.get("other_enterprise_value_adjustments"))
        if values.get("market_cap") is not None and adjustments is not None and values.get("enterprise_value") is None:
            values["enterprise_value"] = values["market_cap"] + values["net_debt"] + adjustments
    sector_value = sector or _text((classification_context or {}).get("sector"))
    bank_route = _classification_is_known(sector_value, classification_context) and _is_special_sector(sector_value, classification_context)
    projection_metrics = _financial_projection_metrics(financial_projection) if bank_route else {}
    if bank_route:
        for projection_name, value_name in (("net_profit_attributable", "net_income"), ("closing_equity", "equity"), ("tangible_book_value", "tangible_book_value")):
            if projection_metrics.get(projection_name) is not None:
                values[value_name] = projection_metrics[projection_name]
        sustainable_roe = _float(assumption_values.get("sustainable_roe"))
        sustainable_rote = _float(assumption_values.get("sustainable_rote"))
        if sustainable_roe is not None and values.get("equity") is not None:
            values["net_income"] = values["equity"] * sustainable_roe
            values["net_income_basis"] = "explicit_sustainable_roe_assumption"
        elif sustainable_rote is not None and values.get("tangible_book_value") is not None:
            values["net_income"] = values["tangible_book_value"] * sustainable_rote
            values["net_income_basis"] = "explicit_sustainable_rote_assumption"
        else:
            values["net_income"] = None
    ev_applicability = "not_applicable" if bank_route else "applicable"
    ev_limitation = "Enterprise-value industrial multiples are not applicable to financial institutions." if bank_route else ""
    ebitda = values.get("ebitda")
    relative_metrics = {
        "ev_to_sales": _ratio_metric("ev_to_sales", values.get("enterprise_value"), values.get("revenue"), "enterprise_value / revenue", frame, "enterprise_value", applicability=ev_applicability, limitation=ev_limitation),
        "ev_to_ebitda": _ratio_metric("ev_to_ebitda", values.get("enterprise_value"), ebitda, "enterprise_value / EBITDA", frame, "enterprise_value", applicability=ev_applicability, limitation=ev_limitation),
        "price_to_earnings": _ratio_metric("price_to_earnings", values.get("market_cap"), values.get("net_income"), "market_cap / net_income", frame, "market_cap", zero_denominator_status="not_applicable"),
        "price_to_book": _ratio_metric("price_to_book", values.get("market_cap"), values.get("equity"), "market_cap / equity", frame, "market_cap", zero_denominator_status="not_applicable"),
        "price_to_tangible_book": _ratio_metric("price_to_tangible_book", values.get("market_cap"), values.get("tangible_book_value"), "market_cap / tangible_book_value", frame, "market_cap", applicability="applicable" if bank_route else "not_applicable", limitation="Bank tangible-book multiple; underlying tangible book value must be evidenced." if bank_route else "Applicable to the bank route only."),
        "dividend_yield": _ratio_metric("dividend_yield", values.get("dividend_per_share"), values.get("share_price"), "dividend_per_share / share_price", frame, "dividend_per_share", zero_denominator_status="not_applicable"),
    }
    comparability = {
        "ev_to_sales": _valuation_inputs_comparable(frame, ("revenue",), market_inputs or {}, net_debt=True),
        "ev_to_ebitda": _valuation_inputs_comparable(frame, ("ebitda",), market_inputs or {}, net_debt=True),
        "price_to_earnings": _valuation_inputs_comparable(frame, ("net_income",), market_inputs or {}),
        "price_to_book": _valuation_inputs_comparable(frame, ("equity",), market_inputs or {}),
        "price_to_tangible_book": _valuation_inputs_comparable(frame, ("tangible_book_value",), market_inputs or {}),
    }
    if strict_comparability:
        for name, basis in comparability.items():
            if relative_metrics[name].get("status") != "not_applicable" and basis["status"] != "available":
                relative_metrics[name] = _mark_valuation_metric_unavailable(relative_metrics[name], str(basis["reason"]))
    peer_relative_metrics = _peer_relative_valuation_metrics(
        frame,
        peer_frame,
        peer_market_inputs or {},
        as_known_at=as_known_at,
        instrument_id=instrument_id,
        bank_route=bank_route,
    )
    intrinsic = _not_applicable_valuation("Industrial FCF DCF is not applicable to financial institutions.") if bank_route else _intrinsic_value(values, assumption_values)
    reverse = _not_applicable_valuation("Industrial reverse DCF is not applicable to financial institutions.") if bank_route else _reverse_dcf(values, assumption_values)
    residual_assumptions = assumption_values
    if bank_route and "cost_of_equity" not in assumption_values:
        residual_assumptions = {**assumption_values, "cost_of_equity": None}
    adapter_status = str(_projection_member(financial_projection, "status", "unavailable")) if bank_route else "not_applicable"
    residual = (
        _residual_income(values, residual_assumptions)
        if not bank_route or adapter_status == "available"
        else {"status": "unavailable", "confidence": "low", "reason": "Financial-institution evidence from ISSUE-0099_fundamental_release is unavailable.", "execution_allowed": False}
    )
    if strict_comparability:
        raw_scenarios = assumption_values.get("scenarios")
        margin_scenario = isinstance(raw_scenarios, Mapping) and any(
            isinstance(item, Mapping) and _float(item.get("margin")) is not None
            for item in raw_scenarios.values()
        )
        dcf_facts = ("free_cash_flow", "revenue") if margin_scenario else ("free_cash_flow",)
        dcf_basis = _valuation_inputs_comparable(frame, dcf_facts, market_inputs or {}, net_debt=True)
        if bank_route:
            sustainable_roe = _float(assumption_values.get("sustainable_roe"))
            sustainable_rote = _float(assumption_values.get("sustainable_rote"))
            projection_inputs = (
                ("closing_equity", "tangible_book_value")
                if sustainable_roe is None and sustainable_rote is not None
                else ("closing_equity",)
                if sustainable_roe is not None
                else ("closing_equity", "net_profit_attributable")
            )
            residual_basis = _financial_projection_inputs_comparable(
                financial_projection,
                projection_inputs,
                instrument_id=instrument_id,
                as_known_at=as_known_at,
            )
        else:
            residual_basis = _valuation_inputs_comparable(frame, ("equity", "net_income"), market_inputs or {})
        if not bank_route and dcf_basis["status"] != "available":
            intrinsic = {"status": "unavailable", "confidence": "low", "reason": str(dcf_basis["reason"]), "scenarios": {}, "execution_allowed": False}
            reverse = {"status": "unavailable", "confidence": "low", "reason": str(dcf_basis["reason"]), "execution_allowed": False}
        if residual_basis["status"] != "available":
            residual = {"status": "unavailable", "confidence": "low", "reason": str(residual_basis["reason"]), "execution_allowed": False}
    sensitivity = _residual_income_sensitivity(values, assumption_values) if bank_route else _valuation_sensitivity(values, assumption_values)
    bank_metrics = {
        "sustainable_roe": assumption_values.get("sustainable_roe", projection_metrics.get("sustainable_roe")),
        "sustainable_rote": assumption_values.get("sustainable_rote", projection_metrics.get("rote")),
        "cost_of_equity": assumption_values.get("cost_of_equity"),
        "regulatory_capital_assumptions": assumption_values.get("regulatory_capital_assumptions"),
    } if bank_route else {}
    lineage = _lineage(frame)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "relative_metrics": relative_metrics,
        "comparability": comparability,
        "peer_relative_metrics": peer_relative_metrics,
        "intrinsic_value": intrinsic,
        "reverse_dcf": reverse,
        "residual_income": residual,
        "sensitivity": sensitivity,
        "bank_route": {"status": "available" if bank_route and adapter_status == "available" else "unavailable" if bank_route else "not_applicable", "path": "ISSUE-0099_fundamental_release" if bank_route else "industrial_dcf", "financial_projection_status": adapter_status, "metrics": bank_metrics},
        "model_disagreement": _model_disagreement(intrinsic, residual),
        "assumptions": assumption_values,
        "market_evidence": dict(market_inputs or {}),
        "provider_reported_multiples": {"status": "unavailable", "reason": "No issuer/provider multiple series is available in the supplied evidence."},
        "snapshot": {"valuation_date": market.get("valuation_date"), "decision_time": as_known_at, "price_timestamp": market.get("price_timestamp"), "filing_vintage": market.get("filing_vintage", lineage.get("filing_versions", [])), "currency_conversion_timestamp": market.get("currency_conversion_timestamp"), "assumptions_version": assumption_values.get("version"), "assumptions": assumption_values, "market_evidence": dict(market_inputs or {}), "execution_allowed": False},
        "peer_context": {"status": "available" if isinstance(peer_frame, pd.DataFrame) and not peer_frame.empty else "unavailable", "peer_ids": sorted({str(value) for value in peer_frame.get("instrument_id", pd.Series(dtype="object")).dropna()}) if isinstance(peer_frame, pd.DataFrame) and not peer_frame.empty else [], "period": lineage.get("periods", []), "accounting_scope": lineage.get("accounting_scopes", []), "currency": lineage.get("currencies", []), "outlier_treatment": "No peer multiple outlier treatment; issuer calculated multiples shown separately."},
        "source_lineage": lineage,
        "execution_allowed": False,
    }


def growth_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    strict_comparability: bool = False,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    """Return period-aligned reported growth without analyst assumptions.

    Aggregate values and per-share values are kept in separate series. A
    zero or negative prior period is reported as a base-effect state rather
    than being turned into a misleading percentage. Acquisition and organic
    growth are only calculated when the statement package contains explicit
    structured evidence for them.
    """

    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    periods = _period_rows(frame)
    aggregate = {
        name: _growth_series(periods, name, aliases, basis="aggregate")
        for name, aliases in {
            "revenue": ("revenue",),
            "operating_profit": ("operating_profit",),
            "free_cash_flow": ("free_cash_flow",),
        }.items()
    }
    per_share = {
        "earnings_per_share": _growth_series(
            periods,
            "earnings_per_share",
            ("earnings_per_share",),
            basis="per_share",
            derived_from=("net_income", "shares_outstanding"),
        ),
        "free_cash_flow_per_share": _growth_series(
            periods,
            "free_cash_flow_per_share",
            (),
            basis="per_share",
            derived_from=("free_cash_flow", "shares_outstanding"),
        ),
    }
    result = {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "statement_view": frame.attrs.get("statement_view", "latest_restated"),
        "periods": [period["period_key"] for period in periods],
        "series": {"aggregate": aggregate, "per_share": per_share},
        "organic_inorganic": _organic_inorganic_analysis(frame, periods),
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }
    if strict_comparability:
        for group_name in ("aggregate", "per_share"):
            group = result["series"][group_name]
            for series in group.values():
                if isinstance(series, dict):
                    _apply_growth_comparability(frame, series)
        organic = result["organic_inorganic"]
        for key in ("organic_growth", "inorganic_growth"):
            series = organic.get(key)
            if isinstance(series, dict):
                _apply_growth_comparability(frame, series)
        if organic.get("organic_growth", {}).get("status") == "unavailable":
            organic["status"] = "unavailable"
    return result


def build_stock_research_report(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    peer_frame: pd.DataFrame | None = None,
    peer_market_inputs: Mapping[str, Mapping[str, object]] | None = None,
    classification_context: Mapping[str, object] | None = None,
    peer_context: Mapping[str, object] | None = None,
    financial_projection: object | None = None,
    strict_comparability: bool = True,
    market_inputs: Mapping[str, object] | None = None,
    assumptions: Mapping[str, object] | None = None,
    expectation_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None = None,
    guidance_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    sector = sector or _text((classification_context or {}).get("sector"))
    assumption_values = assumptions or {}
    sector_known = _classification_is_known(sector, classification_context)
    special = sector_known and _is_special_sector(sector, classification_context)
    capital_sector = "financials" if special else sector
    profitability = profitability_analysis(
        frame,
        instrument_id=instrument_id,
        sector=sector,
        peer_frame=peer_frame,
        classification_context=classification_context,
        peer_context=peer_context,
        strict_comparability=strict_comparability,
        tax_rate=_float(assumption_values.get("tax_rate")),
        as_known_at=as_known_at,
    )
    capital_efficiency = capital_efficiency_analysis(
        frame,
        instrument_id=instrument_id,
        sector=capital_sector,
        peer_frame=peer_frame if not strict_comparability else None,
        tax_rate=_float(assumption_values.get("tax_rate")),
        cost_of_capital=_float(assumption_values.get("cost_of_capital")),
        intangible_assumptions=assumption_values.get("intangible_adjustment") if isinstance(assumption_values.get("intangible_adjustment"), Mapping) else None,
        profitability_output=profitability,
        strict_comparability=strict_comparability,
        as_known_at=as_known_at,
    )
    if strict_comparability and not sector_known:
        _mark_capital_efficiency_unavailable(capital_efficiency, "Classification is unavailable or unresolved; industrial capital-efficiency applicability cannot be established.")
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "profitability": profitability,
        "capital_efficiency": capital_efficiency,
        "balance_sheet": balance_sheet_analysis(frame, instrument_id=instrument_id, sector=sector, classification_context=classification_context, strict_comparability=strict_comparability, as_known_at=as_known_at),
        "valuation": valuation_analysis(
            frame,
            instrument_id=instrument_id,
            market_inputs=market_inputs,
            assumptions=assumptions,
            as_known_at=as_known_at,
            strict_comparability=strict_comparability,
            sector=sector,
            classification_context=classification_context,
            peer_frame=peer_frame,
            peer_market_inputs=peer_market_inputs,
            financial_projection=financial_projection,
        ),
        "growth": growth_analysis(frame, instrument_id=instrument_id, strict_comparability=strict_comparability, as_known_at=as_known_at),
        "expectations": _expectations_report(frame, expectation_evidence, guidance_evidence, instrument_id=instrument_id, as_known_at=as_known_at),
        "classification_context": dict(classification_context or {}),
        "peer_context": dict(peer_context or {}),
        "financial_institutions": _financial_projection_payload(financial_projection),
        "statement_context": _statement_context(frame),
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def load_stock_research_frame(path: object, *, instrument_id: str | None = None, as_known_at: str | date | None = None) -> pd.DataFrame:
    try:
        frame = pd.read_parquet(path) if path else pd.DataFrame()
    except (OSError, ValueError, ImportError):
        frame = pd.DataFrame()
    return _statement_frame(frame, instrument_id, as_known_at=as_known_at)


def load_optional_research_import(path: object, *, instrument_id: str | None = None) -> pd.DataFrame:
    """Load local optional evidence without granting it data authority."""

    try:
        candidate = Path(path)
    except TypeError:
        return _empty_optional_import(path, "rejected", "invalid_path")
    if not candidate.is_file():
        return _empty_optional_import(candidate, "missing", "file_not_found")
    try:
        checksum_before = _file_sha256(candidate)
        suffix = candidate.suffix.casefold()
        if suffix == ".csv":
            frame = pd.read_csv(candidate)
        elif suffix in {".json", ".jsonl"}:
            frame = pd.read_json(candidate, lines=suffix == ".jsonl")
        elif suffix == ".parquet":
            frame = pd.read_parquet(candidate)
        else:
            return _empty_optional_import(candidate, "rejected", f"unsupported_file_type:{suffix or 'none'}")
        checksum_after = _file_sha256(candidate)
    except (ImportError, OSError, UnicodeError, ValueError) as exc:
        return _empty_optional_import(candidate, "rejected", f"unreadable_import:{type(exc).__name__}")
    if checksum_before != checksum_after:
        return _empty_optional_import(candidate, "rejected", "file_changed_during_read")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return _empty_optional_import(candidate, "empty", "no_records")
    if instrument_id:
        if "instrument_id" not in frame.columns:
            return _empty_optional_import(candidate, "rejected", "missing_instrument_id")
        frame = frame[frame["instrument_id"].astype(str).eq(str(instrument_id))].copy()
        if frame.empty:
            return _empty_optional_import(candidate, "empty", "instrument_not_present")
    if "source_checksum" not in frame.columns:
        frame["source_checksum"] = checksum_after
    else:
        supplied = frame["source_checksum"].notna() & frame["source_checksum"].astype(str).str.strip().ne("")
        frame["source_checksum"] = frame["source_checksum"].where(supplied, checksum_after)
    frame = frame.reset_index(drop=True)
    frame.attrs.update({"import_path": str(candidate), "import_status": "loaded", "import_reason": "", "file_sha256": checksum_after})
    return frame


def _empty_optional_import(path: object, status: str, reason: str) -> pd.DataFrame:
    frame = pd.DataFrame()
    frame.attrs.update({"import_path": str(path), "import_status": status, "import_reason": reason})
    return frame


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _statement_frame(frame: pd.DataFrame, instrument_id: str | None, *, as_known_at: str | date | None = None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    view = "as_known_at" if as_known_at is not None else "latest_restated"
    result = statement_view(frame, view, as_known_at=as_known_at)
    if instrument_id and "instrument_id" in result.columns:
        result = result[result["instrument_id"].astype(str).eq(str(instrument_id))]
    if "canonical_metric" in result.columns:
        result["canonical_metric"] = result["canonical_metric"].map(lambda value: _METRIC_ALIASES.get(_text(value), _text(value)))
    result = result.reset_index(drop=True)
    result.attrs["statement_view"] = view
    if as_known_at is not None:
        result.attrs["as_known_at"] = pd.Timestamp(as_known_at).date().isoformat()
    return result


def _latest_values(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty or "canonical_metric" not in frame.columns:
        return {}
    result: dict[str, float] = {}
    ordered = frame.copy()
    for column in ("period_end", "filed", "fiscal_year", "period_key"):
        if column not in ordered:
            ordered[column] = ""
    ordered = ordered.sort_values(["canonical_metric", "period_end", "filed", "fiscal_year", "period_key"], kind="stable", na_position="last")
    for metric, rows in ordered.groupby("canonical_metric", dropna=True):
        numeric = pd.to_numeric(rows["value"], errors="coerce").dropna()
        if not numeric.empty:
            result[str(metric)] = float(numeric.iloc[-1])
    return result


def _histories(frame: pd.DataFrame) -> dict[str, list[float]]:
    if frame.empty or "canonical_metric" not in frame.columns:
        return {}
    ordered = frame.copy()
    for column in ("period_end", "fiscal_year", "period_key"):
        if column not in ordered:
            ordered[column] = ""
    ordered = ordered.sort_values(["period_end", "fiscal_year", "period_key"], kind="stable", na_position="last")
    result: dict[str, list[float]] = {}
    for metric, rows in ordered.groupby("canonical_metric", dropna=True):
        values = pd.to_numeric(rows["value"], errors="coerce").dropna().astype(float).tolist()
        if values:
            result[str(metric)] = values
    return result


def _period_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Build one deterministic, period-aligned row per statement period."""

    if frame.empty or "canonical_metric" not in frame.columns:
        return []
    work = frame.copy()
    for column, default in (("period_type", "unknown"), ("period_key", ""), ("period_end", ""), ("fiscal_year", "")):
        if column not in work.columns:
            work[column] = default
    work["__period_end"] = work["period_end"].fillna("").astype(str)
    work["__sort_end"] = pd.to_datetime(work["__period_end"], errors="coerce")
    work = work.sort_values(["__sort_end", "__period_end", "period_key", "canonical_metric", "source_id"], kind="stable", na_position="last")
    periods: list[dict[str, object]] = []
    grouped = work.groupby(["period_type", "period_key", "__period_end"], sort=False, dropna=False)
    for (period_type, period_key, period_end), rows in grouped:
        raw_values: dict[str, float] = {}
        raw_sources: dict[str, tuple[str, ...]] = {}
        for metric, metric_rows in rows.groupby("canonical_metric", dropna=True, sort=False):
            ordered = metric_rows.assign(__restatement_rank=metric_rows["restatement_kind"].map(_restatement_rank)).sort_values(["filed", "__restatement_rank", "accession", "source_id"], kind="stable", na_position="last")
            numeric = ordered.assign(__numeric=pd.to_numeric(ordered["value"], errors="coerce")).dropna(subset=["__numeric"])
            if numeric.empty:
                continue
            raw_values[str(metric)] = float(numeric.iloc[-1]["__numeric"])
            raw_sources[str(metric)] = tuple(sorted({str(value) for value in numeric["source_id"].dropna() if str(value)}))

        values: dict[str, float] = {}
        sources: dict[str, tuple[str, ...]] = {}
        formulas: dict[str, str] = {}
        for logical, aliases in _GROWTH_ALIASES.items():
            for alias in aliases:
                if alias in raw_values:
                    values[logical] = raw_values[alias]
                    sources[logical] = raw_sources.get(alias, ())
                    formulas[logical] = f"reported {alias}"
                    break
        if "earnings_per_share" not in values and {"net_income", "shares_outstanding"} <= values.keys() and values["shares_outstanding"] != 0:
            values["earnings_per_share"] = values["net_income"] / values["shares_outstanding"]
            sources["earnings_per_share"] = tuple(sorted(set(sources.get("net_income", ())) | set(sources.get("shares_outstanding", ()))))
            formulas["earnings_per_share"] = "net_income / shares_outstanding"

        first = rows.iloc[0]
        fiscal_year = str(first.get("fiscal_year", "") or "")
        aliases = {str(period_key), str(period_end)}
        if fiscal_year and fiscal_year not in {"nan", "None"}:
            aliases.update({fiscal_year, f"FY{fiscal_year}"})
        flags: list[str] = []
        for column in ("acquisition_flag", "inorganic_flag", "divestiture_flag", "transaction_flag"):
            if column in rows and any(_truthy(value) for value in rows[column]):
                flags.append(column)
        for metric in ("acquisition_revenue", "inorganic_revenue", "acquired_revenue"):
            if metric in raw_values and raw_values[metric] != 0:
                flags.append(metric)
        periods.append(
            {
                "period_type": str(period_type),
                "period_key": str(period_key),
                "period_end": str(period_end),
                "period_aliases": sorted(alias for alias in aliases if alias),
                "values": values,
                "source_ids": sources,
                "formulas": formulas,
                "flags": sorted(set(flags)),
            }
        )
    return periods


def _growth_series(
    periods: list[dict[str, object]],
    name: str,
    aliases: tuple[str, ...],
    *,
    basis: str,
    derived_from: tuple[str, str] | None = None,
) -> dict[str, object]:
    history: list[dict[str, object]] = []
    for period in periods:
        values = period.get("values", {})
        if not isinstance(values, Mapping):
            continue
        value = next((_float(values.get(alias)) for alias in aliases if _float(values.get(alias)) is not None), None)
        formula = next((str(period.get("formulas", {}).get(alias, "")) for alias in aliases if alias in period.get("formulas", {})), "")
        source_ids = next((tuple(period.get("source_ids", {}).get(alias, ())) for alias in aliases if alias in period.get("source_ids", {})), ())
        if value is None and derived_from and all(_float(values.get(item)) is not None for item in derived_from):
            numerator = _float(values[derived_from[0]])
            denominator = _float(values[derived_from[1]])
            if numerator is not None and denominator not in (None, 0):
                value = numerator / denominator
                formula = f"{derived_from[0]} / {derived_from[1]}"
                source_ids = tuple(sorted(set(period.get("source_ids", {}).get(derived_from[0], ())) | set(period.get("source_ids", {}).get(derived_from[1], ()))))
        history.append(
            {
                "period_type": period["period_type"],
                "period_key": period["period_key"],
                "period_end": period["period_end"],
                "value": value,
                "basis": basis,
                "formula": formula or f"reported {name}",
                "source_ids": list(source_ids),
                "status": "available" if value is not None else "missing",
            }
        )
    growth: list[dict[str, object]] = []
    by_type: dict[str, list[dict[str, object]]] = {}
    for point in history:
        by_type.setdefault(str(point["period_type"]), []).append(point)
    for points in by_type.values():
        for prior, current in zip(points, points[1:]):
            prior_value = _float(prior["value"])
            current_value = _float(current["value"])
            comparison = "year_over_year" if current["period_type"] == "annual" else "period_over_period"
            base_effect = "normal"
            status = "available"
            value: float | None
            if prior_value is None or current_value is None:
                value = None
                status = "missing"
                base_effect = "missing_period"
            elif prior_value == 0:
                value = None
                status = "base_effect"
                base_effect = "prior_zero"
            elif prior_value < 0:
                value = None
                status = "base_effect"
                base_effect = "prior_negative"
            else:
                value = current_value / prior_value - 1.0
                if current_value < 0:
                    base_effect = "current_negative"
            growth.append(
                {
                    "period_type": current["period_type"],
                    "period_key": current["period_key"],
                    "period_end": current["period_end"],
                    "base_period_key": prior["period_key"],
                    "value": value,
                    "basis": basis,
                    "formula": "(current / prior) - 1",
                    "comparison": comparison,
                    "base_effect": base_effect,
                    "status": status,
                    "source_ids": sorted(set(prior.get("source_ids", [])) | set(current.get("source_ids", []))),
                    "execution_allowed": False,
                }
            )
    growth.sort(key=lambda item: (str(item["period_end"]), str(item["period_key"])))
    return {
        "basis": basis,
        "history": history,
        "growth": growth,
        "latest_growth": growth[-1] if growth else None,
        "status": "available" if any(point.get("value") is not None for point in history) else "missing",
        "formula": "(current / prior) - 1",
        "execution_allowed": False,
    }


def _organic_inorganic_analysis(frame: pd.DataFrame, periods: list[dict[str, object]]) -> dict[str, object]:
    organic = _growth_series(periods, "organic_revenue", ("organic_revenue",), basis="aggregate")
    acquired = _growth_series(periods, "acquisition_revenue", ("acquisition_revenue",), basis="aggregate")
    flags = [
        {"period_key": period["period_key"], "flags": period["flags"]}
        for period in periods
        if period.get("flags")
    ]
    has_organic = any(point.get("value") is not None for point in organic["history"])
    return {
        "status": "available" if has_organic else "unavailable",
        "organic_growth": organic,
        "inorganic_growth": acquired,
        "acquisition_flags": flags,
        "limitation": "Organic growth is unavailable without explicit organic-revenue or acquisition evidence; consolidated growth is not silently labelled organic." if not has_organic else "",
        "execution_allowed": False,
    }


def _expectations_report(
    statements: pd.DataFrame,
    expectation_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None,
    guidance_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None,
    *,
    instrument_id: str | None,
    as_known_at: str | date | None,
) -> dict[str, object]:
    consensus_rows, consensus_rejected, cutoff = _prepare_optional_rows(expectation_evidence, instrument_id=instrument_id, as_known_at=as_known_at, guidance=False)
    guidance_rows, guidance_rejected, _ = _prepare_optional_rows(guidance_evidence, instrument_id=instrument_id, as_known_at=as_known_at, guidance=True)
    return {
        "as_known_at": cutoff,
        "consensus": _consensus_report(statements, consensus_rows, consensus_rejected, cutoff),
        "guidance": _guidance_report(guidance_rows, guidance_rejected),
        "execution_allowed": False,
    }


def _consensus_report(frame: pd.DataFrame, rows: list[dict[str, object]], rejected: list[str], cutoff: str | None) -> dict[str, object]:
    if not rows:
        return {"status": "unavailable", "metrics": {}, "accepted_records": 0, "rejected_records": rejected, "reason": "No licensed point-in-time consensus evidence was supplied.", "execution_allowed": False}
    periods = _period_rows(frame)
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((str(row["metric"]), str(row["period_key"])), []).append(row)
    metrics: dict[str, dict[str, object]] = {}
    for (metric, period_key), candidates in sorted(grouped.items()):
        ordered = sorted(candidates, key=lambda item: (str(item["available_at"]), str(item["source_id"])))
        latest_timestamp = ordered[-1]["available_at"]
        latest_rows = [item for item in ordered if item["available_at"] == latest_timestamp]
        latest_values = [float(item["value"]) for item in latest_rows if item.get("value") is not None]
        if not latest_values:
            continue
        latest = latest_rows[-1]
        actual = _actual_for_period(periods, metric, period_key)
        estimate = float(latest["value"])
        surprise = None
        if actual is not None:
            surprise = {"value": actual - estimate, "percent": None if estimate == 0 else actual / estimate - 1.0, "formula": "actual - estimate", "status": "available"}
        revision_value = float(latest["value"]) - float(ordered[0]["value"])
        revision = {"value": revision_value, "status": "available" if len(ordered) > 1 else "not_available", "formula": "latest estimate - earliest estimate"}
        dispersion = {"value": max(latest_values) - min(latest_values), "status": "available" if len(latest_values) > 1 else "not_available", "formula": "max(latest-vintage estimates) - min(latest-vintage estimates)"}
        staleness = _staleness(latest["available_at"], cutoff)
        item = {
            "period_key": period_key,
            "latest_value": estimate,
            "latest_available_at": latest["available_at"],
            "source_ids": sorted({str(candidate["source_id"]) for candidate in candidates}),
            "source_authorities": sorted({str(candidate["source_authority"]) for candidate in candidates}),
            "license_statuses": sorted({str(candidate["license_status"]) for candidate in candidates if candidate.get("license_status")}),
            "source_records": [
                {
                    "source_id": candidate["source_id"],
                    "source_authority": candidate["source_authority"],
                    "license_status": candidate["license_status"],
                    "source_checksum": candidate["source_checksum"],
                }
                for candidate in ordered
            ],
            "revision": revision,
            "dispersion": dispersion,
            "surprise": surprise or {"value": None, "percent": None, "status": "unavailable", "reason": "Reported actual for this period is unavailable."},
            "staleness": staleness,
            "revision_history": [{key: candidate[key] for key in ("value", "available_at", "source_id")} for candidate in ordered],
            "execution_allowed": False,
        }
        metrics.setdefault(metric, {})[period_key] = item
    return {
        "status": "available" if metrics else "unavailable",
        "metrics": metrics,
        "accepted_records": len(rows),
        "rejected_records": rejected,
        "source_ids": sorted({str(row["source_id"]) for row in rows}),
        "execution_allowed": False,
    }


def _guidance_report(rows: list[dict[str, object]], rejected: list[str]) -> dict[str, object]:
    if not rows:
        return {"status": "unavailable", "items": [], "accepted_records": 0, "rejected_records": rejected, "reason": "Guidance requires structured or human-reviewed evidence with provenance.", "execution_allowed": False}
    items = []
    for row in sorted(rows, key=lambda item: (str(item["available_at"]), str(item["source_id"]))):
        items.append(
            {
                "status": "available",
                "metric": row.get("metric"),
                "period_key": row.get("period_key"),
                "value": row.get("value"),
                "lower": row.get("lower"),
                "upper": row.get("upper"),
                "text": row.get("text", ""),
                "source_id": row["source_id"],
                "source_authority": row["source_authority"],
                "license_status": row["license_status"],
                "source_checksum": row.get("source_checksum"),
                "review_status": row["review_status"],
                "available_at": row["available_at"],
                "execution_allowed": False,
            }
        )
    return {"status": "available", "items": items, "accepted_records": len(items), "rejected_records": rejected, "execution_allowed": False}


def _prepare_optional_rows(
    evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None,
    *,
    instrument_id: str | None,
    as_known_at: str | date | None,
    guidance: bool,
) -> tuple[list[dict[str, object]], list[str], str | None]:
    if evidence is None:
        return [], [], _normalise_cutoff(as_known_at)
    cutoff = _normalise_cutoff(as_known_at)
    if as_known_at is not None and cutoff is None:
        return [], ["invalid_as_known_at"], None
    frame = _evidence_frame(evidence)
    valid: list[dict[str, object]] = []
    import_reason = _text(frame.attrs.get("import_reason"))
    rejected: list[str] = [f"import:{import_reason}"] if import_reason and import_reason != "file_not_found" else []
    for index, raw in enumerate(frame.to_dict("records")):
        row_instrument = _text(raw.get("instrument_id"))
        if instrument_id and row_instrument and row_instrument != str(instrument_id):
            rejected.append(f"row_{index}:instrument_mismatch")
            continue
        reason, row = _validate_optional_row(raw, index=index, cutoff=cutoff, guidance=guidance)
        if reason:
            rejected.append(reason)
        elif row is not None:
            valid.append(row)
    return valid, rejected, cutoff


def _validate_optional_row(raw: Mapping[str, object], *, index: int, cutoff: str | None, guidance: bool) -> tuple[str | None, dict[str, object] | None]:
    source_id = _text(_first_present(raw.get("source_id"), raw.get("source"), raw.get("citation")))
    source_authority = _text(_first_present(raw.get("source_authority"), raw.get("authority"), raw.get("ownership")))
    source_kind = _text(_first_present(raw.get("source_kind"), raw.get("source_type"))).casefold()
    provider = _text(_first_present(raw.get("provider"), raw.get("vendor"), raw.get("source_name"))).casefold()
    if not source_authority and source_kind in {"official", "company", "issuer"}:
        source_authority = source_kind
    authority_key = source_authority.casefold().replace("–", "-")
    allowed_authorities = _GUIDANCE_SOURCE_AUTHORITIES if guidance else _CONSENSUS_SOURCE_AUTHORITIES
    source_checksum = _text(_first_present(raw.get("source_checksum"), raw.get("checksum")))
    available_at = _normalise_timestamp(_first_present(raw.get("available_at"), raw.get("as_of"), raw.get("published_at")))
    supplied_licence = _text(_first_present(raw.get("license_status"), raw.get("licence_status")))
    licence_key = supplied_licence.casefold().replace("-", "_").replace(" ", "_")
    if source_kind in {"current_analyst", "current_analyst_field", "analyst_current"} or "yahoo" in provider or "yahoo" in source_id.casefold() or ("analyst" in provider and "point" not in source_kind):
        return f"row_{index}:current_or_restricted_provider_rejected", None
    if not source_id or not available_at or authority_key not in allowed_authorities or not _valid_checksum(source_checksum):
        return f"row_{index}:missing_or_unlicensed_provenance", None
    if any(marker in licence_key for marker in _REJECTED_LICENCE_MARKERS):
        return f"row_{index}:missing_or_unlicensed_provenance", None
    if cutoff and available_at > cutoff:
        return f"row_{index}:after_as_known_cutoff", None
    metric = _normalise_optional_metric(_first_present(raw.get("canonical_metric"), raw.get("metric"), raw.get("measure")))
    period_key = _text(_first_present(raw.get("period_key"), raw.get("period_end"), raw.get("fiscal_year")))
    value = _first_float(raw.get("value"), raw.get("estimate"), raw.get("forecast"))
    if not guidance and (not metric or not period_key or value is None):
        return f"row_{index}:missing_metric_period_or_value", None
    review_status = _text(_first_present(raw.get("review_status"), raw.get("review"))).casefold().replace(" ", "_")
    text = _text(_first_present(raw.get("guidance_text"), raw.get("text"), raw.get("statement")))
    lower = _first_float(raw.get("lower"), raw.get("low"))
    upper = _first_float(raw.get("upper"), raw.get("high"))
    if guidance and lower is not None and upper is not None and lower > upper:
        return f"row_{index}:invalid_guidance_range", None
    if guidance and value is not None and ((lower is not None and value < lower) or (upper is not None and value > upper)):
        return f"row_{index}:guidance_value_outside_range", None
    if guidance and not period_key:
        return f"row_{index}:missing_guidance_period", None
    if guidance and (review_status not in _REVIEWED_GUIDANCE_STATUSES or (value is None and lower is None and upper is None and not text)):
        return f"row_{index}:guidance_not_structured_or_reviewed", None
    if guidance and not metric:
        metric = _normalise_optional_metric(raw.get("guidance_type") or "guidance") or "guidance"
    return None, {
        "metric": metric,
        "period_key": period_key,
        "value": value,
        "lower": lower,
        "upper": upper,
        "text": text,
        "source_id": source_id,
        "source_authority": source_authority,
        "license_status": supplied_licence or _default_license_status(authority_key),
        "source_checksum": source_checksum,
        "available_at": available_at,
        "review_status": review_status,
    }


def _default_license_status(authority_key: str) -> str:
    if "user" in authority_key:
        return "user_owned"
    if "broker" in authority_key:
        return "broker_licensed"
    if "licensed" in authority_key:
        return "licensed_vendor"
    return "official"


def _actual_for_period(periods: list[dict[str, object]], metric: str, period_key: str) -> float | None:
    aliases = ("operating_profit",) if metric == "operating_profit" else ("earnings_per_share",) if metric == "earnings_per_share" else (metric,)
    for period in periods:
        if period_key in period.get("period_aliases", []) or period_key == period.get("period_key"):
            values = period.get("values", {})
            if isinstance(values, Mapping):
                for alias in aliases:
                    value = _float(values.get(alias))
                    if value is not None:
                        return value
    return None


def _staleness(available_at: str, cutoff: str | None) -> dict[str, object]:
    if not cutoff:
        return {"status": "not_evaluated", "days": None}
    days = max(0, (pd.Timestamp(cutoff) - pd.Timestamp(available_at)).days)
    return {"status": "available", "days": days, "as_known_at": cutoff}


def _evidence_frame(evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(evidence, pd.DataFrame):
        return evidence.copy()
    if isinstance(evidence, Mapping):
        records = evidence.get("records")
        if isinstance(records, Iterable) and not isinstance(records, (str, bytes, Mapping)):
            evidence = records
        else:
            return pd.DataFrame([dict(evidence)])
    if isinstance(evidence, Iterable) and not isinstance(evidence, (str, bytes)):
        rows = [asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item) if isinstance(item, Mapping) else {} for item in evidence]
        return pd.DataFrame(rows)
    return pd.DataFrame()


def _normalise_optional_metric(value: object) -> str:
    key = _text(value).casefold().replace("-", "_").replace(" ", "_")
    return {
        "sales": "revenue",
        "operating_income": "operating_profit",
        "ebit": "operating_profit",
        "eps": "earnings_per_share",
        "diluted_eps": "earnings_per_share",
        "basic_eps": "earnings_per_share",
        "fcf": "free_cash_flow",
    }.get(key, key)


def _normalise_timestamp(value: object) -> str:
    if value is None or not _text(value):
        return ""
    if isinstance(value, (bool, int, float)):
        return ""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(timestamp):
        return ""
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat()


def _valid_checksum(value: str) -> bool:
    checksum = value.casefold().removeprefix("sha256:")
    return len(checksum) == 64 and all(character in "0123456789abcdef" for character in checksum)


def _normalise_cutoff(value: str | date | None) -> str | None:
    if value is None:
        return None
    timestamp = _normalise_timestamp(value)
    return timestamp or None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if _float(value) is not None:
        return bool(_float(value))
    return _text(value).casefold() in {"1", "true", "yes", "y", "material"}


def _restatement_rank(value: object) -> int:
    return {"reported": 0, "restated": 1, "amended": 2, "corrected": 3}.get(_text(value).casefold(), 1)


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.api.types.is_scalar(value) and bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _is_special_sector(sector: str, classification: Mapping[str, object] | None = None) -> bool:
    labels = {_text(sector).casefold()}
    for name in ("sector", "industry", "issuer_sector", "issuer_type"):
        value = _text((classification or {}).get(name)).casefold()
        if value:
            labels.update({value, value.replace("-", "_")})
    for name in ("business_model_tags", "strategy_labels", "special_structures"):
        values = (classification or {}).get(name, ())
        if isinstance(values, str):
            values = (values,)
        if isinstance(values, Iterable):
            labels.update(label for value in values if _text(value) for label in (_text(value).casefold(), _text(value).casefold().replace("-", "_")))
    return any(label in _SPECIAL_SECTORS for label in labels)


def _classification_is_known(sector: str, classification: Mapping[str, object] | None = None) -> bool:
    status = _text((classification or {}).get("classification_status")).casefold()
    if status in {"unresolved", "manual_review", "unavailable", "unknown"}:
        return False
    return _text(sector).casefold() not in {"", "unclassified", "unavailable", "unknown"}


def _mark_metric_unavailable(metric: dict[str, object], reason: str) -> None:
    metric["value"] = None
    metric["status"] = "unavailable"
    metric["confidence"] = "low"
    metric["limitation"] = reason


def _mark_capital_efficiency_unavailable(report: dict[str, object], reason: str) -> None:
    for name in ("reported", "adjusted"):
        section = report.get(name)
        if not isinstance(section, dict):
            continue
        metrics = section.get("metrics")
        if isinstance(metrics, dict):
            for metric in metrics.values():
                if isinstance(metric, dict) and metric.get("status") != "not_applicable":
                    _mark_metric_unavailable(metric, reason)
        section["history"] = []
        if section.get("status") != "disabled":
            section["status"] = "unavailable"
        section["limitation"] = reason
    relative = report.get("sector_relative")
    if isinstance(relative, dict):
        relative.update({"status": "unavailable", "reason": reason, "peer_count": 0, "percentiles": {}})


def _first_present(*values: object) -> object | None:
    return next((value for value in values if _text(value)), None)


def _first_float(*values: object) -> float | None:
    return next((number for value in values if (number := _float(value)) is not None), None)


def _derived_history(histories: Mapping[str, list[float]], numerator: str, denominator: str) -> list[float]:
    numerators = histories.get(numerator, [])
    denominators = histories.get(denominator, [])
    return [float(numerator_value / denominator_value) for numerator_value, denominator_value in zip(numerators, denominators) if denominator_value != 0]


def _ratio_metric(name: str, numerator: float | None, denominator: float | None, formula: str, frame: pd.DataFrame, source_metric: str, *, applicability: str = "applicable", limitation: str = "", zero_denominator_status: str = "missing") -> dict[str, object]:
    if applicability != "applicable":
        return _metric(name, None, formula, frame, status_override="not_applicable", source_metric=source_metric, applicability=applicability, limitation=limitation)
    if numerator is None or denominator is None:
        return _metric(name, None, formula, frame, status_override="missing", source_metric=source_metric, limitation=limitation)
    if denominator == 0:
        return _metric(name, None, formula, frame, status_override=zero_denominator_status, source_metric=source_metric, limitation="Denominator is zero; the ratio is not defined.")
    return _metric(name, float(numerator / denominator), formula, frame, source_metric=source_metric, limitation=limitation)


def _metric(name: str, value: float | None, formula: str, frame: pd.DataFrame, *, status_override: str | None = None, source_metric: str | None = None, applicability: str = "applicable", limitation: str = "") -> dict[str, object]:
    source_ids = _source_ids(frame, source_metric or name)
    period = _period_label(frame)
    status = status_override or ("missing" if value is None else "negative" if value < 0 else "available")
    result = asdict(MetricEvidence(name, value, status, formula, period, source_ids, "high" if value is not None and source_ids else "low", applicability, limitation))
    result["value_kind"] = "calculated"
    result["evidence"] = _evidence_metadata(frame)
    return result


def _source_ids(frame: pd.DataFrame, metric: str) -> tuple[str, ...]:
    if frame.empty or "canonical_metric" not in frame.columns or "source_id" not in frame.columns:
        return ()
    return tuple(sorted({str(value) for value in frame.loc[frame["canonical_metric"].astype(str).eq(metric), "source_id"].dropna() if str(value)}))


def _period_label(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "unavailable"
    for column in ("period_end", "period_key", "fiscal_year"):
        if column in frame and frame[column].notna().any():
            value = frame[column].dropna().astype(str).iloc[-1]
            if value:
                return value
    return "unavailable"


def _lineage(frame: pd.DataFrame) -> dict[str, object]:
    lineage = {
        "statement_view": frame.attrs.get("statement_view", "latest_restated"),
        "coverage": statement_coverage(frame),
        "source_ids": sorted({str(value) for value in frame.get("source_id", pd.Series(dtype="object")).dropna() if str(value)}),
        **_evidence_metadata(frame),
        "execution_allowed": False,
    }
    if frame.attrs.get("as_known_at"):
        lineage["as_known_at"] = frame.attrs["as_known_at"]
    return lineage


def _evidence_metadata(frame: pd.DataFrame) -> dict[str, object]:
    columns = {
        "periods": ("period_key", "period_end"),
        "known_at": ("known_at", "available_at"),
        "units": ("unit",),
        "currencies": ("currency",),
        "restatements": ("restatement_kind",),
        "filing_versions": ("filing_version", "accession", "form"),
        "accounting_scopes": ("consolidation_scope", "accounting_scope"),
    }
    result: dict[str, object] = {}
    for output, candidates in columns.items():
        column = next((name for name in candidates if name in frame.columns), None)
        values = () if column is None else tuple(sorted({_text(value) for value in frame[column].tolist() if _text(value)}))
        result[output] = list(values)
    result["source_ids"] = sorted({str(value) for value in frame.get("source_id", pd.Series(dtype="object")).dropna() if _text(value)})
    result["coverage"] = statement_coverage(frame)
    return result


def _statement_context(frame: pd.DataFrame) -> dict[str, object]:
    metadata = _evidence_metadata(frame)

    def single(values: object) -> str:
        items = values if isinstance(values, list) else []
        if len(items) == 1:
            return str(items[0])
        return "unavailable" if not items else "mixed"

    return {
        "currency": single(metadata.get("currencies")),
        "accounting_scope": single(metadata.get("accounting_scopes")),
        "period": max((_text(value) for value in frame.get("period_end", pd.Series(dtype="object")).tolist() if _text(value)), default="unavailable"),
        "known_at": max((str(value) for value in metadata.get("known_at", []) if str(value)), default="unavailable"),
        "execution_allowed": False,
    }


def _debt_cash_breakdown(values: Mapping[str, float], frame: pd.DataFrame) -> dict[str, object]:
    contractual_value = values.get("contractual_debt")
    reported_debt = values.get("debt")
    leases = values.get("lease_liabilities")
    cash = values.get("cash")
    restricted_cash = values.get("restricted_cash")
    limitations = []
    if contractual_value is None:
        limitations.append("Contractual debt is unavailable as a distinct reported fact; generic reported debt is not silently reclassified.")
    if leases is None:
        limitations.append("Lease liabilities are unavailable; lease inclusion in reported debt cannot be assessed.")
    elif contractual_value is None:
        limitations.append("Reported debt does not state whether lease liabilities are included; the lease amount remains a separate adjustment.")
    if restricted_cash is None:
        limitations.append("Restricted cash is unavailable; reported cash is not adjusted for restrictions.")
    elif cash is None:
        limitations.append("Restricted cash is reported but unrestricted cash cannot be derived without a reported cash balance.")
    return {
        "contractual_debt": {"value": contractual_value, "status": "available" if contractual_value is not None else "unavailable", "source_ids": list(_source_ids(frame, "contractual_debt")), "value_kind": "reported"},
        "reported_debt": {"value": reported_debt, "status": "available" if reported_debt is not None else "unavailable", "source_ids": list(_source_ids(frame, "debt")), "value_kind": "reported", "basis": "lease_inclusion_unspecified"},
        "lease_liabilities": {"value": leases, "status": "available" if leases is not None else "unavailable", "source_ids": list(_source_ids(frame, "lease_liabilities")), "value_kind": "reported", "included_in_net_debt": False},
        "lease_adjustment": {"value": leases, "status": "available" if leases is not None else "unavailable", "included_in_net_debt": False},
        "cash": {"value": cash, "status": "available" if cash is not None else "unavailable", "source_ids": list(_source_ids(frame, "cash")), "value_kind": "reported", "basis": "restricted_cash_inclusion_unspecified"},
        "restricted_cash": {"value": restricted_cash, "status": "available" if restricted_cash is not None else "unavailable", "source_ids": list(_source_ids(frame, "restricted_cash")), "value_kind": "reported", "subtracted_from_cash": False},
        "formula": "Reported debt - reported cash; lease and restricted-cash adjustments remain separate until inclusion basis is evidenced.",
        "coverage_limitations": limitations,
        "execution_allowed": False,
    }


def _tax_rate(values: Mapping[str, float]) -> float | None:
    tax_expense = values.get("tax_expense")
    pre_tax = values.get("income_before_tax")
    if tax_expense is None or pre_tax in (None, 0):
        return None
    return float(tax_expense / pre_tax)


def _sum_if_present(*values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    return float(sum(value for value in values if value is not None))


def _float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _peer_percentile(metric: str, value: object, peer_frame: pd.DataFrame | None) -> float | None:
    observed = _float(value)
    if observed is None or not isinstance(peer_frame, pd.DataFrame) or peer_frame.empty:
        return None
    peer = _statement_frame(peer_frame, None)
    values = _latest_values(peer)
    if metric in values:
        peers = [values[metric]]
    else:
        histories = _histories(peer)
        peers = _derived_history(histories, "gross_profit", "revenue") if metric == "gross_margin" else []
    if not peers:
        return None
    return float(100.0 * (sum(item < observed for item in peers) + 0.5 * sum(item == observed for item in peers)) / len(peers))


_PEER_COMPONENTS = {
    "gross_margin": ("gross_profit", "revenue"),
    "operating_margin": ("operating_income", "revenue"),
    "net_margin": ("net_income", "revenue"),
    "roa": ("net_income", "assets"),
    "roe": ("net_income", "equity"),
    "cash_conversion": ("cash_from_operations", "net_income"),
    "accrual_ratio": ("net_income", "cash_from_operations", "assets"),
    "exceptional_item_dependence": ("exceptional_items", "net_income"),
}


def _period_basis_key(row: Mapping[str, object]) -> tuple[str, str, str] | None:
    period_type = _text(row.get("period_type")).casefold()
    fiscal_year = _text(row.get("fiscal_year"))
    fiscal_period = _text(row.get("fiscal_period")) or _text(row.get("period_key"))
    if not period_type or not fiscal_year and not fiscal_period:
        return None
    return period_type, fiscal_year, fiscal_period


def _accounting_scope(row: Mapping[str, object]) -> str:
    return _text(_first_present(row.get("consolidation_scope"), row.get("accounting_scope")))


def _period_observations(frame: pd.DataFrame, components: tuple[str, ...]) -> tuple[dict[tuple[str, str, str], dict[str, object]], str]:
    if frame.empty or "canonical_metric" not in frame.columns:
        return {}, "statement_evidence_unavailable"
    grouped: dict[str, dict[tuple[str, str, str], pd.DataFrame]] = {}
    for metric in components:
        subset = frame[frame["canonical_metric"].astype(str).eq(metric)]
        periods: dict[tuple[str, str, str], pd.DataFrame] = {}
        for index, row in subset.iterrows():
            key = _period_basis_key(row)
            if key is not None:
                periods.setdefault(key, []).append(index)
        grouped[metric] = {key: subset.loc[indices] for key, indices in periods.items()}
        if not grouped[metric]:
            return {}, f"missing_{metric}_periods"
    common = set.intersection(*(set(periods) for periods in grouped.values()))
    if not common:
        return {}, "period_basis_mismatch"
    observations: dict[tuple[str, str, str], dict[str, object]] = {}
    for key in common:
        rows = [grouped[metric][key] for metric in components]
        currencies = {_text(value).upper() for group in rows for value in group.get("currency", pd.Series(dtype="object")).tolist() if _text(value)}
        scopes = {_accounting_scope(record) for group in rows for record in group.to_dict("records") if _accounting_scope(record)}
        if not currencies:
            return {}, "currency_unavailable"
        if len(currencies) != 1:
            return {}, "currency_mismatch"
        if not scopes:
            return {}, "accounting_scope_unavailable"
        if len(scopes) != 1:
            return {}, "accounting_scope_mismatch"
        period_ends = {_text(value) for group in rows for value in group.get("period_end", pd.Series(dtype="object")).tolist() if _text(value)}
        if not period_ends:
            return {}, "period_end_unavailable"
        if len(period_ends) != 1:
            return {}, "period_end_mismatch"
        values: dict[str, float] = {}
        for metric, group in zip(components, rows):
            selected = group.copy()
            if "dimensions" in selected.columns:
                dimensions = {_text(value) for value in selected["dimensions"].tolist() if _text(value)}
                if len(dimensions) > 1:
                    return {}, "accounting_scope_mismatch"
            for column in ("filed", "known_at", "source_id"):
                if column not in selected.columns:
                    selected[column] = ""
            selected = selected.sort_values(["filed", "known_at", "source_id"], kind="stable", na_position="last")
            numeric = pd.to_numeric(selected["value"], errors="coerce").dropna()
            if numeric.empty:
                return {}, f"missing_{metric}_value"
            values[metric] = float(numeric.iloc[-1])
        observations[key] = {
            "values": values,
            "currency": next(iter(currencies)),
            "accounting_scope": next(iter(scopes)),
            "period_end": next(iter(period_ends)),
        }
    return observations, ""


def _comparison_value(metric: str, values: Mapping[str, float]) -> float | None:
    components = _PEER_COMPONENTS.get(metric)
    if not components or any(name not in values for name in components):
        return None
    if metric == "accrual_ratio":
        numerator = values["net_income"] - values["cash_from_operations"]
        denominator = values["assets"]
    else:
        numerator, denominator = (values[name] for name in components)
    return None if denominator in (0, None) else float(numerator / denominator)


def _comparable_peer_percentile(
    metric: str,
    observed: object,
    target_frame: pd.DataFrame,
    peer_frame: pd.DataFrame | None,
) -> dict[str, object]:
    components = _PEER_COMPONENTS.get(metric)
    if components is None:
        return {"status": "unavailable", "reason": "metric_comparison_not_defined"}
    target_observations, reason = _period_observations(target_frame, components)
    if reason:
        return {"status": "unavailable", "reason": f"target_{reason}"}
    target_basis = max(target_observations, key=lambda key: str(target_observations[key]["period_end"]))
    target = target_observations[target_basis]
    target_value = _comparison_value(metric, target["values"])
    supplied_value = _float(observed)
    if target_value is None or supplied_value is None or not math.isclose(target_value, supplied_value, rel_tol=1e-9, abs_tol=1e-12):
        return {"status": "unavailable", "reason": "target_metric_period_mismatch", "period_basis": target_basis}
    if not isinstance(peer_frame, pd.DataFrame) or peer_frame.empty or "instrument_id" not in peer_frame.columns:
        return {"status": "unavailable", "reason": "peer_statement_evidence_unavailable", "period_basis": target_basis}
    peer_ids = sorted({str(value) for value in peer_frame["instrument_id"].dropna() if str(value) and str(value) != str(target_frame["instrument_id"].iloc[0] if "instrument_id" in target_frame.columns and not target_frame.empty else "")})
    if not peer_ids:
        return {"status": "unavailable", "reason": "peer_identity_unavailable", "period_basis": target_basis}
    values = []
    for peer_id in peer_ids:
        observations, peer_reason = _period_observations(peer_frame[peer_frame["instrument_id"].astype(str).eq(peer_id)], components)
        if peer_reason or target_basis not in observations:
            return {"status": "unavailable", "reason": f"peer_{peer_reason or 'period_basis_mismatch'}", "period_basis": target_basis, "peer_id": peer_id}
        peer = observations[target_basis]
        if peer["currency"] != target["currency"]:
            return {"status": "unavailable", "reason": "peer_currency_mismatch", "period_basis": target_basis, "peer_id": peer_id}
        if peer["accounting_scope"] != target["accounting_scope"]:
            return {"status": "unavailable", "reason": "peer_accounting_scope_mismatch", "period_basis": target_basis, "peer_id": peer_id}
        peer_value = _comparison_value(metric, peer["values"])
        if peer_value is None:
            return {"status": "unavailable", "reason": "peer_denominator_unavailable", "period_basis": target_basis, "peer_id": peer_id}
        values.append(peer_value)
    percentile = float(100.0 * (sum(value < target_value for value in values) + 0.5 * sum(value == target_value for value in values)) / len(values))
    return {"status": "available", "reason": "comparable_peer_statements", "percentile": percentile, "support": len(values), "period_basis": target_basis, "currency": target["currency"], "accounting_scope": target["accounting_scope"]}


def _latest_comparable_value(frame: pd.DataFrame, metric: str, components: tuple[str, ...]) -> tuple[float | None, str]:
    observations, reason = _period_observations(frame, components)
    if reason:
        return None, reason
    basis = max(observations, key=lambda key: str(observations[key]["period_end"]))
    values = observations[basis]["values"]
    if metric == "roic":
        pre_tax = values.get("income_before_tax")
        tax_expense = values.get("tax_expense")
        debt = values.get("debt")
        cash = values.get("cash")
        equity = values.get("equity")
        operating_income = values.get("operating_income")
        if pre_tax in (None, 0) or tax_expense is None or debt is None or cash is None or equity is None or operating_income is None:
            return None, "roic_inputs_unavailable"
        invested_capital = equity + debt - cash
        return (None, "roic_denominator_zero") if invested_capital == 0 else (float(operating_income * (1.0 - tax_expense / pre_tax) / invested_capital), "")
    if metric == "net_debt":
        debt = values.get(components[0])
        cash = values.get("cash")
        return (None, "net_debt_inputs_unavailable") if debt is None or cash is None else (float(debt - cash), "")
    if metric == "working_capital":
        assets = values.get("current_assets")
        liabilities = values.get("current_liabilities")
        return (None, "working_capital_inputs_unavailable") if assets is None or liabilities is None else (float(assets - liabilities), "")
    if metric == "quick_ratio":
        cash = values.get("cash")
        receivables = values.get("receivables")
        current_liabilities = values.get("current_liabilities")
        if cash is None or receivables is None or current_liabilities in (None, 0):
            return None, "quick_ratio_inputs_unavailable"
        return float((cash + receivables) / current_liabilities), ""
    if metric == "altman_like_distress":
        current_assets = values.get("current_assets")
        current_liabilities = values.get("current_liabilities")
        assets = values.get("assets")
        retained_earnings = values.get("retained_earnings")
        operating_income = values.get("operating_income")
        equity = values.get("equity")
        liabilities = values.get("liabilities")
        revenue = values.get("revenue")
        if any(value is None for value in (current_assets, current_liabilities, assets, retained_earnings, operating_income, equity, liabilities, revenue)) or assets == 0 or liabilities == 0:
            return None, "distress_inputs_unavailable"
        working_capital = current_assets - current_liabilities
        return float(1.2 * working_capital / assets + 1.4 * retained_earnings / assets + 3.3 * operating_income / assets + 0.6 * equity / liabilities + revenue / assets), ""
    value = _comparison_value_from_components(components, values)
    return value, "" if value is not None else "ratio_denominator_unavailable"


def _comparable_ratio_history(frame: pd.DataFrame, components: tuple[str, ...]) -> dict[str, object]:
    observations, reason = _period_observations(frame, components)
    if reason:
        return {"status": "unavailable", "reason": reason, "values": []}
    latest = max(observations, key=lambda key: str(observations[key]["period_end"]))
    latest_type = latest[0]
    periods = {key: value for key, value in observations.items() if key[0] == latest_type}
    currency = {str(value["currency"]) for value in periods.values()}
    scopes = {str(value["accounting_scope"]) for value in periods.values()}
    if len(currency) != 1:
        return {"status": "unavailable", "reason": "currency_changes_across_trend_window", "values": []}
    if len(scopes) != 1:
        return {"status": "unavailable", "reason": "accounting_scope_changes_across_trend_window", "values": []}
    ordered = sorted(periods.items(), key=lambda item: str(item[1]["period_end"]))
    if latest_type == "annual":
        years = [int(key[1]) for key, _ in ordered if key[1].isdigit()]
        if len(years) > 1 and any(right - left != 1 for left, right in zip(years, years[1:])):
            return {"status": "unavailable", "reason": "missing_intermediate_period", "values": []}
    values = [value for _, item in ordered if (value := _comparison_value_from_components(components, item["values"])) is not None]
    status = "available" if len(values) >= 2 else "unavailable"
    return {"status": status, "reason": "comparable_periods" if status == "available" else "insufficient_comparable_periods", "values": values if status == "available" else [], "currency": next(iter(currency)), "accounting_scope": next(iter(scopes)), "period_type": latest_type, "periods": len(values)}


def _comparable_metric_history(frame: pd.DataFrame, metric: str) -> dict[str, object]:
    observations, reason = _period_observations(frame, (metric,))
    if reason:
        return {"status": "unavailable", "reason": reason, "values": []}
    latest = max(observations, key=lambda key: str(observations[key]["period_end"]))
    latest_type = latest[0]
    periods = {key: item for key, item in observations.items() if key[0] == latest_type}
    currencies = {str(item["currency"]) for item in periods.values()}
    scopes = {str(item["accounting_scope"]) for item in periods.values()}
    if len(currencies) != 1:
        return {"status": "unavailable", "reason": "currency_changes_across_trend_window", "values": []}
    if len(scopes) != 1:
        return {"status": "unavailable", "reason": "accounting_scope_changes_across_trend_window", "values": []}
    ordered = sorted(periods.items(), key=lambda item: str(item[1]["period_end"]))
    if latest_type == "annual":
        years = [int(key[1]) for key, _ in ordered if key[1].isdigit()]
        if len(years) > 1 and any(right - left != 1 for left, right in zip(years, years[1:])):
            return {"status": "unavailable", "reason": "missing_intermediate_period", "values": []}
    values = [float(item["values"][metric]) for _, item in ordered]
    status = "available" if len(values) >= 2 else "unavailable"
    return {"status": status, "reason": "comparable_periods" if status == "available" else "insufficient_comparable_periods", "values": values if status == "available" else [], "currency": next(iter(currencies)), "accounting_scope": next(iter(scopes)), "period_type": latest_type, "periods": len(values)}


def _apply_growth_comparability(frame: pd.DataFrame, series: dict[str, object]) -> None:
    history = series.get("history")
    points = [point for point in history if isinstance(point, Mapping) and point.get("value") is not None] if isinstance(history, list) else []
    if len(points) < 2:
        reason = "insufficient_comparable_periods"
        series["comparability"] = {"status": "unavailable", "reason": reason, "execution_allowed": False}
        series["growth"] = []
        series["latest_growth"] = {"status": "unavailable", "value": None, "reason": reason, "execution_allowed": False}
        return
    signatures: set[tuple[str, str]] = set()
    for point in points:
        rows = frame[
            frame.get("period_type", pd.Series(index=frame.index, dtype="object")).astype(str).eq(str(point.get("period_type")))
            & frame.get("period_key", pd.Series(index=frame.index, dtype="object")).astype(str).eq(str(point.get("period_key")))
            & frame.get("period_end", pd.Series(index=frame.index, dtype="object")).astype(str).eq(str(point.get("period_end")))
        ]
        currencies = {_text(value).upper() for value in rows.get("currency", pd.Series(dtype="object")).tolist() if _text(value)}
        scopes = {_accounting_scope(record) for record in rows.to_dict("records") if _accounting_scope(record)}
        if not currencies:
            reason = "currency_unavailable"
            break
        if len(currencies) != 1:
            reason = "currency_mismatch"
            break
        if not scopes:
            reason = "accounting_scope_unavailable"
            break
        if len(scopes) != 1:
            reason = "accounting_scope_mismatch"
            break
        signatures.add((next(iter(currencies)), next(iter(scopes))))
    else:
        reason = ""
    if reason or len(signatures) != 1:
        reason = reason or "currency_or_scope_changes_across_trend_window"
        series["comparability"] = {"status": "unavailable", "reason": reason, "execution_allowed": False}
        series["history"] = []
        series["growth"] = []
        series["latest_growth"] = {"status": "unavailable", "value": None, "reason": reason, "execution_allowed": False}
        series["status"] = "unavailable"
        return
    currency, scope = next(iter(signatures))
    series["comparability"] = {"status": "available", "currency": currency, "accounting_scope": scope, "periods": len(points), "execution_allowed": False}


def _comparison_value_from_components(components: tuple[str, ...], values: Mapping[str, float]) -> float | None:
    if len(components) == 2:
        numerator, denominator = (values.get(name) for name in components)
        return None if numerator is None or denominator in (None, 0) else float(numerator / denominator)
    if components == ("net_income", "cash_from_operations", "assets"):
        net_income = values.get("net_income")
        cash_from_operations = values.get("cash_from_operations")
        assets = values.get("assets")
        return None if net_income is None or cash_from_operations is None or assets in (None, 0) else float((net_income - cash_from_operations) / assets)
    return None


def _quality_components(values: Mapping[str, float], histories: Mapping[str, list[float]]) -> dict[str, object]:
    components: dict[str, object] = {}
    for name, value in {
        "positive_net_income": values.get("net_income"),
        "positive_cash_from_operations": values.get("cash_from_operations"),
        "lower_leverage": _trend(histories.get("debt", []), descending=True),
        "improving_gross_margin": _trend(_derived_history(histories, "gross_profit", "revenue"), descending=False),
    }.items():
        components[name] = {"value": value if isinstance(value, bool) else value > 0 if isinstance(value, (int, float)) else value, "status": "available" if value is not None else "missing", "execution_allowed": False}
    return components


def _trend(values: list[float], *, descending: bool) -> bool | None:
    if len(values) < 2:
        return None
    return values[-1] < values[0] if descending else values[-1] > values[0]


def _maturity_timeline(values: Mapping[str, float], frame: pd.DataFrame) -> dict[str, object]:
    names = ("debt_due_1y", "debt_due_2_3y", "debt_due_4_5y", "debt_due_5y_plus")
    available = {name: values[name] for name in names if name in values}
    limitations = [] if available else ["Debt maturity schedules are unavailable; missing buckets are not treated as zero or as favourable evidence."]
    return {"status": "available" if available else "missing", "buckets": available, "formula": "reported debt maturity buckets", "source_ids": sorted({source for name in available for source in _source_ids(frame, name)}), "confidence": "high" if available else "low", "limitation": "; ".join(limitations), "coverage_limitations": limitations, "value_kind": "reported", "execution_allowed": False}


def _distress_metric(values: Mapping[str, float], frame: pd.DataFrame, special: bool) -> dict[str, object]:
    if special:
        return _metric("altman_like_distress", None, "sector adapter required", frame, status_override="not_applicable", limitation="Altman-like industrial evidence is not applied to banks or insurers.")
    assets = values.get("assets")
    liabilities = values.get("liabilities")
    revenue = values.get("revenue")
    equity = values.get("equity")
    operating_income = values.get("operating_income")
    working_capital = None if values.get("current_assets") is None or values.get("current_liabilities") is None else values["current_assets"] - values["current_liabilities"]
    required = (working_capital, assets, values.get("retained_earnings"), operating_income, equity, liabilities, revenue)
    if any(value is None or assets == 0 or liabilities == 0 for value in required):
        return _metric("altman_like_distress", None, "transparent multi-factor distress evidence", frame, status_override="missing", limitation="All disclosed components are required; result is contextual, not a rating.")
    score = 1.2 * working_capital / assets + 1.4 * values["retained_earnings"] / assets + 3.3 * operating_income / assets + 0.6 * equity / liabilities + revenue / assets
    return _metric("altman_like_distress", score, "1.2*WC/assets + 1.4*retained_earnings/assets + 3.3*EBIT/assets + 0.6*equity/liabilities + revenue/assets", frame, limitation="Contextual distress evidence only; no credit-rating claim.")


def _stress_scenarios(values: Mapping[str, float], frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    revenue = values.get("revenue")
    operating_income = values.get("operating_income")
    debt = values.get("debt")
    interest = values.get("interest_expense")
    margin = None if revenue in (None, 0) or operating_income is None else operating_income / revenue
    scenarios: dict[str, dict[str, object]] = {}
    for name, revenue_factor, rate_add in (("revenue_down_20", 0.8, 0.0), ("refinance_rate_up_200bp", 1.0, 0.02)):
        if revenue is None or margin is None or interest is None or debt is None:
            scenarios[name] = {"status": "missing", "confidence": "low", "assumptions": {"revenue_factor": revenue_factor, "rate_add": rate_add}, "execution_allowed": False}
            continue
        stressed_revenue = revenue * revenue_factor
        stressed_operating_income = stressed_revenue * margin
        stressed_interest = interest + debt * rate_add
        scenarios[name] = {"status": "available", "confidence": "scenario_only", "assumptions": {"revenue_factor": revenue_factor, "rate_add": rate_add}, "stressed_revenue": stressed_revenue, "stressed_operating_income": stressed_operating_income, "stressed_interest": stressed_interest, "interest_coverage": None if stressed_interest == 0 else stressed_operating_income / stressed_interest, "execution_allowed": False}
    return scenarios


def _intrinsic_value(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    fcf = values.get("free_cash_flow")
    shares = values.get("shares_outstanding")
    net_debt = values.get("net_debt")
    discount = _float(assumptions.get("discount_rate"))
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = _forecast_years(assumptions)
    scenarios = assumptions.get("scenarios")
    if fcf is None or shares is None or shares <= 0 or net_debt is None or discount is None or terminal_growth is None or years <= 0 or discount <= terminal_growth or discount <= -1.0 or terminal_growth <= -1.0 or not isinstance(scenarios, Mapping) or not scenarios:
        return {"status": "unavailable", "confidence": "low", "reason": "free cash flow, share count, net debt, forecast and explicit scenario assumptions are required", "scenarios": {}, "execution_allowed": False}
    results: dict[str, dict[str, object]] = {}
    for name, raw in scenarios.items():
        growth = _float(raw.get("growth")) if isinstance(raw, Mapping) else None
        if growth is None or growth <= -1.0:
            continue
        margin = _float(raw.get("margin"))
        per_share = _dcf_per_share(values, growth, margin, discount, terminal_growth, years)
        if per_share is None:
            continue
        forecast_path = [fcf * (1.0 + growth) ** year for year in range(1, years + 1)] if margin is None else [float(values["revenue"]) * margin * (1.0 + growth) ** year for year in range(1, years + 1)]
        enterprise_value = _dcf_enterprise_value(forecast_path, discount, terminal_growth)
        if enterprise_value is None:
            continue
        equity_value = enterprise_value - net_debt
        results[str(name)] = {"growth": growth, "margin": margin, "margin_basis": "free_cash_flow_margin" if margin is not None else "reported_free_cash_flow", "growth_path": forecast_path, "enterprise_value": enterprise_value, "equity_value": equity_value, "per_share": per_share, "confidence": "scenario_only", "execution_allowed": False}
    if not results:
        return {"status": "unavailable", "confidence": "low", "reason": "no valid scenario assumptions", "scenarios": {}, "execution_allowed": False}
    per_share_values = [float(item["per_share"]) for item in results.values()]
    return {"status": "available", "confidence": "scenario_only", "forecast_years": years, "discount_rate": discount, "terminal_growth": terminal_growth, "scenarios": results, "range": [min(per_share_values), max(per_share_values)], "execution_allowed": False}


def _reverse_dcf(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    target = values.get("market_cap")
    fcf = values.get("free_cash_flow")
    shares = values.get("shares_outstanding")
    net_debt = values.get("net_debt")
    discount = _float(assumptions.get("discount_rate"))
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = _forecast_years(assumptions)
    if target is None or fcf is None or fcf <= 0 or shares is None or shares <= 0 or net_debt is None or discount is None or terminal_growth is None or years <= 0 or discount <= terminal_growth or discount <= -1.0 or terminal_growth <= -1.0:
        return {"status": "unavailable", "confidence": "low", "reason": "positive FCF, market value, diluted share count, net debt and explicit bounded assumptions are required", "execution_allowed": False}
    def equity_for(growth: float) -> float:
        return float(_dcf_per_share(values, growth, None, discount, terminal_growth, years) * shares) if _dcf_per_share(values, growth, None, discount, terminal_growth, years) is not None else math.nan
    low, high = -0.5, 1.0
    try:
        lower_value, upper_value = equity_for(low), equity_for(high)
    except (ArithmeticError, OverflowError, ValueError):
        lower_value, upper_value = math.nan, math.nan
    if not math.isfinite(lower_value) or not math.isfinite(upper_value) or not (lower_value <= target <= upper_value):
        return {"status": "unavailable", "confidence": "low", "reason": "market value is outside the bounded growth search", "execution_allowed": False}
    for _ in range(80):
        middle = (low + high) / 2.0
        middle_value = equity_for(middle)
        if not math.isfinite(middle_value):
            return {"status": "unavailable", "confidence": "low", "reason": "bounded growth search produced a nonfinite value", "execution_allowed": False}
        if middle_value < target:
            low = middle
        else:
            high = middle
    return {"status": "available", "confidence": "scenario_only", "implied_growth": (low + high) / 2.0, "target_equity_value": target, "execution_allowed": False}


def _residual_income(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    book = values.get("equity")
    net_income = values.get("net_income")
    shares = values.get("shares_outstanding")
    cost = _float(assumptions.get("cost_of_equity", assumptions.get("discount_rate")))
    growth = _float(assumptions.get("terminal_growth"))
    years = _forecast_years(assumptions)
    if book is None or net_income is None or shares is None or shares <= 0 or cost is None or growth is None or years <= 0 or cost <= growth or cost <= -1.0 or growth <= -1.0:
        return {"status": "unavailable", "confidence": "low", "reason": "book equity, net income, diluted share count and explicit cost-of-equity/terminal assumptions are required", "execution_allowed": False}
    try:
        value = book
        residual = net_income - cost * book
        for year in range(1, years + 1):
            value += residual * (1.0 + growth) ** (year - 1) / (1.0 + cost) ** year
        terminal = residual * (1.0 + growth) ** years / (cost - growth)
        value += terminal / (1.0 + cost) ** years
    except (ArithmeticError, OverflowError, ValueError):
        return {"status": "unavailable", "confidence": "low", "reason": "residual-income calculation produced an invalid value", "execution_allowed": False}
    if not math.isfinite(value):
        return {"status": "unavailable", "confidence": "low", "reason": "residual-income calculation produced a nonfinite value", "execution_allowed": False}
    return {"status": "available", "confidence": "scenario_only", "equity_value": value, "per_share": value / shares, "cost_of_equity": cost, "terminal_growth": growth, "forecast_years": years, "net_income_basis": values.get("net_income_basis", "latest_reported_net_income"), "execution_allowed": False}


def _valuation_inputs_comparable(
    frame: pd.DataFrame,
    metrics: tuple[str, ...],
    market_inputs: Mapping[str, object],
    *,
    net_debt: bool = False,
) -> dict[str, str]:
    if frame.empty or not {"canonical_metric", "period_end", "currency"}.issubset(frame.columns):
        return {"status": "unavailable", "reason": "Statement period, currency and accounting-scope lineage are required for comparable valuation."}
    periods: set[str] = set()
    currencies: set[str] = set()
    scopes: set[str] = set()
    for metric in metrics:
        rows = frame.loc[frame["canonical_metric"].astype(str).eq(metric)].copy()
        if rows.empty or rows["period_end"].isna().all():
            return {"status": "unavailable", "reason": f"{metric} period is unavailable; comparable valuation is withheld."}
        sort_columns = ["period_end", "filed"] if "filed" in rows else ["period_end"]
        rows = rows.sort_values(sort_columns, kind="stable", na_position="last")
        latest_period = str(rows.iloc[-1]["period_end"])
        selected = rows.loc[rows["period_end"].astype(str).eq(latest_period)]
        if selected["currency"].isna().any():
            return {"status": "unavailable", "reason": f"{metric} currency is unavailable; comparable valuation is withheld."}
        currencies.update(str(value).strip().upper() for value in selected["currency"] if str(value).strip())
        scopes.update(_accounting_scope(row) for row in selected.to_dict("records") if _accounting_scope(row))
        periods.add(latest_period)
    if len(periods) != 1:
        return {"status": "unavailable", "reason": "Selected statement metrics do not share one reporting period."}
    if len(currencies) != 1 or len(scopes) != 1:
        return {"status": "unavailable", "reason": "Selected statement metrics have mixed or unavailable currency/accounting scope."}
    reporting_currency = _text(market_inputs.get("reporting_currency")).upper()
    if reporting_currency and reporting_currency not in currencies:
        return {"status": "unavailable", "reason": "Market and statement reporting currencies do not match."}
    statement_period = next(iter(periods))
    if market_inputs.get("shares_outstanding") is not None or market_inputs.get("market_cap") is not None:
        share_period = _text(market_inputs.get("share_count_period_end"))
        if not share_period or share_period != statement_period:
            return {"status": "unavailable", "reason": "Diluted share-count vintage does not match the selected statement period."}
    if net_debt and market_inputs.get("net_debt") is not None:
        debt_period = _text(market_inputs.get("net_debt_period_end"))
        if not debt_period or debt_period != statement_period:
            return {"status": "unavailable", "reason": "Net-debt vintage does not match the selected statement period."}
    if net_debt and market_inputs.get("enterprise_value") is not None:
        adjustment_status = market_inputs.get("enterprise_value_adjustments", {})
        if isinstance(adjustment_status, Mapping) and adjustment_status.get("status") != "available":
            return {"status": "unavailable", "reason": "Enterprise-value adjustment coverage is incomplete."}
    return {"status": "available", "reason": "Selected values share a period, reporting currency and accounting scope."}


def _mark_valuation_metric_unavailable(metric: Mapping[str, object], reason: str) -> dict[str, object]:
    return {**metric, "value": None, "status": "unavailable", "confidence": "low", "limitation": reason}


def _forecast_years(assumptions: Mapping[str, object]) -> int:
    value = assumptions.get("forecast_years")
    if isinstance(value, bool):
        return 0
    try:
        years = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    try:
        return years if float(value or 0) == years and 0 < years <= 100 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _peer_relative_valuation_metrics(
    statements: pd.DataFrame,
    peer_frame: pd.DataFrame | None,
    peer_market_inputs: Mapping[str, Mapping[str, object]],
    *,
    as_known_at: str | date | None,
    instrument_id: str | None,
    bank_route: bool,
) -> dict[str, object]:
    peer_statements = _statement_frame(peer_frame, None, as_known_at=as_known_at) if isinstance(peer_frame, pd.DataFrame) else pd.DataFrame()
    peer_ids = sorted({str(value) for value in peer_statements.get("instrument_id", pd.Series(dtype="object")).dropna() if str(value) and str(value) != str(instrument_id or "")})
    names = ("price_to_earnings", "price_to_book", "price_to_tangible_book") if bank_route else ("ev_to_sales", "ev_to_ebitda", "price_to_earnings", "price_to_book")
    denominators = {
        "ev_to_sales": ("enterprise_value", "revenue"),
        "ev_to_ebitda": ("enterprise_value", "ebitda"),
        "price_to_earnings": ("market_cap", "net_income"),
        "price_to_book": ("market_cap", "equity"),
        "price_to_tangible_book": ("market_cap", "tangible_book_value"),
    }
    observed: dict[str, list[dict[str, object]]] = {name: [] for name in names}
    missing: dict[str, list[str]] = {name: [] for name in names}
    for peer_id in peer_ids:
        facts = _statement_frame(peer_statements, peer_id, as_known_at=as_known_at)
        market = peer_market_inputs.get(peer_id)
        if not facts.empty and isinstance(market, Mapping) and market.get("status") in {"available", "available_with_warning"}:
            currencies = {_text(item).upper() for item in facts.get("currency", pd.Series(dtype="object")).dropna() if _text(item)}
            scopes = {_accounting_scope(row) for row in facts.to_dict("records") if _accounting_scope(row)}
            reporting_currency = _text(market.get("reporting_currency")).upper()
            if len(currencies) == 1 and reporting_currency in currencies and len(scopes) == 1:
                values = _latest_values(facts)
                for name in names:
                    numerator_name, denominator_name = denominators[name]
                    numerator = _float(market.get(numerator_name))
                    denominator = _float(values.get(denominator_name))
                    if numerator is None or denominator is None or denominator <= 0:
                        missing[name].append(peer_id)
                        continue
                    period_rows = facts.loc[facts["canonical_metric"].astype(str).eq(denominator_name)]
                    period = _text(period_rows.sort_values("period_end", kind="stable").iloc[-1].get("period_end")) if not period_rows.empty and "period_end" in period_rows else "unavailable"
                    observed[name].append({"instrument_id": peer_id, "value": numerator / denominator, "period": period, "currency": reporting_currency, "accounting_scope": next(iter(scopes)), "market_price_timestamp": market.get("price_timestamp"), "filing_vintage": market.get("filing_vintage", [])})
                    continue
        for name in names:
            missing[name].append(peer_id)
    metrics: dict[str, object] = {}
    for name in names:
        items = observed[name]
        numbers = [float(item["value"]) for item in items]
        metrics[name] = {
            "status": "available" if numbers else "unavailable",
            "median": float(pd.Series(numbers).median()) if numbers else None,
            "range": [min(numbers), max(numbers)] if numbers else [],
            "peer_count": len(items),
            "peer_values": items,
            "missing_peer_ids": sorted(set(missing[name])),
            "formula": denominators[name][0] + " / " + denominators[name][1],
            "outlier_treatment": "All available peer values are retained; median and range are reported without winsorisation or clipping.",
        }
    return {
        "status": "available" if any(item["status"] == "available" for item in metrics.values()) else "unavailable",
        "peer_ids": peer_ids,
        "metrics": metrics,
        "period_basis": "Each peer's latest then-known denominator period is disclosed per value; no synthetic common period is assigned.",
        "currency_basis": "Each multiple is calculated within the peer's reporting currency; missing or mixed currency evidence excludes that peer.",
        "accounting_scope": "A peer is included only when its available statement scope is unique.",
        "execution_allowed": False,
    }


def _dcf_per_share(
    values: Mapping[str, float], growth: float, margin: float | None,
    discount: float, terminal_growth: float, years: int,
) -> float | None:
    shares, net_debt, fcf = values.get("shares_outstanding"), values.get("net_debt"), values.get("free_cash_flow")
    if shares is None or shares <= 0 or net_debt is None or fcf is None or discount <= terminal_growth or discount <= -1.0 or terminal_growth <= -1.0 or growth <= -1.0:
        return None
    if margin is not None and values.get("revenue") is None:
        return None
    base_cash_flow = fcf if margin is None else values["revenue"] * margin
    try:
        path = [base_cash_flow * (1.0 + growth) ** year for year in range(1, years + 1)]
    except (ArithmeticError, OverflowError, ValueError):
        return None
    enterprise_value = _dcf_enterprise_value(path, discount, terminal_growth)
    if enterprise_value is None:
        return None
    result = (enterprise_value - net_debt) / shares
    return result if math.isfinite(result) else None


def _dcf_enterprise_value(path: list[float], discount: float, terminal_growth: float) -> float | None:
    if not path or discount <= terminal_growth or discount <= -1.0:
        return None
    try:
        present_value = sum(value / (1.0 + discount) ** year for year, value in enumerate(path, 1))
        terminal = path[-1] * (1.0 + terminal_growth) / (discount - terminal_growth)
        value = present_value + terminal / (1.0 + discount) ** len(path)
    except (ArithmeticError, OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _valuation_sensitivity(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    raw = assumptions.get("sensitivity")
    years = _forecast_years(assumptions)
    if not isinstance(raw, Mapping):
        return {"status": "unavailable", "reason": "explicit discount-rate and terminal-growth sensitivity ranges are required", "grid": {}, "execution_allowed": False}
    discounts = raw.get("discount_rates")
    terminals = raw.get("terminal_growth_rates")
    scenarios = assumptions.get("scenarios")
    if not isinstance(discounts, (tuple, list)) or not isinstance(terminals, (tuple, list)) or not isinstance(scenarios, Mapping) or years <= 0:
        return {"status": "unavailable", "reason": "explicit sensitivity ranges and DCF scenario assumptions are required", "grid": {}, "execution_allowed": False}
    discount_values = [_float(value) for value in discounts]
    terminal_values = [_float(value) for value in terminals]
    if len(discount_values) < 2 or len(terminal_values) < 2 or any(value is None for value in (*discount_values, *terminal_values)):
        return {"status": "unavailable", "reason": "sensitivity ranges need at least two finite values for each rate", "grid": {}, "execution_allowed": False}
    grid: dict[str, object] = {}
    for name, raw_scenario in scenarios.items():
        if not isinstance(raw_scenario, Mapping):
            continue
        growth = _float(raw_scenario.get("growth"))
        margin = _float(raw_scenario.get("margin"))
        if growth is None:
            continue
        cells = []
        outputs = []
        for discount in discount_values:
            for terminal in terminal_values:
                if discount is None or terminal is None:
                    continue
                per_share = _dcf_per_share(values, growth, margin, discount, terminal, years)
                cell = {"discount_rate": discount, "terminal_growth": terminal, "per_share": per_share, "status": "available" if per_share is not None else "unavailable"}
                cells.append(cell)
                if per_share is not None:
                    outputs.append(per_share)
        grid[str(name)] = {"cells": cells, "range": [min(outputs), max(outputs)] if outputs else [], "status": "available" if outputs else "unavailable"}
    return {"status": "available" if any(item.get("status") == "available" for item in grid.values()) else "unavailable", "grid": grid, "execution_allowed": False}


def _residual_income_sensitivity(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    raw = assumptions.get("sensitivity")
    if not isinstance(raw, Mapping):
        return {"status": "unavailable", "reason": "Explicit cost-of-equity, terminal-growth and sustainable-ROE/ROTE ranges are required.", "grid": [], "execution_allowed": False}
    costs = raw.get("cost_of_equity_rates", raw.get("discount_rates"))
    terminal_rates = raw.get("terminal_growth_rates")
    roe_rates = raw.get("sustainable_roe_rates")
    rote_rates = raw.get("sustainable_rote_rates")
    return_rates = roe_rates if isinstance(roe_rates, (tuple, list)) and len(roe_rates) >= 2 else rote_rates
    if not isinstance(costs, (tuple, list)) or len(costs) < 2 or not isinstance(terminal_rates, (tuple, list)) or len(terminal_rates) < 2 or not isinstance(return_rates, (tuple, list)) or len(return_rates) < 2:
        return {"status": "unavailable", "reason": "Sensitivity needs at least two explicit values for cost of equity, terminal growth and sustainable ROE or ROTE.", "grid": [], "execution_allowed": False}
    cost_values = [_float(value) for value in costs]
    terminal_values = [_float(value) for value in terminal_rates]
    return_values = [_float(value) for value in return_rates]
    if any(value is None for value in (*cost_values, *terminal_values, *return_values)):
        return {"status": "unavailable", "reason": "Sensitivity assumptions must be finite numeric values.", "grid": [], "execution_allowed": False}
    uses_roe = return_rates is roe_rates
    grid = []
    outputs = []
    for sustainable_return in return_values:
        for cost in cost_values:
            for terminal in terminal_values:
                scenario_values = dict(values)
                if uses_roe and scenario_values.get("equity") is not None:
                    scenario_values["net_income"] = scenario_values["equity"] * sustainable_return
                    basis = "sustainable_roe"
                elif not uses_roe and scenario_values.get("tangible_book_value") is not None:
                    scenario_values["net_income"] = scenario_values["tangible_book_value"] * sustainable_return
                    basis = "sustainable_rote"
                else:
                    continue
                result = _residual_income(scenario_values, {**assumptions, "cost_of_equity": cost, "terminal_growth": terminal})
                per_share = _float(result.get("per_share"))
                cell = {"return_basis": basis, "sustainable_return": sustainable_return, "cost_of_equity": cost, "terminal_growth": terminal, "per_share": per_share, "status": result.get("status", "unavailable")}
                grid.append(cell)
                if per_share is not None:
                    outputs.append(per_share)
    return {"status": "available" if outputs else "unavailable", "grid": grid, "range": [min(outputs), max(outputs)] if outputs else [], "execution_allowed": False}


def _not_applicable_valuation(reason: str) -> dict[str, object]:
    return {"status": "not_applicable", "confidence": "low", "reason": reason, "execution_allowed": False}


def _projection_member(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _financial_projection_payload(projection: object | None) -> dict[str, object]:
    if projection is None:
        return {}
    if hasattr(projection, "__dataclass_fields__"):
        return asdict(projection)
    return dict(projection) if isinstance(projection, Mapping) else {}


def _financial_projection_metrics(projection: object | None) -> dict[str, float]:
    raw_metrics = _projection_member(projection, "metrics", ())
    if isinstance(raw_metrics, Mapping):
        rows = raw_metrics.items()
    elif isinstance(raw_metrics, (tuple, list)):
        rows = ((_projection_member(item, "metric"), item) for item in raw_metrics)
    else:
        return {}
    result: dict[str, float] = {}
    for name, item in rows:
        if _projection_member(item, "status") not in {None, "available", "calculated"}:
            continue
        value = _float(_projection_member(item, "value"))
        if value is not None:
            result[str(name)] = value
    return result


def _financial_projection_inputs_comparable(
    projection: object | None,
    metric_names: tuple[str, ...],
    *,
    instrument_id: str | None,
    as_known_at: str | date | None,
) -> dict[str, str]:
    unavailable = "Financial-institution projection period, currency and accounting-scope lineage are required for comparable residual income."
    if _projection_member(projection, "status") != "available":
        return {"status": "unavailable", "reason": "Financial-institution projection inputs are unavailable."}
    if instrument_id and _projection_member(projection, "instrument_id") != instrument_id:
        return {"status": "unavailable", "reason": "Financial-institution projection identity does not match the instrument."}
    if _projection_member(projection, "execution_allowed") is not False:
        return {"status": "unavailable", "reason": "Financial-institution projection is not non-executable evidence."}

    lineage = _projection_member(projection, "lineage", {})
    projection_decision = _projection_member(lineage, "decision_time")
    cutoff_value = as_known_at or projection_decision
    cutoff = pd.to_datetime(cutoff_value, errors="coerce", utc=True)
    built_at = pd.to_datetime(projection_decision, errors="coerce", utc=True)
    if pd.isna(cutoff) or pd.isna(built_at) or built_at > cutoff:
        return {"status": "unavailable", "reason": "Financial-institution projection decision-time lineage is missing or outside the valuation cutoff."}

    source_ids = {
        str(value).strip()
        for value in _projection_member(lineage, "sources", ())
        if str(value).strip()
    }
    raw_metrics = _projection_member(projection, "metrics", ())
    if isinstance(raw_metrics, Mapping):
        rows = list(raw_metrics.items())
    elif isinstance(raw_metrics, (tuple, list)):
        rows = [(_projection_member(item, "metric"), item) for item in raw_metrics]
    else:
        return {"status": "unavailable", "reason": unavailable}

    selected: list[dict[str, str]] = []
    for metric_name in metric_names:
        matches = [
            item
            for name, item in rows
            if str(_projection_member(item, "metric", name)) == metric_name
        ]
        if len(matches) != 1:
            return {"status": "unavailable", "reason": f"{metric_name} projection lineage is unavailable; comparable residual income is withheld."}
        item = matches[0]
        if (
            _projection_member(item, "status") not in {"available", "calculated"}
            or _projection_member(item, "execution_allowed") is not False
            or _float(_projection_member(item, "value")) is None
        ):
            return {"status": "unavailable", "reason": f"{metric_name} projection value is unavailable; comparable residual income is withheld."}
        fields = {
            name: str(_projection_member(item, name, "") or "").strip()
            for name in (
                "period",
                "unit",
                "reporting_standard",
                "jurisdiction",
                "business_model",
                "scope",
                "source_id",
                "source_authority",
                "as_of",
                "known_at",
            )
        }
        if any(not fields[name] for name in ("period", "unit", "reporting_standard", "jurisdiction", "business_model", "scope", "source_id", "source_authority", "as_of", "known_at")):
            return {"status": "unavailable", "reason": f"{metric_name} projection lineage is incomplete; comparable residual income is withheld."}
        as_of = pd.to_datetime(fields["as_of"], errors="coerce", utc=True)
        known_at = pd.to_datetime(fields["known_at"], errors="coerce", utc=True)
        if pd.isna(as_of) or pd.isna(known_at) or as_of > cutoff or known_at > cutoff:
            return {"status": "unavailable", "reason": f"{metric_name} projection is outside the valuation decision-time cutoff."}
        if fields["source_id"] not in source_ids:
            return {"status": "unavailable", "reason": f"{metric_name} source is absent from projection lineage."}
        selected.append(fields)

    dimensions = ("period", "unit", "reporting_standard", "jurisdiction", "business_model", "scope")
    if any(len({item[name] for item in selected}) != 1 for name in dimensions):
        return {"status": "unavailable", "reason": "Selected ISSUE-0099 projection inputs have mixed period, currency, or accounting scope."}
    return {"status": "available", "reason": ""}


def _model_disagreement(intrinsic: Mapping[str, object], residual: Mapping[str, object]) -> dict[str, object]:
    values = [result.get("per_share") for result in (intrinsic.get("scenarios", {}) or {}).values() if isinstance(result, Mapping) and result.get("per_share") is not None]
    if residual.get("per_share") is not None:
        values.append(residual["per_share"])
    return {"status": "available" if len(values) >= 2 else "unavailable", "range": [min(values), max(values)] if values else [], "confidence": "scenario_only" if values else "low", "execution_allowed": False}


__all__ = [
    "CONSENSUS_IMPORT_PATH",
    "GUIDANCE_IMPORT_PATH",
    "MetricEvidence",
    "STOCK_RESEARCH_IMPORT_DIR",
    "STOCK_RESEARCH_SCHEMA_VERSION",
    "balance_sheet_analysis",
    "build_stock_research_report",
    "capital_efficiency_analysis",
    "growth_analysis",
    "load_optional_research_import",
    "load_stock_research_frame",
    "profitability_analysis",
    "valuation_analysis",
]
