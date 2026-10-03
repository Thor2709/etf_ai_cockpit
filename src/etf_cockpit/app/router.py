from __future__ import annotations

from base64 import b64encode
from importlib.resources import files
from pathlib import Path

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.command_palette import search_commands
from etf_cockpit.app.components.cards import panel
from etf_cockpit.app.components.kit import backdrop, glass_panel
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
from etf_cockpit.app.pages.help_glossary import help_glossary_page, page_help_panel
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
from etf_cockpit.app.pages.strategy_builder import strategy_builder_page
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
from etf_cockpit.core.ui_acceptance import UIInvocationResult, command_contract_from_metadata

PAGES = {
    "/": ("Simple Scores", dashboard_page),
    "/portfolio": ("Portfolio Sandbox", portfolio_page),
    "/portfolio-optimiser": ("Portfolio Optimiser Lab", portfolio_optimiser_page),
    "/signals": ("Scores", signals_page),
    "/strategy-builder": ("Strategy Builder", strategy_builder_page),
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
    ("Home", ("/", "/onboarding")),
    ("Research", ("/stock-research", "/etf", "/instrument", "/signals", "/screener", "/strategy-builder")),
    ("Compare", ("/comparison",)),
    ("Map", ("/macro",)),
    ("Universe", ("/universe", "/catalogue", "/providers", "/filings", "/etf-disclosures", "/news-context", "/data-health")),
    ("Portfolio", ("/portfolio", "/portfolio-optimiser", "/risk", "/stress-lab", "/decision-journal", "/forward-evidence", "/operations")),
    ("Lab", ("/forecasts", "/training-centre", "/feature-catalogue", "/data-models", "/backtests")),
    ("Changes", ("/what-changed", "/jobs")),
    ("Help", ("/help", "/settings", "/diagnostics", "/errors", "/import-export", "/system-map", "/chatgpt", "/evidence", "/release-readiness", "/roadmap")),
)

WORKSPACE_ICONS = {
    "Home": "house",
    "Research": "telescope",
    "Compare": "abacus",
    "Map": "compass",
    "Universe": "globe",
    "Portfolio": "briefcase",
    "Lab": "alembic",
    "Changes": "newspaper",
    "Help": "bulb",
}

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


def uses_narrow_layout(page: ft.Page, state: AppState, width: float | None = None) -> bool:
    """Return whether the shell should use its stacked, sidebar-free layout."""

    page_width = float(width or getattr(page, "width", 0) or state.snapshot.config.ui.window_width)
    return page_width < NARROW_LAYOUT_BREAKPOINT


def _available_display(value: object, reason: str) -> tuple[str, str | None]:
    if value is None:
        return "Unavailable", reason
    rendered = str(value).strip()
    if rendered.casefold() in {"", "none", "nan", "nat", "<na>", "unavailable"}:
        return "Unavailable", reason
    return rendered, None


def _safety_rail(state: AppState, data_report: object) -> ft.Container:
    snapshot = getattr(state, "snapshot", None)
    quality_value, quality_reason = _available_display(
        getattr(data_report, "status", None),
        "The current snapshot has no data-quality status.",
    )
    as_of_value, as_of_reason = _available_display(
        getattr(snapshot, "as_of_time", getattr(data_report, "as_of_time", None)),
        "The current snapshot provides an as-of date but no as-of timestamp.",
    )
    forecasts = getattr(snapshot, "forecasts", None)
    forecast_value: object = None
    forecast_reason = "No forecast source is available in the current snapshot."
    if forecasts is not None and not getattr(forecasts, "empty", True) and "source_file" in getattr(forecasts, "columns", ()):
        raw_forecast_source = forecasts["source_file"].iloc[0]
        forecast_value = Path(str(raw_forecast_source)).name
        forecast_reason = "The current snapshot has no forecast source file."
    forecast_display, forecast_reason = _available_display(forecast_value, forecast_reason)

    def rail_item(key: str, label: str, value: str, reason: str | None = None) -> ft.Container:
        return ft.Container(
            key=key,
            data="unavailable" if value == "Unavailable" else "available",
            tooltip=reason or label,
            content=ft.Text(
                "Execution locked"
                if label == "Execution locked"
                else f"execution_allowed={value}"
                if label == "execution_allowed"
                else f"{label}: {value}",
                color=theme.TEXT,
                size=theme.FONT_XS,
            ),
            bgcolor="#4c040a1a",
            border=ft.Border(
                left=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                top=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                right=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                bottom=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
            ),
            border_radius=999,
            padding=ft.Padding(left=9, top=4, right=9, bottom=4),
        )

    rail_contents: list[ft.Control] = [
        rail_item(
            "shell.safety.execution",
            "Execution locked",
            "Execution locked",
            "Execution is permanently locked in this application.",
        ),
        rail_item("shell.safety.data-quality", "Data quality", quality_value, quality_reason),
        rail_item("shell.safety.as-of-time", "As of time", as_of_value, as_of_reason),
        rail_item("shell.safety.price-basis", "Price basis", "adjusted"),
        rail_item("shell.safety.forecast-source", "Forecast source", forecast_display, forecast_reason),
        rail_item("shell.safety.execution-authority", "execution_allowed", "false"),
    ]
    return ft.Container(
        key="shell.safety-rail",
        content=ft.Row(rail_contents, spacing=6, scroll=ft.ScrollMode.AUTO, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=48,
        padding=ft.Padding(left=8, top=4, right=8, bottom=4),
        gradient=ft.LinearGradient(
            colors=("#7a0e1830", "#66081024"),
            begin=ft.Alignment(0, -1),
            end=ft.Alignment(0, 1),
        ),
        blur=theme.GLASS_PANEL_BLUR,
        border=ft.Border(
            left=ft.BorderSide(width=1, color=theme.FOOTER_RAIL_BORDER),
            top=ft.BorderSide(width=1, color=theme.FOOTER_RAIL_BORDER),
            right=ft.BorderSide(width=1, color=theme.FOOTER_RAIL_BORDER),
            bottom=ft.BorderSide(width=1, color=theme.FOOTER_RAIL_BORDER),
        ),
        border_radius=theme.FOOTER_RAIL_RADIUS,
    )


def navigate_to(page: ft.Page, state: AppState, route: str, *, candidate_score: object | None = None) -> None:
    if str(route).startswith("/instrument/"):
        selected = str(route).split("/", 2)[-1].strip()
        if selected:
            state.selected_etf = selected
            state.selected_instrument_score = candidate_score
    go = getattr(page, "go", None)
    native_transition = (
        isinstance(page, ft.Page)
        and callable(getattr(page, "on_route_change", None))
        and page.route != route
    )
    if callable(go) and page.route != route:
        go(route)
    elif not callable(go):
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
    # Native go() queues a browser event; that handler owns the render.
    # Same-route refreshes and non-native test/embedded pages render directly.
    if not native_transition:
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
            style=ft.ButtonStyle(
                color=theme.QUAIL_SELECTED_INK if selected else theme.TEXT,
                bgcolor="transparent",
                padding=ft.Padding(left=10, top=6, right=10, bottom=6),
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
        )
        return ft.Container(
            tooltip=label,
            content=button,
            gradient=(
                ft.LinearGradient(
                    colors=list(theme.QUAIL_SELECTED_COLORS),
                    begin=ft.Alignment(0, -1),
                    end=ft.Alignment(0, 1),
                )
                if selected
                else ft.LinearGradient(
                    colors=("#14ffffff", "#0affffff"),
                    begin=ft.Alignment(0, -1),
                    end=ft.Alignment(0, 1),
                )
            ),
            border=ft.Border(
                left=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                top=ft.BorderSide(width=1, color=theme.QUAIL_SELECTED_HIGHLIGHT if selected else theme.HAIRLINE_BORDER),
                right=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                bottom=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
            ),
            border_radius=theme.RADIUS_MD,
            shadow=[ft.BoxShadow(color=theme.QUAIL_SELECTED_SHADOW, blur_radius=0, offset=ft.Offset(0, 3))]
            if selected
            else None,
        )

    active_workspace = workspace_for_route(canonical_route)
    mode_options = [ft.dropdown.Option(value, theme.EVIDENCE_MODE_LABELS[value]) for value in theme.EVIDENCE_MODES]
    snapshot = getattr(state, "snapshot", None)
    data_report = getattr(snapshot, "data_report", None)

    def evidence_mode_changed(event: ft.ControlEvent) -> None:
        value = getattr(getattr(event, "control", None), "value", None) or getattr(event, "data", None)
        if value in theme.EVIDENCE_MODES:
            state.set_evidence_mode(value)
            message_text.value = state.last_message
            page.update()

    evidence_mode = ft.Dropdown(
        key="shell.evidence-mode",
        label="Evidence mode",
        value=state.evidence_mode,
        options=mode_options,
        width=190 if not narrow else 160,
        dense=True,
        on_select=evidence_mode_changed,
    )

    palette_results = ft.Container(visible=False)
    palette_commands: dict[str, object] = {}
    palette_invocations: dict[str, UIInvocationResult] = {}

    def navigate_palette_command(event: ft.ControlEvent) -> None:
        route = str(getattr(getattr(event, "control", None), "data", "") or "")
        if not route:
            raise ValueError("selected command has no registered route")
        navigate_to(page, state, route)

    def show_palette_message(message: str) -> None:
        palette_results.content = panel(ft.Column([ft.Text(message, color=theme.AMBER, size=theme.FONT_SM, selectable=True)]))
        palette_results.visible = True
        state.last_message = message
        if callable(getattr(page, "update", None)):
            page.update()

    def select_palette_command(event: ft.ControlEvent) -> UIInvocationResult | None:
        route = str(getattr(getattr(event, "control", None), "data", "") or "")
        command = palette_commands.get(route)
        if command is None:
            show_palette_message("Selected command has no registered route")
            return None
        contract = command_contract_from_metadata(command)
        result = contract.invoke(
            navigate_palette_command,
            event,
            invoked=palette_invocations,
            show_failure=lambda _message: None,
        )
        if result.status == "failed":
            show_palette_message(f"{result.signal} · {result.visible_message}")
        return result

    def render_palette_results(event: ft.ControlEvent) -> None:
        query = str(getattr(getattr(event, "control", None), "value", None) or "")
        matches = search_commands(PAGES, WORKSPACE_GROUPS, query)
        palette_commands.update({command.route: command for command in matches})
        result_controls: list[ft.Control] = [
            ft.Text("Command palette results", color=theme.MUTED, size=theme.FONT_XS, weight=ft.FontWeight.BOLD)
        ]
        result_controls.extend(
            ft.TextButton(
                f"{command.title} · {command.workspace} · {command.route}",
                key=f"shell.command.{command.route.strip('/').replace('/', '-') or 'home'}",
                tooltip=f"Open {command.title}",
                data=command.route,
                on_click=select_palette_command,
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
            navigate_to(page, state, matches[0].route)
        else:
            show_palette_message("No matching workspace")

    palette_field = ft.TextField(
        key="shell.command-palette",
        label="Command palette",
        hint_text="Search pages or commands",
        dense=True,
        width=300 if not narrow else 220,
        on_change=render_palette_results,
        on_submit=submit_palette,
    )
    palette_column = ft.Column(
        [
            ft.Text("Search or jump to…", key="shell.command-prompt", color=theme.MUTED, size=theme.FONT_XS),
            palette_field,
        ],
        spacing=0,
        tight=True,
    )
    title_column = ft.Column(
        [
            ft.Text(title, color=theme.TEXT, size=theme.FONT_LG if narrow else theme.FONT_XL, weight=ft.FontWeight.BOLD),
            ft.Text(
                theme.APP_TAGLINE,
                color=theme.MUTED,
                size=theme.FONT_XS,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
        ],
        spacing=theme.SPACE_1,
    )
    message_text = ft.Text(state.last_message, color=theme.MUTED, size=theme.FONT_XS, visible=not narrow, col=12)

    def value_pill(key: str, label: str, value: object, unavailable_reason: str) -> ft.Container:
        rendered, reason = _available_display(value, unavailable_reason)
        return ft.Container(
            key=key,
            data="unavailable" if reason else "available",
            tooltip=reason or f"{label}: {rendered}",
            content=ft.Column(
                [
                    ft.Text(label, color=theme.BLUE_GREY, size=theme.FONT_XS, weight=ft.FontWeight.W_600),
                    ft.Text(rendered, color=theme.TEXT, size=theme.FONT_SM, weight=ft.FontWeight.W_600),
                ],
                spacing=1,
                tight=True,
            ),
            bgcolor="#61040a1a",
            border=ft.Border(
                left=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                top=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                right=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                bottom=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
            ),
            border_radius=theme.RADIUS_MD,
            padding=ft.Padding(left=10, top=4, right=10, bottom=4),
            width=130,
        )

    as_of_date = getattr(data_report, "as_of_date", None)
    global_values = ft.Row(
        [
            value_pill(
                "shell.as-of.data-date",
                "Data as-of",
                as_of_date,
                "The current snapshot has no data as-of date.",
            ),
            value_pill("shell.as-of.price-basis", "Price basis", "adjusted", "The shell contract uses adjusted prices."),
            value_pill(
                "shell.as-of.horizon",
                "Horizon",
                getattr(state, "selected_horizon", None),
                "No selected horizon is available in app state.",
            ),
            value_pill(
                "shell.as-of.currency",
                "Currency",
                getattr(state, "selected_currency", None),
                "No selected currency is available in app state.",
            ),
            value_pill(
                "shell.as-of.risk-profile",
                "Risk profile",
                getattr(state, "risk_profile", None),
                "No selected risk profile is available in app state.",
            ),
            value_pill(
                "shell.as-of.analysis-depth",
                "Analysis depth",
                getattr(state, "analysis_depth", None),
                "App state exposes evidence display mode, not analysis depth.",
            ),
        ],
        spacing=6,
        wrap=True,
    )
    sub_navigation = ft.Row(
        [nav_button(path, PAGES[path][0]) for path in next(routes for workspace, routes in WORKSPACE_GROUPS if workspace == active_workspace)],
        key="shell.workspace-navigation",
        spacing=5,
        run_spacing=5,
        wrap=True,
    )

    other_workspace_rows = [
        ft.Column(
            [
                ft.Text(workspace, size=theme.FONT_XS, weight=ft.FontWeight.W_600, color=theme.MUTED),
                ft.Row(
                    [nav_button(path, PAGES[path][0]) for path in routes],
                    spacing=5,
                    run_spacing=5,
                    wrap=True,
                ),
            ],
            spacing=3,
        )
        for workspace, routes in WORKSPACE_GROUPS
        if workspace != active_workspace
    ]
    all_pages_navigation = ft.ExpansionTile(
        title=ft.Text("All pages", size=theme.FONT_SM, color=theme.TEXT),
        key="shell.all-pages-navigation",
        tooltip="Show every page in the other workspaces",
        controls=other_workspace_rows,
        dense=True,
    )

    def _go_to(_event: ft.ControlEvent) -> None:
        navigate_to(page, state, "/what-changed")

    what_changed_button = ft.TextButton(
        "What changed",
        key="dashboard.open-what-changed",
        tooltip="Open What Changed",
        icon=ft.Icons.HISTORY,
        on_click=_go_to,
    )
    header_content = ft.Column(
        [
            ft.Row(
                [title_column, palette_column, evidence_mode, what_changed_button],
                spacing=theme.SPACE_2,
                run_spacing=theme.SPACE_2,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            global_values,
            sub_navigation,
            all_pages_navigation,
            message_text,
        ],
        spacing=theme.SPACE_2,
    )
    header = glass_panel(
        header_content,
        key="shell.topbar",
        label=f"{title} page header",
        padding=12,
    )

    dock_labels: dict[str, ft.Text] = {}

    def dock_item(workspace: str) -> ft.Container:
        selected = workspace == active_workspace
        label = ft.Text(
            workspace,
            key=f"shell.dock.label.{workspace}",
            color=theme.QUAIL_SELECTED_INK if selected else theme.TEXT,
            size=theme.FONT_XS,
            weight=ft.FontWeight.W_600,
            visible=selected and not narrow,
            text_align=ft.TextAlign.CENTER,
        )
        if selected:
            dock_labels[workspace] = label
        icon_name = WORKSPACE_ICONS[workspace]
        icon_path = files("etf_cockpit.app").joinpath("assets", "icons", f"{icon_name}.png")
        icon_data = b64encode(icon_path.read_bytes()).decode("ascii")
        icon = ft.Image(
            src=f"data:image/png;base64,{icon_data}",
            width=50,
            height=50,
            scale=1.06 if selected else 1.0,
            fit=ft.BoxFit.CONTAIN,
            semantics_label=f"{workspace} workspace icon",
        )
        icon_pad = ft.Container(
            content=icon,
            width=54,
            height=54,
            alignment=ft.Alignment(0, 0),
            gradient=(
                ft.LinearGradient(
                    colors=list(theme.QUAIL_SELECTED_COLORS),
                    begin=ft.Alignment(0, -1),
                    end=ft.Alignment(0, 1),
                )
                if selected
                else None
            ),
            border=ft.Border(
                left=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER),
                top=ft.BorderSide(width=1, color=theme.QUAIL_SELECTED_HIGHLIGHT if selected else "transparent"),
                right=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER if selected else "transparent"),
                bottom=ft.BorderSide(width=1, color=theme.HAIRLINE_BORDER if selected else "transparent"),
            ),
            border_radius=theme.RADIUS_MD,
            shadow=[ft.BoxShadow(color=theme.QUAIL_SELECTED_SHADOW, blur_radius=0, offset=ft.Offset(0, 3))]
            if selected
            else None,
        )
        return ft.Container(
            key=f"nav.workspace.{workspace}",
            data="active" if selected else "inactive",
            tooltip=f"Workspace: {workspace}",
            content=ft.Column(
                [icon_pad, label],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=68,
            height=72 if selected and not narrow else 60,
            alignment=ft.Alignment(0, 0),
            on_click=lambda _event, name=workspace: navigate_to(page, state, dict(WORKSPACE_GROUPS)[name][0]),
        )

    dock_items = [dock_item(workspace) for workspace, _routes in WORKSPACE_GROUPS]
    help_item = dock_items.pop()
    dock_content = ft.Column(
        [
            *dock_items,
            ft.Container(key="shell.dock.help-spacer", expand=True),
            help_item,
        ],
        spacing=5,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    dock = glass_panel(dock_content, key="shell.dock", label="Workspace dock", padding=6)
    dock.width = 84
    progress_strip: ft.Control
    if state.current_activity is not None:
        running_action_id = state.current_activity.action_id

        def cancel_running_activity(_event: ft.ControlEvent) -> None:
            state.cancel_activity(expected_action_id=running_action_id)
            render_shell(page, state, route)

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
                            ft.TextButton(
                                "Cancel",
                                key="activity.cancel",
                                icon=ft.Icons.CANCEL_OUTLINED,
                                on_click=cancel_running_activity,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.ProgressBar(
                        value=(
                            state.current_activity.completed_units / state.current_activity.total_units
                            if state.current_activity.total_units
                            else None
                        ),
                        color=theme.CYAN,
                        bgcolor=theme.SURFACE_2,
                    ),
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
    context_help = page_help_panel(
        canonical_route,
        title,
        on_open_help=lambda _event: navigate_to(page, state, "/help"),
    )
    content_container = glass_panel(
        ft.Column([context_help, page_content], expand=True, spacing=theme.SPACE_3, scroll=ft.ScrollMode.AUTO),
        key="shell.content",
        label=f"{title} content",
        expand=True,
        padding=theme.SPACE_3 if narrow else theme.SPACE_5,
    )
    body = ft.Column(
        [
            header,
            palette_results,
            progress_strip,
            content_container,
            _safety_rail(state, data_report),
        ],
        expand=True,
        spacing=theme.SPACE_2,
    )
    shell_row = ft.Row([dock, body], expand=True, spacing=theme.SPACE_3, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    shell_content = ft.Container(content=shell_row, padding=theme.SPACE_4, expand=True)
    view = ft.View(route=route, controls=[backdrop(shell_content, key="shell.backdrop")], bgcolor=theme.BG, padding=0)
    layout_state = {"narrow": narrow}

    def relayout(width: float | None = None) -> bool:
        next_narrow = uses_narrow_layout(page, state, width)
        if layout_state["narrow"] == next_narrow:
            return False
        layout_state["narrow"] = next_narrow
        for label in dock_labels.values():
            label.visible = not next_narrow
        message_text.visible = not next_narrow
        content_container.padding = theme.SPACE_3 if next_narrow else theme.SPACE_5
        title_column.controls[0].size = theme.FONT_LG if next_narrow else theme.FONT_XL
        palette_field.width = 220 if next_narrow else 300
        evidence_mode.width = 160 if next_narrow else 190
        return True

    # Page content remains mounted at the same position; resize changes chrome only.
    view.data = {"relayout": relayout}
    return view


def relayout_shell(page: ft.Page, state: AppState, width: float | None = None) -> None:
    if not page.views:
        return
    layout = page.views[-1].data
    if isinstance(layout, dict) and callable(layout.get("relayout")) and layout["relayout"](width):
        page.update()



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
    dispose_workspace = getattr(page, "_valuation_workspace_dispose", None)
    if callable(dispose_workspace):
        page._valuation_workspace_dispose = None
        dispose_workspace()
        page.update()
    view = build_shell(page, state, route)
    page.views[:] = [view]
    page.update()
