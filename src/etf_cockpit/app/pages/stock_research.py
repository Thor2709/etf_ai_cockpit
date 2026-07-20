from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, metric_card, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    CONSENSUS_IMPORT_PATH,
    GUIDANCE_IMPORT_PATH,
    STATEMENT_FACTS_PATH,
    build_stock_research_report,
    load_optional_research_import,
    load_stock_research_frame,
)


def stock_research_page(_page: ft.Page, state: AppState) -> ft.Control:
    instrument_id = str(getattr(state, "selected_etf", "") or state.snapshot.config.ui.default_etf)
    statements = load_stock_research_frame(STATEMENT_FACTS_PATH, instrument_id=instrument_id)
    consensus = load_optional_research_import(CONSENSUS_IMPORT_PATH, instrument_id=instrument_id)
    guidance = load_optional_research_import(GUIDANCE_IMPORT_PATH, instrument_id=instrument_id)
    report = build_stock_research_report(statements, instrument_id=instrument_id, market_inputs={}, assumptions={}, expectation_evidence=consensus, guidance_evidence=guidance)
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
            panel(_selectable_text("All stock research outputs are evidence-only and carry execution_allowed=false. Import an official local statement package to replace the explicit unavailable state.", color=theme.MUTED)),
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
    return panel(ft.Column([section_header(title, description), _metric_cards(cards), _selectable_text(f"Source lineage: {value.get('source_lineage', {}).get('source_ids', []) if isinstance(value, dict) else []}; execution_allowed=false", color=theme.MUTED)], spacing=8))


def _valuation_panel(section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    intrinsic = value.get("intrinsic_value", {}) if isinstance(value, dict) else {}
    relative = value.get("relative_metrics", {}) if isinstance(value, dict) else {}
    status = str(intrinsic.get("status", "unavailable")) if isinstance(intrinsic, dict) else "unavailable"
    multiples = ", ".join(f"{name.replace('_', ' ')}={item.get('value', 'n/a')}" for name, item in relative.items() if isinstance(item, dict)) or "No relative valuation inputs available."
    return panel(ft.Column([section_header("Valuation Lab", "Relative valuation, intrinsic-value scenarios, reverse DCF and residual income require explicit local assumptions."), _selectable_text(f"Relative measures: {multiples}", color=theme.MUTED), _selectable_text(f"Intrinsic scenarios: {status}; reverse DCF={value.get('reverse_dcf', {}).get('status', 'unavailable')}; residual income={value.get('residual_income', {}).get('status', 'unavailable')}; no single fair-value point is presented.", color=theme.AMBER if status != "available" else theme.CYAN), _selectable_text("execution_allowed=false", color=theme.GREEN)], spacing=8))


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
    return panel(ft.Column([section_header("Growth", "Reported aggregate and per-share growth are formula-labelled. Base effects and organic/inorganic evidence stay explicit."), _metric_cards(cards), _selectable_text(f"Period history: {history_text}", color=theme.MUTED), _selectable_text(f"Organic/inorganic evidence: {organic.get('status', 'unavailable')}; acquisition flags={len(organic.get('acquisition_flags', [])) if isinstance(organic, dict) else 0}; source lineage={source_ids}; execution_allowed=false", color=theme.MUTED)], spacing=8))


def _expectations_panel(section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    consensus = value.get("consensus", {}) if isinstance(value, dict) else {}
    guidance = value.get("guidance", {}) if isinstance(value, dict) else {}
    consensus_status = consensus.get("status", "unavailable") if isinstance(consensus, dict) else "unavailable"
    guidance_status = guidance.get("status", "unavailable") if isinstance(guidance, dict) else "unavailable"
    guidance_rejected = len(guidance.get("rejected_records", [])) if isinstance(guidance, dict) else 0
    consensus_rejected = len(consensus.get("rejected_records", [])) if isinstance(consensus, dict) else 0
    return panel(ft.Column([section_header("Growth & Expectations", "Realised reported growth, reviewed management guidance and optional licensed point-in-time consensus are separate evidence classes."), _selectable_text("Reported growth: available in the separate Growth panel.", color=theme.MUTED), _selectable_text(f"Management guidance ({guidance_status})\n" + "\n".join(_guidance_lines(guidance)), color=theme.CYAN if guidance_status == "available" else theme.MUTED), _selectable_text(f"Optional consensus ({consensus_status})\n" + "\n".join(_consensus_lines(consensus)), color=theme.CYAN if consensus_status == "available" else theme.MUTED), _selectable_text(f"Rejected import records: guidance={guidance_rejected}; consensus={consensus_rejected}. Current or unlicensed analyst fields are rejected.", color=theme.AMBER), _selectable_text(f"Local import paths: {GUIDANCE_IMPORT_PATH} | {CONSENSUS_IMPORT_PATH}", color=theme.MUTED), _selectable_text("execution_allowed=false", color=theme.GREEN)], spacing=8))


def _selectable_text(value: str, *, color: str) -> ft.SelectionArea:
    """Keep evidence copyable without Flet's oversized selectable Text overlay."""
    return ft.SelectionArea(ft.Text(value, color=color))


def _metric_cards(cards: list[ft.Control]) -> ft.ResponsiveRow:
    """Give expanding metric cards finite responsive cells inside scrolling pages."""
    return ft.ResponsiveRow(
        [ft.Container(content=card, col={"xs": 12, "sm": 6, "md": 4, "lg": 3}) for card in cards],
        spacing=10,
        run_spacing=10,
    )


def _guidance_lines(guidance: object) -> list[str]:
    value = guidance if isinstance(guidance, dict) else {}
    lines = []
    for item in value.get("items", [])[:8]:
        if not isinstance(item, dict):
            continue
        displayed = _research_number(item.get("value"))
        if item.get("lower") is not None or item.get("upper") is not None:
            displayed = f"{_research_number(item.get('lower'))} to {_research_number(item.get('upper'))}"
        lines.append(f"{item.get('metric', 'guidance')} {item.get('period_key', 'unspecified')}: {displayed}; review={item.get('review_status', 'unknown')}; source={item.get('source_id', 'unknown')}")
    return lines or [str(value.get("reason") or "No structured, reviewed official guidance import is available.")]


def _consensus_lines(consensus: object) -> list[str]:
    value = consensus if isinstance(consensus, dict) else {}
    lines = []
    for metric, periods in value.get("metrics", {}).items():
        if not isinstance(periods, dict):
            continue
        for period_key, item in periods.items():
            if not isinstance(item, dict):
                continue
            revision = item.get("revision", {}) if isinstance(item.get("revision"), dict) else {}
            dispersion = item.get("dispersion", {}) if isinstance(item.get("dispersion"), dict) else {}
            surprise = item.get("surprise", {}) if isinstance(item.get("surprise"), dict) else {}
            staleness = item.get("staleness", {}) if isinstance(item.get("staleness"), dict) else {}
            lines.append(f"{metric} {period_key}: estimate={_research_number(item.get('latest_value'))}; revision={_research_number(revision.get('value'))}; dispersion={_research_number(dispersion.get('value'))}; surprise={_research_number(surprise.get('value'))}; staleness={staleness.get('days', 'n/a')} days; sources={item.get('source_ids', [])}")
            if len(lines) >= 8:
                return lines
    return lines or [str(value.get("reason") or "No licensed point-in-time consensus import is available; revisions, dispersion, surprises and staleness remain n/a.")]


def _research_number(value: object) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)


def _research_value(value: object) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100.0:.2f}%"
    except (TypeError, ValueError):
        return str(value)


__all__ = ["stock_research_page"]
