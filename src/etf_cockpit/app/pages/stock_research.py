from __future__ import annotations



import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, section_header
from etf_cockpit.app.components.research_surface import metric_card, panel
from etf_cockpit.app.components.valuation_lab import (
    _recalculate_valuation,
    _research_number,
    _research_value,
    _selectable_text,
    _valuation_panel,
)
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    CONSENSUS_IMPORT_PATH,
    GUIDANCE_IMPORT_PATH,
    STATEMENT_FACTS_PATH,
    build_stock_research_report,
    load_capital_allocation_analysis,
    load_optional_research_import,
    load_valuation_market_inputs,
    load_stock_research_context,
)


def stock_research_page(_page: ft.Page, state: AppState) -> ft.Control:
    instrument_id = str(getattr(state, "selected_etf", "") or state.snapshot.config.ui.default_etf)
    snapshot_decision_time = getattr(getattr(state, "snapshot", None), "benchmark_reference_decision_time", None)
    context = load_stock_research_context(instrument_id, statements_path=STATEMENT_FACTS_PATH, decision_time=snapshot_decision_time)
    statements = context.get("statements")
    statements = statements if isinstance(statements, pd.DataFrame) else pd.DataFrame()
    consensus = load_optional_research_import(CONSENSUS_IMPORT_PATH, instrument_id=instrument_id)
    guidance = load_optional_research_import(GUIDANCE_IMPORT_PATH, instrument_id=instrument_id)
    snapshot = getattr(state, "snapshot", None)
    benchmark_context = {
        name: getattr(snapshot, name, None)
        for name in (
            "benchmark_reference_instrument",
            "benchmark_reference_currency",
            "benchmark_reference_horizon_years",
            "benchmark_reference_start_date",
            "benchmark_reference_end_date",
            "benchmark_reference_decision_time",
        )
    }
    market_inputs = context.get("valuation_market_inputs")
    market_inputs = dict(market_inputs) if isinstance(market_inputs, dict) else load_valuation_market_inputs(
        instrument_id,
        statements=statements,
        decision_time=context.get("decision_time"),
        benchmark_context=benchmark_context,
    )
    market_inputs["benchmark_context"] = benchmark_context
    report_arguments = dict(
        instrument_id=instrument_id,
        sector=str(context.get("sector") or ""),
        peer_frame=context.get("peer_frame") if isinstance(context.get("peer_frame"), pd.DataFrame) else None,
        peer_market_inputs=context.get("peer_valuation_market_inputs") if isinstance(context.get("peer_valuation_market_inputs"), dict) else {},
        classification_context=context.get("classification") if isinstance(context.get("classification"), dict) else None,
        peer_context=context.get("peer_context") if isinstance(context.get("peer_context"), dict) else None,
        financial_projection=context.get("financial_projection") if isinstance(context.get("financial_projection"), dict) else None,
        market_inputs=market_inputs,
        assumptions={},
        expectation_evidence=consensus,
        guidance_evidence=guidance,
        as_known_at=context.get("decision_time"),
    )
    report = build_stock_research_report(statements, **report_arguments)
    statement_context = report.get("statement_context", {})
    statement_context = statement_context if isinstance(statement_context, dict) else {}
    classification_status = str(context.get("classification_status", "unavailable"))
    sector = str(context.get("sector") or "unclassified")
    statement_view = "as known at " + str(context.get("decision_time")) if context.get("decision_time") else "latest restated"
    capital_allocation = load_capital_allocation_analysis(
        statements,
        instrument_id=instrument_id,
        market_inputs={},
        decision_time=context.get("decision_time"),
    )
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Stock Research", "Transparent statement-derived evidence. Reported facts, derived metrics and valuation assumptions remain separate."),
                        ft.Row([evidence_chip("Instrument", instrument_id or "unselected", theme.CYAN), evidence_chip("Sector", sector, theme.BLUE_GREY), evidence_chip("Statement view", statement_view, theme.BLUE_GREY), evidence_chip("Execution", "disabled", theme.GREEN)], wrap=True),
                        _selectable_text(f"Classification: {classification_status}; currency={statement_context.get('currency', 'unavailable')}; accounting scope={statement_context.get('accounting_scope', 'unavailable')}; period={statement_context.get('period', 'unavailable')}; known_at={statement_context.get('known_at', 'unavailable')}", color=theme.MUTED),
                    ],
                    spacing=8,
                )
            ),
            _metrics_panel("Profitability", "Margins, returns, cash conversion and history are formula-labelled; peer percentiles are descriptive only.", report["profitability"]),
            _metrics_panel("Earnings quality", "Accruals, exceptional-item dependence, margin stability and transparent quality components.", report["profitability"]),
            _metrics_panel("Balance sheet", "Debt, liquidity, working capital and source-linked coverage; missing maturities remain unavailable.", report["balance_sheet"]),
            _metrics_panel("Solvency", "Stress scenarios and contextual distress evidence; this is not a credit rating or execution authority.", report["balance_sheet"]),
            _metrics_panel("Financial institution adapter", "Financial-sector evidence is delegated to its dedicated adapter; industrial measures are marked inapplicable.", report["financial_institutions"]) if report.get("financial_institutions") else ft.Container(),
            _capital_efficiency_panel(report["capital_efficiency"], _page),
            _capital_allocation_panel(capital_allocation),
            _growth_panel(report["growth"]),
            _expectations_panel(report["expectations"]),
            _valuation_panel(
                report["valuation"],
                on_calculate=lambda assumptions: _recalculate_valuation(
                    statements,
                    report_arguments,
                    instrument_id=instrument_id,
                    decision_time=context.get("decision_time"),
                    benchmark_context=benchmark_context,
                    assumptions=assumptions,
                ),
                page=_page,
            ),
            panel(_selectable_text("All stock research outputs are evidence-only and carry execution_allowed=false. Import an official local statement package to replace the explicit unavailable state.", color=theme.MUTED)),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _capital_allocation_panel(section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    metrics = value.get("metrics", {}) if isinstance(value.get("metrics"), dict) else {}
    metric_names = (
        "cash_from_operations_to_net_income",
        "cash_from_operations_to_ebitda",
        "free_cash_flow",
        "free_cash_flow_margin",
        "capex_intensity",
        "dividend_yield",
        "buyback_yield",
        "issuance_dilution_yield",
        "shareholder_yield",
    )
    cards: list[ft.Control] = []
    details: list[str] = []
    for name in metric_names:
        item = metrics.get(name, {}) if isinstance(metrics, dict) else {}
        if not isinstance(item, dict):
            continue
        metric_value = item.get("value")
        if metric_value is None:
            display = "N/A"
        elif item.get("unit") == "ratio":
            display = f"{float(metric_value) * 100.0:.2f}%"
        else:
            display = f"{_research_number(metric_value)} {item.get('currency', '')}".strip()
        cards.append(metric_card(name.replace("_", " ").title(), display, str(item.get("status", "unavailable"))))
        details.append(
            f"{name}: formula={item.get('formula', 'n/a')}; denominator={item.get('denominator', 'n/a')}; "
            f"currency={item.get('currency', 'unavailable')}; period={item.get('period', 'unavailable')}; "
            f"sign={item.get('sign_convention', 'n/a')}; sources={item.get('source_ids', [])}"
        )
    if not cards:
        cards = [metric_card("Capital allocation", "Unavailable", str(value.get("status", "unavailable")))]
    coverage = value.get("coverage", {}) if isinstance(value.get("coverage"), dict) else {}
    lineage = value.get("source_lineage", {}) if isinstance(value.get("source_lineage"), dict) else {}
    source_ids = lineage.get("source_ids", []) if isinstance(lineage.get("source_ids"), list) else []
    allocation = value.get("capital_allocation", {}) if isinstance(value.get("capital_allocation"), dict) else {}
    allocation_lines = []
    for name, item in allocation.items():
        if not isinstance(item, dict):
            continue
        allocation_lines.append(f"{name}={_research_number(item.get('value'))} {item.get('currency', '')} ({item.get('status', 'unavailable')})")
    checks = value.get("reconciliations", []) if isinstance(value.get("reconciliations"), list) else []
    check_summary = ", ".join(f"{item.get('name')}={item.get('status')}" for item in checks if isinstance(item, dict)) or "No comparable reconciliations."
    bank_projection = value.get("financial_projection") if isinstance(value.get("financial_projection"), dict) else None
    bank_status = value.get("financial_projection_status", "not_applicable")
    bank_line = f"Financial-institution projection: {bank_status}."
    if bank_projection:
        projection_metrics = bank_projection.get("metrics", [])
        if isinstance(projection_metrics, (list, tuple)):
            delegated = ", ".join(
                f"{item.get('metric')}={_research_number(item.get('value'))} ({item.get('status', 'unavailable')})"
                for item in projection_metrics
                if isinstance(item, dict) and item.get("metric") in {"dividends", "retained_earnings", "issuance_dilution"}
            )
            if delegated:
                bank_line += f" Delegated evidence: {delegated}."
    capex_policy = value.get("maintenance_growth_capex", {}) if isinstance(value.get("maintenance_growth_capex"), dict) else {}
    return panel(
        ft.Column(
            [
                section_header("Capital Allocation", "Reported cash-flow evidence, calculated free cash flow, capital uses, dated shareholder yields and split-adjusted share changes remain separate."),
                ft.Row(
                    [
                        evidence_chip("Coverage", str(coverage.get("status", "unavailable")), theme.CYAN if coverage.get("status") == "available" else theme.AMBER),
                        evidence_chip("Periods", str(coverage.get("period_count", 0)), theme.BLUE_GREY),
                        evidence_chip("Sources", str(len(source_ids)), theme.BLUE_GREY),
                    ],
                    wrap=True,
                ),
                _metric_cards(cards),
                _selectable_text(" | ".join(details) or "Formula and period evidence are unavailable.", color=theme.MUTED),
                _selectable_text(f"Capital-allocation records: {'; '.join(allocation_lines) or 'Unavailable.'}", color=theme.MUTED),
                _selectable_text(f"Reconciliations: {check_summary}. {bank_line} Maintenance/growth capex: {capex_policy.get('reason', 'not inferred without issuer evidence')}; execution_allowed=false", color=theme.MUTED),
            ],
            spacing=8,
        )
    )


def _metrics_panel(title: str, description: str, section: object) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    metrics = value.get("metrics", {}) if isinstance(value, dict) else {}
    metric_order = {
        "Profitability": ("gross_margin", "operating_margin", "net_margin", "roa", "roe", "roic", "cash_conversion"),
        "Earnings quality": ("cash_conversion", "accrual_ratio", "exceptional_item_dependence", "margin_stability"),
        "Balance sheet": ("net_debt", "debt_to_equity", "current_ratio", "quick_ratio", "working_capital", "interest_coverage"),
        "Solvency": ("altman_like_distress",),
    }
    selected_names = metric_order.get(title, tuple(metrics)[:6])
    cards = []
    for name in selected_names:
        if name not in metrics:
            continue
        item = metrics[name]
        if not isinstance(item, dict):
            continue
        display = "N/A" if item.get("value") is None else f"{float(item['value']):.3f}"
        cards.append(metric_card(name.replace("_", " ").title(), display, str(item.get("status", "unavailable"))))
    if not cards:
        cards = [metric_card("Evidence", "Unavailable", "No canonical statement rows")]
    definitions = " | ".join(
        f"{name}: {item.get('formula', 'definition unavailable')} ({item.get('status', 'unavailable')}; period={item.get('period', 'unavailable')})"
        for name, item in [(name, metrics[name]) for name in selected_names if name in metrics][:8]
        if isinstance(item, dict)
    ) or "No metric definitions are available."
    peer_status = value.get("peer_comparisons", {}) if isinstance(value.get("peer_comparisons"), dict) else {}
    peer_text = f"Peer percentiles: {value.get('peer_percentiles', {})}; comparison coverage: {peer_status}"
    coverage = value.get("coverage_limitations", []) if isinstance(value.get("coverage_limitations"), list) else []
    maturity = value.get("maturity_timeline", {}) if isinstance(value.get("maturity_timeline"), dict) else {}
    coverage_text = f"Coverage limitations: {coverage}; maturity status={maturity.get('status', 'unavailable')}; maturity limitation={maturity.get('limitation', 'unavailable')}"
    return panel(ft.Column([section_header(title, description), _metric_cards(cards), _selectable_text(f"Definitions and denominators: {definitions}", color=theme.MUTED), _selectable_text(peer_text, color=theme.MUTED), _selectable_text(coverage_text, color=theme.AMBER if coverage or maturity.get("status") == "missing" else theme.MUTED), _selectable_text(f"Source lineage: {value.get('source_lineage', {}).get('source_ids', []) if isinstance(value, dict) else []}; execution_allowed=false", color=theme.MUTED)], spacing=8))


def _capital_efficiency_panel(section: object, page: object | None = None) -> ft.Control:
    value = section if isinstance(section, dict) else {}
    reported = value.get("reported", {}) if isinstance(value.get("reported"), dict) else {}
    adjusted = value.get("adjusted", {}) if isinstance(value.get("adjusted"), dict) else {}
    reported_view = ft.Container(content=_capital_view("Reported", reported), data="capital-efficiency-reported", visible=True)
    adjusted_view = ft.Container(content=_capital_view("Adjusted", adjusted), data="capital-efficiency-adjusted", visible=False)

    def select_basis(event: ft.ControlEvent) -> None:
        show_adjusted = "adjusted" in list(getattr(event.control, "selected", []) or [])
        reported_view.visible = not show_adjusted
        adjusted_view.visible = show_adjusted
        update = getattr(page, "update", None)
        if callable(update):
            update()

    selector = ft.SegmentedButton(
        segments=[ft.Segment(value="reported", label="Reported"), ft.Segment(value="adjusted", label="Adjusted")],
        selected=["reported"],
        allow_empty_selection=False,
        on_change=select_basis,
        key="stock-research.capital-basis",
    )
    proxies = value.get("business_quality_proxies", {}) if isinstance(value.get("business_quality_proxies"), dict) else {}
    proxy_text = ", ".join(f"{name.replace('_', ' ')}={_research_number(item.get('value'))} ({item.get('status', 'unavailable')})" for name, item in proxies.items() if isinstance(item, dict)) or "No source-backed quality proxies are available."
    peer = value.get("sector_relative", {}) if isinstance(value.get("sector_relative"), dict) else {}
    sensitivity = value.get("assumption_sensitivity", []) if isinstance(value.get("assumption_sensitivity"), list) else []
    return panel(
        ft.Column(
            [
                section_header("Capital Efficiency", "Reported statement evidence never blends with optional intangible adjustments. Incremental measures require stable denominators and at least three periods."),
                selector,
                reported_view,
                adjusted_view,
                _selectable_text(f"Sector-relative context: {peer.get('status', 'unavailable')}; peers={peer.get('peer_count', 0)}; percentiles={peer.get('percentiles', {})}", color=theme.MUTED),
                _selectable_text(f"Disclosure-only business-quality proxies: {proxy_text}. These cannot override valuation or risk.", color=theme.MUTED),
                _selectable_text(f"Exportable adjustment sensitivity scenarios: {len(sensitivity)}; proxy_authority={value.get('proxy_authority', 'descriptive_only')}; execution_allowed=false", color=theme.GREEN),
            ],
            spacing=8,
        )
    )


def _capital_view(label: str, section: dict[str, object]) -> ft.Control:
    metrics = section.get("metrics", {}) if isinstance(section.get("metrics"), dict) else {}
    cards = []
    for name in ("roic", "incremental_roic", "reinvestment_rate", "sales_to_capital", "asset_turns", "economic_profit_spread"):
        item = metrics.get(name, {}) if isinstance(metrics, dict) else {}
        if isinstance(item, dict):
            cards.append(metric_card(name.replace("_", " ").title(), _research_value(item.get("value")), str(item.get("status", "unavailable"))))
    if not cards:
        cards = [metric_card(f"{label} metrics", "N/A", str(section.get("status", "unavailable")))]
    assumptions = section.get("assumptions", {}) if isinstance(section.get("assumptions"), dict) else {}
    bridge = section.get("latest_bridge", {}) if isinstance(section.get("latest_bridge"), dict) else {}
    return ft.Column(
        [
            _metric_cards(cards),
            _selectable_text(f"{label} basis: status={section.get('status', 'unavailable')}; assumptions={assumptions}; latest bridge={bridge}", color=theme.CYAN if section.get("status") == "available" else theme.MUTED),
            _capital_persistence_chart(section.get("history", []), label),
        ],
        spacing=8,
    )


def _capital_persistence_chart(history: object, label: str) -> ft.Control:
    rows = history if isinstance(history, list) else []
    controls: list[ft.Control] = [_selectable_text(f"{label} ROIC persistence", color=theme.MUTED)]
    for item in rows[-6:]:
        if not isinstance(item, dict):
            continue
        try:
            value = float(item.get("roic"))
        except (TypeError, ValueError):
            value = 0.0
        controls.append(ft.Row([ft.Text(str(item.get("period_key") or item.get("period_end") or "period"), width=90, color=theme.MUTED), ft.ProgressBar(value=max(0.0, min(abs(value), 1.0)), color=theme.CYAN if value >= 0 else theme.AMBER, expand=True), ft.Text(_research_value(item.get("roic")), width=72, color=theme.CYAN if value >= 0 else theme.AMBER)]))
    if len(controls) == 1:
        controls.append(_selectable_text("No comparable ROIC history is available.", color=theme.MUTED))
    return ft.Column(controls, spacing=4, data=f"capital-persistence-{label.casefold()}")


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
        cards = [metric_card("Reported growth", "N/A", "No canonical statement rows")]
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


__all__ = ["stock_research_page"]
