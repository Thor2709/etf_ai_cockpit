"""Governance glossary surface."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import legal_terms_report
from etf_cockpit.governance.product_scope import load_glossary


PAGE_HELP: dict[str, str] = {
    "/": "Compare configured instruments using the same local score evidence. Check the as-of date, coverage and score components before treating a rank as useful.",
    "/portfolio": "Explore holdings and allocation scenarios from local portfolio inputs. This sandbox does not submit orders or replace a suitability review.",
    "/portfolio-optimiser": "Test candidate weights against the displayed constraints and evidence. Optimiser output is a scenario; inspect infeasible constraints, missing inputs and costs.",
    "/signals": "Review canonical score components, evidence gates and reasons for a signal state. A score is research context, not a buy or sell instruction.",
    "/strategy-builder": "Combine supported research features into a strategy template. Results remain research-only and inherit the data, validation and cost limits shown for each feature.",
    "/screener": "Filter the loaded fundamentals evidence. Missing or inapplicable fields stay unavailable and are not turned into zero values or hidden rankings.",
    "/comparison": "Compare aligned instruments using their displayed dates, horizons and canonical score fields. A blank comparison means evidence is unavailable, not equivalent.",
    "/stock-research": "Inspect statement-based profitability, balance-sheet, valuation and sector evidence. Read the reporting period, source and adapter limitations beside each metric.",
    "/risk": "Review portfolio exposure, volatility, drawdown, liquidity and cost evidence. Risk summaries describe supplied holdings and assumptions, not future loss limits.",
    "/stress-lab": "Change explicit scenario assumptions to see how evidence responds. Scenarios are not forecasts, and they do not alter canonical scores or create order authority.",
    "/etf": "Inspect fund identity, holdings, adjusted-price, liquidity and attribution evidence. Check holdings coverage and source dates before relying on look-through results.",
    "/backtests": "Read historical results together with the selected universe, dates, benchmark, rebalance and cost assumptions. A backtest is not live or prospective evidence.",
    "/chatgpt": "Review local audit commentary and its linked evidence. Model-generated text is advisory, may be incomplete and cannot override policy gates or source records.",
    "/providers": "Check provider capability, local cache, freshness, terms and failure status. An unavailable optional provider does not trigger a silent refresh or change the deterministic baseline.",
    "/evidence": "Trace displayed facts to their source, observation date, retrieval time and authority. Conflicts and restricted-source limits remain visible for manual review.",
    "/filings": "Review filing identity, period, publication and retrieval details. A filing may be amended or incomplete; compare versions and keep point-in-time availability in view.",
    "/etf-disclosures": "Inspect available fund disclosures and their dates. A disclosure is not a complete or current holdings feed unless its coverage explicitly says so.",
    "/news-context": "Use news as dated context, with its source and mapping confidence. Headlines do not become score evidence or an action by themselves.",
    "/data-models": "Compare model tasks, availability, versions, validation and licence metadata. Optional challengers can be absent; only the deterministic baseline is required for core behaviour.",
    "/forecasts": "Review forecast dates, horizons, matured outcomes, error measures and interval coverage. Unmatured outcomes are not scored, and forecast output has no execution authority.",
    "/training-centre": "Inspect recorded experiments, run status, metrics, artefacts and human approval. Approval can establish research status only; it cannot enable broker or live actions.",
    "/feature-catalogue": "Read each feature's meaning, source, availability and supported use before selecting it. Unsupported or future-dated values must not be treated as valid historical inputs.",
    "/catalogue": "Use the local dataset catalogue to check coverage, dates, source and licence notes. A listed dataset may still be stale, partial or unavailable for a particular instrument.",
    "/macro": "Read macro observations with their release/vintage dates and units. Later revisions must not be treated as information known at an earlier decision date.",
    "/settings": "Review local preferences and release metadata. Settings do not grant provider, broker, paper or live authority.",
    "/diagnostics": "Use diagnostics to inspect configuration and local service state. Record the visible failure and preserve evidence before attempting recovery.",
    "/errors": "Follow the named recovery guidance and keep the original files and logs intact. Unknown or conflicting state should remain blocked until reconciled.",
    "/data-health": "Check freshness, coverage, conflicts and unsupported fields before analysis. A missing value remains unavailable and cannot be assumed to be zero or current.",
    "/universe": "Inspect configured membership, classification and coverage evidence. Historical comparisons require point-in-time membership; current membership alone can introduce survivorship bias.",
    "/onboarding": "Set up local preferences and supported data paths. Setup does not fetch data silently, store broker credentials or enable execution.",
    "/what-changed": "Compare dated evidence, source revisions, formula versions and policy changes between runs. A changed value should be traced to its recorded cause.",
    "/instrument": "Inspect one instrument's evidence, score components, history and limitations. Confirm the selected identity and as-of dates before comparing values.",
    "/import-export": "Review file identity, licence, mappings and dry-run warnings before importing. Choose an explicit local export path and verify which restricted content is omitted.",
    "/system-map": "Use the map to understand which policy and evidence gates control a capability. The map explains boundaries; it does not grant permission to cross them.",
    "/help": "Use the glossary for score, data and authority terms. The user guide explains methodology, adapters, licences, paper operations, incidents and reproducibility.",
    "/decision-journal": "Record your own decision, alternatives and rationale beside the evidence snapshot. Journal notes are user context, not model output or an order.",
    "/forward-evidence": "Review frozen decisions against outcomes only after their horizons mature. Keep observation-only proposals separate from manually accepted paper activity.",
    "/jobs": "Check local job status, progress and recorded errors. A failed or cancelled job is not a completed result; inspect its inputs before a deliberate retry.",
    "/operations": "Review proposal and local paper states separately. Paper is a simulation; broker connections, live accounts and order submission are disabled in this release.",
    "/release-readiness": "Read the exact gate results and their evidence scope. A readiness display is not a release approval or a promise that future data and models will be available.",
    "/roadmap": "Use the programme map to understand implementation status and dependencies. Planned capabilities are not present authority or current user functionality.",
}


def page_help_panel(
    route: str,
    title: str,
    on_open_help: Callable[[ft.ControlEvent], None] | None = None,
) -> ft.Control:
    """Render the route-specific help copy shared by every workspace page."""

    description = PAGE_HELP.get(route, "This route is not registered. Return to a supported page using navigation.")
    controls: list[ft.Control] = [
        ft.Column(
            [
                ft.Text(f"About {title}", color=theme.CYAN, size=11, weight=ft.FontWeight.BOLD),
                ft.Text(description, color=theme.MUTED, size=11, selectable=True),
            ],
            spacing=4,
            expand=True,
        )
    ]
    if route != "/help" and on_open_help is not None:
        controls.append(
            ft.TextButton(
                "Help & Glossary",
                key="shell.open-help",
                tooltip="Open score, data and authority definitions",
                on_click=on_open_help,
            )
        )
    return panel(
        ft.Row(
            controls,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    )


def help_glossary_page(page: ft.Page | None, state: AppState) -> ft.Control:
    route = str(getattr(page, "route", "") or "") if page is not None else ""
    target = route.split("#", 1)[1].casefold() if "#" in route else ""

    def _slug(term: str) -> str:
        return term.casefold().replace(" ", "-").replace("/", "-")

    def open_help(term: str) -> None:
        if page is None:
            return
        suffix = f"#{_slug(term)}" if term else ""
        go = getattr(page, "go", None)
        if callable(go):
            go(f"/help{suffix}")
        else:
            page.route = f"/help{suffix}"
    loaded = load_glossary()
    legal_report = legal_terms_report(Path.cwd())
    if loaded.policy is not None and not loaded.diagnostic_mode:
        rows: list[ft.Control] = [
            panel(
                ft.Column(
                    [
                        ft.TextButton(
                            entry.term,
                            key=f"help.glossary-term.{_slug(entry.term)}",
                            tooltip=f"Open glossary definition for {entry.term}",
                            on_click=lambda _event, term=entry.term: open_help(term),
                        ),
                        ft.Text("Selected definition", color=theme.CYAN, size=10) if target == _slug(entry.term) else ft.Container(height=0),
                        ft.Text(entry.definition, color=theme.MUTED, selectable=True),
                        ft.Text(entry.authority_note or "Authority remains bounded by evidence and policy.", color=theme.AMBER, size=11, selectable=True),
                    ],
                    spacing=6,
                ),
                expand=True,
            )
            for entry in loaded.policy.entries
        ]
    else:
        rows = [panel(ft.Text("Unavailable: glossary policy could not be loaded. Manual review is required.", color=theme.AMBER, selectable=True))]
    return ft.Column(
        [
            section_header("Help and glossary", "Definitions are explanatory and do not grant authority."),
            ft.Text("Authority is evidence-bounded. Manual review is required whenever evidence is incomplete or stale. Unavailable states are explicit and never imply a positive decision.", color=theme.MUTED, selectable=True),
            ft.Text("User guide: docs/user/USER_GUIDE.md", color=theme.CYAN, selectable=True),
            panel(ft.Column([section_header("Terms and use boundaries", "The registry records source and model permissions for local replay and audit export."), ft.Text("Research and education only. Not financial or tax advice. No broker execution or order transmission.", color=theme.AMBER, selectable=True), ft.Text(f"Legal terms status: {legal_report['status']} ({legal_report['review_status']}); restricted sources are not redistributed.", color=theme.MUTED, selectable=True)], spacing=6)),
            ft.ResponsiveRow([ft.Container(content=row, col={"xs": 12, "md": 6}) for row in rows], spacing=12),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["PAGE_HELP", "help_glossary_page", "page_help_panel"]
