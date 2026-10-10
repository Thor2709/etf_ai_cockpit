from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from itertools import count
import threading

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel
from etf_cockpit.app.components.depth_selector import depth_label
from etf_cockpit.app.components.kit import Note, glass_panel
from etf_cockpit.app.components.kit._base import txt
from etf_cockpit.app.components.shell._glass import glass
from etf_cockpit.app.components.shell.depth_dialog import open_depth_dialog
from etf_cockpit.app.components.shell.dock import DOCK_WIDTH, DOCK_WIDTH_NARROW, build_dock
from etf_cockpit.app.components.shell.footer import Footer, build_footer
from etf_cockpit.app.components.shell.loading import skeleton_body
from etf_cockpit.app.components.shell.overlay import Overlay, Toast
from etf_cockpit.app.components.shell.page_menu import PageMenu, build_page_menu, menu_routes
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.components.shell.search import Search, build_search
from etf_cockpit.app.components.shell.status import footer_values, material_change_count
from etf_cockpit.app.components.shell.topbar import build_topbar
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
from etf_cockpit.app.pages.strategy_builder import strategy_builder_page
from etf_cockpit.app.pages.trust_evidence import (
    etf_disclosures_page,
    evidence_ledger_page,
    filings_page,
    news_context_page,
    provider_status_page,
)
from etf_cockpit.app.pages.sectors import sectors_page
from etf_cockpit.app.pages.release_readiness import release_readiness_page
from etf_cockpit.app.pages.programme_map import programme_map_page
from etf_cockpit.app.state import AppState
from etf_cockpit.core.navigation import ROUTE_TITLES, WORKSPACE_GROUPS, WORKSPACE_ICONS
from etf_cockpit.core.session_log import log_event

_PAGE_RENDERERS = {
    "/": dashboard_page,
    "/portfolio": portfolio_page,
    "/portfolio-optimiser": portfolio_optimiser_page,
    "/signals": signals_page,
    "/strategy-builder": strategy_builder_page,
    "/screener": screener_page,
    "/comparison": comparison_page,
    "/stock-research": stock_research_page,
    "/risk": risk_page,
    "/stress-lab": stress_lab_page,
    "/etf": instrument_detail_page,
    "/backtests": backtests_page,
    "/chatgpt": chatgpt_audit_page,
    "/providers": provider_status_page,
    "/evidence": evidence_ledger_page,
    "/filings": filings_page,
    "/etf-disclosures": etf_disclosures_page,
    "/news-context": news_context_page,
    "/data-models": data_models_page,
    "/forecasts": forecast_lab_page,
    "/training-centre": training_centre_page,
    "/feature-catalogue": feature_catalogue_page,
    "/catalogue": catalogue_page,
    "/macro": macro_factors_page,
    "/settings": settings_page,
    "/diagnostics": diagnostics_page,
    "/errors": errors_recovery_page,
    "/data-health": data_health_page,
    "/universe": universe_manager_page,
    "/onboarding": onboarding_page,
    "/what-changed": what_changed_page,
    "/instrument": instrument_detail_page,
    "/import-export": import_export_page,
    "/system-map": system_map_page,
    "/help": help_glossary_page,
    "/decision-journal": decision_journal_page,
    "/forward-evidence": forward_evidence_page,
    "/jobs": jobs_page,
    "/operations": operations_page,
    "/release-readiness": release_readiness_page,
    "/roadmap": programme_map_page,
    "/sectors": sectors_page,
}
if set(_PAGE_RENDERERS) != {route for route, _title in ROUTE_TITLES}:
    raise RuntimeError("router renderers and core.navigation.ROUTE_TITLES disagree")
PAGES = {route: (title, _PAGE_RENDERERS[route]) for route, title in ROUTE_TITLES}

# Pages whose builder may touch the lazy backtest (a recalculation after a data change takes tens of seconds)
# or other heavy evidence: they build off the event thread behind the skeleton instead of a white screen.
_DEFERRED_RENDER_ROUTES = {
    "/backtests",
    "/chatgpt",
    "/comparison",
    "/diagnostics",
    "/evidence",
    "/etf",
    "/forward-evidence",
    "/instrument",
    "/settings",
    "/signals",
    "/stock-research",
    "/what-changed",
}


NARROW_LAYOUT_BREAKPOINT = 1100


def instrument_detail_route(instrument_id: str) -> str:
    """Return the canonical inspect route for a configured instrument ID."""

    value = str(instrument_id or "").strip()
    return f"/instrument/{value}" if value else "/instrument"


def _route_parts(route: str) -> tuple[str, str | None]:
    """Return ``(registered page route, instrument id)``; query and hash never reach either part."""

    value = str(route or "/").split("?", 1)[0].split("#", 1)[0] or "/"
    if value.startswith("/instrument/"):
        return "/instrument", value.split("/", 2)[-1].strip() or None
    return value, None


def _page_route(route: str) -> str:
    """Return the registered route while preserving query/hash targets for pages."""

    return _route_parts(route)[0]


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


def _shell_controls(state: AppState) -> object | None:
    """Saved SettingsBundle controls for the shell metadata row, or None when unavailable."""

    root = getattr(state, "settings_root", None)
    if root is None:
        return None
    try:
        from etf_cockpit.application.settings import SettingsError, load_settings_bundle

        return load_settings_bundle(root).controls
    except (SettingsError, OSError, ValueError):
        return None


def navigate_to(page: ft.Page, state: AppState, route: str, *, candidate_score: object | None = None) -> None:
    if str(route).startswith("/instrument/"):
        selected = _route_parts(route)[1]
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


MIN_BODY_HEIGHT = 742  # row A 420 + gap + row B 300 (spec 1): below this the body scrolls inside the main area
MIN_BODY_HEIGHT_NARROW = 1400  # stacked cards in one column (spec 1, width < 1100)
_CHROME_HEIGHT = 24 + 80 + 22 + 22 + 48 + 24  # margins, top bar, two gaps, footer


def _body_scrolls(height: float, narrow: bool) -> bool:
    """True when the area below the chrome is shorter than the body's minimum height (body scrolls inside)."""

    return height - _CHROME_HEIGHT < (MIN_BODY_HEIGHT_NARROW if narrow else MIN_BODY_HEIGHT)


def _window_size(page: ft.Page, state: AppState, width: float | None = None) -> tuple[float, float]:
    ui = state.snapshot.config.ui
    page_width = float(width or getattr(page, "width", 0) or ui.window_width)
    page_height = float(getattr(page, "height", 0) or getattr(ui, "window_height", 900))
    return page_width, page_height


def _workspace_tooltips() -> dict[str, str]:
    """Tooltip per dock item: workspace name and its page list (spec 5.1)."""
    return {
        workspace: f"{workspace} — " + ", ".join(PAGES[route][0] for route in menu_routes(routes) if route in PAGES)
        for workspace, routes in WORKSPACE_GROUPS
    }


def _profile_text(state: AppState) -> str | None:
    controls = _shell_controls(state)
    currency = getattr(controls, "output_currency", None)
    horizon = getattr(controls, "horizon", None)
    risk = getattr(controls, "risk_profile", None)
    if currency is None or horizon is None or risk is None:
        return None
    return f"{currency} · {horizon} · {str(risk).capitalize()} risk"


def _toast_is_error(message: str) -> bool:
    return message.casefold().startswith(("route failure", "error", "failed", "unavailable"))


# One page build at a time: builders share state and the (patched) page.update, and a superseded
# background build must finish before the next starts.
_BUILD_LOCK = threading.RLock()
_RENDER_LOCK = threading.RLock()
_RENDER_GENERATIONS = count(1)
SKELETON_PATIENCE_S = 0.08  # a page that builds faster than this is painted once, without a skeleton frame
_DEFERRED_UPDATE_KEY = "shell.deferred-update"
_PAGE_UPDATE_SWAP_LOCK = threading.RLock()


def _deferred_callbacks(root: object, *, consume: bool = False) -> list[tuple[ft.Control, Callable[[], object]]]:
    pending: list[tuple[ft.Control, Callable[[], object]]] = []
    seen: set[int] = set()

    def walk(control: object) -> None:
        if isinstance(control, PageView):
            walk(control.body)
            return
        if not isinstance(control, ft.Control) or id(control) in seen:
            return
        seen.add(id(control))
        data = getattr(control, "data", None)
        if isinstance(data, dict):
            callback = data.pop(_DEFERRED_UPDATE_KEY, None) if consume else data.get(_DEFERRED_UPDATE_KEY)
            if callable(callback):
                pending.append((control, callback))
        for child in getattr(control, "controls", ()) or ():
            walk(child)
        walk(getattr(control, "content", None))

    if isinstance(root, ft.View):
        for control in root.controls:
            walk(control)
    else:
        walk(root)
    return pending


def _deferred_failure(target: ft.Control, route: str, exc: Exception) -> None:
    """Log a failed section filler and replace its "Preparing…" content with a visible notice."""

    log_event(
        event_type="deferred_section_failure",
        severity="error",
        route=route,
        component="navigation",
        button_label="Section unavailable",
        operation="deferred_update",
        status="failed",
        message=f"{type(exc).__name__}: {exc}",
    )
    notice = Note(f"This section could not load: {type(exc).__name__}")
    if hasattr(target, "content"):
        target.content = notice
    elif isinstance(getattr(target, "controls", None), list):
        target.controls = [notice]


def _resolve_deferred_controls(page: ft.Page, built: object, route: str = "") -> object:
    """Fill a fresh, unmounted page tree before the router mounts it."""

    for _ in range(64):
        pending = _deferred_callbacks(built, consume=True)
        if not pending:
            return built
        replaced = False
        for target, callback in pending:
            try:
                with _BUILD_LOCK, _deferred_page_update(page):  # same lock order as build_page
                    result = callback()
            except Exception as exc:
                _deferred_failure(target, route, exc)
                continue
            if isinstance(result, PageView):
                built = result
                replaced = True
                break
        if replaced:
            continue
    _deferred_callbacks(built, consume=True)
    return built


def _schedule_deferred_updates(page: ft.Page, view: ft.View, generation: int, state: AppState, route: str) -> None:
    """Rebuild tagged sections off-thread, resolving their fillers before mounting controls."""

    if not _deferred_callbacks(view):
        return

    def refresh() -> None:
        if getattr(page, "_render_generation", generation) != generation:
            return
        if _page_route(getattr(page, "route", route)) != _page_route(route):
            return
        built = _resolve_deferred_controls(page, build_page(page, state, route), route)
        if getattr(page, "_render_generation", generation) != generation:
            return
        replacement = build_shell(page, state, route, built=built, show_toast=False)
        if _page_route(getattr(page, "route", route)) != _page_route(route):
            return
        if not _paint_if_current(page, replacement, generation):
            return
        _schedule_deferred_updates(page, replacement, generation, state, route)

    threading.Thread(target=refresh, name="deferred-page-refresh", daemon=True).start()


@contextmanager
def _deferred_page_update(page: ft.Page):
    """Legacy builders call ``page.update()`` while building; the shell mounts the view and updates once.

    Only calls made by the building thread are swallowed, so a background build never hides an update
    requested by the UI thread (a click, a resize) meanwhile.
    """
    owner = threading.get_ident()
    with _PAGE_UPDATE_SWAP_LOCK:  # held for the whole block: an interleaved swap would restore the wrong method
        original = page.__dict__.get("update")
        real_update = getattr(page, "update", None)  # embedded/test pages may have none

        def deferred(*args: object, **kwargs: object) -> object:
            if real_update is None or threading.get_ident() == owner:
                return None
            return real_update(*args, **kwargs)

        page.update = deferred  # type: ignore[method-assign]
        try:
            yield
        finally:
            if original is None:
                page.__dict__.pop("update", None)
            else:
                page.update = original  # type: ignore[method-assign]


def build_page(page: ft.Page, state: AppState, route: str) -> object:
    """Run the route page builder and return its control or PageView (a failure control when it raises)."""

    canonical_route = _page_route(route)
    builder = PAGES.get(canonical_route, (None, None))[1]
    if builder is None:
        return _route_failure_control(state, route, "The requested route is not registered.")

    if canonical_route in _DEFERRED_RENDER_ROUTES and (
        isinstance(page, ft.Page) or callable(getattr(page, "run_thread", None))
    ):
        title = PAGES[canonical_route][0]

        def render_deferred() -> object:
            try:
                with _BUILD_LOCK:
                    with _deferred_page_update(page):
                        return builder(page, state)
            except Exception as exc:
                return _route_failure_control(state, route, f"The page could not be rendered safely ({type(exc).__name__}).")

        placeholder = ft.Container(content=ft.Text("Preparing local evidence…"), expand=True)
        placeholder.data = {_DEFERRED_UPDATE_KEY: render_deferred}
        return PageView(PageChrome(title, "Preparing local evidence…"), placeholder)

    with _BUILD_LOCK:
        try:
            with _deferred_page_update(page):
                return builder(page, state)
        except Exception as exc:
            return _route_failure_control(state, route, f"The page could not be rendered safely ({type(exc).__name__}).")


def build_shell(page: ft.Page, state: AppState, route: str, *, built: object | None = None, show_toast: bool = True) -> ft.View:
    canonical_route = _page_route(route)
    page_entry = PAGES.get(canonical_route)
    title = page_entry[0] if page_entry is not None else "Route unavailable"
    window_width, window_height = _window_size(page, state)
    narrow = uses_narrow_layout(page, state)
    active_workspace = workspace_for_route(canonical_route)
    snapshot = getattr(state, "snapshot", None)
    data_report = getattr(snapshot, "data_report", None)

    if built is None:
        built = build_page(page, state, route)
    if isinstance(built, PageView):
        chrome, page_body = built.chrome, built.body
    else:  # legacy builder: plain control under the route's default title
        chrome = PageChrome(title, theme.APP_TAGLINE)
        page_body = glass_panel(
            ft.Column([built], expand=True, spacing=theme.SPACE_3, scroll=ft.ScrollMode.AUTO),
            key="shell.legacy-body",
            label=f"{title} content",
            expand=True,
            padding=theme.SPACE_3 if narrow else theme.SPACE_5,
        )

    def go(target: str) -> None:
        navigate_to(page, state, target)

    def update() -> None:
        if callable(getattr(page, "update", None)):
            page.update()

    mode = {"narrow": narrow, "width": window_width, "height": window_height}

    def margin() -> int:
        return 16 if mode["narrow"] else 24

    def left_edge() -> float:
        return margin() + (DOCK_WIDTH_NARROW if mode["narrow"] else DOCK_WIDTH) + margin()

    overlay = Overlay(update)
    toast = Toast(page, update)

    # Dock
    def select_workspace(workspace: str) -> None:
        go(dict(WORKSPACE_GROUPS)[workspace][0])

    badge_count = {"value": material_change_count(state)}
    dock = build_dock(
        [workspace for workspace, _routes in WORKSPACE_GROUPS],
        active=active_workspace,
        narrow=narrow,
        icons=WORKSPACE_ICONS,
        tooltips=_workspace_tooltips(),
        badge_count=badge_count["value"],
        on_select=select_workspace,
    )

    # Top bar
    workspace_routes = menu_routes(dict(WORKSPACE_GROUPS)[active_workspace])
    menu_state: dict[str, PageMenu] = {}

    def title_width() -> float:
        return 260 if mode["width"] < 1500 else 340

    def search_anchor() -> float:
        return left_edge() + 28 + title_width() + 16

    search = build_search(
        page,
        state,
        PAGES,
        WORKSPACE_GROUPS,
        navigate=go,
        overlay=overlay,
        anchor_left=search_anchor,
        anchor_top=margin() + 80 + 8,
        compact=mode["width"] < 1500,
    )

    def open_page_menu() -> None:
        if overlay.kind == "menu":
            overlay.hide(update=True)
            return
        menu = build_page_menu(workspace_routes, canonical_route, PAGES, navigate_to=go)
        menu_state["menu"] = menu
        overlay.show("menu", menu.panel, left_edge() + 8, margin() + 80 + 8, on_hide=lambda: menu_state.clear())

    def walk_controls(control: ft.Control):
        yield control
        for child in getattr(control, "controls", ()) or ():
            if isinstance(child, ft.Control):
                yield from walk_controls(child)
        content = getattr(control, "content", None)
        if isinstance(content, ft.Control):
            yield from walk_controls(content)

    topbar_holder: dict[str, object] = {}
    column_holder: dict[str, ft.Column] = {}
    active_segment_groups = {group.key: group for group in chrome.segment_groups}

    def wrap_group(group: SegmentGroup) -> SegmentGroup:
        def on_segment_change(value: str, key=group.key) -> PageChrome | None:
            current = active_segment_groups.get(key, group)
            updated = current.on_change(value) if current.on_change is not None else None
            if isinstance(updated, PageChrome):
                refresh_chrome(updated)
                return updated
            return None

        return SegmentGroup(group.key, group.items, group.selected, on_segment_change)

    def build_chrome_topbar(updated: PageChrome):
        return build_topbar(
            PageChrome(updated.title, updated.subtitle, [wrap_group(group) for group in updated.segment_groups]),
            has_menu=len(workspace_routes) > 1,
            on_open_menu=open_page_menu,
            search=search,
            overlay=overlay,
            badge_count=badge_count["value"],
            on_what_changed=None if canonical_route == "/what-changed" else (lambda: go("/what-changed")),
            width=lambda: mode["width"],
        )

    topbar = build_chrome_topbar(chrome)
    topbar_holder["control"] = topbar.control

    def refresh_chrome(updated: PageChrome) -> None:
        active_segment_groups.clear()
        active_segment_groups.update((group.key, group) for group in updated.segment_groups)
        replacement = build_chrome_topbar(updated)
        topbar.control = replacement.control
        topbar.title_left = replacement.title_left
        topbar.set_width = replacement.set_width
        topbar_holder["control"] = topbar.control
        if column_holder:
            column_holder["column"].controls[0] = topbar.control
            update()

    render_generation = getattr(page, "_render_generation", None)

    def update_chrome_later(updated: PageChrome) -> None:
        if render_generation is not None and getattr(page, "_render_generation", render_generation) != render_generation:
            return
        refresh_chrome(updated)

    try:
        page._shell_chrome_update = update_chrome_later
    except Exception:
        pass

    def refresh_page() -> None:
        current_route = str(getattr(page, "route", None) or route)
        if _page_route(current_route) == canonical_route:
            render_shell(page, state, current_route)

    if hasattr(page, "views"):
        try:
            page._shell_refresh = refresh_page
        except Exception:
            pass

    # Footer
    def make_footer() -> Footer:
        values = footer_values(snapshot, data_report)
        return build_footer(
            values,
            depth_label=depth_label(getattr(state, "analysis_depth", None)),
            profile_text=_profile_text(state),
            on_data_health=lambda: go("/data-health"),
            on_depth=lambda: open_depth_dialog(page, state, on_changed=refresh_footer),
            on_settings=lambda: go("/settings"),
            compact=mode["width"] < 1500,
            width=mode["width"],
        )

    footer = make_footer()

    def refresh_footer() -> None:
        nonlocal footer
        footer = make_footer()
        column.controls[column.controls.index(footer_slot[0])] = footer.control
        footer_slot[0] = footer.control

    # Progress strip for a running activity (cancel stays reachable)
    progress_strip: ft.Control | None = None
    if getattr(state, "current_activity", None) is not None:
        running_action_id = state.current_activity.action_id

        def cancel_running_activity(_event: ft.ControlEvent) -> None:
            state.cancel_activity(expected_action_id=running_action_id)
            render_shell(page, state, route)

        activity = state.current_activity
        progress_strip = glass(
            ft.Row(
                [
                    ft.ProgressRing(width=16, height=16, stroke_width=2, color=theme.ACC),
                    txt(activity.label, 13.5, 650, theme.INK, trunc=True),
                    ft.Container(content=txt(activity.step, 12.5, 400, theme.INK2, trunc=True), expand=True),
                    ft.TextButton("Cancel", key="activity.cancel", icon=ft.Icons.CANCEL_OUTLINED, on_click=cancel_running_activity),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            radius=24,
            padding=ft.Padding(20, 0, 12, 0),
            height=48,
            key="shell.progress",
        )

    # Body: fills the area between top bar and footer; scrolls inside when too short or narrow
    body_holder = ft.Container(content=page_body, key="shell.content")
    body_area = ft.Column([body_holder], expand=True)

    def apply_body_mode() -> None:
        minimum = MIN_BODY_HEIGHT_NARROW if mode["narrow"] else MIN_BODY_HEIGHT
        scrolls = _body_scrolls(mode["height"], mode["narrow"])
        body_area.scroll = ft.ScrollMode.AUTO if scrolls else None
        body_holder.height = minimum if scrolls else None
        body_holder.expand = not scrolls

    apply_body_mode()

    footer_slot = [footer.control]
    column = ft.Column(
        [c for c in (topbar.control, progress_strip, body_area, footer.control) if c is not None],
        expand=True,
        spacing=22,
    )
    column_holder["column"] = column
    shell_row = ft.Row(
        [dock.control, column],
        expand=True,
        spacing=margin(),
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    shell_content = ft.Container(content=shell_row, padding=margin(), expand=True)
    background = ft.Image(src="background/bg_3200.jpg", fit=ft.BoxFit.COVER, left=-12, top=-12, right=-12, bottom=-12,
                          exclude_from_semantics=True)
    scrim = ft.Container(
        left=0, top=0, right=0, bottom=0, ignore_interactions=True,
        gradient=ft.LinearGradient(colors=[theme.rgba(6, 10, 24, 0.10), theme.rgba(6, 10, 24, 0.26)],
                                   begin=ft.Alignment(0, -1), end=ft.Alignment(0, 1)),
    )
    root = ft.Stack(
        [background, scrim, ft.Container(content=shell_content, left=0, top=0, right=0, bottom=0), overlay.layer, toast.holder],
        expand=True,
        key="shell.backdrop",
    )
    view = ft.View(route=route, controls=[root], bgcolor=theme.BG, padding=0)

    message = str(getattr(state, "last_message", "") or "")
    toast_key = getattr(state, "message_serial", message)  # serial: a repeated message is a new event
    if show_toast and message and message != "Ready" and toast_key != getattr(page, "_shell_last_toast", None):
        try:
            page._shell_last_toast = toast_key
        except Exception:
            pass
        toast.show(message, error=_toast_is_error(message), update=False)

    def relayout(width: float | None = None) -> bool:
        new_width, new_height = _window_size(page, state, width)
        new_narrow = uses_narrow_layout(page, state, width)
        before = (mode["narrow"], mode["width"] < 1500, mode["width"] < 1300, _body_scrolls(mode["height"], mode["narrow"]))
        mode.update(narrow=new_narrow, width=new_width, height=new_height)
        footer.set_width(new_width)
        after = (new_narrow, new_width < 1500, new_width < 1300, _body_scrolls(new_height, new_narrow))
        if before == after:
            return False
        dock.set_narrow(new_narrow)
        topbar.set_width(new_width)
        footer.set_compact(new_width < 1500)
        shell_content.padding = margin()
        shell_row.spacing = margin()
        apply_body_mode()
        return True

    # Page content remains mounted at the same position; resize changes chrome only.
    def on_key(event: ft.KeyboardEvent) -> bool:
        return handle_shell_key(event, go=go, overlay=overlay, search=search, menu=menu_state.get("menu"), update=update)

    view.data = {"relayout": relayout, "on_key": on_key}
    return view


def handle_shell_key(
    event: ft.KeyboardEvent,
    *,
    go: Callable[[str], None],
    overlay: Overlay,
    search: Search,
    menu: PageMenu | None,
    update: Callable[[], None],
) -> bool:
    """Keyboard path of the shell (spec 10): ``/`` search, Esc closes, Alt+1..9 workspaces, arrows in the page menu."""
    key = str(getattr(event, "key", ""))
    if key == "Escape":
        if overlay.hide(update=True):
            return True
        if getattr(search.field, "value", ""):
            search.clear()
            update()
            return True
        return False
    if getattr(event, "alt", False) and key.isdigit() and 1 <= int(key) <= len(WORKSPACE_GROUPS):
        go(WORKSPACE_GROUPS[int(key) - 1][1][0])
        return True
    if key == "/" and not search.status["focused"] and not getattr(event, "ctrl", False):
        search.focus()
        return True
    if menu is not None and overlay.kind == "menu":
        if key == "Arrow Down":
            menu.highlight(menu.state["index"] + 1)
        elif key == "Arrow Up":
            menu.highlight(menu.state["index"] - 1)
        elif key == "Enter":
            go(menu.routes[menu.state["index"]])
            return True
        else:
            return False
        update()
        return True
    return False


def shell_key_event(page: ft.Page, event: ft.KeyboardEvent) -> bool:
    """Route a page-level key event to the mounted shell view."""
    if not page.views:
        return False
    data = page.views[-1].data
    handler = data.get("on_key") if isinstance(data, dict) else None
    return bool(callable(handler) and handler(event))


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


def _dispose_workspace(page: ft.Page) -> None:
    dispose_workspace = getattr(page, "_valuation_workspace_dispose", None)
    if callable(dispose_workspace):
        page._valuation_workspace_dispose = None
        dispose_workspace()
        page.update()


def _claim_render(page: ft.Page) -> int:
    """Newest render wins: an older background build that finishes later must not repaint."""

    with _RENDER_LOCK:
        generation = next(_RENDER_GENERATIONS)
        try:
            page._render_generation = generation
        except Exception:
            pass
        return generation


def _paint_if_current(page: ft.Page, view: ft.View, generation: int) -> bool:
    with _RENDER_LOCK:
        if getattr(page, "_render_generation", generation) != generation:
            return False
        page.views[:] = [view]
        page.update()
        return True


def render_shell(page: ft.Page, state: AppState, route: str) -> None:
    generation = _claim_render(page)
    _dispose_workspace(page)
    view = build_shell(page, state, route)
    if not _paint_if_current(page, view, generation):
        return
    _schedule_deferred_updates(page, view, generation, state, route)


def render_route_change(
    page: ft.Page,
    state: AppState,
    route: str,
    *,
    background: bool | None = None,
    patience_s: float = SKELETON_PATIENCE_S,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Render a navigation without blocking the event thread on a slow page.

    The page builds on a worker thread. If it finishes within ``patience_s`` the finished view is painted
    once; otherwise the shell is painted at once with a skeleton body and the finished view replaces it when
    the build completes. A newer navigation or render supersedes an unfinished one. ``background`` defaults
    to real Flet pages; plain test/embedded pages render synchronously exactly like :func:`render_shell`.
    """

    if background is None:
        background = isinstance(page, ft.Page)
    if not background:
        render_shell(page, state, route)
        if on_done is not None:
            on_done()
        return
    generation = _claim_render(page)
    _dispose_workspace(page)
    done = threading.Event()
    gate = threading.Lock()
    skeleton_shown = {"value": False}
    result: dict[str, object] = {}

    def paint_final() -> None:
        if getattr(page, "_render_generation", generation) != generation:
            return  # superseded by a newer render
        view = build_shell(page, state, route, built=result["built"])
        if not _paint_if_current(page, view, generation):
            return
        _schedule_deferred_updates(page, view, generation, state, route)
        if on_done is not None:
            on_done()

    def work() -> None:
        try:
            result["built"] = build_page(page, state, route)
        finally:
            with gate:
                done.set()
                late = skeleton_shown["value"]
        if late:
            paint_final()

    threading.Thread(target=work, name=f"page-build:{route}", daemon=True).start()
    if done.wait(patience_s):
        paint_final()
        return
    with gate:
        pending = not done.is_set()
        if pending:
            title = PAGES.get(_page_route(route), ("Loading", None))[0]
            skeleton = PageView(PageChrome(title, theme.APP_TAGLINE), skeleton_body(f"Loading {title}…"))
            shell = build_shell(page, state, route, built=skeleton, show_toast=False)
            skeleton_shown["value"] = _paint_if_current(page, shell, generation)
    if not pending:
        paint_final()
