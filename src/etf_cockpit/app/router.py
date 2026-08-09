from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.command_palette import PaletteCommand, search_commands
from etf_cockpit.app.components.cards import panel
from etf_cockpit.app.components.flet_compat import border_only, padding_symmetric
from etf_cockpit.app.pages.backtests import backtests_page
from etf_cockpit.app.pages.catalogue import catalogue_page
from etf_cockpit.app.pages.comparison import comparison_page
from etf_cockpit.app.pages.chatgpt_audit import chatgpt_audit_page
from etf_cockpit.app.pages.dashboard import dashboard_page
from etf_cockpit.app.pages.data_models import data_models_page
from etf_cockpit.app.pages.forecast_lab import forecast_lab_page
from etf_cockpit.app.pages.training_centre import training_centre_page
from etf_cockpit.app.pages.feature_catalogue import feature_catalogue_page
from etf_cockpit.app.pages.macro_factors import macro_factors_page
from etf_cockpit.app.pages.diagnostics import diagnostics_page
from etf_cockpit.app.pages.data_health import data_health_page
from etf_cockpit.app.pages.errors_recovery import errors_recovery_page
from etf_cockpit.app.pages.onboarding import onboarding_page
from etf_cockpit.app.pages.operations import operations_page
from etf_cockpit.app.pages.universe_manager import universe_manager_page
from etf_cockpit.app.pages.what_changed import what_changed_page
from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.app.pages.import_export import import_export_page
from etf_cockpit.app.pages.system_map import system_map_page
from etf_cockpit.app.pages.help_glossary import help_glossary_page
from etf_cockpit.app.pages.decision_journal import decision_journal_page
from etf_cockpit.app.pages.forward_evidence import forward_evidence_page
from etf_cockpit.app.pages.jobs import jobs_page
from etf_cockpit.app.pages.portfolio import portfolio_page
from etf_cockpit.app.pages.portfolio_optimiser import portfolio_optimiser_page
from etf_cockpit.app.pages.risk import risk_page
from etf_cockpit.app.pages.stress_lab import stress_lab_page
from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.pages.screener import screener_page
from etf_cockpit.app.pages.stock_research import stock_research_page
from etf_cockpit.app.pages.signals import signals_page
from etf_cockpit.app.pages.trust_evidence import (
    etf_disclosures_page,
    evidence_ledger_page,
    filings_page,
    news_context_page,
    provider_status_page,
)
from etf_cockpit.app.pages.release_readiness import release_readiness_page
from etf_cockpit.app.pages.programme_map import programme_map_page
from etf_cockpit.app.state import AppState
from etf_cockpit.core.session_log import log_event

PAGES = {
    "/": ("Simple Scores", dashboard_page),
    "/portfolio": ("Portfolio Sandbox", portfolio_page),
    "/portfolio-optimiser": ("Portfolio Optimiser Lab", portfolio_optimiser_page),
    "/signals": ("Scores", signals_page),
    "/screener": ("Fundamentals Screener", screener_page),
    "/comparison": ("Comparison", comparison_page),
    "/stock-research": ("Stock Research", stock_research_page),
    "/risk": ("Risk Evidence", risk_page),
    "/stress-lab": ("Stress Lab", stress_lab_page),
    "/etf": ("Instrument Detail", instrument_detail_page),
    "/backtests": ("Backtests", backtests_page),
    "/chatgpt": ("Audit Notes", chatgpt_audit_page),
    "/providers": ("Provider Status", provider_status_page),
    "/evidence": ("Evidence Ledger", evidence_ledger_page),
    "/filings": ("Filings & Statements", filings_page),
    "/etf-disclosures": ("ETF Disclosures", etf_disclosures_page),
    "/news-context": ("News & Context", news_context_page),
    "/data-models": ("Data & Models", data_models_page),
    "/forecasts": ("Forecast Lab", forecast_lab_page),
    "/training-centre": ("Training Centre", training_centre_page),
    "/feature-catalogue": ("Feature Catalogue", feature_catalogue_page),
    "/catalogue": ("Data Catalogue", catalogue_page),
    "/macro": ("Macro and Factors", macro_factors_page),
    "/settings": ("Settings", settings_page),
    "/diagnostics": ("Diagnostics", diagnostics_page),
    "/errors": ("Errors & Recovery", errors_recovery_page),
    "/data-health": ("Data Health", data_health_page),
    "/universe": ("Universe", universe_manager_page),
    "/onboarding": ("First-run Setup", onboarding_page),
    "/what-changed": ("What Changed", what_changed_page),
    "/instrument": ("Instrument Detail", instrument_detail_page),
    "/import-export": ("Import & Export", import_export_page),
    "/system-map": ("System Map", system_map_page),
    "/help": ("Help & Glossary", help_glossary_page),
    "/decision-journal": ("Decision Journal", decision_journal_page),
    "/forward-evidence": ("Forward Evidence Diary", forward_evidence_page),
    "/jobs": ("Jobs & Activity", jobs_page),
    "/operations": ("Operations Centre", operations_page),
    "/release-readiness": ("Release Readiness", release_readiness_page),
    "/roadmap": ("Programme Map", programme_map_page),
}

# One stable information architecture for the existing routes. The pages stay
# independently testable while the shell gives them a decision-oriented home.
WORKSPACE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Home", ("/",)),
    ("Discover", ("/signals", "/screener", "/comparison", "/stock-research", "/universe", "/what-changed")),
    ("Instrument", ("/etf", "/instrument")),
    ("Portfolio", ("/portfolio", "/portfolio-optimiser", "/risk", "/stress-lab")),
    ("Models", ("/data-models", "/forecasts", "/training-centre", "/feature-catalogue", "/macro")),
    ("Backtest/Paper", ("/backtests", "/operations", "/forward-evidence")),
    ("Data Health", ("/providers", "/filings", "/etf-disclosures", "/news-context", "/catalogue", "/data-health")),
    ("Audit", ("/chatgpt", "/evidence", "/decision-journal", "/release-readiness", "/roadmap")),
    ("Settings", ("/settings", "/diagnostics", "/errors", "/onboarding", "/import-export", "/system-map", "/help", "/jobs")),
)

NARROW_LAYOUT_BREAKPOINT = 1100


def instrument_detail_route(instrument_id: str) -> str:
    """Return the canonical inspect route for a configured instrument ID."""

    value = str(instrument_id or "").strip()
    return f"/instrument/{value}" if value else "/instrument"


def _page_route(route: str) -> str:
    """Return the registered route while preserving query/hash targets for pages."""

    value = str(route or "/").split("?", 1)[0].split("#", 1)[0] or "/"
    if value.startswith("/instrument/"):
        return "/instrument"
    return value


def workspace_for_route(route: str) -> str:
    canonical_route = _page_route(route)
    for workspace, routes in WORKSPACE_GROUPS:
        if canonical_route in routes:
            return workspace
    return "Home"


def uses_narrow_layout(page: ft.Page, state: AppState) -> bool:
    """Return whether the shell should use its stacked, sidebar-free layout."""

    page_width = float(getattr(page, "width", 0) or state.snapshot.config.ui.window_width)
    return page_width < NARROW_LAYOUT_BREAKPOINT


def navigate_to(page: ft.Page, state: AppState, route: str, *, candidate_score: object | None = None) -> None:
    if str(route).startswith("/instrument/"):
        selected = str(route).split("/", 2)[-1].strip()
        if selected:
            state.selected_etf = selected
            state.selected_instrument_score = candidate_score
    go = getattr(page, "go", None)
    if callable(go):
        go(route)
    else:
        page.route = route
    log_event(
        event_type="button_click",
        severity="info",
        route=route,
        component="navigation",
        button_label=PAGES.get(_page_route(route), ("Unknown", None))[0],
        operation="navigate_to",
        status="started",
    )
    render_shell(page, state, route)


def build_shell(page: ft.Page, state: AppState, route: str) -> ft.View:
    canonical_route = _page_route(route)
    page_entry = PAGES.get(canonical_route)
    title = page_entry[0] if page_entry is not None else "Route unavailable"
    builder = page_entry[1] if page_entry is not None else None
    narrow = uses_narrow_layout(page, state)

    def nav_button(path: str, label: str) -> ft.Container:
        selected = path == canonical_route
        button = ft.TextButton(
            label,
            key=f"navigation.{path.strip('/').replace('/', '-') or 'home'}",
            tooltip=label,
            on_click=lambda _e, p=path: navigate_to(page, state, p),
        )
        return ft.Container(
            tooltip=label,
            content=button,
            bgcolor=theme.SURFACE_2 if selected else None,
            border_radius=theme.RADIUS_SM,
            padding=padding_symmetric(horizontal=theme.SPACE_3, vertical=theme.SPACE_2),
        )

    def navigation_controls() -> list[ft.Control]:
        controls: list[ft.Control] = []
        for workspace, routes in WORKSPACE_GROUPS:
            controls.append(ft.Text(workspace, color=theme.MUTED, size=theme.FONT_XS, weight=ft.FontWeight.BOLD))
            controls.extend(nav_button(path, PAGES[path][0]) for path in routes)
        return controls

    active_workspace = workspace_for_route(canonical_route)
    mode_options = [ft.dropdown.Option(value, theme.EVIDENCE_MODE_LABELS[value]) for value in theme.EVIDENCE_MODES]

    def evidence_mode_changed(event: ft.ControlEvent) -> None:
        value = getattr(getattr(event, "control", None), "value", None) or getattr(event, "data", None)
        if value in theme.EVIDENCE_MODES:
            state.set_evidence_mode(value)
            page.update()

    evidence_mode = ft.Dropdown(
        key="shell.evidence-mode",
        label="Evidence mode",
        value=state.evidence_mode,
        options=mode_options,
        width=210 if not narrow else 170,
        dense=True,
        on_select=evidence_mode_changed,
    )

    palette_results = ft.Container(visible=False)

    def select_palette_command(command: PaletteCommand) -> None:
        navigate_to(page, state, command.route)

    def show_palette_message(message: str) -> None:
        palette_results.content = panel(ft.Column([ft.Text(message, color=theme.AMBER, size=theme.FONT_SM, selectable=True)]))
        palette_results.visible = True
        state.last_message = message
        if callable(getattr(page, "update", None)):
            page.update()

    def render_palette_results(event: ft.ControlEvent) -> None:
        query = str(getattr(getattr(event, "control", None), "value", None) or "")
        matches = search_commands(PAGES, WORKSPACE_GROUPS, query)
        result_controls: list[ft.Control] = [
            ft.Text("Command palette results", color=theme.MUTED, size=theme.FONT_XS, weight=ft.FontWeight.BOLD)
        ]
        result_controls.extend(
            ft.TextButton(
                f"{command.title} · {command.workspace} · {command.route}",
                key=f"shell.command.{command.route.strip('/').replace('/', '-') or 'home'}",
                tooltip=f"Open {command.title}",
                on_click=lambda _event, item=command: select_palette_command(item),
            )
            for command in matches
        )
        if not matches:
            result_controls.append(ft.Text("No matching workspace", color=theme.AMBER, size=theme.FONT_SM, selectable=True))
        palette_results.content = panel(ft.Column(result_controls, spacing=2))
        palette_results.visible = bool(query.strip())
        if callable(getattr(page, "update", None)):
            page.update()

    def submit_palette(event: ft.ControlEvent) -> None:
        query = str(getattr(getattr(event, "control", None), "value", None) or "")
        if not query.strip():
            show_palette_message("Enter a page or workspace to search")
            return
        matches = search_commands(PAGES, WORKSPACE_GROUPS, query, limit=1)
        if matches:
            select_palette_command(matches[0])
        else:
            show_palette_message("No matching workspace")

    palette_field = ft.TextField(
        key="shell.command-palette",
        label="Command palette",
        hint_text="Search pages or commands",
        dense=True,
        width=250 if not narrow else 220,
        on_change=render_palette_results,
        on_submit=submit_palette,
    )
    sidebar = ft.Container(
        width=220,
        bgcolor=theme.SURFACE,
        border=border_only(right=ft.BorderSide(width=1, color=theme.BORDER)),
        padding=theme.SPACE_3,
        content=ft.Column(
            [
                ft.Text(theme.APP_NAME, color=theme.TEXT, size=theme.FONT_XL, weight=ft.FontWeight.BOLD),
                ft.Text(theme.APP_TAGLINE, color=theme.MUTED, size=theme.FONT_XS),
                ft.Text(f"Workspace: {active_workspace}", color=theme.CYAN, size=theme.FONT_XS),
            ]
            + navigation_controls(),
            spacing=theme.SPACE_2,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )
    mobile_nav = ft.Container(
        bgcolor=theme.SURFACE,
        border=border_only(bottom=ft.BorderSide(width=1, color=theme.BORDER)),
        padding=padding_symmetric(horizontal=theme.SPACE_3, vertical=theme.SPACE_2),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(theme.APP_NAME, color=theme.TEXT, size=theme.FONT_LG, weight=ft.FontWeight.BOLD),
                        ft.Text("local", color=theme.MUTED, size=11),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Text(f"Workspace: {active_workspace}", color=theme.CYAN, size=theme.FONT_XS),
                ft.Row(navigation_controls(), spacing=theme.SPACE_1, wrap=True, scroll=ft.ScrollMode.AUTO),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    header_content: ft.Control
    title_column = ft.Column(
        [
            ft.Text(title, color=theme.TEXT, size=theme.FONT_LG if narrow else theme.FONT_XL, weight=ft.FontWeight.BOLD),
            ft.Text(f"{active_workspace} | Data date {state.snapshot.data_report.as_of_date}", color=theme.MUTED, size=theme.FONT_XS),
        ],
        spacing=theme.SPACE_1,
        expand=True,
    )
    if narrow:
        header_content = ft.Column(
            [
                ft.Row([title_column, evidence_mode], spacing=theme.SPACE_2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                palette_field,
            ],
            spacing=theme.SPACE_2,
        )
    else:
        header_content = ft.Row(
            [
                title_column,
                palette_field,
                ft.Text(state.last_message, color=theme.MUTED, size=theme.FONT_XS, text_align=ft.TextAlign.RIGHT),
                evidence_mode,
            ],
            spacing=theme.SPACE_2,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    header = ft.Container(
        bgcolor=theme.BG,
        border=border_only(bottom=ft.BorderSide(width=1, color=theme.BORDER)),
        padding=padding_symmetric(horizontal=theme.SPACE_3 if narrow else theme.SPACE_5, vertical=theme.SPACE_2 if narrow else theme.SPACE_3),
        content=header_content,
    )
    progress_strip: ft.Control
    if state.current_activity is not None:
        progress_strip = ft.Container(
            bgcolor=theme.SURFACE,
            border=border_only(bottom=ft.BorderSide(width=1, color=theme.BORDER)),
            padding=padding_symmetric(horizontal=theme.SPACE_5, vertical=theme.SPACE_2),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.ProgressRing(width=16, height=16, stroke_width=2, color=theme.CYAN),
                            ft.Text(state.current_activity.label, color=theme.TEXT, size=theme.FONT_SM, weight=ft.FontWeight.BOLD),
                            ft.Text(state.current_activity.step, color=theme.MUTED, size=theme.FONT_SM, expand=True),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.ProgressBar(value=None, color=theme.CYAN, bgcolor=theme.SURFACE_2),
                ],
                spacing=6,
            ),
        )
    else:
        progress_strip = ft.Container(height=0)
    if builder is None:
        page_content = _route_failure_control(state, route, "The requested route is not registered.")
    else:
        try:
            page_content = builder(page, state)
        except Exception as exc:
            page_content = _route_failure_control(
                state,
                route,
                f"The page could not be rendered safely ({type(exc).__name__}).",
            )
    body = ft.Column(
        [
            header,
            palette_results,
            progress_strip,
            ft.Container(content=page_content, expand=True, padding=theme.SPACE_3 if narrow else theme.SPACE_5),
            ft.Container(
                height=28,
                bgcolor=theme.SURFACE,
                border=border_only(top=ft.BorderSide(width=1, color=theme.BORDER)),
                padding=padding_symmetric(horizontal=theme.SPACE_5, vertical=theme.SPACE_1),
                content=ft.Text("Local evidence scoring only. No broker execution. Model and LLM output are advisory inputs, not trading authority.", color=theme.MUTED, size=theme.FONT_XS),
            ),
        ],
        expand=True,
        spacing=0,
    )
    controls: list[ft.Control]
    if narrow:
        controls = [ft.Column([mobile_nav, body], expand=True, spacing=0)]
    else:
        controls = [ft.Row([sidebar, body], expand=True, spacing=0)]
    return ft.View(route=route, controls=controls, bgcolor=theme.BG, padding=0)


def _route_failure_control(state: AppState, route: str, detail: str) -> ft.Control:
    message = f"Route failure: {route or '/'} · {detail} No action was executed."
    state.last_message = message
    log_event(
        event_type="route_render_failure",
        severity="error",
        route=route,
        component="navigation",
        button_label="Route unavailable",
        operation="render_shell",
        status="failed",
        message=detail,
    )
    return ft.Container(
        key="router.route-error",
        content=panel(
            ft.Column(
                [
                    ft.Text("Route unavailable", color=theme.AMBER, size=theme.FONT_LG, weight=ft.FontWeight.BOLD),
                    ft.Text(message, color=theme.TEXT, selectable=True),
                    ft.Text("Return to a registered workspace from navigation or the command palette.", color=theme.MUTED),
                ],
                spacing=theme.SPACE_2,
            )
        ),
    )


def render_shell(page: ft.Page, state: AppState, route: str) -> None:
    view = build_shell(page, state, route)
    page.views[:] = [view]
    page.update()
