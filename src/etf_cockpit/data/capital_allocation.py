"""Point-in-time cash-flow quality and capital-allocation evidence.

This module is a pure projection over canonical statement rows and caller-owned
market/corporate-action evidence.  It reports calculated free cash flow apart
from any issuer-reported free cash flow, and keeps missing or ambiguous inputs
unavailable instead of filling them with zero.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
import math
import pandas as pd

from etf_cockpit.data.market_adjustments import (
    CorporateAction,
    CorporateActionCoverage,
    reconcile_provider_observations,
)
from etf_cockpit.data.statement_normalisation import statement_coverage, statement_view


CAPITAL_ALLOCATION_SCHEMA_VERSION = "capital_allocation.v1"
_FINANCIAL_SECTORS = frozenset({"bank", "banks", "insurance", "insurer", "financial", "financials"})
_CASH_METRICS = (
    "cash_from_operations",
    "cash_from_investing",
    "cash_from_financing",
    "cash_from_fx",
    "cash_net_change",
)
_CURRENCY_PATTERN = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_METRIC_NAMES = (
    "cash_from_operations_to_net_income",
    "cash_from_operations_to_ebitda",
    "free_cash_flow",
    "reported_free_cash_flow",
    "free_cash_flow_margin",
    "working_capital_contribution",
    "cash_taxes_paid",
    "cash_interest_paid",
    "capex_intensity",
    "cash_conversion",
    "organic_capex",
    "acquisitions",
    "disposals",
    "debt_issuance",
    "debt_repayment",
    "dividends",
    "gross_buybacks",
    "equity_issuance",
    "stock_based_compensation",
    "cash_accumulation",
    "dividend_yield",
    "buyback_yield",
    "issuance_dilution_yield",
    "shareholder_yield",
    "basic_share_count_change",
    "diluted_share_count_change",
    "treasury_share_change",
    "buybacks_vs_sbc_issuance",
)


def capital_allocation_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    market_inputs: Mapping[str, object] | None = None,
    corporate_actions: Sequence[CorporateAction] = (),
    corporate_action_coverage: CorporateActionCoverage | None = None,
    as_known_at: str | date | None = None,
    financial_projection: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return auditable period metrics without performing I/O or fetching data.

    Duration statement inputs follow the row sign convention in their
    canonical records.  Capital-allocation magnitudes such as ``capex``,
    ``dividends`` and ``gross_buybacks`` are treated as positive reported
    amounts; cash-flow-statement totals retain their signed inflow/outflow
    convention.  Share-count changes require dated corporate-action coverage.
    """

    cutoff = _timestamp(as_known_at)
    if cutoff is None:
        frame = pd.DataFrame()
        decision_time = ""
        unavailable_reason = "decision_time_required"
    else:
        decision_time = cutoff.isoformat().replace("+00:00", "Z")
        frame = statement_view(statements, "as_known_at", as_known_at=decision_time)
        if instrument_id and "instrument_id" in frame:
            frame = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))].copy()
        frame = _exclude_future_periods(frame, cutoff)
        unavailable_reason = "no_point_in_time_statement_rows" if frame.empty else ""

    special_sector = str(sector or "").strip().casefold() in _FINANCIAL_SECTORS
    periods = _flow_periods(frame)
    history: list[dict[str, object]] = []
    for period_frame, period, period_end in periods:
        previous_end = _prior_period_end(periods, period_end)
        previous_frame = _point_rows_for_end(frame, previous_end) if previous_end else pd.DataFrame()
        point_frame = _point_rows_for_end(frame, period_end)
        period_metrics, allocation, reconciliations = _period_analysis(
            period_frame,
            point_frame,
            previous_frame,
            period=period,
            period_end=period_end,
            previous_end=previous_end,
            sector_special=special_sector,
            market_inputs=market_inputs or {},
            corporate_actions=corporate_actions,
            corporate_action_coverage=corporate_action_coverage,
            instrument_id=instrument_id,
            decision_time=cutoff,
        )
        history.append(
            {
                "period": period,
                "period_end": period_end,
                "metrics": period_metrics,
                "capital_allocation": allocation,
                "reconciliations": reconciliations,
                "execution_allowed": False,
            }
        )

    latest = history[-1] if history else None
    metrics = dict(latest["metrics"]) if latest else _unavailable_metrics(unavailable_reason or "no_comparable_statement_period")
    capital_allocation = dict(latest["capital_allocation"]) if latest else {}
    reconciliations = list(latest["reconciliations"]) if latest else []
    available_metrics = sum(item.get("value") is not None for item in metrics.values() if isinstance(item, dict))
    coverage = {
        "period_count": len(history),
        "latest_period": latest.get("period") if latest else "unavailable",
        "metric_count": len(metrics),
        "available_metric_count": available_metrics,
        "status": "available" if available_metrics else "unavailable",
        "statement_coverage": statement_coverage(frame),
    }
    source_ids = sorted(
        {
            source_id
            for item in metrics.values()
            if isinstance(item, dict)
            for source_id in item.get("source_ids", ())
        }
    )
    lineage: dict[str, object] = {
        "statement_view": "as_known_at" if cutoff is not None else "unavailable",
        "as_known_at": decision_time or None,
        "source_ids": source_ids,
        "execution_allowed": False,
    }
    if cutoff is None:
        lineage["limitation"] = unavailable_reason

    result: dict[str, object] = {
        "schema_version": CAPITAL_ALLOCATION_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "status": "available" if available_metrics else "unavailable",
        "metrics": metrics,
        "history": history,
        "capital_allocation": capital_allocation,
        "reconciliations": reconciliations,
        "coverage": coverage,
        "source_lineage": lineage,
        "maintenance_growth_capex": {
            "status": "unavailable",
            "reason": "maintenance_vs_growth_capex_requires_explicit_issuer_evidence",
        },
        "financial_projection": None,
        "execution_allowed": False,
    }
    if special_sector:
        result["financial_projection"] = dict(financial_projection or {})
        result["financial_projection_status"] = "available" if financial_projection and financial_projection.get("status") == "available" else "unavailable"
    return result


def _period_analysis(
    flow_rows: pd.DataFrame,
    point_rows: pd.DataFrame,
    previous_rows: pd.DataFrame,
    *,
    period: str,
    period_end: str,
    previous_end: str | None,
    sector_special: bool,
    market_inputs: Mapping[str, object],
    corporate_actions: Sequence[CorporateAction],
    corporate_action_coverage: CorporateActionCoverage | None,
    instrument_id: str | None,
    decision_time: pd.Timestamp,
) -> tuple[dict[str, dict[str, object]], dict[str, object], list[dict[str, object]]]:
    metrics: dict[str, dict[str, object]] = {}
    cfo = _metric_value(flow_rows, "cash_from_operations")
    net_income = _metric_value(flow_rows, "net_income")
    ebitda = _metric_value(flow_rows, "ebitda")
    revenue = _metric_value(flow_rows, "revenue")
    capex = _metric_value(flow_rows, "capex")
    currency, currency_reason = _common_currency(cfo, net_income)

    metrics["cash_from_operations_to_net_income"] = _ratio_record(
        "cash_from_operations_to_net_income",
        cfo,
        net_income,
        "cash_from_operations / net_income",
        period,
        denominator="net_income",
        unit="ratio",
        currency=currency,
        invalid_denominator="net_income_must_be_positive",
        shared_reason=currency_reason,
    )
    ebitda_currency, ebitda_reason = _common_currency(cfo, ebitda)
    metrics["cash_from_operations_to_ebitda"] = _ratio_record(
        "cash_from_operations_to_ebitda",
        cfo,
        ebitda,
        "cash_from_operations / ebitda",
        period,
        denominator="ebitda",
        unit="ratio",
        currency=ebitda_currency,
        invalid_denominator="ebitda_must_be_positive",
        shared_reason=ebitda_reason,
        applicability="not_applicable" if sector_special else "applicable",
        limitation="Industrial EBITDA conversion is not meaningful for financial institutions." if sector_special else "",
    )

    fcf_currency, fcf_reason = _common_currency(cfo, capex)
    fcf_value: float | None = None
    fcf_status = "available"
    fcf_limitation = ""
    if sector_special:
        fcf_status = "not_applicable"
        fcf_limitation = "Industrial free cash flow is not applicable to financial institutions."
    elif cfo["value"] is None or capex["value"] is None:
        fcf_status = "missing"
        fcf_limitation = _missing_reason(cfo, capex, fallback="cash_from_operations_or_capex_missing")
    elif fcf_reason:
        fcf_status = "missing"
        fcf_limitation = fcf_reason
    elif float(capex["value"]) < 0:
        fcf_status = "missing"
        fcf_limitation = "capex_sign_ambiguous_expected_positive_spend_amount"
    else:
        fcf_value = float(cfo["value"]) - float(capex["value"])
    metrics["free_cash_flow"] = _record(
        "free_cash_flow",
        fcf_value,
        "cash_from_operations - capex",
        period,
        currency=fcf_currency,
        denominator="none",
        sign_convention="reported CFO less positive capex spend; calculated value is distinct from reported free_cash_flow",
        source_ids=_sources(cfo, capex),
        status=fcf_status,
        limitation=fcf_limitation,
    )

    reported_fcf = _metric_value(flow_rows, "free_cash_flow")
    metrics["reported_free_cash_flow"] = _reported_record(
        "reported_free_cash_flow",
        reported_fcf,
        period,
        source_name="free_cash_flow",
        sign_convention="issuer-reported value, preserved without substituting it for calculated free cash flow",
    )
    revenue_currency, revenue_reason = _common_currency(
        {"value": fcf_value, "currency": fcf_currency, "source_ids": _sources(cfo, capex), "reason": fcf_limitation},
        revenue,
    )
    metrics["free_cash_flow_margin"] = _ratio_record(
        "free_cash_flow_margin",
        {"value": fcf_value, "currency": fcf_currency, "source_ids": _sources(cfo, capex), "reason": fcf_limitation},
        revenue,
        "free_cash_flow / revenue",
        period,
        denominator="revenue",
        unit="ratio",
        currency=revenue_currency,
        invalid_denominator="revenue_must_be_positive",
        shared_reason=revenue_reason,
        applicability="not_applicable" if sector_special else "applicable",
        limitation="Industrial free-cash-flow margin is not applicable to financial institutions." if sector_special else "",
    )

    wc = _metric_value(flow_rows, "working_capital_contribution")
    metrics["working_capital_contribution"] = _reported_record(
        "working_capital_contribution",
        wc,
        period,
        source_name="working_capital_contribution",
        sign_convention="reported cash-flow contribution; positive releases cash and negative consumes cash",
    )
    for name, label in (("cash_taxes_paid", "cash_taxes_paid"), ("cash_interest_paid", "cash_interest_paid")):
        paid = _metric_value(flow_rows, label)
        metrics[name] = _reported_record(
            name,
            paid,
            period,
            source_name=label,
            sign_convention="reported positive amount paid; no proxy from income-statement tax or interest expense",
        )

    if capex["value"] is None or revenue["value"] is None:
        capex_intensity = _record(
            "capex_intensity", None, "capex / revenue", period, currency=fcf_currency,
            denominator="revenue", sign_convention="positive capex spend divided by positive revenue",
            source_ids=_sources(capex, revenue), status="missing",
            limitation=_missing_reason(capex, revenue, fallback="capex_or_revenue_missing"),
        )
    else:
        capex_intensity = _ratio_record(
            "capex_intensity", capex, revenue, "capex / revenue", period,
            denominator="revenue", unit="ratio", currency=fcf_currency,
            invalid_denominator="revenue_must_be_positive", shared_reason=_common_currency(capex, revenue)[1],
            numerator_value=float(capex["value"]),
        )
    metrics["capex_intensity"] = capex_intensity
    metrics["cash_conversion"] = _ratio_record(
        "cash_conversion", cfo, net_income, "cash_from_operations / net_income", period,
        denominator="net_income", unit="ratio", currency=currency,
        invalid_denominator="net_income_must_be_positive", shared_reason=currency_reason,
    )

    allocation_specs = {
        "organic_capex": ("capex", "positive spend amount; not classified as maintenance or growth"),
        "acquisitions": ("acquisitions", "positive cash spend amount"),
        "disposals": ("disposals", "positive cash proceeds amount"),
        "debt_issuance": ("debt_issuance", "positive financing proceeds amount"),
        "debt_repayment": ("debt_repayment", "positive repayment amount"),
        "dividends": ("dividends", "positive distribution amount"),
        "gross_buybacks": ("gross_buybacks", "positive gross repurchase amount; not netted against issuance"),
        "equity_issuance": ("equity_issuance", "positive equity proceeds amount, kept separate from compensation expense"),
        "stock_based_compensation": ("stock_based_compensation", "positive reported compensation expense; non-cash unless separately evidenced"),
        "cash_accumulation": ("cash_net_change", "signed reported change in cash; positive is accumulation, negative is drawdown"),
    }
    allocation: dict[str, object] = {}
    for name, (source_name, sign_convention) in allocation_specs.items():
        item = _metric_value(flow_rows, source_name)
        if name == "cash_accumulation":
            allocation_value = _reported_record(name, item, period, source_name=source_name, sign_convention=sign_convention)
        else:
            allocation_value = _positive_amount_record(name, item, period, sign_convention=sign_convention)
        allocation[name] = allocation_value
        metrics[name] = allocation_value

    allocation["reported_cash_flow_sections"] = {
        name: _reported_record(
            name,
            _metric_value(flow_rows, source_name),
            period,
            source_name=source_name,
            sign_convention="reported signed cash flow; positive is an inflow and negative is an outflow",
        )
        for name, source_name in (
            ("operating_cash_flow", "cash_from_operations"),
            ("investing_cash_flow", "cash_from_investing"),
            ("financing_cash_flow", "cash_from_financing"),
            ("foreign_exchange_effect", "cash_from_fx"),
        )
    }

    payout_currency, payout_currency_reason = _common_currency(
        _metric_value(flow_rows, "dividends"),
        _metric_value(flow_rows, "gross_buybacks"),
        _metric_value(flow_rows, "equity_issuance"),
    )
    market_cap, market_currency, market_date, market_sources, market_reason = _market_cap(
        market_inputs,
        point_rows,
        period_end=period_end,
        statement_currency=payout_currency,
    )
    if payout_currency_reason:
        market_reason = market_reason or payout_currency_reason
    if market_currency and payout_currency and market_currency != payout_currency:
        market_reason = "market_statement_currency_mismatch"

    dividend = _metric_value(flow_rows, "dividends")
    buyback = _metric_value(flow_rows, "gross_buybacks")
    issuance = _metric_value(flow_rows, "equity_issuance")
    metrics["dividend_yield"] = _yield_record(
        "dividend_yield", dividend, market_cap, period, market_date,
        formula="dividends / dated_market_cap", numerator_sign=1,
        market_sources=market_sources, reason=market_reason,
    )
    metrics["buyback_yield"] = _yield_record(
        "buyback_yield", buyback, market_cap, period, market_date,
        formula="gross_buybacks / dated_market_cap", numerator_sign=1,
        market_sources=market_sources, reason=market_reason,
    )
    metrics["issuance_dilution_yield"] = _yield_record(
        "issuance_dilution_yield", issuance, market_cap, period, market_date,
        formula="-equity_issuance / dated_market_cap", numerator_sign=-1,
        market_sources=market_sources, reason=market_reason,
        sign_convention="negative contribution; positive issuance is subtracted from shareholder yield",
    )
    payout_components = (dividend, buyback, issuance)
    shareholder_value: float | None = None
    shareholder_reason = market_reason or _missing_reason(*payout_components, fallback="payout_components_not_separated")
    if all(item["value"] is not None for item in payout_components) and market_cap is not None and not market_reason:
        values = [float(item["value"]) for item in payout_components]
        if any(value < 0 for value in values):
            shareholder_reason = "payout_amounts_must_be_nonnegative"
        else:
            shareholder_value = (values[0] + values[1] - values[2]) / market_cap
            shareholder_reason = ""
    metrics["shareholder_yield"] = _record(
        "shareholder_yield", shareholder_value,
        "(dividends + gross_buybacks - equity_issuance) / dated_market_cap",
        period, currency=payout_currency, denominator="dated_market_cap", denominator_value=market_cap,
        sign_convention="positive distributions and gross repurchases less positive issuance proceeds",
        source_ids=_sources(dividend, buyback, issuance, extra=market_sources),
        status="available" if shareholder_value is not None else "missing",
        limitation=shareholder_reason,
        unit="ratio",
    )
    metrics["shareholder_yield"]["market_input_date"] = market_date

    buyback_vs_issuance = None
    offset_reason = _missing_reason(buyback, _metric_value(flow_rows, "stock_based_compensation"), issuance, fallback="buyback_sbc_and_issuance_not_separately_reported")
    sbc = _metric_value(flow_rows, "stock_based_compensation")
    offset_currency, offset_currency_reason = _common_currency(buyback, sbc, issuance)
    if all(item["value"] is not None for item in (buyback, sbc, issuance)) and not offset_currency_reason:
        amounts = [float(item["value"]) for item in (buyback, sbc, issuance)]
        if any(value < 0 for value in amounts):
            offset_reason = "buyback_sbc_and_issuance_require_positive_amounts"
        else:
            buyback_vs_issuance = amounts[0] - amounts[1] - amounts[2]
            offset_reason = ""
    if buyback_vs_issuance is None:
        offset_status = "missing"
    elif math.isclose(buyback_vs_issuance, 0.0, abs_tol=1e-12):
        offset_status = "offsets"
    elif buyback_vs_issuance > 0:
        offset_status = "exceeds"
    else:
        offset_status = "does_not_exceed"
    metrics["buybacks_vs_sbc_issuance"] = _record(
        "buybacks_vs_sbc_issuance", buyback_vs_issuance,
        "gross_buybacks - (stock_based_compensation + equity_issuance)",
        period, currency=offset_currency, denominator="none",
        sign_convention="positive means gross buybacks exceed separately reported SBC plus equity issuance; zero means offset",
        source_ids=_sources(buyback, sbc, issuance), status=offset_status,
        limitation=offset_reason, unit="currency",
    )

    action_evidence = _split_factor(
        corporate_actions,
        corporate_action_coverage,
        instrument_id=instrument_id,
        previous_end=previous_end,
        period_end=period_end,
        decision_time=decision_time,
    )
    basic_current = _first_metric_value(point_rows, ("shares_outstanding", "basic_shares"))
    basic_previous = _first_metric_value(previous_rows, ("shares_outstanding", "basic_shares"))
    diluted_current = _metric_value(point_rows, "diluted_shares")
    diluted_previous = _metric_value(previous_rows, "diluted_shares")
    metrics["basic_share_count_change"] = _share_change_record(
        "basic_share_count_change", basic_current, basic_previous, action_evidence, period,
    )
    metrics["diluted_share_count_change"] = _share_change_record(
        "diluted_share_count_change", diluted_current, diluted_previous, action_evidence, period,
    )
    treasury_current = _metric_value(point_rows, "treasury_shares")
    treasury_previous = _metric_value(previous_rows, "treasury_shares")
    metrics["treasury_share_change"] = _treasury_change_record(
        treasury_current, treasury_previous, period,
    )

    reconciliations = _reconciliation_checks(
        flow_rows,
        point_rows,
        previous_rows,
        period=period,
        period_end=period_end,
        previous_end=previous_end,
        action_evidence=action_evidence,
    )
    return metrics, allocation, reconciliations


def _reconciliation_checks(
    flow_rows: pd.DataFrame,
    point_rows: pd.DataFrame,
    previous_rows: pd.DataFrame,
    *,
    period: str,
    period_end: str,
    previous_end: str | None,
    action_evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    flows = {name: _metric_value(flow_rows, name) for name in _CASH_METRICS}
    currency, currency_reason = _common_currency(*(flows[name] for name in _CASH_METRICS))
    if any(flows[name]["value"] is None for name in _CASH_METRICS):
        cash_status = "unavailable"
        residual = None
        reason = _missing_reason(*(flows[name] for name in _CASH_METRICS), fallback="cash_flow_statement_components_missing")
    elif currency_reason:
        cash_status, residual, reason = "unavailable", None, currency_reason
    else:
        expected = sum(float(flows[name]["value"]) for name in _CASH_METRICS[:-1])
        residual = expected - float(flows["cash_net_change"]["value"])
        cash_status = "passed" if math.isclose(residual, 0.0, rel_tol=1e-8, abs_tol=0.01) else "failed"
        reason = "" if cash_status == "passed" else "cash_flow_sections_do_not_reconcile_to_reported_cash_change"
    checks.append(
        _check_record(
            "cash_flow_identity", cash_status,
            "cash_from_operations + cash_from_investing + cash_from_financing + cash_from_fx = cash_net_change",
            period, residual, currency, _sources(*(flows[name] for name in _CASH_METRICS)), reason,
        )
    )

    current_cash = _metric_value(point_rows, "cash")
    prior_cash = _metric_value(previous_rows, "cash")
    if current_cash["value"] is None or prior_cash["value"] is None or flows["cash_net_change"]["value"] is None:
        balance_status, balance_residual = "unavailable", None
        balance_reason = _missing_reason(current_cash, prior_cash, flows["cash_net_change"], fallback="comparable_cash_balances_missing")
    else:
        balance_currency, balance_reason = _common_currency(current_cash, prior_cash, flows["cash_net_change"])
        if balance_reason:
            balance_status, balance_residual = "unavailable", None
        else:
            balance_residual = (float(current_cash["value"]) - float(prior_cash["value"])) - float(flows["cash_net_change"]["value"])
            balance_status = "passed" if math.isclose(balance_residual, 0.0, rel_tol=1e-8, abs_tol=0.01) else "failed"
            if balance_status == "failed":
                balance_reason = "cash_balance_change_does_not_reconcile_to_reported_cash_change"
    checks.append(
        _check_record(
            "cash_balance_change", balance_status,
            "closing_cash - prior_closing_cash = cash_net_change",
            period, balance_residual,
            _common_currency(current_cash, prior_cash, flows["cash_net_change"])[0],
            _sources(current_cash, prior_cash, flows["cash_net_change"]), balance_reason,
        )
    )
    combined = "failed" if "failed" in {cash_status, balance_status} else "passed" if cash_status == balance_status == "passed" else "unavailable"
    combined_reason = "" if combined == "passed" else "cash_flow_or_cash_balance_reconciliation_failed" if combined == "failed" else "cash_flow_or_cash_balance_reconciliation_inputs_missing"
    combined_residual = residual if balance_residual is None else balance_residual if residual is None else max(abs(residual), abs(balance_residual))
    checks.append(
        _check_record(
            "sources_and_uses_to_cash", combined,
            "cash-flow statement sections reconcile to reported net change and closing cash balance",
            period, combined_residual, currency, _sources(*(flows[name] for name in _CASH_METRICS), current_cash, prior_cash), combined_reason,
        )
    )

    action_status = str(action_evidence.get("status", "unavailable"))
    checks.append(
        _check_record(
            "corporate_action_split_coverage", "passed" if action_status == "available" else action_status,
            "share-count comparisons use market_adjustments CorporateAction.quantity_factor for known split actions",
            period, float(action_evidence["split_factor"]) if action_evidence.get("split_factor") is not None else None,
            "not_applicable", tuple(action_evidence.get("source_ids", ())),
            str(action_evidence.get("reason", "")),
        )
    )

    equity_check = _equity_reconciliation(flow_rows, point_rows, previous_rows, period=period)
    checks.append(equity_check)
    share_check = _share_reconciliation(flow_rows, point_rows, previous_rows, period=period, action_evidence=action_evidence)
    checks.append(share_check)
    return checks


def _equity_reconciliation(flow_rows: pd.DataFrame, point_rows: pd.DataFrame, previous_rows: pd.DataFrame, *, period: str) -> dict[str, object]:
    current = _metric_value(point_rows, "equity")
    previous = _metric_value(previous_rows, "equity")
    required_names = ("net_income", "other_comprehensive_income", "dividends", "gross_buybacks", "equity_issuance", "stock_based_compensation")
    items = [_metric_value(flow_rows, name) for name in required_names]
    currency, reason = _common_currency(current, previous, *items)
    if current["value"] is None or previous["value"] is None or any(item["value"] is None for item in items):
        status, residual = "unavailable", None
        reason = reason or _missing_reason(current, previous, *items, fallback="equity_roll_forward_components_missing")
    elif reason:
        status, residual = "unavailable", None
    else:
        net_income, oci, dividends, buybacks, issuance, sbc = (float(item["value"]) for item in items)
        expected_change = net_income + oci - dividends - buybacks + issuance + sbc
        residual = (float(current["value"]) - float(previous["value"])) - expected_change
        status = "passed" if math.isclose(residual, 0.0, rel_tol=1e-8, abs_tol=0.01) else "failed"
        reason = "" if status == "passed" else "equity_statement_does_not_reconcile_to_reported_changes"
    return _check_record(
        "equity_roll_forward", status,
        "closing_equity - prior_equity = net_income + other_comprehensive_income - dividends - gross_buybacks + equity_issuance + stock_based_compensation",
        period, residual, currency, _sources(current, previous, *items), reason,
    )


def _share_reconciliation(flow_rows: pd.DataFrame, point_rows: pd.DataFrame, previous_rows: pd.DataFrame, *, period: str, action_evidence: Mapping[str, object]) -> dict[str, object]:
    checks: list[tuple[str, dict[str, object], dict[str, object]]] = [
        ("shares_outstanding", _first_metric_value(point_rows, ("shares_outstanding", "basic_shares")), _first_metric_value(previous_rows, ("shares_outstanding", "basic_shares"))),
        ("diluted_shares", _metric_value(point_rows, "diluted_shares"), _metric_value(previous_rows, "diluted_shares")),
    ]
    discrepancies: list[float] = []
    source_items: list[dict[str, object]] = []
    for metric, current, previous in checks:
        issued = _metric_value(flow_rows, "shares_issued")
        repurchased = _metric_value(flow_rows, "shares_repurchased")
        if current["value"] is None or previous["value"] is None or issued["value"] is None or repurchased["value"] is None or action_evidence.get("status") != "available":
            return _check_record(
                "share_count_roll_forward", "unavailable",
                "current_shares - prior_shares * split_factor = shares_issued - shares_repurchased",
                period, None, "shares", _sources(current, previous, issued, repurchased),
                "share_issuance_or_repurchase_and_corporate_action_evidence_required",
            )
        factor = float(action_evidence["split_factor"])
        residual = (float(current["value"]) - float(previous["value"]) * factor) - (float(issued["value"]) - float(repurchased["value"]))
        discrepancies.append(residual)
        source_items.extend((current, previous, issued, repurchased))
    worst = max(discrepancies, key=abs, default=0.0)
    status = "passed" if all(math.isclose(value, 0.0, rel_tol=1e-8, abs_tol=0.01) for value in discrepancies) else "failed"
    return _check_record(
        "share_count_roll_forward", status,
        "current_shares - prior_shares * split_factor = shares_issued - shares_repurchased; treasury shares are not added again",
        period, worst, "shares", _sources(*source_items), "" if status == "passed" else "share_count_does_not_reconcile_to_separated_issuance_and_repurchase_flows",
    )


def _split_factor(
    actions: Sequence[CorporateAction],
    coverage: CorporateActionCoverage | None,
    *,
    instrument_id: str | None,
    previous_end: str | None,
    period_end: str,
    decision_time: pd.Timestamp,
) -> dict[str, object]:
    if coverage is None:
        return {"status": "unavailable", "split_factor": None, "source_ids": (), "reason": "corporate_action_coverage_missing"}
    if coverage.status != "active" or (instrument_id and coverage.instrument_id != str(instrument_id)):
        return {"status": "unavailable", "split_factor": None, "source_ids": (), "reason": "corporate_action_coverage_identity_or_status_invalid"}
    try:
        coverage_known = _timestamp(coverage.known_at)
        coverage_through = _timestamp(coverage.coverage_through)
        end = _timestamp(period_end)
    except (TypeError, ValueError):
        coverage_known = coverage_through = end = None
    if coverage_known is None or coverage_through is None or end is None or coverage_known > decision_time or coverage_through < end:
        return {"status": "unavailable", "split_factor": None, "source_ids": (), "reason": "corporate_action_coverage_not_known_through_period_end"}
    start = _timestamp(previous_end) if previous_end else None
    eligible: list[CorporateAction] = []
    for action in actions:
        if action.action_type != "split" or action.status != "active":
            continue
        if instrument_id and action.instrument_id != str(instrument_id):
            continue
        known = _timestamp(action.known_at)
        event = _timestamp(action.event_at)
        if known is None or event is None or known > decision_time or event > end or (start is not None and event <= start):
            continue
        try:
            action.validate()
        except (TypeError, ValueError):
            return {"status": "quarantined", "split_factor": None, "source_ids": (action.source_id,), "reason": "invalid_split_action"}
        eligible.append(action)
    by_action: dict[tuple[str, str], list[CorporateAction]] = defaultdict(list)
    for action in eligible:
        by_action[(action.action_id, action.action_type)].append(action)
    selected: list[CorporateAction] = []
    for candidates in by_action.values():
        reconciliation = reconcile_provider_observations(tuple(candidates))
        if not reconciliation.available or reconciliation.selected_source_id is None:
            return {"status": "quarantined", "split_factor": None, "source_ids": tuple(sorted(item.source_id for item in candidates)), "reason": "conflicted_split_action_evidence"}
        selected.append(next(item for item in candidates if item.source_id == reconciliation.selected_source_id))
    factor = math.prod(float(item.quantity_factor) for item in selected)
    return {
        "status": "available",
        "split_factor": factor,
        "source_ids": tuple(sorted(item.source_id for item in selected)),
        "reason": "",
    }


def _share_change_record(name: str, current: Mapping[str, object], previous: Mapping[str, object], action_evidence: Mapping[str, object], period: str) -> dict[str, object]:
    source_ids = _sources(current, previous, extra=tuple(action_evidence.get("source_ids", ())))
    factor = action_evidence.get("split_factor")
    if current["value"] is None or previous["value"] is None:
        value = None
        limitation = _missing_reason(current, previous, fallback="current_or_prior_share_count_missing")
    elif action_evidence.get("status") != "available" or factor is None:
        value = None
        limitation = str(action_evidence.get("reason") or "corporate_action_evidence_unavailable")
    elif float(previous["value"]) <= 0:
        value = None
        limitation = "prior_share_count_must_be_positive"
    else:
        value = float(current["value"]) / (float(previous["value"]) * float(factor)) - 1.0
        limitation = ""
    return _record(
        name, value,
        "current_shares / (prior_shares * split_quantity_factor) - 1",
        period, currency="not_applicable", denominator="prior_shares * split_quantity_factor",
        denominator_value=None if previous["value"] is None or factor is None else float(previous["value"]) * float(factor),
        sign_convention="positive means share-count growth after known splits; treasury-share movements are not added again",
        source_ids=source_ids, status="available" if value is not None else "missing",
        limitation=limitation, unit="ratio",
    )


def _treasury_change_record(current: Mapping[str, object], previous: Mapping[str, object], period: str) -> dict[str, object]:
    value = None if current["value"] is None or previous["value"] is None else float(current["value"]) - float(previous["value"])
    return _record(
        "treasury_share_change", value, "current_treasury_shares - prior_treasury_shares", period,
        currency="not_applicable", denominator="none",
        sign_convention="reported separately; excluded from share-count change because outstanding shares already reflect treasury shares",
        source_ids=_sources(current, previous), status="available" if value is not None else "missing",
        limitation="treasury_share_history_missing" if value is None else "", unit="shares",
    )


def _market_cap(
    market_inputs: Mapping[str, object],
    point_rows: pd.DataFrame,
    *,
    period_end: str,
    statement_currency: str | None,
) -> tuple[float | None, str | None, str | None, tuple[str, ...], str]:
    market_cap = _finite(market_inputs.get("market_cap"))
    market_date_raw = market_inputs.get("market_cap_at") or market_inputs.get("market_cap_date")
    market_currency = _currency_text(market_inputs.get("currency"))
    market_source = str(market_inputs.get("source_id") or "").strip()
    if market_cap is not None:
        if market_date_raw is None:
            return None, market_currency, None, (market_source,) if market_source else (), "dated_market_cap_missing_date"
        market_date = _date_text(market_date_raw)
        if market_date != _date_text(period_end):
            return None, market_currency, market_date, (market_source,) if market_source else (), "market_cap_date_must_match_statement_period_end"
        if market_cap <= 0:
            return None, market_currency, market_date, (market_source,) if market_source else (), "market_cap_must_be_positive"
        if not market_currency:
            return None, None, market_date, (market_source,) if market_source else (), "market_cap_currency_missing"
        if statement_currency and market_currency != statement_currency:
            return None, market_currency, market_date, (market_source,) if market_source else (), "market_statement_currency_mismatch"
        return market_cap, market_currency, market_date, (market_source,) if market_source else (), ""

    price = _finite(market_inputs.get("share_price"))
    price_date_raw = market_inputs.get("share_price_at") or market_inputs.get("price_at") or market_inputs.get("price_date")
    if price is None:
        return None, None, None, (), "dated_price_or_market_cap_missing"
    if price_date_raw is None:
        return None, market_currency, None, (market_source,) if market_source else (), "dated_share_price_missing_date"
    price_date = _date_text(price_date_raw)
    if price_date != _date_text(period_end):
        return None, market_currency, price_date, (market_source,) if market_source else (), "share_price_date_must_match_statement_period_end"
    shares = _first_metric_value(point_rows, ("shares_outstanding", "basic_shares"))
    if price <= 0 or shares["value"] is None or float(shares["value"]) <= 0:
        return None, market_currency, price_date, _sources(shares, extra=((market_source,) if market_source else ())), "share_price_and_positive_basic_share_count_required"
    if not market_currency:
        return None, None, price_date, _sources(shares, extra=((market_source,) if market_source else ())), "share_price_currency_missing"
    if statement_currency and market_currency != statement_currency:
        return None, market_currency, price_date, _sources(shares, extra=((market_source,) if market_source else ())), "market_statement_currency_mismatch"
    return price * float(shares["value"]), market_currency, price_date, _sources(shares, extra=((market_source,) if market_source else ())), ""


def _yield_record(
    name: str,
    flow: Mapping[str, object],
    market_cap: float | None,
    period: str,
    market_date: str | None,
    *,
    formula: str,
    numerator_sign: int,
    market_sources: Sequence[str],
    reason: str,
    sign_convention: str | None = None,
) -> dict[str, object]:
    flow_value = flow.get("value")
    limitation = reason
    value = None
    if not limitation and flow_value is None:
        limitation = str(flow.get("reason") or "payout_component_missing")
    elif not limitation and market_cap is None:
        limitation = "dated_market_cap_or_price_missing"
    elif not limitation and float(flow_value) < 0:
        limitation = "payout_amount_must_be_nonnegative"
    elif not limitation:
        value = numerator_sign * float(flow_value) / float(market_cap)
    return _record(
        name, value, formula, period,
        currency=flow.get("currency") if flow.get("currency") else "unavailable",
        denominator="dated_market_cap", denominator_value=market_cap,
        sign_convention=sign_convention or "positive payout amount divided by dated market capitalisation",
        source_ids=_sources(flow, extra=market_sources),
        status="available" if value is not None else "missing",
        limitation=limitation,
        unit="ratio",
    )


def _positive_amount_record(name: str, item: Mapping[str, object], period: str, *, sign_convention: str) -> dict[str, object]:
    value = item.get("value")
    limitation = str(item.get("reason") or "")
    if value is not None and float(value) < 0:
        value = None
        limitation = "canonical_amount_must_be_nonnegative"
    return _record(
        name, None if value is None else float(value), f"reported {name}", period,
        currency=item.get("currency") or "unavailable", denominator="none",
        sign_convention=sign_convention, source_ids=_sources(item),
        status="available" if value is not None else "missing", limitation=limitation,
        unit="currency",
    )


def _reported_record(
    name: str,
    item: Mapping[str, object],
    period: str,
    *,
    source_name: str,
    sign_convention: str,
) -> dict[str, object]:
    return _record(
        name, item.get("value"), f"reported {source_name}", period,
        currency=item.get("currency") or ("not_applicable" if name in {"cash_conversion"} else "unavailable"),
        denominator="none", sign_convention=sign_convention, source_ids=_sources(item),
        status="available" if item.get("value") is not None else "missing",
        limitation=str(item.get("reason") or ("statement_metric_missing" if item.get("value") is None else "")),
        unit="currency",
    )


def _ratio_record(
    name: str,
    numerator: Mapping[str, object],
    denominator_value: Mapping[str, object],
    formula: str,
    period: str,
    *,
    denominator: str,
    unit: str,
    currency: str | None,
    invalid_denominator: str,
    shared_reason: str = "",
    numerator_value: float | None = None,
    applicability: str = "applicable",
    limitation: str = "",
) -> dict[str, object]:
    num = numerator.get("value") if numerator_value is None else numerator_value
    den = denominator_value.get("value")
    value = None
    status = "available"
    reason = shared_reason or str(numerator.get("reason") or denominator_value.get("reason") or "")
    if applicability != "applicable":
        status = "not_applicable"
        value = None
    elif num is None or den is None:
        status = "missing"
        reason = reason or "ratio_input_missing"
    elif reason:
        status = "missing"
    elif float(den) <= 0:
        status = "missing"
        reason = invalid_denominator
    else:
        value = float(num) / float(den)
    return _record(
        name, value, formula, period, currency=currency or "unavailable",
        denominator=denominator, denominator_value=None if den is None else float(den),
        sign_convention="signed numerator divided by positive reported denominator",
        source_ids=_sources(numerator, denominator_value), status=status,
        limitation=limitation or reason, unit=unit, applicability=applicability,
    )


def _record(
    name: str,
    value: object,
    formula: str,
    period: str,
    *,
    currency: object,
    denominator: str,
    sign_convention: str,
    source_ids: Sequence[str] = (),
    status: str = "available",
    limitation: str = "",
    unit: str = "currency",
    denominator_value: float | None = None,
    applicability: str = "applicable",
) -> dict[str, object]:
    numeric = _finite(value)
    if value is not None and numeric is None and status == "available":
        status = "missing"
        limitation = limitation or "non_finite_or_non_numeric_value"
    if numeric is None and status == "available":
        status = "missing"
        limitation = limitation or "required_input_missing"
    elif numeric is not None and numeric < 0 and status == "available":
        status = "negative"
    return {
        "name": name,
        "value": numeric,
        "status": status,
        "formula": formula,
        "period": period or "unavailable",
        "source_ids": tuple(sorted({str(item) for item in source_ids if str(item)})),
        "confidence": "high" if numeric is not None and source_ids else "low",
        "applicability": applicability,
        "limitation": limitation,
        "currency": str(currency or "unavailable"),
        "denominator": denominator,
        "denominator_value": denominator_value,
        "sign_convention": sign_convention,
        "unit": unit,
        "execution_allowed": False,
    }


def _check_record(name: str, status: str, formula: str, period: str, value: float | None, currency: str | None, source_ids: Sequence[str], reason: str) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "value": value,
        "formula": formula,
        "period": period,
        "currency": currency or "unavailable",
        "denominator": "none",
        "sign_convention": "absolute residual within the stated tolerance passes; a nonzero residual is flagged",
        "source_ids": tuple(sorted({str(item) for item in source_ids if str(item)})),
        "limitation": reason,
        "tolerance": 0.01,
        "execution_allowed": False,
    }


def _metric_value(rows: pd.DataFrame, metric: str) -> dict[str, object]:
    if rows.empty or "canonical_metric" not in rows or "value" not in rows:
        return {"value": None, "currency": None, "source_ids": (), "reason": "statement_metric_missing"}
    selected = rows.loc[rows["canonical_metric"].astype(str).eq(metric)]
    if selected.empty:
        return {"value": None, "currency": None, "source_ids": (), "reason": f"{metric}_missing"}
    numeric = pd.to_numeric(selected["value"], errors="coerce")
    valid = numeric.map(lambda item: math.isfinite(float(item)) if pd.notna(item) else False)
    selected = selected.loc[valid].copy()
    selected["__numeric"] = numeric.loc[valid].astype(float)
    source_ids = tuple(sorted({str(item) for item in selected.get("source_id", pd.Series(dtype="object")).dropna() if str(item)}))
    if selected.empty:
        return {"value": None, "currency": None, "source_ids": source_ids, "reason": f"{metric}_invalid_value"}
    values = set(float(item) for item in selected["__numeric"].tolist())
    dimensions = {str(item).strip() for item in selected.get("dimensions", pd.Series(dtype="object")).fillna("")}
    if len(values) != 1 or len(dimensions) > 1:
        return {"value": None, "currency": None, "source_ids": source_ids, "reason": f"{metric}_ambiguous_evidence"}
    currencies = {_row_currency(row) for row in selected.to_dict("records")}
    if len(currencies) != 1:
        return {"value": None, "currency": None, "source_ids": source_ids, "reason": f"{metric}_currency_mismatch"}
    currency = next(iter(currencies))
    if currency is None:
        return {"value": None, "currency": None, "source_ids": source_ids, "reason": f"{metric}_currency_missing"}
    return {"value": next(iter(values)), "currency": currency, "source_ids": source_ids, "reason": ""}


def _first_metric_value(rows: pd.DataFrame, names: Sequence[str]) -> dict[str, object]:
    found = [name for name in names if not rows.empty and "canonical_metric" in rows and rows["canonical_metric"].astype(str).eq(name).any()]
    if not found:
        return {"value": None, "currency": None, "source_ids": (), "reason": f"{'_or_'.join(names)}_missing"}
    candidates = [_metric_value(rows, name) for name in found]
    if len(candidates) > 1:
        values = {item["value"] for item in candidates}
        if None in values or len(values) != 1:
            return {"value": None, "currency": None, "source_ids": _sources(*candidates), "reason": "share_count_aliases_ambiguous"}
    return candidates[0]


def _common_currency(*items: Mapping[str, object]) -> tuple[str | None, str]:
    values = [str(item.get("currency")) for item in items if item.get("value") is not None]
    if any(item.get("reason", "").endswith("currency_missing") for item in items if item.get("value") is None):
        return None, "currency_missing"
    if any(item.get("reason", "").endswith("currency_mismatch") for item in items if item.get("value") is None):
        return None, "currency_mismatch"
    if not values:
        return None, ""
    if len(set(values)) != 1:
        return None, "currency_mismatch"
    return values[0], ""


def _sources(*items: Mapping[str, object], extra: Sequence[str] = ()) -> tuple[str, ...]:
    sources = {str(item) for item in extra if str(item)}
    for value in items:
        sources.update(str(item) for item in value.get("source_ids", ()) if str(item))
    return tuple(sorted(sources))


def _missing_reason(*items: Mapping[str, object], fallback: str) -> str:
    reasons = [str(item.get("reason") or "") for item in items if item.get("value") is None]
    reasons = [reason for reason in reasons if reason]
    return ";".join(dict.fromkeys(reasons)) if reasons else fallback


def _flow_periods(frame: pd.DataFrame) -> list[tuple[pd.DataFrame, str, str]]:
    if frame.empty or "canonical_metric" not in frame:
        return []
    flow = frame.loc[~frame.get("period_type", pd.Series(index=frame.index, dtype="object")).astype(str).eq("instant")].copy()
    if flow.empty:
        return []
    for column in ("period_type", "period_key", "period_end", "fiscal_year", "fiscal_period"):
        if column not in flow:
            flow[column] = ""
        flow[column] = flow[column].fillna("").astype(str)
    flow = flow.sort_values(["period_end", "period_type", "period_key"], kind="stable", na_position="last")
    result = []
    group_columns = ["period_type", "period_key", "period_end", "fiscal_year", "fiscal_period"]
    for key, rows in flow.groupby(group_columns, dropna=False, sort=False):
        period_type, period_key, end, fiscal_year, fiscal_period = key
        if not end:
            continue
        label = _period_label(period_key, fiscal_year, fiscal_period, end)
        result.append((rows, label, end[:10]))
    return result


def _period_label(period_key: str, fiscal_year: str, fiscal_period: str, end: str) -> str:
    if fiscal_period == "FY" and fiscal_year:
        return f"FY{fiscal_year}"
    if fiscal_period and fiscal_year:
        return f"{fiscal_year}-{fiscal_period}"
    return period_key or end[:10] or "unavailable"


def _point_rows_for_end(frame: pd.DataFrame, period_end: str | None) -> pd.DataFrame:
    if frame.empty or period_end is None or "period_end" not in frame:
        return pd.DataFrame(columns=frame.columns)
    end_date = _date_text(period_end)
    ends = frame["period_end"].map(lambda item: _date_text(item) if _timestamp(item) is not None else "")
    return frame.loc[ends.eq(end_date)].copy()


def _prior_period_end(periods: Sequence[tuple[pd.DataFrame, str, str]], current_end: str) -> str | None:
    ends = sorted({period_end for _, _, period_end in periods if period_end < current_end})
    return ends[-1] if ends else None


def _exclude_future_periods(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    end_column = "period_end" if "period_end" in result else "end"
    if end_column not in result:
        return result.iloc[0:0].copy()
    ends = result[end_column].map(_timestamp)
    return result.loc[ends.map(lambda item: item is not None and item <= cutoff)].copy()


def _unavailable_metrics(reason: str) -> dict[str, dict[str, object]]:
    return {
        name: _record(
            name, None, f"unavailable:{reason}", "unavailable", currency="unavailable",
            denominator="unavailable", sign_convention="unavailable without decision-time statement evidence",
            status="missing", limitation=reason,
            unit="ratio" if "yield" in name or "margin" in name or "change" in name else "currency",
        )
        for name in _METRIC_NAMES
    }


def _timestamp(value: object) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")


def _date_text(value: object) -> str:
    parsed = _timestamp(value)
    return parsed.date().isoformat() if parsed is not None else ""


def _currency_text(value: object) -> str | None:
    text = str(value or "").strip().upper()
    return text if len(text) == 3 and set(text) <= _CURRENCY_PATTERN else None


def _row_currency(row: Mapping[str, object]) -> str | None:
    currency = _currency_text(row.get("currency"))
    if currency:
        return currency
    unit = str(row.get("unit") or "").strip().casefold()
    if unit in {"shares", "share", "ratio", "percent", "multiple"}:
        return "not_applicable"
    return _currency_text(row.get("unit"))


def _finite(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


__all__ = ["CAPITAL_ALLOCATION_SCHEMA_VERSION", "capital_allocation_analysis"]
