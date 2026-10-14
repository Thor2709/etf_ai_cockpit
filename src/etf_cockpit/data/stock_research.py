"""Transparent stock research analytics over canonical statement evidence.

The functions in this module deliberately return evidence dictionaries rather
than an action score. Every value carries a formula, period, source coverage
and confidence boundary. Missing inputs remain missing and structurally
inapplicable sectors are not forced through industrial formulas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
import math
from pathlib import Path

import pandas as pd

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.core.atomic_io import sha256_file as _file_sha256
from etf_cockpit.core.paths import RAW_DIR
from etf_cockpit.core.values import finite_float_or_none as _float, mapping_or_attribute as _projection_member
from etf_cockpit.data.capital_efficiency import (
    CostOfCapitalLedger,
    build_cost_of_capital_ledger,
    capital_efficiency_analysis,
    cost_of_capital_sensitivity_grid,
)
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
    "shares_outstanding": ("shares_outstanding",),
    "diluted_shares_outstanding": ("diluted_shares_outstanding", "diluted_shares"),
    "weighted_average_shares": ("weighted_average_shares", "weighted_average_shares_basic", "weighted_shares"),
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
        source_metrics=("gross_profit", "revenue"),
        applicability="not_applicable" if special else "applicable",
        limitation="Financial-institution profitability is delegated to the financial-sector adapter." if special else "",
    )
    metrics["operating_margin"] = _ratio_metric("operating_margin", operating_income, revenue, "operating_income / revenue", frame, "revenue")
    metrics["net_margin"] = _ratio_metric("net_margin", net_income, revenue, "net_income / revenue", frame, "revenue")
    metrics["roa"] = _ratio_metric("roa", net_income, assets, "net_income / assets", frame, "assets")
    metrics["roe"] = _ratio_metric("roe", net_income, equity, "net_income / equity", frame, "equity")
    invested_capital = sm.invested_capital(equity, debt, latest.get("lease_liabilities"), cash)
    roic = None if special else (None if operating_income is None or tax is None else operating_income * (1.0 - tax))
    metrics["roic"] = _ratio_metric(
        "roic",
        roic,
        invested_capital,
        "NOPAT / invested_capital",
        frame,
        "equity",
        applicability="not_applicable" if special else "applicable",
        limitation="Financial-institution profitability is delegated to the financial-sector adapter." if special else "",
    )
    metrics["cash_conversion"] = _ratio_metric(
        "cash_conversion", cfo, net_income, "cash_from_operations / net_income", frame,
        "cash_from_operations", source_metrics=("cash_from_operations", "net_income"), applicability="not_applicable" if special else "applicable",
        limitation="Industrial cash-conversion analysis is not applicable to financial institutions." if special else "",
        zero_denominator_status="not_applicable",
    )
    accrual_numerator = None if net_income is None or cfo is None else net_income - cfo
    metrics["accrual_ratio"] = _ratio_metric(
        "accrual_ratio", accrual_numerator, assets, "(net_income - cash_from_operations) / assets", frame, "assets",
        source_metrics=("net_income", "cash_from_operations", "assets"),
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
    margin_provenance = _history_source_provenance(frame, ("gross_profit", "revenue"))
    metrics["margin_stability"]["source_provenance"] = margin_provenance
    metrics["margin_stability"]["source_ids"] = tuple(
        sorted(
            {
                str(item.get("source_id"))
                for item in margin_provenance
                if _text(item.get("source_id"))
            }
        )
    )
    metrics["margin_stability"]["source_timing_status"] = (
        "available"
        if _source_provenance_is_complete(
            margin_provenance, ("gross_profit", "revenue")
        )
        else "unavailable"
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
            "roic": ("operating_income", "equity", "debt", "cash", "income_before_tax", "tax_expense") + (("lease_liabilities",) if "lease_liabilities" in histories else ()),
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
    metrics["debt_to_equity"] = _ratio_metric("debt_to_equity", debt, equity, f"{debt_name} / equity", frame, debt_name, source_metrics=(debt_name, "equity"), applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "")
    metrics["current_ratio"] = _ratio_metric("current_ratio", current_assets, current_liabilities, "current_assets / current_liabilities", frame, "current_assets", applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "")
    quick_assets = _sum_if_present(cash, receivables)
    metrics["quick_ratio"] = _ratio_metric("quick_ratio", quick_assets, current_liabilities, "(cash + receivables) / current_liabilities", frame, "cash", applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "")
    metrics["working_capital"] = _metric("working_capital", None if special or current_assets is None or current_liabilities is None else current_assets - current_liabilities, "current_assets - current_liabilities", frame, status_override="not_applicable" if special else None, limitation=industrial_reason if special else "")
    metrics["interest_coverage"] = _ratio_metric("interest_coverage", operating_income, interest_expense, "operating_income / interest_expense", frame, "operating_income", source_metrics=("operating_income", "interest_expense"), applicability="not_applicable" if special else "applicable", limitation=industrial_reason if special else "", zero_denominator_status="not_applicable")

    distress = _distress_metric(latest, frame, special)
    metrics["altman_like_distress"] = distress
    maturity = (
        {"status": "not_applicable", "buckets": {}, "formula": "sector adapter required", "source_ids": [], "confidence": "low", "limitation": industrial_reason, "coverage_limitations": [industrial_reason], "execution_allowed": False}
        if special else _maturity_timeline(latest, frame)
    )
    stress = (
        {
            **{name: {"status": "not_applicable", "value": None, "reason": industrial_reason, "execution_allowed": False} for name in ("revenue_down_20", "margin_down_5pp")},
            **_bank_stress_scenarios(latest),
        }
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
    strict_comparability: bool = True,
    sector: str = "",
    classification_context: Mapping[str, object] | None = None,
    peer_frame: pd.DataFrame | None = None,
    peer_market_inputs: Mapping[str, Mapping[str, object]] | None = None,
    financial_projection: object | None = None,
) -> dict[str, object]:
    """Valuation evidence. ``strict_comparability`` defaults to True for every score/recommendation consumer;
    ``strict_comparability=False`` calls are diagnostic only and are labelled so in the output."""

    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    latest = _latest_values(frame)
    market = {str(key): _float(value) for key, value in (market_inputs or {}).items()}
    assumption_values = {str(key): value for key, value in (assumptions or {}).items()}
    values = {**latest, **{key: value for key, value in market.items() if value is not None}}
    for input_name in ("shares_outstanding", "market_cap", "net_debt", "enterprise_value"):
        if input_name in market:
            values[input_name] = market[input_name]
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
    driver = _not_applicable_valuation("Industrial driver DCF is not applicable to financial institutions.") if bank_route else _driver_dcf(values, assumption_values)
    ledger = build_cost_of_capital_ledger(assumption_values)
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
            intrinsic = {"status": "unavailable", "confidence": "low", "reason": str(dcf_basis["reason"]), "scenarios": {}, "score_eligible": False, "execution_allowed": False}
            reverse = {"status": "unavailable", "confidence": "low", "reason": str(dcf_basis["reason"]), "score_eligible": False, "execution_allowed": False}
            driver = {"status": "unavailable", "confidence": "low", "reason": str(dcf_basis["reason"]), "score_eligible": False, "execution_allowed": False}
        if residual_basis["status"] != "available":
            residual = {"status": "unavailable", "confidence": "low", "reason": str(residual_basis["reason"]), "score_eligible": False, "execution_allowed": False}
    sensitivity = _residual_income_sensitivity(values, assumption_values) if bank_route else _valuation_sensitivity(values, assumption_values)
    price_provenance = _market_input_provenance(
        market_inputs or {}, "share_price"
    )
    mos_models: dict[str, dict[str, object]] = {}
    dcf_provenance = _valuation_model_provenance(
        frame,
        latest,
        market_inputs or {},
        assumption_values,
        model="dcf",
        use_margin=any(
            isinstance(item, Mapping) and _float(item.get("margin")) is not None
            for item in (assumption_values.get("scenarios", {}) or {}).values()
        )
        if isinstance(assumption_values.get("scenarios"), Mapping)
        else False,
        financial_projection=financial_projection,
        bank_route=bank_route,
    )
    scenarios = intrinsic.get("scenarios")
    if isinstance(scenarios, dict):
        for scenario_name, scenario in scenarios.items():
            if not isinstance(scenario, dict):
                continue
            mos = _margin_of_safety(
                scenario.get("per_share"),
                market.get("share_price"),
                dcf_provenance,
                price_provenance,
                model=f"dcf:{scenario_name}",
            )
            scenario["margin_of_safety"] = mos
            mos_models[f"dcf:{scenario_name}"] = mos
    residual_provenance = _valuation_model_provenance(
        frame,
        latest,
        market_inputs or {},
        assumption_values,
        model="residual_income",
        financial_projection=financial_projection,
        bank_route=bank_route,
    )
    if driver.get("per_share") is not None:
        driver_mos = _margin_of_safety(driver.get("per_share"), market.get("share_price"), dcf_provenance, price_provenance, model="driver_dcf")
        driver["margin_of_safety"] = driver_mos
        mos_models["driver_dcf"] = driver_mos
    residual_mos = _margin_of_safety(
        residual.get("per_share"),
        market.get("share_price"),
        residual_provenance,
        price_provenance,
        model="residual_income",
    )
    residual["margin_of_safety"] = residual_mos
    mos_models["residual_income"] = residual_mos
    reverse_provenance = _valuation_model_provenance(
        frame,
        latest,
        market_inputs or {},
        assumption_values,
        model="dcf",
        financial_projection=financial_projection,
        bank_route=bank_route,
    )
    reverse_provenance.extend(
        _market_input_provenance(market_inputs or {}, "market_cap")
    )
    if not _source_triplets_complete(reverse_provenance):
        reverse_provenance.append(
            {
                "source_id": None,
                "effective_at": None,
                "known_at": None,
                "canonical_metric": "missing_reverse_dcf_input_provenance",
            }
        )
    reverse["source_provenance"] = reverse_provenance
    reverse_gap = _reverse_dcf_gap(reverse, assumption_values)
    expiry = _valuation_expiry(frame, market, market_inputs or {}, assumption_values, as_known_at)
    eligibility = _score_eligibility(
        {"driver_dcf": driver, "residual_income": residual, "intrinsic_value": intrinsic},
        ledger=ledger, strict_comparability=strict_comparability, expiry=expiry, bank_route=bank_route,
    )
    for model_name, model_result in (("driver_dcf", driver), ("residual_income", residual)):
        mos_entry = mos_models.get(model_name)
        if isinstance(mos_entry, dict):
            mos_entry["score_eligible"] = bool(eligibility["models"].get(model_name, {}).get("score_eligible"))
    for scenario_mos in mos_models:
        if scenario_mos.startswith("dcf:"):
            mos_models[scenario_mos]["score_eligible"] = False
    disagreement = _model_disagreement(
        intrinsic, residual, driver=driver, peer_metrics=peer_relative_metrics, values=values,
    )
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
        "reverse_dcf_gap": reverse_gap,
        "residual_income": residual,
        "margin_of_safety": {
            "status": "available"
            if any(item.get("status") == "available" for item in mos_models.values())
            else "unavailable",
            "models": mos_models,
            "execution_allowed": False,
        },
        "normalized_mid_cycle": {
            "status": "unavailable",
            "reason": "No normalized or mid-cycle earnings evidence was supplied.",
            "execution_allowed": False,
        },
        "sensitivity": sensitivity,
        "bank_route": {"status": "available" if bank_route and adapter_status == "available" else "unavailable" if bank_route else "not_applicable", "path": "ISSUE-0099_fundamental_release" if bank_route else "industrial_dcf", "financial_projection_status": adapter_status, "metrics": bank_metrics},
        "driver_dcf": driver,
        "model_disagreement": disagreement,
        "cost_of_capital": {**ledger.to_dict(), "sensitivity": cost_of_capital_sensitivity_grid(ledger)},
        "score_eligibility": eligibility,
        "expiry": expiry,
        "valuation_status": "provisional" if expiry["status"] == "provisional" else "current",
        "expires_at": expiry["expires_at"],
        "refresh_reason": expiry["refresh_reason"],
        "operator_weights": _operator_weights(assumption_values),
        "comparability_mode": "strict" if strict_comparability else "diagnostic_only",
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
            derived_from=("net_income", "weighted_average_shares"),
            unavailable_reason="weighted-average shares are not reported for the period; period-end shares are not a valid EPS denominator",
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
        cost_of_capital_ledger=build_cost_of_capital_ledger(assumption_values),
        intangible_assumptions=assumption_values.get("intangible_adjustment") if isinstance(assumption_values.get("intangible_adjustment"), Mapping) else None,
        profitability_output=profitability,
        strict_comparability=strict_comparability,
        as_known_at=as_known_at,
    )
    if strict_comparability and not sector_known:
        _mark_capital_efficiency_unavailable(capital_efficiency, "Classification is unavailable or unresolved; industrial capital-efficiency applicability cannot be established.")
    _bind_capital_efficiency_source_provenance(
        capital_efficiency, frame, assumption_values
    )
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
        if "earnings_per_share" not in values and "net_income" in values and values.get("weighted_average_shares") not in (None, 0):
            # EPS divides a period flow by the weighted-average share count of that period. Period-end
            # shares are not a verified denominator for the earnings period, so without a reported EPS or
            # a weighted average the series stays unavailable (see ``unavailable_reason``).
            values["earnings_per_share"] = values["net_income"] / values["weighted_average_shares"]
            sources["earnings_per_share"] = tuple(sorted(set(sources.get("net_income", ())) | set(sources.get("weighted_average_shares", ()))))
            formulas["earnings_per_share"] = "net_income / weighted_average_shares"

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
    unavailable_reason: str | None = None,
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
                **({"reason": unavailable_reason} if value is None and unavailable_reason else {}),
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


def _ratio_metric(name: str, numerator: float | None, denominator: float | None, formula: str, frame: pd.DataFrame, source_metric: str, *, source_metrics: Sequence[str] | None = None, applicability: str = "applicable", limitation: str = "", zero_denominator_status: str = "missing") -> dict[str, object]:
    if applicability != "applicable":
        return _metric(name, None, formula, frame, status_override="not_applicable", source_metric=source_metric, source_metrics=source_metrics, applicability=applicability, limitation=limitation)
    if numerator is None or denominator is None:
        return _metric(name, None, formula, frame, status_override="missing", source_metric=source_metric, source_metrics=source_metrics, limitation=limitation)
    if denominator == 0:
        return _metric(name, None, formula, frame, status_override=zero_denominator_status, source_metric=source_metric, source_metrics=source_metrics, limitation="Denominator is zero; the ratio is not defined.")
    return _metric(name, float(numerator / denominator), formula, frame, source_metric=source_metric, source_metrics=source_metrics, limitation=limitation)


def _metric(name: str, value: float | None, formula: str, frame: pd.DataFrame, *, status_override: str | None = None, source_metric: str | None = None, source_metrics: Sequence[str] | None = None, applicability: str = "applicable", limitation: str = "") -> dict[str, object]:
    source_ids = (
        tuple(sorted({
            source_id
            for metric_name in source_metrics
            for source_id in _source_ids(frame, metric_name)
        }))
        if source_metrics is not None
        else _source_ids(frame, source_metric or name)
    )
    period = _period_label(frame)
    status = status_override or ("missing" if value is None else "negative" if value < 0 else "available")
    result = asdict(MetricEvidence(name, value, status, formula, period, source_ids, "high" if value is not None and source_ids else "low", applicability, limitation))
    result["value_kind"] = "calculated"
    result["evidence"] = _evidence_metadata(frame)
    if source_metrics is not None:
        provenance = _latest_source_provenance(frame, source_metrics)
        result["source_provenance"] = provenance
        result["source_timing_status"] = (
            "available"
            if _source_provenance_is_complete(provenance, source_metrics)
            else "unavailable"
        )
        if result["source_timing_status"] == "unavailable":
            result["source_timing_limitation"] = "Exact selected source timing is incomplete."
    return result


def _latest_source_provenance(
    frame: pd.DataFrame, source_metrics: Sequence[str]
) -> list[dict[str, object]]:
    """Return exact source triplets for the rows backing latest-value metrics."""

    if frame.empty or "canonical_metric" not in frame.columns:
        return []
    ordered = frame.copy()
    for column in ("period_end", "filed", "fiscal_year", "period_key"):
        if column not in ordered:
            ordered[column] = ""
    ordered = ordered.sort_values(
        ["canonical_metric", "period_end", "filed", "fiscal_year", "period_key"],
        kind="stable",
        na_position="last",
    )
    result: list[dict[str, object]] = []
    for metric in dict.fromkeys(source_metrics):
        rows = ordered.loc[ordered["canonical_metric"].astype(str).eq(metric)]
        if rows.empty:
            continue
        numeric = pd.to_numeric(rows["value"], errors="coerce")
        selected = rows.loc[numeric.notna()]
        if selected.empty:
            continue
        row = selected.iloc[-1]
        result.append(
            {
                "source_id": _text(row.get("source_id")) or None,
                "effective_at": _text(row.get("effective_at")) or None,
                "known_at": _text(row.get("known_at")) or None,
                "canonical_metric": metric,
            }
        )
    return result


def _source_provenance_is_complete(
    provenance: Sequence[Mapping[str, object]], source_metrics: Sequence[str]
) -> bool:
    if not provenance or {str(item.get("canonical_metric")) for item in provenance} != set(source_metrics):
        return False
    return all(
        _text(item.get("source_id"))
        and _text(item.get("effective_at"))
        and _timezone_aware(_text(item.get("known_at")))
        for item in provenance
    )


def _period_source_provenance(
    frame: pd.DataFrame,
    source_metrics: Sequence[str],
    periods: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if frame.empty or "canonical_metric" not in frame.columns:
        return []
    result: list[dict[str, object]] = []
    for period in periods:
        rows = frame
        for column in ("period_type", "period_key", "period_end"):
            value = period.get(column)
            if column not in rows or value is None:
                rows = rows.iloc[0:0]
                break
            rows = rows.loc[rows[column].astype(str).eq(str(value))]
        for metric in source_metrics:
            candidates = rows.loc[rows["canonical_metric"].astype(str).eq(metric)]
            if candidates.empty:
                continue
            numeric = pd.to_numeric(candidates["value"], errors="coerce")
            candidates = candidates.loc[numeric.notna()].copy()
            if candidates.empty:
                continue
            if "source_id" in candidates:
                candidates = candidates.sort_values("source_id", kind="stable")
            row = candidates.iloc[-1]
            result.append(
                {
                    "source_id": _text(row.get("source_id")) or None,
                    "effective_at": _text(row.get("effective_at")) or None,
                    "known_at": _text(row.get("known_at")) or None,
                    "canonical_metric": metric,
                    "period_key": _text(period.get("period_key")),
                }
            )
    return result


def _history_source_provenance(
    frame: pd.DataFrame, source_metrics: Sequence[str]
) -> list[dict[str, object]]:
    if frame.empty or "canonical_metric" not in frame.columns:
        return []
    result: list[dict[str, object]] = []
    for metric in source_metrics:
        rows = frame.loc[frame["canonical_metric"].astype(str).eq(metric)]
        numeric = pd.to_numeric(rows.get("value", pd.Series(dtype="float64")), errors="coerce")
        for index, row in rows.loc[numeric.notna()].iterrows():
            result.append(
                {
                    "source_id": _text(row.get("source_id")) or None,
                    "effective_at": _text(row.get("effective_at")) or None,
                    "known_at": _text(row.get("known_at")) or None,
                    "canonical_metric": metric,
                    "period_key": _text(row.get("period_key")),
                }
            )
    return result


def _external_source_provenance(
    assumptions: Mapping[str, object], input_name: str
) -> list[dict[str, object]]:
    raw = assumptions.get("source_provenance", assumptions.get("provenance"))
    item = raw.get(input_name) if isinstance(raw, Mapping) else None
    if isinstance(item, Mapping):
        items: Sequence[object] = (item,)
    elif isinstance(item, (tuple, list)):
        items = item
    else:
        return []
    result: list[dict[str, object]] = []
    for candidate in items:
        if not isinstance(candidate, Mapping):
            continue
        result.append(
            {
                "source_id": _text(candidate.get("source_id")) or None,
                "effective_at": _text(candidate.get("effective_at")) or None,
                "known_at": _text(candidate.get("known_at")) or None,
                "canonical_metric": f"assumption:{input_name}",
            }
        )
    return result


def _market_input_provenance(
    market_inputs: Mapping[str, object], input_name: str
) -> list[dict[str, object]]:
    raw_map = market_inputs.get("source_provenance")
    mapped = raw_map.get(input_name) if isinstance(raw_map, Mapping) else None
    raw = market_inputs.get(f"{input_name}_source_provenance", mapped)
    if isinstance(raw, Mapping):
        raw_items: Sequence[object] = (raw,)
    elif isinstance(raw, (tuple, list)):
        raw_items = raw
    else:
        raw_items = ()
    result: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "source_id": _text(item.get("source_id")) or None,
                "effective_at": _text(item.get("effective_at")) or None,
                "known_at": _text(item.get("known_at")) or None,
                "canonical_metric": f"market:{input_name}",
            }
        )
    if result:
        return result

    source_fields = (
        (f"{input_name}_source_ids", f"{input_name}_source_id")
        if input_name != "share_price"
        else ("share_price_source_ids", "share_price_source_id", "price_source_ids", "price_source_id", "source_ids", "source_id")
    )
    sources: list[str] = []
    for key in source_fields:
        value = market_inputs.get(key)
        if isinstance(value, (tuple, list)):
            sources.extend(_text(item) for item in value if _text(item))
        elif _text(value):
            sources.append(_text(value))
        if sources:
            break
    if input_name == "share_price":
        effective = _first_present(
            market_inputs.get("share_price_effective_at"),
            market_inputs.get("share_price_at"),
            market_inputs.get("price_timestamp"),
            market_inputs.get("price_at"),
            market_inputs.get("price_date"),
        )
        known = _first_present(
            market_inputs.get("share_price_known_at"),
            market_inputs.get("price_known_at"),
            market_inputs.get("known_at"),
        )
    else:
        effective = market_inputs.get(f"{input_name}_effective_at")
        known = market_inputs.get(f"{input_name}_known_at")
    return [
        {
            "source_id": source_id,
            "effective_at": _text(effective) or None,
            "known_at": _text(known) or None,
            "canonical_metric": f"market:{input_name}",
        }
        for source_id in dict.fromkeys(sources)
    ]


def _financial_projection_source_provenance(
    projection: object | None, metric_names: Sequence[str]
) -> list[dict[str, object]]:
    raw_metrics = _projection_member(projection, "metrics", ())
    if isinstance(raw_metrics, Mapping):
        items = list(raw_metrics.items())
    elif isinstance(raw_metrics, (tuple, list)):
        items = [(_projection_member(item, "metric"), item) for item in raw_metrics]
    else:
        return []
    result: list[dict[str, object]] = []
    for metric_name in metric_names:
        matches = [
            item
            for name, item in items
            if str(_projection_member(item, "metric", name)) == metric_name
        ]
        if len(matches) != 1:
            continue
        item = matches[0]
        result.append(
            {
                "source_id": _text(_projection_member(item, "source_id")) or None,
                "effective_at": _text(_projection_member(item, "as_of")) or None,
                "known_at": _text(_projection_member(item, "known_at")) or None,
                "canonical_metric": f"financial_projection:{metric_name}",
            }
        )
    return result


def _valuation_model_provenance(
    frame: pd.DataFrame,
    latest: Mapping[str, float],
    market_inputs: Mapping[str, object],
    assumptions: Mapping[str, object],
    *,
    model: str,
    use_margin: bool = False,
    financial_projection: object | None = None,
    bank_route: bool = False,
) -> list[dict[str, object]]:
    source_metrics: list[str] = []
    market_metric_names: list[str] = []
    projection_metric_names: list[str] = []
    required_inputs: list[tuple[str, str]] = []
    if model == "dcf":
        if _float(market_inputs.get("free_cash_flow")) is not None:
            market_metric_names.append("free_cash_flow")
            required_inputs.append(("market:free_cash_flow", "free_cash_flow"))
        else:
            source_metrics.append("free_cash_flow")
            required_inputs.append(("statement:free_cash_flow", "free_cash_flow"))
        if use_margin:
            source_metrics.append("revenue")
            required_inputs.append(("statement:revenue", "revenue"))
        if _float(market_inputs.get("shares_outstanding")) is not None:
            market_metric_names.append("shares_outstanding")
            required_inputs.append(("market:shares_outstanding", "shares_outstanding"))
        elif "shares_outstanding" in latest:
            source_metrics.append("shares_outstanding")
            required_inputs.append(("statement:shares_outstanding", "shares_outstanding"))
        else:
            market_metric_names.append("shares_outstanding")
            required_inputs.append(("market:shares_outstanding", "shares_outstanding"))
        net_debt = _float(market_inputs.get("net_debt"))
        if net_debt is not None:
            market_metric_names.append("net_debt")
            required_inputs.append(("market:net_debt", "net_debt"))
        elif "net_debt" in latest:
            source_metrics.append("net_debt")
            required_inputs.append(("statement:net_debt", "net_debt"))
        else:
            source_metrics.extend(("debt", "cash"))
            required_inputs.extend(
                [("statement:debt", "debt"), ("statement:cash", "cash")]
            )
    elif model == "residual_income":
        if bank_route:
            projection_metric_names.extend(("closing_equity", "net_profit_attributable"))
            if _float(assumptions.get("sustainable_roe")) is not None:
                projection_metric_names = ["closing_equity"]
            elif _float(assumptions.get("sustainable_rote")) is not None:
                projection_metric_names = ["tangible_book_value"]
            else:
                projection_metric_names.append("tangible_book_value")
            required_inputs.extend(
                (f"projection:{name}", name) for name in projection_metric_names
            )
            if _float(assumptions.get("sustainable_roe")) is not None:
                required_inputs.append(("assumption:sustainable_roe", "sustainable_roe"))
            if _float(assumptions.get("sustainable_rote")) is not None:
                required_inputs.append(("assumption:sustainable_rote", "sustainable_rote"))
        else:
            source_metrics.extend(("equity", "net_income"))
            required_inputs.extend(
                [("statement:equity", "equity"), ("statement:net_income", "net_income")]
            )
            if _float(market_inputs.get("shares_outstanding")) is not None:
                market_metric_names.append("shares_outstanding")
                required_inputs.append(("market:shares_outstanding", "shares_outstanding"))
            elif "shares_outstanding" in latest:
                source_metrics.append("shares_outstanding")
                required_inputs.append(("statement:shares_outstanding", "shares_outstanding"))
            else:
                market_metric_names.append("shares_outstanding")
                required_inputs.append(("market:shares_outstanding", "shares_outstanding"))
        if _float(market_inputs.get("equity")) is not None and not bank_route:
            market_metric_names.append("equity")
            required_inputs = [item for item in required_inputs if item[1] != "equity"]
            required_inputs.append(("market:equity", "equity"))
        if _float(market_inputs.get("net_income")) is not None and not bank_route:
            market_metric_names.append("net_income")
            required_inputs = [item for item in required_inputs if item[1] != "net_income"]
            required_inputs.append(("market:net_income", "net_income"))
        if bank_route:
            if _float(market_inputs.get("shares_outstanding")) is not None:
                market_metric_names.append("shares_outstanding")
                required_inputs.append(("market:shares_outstanding", "shares_outstanding"))
            elif "shares_outstanding" in latest:
                source_metrics.append("shares_outstanding")
                required_inputs.append(("statement:shares_outstanding", "shares_outstanding"))
            else:
                market_metric_names.append("shares_outstanding")
                required_inputs.append(("market:shares_outstanding", "shares_outstanding"))
    provenance = _latest_source_provenance(frame, source_metrics)
    for market_metric in dict.fromkeys(market_metric_names):
        provenance.extend(_market_input_provenance(market_inputs, market_metric))
    if projection_metric_names:
        provenance.extend(
            _financial_projection_source_provenance(
                financial_projection, tuple(dict.fromkeys(projection_metric_names))
            )
        )
    provenance.extend(_external_source_provenance(assumptions, model))
    for assumption_name in (
        ("sustainable_roe", "sustainable_rote")
        if model == "residual_income"
        else ()
    ):
        if _float(assumptions.get(assumption_name)) is not None:
            provenance.extend(_external_source_provenance(assumptions, assumption_name))
    available_pairs = {
        (f"statement:{item.get('canonical_metric')}", str(item.get("canonical_metric")))
        for item in provenance
        if item.get("canonical_metric")
        and not str(item.get("canonical_metric")).startswith(("market:", "assumption:", "financial_projection:"))
    }
    available_pairs.update(
        (f"market:{str(item.get('canonical_metric')).removeprefix('market:')}", str(item.get("canonical_metric")).removeprefix("market:"))
        for item in provenance
        if str(item.get("canonical_metric", "")).startswith("market:")
    )
    available_pairs.update(
        (f"projection:{str(item.get('canonical_metric')).removeprefix('financial_projection:')}", str(item.get("canonical_metric")).removeprefix("financial_projection:"))
        for item in provenance
        if str(item.get("canonical_metric", "")).startswith("financial_projection:")
    )
    available_pairs.update(
        (str(item.get("canonical_metric")), str(item.get("canonical_metric")).removeprefix("assumption:"))
        for item in provenance
        if str(item.get("canonical_metric", "")).startswith("assumption:")
    )
    missing_required = [item for item in required_inputs if item not in available_pairs]
    if not any(str(item.get("canonical_metric")) == f"assumption:{model}" for item in provenance):
        missing_required.append((f"assumption:{model}", model))
    if missing_required:
        provenance.append(
            {
                "source_id": None,
                "effective_at": None,
                "known_at": None,
                "canonical_metric": "missing_model_input_provenance",
                "missing_inputs": tuple(name for _key, name in missing_required),
            }
        )
    return provenance


def _margin_of_safety(
    value_per_share: object,
    price: object,
    value_provenance: Sequence[Mapping[str, object]],
    price_provenance: Sequence[Mapping[str, object]],
    *,
    model: str,
) -> dict[str, object]:
    model_value = _float(value_per_share)
    current_price = _float(price)
    provenance = [dict(item) for item in (*value_provenance, *price_provenance)]
    missing = []
    if model_value is None:
        missing.append("model_value_unavailable")
    if current_price is None or current_price <= 0:
        missing.append("positive_current_price_unavailable")
    if not _source_triplets_complete(value_provenance):
        missing.append("model_source_timing_unavailable")
    if not _source_triplets_complete(price_provenance):
        missing.append("price_source_timing_unavailable")
    if missing:
        return {
            "model": model,
            "status": "unavailable",
            "value": None,
            "per_share_value": model_value,
            "price": current_price,
            "reason_codes": tuple(dict.fromkeys(missing)),
            "source_provenance": provenance,
            "execution_allowed": False,
        }
    assert model_value is not None and current_price is not None
    mos = (model_value - current_price) / current_price
    return {
        "model": model,
        "status": "available" if math.isfinite(mos) else "unavailable",
        "value": mos if math.isfinite(mos) else None,
        "formula": "(model_per_share_value - current_price) / current_price",
        "per_share_value": model_value,
        "price": current_price,
        "reason_codes": () if math.isfinite(mos) else ("nonfinite_margin_of_safety",),
        "source_provenance": provenance,
        "execution_allowed": False,
    }


def _reverse_dcf_gap(
    reverse_dcf: Mapping[str, object], assumptions: Mapping[str, object]
) -> dict[str, object]:
    reference = assumptions.get("reverse_dcf_reference")
    if not isinstance(reference, Mapping):
        return {
            "status": "unavailable",
            "reason": "Explicit source-backed reverse-DCF comparison evidence is required.",
            "execution_allowed": False,
        }
    reference_growth = _float(reference.get("growth"))
    raw_provenance = reference.get("source_provenance")
    reference_provenance = (
        [dict(item) for item in raw_provenance if isinstance(item, Mapping)]
        if isinstance(raw_provenance, (tuple, list))
        else []
    )
    model_provenance = reverse_dcf.get("source_provenance")
    implied = _float(reverse_dcf.get("implied_growth"))
    if (
        reverse_dcf.get("status") != "available"
        or implied is None
        or reference_growth is None
        or not _source_triplets_complete(reference_provenance)
        or not isinstance(model_provenance, (tuple, list))
        or not _source_triplets_complete(model_provenance)
    ):
        return {
            "status": "unavailable",
            "reason": "Reverse-DCF model and explicit comparison evidence must both be available and timed.",
            "execution_allowed": False,
        }
    assert implied is not None
    gap = reference_growth - implied
    return {
        "status": "available" if math.isfinite(gap) else "unavailable",
        "value": gap if math.isfinite(gap) else None,
        "formula": "explicit_reference_growth - reverse_dcf_implied_growth",
        "implied_growth": implied,
        "reference_growth": reference_growth,
        "source_provenance": [*model_provenance, *reference_provenance],
        "execution_allowed": False,
    }


def _source_triplets_complete(
    provenance: Sequence[Mapping[str, object]],
) -> bool:
    return bool(provenance) and all(
        _text(item.get("source_id"))
        and _text(item.get("effective_at"))
        and _timezone_aware(_text(item.get("known_at")))
        for item in provenance
    )


def _bind_capital_efficiency_source_provenance(
    output: dict[str, object],
    frame: pd.DataFrame,
    assumptions: Mapping[str, object],
) -> None:
    reported = output.get("reported")
    if not isinstance(reported, dict):
        return
    metrics = reported.get("metrics")
    history = reported.get("history")
    if not isinstance(metrics, dict) or not isinstance(history, list):
        return
    history_rows = [item for item in history if isinstance(item, Mapping)]
    calculation_inputs = output.get("calculation_inputs")
    tax_basis = (
        calculation_inputs.get("tax_rate_basis")
        if isinstance(calculation_inputs, Mapping)
        else "unavailable"
    )
    period_metrics = ("operating_income", "equity", "debt", "cash")
    tax_metrics = ("income_before_tax", "tax_expense")
    history_specs: dict[str, list[Mapping[str, object]]] = {
        "economic_profit_spread": history_rows[-1:],
        "incremental_roic": history_rows[-2:],
        "reinvestment_rate": history_rows[-2:],
    }
    for name, selected_periods in history_specs.items():
        metric = metrics.get(name)
        if not isinstance(metric, dict):
            continue
        metrics_needed = (*period_metrics, *tax_metrics) if tax_basis == "reported_effective_rate" else period_metrics
        provenance = _period_source_provenance(frame, metrics_needed, selected_periods)
        if tax_basis == "explicit_assumption":
            provenance.extend(_external_source_provenance(assumptions, "tax_rate"))
        if name == "economic_profit_spread":
            provenance.extend(_external_source_provenance(assumptions, "cost_of_capital"))
        metric["source_provenance"] = provenance
        required_statement_metrics = set(metrics_needed)
        actual_statement_metrics = {
            str(item.get("canonical_metric"))
            for item in provenance
            if not str(item.get("canonical_metric", "")).startswith("assumption:")
        }
        assumptions_complete = (
            tax_basis != "explicit_assumption"
            or any(item.get("canonical_metric") == "assumption:tax_rate" for item in provenance)
        )
        if name == "economic_profit_spread":
            assumptions_complete = assumptions_complete and any(
                item.get("canonical_metric") == "assumption:cost_of_capital"
                for item in provenance
            )
        complete = (
            bool(selected_periods)
            and required_statement_metrics <= actual_statement_metrics
            and assumptions_complete
            and _source_triplets_complete(provenance)
        )
        metric["source_timing_status"] = "available" if complete else "unavailable"
        if not complete:
            metric["source_timing_limitation"] = "Exact selected source or assumption timing is incomplete."

    proxy_section = output.get("business_quality_proxies")
    proxies = proxy_section if isinstance(proxy_section, dict) else {}
    for name, source_metrics in (
        ("recurring_revenue_share", ("recurring_revenue", "revenue")),
        ("customer_concentration", ("customer_concentration",)),
        ("supplier_concentration", ("supplier_concentration",)),
    ):
        metric = proxies.get(name)
        if not isinstance(metric, dict):
            continue
        provenance = _latest_source_provenance(frame, source_metrics)
        metric["source_provenance"] = provenance
        metric["source_ids"] = tuple(
            sorted(
                {
                    str(item.get("source_id"))
                    for item in provenance
                    if _text(item.get("source_id"))
                }
            )
        )
        metric["source_timing_status"] = (
            "available"
            if _source_provenance_is_complete(provenance, source_metrics)
            else "unavailable"
        )
    persistence = proxies.get("capital_return_persistence")
    if isinstance(persistence, dict):
        persistence_metrics = (*period_metrics, *tax_metrics) if tax_basis == "reported_effective_rate" else period_metrics
        provenance = _period_source_provenance(frame, persistence_metrics, history_rows)
        if tax_basis == "explicit_assumption":
            provenance.extend(_external_source_provenance(assumptions, "tax_rate"))
        persistence["source_provenance"] = provenance
        actual_metrics = {
            str(item.get("canonical_metric"))
            for item in provenance
            if not str(item.get("canonical_metric", "")).startswith("assumption:")
        }
        complete = (
            len(history_rows) >= 3
            and set(persistence_metrics) <= actual_metrics
            and (tax_basis != "explicit_assumption" or any(item.get("canonical_metric") == "assumption:tax_rate" for item in provenance))
            and _source_triplets_complete(provenance)
        )
        persistence["source_timing_status"] = "available" if complete else "unavailable"



def _timezone_aware(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return not pd.isna(parsed) and parsed.tzinfo is not None


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
        invested_capital = sm.invested_capital(equity, debt, values.get("lease_liabilities"), cash)
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


_STRESS_LABEL = {"kind": "sensitivity", "is_probability": False, "execution_allowed": False}


def _stress_unavailable(reason: str, assumptions: Mapping[str, object]) -> dict[str, object]:
    return {"status": "unavailable", "confidence": "low", "reason": reason, "assumptions": dict(assumptions), **_STRESS_LABEL}


def _stress_scenarios(values: Mapping[str, float], frame: pd.DataFrame, assumptions: Mapping[str, object] | None = None) -> dict[str, dict[str, object]]:
    """Deterministic sensitivities, never probabilities. Defaults (documented): recession revenue -20 %, favourable +10 %,
    50 % of the cost base fixed (operating leverage), +200 bp on debt that reprices within one year."""

    params = assumptions or {}
    revenue = values.get("revenue")
    operating_income = values.get("operating_income")
    debt = values.get("debt")
    interest = values.get("interest_expense")
    cash = values.get("cash")
    margin = None if revenue in (None, 0) or operating_income is None else operating_income / revenue
    fixed_share = _float(params.get("fixed_cost_share"))
    fixed_share = 0.5 if fixed_share is None or not 0.0 <= fixed_share <= 1.0 else fixed_share
    rate_add = _float(params.get("refinancing_rate_add")) or 0.02
    scenarios: dict[str, dict[str, object]] = {}
    assumed_flat = {"revenue_factor": 0.8, "rate_add": 0.0}
    if revenue is None or margin is None or interest is None or debt is None:
        scenarios["revenue_down_20"] = {"status": "missing", "confidence": "low", "assumptions": assumed_flat, **_STRESS_LABEL}
    else:
        stressed_revenue = revenue * 0.8
        stressed_operating_income = stressed_revenue * margin
        scenarios["revenue_down_20"] = {"status": "available", "confidence": "scenario_only", "assumptions": assumed_flat, "stressed_revenue": stressed_revenue, "stressed_operating_income": stressed_operating_income, "stressed_interest": interest, "interest_coverage": None if interest == 0 else stressed_operating_income / interest, **_STRESS_LABEL}

    def operating_case(revenue_factor: float) -> dict[str, object]:
        assumed = {"revenue_factor": revenue_factor, "fixed_cost_share": fixed_share, "operating_leverage": True}
        if revenue is None or revenue <= 0 or operating_income is None or interest is None:
            return _stress_unavailable("revenue, operating income and interest expense are required", assumed)
        costs = revenue - operating_income
        stressed_revenue = revenue * revenue_factor
        stressed_costs = costs * fixed_share + costs * (1.0 - fixed_share) * revenue_factor
        stressed_income = stressed_revenue - stressed_costs
        return {"status": "available", "confidence": "scenario_only", "assumptions": assumed, "stressed_revenue": stressed_revenue, "stressed_operating_income": stressed_income, "stressed_interest": interest, "interest_coverage": None if interest == 0 else stressed_income / interest, **_STRESS_LABEL}

    scenarios["baseline"] = operating_case(1.0)
    scenarios["favourable"] = operating_case(1.1)
    scenarios["recession_operating_leverage"] = operating_case(0.8)

    due_1y = values.get("debt_due_1y")
    refinance_assumed = {"rate_add": rate_add, "applies_to": "debt_due_1y (repricing within one year)"}
    if due_1y is None:
        scenarios["refinancing_shock"] = _stress_unavailable("No debt maturity schedule is available; the shock applies only to repricing debt and total debt is never repriced.", refinance_assumed)
    elif operating_income is None or interest is None or due_1y < 0 or (debt is not None and due_1y > debt * 1.0000001):
        scenarios["refinancing_shock"] = _stress_unavailable("Maturity bucket, operating income or interest expense is missing or inconsistent with total debt.", refinance_assumed)
    else:
        stressed_interest = interest + due_1y * rate_add
        scenarios["refinancing_shock"] = {"status": "available", "confidence": "scenario_only", "assumptions": refinance_assumed, "repricing_debt": due_1y, "stressed_interest": stressed_interest, "stressed_operating_income": operating_income, "interest_coverage": None if stressed_interest == 0 else operating_income / stressed_interest, **_STRESS_LABEL}

    fcf = values.get("free_cash_flow")
    market_cap = values.get("market_cap")
    dilution_assumed = {"cash_buffer": "reported cash", "funding": "equity issued at the decision-time market cap"}
    if due_1y is None or cash is None or fcf is None:
        scenarios["dilution_insolvency"] = _stress_unavailable("Debt due within one year, cash and free cash flow are required.", dilution_assumed)
    else:
        gap = max(0.0, due_1y - cash - max(fcf, 0.0))
        dilution = None if market_cap is None or market_cap <= 0 else gap / (market_cap + gap)
        scenarios["dilution_insolvency"] = {"status": "available", "confidence": "scenario_only", "assumptions": dilution_assumed, "liquidity_shortfall": gap, "dilution_fraction": dilution, "dilution_status": "available" if dilution is not None else "unavailable: market cap required", "insolvency_flag": gap > 0 and (market_cap is None or market_cap <= 0), **_STRESS_LABEL}
    return scenarios


def _bank_stress_scenarios(values: Mapping[str, float], assumptions: Mapping[str, object] | None = None) -> dict[str, dict[str, object]]:
    """Bank sensitivities (CRE/property, funding shift, impairment, capital breach); evidence-gated, never invented."""

    params = assumptions or {}
    cet1 = values.get("cet1_capital")
    rwa = values.get("risk_weighted_assets")
    loans = values.get("gross_loans")
    cre = values.get("cre_exposure")
    deposits = values.get("deposits")
    wholesale = values.get("wholesale_funding")
    requirement = _float(params.get("cet1_requirement"))
    cre_haircut = _float(params.get("cre_haircut")) or 0.20
    impairment_rate = _float(params.get("impairment_rate")) or 0.02
    funding_spread = _float(params.get("funding_spread_add")) or 0.01
    deposit_outflow = _float(params.get("deposit_outflow_fraction")) or 0.10
    scenarios: dict[str, dict[str, object]] = {}
    scenarios["cre_property_stress"] = (
        _stress_unavailable("CRE/property exposure is not evidenced.", {"cre_haircut": cre_haircut})
        if cre is None else {"status": "available", "confidence": "scenario_only", "assumptions": {"cre_haircut": cre_haircut}, "loss": cre * cre_haircut, **_STRESS_LABEL}
    )
    scenarios["funding_shift"] = (
        _stress_unavailable("Deposits and wholesale funding are not evidenced.", {"deposit_outflow_fraction": deposit_outflow, "funding_spread_add": funding_spread})
        if deposits is None or wholesale is None else {"status": "available", "confidence": "scenario_only", "assumptions": {"deposit_outflow_fraction": deposit_outflow, "funding_spread_add": funding_spread}, "replacement_funding": deposits * deposit_outflow, "extra_funding_cost": (wholesale + deposits * deposit_outflow) * funding_spread, **_STRESS_LABEL}
    )
    scenarios["impairment_stress"] = (
        _stress_unavailable("Gross loans are not evidenced.", {"impairment_rate": impairment_rate})
        if loans is None else {"status": "available", "confidence": "scenario_only", "assumptions": {"impairment_rate": impairment_rate}, "loss": loans * impairment_rate, **_STRESS_LABEL}
    )
    cre_loss = scenarios["cre_property_stress"].get("loss")
    impairment_loss = scenarios["impairment_stress"].get("loss")
    funding_cost = scenarios["funding_shift"].get("extra_funding_cost")
    assumed = {"cet1_requirement": requirement}
    if cet1 is None or rwa is None or rwa <= 0 or requirement is None or None in (cre_loss, impairment_loss, funding_cost):
        scenarios["capital_breach"] = _stress_unavailable("CET1 capital, risk-weighted assets, the stated CET1 requirement and all three loss legs are required.", assumed)
    else:
        stressed_ratio = (cet1 - float(cre_loss) - float(impairment_loss) - float(funding_cost)) / rwa
        scenarios["capital_breach"] = {"status": "available", "confidence": "scenario_only", "assumptions": assumed, "stressed_cet1_ratio": stressed_ratio, "breach": stressed_ratio < requirement, **_STRESS_LABEL}
    return scenarios


_CLAIM_TYPES = ("fcff", "fcfe", "proxy")
_DEFAULT_CLAIM_TYPE = "proxy"
_DEFAULT_LONG_RUN_NOMINAL_GROWTH_CAP = 0.05
_BRIDGE_ITEMS: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("net_debt", ("net_debt",), -1.0),
    ("lease_liabilities", ("lease_liabilities", "lease_liability"), -1.0),
    ("minority_interest", ("minority_interest", "non_controlling_interest"), -1.0),
    ("preferred_equity", ("preferred_equity", "preferred_stock"), -1.0),
    ("pension_deficit", ("pension_deficit", "net_pension_liability", "pension_liability"), -1.0),
    ("non_operating_assets", ("non_operating_assets", "investments_non_operating"), 1.0),
)
_STATEMENT_MAX_AGE_DAYS = 548
_FX_MAX_AGE_DAYS = 7
_ASSUMPTION_MAX_AGE_DAYS = 365


def _claim_context(assumptions: Mapping[str, object]) -> dict[str, object]:
    """Resolve the cash-flow claim contract; an absent label is a ``proxy`` (descriptive, never score-eligible)."""

    raw = assumptions.get("cash_flow_claim_type")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {"status": "available", "claim": _DEFAULT_CLAIM_TYPE, "source": "default_proxy"}
    claim = str(raw).strip().casefold()
    if claim not in _CLAIM_TYPES:
        return {"status": "unavailable", "claim": None, "source": "invalid", "reason": f"cash_flow_claim_type must be one of {', '.join(_CLAIM_TYPES)}"}
    return {"status": "available", "claim": claim, "source": "explicit"}


def _claim_rate(assumptions: Mapping[str, object], claim: str) -> tuple[float | None, str]:
    """FCFF is discounted at WACC, FCFE at the cost of equity, a proxy at the unlabelled ``discount_rate``."""

    ledger = build_cost_of_capital_ledger(assumptions)
    if claim == "fcff":
        return ledger.wacc, "wacc"
    if claim == "fcfe":
        return ledger.cost_of_equity, "cost_of_equity"
    return _float(assumptions.get("discount_rate")), "unlabelled_discount_rate"


def _growth_cap(assumptions: Mapping[str, object]) -> float:
    cap = _float(assumptions.get("long_run_nominal_growth_cap"))
    return cap if cap is not None and cap > -1.0 else _DEFAULT_LONG_RUN_NOMINAL_GROWTH_CAP


def _terminal_growth_invalid(discount: float, terminal_growth: float, cap: float) -> str | None:
    if discount <= -1.0 or terminal_growth <= -1.0:
        return "discount rate and terminal growth must exceed -100 %"
    if terminal_growth >= discount:
        return "terminal growth must be below the discount rate (g < WACC / k_e)"
    if terminal_growth > cap:
        return "terminal growth exceeds the long-run nominal growth cap"
    return None


def _ev_equity_bridge(values: Mapping[str, float], assumptions: Mapping[str, object], claim: str) -> dict[str, object]:
    """Items between enterprise and equity value. Each is evidenced or explicitly declared nil; a gap is not zero."""

    if claim == "fcfe":
        return {"status": "not_applicable", "reason": "FCFE is already after debt claims; no debt is subtracted afterwards.", "items": {}, "missing": [], "total_claims": 0.0}
    declared_nil = assumptions.get("bridge_not_applicable")
    declared = {str(key): str(reason) for key, reason in declared_nil.items() if str(reason).strip()} if isinstance(declared_nil, Mapping) else {}
    items: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    adjustment = 0.0
    required = _BRIDGE_ITEMS if claim == "fcff" else _BRIDGE_ITEMS[:1]
    for name, aliases, sign in required:
        value = next((values[alias] for alias in aliases if values.get(alias) is not None), None)
        if value is not None:
            items[name] = {"value": value, "evidence": "reported"}
            adjustment += sign * value
        elif name in declared:
            items[name] = {"value": 0.0, "evidence": "declared_not_applicable", "reason": declared[name]}
        else:
            missing.append(name)
    return {
        "status": "incomplete" if missing else "complete",
        "items": items,
        "missing": missing,
        "total_claims": None if missing else adjustment,
        "reason": "missing bridge evidence: " + ", ".join(missing) if missing else "",
        "formula": "equity = EV - net debt - leases - minorities - preferreds - pensions + non-operating assets",
    }


def _equity_from_enterprise(enterprise_value: float, bridge: Mapping[str, object]) -> float | None:
    claims = bridge.get("total_claims")
    return None if claims is None else enterprise_value + float(claims)


def _base_cash_flow(values: Mapping[str, float], margin: float | None) -> float | None:
    if margin is None:
        return values.get("free_cash_flow")
    revenue = values.get("revenue")
    return None if revenue is None else float(revenue) * margin


def _intrinsic_value(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    """Flat-growth DCF kept as a labelled diagnostic (``diagnostic_flat_growth``); never score-eligible."""

    context = _claim_context(assumptions)
    if context["status"] != "available":
        return {"status": "unavailable", "confidence": "low", "reason": str(context["reason"]), "scenarios": {}, "score_eligible": False, "execution_allowed": False}
    claim = str(context["claim"])
    fcf = values.get("free_cash_flow")
    shares = values.get("shares_outstanding")
    discount, rate_kind = _claim_rate(assumptions, claim)
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = _forecast_years(assumptions)
    scenarios = assumptions.get("scenarios")
    bridge = _ev_equity_bridge(values, assumptions, claim)
    base = {
        "cash_flow_claim_type": claim,
        "claim_type_source": context["source"],
        "discount_rate_kind": rate_kind,
        "label": "diagnostic_flat_growth",
        "score_eligible": False,
        "score_eligibility_reason": "proxy cash flow: descriptive value only" if claim == "proxy" else "flat-growth DCF is a labelled diagnostic",
        "bridge": bridge,
    }
    if fcf is None or shares is None or shares <= 0 or (claim != "fcfe" and values.get("net_debt") is None) or discount is None or terminal_growth is None or years <= 0 or not isinstance(scenarios, Mapping) or not scenarios:
        return {**base, "status": "unavailable", "confidence": "low", "reason": "free cash flow, share count, net debt (not for FCFE), a claim-matched discount rate, forecast and explicit scenario assumptions are required", "scenarios": {}, "execution_allowed": False}
    invalid = _terminal_growth_invalid(discount, terminal_growth, _growth_cap(assumptions))
    if invalid is not None:
        return {**base, "status": "unavailable", "confidence": "low", "reason": invalid, "scenarios": {}, "execution_allowed": False}
    if claim == "fcff" and bridge["status"] != "complete":
        return {**base, "status": "unavailable", "confidence": "low", "reason": f"no binding per-share value: {bridge['reason']}", "scenarios": {}, "execution_allowed": False}
    results: dict[str, dict[str, object]] = {}
    rejected: dict[str, str] = {}
    for name, raw in scenarios.items():
        growth = _float(raw.get("growth")) if isinstance(raw, Mapping) else None
        if growth is None or growth <= -1.0:
            continue
        margin = _float(raw.get("margin"))
        base_cash_flow = _base_cash_flow(values, margin)
        if base_cash_flow is None:
            continue
        if base_cash_flow <= 0:
            rejected[str(name)] = "negative_or_zero_base_cash_flow_not_extrapolated"
            continue
        per_share = _dcf_per_share(values, growth, margin, discount, terminal_growth, years, claim=claim, bridge=bridge)
        if per_share is None:
            rejected[str(name)] = "negative_equity_value_or_incomplete_bridge"
            continue
        forecast_path = [base_cash_flow * (1.0 + growth) ** year for year in range(1, years + 1)]
        enterprise_value = _dcf_enterprise_value(forecast_path, discount, terminal_growth)
        if enterprise_value is None:
            continue
        equity_value = enterprise_value if claim == "fcfe" else _equity_from_enterprise(enterprise_value, bridge)
        results[str(name)] = {
            "growth": growth,
            "margin": margin,
            "margin_basis": "free_cash_flow_margin" if margin is not None else "reported_free_cash_flow",
            "growth_path": forecast_path,
            "enterprise_value": enterprise_value,
            "equity_value": equity_value,
            "per_share": per_share,
            "kind": "sensitivity",
            "is_probability": False,
            "confidence": "scenario_only",
            "execution_allowed": False,
        }
    if not results:
        return {**base, "status": "unavailable", "confidence": "low", "reason": "no valid scenario assumptions", "scenarios": {}, "rejected_scenarios": rejected, "execution_allowed": False}
    per_share_values = [float(item["per_share"]) for item in results.values()]
    return {**base, "status": "available", "confidence": "scenario_only", "forecast_years": years, "discount_rate": discount, "terminal_growth": terminal_growth, "scenarios": results, "rejected_scenarios": rejected, "range": [min(per_share_values), max(per_share_values)], "execution_allowed": False}


def _reverse_dcf(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    context = _claim_context(assumptions)
    claim = str(context.get("claim") or _DEFAULT_CLAIM_TYPE)
    target = values.get("market_cap")
    fcf = values.get("free_cash_flow")
    shares = values.get("shares_outstanding")
    discount, _ = _claim_rate(assumptions, claim)
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = _forecast_years(assumptions)
    bridge = _ev_equity_bridge(values, assumptions, claim)
    labels = {"cash_flow_claim_type": claim, "score_eligible": False}
    if (
        context["status"] != "available" or target is None or fcf is None or fcf <= 0 or shares is None or shares <= 0
        or (claim != "fcfe" and values.get("net_debt") is None) or discount is None or terminal_growth is None or years <= 0
        or _terminal_growth_invalid(discount, terminal_growth, _growth_cap(assumptions)) is not None
        or (claim == "fcff" and bridge["status"] != "complete")
    ):
        return {**labels, "status": "unavailable", "confidence": "low", "reason": "positive FCF, market value, diluted share count, net debt, a valid claim label, bridge evidence and explicit bounded assumptions are required", "execution_allowed": False}

    def equity_for(growth: float) -> float:
        per_share = _dcf_per_share(values, growth, None, discount, terminal_growth, years, claim=claim, bridge=bridge)
        return float(per_share * shares) if per_share is not None else math.nan

    low, high = -0.5, 1.0
    try:
        lower_value, upper_value = equity_for(low), equity_for(high)
    except (ArithmeticError, OverflowError, ValueError):
        lower_value, upper_value = math.nan, math.nan
    if not math.isfinite(lower_value) or not math.isfinite(upper_value) or not (lower_value <= target <= upper_value):
        return {**labels, "status": "unavailable", "confidence": "low", "reason": "market value is outside the bounded growth search", "execution_allowed": False}
    for _ in range(80):
        middle = (low + high) / 2.0
        middle_value = equity_for(middle)
        if not math.isfinite(middle_value):
            return {**labels, "status": "unavailable", "confidence": "low", "reason": "bounded growth search produced a nonfinite value", "execution_allowed": False}
        if middle_value < target:
            low = middle
        else:
            high = middle
    return {**labels, "status": "available", "confidence": "scenario_only", "implied_growth": (low + high) / 2.0, "target_equity_value": target, "execution_allowed": False}


def _residual_income(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    """Clean-surplus residual income: B_t = B_{t-1} + NI_t - dividends_t + issuance_t, RI_t = NI_t - k_e * B_{t-1}."""

    unavailable = {"status": "unavailable", "confidence": "low", "score_eligible": False, "execution_allowed": False}
    book = values.get("equity")
    net_income = values.get("net_income")
    shares = values.get("shares_outstanding")
    cost = _float(assumptions.get("cost_of_equity", assumptions.get("discount_rate")))
    growth = _float(assumptions.get("terminal_growth"))
    years = _forecast_years(assumptions)
    if book is None or net_income is None or shares is None or shares <= 0 or cost is None or growth is None or years <= 0 or cost <= growth or cost <= -1.0 or growth <= -1.0:
        return {**unavailable, "reason": "book equity, net income, diluted share count and explicit cost-of-equity/terminal assumptions are required"}
    if growth > _growth_cap(assumptions):
        return {**unavailable, "reason": "terminal growth exceeds the long-run nominal growth cap"}
    if net_income <= 0:
        return {**unavailable, "reason": "negative_or_zero_net_income_not_extrapolated"}
    payout = _float(assumptions.get("payout_ratio"))
    dividend_per_share = _float(values.get("dividend_per_share"))
    reported_payout = None if dividend_per_share is None else dividend_per_share * shares / net_income
    if payout is not None and not 0.0 <= payout <= 1.0:
        return {**unavailable, "reason": "payout ratio must lie between 0 and 1"}
    if payout is not None:
        dividend_basis, used_payout = "explicit_payout_ratio", payout
    elif reported_payout is not None and 0.0 <= reported_payout <= 1.0:
        dividend_basis, used_payout = "reported_dividend_per_share", reported_payout
    else:
        dividend_basis, used_payout = "default_full_payout_unevidenced", 1.0
    issuance = _float(assumptions.get("net_issuance"))
    issuance_value = 0.0 if issuance is None else issuance
    reconciliation: dict[str, object] = {"status": "not_checked", "reason": "only one dividend input supplied"}
    if payout is not None and reported_payout is not None:
        reconciliation = {"status": "reconciled" if abs(payout - reported_payout) <= 0.02 else "mismatch", "assumed_payout": payout, "reported_payout": reported_payout}
    try:
        opening = float(book)
        earnings = float(net_income)
        value = float(book)
        roll: list[dict[str, float]] = []
        for year in range(1, years + 1):
            earnings = earnings * (1.0 + growth) if year > 1 else earnings
            dividends = used_payout * earnings
            closing = opening + earnings - dividends + issuance_value
            roll.append({"year": year, "opening_book": opening, "net_income": earnings, "dividends": dividends, "issuance": issuance_value, "closing_book": closing, "residual_income": earnings - cost * opening})
            value += (earnings - cost * opening) / (1.0 + cost) ** year
            opening = closing
        terminal_residual = earnings * (1.0 + growth) - cost * opening
        value += terminal_residual / (cost - growth) / (1.0 + cost) ** years
    except (ArithmeticError, OverflowError, ValueError):
        return {**unavailable, "reason": "residual-income calculation produced an invalid value"}
    if not math.isfinite(value):
        return {**unavailable, "reason": "residual-income calculation produced a nonfinite value"}
    clean_surplus_error = max(abs(row["closing_book"] - (row["opening_book"] + row["net_income"] - row["dividends"] + row["issuance"])) for row in roll)
    evidenced = dividend_basis != "default_full_payout_unevidenced" and reconciliation["status"] != "mismatch" and issuance is not None
    return {
        "status": "available",
        "confidence": "scenario_only",
        "equity_value": value,
        "per_share": value / shares,
        "cost_of_equity": cost,
        "terminal_growth": growth,
        "forecast_years": years,
        "net_income_basis": values.get("net_income_basis", "latest_reported_net_income"),
        "clean_surplus": {
            "status": "reconciled" if clean_surplus_error < 1e-9 else "broken",
            "max_abs_error": clean_surplus_error,
            "identity": "B_t = B_{t-1} + NI_t - dividends_t + issuance_t",
            "dividend_basis": dividend_basis,
            "payout_ratio": used_payout,
            "net_issuance": issuance_value,
            "net_issuance_basis": "explicit" if issuance is not None else "default_zero_unevidenced",
            "book_roll": roll,
            "terminal_residual_income": terminal_residual,
        },
        "dividend_reconciliation": reconciliation,
        "cash_flow_claim_type": "fcfe",
        "score_eligible": evidenced,
        "score_eligibility_reason": "" if evidenced else "dividend or issuance evidence is a default or does not reconcile",
        "execution_allowed": False,
    }


def _driver_dcf(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    """Driver chain: revenue growth -> margin -> NOPAT -> reinvestment (g / ROIC) -> FCFF, with growth/ROIC fade."""

    base: dict[str, object] = {"cash_flow_claim_type": "fcff", "label": "driver_dcf", "score_eligible": False, "execution_allowed": False}
    raw = assumptions.get("driver_dcf")
    if not isinstance(raw, Mapping):
        return {**base, "status": "unavailable", "confidence": "low", "reason": "explicit driver_dcf assumptions (growth, margin, tax, incremental ROIC) are required"}
    revenue = values.get("revenue")
    shares = values.get("shares_outstanding")
    ledger = build_cost_of_capital_ledger(assumptions)
    wacc = ledger.wacc
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = _forecast_years(assumptions)
    start_growth = _float(raw.get("revenue_growth"))
    start_margin = _float(raw.get("operating_margin"))
    end_margin = _float(raw.get("terminal_operating_margin", raw.get("operating_margin")))
    tax = _float(raw.get("tax_rate", assumptions.get("tax_rate")))
    start_roic = _float(raw.get("incremental_roic"))
    end_roic = _float(raw.get("terminal_roic", wacc))  # conservative default: growth earns only the cost of capital
    needed = (revenue, shares, wacc, terminal_growth, start_growth, start_margin, end_margin, tax, start_roic, end_roic)
    if any(item is None for item in needed) or years <= 0 or shares is None or shares <= 0:
        return {**base, "status": "unavailable", "confidence": "low", "reason": "revenue, shares, WACC, terminal growth, growth, margin, tax rate and incremental ROIC are required"}
    assert revenue is not None and wacc is not None and terminal_growth is not None and start_growth is not None
    assert start_margin is not None and end_margin is not None and tax is not None and start_roic is not None and end_roic is not None
    invalid = _terminal_growth_invalid(wacc, terminal_growth, _growth_cap(assumptions))
    if invalid is not None:
        return {**base, "status": "unavailable", "confidence": "low", "reason": invalid}
    if revenue <= 0 or start_margin <= 0 or not 0.0 <= tax < 1.0 or start_roic <= 0 or end_roic <= 0 or start_growth <= -1.0:
        return {**base, "status": "unavailable", "confidence": "low", "reason": "non-positive revenue, margin or ROIC, or an invalid tax rate, is not extrapolated"}
    bridge = _ev_equity_bridge(values, assumptions, "fcff")
    if bridge["status"] != "complete":
        return {**base, "status": "unavailable", "confidence": "low", "reason": f"no binding per-share value: {bridge['reason']}", "bridge": bridge}
    rows: list[dict[str, float]] = []
    present_value = 0.0
    current_revenue = float(revenue)
    nopat = 0.0
    for year in range(1, years + 1):
        weight = year / years
        growth = start_growth + (terminal_growth - start_growth) * weight
        roic = start_roic + (end_roic - start_roic) * weight
        margin = start_margin + (end_margin - start_margin) * weight
        reinvestment_rate = growth / roic
        if reinvestment_rate >= 1.0:
            return {**base, "status": "unavailable", "confidence": "low", "reason": f"year {year} reinvestment rate g/ROIC >= 100 %; growth is not fundable at this ROIC"}
        current_revenue *= 1.0 + growth
        nopat = current_revenue * margin * (1.0 - tax)
        fcff = nopat * (1.0 - reinvestment_rate)
        present_value += fcff / (1.0 + wacc) ** year
        rows.append({"year": year, "revenue_growth": growth, "revenue": current_revenue, "operating_margin": margin, "nopat": nopat, "incremental_roic": roic, "reinvestment_rate": reinvestment_rate, "reinvestment": nopat * reinvestment_rate, "fcff": fcff})
    terminal_reinvestment = terminal_growth / end_roic
    if terminal_reinvestment >= 1.0:
        return {**base, "status": "unavailable", "confidence": "low", "reason": "terminal reinvestment g/ROIC >= 100 %"}
    terminal_fcff = nopat * (1.0 + terminal_growth) * (1.0 - terminal_reinvestment)
    enterprise_value = present_value + terminal_fcff / (wacc - terminal_growth) / (1.0 + wacc) ** years
    equity_value = _equity_from_enterprise(enterprise_value, bridge)
    if equity_value is None or equity_value <= 0 or not math.isfinite(equity_value):
        return {**base, "status": "unavailable", "confidence": "low", "reason": "negative_equity_value_not_a_fair_value", "bridge": bridge}
    return {
        **base,
        "status": "available",
        "confidence": "scenario_only",
        "discount_rate": wacc,
        "discount_rate_kind": "wacc",
        "terminal_growth": terminal_growth,
        "terminal_reinvestment_rate": terminal_reinvestment,
        "terminal_roic": end_roic,
        "forecast_years": years,
        "path": rows,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "per_share": equity_value / shares,
        "bridge": bridge,
        "kind": "sensitivity",
        "is_probability": False,
        "cost_of_capital_basis": ledger.basis,
    }


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
    *, claim: str = _DEFAULT_CLAIM_TYPE, bridge: Mapping[str, object] | None = None,
) -> float | None:
    shares, fcf = values.get("shares_outstanding"), values.get("free_cash_flow")
    if shares is None or shares <= 0 or fcf is None or discount <= terminal_growth or discount <= -1.0 or terminal_growth <= -1.0 or growth <= -1.0:
        return None
    if claim != "fcfe" and values.get("net_debt") is None:
        return None
    if margin is not None and values.get("revenue") is None:
        return None
    base_cash_flow = fcf if margin is None else values["revenue"] * margin
    if base_cash_flow <= 0:
        return None  # negative cash flow is never extrapolated into a (negative) fair value
    try:
        path = [base_cash_flow * (1.0 + growth) ** year for year in range(1, years + 1)]
    except (ArithmeticError, OverflowError, ValueError):
        return None
    enterprise_value = _dcf_enterprise_value(path, discount, terminal_growth)
    if enterprise_value is None:
        return None
    resolved = bridge if bridge is not None else _ev_equity_bridge(values, {}, claim)
    equity_value = enterprise_value if claim == "fcfe" else _equity_from_enterprise(enterprise_value, resolved)
    if equity_value is None or equity_value < 0:
        return None
    result = equity_value / shares
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
    context = _claim_context(assumptions)
    if context["status"] != "available":
        return {"status": "unavailable", "reason": str(context["reason"]), "grid": {}, "execution_allowed": False}
    claim = str(context["claim"])
    bridge = _ev_equity_bridge(values, assumptions, claim)
    cap = _growth_cap(assumptions)
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
                per_share = None if terminal > cap else _dcf_per_share(values, growth, margin, discount, terminal, years, claim=claim, bridge=bridge)
                cell = {"discount_rate": discount, "terminal_growth": terminal, "per_share": per_share, "status": "available" if per_share is not None else "unavailable"}
                cells.append(cell)
                if per_share is not None:
                    outputs.append(per_share)
        grid[str(name)] = {"cells": cells, "range": [min(outputs), max(outputs)] if outputs else [], "status": "available" if outputs else "unavailable"}
    return {"status": "available" if any(item.get("status") == "available" for item in grid.values()) else "unavailable", "cash_flow_claim_type": claim, "grid": grid, "execution_allowed": False}


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


def _operator_weights(assumptions: Mapping[str, object]) -> dict[str, object]:
    """Operator-supplied scenario weights are a label for the operator's view, never probabilities (V2-12)."""

    raw = assumptions.get("scenario_weights", assumptions.get("weights"))
    if not isinstance(raw, Mapping) or not raw:
        return {"status": "not_supplied", "label": None, "is_probability": False}
    weights = {str(name): _float(value) for name, value in raw.items()}
    return {"status": "available", "label": "operator_supplied", "is_probability": False, "weights": weights, "note": "Operator weights are not probabilities and are not calibrated."}


def _peer_implied_per_share(values: Mapping[str, float], peer_metrics: Mapping[str, object] | None) -> float | None:
    metrics = (peer_metrics or {}).get("metrics")
    pe = metrics.get("price_to_earnings") if isinstance(metrics, Mapping) else None
    median = _float(pe.get("median")) if isinstance(pe, Mapping) and pe.get("status") == "available" else None
    income, shares = values.get("net_income"), values.get("shares_outstanding")
    if median is None or income is None or income <= 0 or shares is None or shares <= 0:
        return None
    return median * income / shares


def _model_disagreement(
    intrinsic: Mapping[str, object],
    residual: Mapping[str, object],
    *,
    driver: Mapping[str, object] | None = None,
    peer_metrics: Mapping[str, object] | None = None,
    values: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Range and pairwise deltas; deltas are reported only between equity-claim values and nothing is ever averaged."""

    scenario_values = [result.get("per_share") for result in (intrinsic.get("scenarios", {}) or {}).values() if isinstance(result, Mapping) and result.get("per_share") is not None]
    values_list = list(scenario_values)
    if residual.get("per_share") is not None:
        values_list.append(residual["per_share"])
    models: dict[str, dict[str, object]] = {}
    base_scenario = (intrinsic.get("scenarios", {}) or {}).get("base") if isinstance(intrinsic.get("scenarios"), Mapping) else None
    if isinstance(driver, Mapping) and driver.get("per_share") is not None:
        models["dcf"] = {"per_share": float(driver["per_share"]), "claim": "fcff", "source": "driver_dcf"}
    elif isinstance(base_scenario, Mapping) and base_scenario.get("per_share") is not None:
        models["dcf"] = {"per_share": float(base_scenario["per_share"]), "claim": str(intrinsic.get("cash_flow_claim_type", "proxy")), "source": "flat_growth_diagnostic"}
    if residual.get("per_share") is not None:
        models["residual_income"] = {"per_share": float(residual["per_share"]), "claim": "fcfe", "source": "residual_income"}
    peer_value = _peer_implied_per_share(values or {}, peer_metrics)
    if peer_value is not None:
        models["peer"] = {"per_share": peer_value, "claim": "market_multiple", "source": "peer_price_to_earnings_median"}
    deltas: dict[str, dict[str, object]] = {}
    names = list(models)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            key = f"{left}_vs_{right}"
            if "proxy" in (models[left]["claim"], models[right]["claim"]):
                deltas[key] = {"status": "incompatible_claim", "reason": "a proxy cash-flow claim is not comparable with other claims"}
                continue
            difference = float(models[left]["per_share"]) - float(models[right]["per_share"])
            reference = float(models[right]["per_share"])
            deltas[key] = {"status": "available", "delta": difference, "relative_delta": None if reference == 0 else difference / reference, "claim_basis": "equity_per_share"}
    return {
        "status": "available" if len(values_list) >= 2 else "unavailable",
        "range": [min(values_list), max(values_list)] if values_list else [],
        "confidence": "scenario_only" if values_list else "low",
        "models": models,
        "deltas": deltas,
        "averaged": False,
        "note": "Methods are compared per share under their own claim; incompatible numbers are never averaged.",
        "execution_allowed": False,
    }


def _parse_utc(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else parsed


def _valuation_expiry(
    frame: pd.DataFrame,
    market: Mapping[str, object],
    market_inputs: Mapping[str, object],
    assumptions: Mapping[str, object],
    as_known_at: str | date | None,
) -> dict[str, object]:
    """A valuation built on stale filings, FX or assumptions is provisional (V2-21). No wall clock is read."""

    reference = _parse_utc(as_known_at if as_known_at is not None else market_inputs.get("decision_time"))
    components: dict[str, dict[str, object]] = {}
    periods = pd.to_datetime(frame["period_end"], errors="coerce", utc=True).dropna() if not frame.empty and "period_end" in frame else pd.Series(dtype="datetime64[ns, UTC]")
    if len(periods):
        components["statements"] = {"basis": str(periods.max().date()), "expires_at": (periods.max() + pd.Timedelta(days=_STATEMENT_MAX_AGE_DAYS)).isoformat()}
    fx_stamp = _parse_utc(market_inputs.get("currency_conversion_timestamp"))
    if fx_stamp is not None:
        components["fx"] = {"basis": fx_stamp.isoformat(), "expires_at": (fx_stamp + pd.Timedelta(days=_FX_MAX_AGE_DAYS)).isoformat()}
    explicit = _parse_utc(assumptions.get("expires_at"))
    assumption_as_of = _parse_utc(assumptions.get("as_of"))
    if explicit is not None:
        components["assumptions"] = {"basis": "explicit expires_at", "expires_at": explicit.isoformat()}
    elif assumption_as_of is not None:
        components["assumptions"] = {"basis": assumption_as_of.isoformat(), "expires_at": (assumption_as_of + pd.Timedelta(days=_ASSUMPTION_MAX_AGE_DAYS)).isoformat()}
    expiries = [_parse_utc(item["expires_at"]) for item in components.values()]
    expires_at = min((item for item in expiries if item is not None), default=None)
    reasons: list[str] = []
    if reference is None:
        reasons.append("decision time is unavailable; freshness cannot be established")
    if "statements" not in components:
        reasons.append("no dated statement evidence")
    if reference is not None:
        for name, item in components.items():
            limit = _parse_utc(item["expires_at"])
            if limit is not None and reference > limit:
                reasons.append(f"{name} evidence expired at {limit.isoformat()}")
    if "assumptions" not in components:
        reasons.append("assumptions carry no as_of or expires_at date")
    provisional = bool(reasons)
    return {
        "status": "provisional" if provisional else "current",
        "expires_at": None if expires_at is None else expires_at.isoformat(),
        "refresh_reason": "; ".join(reasons),
        "components": components,
        "reference_time": None if reference is None else reference.isoformat(),
        "defaults": {"statement_max_age_days": _STATEMENT_MAX_AGE_DAYS, "fx_max_age_days": _FX_MAX_AGE_DAYS, "assumption_max_age_days": _ASSUMPTION_MAX_AGE_DAYS},
        "execution_allowed": False,
    }


def _score_eligibility(
    models: Mapping[str, Mapping[str, object]],
    *,
    ledger: CostOfCapitalLedger,
    strict_comparability: bool,
    expiry: Mapping[str, object],
    bank_route: bool,
) -> dict[str, object]:
    """Only evidenced, strict, current, claim-consistent models may feed a score; a proxy never does."""

    result: dict[str, dict[str, object]] = {}
    for name, model in models.items():
        reasons: list[str] = []
        if model.get("status") != "available":
            reasons.append("model unavailable")
        if name == "intrinsic_value":
            reasons.append("flat-growth DCF is a labelled diagnostic")
        if model.get("cash_flow_claim_type") == "proxy":
            reasons.append("proxy cash-flow claim is descriptive only")
        if name == "residual_income" and not model.get("score_eligible"):
            reasons.append(str(model.get("score_eligibility_reason") or "residual income is not fully evidenced"))
        if ledger.basis != "observed":
            reasons.append("cost-of-capital inputs are a scenario, not observed")
        if not strict_comparability:
            reasons.append("non-strict comparability is diagnostic only")
        if expiry.get("status") == "provisional":
            reasons.append("valuation is provisional: " + str(expiry.get("refresh_reason")))
        if bank_route and name != "residual_income":
            reasons.append("not applicable to financial institutions")
        eligible = not reasons
        result[name] = {"score_eligible": eligible, "reasons": reasons}
        if isinstance(model, dict):
            model["score_eligible"] = eligible
            model["score_eligibility_reasons"] = reasons
    return {"models": result, "any_eligible": any(item["score_eligible"] for item in result.values()), "execution_allowed": False}


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
