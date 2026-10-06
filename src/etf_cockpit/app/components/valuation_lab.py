"""Stock Valuation Lab panel (split from the stock research page so each page keeps its own control inventory)."""

from __future__ import annotations

import json
import math

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import section_header
from etf_cockpit.app.components.research_surface import panel
from etf_cockpit.application.ui_facade import build_stock_research_report, load_valuation_market_inputs

def _valuation_panel(
    section: object,
    *,
    on_calculate: object = None,
    page: object | None = None,
) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    field_names = (
        "forecast_years", "discount_rate", "cost_of_equity", "terminal_growth",
        "sustainable_roe", "sustainable_rote", "regulatory_capital_assumptions",
        "bear_growth", "bear_fcf_margin", "base_growth", "base_fcf_margin",
        "bull_growth", "bull_fcf_margin", "sensitivity_discount_rates", "sensitivity_terminal_growth_rates",
        "sensitivity_roe_rates", "sensitivity_rote_rates",
    )
    fields = {
        name: ft.TextField(
            label={
                "forecast_years": "Forecast years",
                "discount_rate": "Discount rate (%)",
                "cost_of_equity": "Cost of equity (%)",
                "terminal_growth": "Terminal growth (%)",
                "sustainable_roe": "Sustainable ROE (%)",
                "sustainable_rote": "Sustainable ROTE (%)",
                "regulatory_capital_assumptions": "Regulatory-capital assumptions (JSON)",
                "bear_growth": "Bear growth (%)",
                "bear_fcf_margin": "Bear FCF margin (%)",
                "base_growth": "Base growth (%)",
                "base_fcf_margin": "Base FCF margin (%)",
                "bull_growth": "Bull growth (%)",
                "bull_fcf_margin": "Bull FCF margin (%)",
                "sensitivity_discount_rates": "Sensitivity discount/cost-of-equity rates (%)",
                "sensitivity_terminal_growth_rates": "Sensitivity terminal growth (%)",
                "sensitivity_roe_rates": "Sensitivity sustainable ROE (%)",
                "sensitivity_rote_rates": "Sensitivity sustainable ROTE (%)",
            }[name],
            value="",
            width=180,
        )
        for name in field_names
    }
    results = ft.Container(content=_valuation_summary(value), data="stock-research.valuation-results")

    def calculate(_event: ft.ControlEvent) -> None:
        if not callable(on_calculate):
            return
        assumptions, error = _valuation_assumptions(fields)
        updated = (
            {"status": "unavailable", "reason": error, "execution_allowed": False}
            if error
            else on_calculate(assumptions)
        )
        results.content = _valuation_summary(updated if isinstance(updated, dict) else {})
        update = getattr(page, "update", None)
        if callable(update):
            update()

    controls = ft.Row(list(fields.values()), wrap=True, spacing=8, run_spacing=4)
    calculate_button = ft.Button("Calculate valuation snapshot", on_click=calculate, key="stock-research.calculate-valuation")
    return panel(
        ft.Column(
            [
                section_header("Valuation Lab", "Calculated issuer multiples and scenario ranges use the displayed point-in-time evidence. No scenario probabilities are assigned."),
                _selectable_text("Enter annual rates, growth and free-cash-flow margins as percentages. Leave any unsupported input blank; the related model stays unavailable.", color=theme.MUTED),
                controls,
                calculate_button,
                results,
                _selectable_text("Assumptions are session-local and versioned in the generated snapshot. execution_allowed=false", color=theme.GREEN),
            ],
            spacing=8,
        )
    )


def _valuation_assumptions(fields: dict[str, ft.TextField]) -> tuple[dict[str, object], str | None]:
    def numeric(name: str, *, percent: bool = False) -> float | None:
        raw = str(fields[name].value or "").strip()
        if not raw:
            return None
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"{name.replace('_', ' ')} must be finite")
        return value / 100.0 if percent else value

    try:
        assumptions: dict[str, object] = {"version": "valuation_assumptions.v1"}
        years = numeric("forecast_years")
        if years is not None:
            if not years.is_integer():
                raise ValueError("forecast years must be a whole number")
            assumptions["forecast_years"] = int(years)
        for name in ("discount_rate", "cost_of_equity", "terminal_growth", "sustainable_roe", "sustainable_rote"):
            number = numeric(name, percent=True)
            if number is not None:
                assumptions[name] = number
        scenarios = {}
        for name in ("bear", "base", "bull"):
            growth = numeric(f"{name}_growth", percent=True)
            margin = numeric(f"{name}_fcf_margin", percent=True)
            if growth is not None:
                scenarios[name] = {"growth": growth, "margin": margin}
        if scenarios:
            assumptions["scenarios"] = scenarios
        capital_raw = str(fields["regulatory_capital_assumptions"].value or "").strip()
        if capital_raw:
            capital_assumptions = json.loads(capital_raw)
            if not isinstance(capital_assumptions, dict):
                raise ValueError("regulatory-capital assumptions must be a JSON object")
            assumptions["regulatory_capital_assumptions"] = capital_assumptions
        raw_discount = str(fields["sensitivity_discount_rates"].value or "").strip()
        raw_terminal = str(fields["sensitivity_terminal_growth_rates"].value or "").strip()
        raw_roe = str(fields["sensitivity_roe_rates"].value or "").strip()
        raw_rote = str(fields["sensitivity_rote_rates"].value or "").strip()
        if raw_discount or raw_terminal or raw_roe or raw_rote:
            def parse_range(raw: str) -> list[float]:
                return [float(item.strip()) / 100.0 for item in raw.split(",") if item.strip()]

            discount_values = parse_range(raw_discount)
            terminal_values = parse_range(raw_terminal)
            roe_values = parse_range(raw_roe)
            rote_values = parse_range(raw_rote)
            if any(not math.isfinite(item) for item in discount_values + terminal_values + roe_values + rote_values):
                raise ValueError("sensitivity rates must be finite")
            assumptions["sensitivity"] = {
                "discount_rates": discount_values,
                "cost_of_equity_rates": discount_values,
                "terminal_growth_rates": terminal_values,
                "sustainable_roe_rates": roe_values,
                "sustainable_rote_rates": rote_values,
            }
        return assumptions, None
    except (ValueError, OverflowError, json.JSONDecodeError) as exc:
        return {}, str(exc)


def _valuation_summary(section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    intrinsic = value.get("intrinsic_value", {}) if isinstance(value.get("intrinsic_value"), dict) else {}
    evidence = value.get("market_evidence", {}) if isinstance(value.get("market_evidence"), dict) else {}
    relative = value.get("relative_metrics", {}) if isinstance(value.get("relative_metrics"), dict) else {}
    multiples = ", ".join(
        f"{name.replace('_', ' ')}={_research_number(item.get('value'))} ({item.get('status', 'unavailable')}; calculated from underlying facts)"
        for name, item in relative.items()
        if isinstance(item, dict)
    ) or "No calculated issuer multiples are available."
    scenarios = intrinsic.get("scenarios", {}) if isinstance(intrinsic.get("scenarios"), dict) else {}
    scenario_text = "; ".join(
        f"{name}: {_research_number(item.get('per_share'))} per share; growth={_research_value(item.get('growth'))}; FCF margin={_research_value(item.get('margin'))}"
        for name, item in scenarios.items()
        if isinstance(item, dict)
    ) or str(intrinsic.get("reason", intrinsic.get("status", "unavailable")))
    snapshot_text = (
        f"Valuation date={evidence.get('valuation_date', 'unavailable')}; price close={evidence.get('price_timestamp', 'unavailable')} "
        f"price={_research_number(evidence.get('share_price_native'))} {evidence.get('price_currency', 'unavailable')}; "
        f"reporting price={_research_number(evidence.get('share_price'))} {evidence.get('reporting_currency', 'unavailable')}; "
        f"diluted shares={_research_number(evidence.get('shares_outstanding'))}; market cap={_research_number(evidence.get('market_cap'))}; "
        f"net debt={_research_number(evidence.get('net_debt'))}; enterprise value={_research_number(evidence.get('enterprise_value'))}; "
        f"EV adjustments={evidence.get('enterprise_value_adjustments', {}).get('status', 'unavailable') if isinstance(evidence.get('enterprise_value_adjustments'), dict) else 'unavailable'}; "
        f"price staleness={evidence.get('price_staleness', 'unavailable')}; warnings={evidence.get('warnings', [])}; "
        f"FX timestamp={evidence.get('currency_conversion_timestamp', 'not required')}; filing vintage={evidence.get('filing_vintage', 'unavailable')}; "
        f"risk-free reference={_research_value(evidence.get('risk_free_reference', {}).get('rate')) if isinstance(evidence.get('risk_free_reference'), dict) else 'unavailable'} "
        f"vintage={evidence.get('risk_free_reference', {}).get('available_at', 'unavailable') if isinstance(evidence.get('risk_free_reference'), dict) else 'unavailable'}; "
        f"benchmark={evidence.get('benchmark_context', {})}"
    )
    reverse = value.get("reverse_dcf", {}) if isinstance(value.get("reverse_dcf"), dict) else {}
    residual = value.get("residual_income", {}) if isinstance(value.get("residual_income"), dict) else {}
    sensitivity = value.get("sensitivity", {}) if isinstance(value.get("sensitivity"), dict) else {}
    sensitivity_ranges = sensitivity.get("grid", {}) if isinstance(sensitivity.get("grid"), dict) else {}
    sensitivity_text = "; ".join(
        f"{name} per-share range={item.get('range', [])}"
        for name, item in sensitivity_ranges.items()
        if isinstance(item, dict)
    ) or str(sensitivity.get("reason", sensitivity.get("status", "unavailable")))
    bank_route = value.get("bank_route", {}) if isinstance(value.get("bank_route"), dict) else {}
    bank_metrics = bank_route.get("metrics", {}) if isinstance(bank_route.get("metrics"), dict) else {}
    peer_context = value.get("peer_context", {}) if isinstance(value.get("peer_context"), dict) else {}
    peer_relative = value.get("peer_relative_metrics", {}) if isinstance(value.get("peer_relative_metrics"), dict) else {}
    peer_metrics = peer_relative.get("metrics", {}) if isinstance(peer_relative.get("metrics"), dict) else {}
    peer_values = "; ".join(
        f"{name} median={_research_number(item.get('median'))}; range={item.get('range')}; n={item.get('peer_count')}"
        for name, item in peer_metrics.items()
        if isinstance(item, dict)
    ) or str(peer_relative.get("status", "unavailable"))
    lines = [
        _selectable_text(f"Market snapshot: {snapshot_text}", color=theme.MUTED),
        _selectable_text(f"Relative issuer measures: {multiples}; provider-reported multiples are unavailable unless separately evidenced.", color=theme.MUTED),
        _selectable_text(f"DCF scenarios: {scenario_text}; DCF per-share range={intrinsic.get('range', [])}; reverse DCF={reverse.get('status', 'unavailable')} ({reverse.get('reason', 'no explicit reverse-DCF result')}); residual income={residual.get('status', 'unavailable')} per share={_research_number(residual.get('per_share'))} ({residual.get('reason', 'no explicit residual-income result')}; net-income basis={residual.get('net_income_basis', 'unavailable')}).", color=theme.CYAN if intrinsic.get("status") == "available" else theme.AMBER),
        _selectable_text(f"Sensitivity={sensitivity.get('status', 'unavailable')}; ranges={sensitivity_text}; peers={peer_context.get('peer_ids', [])}; period={peer_context.get('period', [])}; scope={peer_context.get('accounting_scope', [])}; currency={peer_context.get('currency', [])}; outlier treatment={peer_context.get('outlier_treatment', 'unavailable')}", color=theme.MUTED),
        _selectable_text(f"Peer multiples: {peer_values}; period basis={peer_relative.get('period_basis', 'unavailable')}; currency basis={peer_relative.get('currency_basis', 'unavailable')}; scope={peer_relative.get('accounting_scope', 'unavailable')}", color=theme.MUTED),
        _selectable_text(f"Bank route={bank_route.get('path', 'not_applicable')}; sustainable ROE={_research_value(bank_metrics.get('sustainable_roe'))}; sustainable ROTE={_research_value(bank_metrics.get('sustainable_rote'))}; cost of equity={_research_value(bank_metrics.get('cost_of_equity'))}; regulatory-capital assumptions={bank_metrics.get('regulatory_capital_assumptions', 'not supplied')}", color=theme.MUTED),
    ]
    return ft.Column(lines, spacing=4)


def _recalculate_valuation(
    statements: pd.DataFrame,
    report_arguments: dict[str, object],
    *,
    instrument_id: str,
    decision_time: object,
    benchmark_context: dict[str, object],
    assumptions: dict[str, object],
) -> dict[str, object]:
    market_inputs = load_valuation_market_inputs(
        instrument_id,
        statements=statements,
        decision_time=decision_time,
        assumptions=assumptions,
        benchmark_context=benchmark_context,
    )
    updated = build_stock_research_report(
        statements,
        **(report_arguments | {"market_inputs": market_inputs, "assumptions": assumptions}),
    )
    valuation = updated.get("valuation")
    return valuation if isinstance(valuation, dict) else {"status": "unavailable", "reason": "Valuation calculation did not produce a result."}


def _selectable_text(value: str, *, color: str) -> ft.SelectionArea:
    """Keep evidence copyable without Flet's oversized selectable Text overlay."""
    return ft.SelectionArea(ft.Text(value, color=color))


def _research_number(value: object) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)


def _research_value(value: object) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100.0:.2f}%"
    except (TypeError, ValueError):
        return str(value)
