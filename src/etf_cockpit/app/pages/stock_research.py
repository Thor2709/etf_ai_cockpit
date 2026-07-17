from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, metric_card, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    STATEMENT_FACTS_PATH,
    build_stock_research_report,
    load_stock_research_frame,
)


def stock_research_page(_page: ft.Page, state: AppState) -> ft.Control:
    instrument_id = str(getattr(state, "selected_etf", "") or state.snapshot.config.ui.default_etf)
    statements = load_stock_research_frame(STATEMENT_FACTS_PATH, instrument_id=instrument_id)
    report = build_stock_research_report(statements, instrument_id=instrument_id, market_inputs={}, assumptions={})
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Stock Research", "Transparent statement-derived evidence. Reported facts, derived metrics and valuation assumptions remain separate."),
                        ft.Row([evidence_chip("Instrument", instrument_id or "unselected", theme.CYAN), evidence_chip("Statement view", "latest restated", theme.BLUE_GREY), evidence_chip("Execution", "disabled", theme.GREEN)], wrap=True),
                    ],
                    spacing=8,
                )
            ),
            _metrics_panel("Profitability", "Margins, returns, cash conversion and history are formula-labelled; peer percentiles are descriptive only.", report["profitability"]),
            _metrics_panel("Earnings quality", "Accruals, exceptional-item dependence, margin stability and transparent quality components.", report["profitability"]),
            _metrics_panel("Balance sheet", "Debt, liquidity, working capital and source-linked coverage; missing maturities remain unavailable.", report["balance_sheet"]),
            _metrics_panel("Solvency", "Stress scenarios and contextual distress evidence; this is not a credit rating or execution authority.", report["balance_sheet"]),
            _valuation_panel(report["valuation"]),
            panel(ft.Text("All stock research outputs are evidence-only and carry execution_allowed=false. Import an official local statement package to replace the explicit unavailable state.", color=theme.MUTED, selectable=True)),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _metrics_panel(title: str, description: str, section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    metrics = value.get("metrics", {}) if isinstance(value, dict) else {}
    cards = []
    for name in list(metrics)[:6]:
        item = metrics[name]
        if not isinstance(item, dict):
            continue
        display = "n/a" if item.get("value") is None else f"{float(item['value']):.3f}"
        cards.append(metric_card(name.replace("_", " ").title(), display, str(item.get("status", "unavailable"))))
    if not cards:
        cards = [metric_card("Evidence", "Unavailable", "No canonical statement rows")]
    return panel(ft.Column([section_header(title, description), ft.Row(cards, wrap=True, spacing=10), ft.Text(f"Source lineage: {value.get('source_lineage', {}).get('source_ids', []) if isinstance(value, dict) else []}; execution_allowed=false", color=theme.MUTED, selectable=True)], spacing=8))


def _valuation_panel(section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    intrinsic = value.get("intrinsic_value", {}) if isinstance(value, dict) else {}
    relative = value.get("relative_metrics", {}) if isinstance(value, dict) else {}
    status = str(intrinsic.get("status", "unavailable")) if isinstance(intrinsic, dict) else "unavailable"
    multiples = ", ".join(f"{name.replace('_', ' ')}={item.get('value', 'n/a')}" for name, item in relative.items() if isinstance(item, dict)) or "No relative valuation inputs available."
    return panel(ft.Column([section_header("Valuation Lab", "Relative valuation, intrinsic-value scenarios, reverse DCF and residual income require explicit local assumptions."), ft.Text(f"Relative measures: {multiples}", color=theme.MUTED, selectable=True), ft.Text(f"Intrinsic scenarios: {status}; reverse DCF={value.get('reverse_dcf', {}).get('status', 'unavailable')}; residual income={value.get('residual_income', {}).get('status', 'unavailable')}; no single fair-value point is presented.", color=theme.AMBER if status != "available" else theme.CYAN, selectable=True), ft.Text("execution_allowed=false", color=theme.GREEN, selectable=True)], spacing=8))


__all__ = ["stock_research_page"]
