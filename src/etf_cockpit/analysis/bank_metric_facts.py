"""Bank regulatory/profitability metric facts from statement rows (domain calculation; ADR-0002)."""

from collections.abc import Mapping
import math
import pandas as pd

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.analysis.financial_sector_adapters import FinancialMetricEvidence


def _row_period(row: Mapping[str, object]) -> pd.Timestamp | None:
    value = row.get("effective_at") or row.get("end") or row.get("instant") or row.get("period")
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _financial_metric_facts(
    rows: list[dict[str, object]], context: object, cutoff: str, *, target_period: str | None = None
) -> list[FinancialMetricEvidence]:
    from etf_cockpit.analysis.financial_sector_adapters import _METRICS, _REGULATORY

    model = "bank"
    candidates: dict[str, dict[str, object]] = {}
    aliases = {
        "liquidity_coverage_ratio": "liquidity_coverage_ratio",
        "lcr": "liquidity_coverage_ratio",
        "nsfr": "net_stable_funding_ratio",
        "net_stable_funding_ratio": "net_stable_funding_ratio",
        "cet1": "cet1_ratio",
        "cet1_ratio": "cet1_ratio",
        "total_capital": "total_capital_ratio",
        "total_capital_ratio": "total_capital_ratio",
        "leverage": "leverage_ratio",
        "leverage_ratio": "leverage_ratio",
        "net_interest_margin": "net_interest_margin",
        "npl_ratio": "npl_ratio",
        "stage_2_exposure": "stage_2_exposure",
        "stage_3_exposure": "stage_3_exposure",
        "cost_of_risk": "cost_of_risk",
        "dividend": "dividends",
        "dividends": "dividends",
        "retained_earnings": "retained_earnings",
        "net_fee_income": "net_fee_income",
        "fee_income": "net_fee_income",
        "other_operating_income": "other_operating_income",
        "other_income": "other_operating_income",
        "net_profit": "net_profit",
        "net_profit_attributable": "net_profit_attributable",
        "net_income_attributable": "net_profit_attributable",
        "profit_attributable": "net_profit_attributable",
        "opening_equity": "opening_equity",
        "closing_equity": "closing_equity",
        "equity": "closing_equity",
        "opening_tangible_equity": "opening_tangible_equity",
        "closing_tangible_equity": "closing_tangible_equity",
        "tangible_equity": "closing_tangible_equity",
        "interest_earning_assets": "interest_earning_assets",
        "average_interest_earning_assets": "interest_earning_assets",
        "opening_interest_earning_assets": "opening_interest_earning_assets",
        "closing_interest_earning_assets": "closing_interest_earning_assets",
        "total_assets": "total_assets",
        "opening_total_assets": "opening_total_assets",
        "closing_total_assets": "closing_total_assets",
        "gross_loans": "gross_loans",
        "opening_gross_loans": "opening_gross_loans",
        "closing_gross_loans": "closing_gross_loans",
        "impairment_losses": "impairment_losses",
        "loss_allowance": "loss_allowance",
        "shares_outstanding": "shares_outstanding",
        "payout": "payout_headroom",
        "payout_ratio": "payout_headroom",
        "tangible_book_value": "tangible_book_value",
        "price_to_book": "price_to_book",
        "price_to_tangible_book": "price_to_tangible_book",
    }
    derivation_inputs = {
        "loans_to_customers", "deposits_from_customers", "operating_expenses", "net_interest_income",
        "net_fee_income", "other_operating_income", "net_profit", "net_profit_attributable",
        "opening_equity", "closing_equity", "opening_tangible_equity", "closing_tangible_equity",
        "interest_earning_assets", "total_assets", "gross_loans", "impairment_losses", "loss_allowance",
        "opening_interest_earning_assets", "closing_interest_earning_assets", "opening_total_assets", "closing_total_assets",
        "opening_gross_loans", "closing_gross_loans",
        "shares_outstanding",
    }
    for row in rows:
        raw_metric = str(row.get("canonical_metric") or row.get("concept") or "").strip().casefold()
        metric = aliases.get(raw_metric, raw_metric)
        if metric not in _METRICS[model] and metric not in derivation_inputs:
            continue
        if target_period and not metric.startswith("opening_"):
            target = pd.Timestamp(target_period)
            row_period = _row_period(row)
            if row_period is not None and row_period.date() != target.date():
                # Retain a sole comparative so a mismatched-period formula is
                # explicitly unavailable; a requested-period row supersedes it.
                if metric not in candidates:
                    candidates[metric] = row
                continue
        previous = candidates.get(metric)
        if previous is not None and (row["_effective"], row["_known"]) <= (previous["_effective"], previous["_known"]):
            continue
        candidates[metric] = row

    def numeric(row: dict[str, object]) -> float | None:
        try:
            value = float(row.get("value"))
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    def category(row: dict[str, object], metric: str) -> str:
        explicit = str(row.get("fact_category") or "").strip().casefold()
        source = f"{row.get('source_id', '')} {row.get('taxonomy', '')} {row.get('concept', '')}".casefold()
        if explicit in {"pillar3", "regulatory", "market", "issuer_apm", "calculated", "ifrs"}:
            return "pillar3" if explicit == "regulatory" else explicit
        if metric in _REGULATORY and any(token in source for token in ("pillar", "prudential", "regulatory", "eba")):
            return "pillar3"
        if "market" in source or "quote" in source:
            return "market"
        if row.get("is_custom") or "extension" in source:
            return "issuer_apm"
        return "ifrs"

    def fact(
        metric: str,
        value: float | None,
        row: dict[str, object] | None,
        *,
        fact_category: str = "calculated",
        definition: str = "",
        limitations: tuple[str, ...] = (),
        source_id_override: str | None = None,
        inputs: tuple[dict[str, object], ...] = (),
        calculated_period: str | None = None,
        calculated_unit: str | None = None,
    ) -> FinancialMetricEvidence:
        selected = row or {}
        lineage_rows = inputs or ((selected,) if row else ())
        known = max((item.get("_known") for item in lineage_rows if item.get("_known") is not None), default=selected.get("_known"))
        effective = calculated_period or selected.get("_effective")
        def aware_iso(value: object, fallback: str) -> str:
            if value is None:
                return fallback
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize("UTC")
            return stamp.isoformat().replace("+00:00", "Z")
        known_at = aware_iso(known, cutoff)
        as_of = aware_iso(effective, cutoff)
        lineage_ids = tuple(sorted(str(item.get("source_id")) for item in lineage_rows if item.get("source_id")))
        source_id = str(source_id_override or selected.get("source_id") or f"unavailable:{metric}")
        if inputs and lineage_ids:
            source_id = f"{source_id}|inputs={','.join(lineage_ids)}"
        unit = str(calculated_unit or selected.get("unit") or "ratio")
        if value is None:
            unit = (
                "currency_per_share"
                if metric == "tangible_book_value"
                else "currency"
                if metric in {"dividends", "retained_earnings", "issuance_dilution", "residual_income_input"}
                else "ratio"
            )
        if metric in {"dividends", "retained_earnings", "issuance_dilution", "residual_income_input"} and unit.casefold() not in {"shares", "currency_per_share", "currency"}:
            unit = "currency"
        return FinancialMetricEvidence(
            metric=metric,
            value=value,
            unit="percent" if unit.casefold() in {"percent", "%"} else unit,
            period=str(calculated_period or selected.get("fiscal_year") or selected.get("end") or selected.get("instant") or "undated"),
            reporting_standard="IFRS" if fact_category == "ifrs" else fact_category.upper(),
            jurisdiction=str(getattr(context, "operating_country", None) or "NO"),
            business_model=model,
            source_id=source_id,
            source_authority=(
                SourceAuthority.OFFICIAL
                if fact_category in {"ifrs", "pillar3", "regulatory"}
                else SourceAuthority.MANUAL
                if fact_category == "calculated"
                else SourceAuthority.ISSUER
            ),
            as_of=as_of,
            known_at=known_at,
            direction=None,
            fact_category=fact_category,
            definition=definition,
            scope=str(selected.get("consolidation_scope") or (lineage_rows[0].get("consolidation_scope") if lineage_rows else None) or "consolidated"),
            coverage="reported" if row else ("derived" if value is not None else "unavailable"),
            source=";".join(str(item.get("source_url") or item.get("source_id") or "") for item in lineage_rows) or str(selected.get("source_url") or source_id),
            limitations=limitations,
        )

    facts: list[FinancialMetricEvidence] = []
    for metric in sorted(_METRICS[model]):
        row = candidates.get(metric)
        value = numeric(row) if row is not None else None
        category_name = category(row, metric) if row is not None else ("pillar3" if metric in _REGULATORY else "calculated")
        facts.append(fact(metric, value, row, fact_category=category_name))

    def compatible(input_names: tuple[str, ...], *, allow_opening: bool = False) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
        selected: list[dict[str, object]] = []
        for name in input_names:
            item = candidates.get(name)
            if item is None and allow_opening and name.startswith("opening_"):
                continue
            if item is None:
                return (), ("missing_input",)
            selected.append(item)
        if not selected:
            return (), ("missing_input",)
        reasons: set[str] = set()
        periods = {_row_period(item).date() for item in selected if _row_period(item) is not None and not (allow_opening and str(item.get("canonical_metric") or "").casefold().startswith("opening_"))}
        if len(periods) > 1:
            reasons.add("period_mismatch")
        currencies = {str(item.get("currency") or str(item.get("unit") or "").split("/", 1)[0]).upper() for item in selected if item.get("currency") or item.get("unit")}
        if len(currencies) > 1:
            reasons.add("currency_mismatch")
        scopes = {str(item.get("consolidation_scope") or "consolidated").casefold() for item in selected}
        if len(scopes) > 1:
            reasons.add("scope_mismatch")
        if target_period:
            target = pd.Timestamp(target_period).date()
            if any(_row_period(item) is not None and _row_period(item).date() != target and not (allow_opening and str(item.get("canonical_metric") or "").casefold().startswith("opening_")) for item in selected):
                reasons.add("period_mismatch")
        return tuple(selected), tuple(sorted(reasons))

    def emit(metric: str, result: float | None, inputs: tuple[dict[str, object], ...], reasons: tuple[str, ...], definition: str, *, unit: str = "ratio", period: str | None = None) -> None:
        facts[:] = [item for item in facts if item.metric != metric]
        limitations = reasons or (() if result is not None else ("missing_input",))
        inferred_period = _row_period(inputs[0]).date().isoformat() if inputs and _row_period(inputs[0]) is not None else cutoff
        facts.append(fact(metric, result, None, definition=definition, limitations=limitations, source_id_override=f"calculated:{metric}", inputs=inputs, calculated_period=period or target_period or inferred_period, calculated_unit=unit))

    selected, reasons = compatible(("loans_to_customers", "deposits_from_customers"))
    denom = selected[1].get("value") if len(selected) == 2 else None
    emit("loan_deposit_ratio", None if reasons or denom is None or float(denom) <= 0 else float(selected[0].get("value")) / float(denom), selected, reasons + (("invalid_denominator",) if denom is None or (denom is not None and float(denom) <= 0) else ()), "loans_to_customers / deposits_from_customers")

    selected, reasons = compatible(("operating_expenses", "net_interest_income", "net_fee_income", "other_operating_income"))
    income = sum(float(item.get("value")) for item in selected[1:]) if len(selected) == 4 else None
    emit("cost_income_ratio", None if reasons or income is None or income <= 0 else float(selected[0].get("value")) / income, selected, reasons + (("invalid_denominator",) if income is None or (income is not None and income <= 0) else ()), "operating_expenses / (net_interest_income + net_fee_income + other_operating_income)")

    selected, reasons = compatible(("net_profit_attributable", "opening_equity", "closing_equity"), allow_opening=True)
    opening = candidates.get("opening_equity")
    closing = candidates.get("closing_equity")
    roe_inputs = tuple(item for item in (candidates.get("net_profit_attributable"), opening, closing) if item is not None)
    average_equity = (float(opening.get("value")) + float(closing.get("value"))) / 2 if opening and closing else None
    emit("roe", None if reasons or average_equity is None or average_equity <= 0 else float(candidates["net_profit_attributable"].get("value")) / average_equity, roe_inputs, reasons + (("missing_opening_equity",) if opening is None else ()) + (("invalid_denominator",) if average_equity is None or (average_equity is not None and average_equity <= 0) else ()), "net_profit_attributable / average(opening_equity, closing_equity)")

    selected, reasons = compatible(("net_profit_attributable", "opening_tangible_equity", "closing_tangible_equity"), allow_opening=True)
    opening = candidates.get("opening_tangible_equity")
    closing = candidates.get("closing_tangible_equity")
    rote_inputs = tuple(item for item in (candidates.get("net_profit_attributable"), opening, closing) if item is not None)
    average_tangible = (float(opening.get("value")) + float(closing.get("value"))) / 2 if opening and closing else None
    emit("rote", None if reasons or average_tangible is None or average_tangible <= 0 else float(candidates["net_profit_attributable"].get("value")) / average_tangible, rote_inputs, reasons + (("missing_opening_tangible_equity",) if opening is None else ()) + (("invalid_denominator",) if average_tangible is None or (average_tangible is not None and average_tangible <= 0) else ()), "net_profit_attributable / average(opening_tangible_equity, closing_tangible_equity)")

    base = candidates.get("net_interest_income")
    assets_open = candidates.get("opening_interest_earning_assets")
    assets_close = candidates.get("closing_interest_earning_assets")
    if assets_open and assets_close:
        selected, reasons = compatible(("net_interest_income", "opening_interest_earning_assets", "closing_interest_earning_assets"), allow_opening=True)
        denominator = (float(assets_open.get("value")) + float(assets_close.get("value"))) / 2
        nim_definition = "net_interest_income / average(interest_earning_assets)"
    else:
        selected, reasons = compatible(("net_interest_income", "interest_earning_assets"))
        if len(selected) != 2:
            assets_open = candidates.get("opening_total_assets")
            assets_close = candidates.get("closing_total_assets")
            if assets_open and assets_close:
                selected, reasons = compatible(("net_interest_income", "opening_total_assets", "closing_total_assets"), allow_opening=True)
                denominator = (float(assets_open.get("value")) + float(assets_close.get("value"))) / 2
            else:
                selected, reasons = compatible(("net_interest_income", "total_assets"))
                denominator = float(selected[1].get("value")) if len(selected) == 2 else None
            nim_definition = "net_interest_income / average(total_assets) (disclosed proxy)"
        else:
            nim_definition = "net_interest_income / average(interest_earning_assets)"
            denominator = float(selected[1].get("value"))
    emit("net_interest_margin", None if reasons or base is None or denominator is None or denominator <= 0 else float(base.get("value")) / denominator, selected, reasons + (("invalid_denominator",) if denominator is None or denominator <= 0 else ()), nim_definition)

    loans_open = candidates.get("opening_gross_loans")
    loans_close = candidates.get("closing_gross_loans")
    if loans_open and loans_close:
        selected, reasons = compatible(("impairment_losses", "opening_gross_loans", "closing_gross_loans"), allow_opening=True)
        denominator = (float(loans_open.get("value")) + float(loans_close.get("value"))) / 2
    else:
        selected, reasons = compatible(("impairment_losses", "gross_loans"))
        denominator = float(selected[1].get("value")) if len(selected) == 2 else None
    emit("cost_of_risk", None if reasons or len(selected) < 2 or denominator is None or denominator <= 0 else float(selected[0].get("value")) / denominator, selected, reasons + (("invalid_denominator",) if denominator is None or denominator <= 0 else ()), "impairment_losses / average(gross_loans)")
    selected, reasons = compatible(("loss_allowance", "stage_3_exposure"))
    emit("coverage_ratio", None if reasons or len(selected) != 2 or float(selected[1].get("value")) <= 0 else float(selected[0].get("value")) / float(selected[1].get("value")), selected, reasons + (("invalid_denominator",) if len(selected) != 2 or float(selected[1].get("value")) <= 0 else ()), "loss_allowance / stage_3_exposure")
    selected, reasons = compatible(("dividends", "net_profit"))
    emit("payout_headroom", None if reasons or len(selected) != 2 or float(selected[1].get("value")) == 0 else float(selected[0].get("value")) / float(selected[1].get("value")), selected, reasons + (("invalid_denominator",) if len(selected) != 2 or float(selected[1].get("value")) == 0 else ()), "dividends / net_profit")
    return facts
