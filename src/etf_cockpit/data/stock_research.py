"""Transparent stock research analytics over canonical statement evidence.

The functions in this module deliberately return evidence dictionaries rather
than an action score. Every value carries a formula, period, source coverage
and confidence boundary. Missing inputs remain missing and structurally
inapplicable sectors are not forced through industrial formulas.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import math
import pandas as pd

from etf_cockpit.data.statement_normalisation import statement_coverage, statement_view


STOCK_RESEARCH_SCHEMA_VERSION = "stock_research.v1"
_SPECIAL_SECTORS = frozenset({"bank", "banks", "insurance", "insurer", "financial", "financials"})


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
    tax_rate: float | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id)
    latest = _latest_values(frame)
    histories = _histories(frame)
    metrics: dict[str, dict[str, object]] = {}
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

    metrics["gross_margin"] = _ratio_metric("gross_margin", gross_profit, revenue, "gross_profit / revenue", frame, "revenue")
    metrics["operating_margin"] = _ratio_metric("operating_margin", operating_income, revenue, "operating_income / revenue", frame, "revenue")
    metrics["net_margin"] = _ratio_metric("net_margin", net_income, revenue, "net_income / revenue", frame, "revenue")
    metrics["roa"] = _ratio_metric("roa", net_income, assets, "net_income / assets", frame, "assets")
    metrics["roe"] = _ratio_metric("roe", net_income, equity, "net_income / equity", frame, "equity")
    invested_capital = _sum_if_present(equity, debt, -cash if cash is not None else None)
    roic = None if sector.casefold() in _SPECIAL_SECTORS else (None if operating_income is None or tax is None else operating_income * (1.0 - tax))
    metrics["roic"] = _ratio_metric(
        "roic",
        roic,
        invested_capital,
        "(operating_income * (1 - tax_rate)) / (equity + debt - cash)",
        frame,
        "equity",
        applicability="not_applicable" if sector.casefold() in _SPECIAL_SECTORS else "applicable",
        limitation="Special-sector adapter required." if sector.casefold() in _SPECIAL_SECTORS else "",
    )
    metrics["cash_conversion"] = _ratio_metric("cash_conversion", cfo, net_income, "cash_from_operations / net_income", frame, "cash_from_operations", zero_denominator_status="not_applicable")
    accrual_numerator = None if net_income is None or cfo is None else net_income - cfo
    metrics["accrual_ratio"] = _ratio_metric("accrual_ratio", accrual_numerator, assets, "(net_income - cash_from_operations) / assets", frame, "assets")
    exceptional = latest.get("exceptional_items")
    metrics["exceptional_item_dependence"] = _ratio_metric("exceptional_item_dependence", exceptional, net_income, "exceptional_items / net_income", frame, "exceptional_items", zero_denominator_status="not_applicable")
    margins = _derived_history(histories, "gross_profit", "revenue")
    metrics["margin_stability"] = _metric(
        "margin_stability",
        None if len(margins) < 2 else float(pd.Series(margins).std(ddof=0)),
        "population standard deviation of gross_margin history",
        frame,
        status_override="missing" if len(margins) == 0 else "not_applicable" if len(margins) == 1 else None,
        limitation="At least two comparable periods are required." if len(margins) < 2 else "",
    )

    peer_percentiles = {
        name: _peer_percentile(name, evidence.get("value"), peer_frame)
        for name, evidence in metrics.items()
        if evidence.get("value") is not None
    }
    components = _quality_components(latest, histories)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "metrics": metrics,
        "history": {name: values for name, values in {"gross_margin": margins, "operating_margin": _derived_history(histories, "operating_income", "revenue"), "net_margin": _derived_history(histories, "net_income", "revenue")}.items()},
        "peer_percentiles": peer_percentiles,
        "quality_components": components,
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def balance_sheet_analysis(statements: pd.DataFrame, *, instrument_id: str | None = None, sector: str = "") -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id)
    latest = _latest_values(frame)
    metrics: dict[str, dict[str, object]] = {}
    debt = latest.get("debt")
    cash = latest.get("cash")
    equity = latest.get("equity")
    current_assets = latest.get("current_assets")
    current_liabilities = latest.get("current_liabilities")
    receivables = latest.get("receivables")
    operating_income = latest.get("operating_income")
    interest_expense = latest.get("interest_expense")
    metrics["net_debt"] = _metric("net_debt", None if debt is None or cash is None else debt - cash, "debt - cash", frame)
    metrics["debt_to_equity"] = _ratio_metric("debt_to_equity", debt, equity, "debt / equity", frame, "debt")
    metrics["current_ratio"] = _ratio_metric("current_ratio", current_assets, current_liabilities, "current_assets / current_liabilities", frame, "current_assets")
    quick_assets = _sum_if_present(cash, receivables)
    metrics["quick_ratio"] = _ratio_metric("quick_ratio", quick_assets, current_liabilities, "(cash + receivables) / current_liabilities", frame, "cash")
    metrics["working_capital"] = _metric("working_capital", None if current_assets is None or current_liabilities is None else current_assets - current_liabilities, "current_assets - current_liabilities", frame)
    metrics["interest_coverage"] = _ratio_metric("interest_coverage", operating_income, interest_expense, "operating_income / interest_expense", frame, "operating_income", zero_denominator_status="not_applicable")

    special = sector.casefold() in _SPECIAL_SECTORS
    distress = _distress_metric(latest, frame, special)
    metrics["altman_like_distress"] = distress
    maturity = _maturity_timeline(latest, frame)
    stress = _stress_scenarios(latest, frame)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "metrics": metrics,
        "maturity_timeline": maturity,
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
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id)
    latest = _latest_values(frame)
    market = {str(key): _float(value) for key, value in (market_inputs or {}).items()}
    assumption_values = {str(key): value for key, value in (assumptions or {}).items()}
    values = {**latest, **{key: value for key, value in market.items() if value is not None}}
    if values.get("net_debt") is None and values.get("debt") is not None and values.get("cash") is not None:
        values["net_debt"] = values["debt"] - values["cash"]
    relative_metrics = {
        "ev_to_sales": _ratio_metric("ev_to_sales", values.get("enterprise_value"), values.get("revenue"), "enterprise_value / revenue", frame, "enterprise_value"),
        "ev_to_ebitda": _ratio_metric("ev_to_ebitda", values.get("enterprise_value"), values.get("operating_income"), "enterprise_value / operating_income", frame, "enterprise_value"),
        "price_to_earnings": _ratio_metric("price_to_earnings", values.get("market_cap"), values.get("net_income"), "market_cap / net_income", frame, "market_cap", zero_denominator_status="not_applicable"),
        "price_to_book": _ratio_metric("price_to_book", values.get("market_cap"), values.get("equity"), "market_cap / equity", frame, "market_cap", zero_denominator_status="not_applicable"),
        "dividend_yield": _ratio_metric("dividend_yield", values.get("dividend_per_share"), values.get("share_price"), "dividend_per_share / share_price", frame, "dividend_per_share", zero_denominator_status="not_applicable"),
    }
    intrinsic = _intrinsic_value(values, assumption_values)
    reverse = _reverse_dcf(values, assumption_values)
    residual = _residual_income(values, assumption_values)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "relative_metrics": relative_metrics,
        "intrinsic_value": intrinsic,
        "reverse_dcf": reverse,
        "residual_income": residual,
        "model_disagreement": _model_disagreement(intrinsic, residual),
        "assumptions": assumption_values,
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def build_stock_research_report(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    peer_frame: pd.DataFrame | None = None,
    market_inputs: Mapping[str, object] | None = None,
    assumptions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "profitability": profitability_analysis(statements, instrument_id=instrument_id, sector=sector, peer_frame=peer_frame),
        "balance_sheet": balance_sheet_analysis(statements, instrument_id=instrument_id, sector=sector),
        "valuation": valuation_analysis(statements, instrument_id=instrument_id, market_inputs=market_inputs, assumptions=assumptions),
        "source_lineage": _lineage(_statement_frame(statements, instrument_id)),
        "execution_allowed": False,
    }


def load_stock_research_frame(path: object, *, instrument_id: str | None = None) -> pd.DataFrame:
    try:
        frame = pd.read_parquet(path) if path else pd.DataFrame()
    except (OSError, ValueError, ImportError):
        frame = pd.DataFrame()
    return _statement_frame(frame, instrument_id)


def _statement_frame(frame: pd.DataFrame, instrument_id: str | None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    result = statement_view(frame, "latest_restated")
    if instrument_id and "instrument_id" in result.columns:
        result = result[result["instrument_id"].astype(str).eq(str(instrument_id))]
    return result.reset_index(drop=True)


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
    return asdict(MetricEvidence(name, value, status, formula, period, source_ids, "high" if value is not None and source_ids else "low", applicability, limitation))


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
    return {
        "statement_view": "latest_restated",
        "coverage": statement_coverage(frame),
        "source_ids": sorted({str(value) for value in frame.get("source_id", pd.Series(dtype="object")).dropna() if str(value)}),
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
    return {"status": "available" if available else "missing", "buckets": available, "formula": "reported debt maturity buckets", "source_ids": sorted({source for name in available for source in _source_ids(frame, name)}), "confidence": "high" if available else "low", "limitation": "Unavailable maturities are not replaced with zero." if not available else "", "execution_allowed": False}


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
    years = int(assumptions.get("forecast_years", 0) or 0)
    scenarios = assumptions.get("scenarios")
    if fcf is None or shares is None or net_debt is None or discount is None or terminal_growth is None or years <= 0 or not isinstance(scenarios, Mapping) or not scenarios:
        return {"status": "unavailable", "confidence": "low", "reason": "free cash flow, share count, net debt, forecast and explicit scenario assumptions are required", "scenarios": {}, "execution_allowed": False}
    results: dict[str, dict[str, object]] = {}
    for name, raw in scenarios.items():
        if not isinstance(raw, Mapping) or _float(raw.get("growth")) is None:
            continue
        growth = float(raw["growth"])
        margin = _float(raw.get("margin"))
        cash_flow = fcf if margin is None else fcf * (margin / max(abs(values.get("operating_income", 1.0)), 1e-12))
        present_value = sum(cash_flow * (1.0 + growth) ** year / (1.0 + discount) ** year for year in range(1, years + 1))
        terminal_cash_flow = cash_flow * (1.0 + growth) ** years
        denominator = discount - terminal_growth
        if denominator <= 0:
            continue
        terminal_value = terminal_cash_flow * (1.0 + terminal_growth) / denominator
        enterprise_value = present_value + terminal_value / (1.0 + discount) ** years
        equity_value = enterprise_value - net_debt
        results[str(name)] = {"growth": growth, "margin": margin, "enterprise_value": enterprise_value, "equity_value": equity_value, "per_share": equity_value / shares, "confidence": "scenario_only", "execution_allowed": False}
    if not results:
        return {"status": "unavailable", "confidence": "low", "reason": "no valid scenario assumptions", "scenarios": {}, "execution_allowed": False}
    return {"status": "available", "confidence": "scenario_only", "forecast_years": years, "discount_rate": discount, "terminal_growth": terminal_growth, "scenarios": results, "execution_allowed": False}


def _reverse_dcf(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    target = values.get("market_cap")
    fcf = values.get("free_cash_flow")
    shares = values.get("shares_outstanding")
    net_debt = values.get("net_debt")
    discount = _float(assumptions.get("discount_rate"))
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = int(assumptions.get("forecast_years", 0) or 0)
    if target is None or fcf is None or shares is None or net_debt is None or discount is None or terminal_growth is None or years <= 0 or discount <= terminal_growth:
        return {"status": "unavailable", "confidence": "low", "execution_allowed": False}
    def equity_for(growth: float) -> float:
        pv = sum(fcf * (1.0 + growth) ** year / (1.0 + discount) ** year for year in range(1, years + 1))
        terminal = fcf * (1.0 + growth) ** years * (1.0 + terminal_growth) / (discount - terminal_growth)
        return pv + terminal / (1.0 + discount) ** years - net_debt
    low, high = -0.5, 1.0
    if not (equity_for(low) <= target <= equity_for(high)):
        return {"status": "unavailable", "confidence": "low", "reason": "market value is outside the bounded growth search", "execution_allowed": False}
    for _ in range(80):
        middle = (low + high) / 2.0
        if equity_for(middle) < target:
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
    years = int(assumptions.get("forecast_years", 0) or 0)
    if book is None or net_income is None or shares is None or cost is None or growth is None or years <= 0 or cost <= growth:
        return {"status": "unavailable", "confidence": "low", "execution_allowed": False}
    value = book
    residual = net_income - cost * book
    for year in range(1, years + 1):
        value += residual * (1.0 + growth) ** (year - 1) / (1.0 + cost) ** year
    terminal = residual * (1.0 + growth) ** years / (cost - growth)
    value += terminal / (1.0 + cost) ** years
    return {"status": "available", "confidence": "scenario_only", "equity_value": value, "per_share": value / shares, "execution_allowed": False}


def _model_disagreement(intrinsic: Mapping[str, object], residual: Mapping[str, object]) -> dict[str, object]:
    values = [result.get("per_share") for result in (intrinsic.get("scenarios", {}) or {}).values() if isinstance(result, Mapping) and result.get("per_share") is not None]
    if residual.get("per_share") is not None:
        values.append(residual["per_share"])
    return {"status": "available" if len(values) >= 2 else "unavailable", "range": [min(values), max(values)] if values else [], "confidence": "scenario_only" if values else "low", "execution_allowed": False}


__all__ = [
    "MetricEvidence",
    "STOCK_RESEARCH_SCHEMA_VERSION",
    "balance_sheet_analysis",
    "build_stock_research_report",
    "load_stock_research_frame",
    "profitability_analysis",
    "valuation_analysis",
]
