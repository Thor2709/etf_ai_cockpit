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
            _growth_panel(report["growth"]),
            _expectations_panel(report["expectations"]),
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


def _growth_panel(section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    series = value.get("series", {}) if isinstance(value, dict) else {}
    aggregate = series.get("aggregate", {}) if isinstance(series, dict) else {}
    per_share = series.get("per_share", {}) if isinstance(series, dict) else {}
    cards = []
    for name, item in list(aggregate.items())[:3] + list(per_share.items())[:2]:
        if not isinstance(item, dict):
            continue
        latest = item.get("latest_growth") if isinstance(item.get("latest_growth"), dict) else {}
        cards.append(metric_card(name.replace("_", " ").title(), _research_value(latest.get("value")), str(latest.get("status", item.get("status", "unavailable")))))
    if not cards:
        cards = [metric_card("Reported growth", "n/a", "No canonical statement rows")]
    organic = value.get("organic_inorganic", {}) if isinstance(value, dict) else {}
    lineage = value.get("source_lineage", {}) if isinstance(value, dict) else {}
    source_ids = lineage.get("source_ids", []) if isinstance(lineage, dict) else []
    history = []
    for name, item in list(aggregate.items())[:3] + list(per_share.items())[:2]:
        if not isinstance(item, dict):
            continue
        latest = item.get("latest_growth") if isinstance(item.get("latest_growth"), dict) else {}
        history.append(f"{name}: {len(item.get('history', []))} periods; status={latest.get('status', item.get('status', 'unavailable'))}; base_effect={latest.get('base_effect', 'n/a')}; formula={item.get('formula', 'n/a')}")
    history_text = " | ".join(history) or "No period history available."
    return panel(ft.Column([section_header("Growth", "Reported aggregate and per-share growth are formula-labelled. Base effects and organic/inorganic evidence stay explicit."), ft.Row(cards, wrap=True, spacing=10), ft.Text(f"Period history: {history_text}", color=theme.MUTED, selectable=True), ft.Text(f"Organic/inorganic evidence: {organic.get('status', 'unavailable')}; acquisition flags={len(organic.get('acquisition_flags', [])) if isinstance(organic, dict) else 0}; source lineage={source_ids}; execution_allowed=false", color=theme.MUTED, selectable=True)], spacing=8))


def _expectations_panel(section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    consensus = value.get("consensus", {}) if isinstance(value, dict) else {}
    guidance = value.get("guidance", {}) if isinstance(value, dict) else {}
    consensus_status = consensus.get("status", "unavailable") if isinstance(consensus, dict) else "unavailable"
    guidance_status = guidance.get("status", "unavailable") if isinstance(guidance, dict) else "unavailable"
    return panel(ft.Column([section_header("Growth & Expectations", "Realised reported growth, reviewed management guidance and optional licensed point-in-time consensus are separate evidence classes."), ft.Text(f"Reported: available in the Growth panel; Management guidance: {guidance_status}; Optional consensus: {consensus_status}.", color=theme.MUTED, selectable=True), ft.Text("Consensus, revisions, dispersion, surprises and staleness remain n/a without point-in-time licensed evidence. Current analyst fields are rejected.", color=theme.AMBER, selectable=True), ft.Text("execution_allowed=false", color=theme.GREEN, selectable=True)], spacing=8))


def _research_value(value: object) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100.0:.2f}%"
    except (TypeError, ValueError):
        return str(value)


__all__ = ["stock_research_page"]
