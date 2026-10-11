"""Governance glossary surface."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.glass_pages import page_panel
from etf_cockpit.app.components.kit import (
    Button,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    GlossaryItem,
    Headline,
    KpiTile,
    ListRow,
    Note,
    Tag,
    field_input_style,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._p1_common import go, grid, make_layout, refresh, text, with_edge_fade
from etf_cockpit.app.state import AppState
from etf_cockpit.application.scope_facade import load_glossary
from etf_cockpit.application.ui_facade import legal_terms_report
from etf_cockpit.application.ui_views.help import (
    SEGMENTS,
    GlossaryTerm,
    build_terms,
    filter_terms,
    find_term,
    related_terms_for,
    sentences,
    slugify,
)
from etf_cockpit.core.navigation import ROUTE_TITLES


panel = page_panel("help")


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
    "/sectors": "Read sector and country returns on the globe and the map. Returns are shown only where loaded evidence supports them; a missing region stays unavailable and is never filled with zero.",
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
                ft.Text(f"About {title}", color=theme.CYAN, size=theme.FONT_XS, weight=ft.FontWeight.BOLD),
                ft.Text(description, color=theme.MUTED, size=theme.FONT_XS, selectable=True),
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


def _fit_size(word: str, size: float = 54, comfortable: int = 18) -> float:
    """Scale a headline word down so long terms still fit their card (text protection)."""
    return size if len(word) <= comfortable else max(28.0, round(size * comfortable / len(word), 1))


def help_glossary_page(page: ft.Page | None, state: AppState) -> PageView:
    route = str(getattr(page, "route", "") or "") if page is not None else ""
    target = route.split("#", 1)[1].casefold() if "#" in route else ""
    loaded = load_glossary()
    legal_report = legal_terms_report(Path.cwd())
    titles = dict(ROUTE_TITLES)
    available = loaded.policy is not None and not loaded.diagnostic_mode
    terms = build_terms(loaded.policy.entries if available else (), PAGE_HELP, titles)
    layout = make_layout(page)
    came_from = str(getattr(state, "previous_route", "") or "/")
    selection = {
        "view": "Glossary",
        "slug": target if find_term(terms, target) else (terms[0].slug if terms else ""),
        "query": "",
    }
    holder = ft.Container(expand=True)
    list_holder = ft.Container(expand=True)
    definition_holder = ft.Container(expand=True)
    search = ft.TextField(key="help.glossary-term.search", on_change=None, **field_input_style(placeholder="Type a term…"))
    glossary_note: dict[str, ft.Text] = {}

    def go_to(route_name: str) -> None:
        go(page, state, route_name)

    def open_help(term: str) -> None:
        selection["slug"] = slugify(term)
        paint_glossary()

    def paint_glossary() -> None:
        shown = filter_terms(terms, selection["query"])
        items = []
        for entry in shown:
            item = GlossaryItem(
                entry.term,
                entry.gloss,
                entry.slug == selection["slug"],
                key=f"help.glossary-term.{entry.slug}",
            )
            item.content.alignment = ft.MainAxisAlignment.SPACE_BETWEEN  # kit row is loose-fit: push the gloss right
            item.on_click = lambda _event, name=entry.term: open_help(name)
            items.append(item)
        list_holder.content = (
            with_edge_fade(ft.ListView(items, spacing=4, expand=True))
            if items
            else EmptyState("No matching term", "Try a shorter search, or clear the search field.")
        )
        if "note" in glossary_note:
            glossary_note["note"].value = f"{len(shown)} of {len(terms)} terms"
        definition_holder.content = _definition_card(find_term(terms, selection["slug"]), terms, open_help, available)
        refresh(list_holder)
        refresh(definition_holder)
        if "note" in glossary_note:
            refresh(glossary_note["note"])

    def search_changed(event: object | None = None) -> None:
        selection["query"] = search.value or ""
        paint_glossary()

    search.on_change = search_changed

    def paint_view() -> None:
        holder.content = _view_body(
            selection["view"], layout, page, state, list_holder, definition_holder, search, glossary_note,
            terms, came_from, legal_report, len(terms), go_to,
        )
        refresh(holder)

    def choose_view(value: str) -> None:
        selection["view"] = value
        paint_view()

    paint_glossary()
    paint_view()
    return PageView(
        chrome=PageChrome(
            "Help & Glossary",
            "Score, data and authority definitions",
            (SegmentGroup("view", SEGMENTS, "Glossary", choose_view),),
        ),
        body=holder,
    )


def _definition_card(term: GlossaryTerm | None, terms, open_help, available: bool) -> ft.Control:
    if term is None:
        reason = (
            "The glossary policy has no entries."
            if available
            else "Unavailable: glossary policy could not be loaded. Manual review is required."
        )
        return GlassCard("Selected definition", "", body=EmptyState("No term selected", reason), expand=True)
    used = term.where_used
    related = [
        ft.Container(
            content=text(name, 14, 600, theme.ACC),
            on_click=lambda _event, name=name: open_help(name),
            ink=True,
            padding=ft.Padding(left=4, top=4, right=4, bottom=4),
            border_radius=theme.RADIUS_SM,
        )
        for name in term.related
    ]
    related_row = ft.Row(
        [text("Related", 14.5, 650), *(related or [text("—", 14, 400, theme.INK3)])],
        spacing=16,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    body = ft.Column(
        [
            Headline(term.term, _fit_size(term.term)),
            ft.Container(
                content=text(term.definition, 15, 400, theme.INK2, line_height=22),
                width=760,
            ),
            *([Note(f"Authority: {term.authority_note}")] if term.authority_note else []),
            ft.Row(
                [
                    KpiTile("Where used", used[0] if used else None,
                            ", ".join(used[1:]) if len(used) > 1 else ("" if used else "Not named in any page help"),
                            expand=True),
                    KpiTile("Source", "local registry", "no zero-fill", expand=True),
                    KpiTile("Authority", "none", "advisory only", tone="neg", expand=True),
                ],
                spacing=12,
            ),
            related_row,
        ],
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    return GlassCard("Selected definition", term.term, body=body, expand=True)


def _about_card(title: str = "About this page") -> ft.Control:
    rows = [
        ("Read the verdict first", "Each page leads with one answer and the reasons behind it."),
        ("Every chart is labelled", "Axis names and units are always shown."),
        ("Switch views in place", "Pills change the metric or range without leaving the page."),
    ]
    return GlassCard(
        title,
        "route-specific help",
        body=ft.Column(
            [ListRow("info", head, sub, last=index == len(rows) - 1) for index, (head, sub) in enumerate(rows)],
            spacing=0,
        ),
        expand=True,
    )


def _terms_card(page, legal_report, *, extended: bool) -> ft.Control:
    guide = "docs/user/USER_GUIDE.md"

    def open_guide(_event: object | None = None) -> None:
        try:
            page.run_task(page.launch_url, Path(guide).resolve().as_uri())
        except Exception:
            _toast(page, "The user guide could not be opened here.")

    def copy_path(_event: object | None = None) -> None:
        try:
            page.run_task(page.clipboard.set, guide)
            _toast(page, "Path copied")
        except Exception:
            _toast(page, "The path could not be copied here.")

    column: list[ft.Control] = [
        text(
            "Research and education only. Not financial or tax advice. No broker execution or order transmission. "
            "The registry records source and model permissions for local replay and audit export.",
            14, 400, theme.INK2, line_height=21,
        ),
    ]
    if extended:
        column.append(
            Note(
                f"Legal terms status: {legal_report['status']} ({legal_report['review_status']}); "
                "restricted sources are not redistributed."
            )
        )
    column += [
        ft.Row([Button.primary("Open user guide", open_guide), Button.secondary("Copy guide path", copy_path)], spacing=12),
        Disclosure("user guide path", guide),
        ft.Row(
            [
                KpiTile("Execution", "locked", "execution_allowed=false", tone="neg", expand=True),
                KpiTile("Data", "local-first", "nothing uploaded", expand=True),
                KpiTile("Models", "optional", "baseline always on", expand=True),
            ],
            spacing=12,
        ),
    ]
    return GlassCard("Terms and use boundaries", "", body=ft.Column(column, spacing=16, scroll=ft.ScrollMode.AUTO, expand=True),
                     expand=True)


def _toast(page: object, message: str) -> None:
    try:
        page.show_dialog(ft.SnackBar(content=text(message, 13.5, 500), duration=4000))
    except Exception:
        pass


def _view_body(view, layout, page, state, list_holder, definition_holder, search, glossary_note, terms, came_from,
               legal_report, total, go_to) -> ft.Control:
    row_b = [(_about_card(), 6), (_terms_card(page, legal_report, extended=False), 6)]
    if view == "Glossary":
        card = GlassCard(
            "Glossary",
            f"{total} of {total} terms",
            body=ft.Column([Field("Search terms", search), ft.Container(content=list_holder, expand=True)],
                           spacing=12, expand=True),
            expand=True,
        )
        glossary_note["note"] = card.data["note_control"]
        return grid(layout, [[(card, 4), (definition_holder, 8)], row_b])
    if view == "This page":
        title = dict(ROUTE_TITLES).get(came_from, "Simple Scores")
        about = PAGE_HELP.get(came_from, PAGE_HELP["/"])
        parts = sentences(about)
        rows = [ListRow("info", part, "", last=index == len(parts) - 1) for index, part in enumerate(parts)]
        chips = related_terms_for(about, terms)
        body = ft.Column(
            [
                ft.Container(content=text(about, 15, 400, theme.INK2, line_height=22), width=900),
                text("How to read it", 14.5, 650),
                ft.Column(rows, spacing=0),
                ft.Row(
                    [text("Related terms", 14.5, 650), *(Tag(name, "mute") for name in chips)] if chips
                    else [text("Related terms", 14.5, 650), text("—", 14, 400, theme.INK3)],
                    spacing=12, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                Button.primary(f"Back to {title}", lambda _event: go_to(came_from)),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        return grid(layout, [[(GlassCard(f"About {title}", "", body=body, expand=True), 12)], row_b])
    boundaries = [
        ("Authority is evidence-bounded", "No score, forecast or model output creates an order."),
        ("Manual review when evidence is incomplete or stale", "Gaps lower authority; they are never filled in."),
        ("Unavailable is explicit, never zero", "A missing value is shown as unavailable with its reason."),
        ("Definitions do not grant authority", "The glossary explains terms; it cannot change a gate."),
    ]
    authority = GlassCard(
        "Authority boundaries",
        "",
        body=ft.Column(
            [ListRow("ok", head, sub, last=index == len(boundaries) - 1) for index, (head, sub) in enumerate(boundaries)],
            spacing=0,
        ),
        expand=True,
    )
    return grid(layout, [[(_terms_card(page, legal_report, extended=True), 6), (authority, 6)], row_b])


__all__ = ["PAGE_HELP", "help_glossary_page", "page_help_panel"]
