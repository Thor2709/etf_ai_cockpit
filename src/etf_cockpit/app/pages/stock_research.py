from __future__ import annotations

from collections.abc import Callable



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
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    EmptyState,
    GateCheck,
    GlassCard,
    Headline,
    Note,
    Pipeline,
    SectionHeader,
    Segmented,
    StatTile,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages import _p3_common as common
from etf_cockpit.app.pages import stock_page as sp
from etf_cockpit.app.formatting import format_date, format_number
from etf_cockpit.app.state import AppState
from etf_cockpit.application.stress_lab import StressLabFacade
from etf_cockpit.application.ui_views import stock_research as research_view
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


def _fundamentals(_page: ft.Page, state: AppState, instrument_id: str, view: str) -> ft.Control:
    """Existing statement and valuation evidence panels; ``view`` is "Statements" or "Valuation"."""
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
    valuation = _valuation_panel(
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
    )
    if view == "Valuation":
        return ft.Column([valuation], spacing=16)
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
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
            panel(_selectable_text("All stock research outputs are evidence-only and carry execution_allowed=false. Import an official local statement package to replace the explicit unavailable state.", color=theme.MUTED)),
        ],
        spacing=16,
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
        period = Note(str(item.get("period_key") or item.get("period_end") or "period"), color=theme.MUTED)
        period.width = 90
        roic = Note(_research_value(item.get("roic")), color=theme.CYAN if value >= 0 else theme.AMBER)
        roic.width = 72
        controls.append(ft.Row([period, ft.ProgressBar(value=max(0.0, min(abs(value), 1.0)), color=theme.CYAN if value >= 0 else theme.AMBER, expand=True), roic]))
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
        spacing=8,
        run_spacing=8,
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


# ---------------------------------------------------------------------------
# Final UI first screen (spec 6.3): verdict, hero chart, attribution, rolling, factors
# ---------------------------------------------------------------------------

_RANGES = ["1M", "3M", "1Y", "5Y"]
_ATTRIBUTION_STEPS = ["Price", "Dividends", "FX", "Fees", "Tax"]


def _resolve_instrument(state: AppState, by_key: dict[str, object]) -> str:
    selected = str(getattr(state, "selected_etf", "") or "")
    if selected in by_key:
        return selected
    for recent in getattr(state, "recent_instruments", []):
        if recent in by_key:
            return recent
    scored = [(getattr(item, "final_score_10", None), key) for key, item in by_key.items()]
    scored = [(value, key) for value, key in scored if value is not None]
    return max(scored)[1] if scored else next(iter(by_key))


_POSITIVE_GATE_WORDING = ((" is available", " is not available"), (" is evaluated", " is not evaluated"), (" are explicit", " are not explicit"))


def gate_sub_line(passed: bool | None, message: str) -> str:
    """A failed gate must state its failing reason; the domain message is the pass wording ("... is available")."""
    text = str(message or "").strip()
    if passed is not False:
        return text
    if not text:
        return "Reason unavailable"
    for positive, negative in _POSITIVE_GATE_WORDING:
        if text.endswith(positive.rstrip()) or positive in text:
            return text.replace(positive, negative, 1)
    return f"Not met: {text}"


def _gate_rows(score: object, view: research_view.StockView, meta: dict[str, str]) -> list[tuple[bool | None, str, str]]:
    gates = tuple(getattr(getattr(score, "authority_decision", None), "gates", ()) or ())
    risk_gate = next((gate for gate in gates if "risk" in str(gate.gate_id).casefold() or "drawdown" in str(gate.gate_id).casefold()), None)
    drawdown = common.signed(view.max_drawdown, 1, ratio=True)
    risk = (
        risk_gate.passed if risk_gate is not None else None,
        "Risk gate",
        f"Max drawdown {drawdown} over {view.range_key}" if drawdown else "Max drawdown unavailable for this range",
    )
    adjusted = common.percent(view.adjusted_share, 0)
    if adjusted is None:
        data = (None, "Data quality", "No stored prices to check")
    else:
        gaps = "no gaps" if not view.gap_count else f"{view.gap_count} gaps"
        data = (view.adjusted_share == 1.0 and not view.gap_count, "Data quality", f"{adjusted} adjusted prices, {gaps}, as of {format_date(view.last_date)}")
    friction = getattr(score, "risk_friction_10", None)
    cost_text = f"TER {meta['ter']}" if meta["ter"] else "TER unavailable"
    # Missing cost evidence is unavailable, never a pass (no fail-open on missing data).
    cost = (None if friction is None or not meta["ter"] else friction >= 4.0, "Cost", f"{cost_text} · tracking difference unavailable")
    q10, q50, q90 = (getattr(score, name, None) for name in ("q10_expected_return", "q50_expected_return", "q90_expected_return"))
    if q10 is None or q50 is None or q90 is None:
        forecast = (None, "Forecast agrees", "No complete forecast distribution")
    else:
        forecast = (True, "Forecast agrees", f"Baseline {common.signed(q50, 1, ratio=True)} (80% range {common.signed(q10, 1, '', ratio=True)} … {common.signed(q90, 1, ratio=True)})")
    rows = [risk, data, cost, forecast]
    failed = [(False, str(gate.gate_id).replace("_", " ").capitalize(), gate_sub_line(False, gate.message)) for gate in sorted(gates, key=lambda item: (item.order, item.gate_id)) if not gate.passed]
    titles = {row[1] for row in rows}
    extra = [row for row in failed if row[1] not in titles]
    rows.sort(key=lambda row: row[0] is not False)  # a failed gate always takes the first slot
    return (extra[:1] + rows)[:4] if extra else rows


def _all_gates_dialog(page: object, score: object) -> Callable[[object], None]:
    gates = sorted(
        getattr(getattr(score, "authority_decision", None), "gates", ()) or (),
        key=lambda gate: (gate.order, gate.gate_id),
    )

    def show(_event: object) -> None:
        rows = [
            GateCheck(gate.passed, gate.gate_id.replace("_", " ").capitalize(), gate_sub_line(gate.passed, gate.message), last=index == len(gates) - 1)
            for index, gate in enumerate(gates)
        ] or [Note("Gate evidence unavailable; manual review required.")]
        dialog = ft.AlertDialog(
            title=common.text("All evidence gates", theme.FONT_LG, 600),
            content=ft.Container(ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO), width=480, height=360),
            actions=[Button.secondary("Close", lambda _e: page.pop_dialog())],
        )
        if hasattr(page, "show_dialog"):
            page.show_dialog(dialog)

    return show


def _verdict_card(g: common.Grid, width: float, height: float, page: object, score: object, view: research_view.StockView, meta: dict[str, str]) -> ft.Control:
    tag, _kind = common.evidence_tag(score)
    gates = tuple(getattr(getattr(score, "authority_decision", None), "gates", ()) or ())
    failed = sum(1 for gate in gates if not gate.passed)
    if not gates:
        status = "Gate evidence unavailable · decision support only"
    elif failed:
        status = f"Fails {failed} of {len(gates)} gates · decision support only"
    else:
        status = f"Passes all {len(gates)} gates · decision support only"
    ids = score.display_id
    inner_w, _ = common.inner_size(width, height, insight=False, title=False)
    verdict_label = Note(f"RESEARCH VERDICT · {ids}", color=theme.INK3)
    verdict_label.expand = True
    verdict_label.max_lines = 1
    verdict_label.overflow = ft.TextOverflow.ELLIPSIS
    verdict_label.tooltip = verdict_label.value
    verdict_row = ft.Container(
        content=ft.Stack(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    verdict_label,
                                    common.link("View all gates", _all_gates_dialog(page, score)),
                                ],
                                spacing=8,
                                height=20,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            Headline(common.verdict_word(tag), 68),
                            Note(status),
                        ],
                        spacing=0,
                        tight=True,
                    ),
                    left=0,
                    top=0,
                    width=inner_w - 128 - 12,
                ),
                ft.Container(
                    content=ck.gauge(getattr(score, "final_score_10", None), maximum=10, caption="of 10", decimals=1),
                    right=0,
                    bottom=0,
                ),
            ]
        ),
        height=136,
        width=inner_w,
    )
    gate_column = ft.Column(
        [GateCheck(passed, title, reason, last=index == 3) for index, (passed, title, reason) in enumerate(_gate_rows(score, view, meta))],
        spacing=0,
    )
    tiles = _stat_tiles(view)
    body = ft.Column(
        [verdict_row, gate_column, ft.Row(tiles[:2], spacing=8), ft.Row(tiles[2:], spacing=8)],
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
    )
    return GlassCard("", body=common.fit(body, width, height, insight=False, title=False), width=width, height=height)


def _stat_tiles(view: research_view.StockView) -> list[ft.Control]:
    label = view.range_key
    values = [
        (f"Return {label}", common.signed(view.total_return, 1, ratio=True), view.spark_price, common.tone_of(view.total_return), "return", None),
        ("Volatility (ann.)", common.percent(view.volatility, 1), view.spark_vol, None, "volatility", ck.palette.P),
        ("Max drawdown", common.signed(view.max_drawdown, 1, ratio=True), view.spark_dd, "neg" if view.max_drawdown else None, "drawdown", None),
        ("Sharpe ratio", None if view.sharpe is None else format_number(view.sharpe, decimals=2), [], None, "sharpe", None),
    ]
    tiles: list[ft.Control] = []
    for title, value, spark, tone, key, _colour in values:
        tile = StatTile(title, value, spark if value is not None else None, tone, expand=True)
        if value is None:
            tile.tooltip = "Unavailable: " + view.stat_reasons.get(key, "no evidence")
        tiles.append(tile)
    return tiles


def _hero_card(width: float, height: float, view: research_view.StockView, meta: dict[str, str], score: object) -> ft.Control:
    models = view.forecasts[:1]
    fans_note = "fans = 50% / 80% range" if any(None not in line.q25 for line in models) else "fan = 80% range"
    note = f"{meta['currency']} · close" + (f" · {fans_note}" if models else "")
    if not view.forecasts and view.baseline is None:
        note = f"{meta['currency']} · close · Forecast unavailable — no forecast run yet"
    insight = _hero_insight(view, score)

    def chart(w: float, h: float) -> ft.Control:
        if view.unavailable_price or not view.dates:
            return ck.empty_state("No price history", view.unavailable_price or "No stored prices.", w, h)
        future = sorted({d for line in ([view.baseline] if view.baseline else []) + view.forecasts for d in line.dates})
        x = view.dates + future
        pad = [None] * len(future)
        last_close = view.close[-1]
        series = [ck.Series("Close", view.close + pad, ck.palette.P, 3.2, glow=True, area=True, decimals=2)]
        if view.benchmark:
            series.append(ck.Series("Benchmark", view.benchmark + pad, ck.palette.BM, 2.0, dashed=True, opacity=0.9))

        def aligned(line: research_view.ForecastLine, values: list[float | None]) -> list[float | None]:
            lookup = dict(zip(line.dates, values))
            return [None] * (len(view.dates) - 1) + [last_close] + [lookup.get(d) for d in future]

        if view.baseline:
            series.append(ck.Series("Baseline", aligned(view.baseline, view.baseline.q50), ck.palette.SECOND, 2.4, dashed=True))
        bands: list[ck.Band] = []
        for index, line in enumerate(models):
            series.append(ck.Series(f"Model ({line.model})", aligned(line, line.q50), ck.palette.VIO, 2.8, glow=True))
            bands.append(ck.Band("80% range", aligned(line, line.q10), aligned(line, line.q90), ck.palette.VIO, 0.16))
            if None not in line.q25:
                bands.append(ck.Band("50% range", aligned(line, line.q25), aligned(line, line.q75), ck.palette.VIO, 0.28))
        for line in view.forecasts[1:]:
            series.append(ck.Series(f"Model ({line.model})", aligned(line, line.q50), ck.palette.VIO, 2.0, dashed=True))
        events = [ck.EventMark(i, "Div", 0) for i in view.dividend_index]
        return ck.price_drawdown_chart(
            x, series, view.drawdown + pad, bands=bands, events=events, today=None if not future else view.dates[-1],
            price_name=f"Price ({meta['currency']})", width=w, height=h, insight=insight,
        )

    body = common.chart_well(chart, width, height)
    return GlassCard("Price, forecast & drawdown", note, insight, body=body, width=width, height=height)


def _hero_insight(view: research_view.StockView, score: object) -> str:
    if view.total_return is None:
        return "Price change is unavailable for this range."
    text = f"Price is {common.signed(view.total_return, 1, ratio=True)} over {view.range_key}"
    if view.benchmark_return is not None:
        gap = (view.total_return - view.benchmark_return) * 100.0
        text += f" and {format_number(abs(gap), decimals=1)} pts {'ahead of' if gap >= 0 else 'behind'} the benchmark"
    text += "."
    model = view.forecasts[0] if view.forecasts else None
    if model and view.baseline and model.q50[-1] is not None and view.baseline.q50[-1] is not None:
        above = model.q50[-1] >= view.baseline.q50[-1]
        inside = model.q10[-1] <= view.baseline.q50[-1] <= model.q90[-1]
        text += f" The model forecast sits {'above' if above else 'below'} the baseline {'but inside' if inside else 'and outside'} its 80% range."
    return text


def _attribution_card(width: float, height: float, view: research_view.StockView) -> ft.Control:
    steps = [(name, view.attribution.get(name)) for name in _ATTRIBUTION_STEPS]
    running = 100.0
    categories, values, bases, kinds, labels, levels = ["Start"], [100.0], [None], ["blue"], ["100"], [100.0]
    for name, delta in steps:
        categories.append(name)
        if delta is None:
            values.append(None)
            bases.append(None)
            kinds.append(None)
            labels.append("n/a")
            continue
        bases.append(min(running, running + delta))
        values.append(abs(delta))
        kinds.append("pos" if delta >= 0 else "neg")
        labels.append(common.signed(delta, 1, "") or "")
        running += delta
        levels.append(running)
    categories.append("End")
    values.append(running)
    bases.append(None)
    kinds.append("blue")
    labels.append(format_number(running, decimals=1))
    levels.append(running)
    known = view.attribution.get("Price") is not None
    low = min(levels)
    y_min = low - max(1.0, (max(levels) - low) * 0.5)
    missing = [name for name, delta in steps if delta is None]
    if known:
        total = running - 100.0
        price = view.attribution["Price"]
        share = "" if not total else f"Price drives {format_number(price / total * 100.0, decimals=0)}% of the {common.signed(total, 1, '')} points; "
        insight = f"{share}no evidence for {', '.join(missing)}." if missing else f"{share}all components have evidence."
    else:
        insight = "Attribution is unavailable for this range."

    def chart(w: float, h: float) -> ft.Control:
        return ck.bar_chart(
            categories, values, kinds=kinds, bases=bases, labels=labels, x_name="Component", y_name="Index (base 100)",
            y_min=y_min, margins=ck.Margins(62, 12, 26, 46), width=w, height=h, insight=insight,
            unavailable_reason=None if known else insight, empty_title="No attribution",
        )

    return GlassCard("Return attribution", "index points, base 100", insight, True, body=common.chart_well(chart, width, height, quiet=True), width=width, height=height)


def _saved_scenario_count(state: AppState) -> int:
    try:
        return len(StressLabFacade(state.snapshot).list_saved())
    except Exception:  # local scenario storage unavailable: counts as none saved, never an error on this page
        return 0


def _rolling_card(state: AppState, width: float, height: float, page: object, view: research_view.StockView, score: object) -> ft.Control:
    ids = score.display_id
    pairs = [(a, b) for a, b in zip(view.roll_instrument, view.roll_benchmark) if a is not None and b is not None]
    if view.roll_reason:
        insight = view.roll_reason
    elif pairs:
        wins = sum(1 for a, b in pairs if a > b)
        insight = f"{ids} beat the benchmark in {wins} of the last {len(pairs)} months."
    else:
        insight = "No benchmark series is stored for this instrument; only the instrument line is shown."
    holder = ft.Container()
    reserve = 38 + 10

    def rolling(w: float, h: float) -> ft.Control:
        series = [ck.Series(ids, view.roll_instrument, ck.palette.P, 3.0, area=True, unit="%")]
        if any(v is not None for v in view.roll_benchmark):
            series.append(ck.Series("Benchmark", view.roll_benchmark, ck.palette.BM, 2.0, dashed=True, unit="%"))
        return ck.line_chart(
            view.roll_labels, series, x_name="Month-end", y_name="12M return (%)", x_label_every=6,
            margins=ck.Margins(58, 20, 30, 46), legend_at="top-right", width=w, height=h, insight=insight,
            unavailable_reason=view.roll_reason, empty_title="No rolling return",
        )

    scenario_reason = research_view.scenario_surface_reason(state.snapshot.forecasts, score.display_id, _saved_scenario_count(state))

    def scenarios(w: float, h: float) -> ft.Control:
        return ck.surface3d(
            [], [], [], width=w, height=h,
            unavailable_reason=scenario_reason,
        )

    def show(name: str) -> None:
        builder = rolling if name == "Rolling" else scenarios
        holder.content = common.chart_well(builder, width, height, reserve=reserve, quiet=True)
        common.update(page)

    holder.content = common.chart_well(rolling, width, height, reserve=reserve, quiet=True)
    body = ft.Column([Segmented(["Rolling", "Scenarios (3D)"], "Rolling", on_change=show), holder], spacing=12)
    return GlassCard("Rolling 12-month return vs. benchmark", "percent per month-end", insight, True, body=body, width=width, height=height)


def _factor_card(page: object, width: float, height: float, state: AppState, score: object, scores: list[object]) -> ft.Control:
    ids = score.display_id
    snapshot = state.snapshot
    universe = [str(item) for item in snapshot.config.universe.enabled_ids]
    values, reason = research_view.factor_profile(snapshot.latest_features, snapshot.holdings, universe, score.display_id, score.benchmark_id)
    pairs = list(zip(research_view.FACTOR_AXES, values))
    over = [name for name, value in pairs if value is not None and value >= 0.25]
    under = [name for name, value in pairs if value is not None and value <= -0.25]
    if reason:
        insight = reason
    elif over or under:
        insight = (f"Tilted to {', '.join(over)}" if over else "No strong positive tilt") + (f"; slightly under-weight {', '.join(under)}." if under else ".")
    else:
        insight = "No factor tilt beyond ±0.25 versus the benchmark."
    usable = [s for s in scores if s.latest_price is not None and s.evidence_quality_10 is not None]
    eligible = [s for s in usable if s.final_action != "manual_review"]
    shortlist = [s for s in eligible if common.evidence_tag(s)[0] in {"Strong", "Good"}]
    pipeline = Pipeline([(str(len(scores)), "Universe"), (str(len(usable)), "Data OK"), (str(len(eligible)), "Eligible"), (str(len(shortlist)), "Shortlist")], key="stock-research.pipeline")
    for step in pipeline.controls:
        if isinstance(step, ft.Container):
            step.on_click = lambda _e: common.open_route(page, state, "/screener")
    def radar(w: float, h: float) -> ft.Control:
        return ck.radar_chart(
            list(research_view.FACTOR_AXES),
            [
                ck.RadarSeries(ids, values, ck.palette.P, 3.0, glow=True, fill_alpha=0.38),
                ck.RadarSeries("Benchmark", [0.0] * len(values), ck.palette.SECOND, 2.0, dashed=True, fill_alpha=0.0),
            ],
            lo=-2.0, hi=2.0, split_area=True, radius=0.62, center=(0.5, 0.54), legend_at="top-left", axis_size=13.5, decimals=1,
            width=w, height=h, insight=insight, unavailable_reason=reason, empty_title="No factor profile",
        )

    body = ft.Column([common.chart_well(radar, width, height, reserve=51 + 12, quiet=True), pipeline], spacing=12)
    return GlassCard("Factor profile & screening", "z-score vs. benchmark", insight, True, body=body, width=width, height=height)


def _fund_evidence(page: object, state: AppState, instrument_id: str) -> ft.Control:
    def open_detail(_event: object) -> None:
        common.open_route(page, state, f"/instrument/{instrument_id}", instrument_id)

    return GlassCard(
        "Fund evidence",
        body=[Note("Statement evidence applies to companies. Fund structure, holdings and costs are in Instrument Detail."), Button.secondary("Open Instrument Detail", open_detail)],
        quiet=True,
    )


def stock_research_page(page: ft.Page, state: AppState) -> PageView:
    scores = common.scores_for(state)
    by_key = {item.display_id: item for item in scores}
    if not by_key:
        return PageView(PageChrome("Stock Research", "No scored instruments"), EmptyState("No scored instruments", "Import or refresh local evidence first; no values are inferred."))
    ui = {"key": _resolve_instrument(state, by_key), "range": "1Y"}
    common.remember_instrument(state, ui["key"])
    ids = common.segment_ids(state, ui["key"], list(by_key))
    holder = ft.Container()
    g = common.grid(page)

    def build() -> ft.Control:
        key = ui["key"]
        score = by_key[key]
        state.selected_etf = key
        common.remember_instrument(state, key)
        meta = common.instrument_meta(state, key)
        snapshot = state.snapshot
        view = research_view.build_stock_view(
            snapshot.prices, snapshot.forecasts, key, ui["range"], benchmark_id=score.benchmark_id,
            cash_return=score.cash_return if score.cash_comparison_status == "available" else None,
            cash_horizon_years=score.cash_horizon_years,
        )
        first = common.place(g, g.row_a, [
            (4, lambda w, h: _verdict_card(g, w, h, page, score, view, meta)),
            (8, lambda w, h: _hero_card(w, h, view, meta, score)),
        ])
        second = common.place(g, g.row_b, [
            (4, lambda w, h: _attribution_card(w, h, view)),
            (4, lambda w, h: _rolling_card(state, w, h, page, view, score)),
            (4, lambda w, h: _factor_card(page, w, h, state, score, scores)),
        ])
        return common.below_fold(g, [first, second, _fundamentals_section(page, state, key, meta, score)])

    def chrome_for_selection() -> PageChrome:
        current = by_key[ui["key"]]
        meta = common.instrument_meta(state, ui["key"])
        return PageChrome(
            f"Stock Research · {current.display_id}",
            f"{meta['name']} · {meta['currency']} · {meta['venue']}",
            (
                SegmentGroup("instrument", ids, current.display_id, select_instrument),
                SegmentGroup("range", _RANGES, ui["range"], select_range),
            ),
        )

    def select_instrument(label: str) -> PageChrome | None:
        if label not in by_key:
            return None
        ui["key"] = label
        holder.content = build()
        common.update(page)
        return chrome_for_selection()

    def select_range(label: str) -> PageChrome:
        ui["range"] = label
        holder.content = build()
        common.update(page)
        return chrome_for_selection()

    holder.content = build()
    return PageView(chrome_for_selection(), holder)


def _stock_statements(state: AppState, key: str, score: object) -> ft.Control | None:
    """Numbers, valuation, peers, reported history and notes from the same evidence as Instrument Detail.

    None for instruments the stock evidence does not cover (banks, certificates, funds): they keep the
    legacy statement panels.
    """

    if str(getattr(score, "final_label", "") or "").casefold() == "scorecard_owned":
        return None
    stock = sp.build_model(getattr(state, "snapshot", None), key, score)
    if not stock.available:
        return None
    config = getattr(getattr(state, "snapshot", None), "config", None)
    cards = [
        *sp.numbers_cards(stock, ("Earnings and returns", "Cash and balance sheet")),
        sp.valuation_card(stock),
        sp.peers_card(stock, config),
        sp.fiscal_history_card(stock),
        sp.notes_card(stock),
    ]
    return ft.Column([ft.ResponsiveRow(cards, spacing=16, run_spacing=16)], spacing=16)


def _fundamentals_section(page: object, state: AppState, key: str, meta: dict[str, str], score: object | None = None) -> ft.Control:
    if meta["type"] and meta["type"].casefold() != "stock":
        return ft.Column([SectionHeader("Company fundamentals", "reported facts, derived metrics and valuation assumptions stay separate"), _fund_evidence(page, state, key)], spacing=12)
    statements = _stock_statements(state, key, score)
    holder = ft.Container(content=statements if statements is not None else _fundamentals(page, state, key, "Statements"))

    def switch(label: str) -> None:
        holder.content = (statements if label == "Statements" and statements is not None else _fundamentals(page, state, key, label))
        common.update(page)

    header = SectionHeader(
        "Company fundamentals",
        "reported facts, derived metrics and valuation assumptions stay separate",
        Segmented(["Statements", "Valuation"], "Statements", on_change=switch),
    )
    return ft.Column([header, holder], spacing=12)


__all__ = ["stock_research_page"]
