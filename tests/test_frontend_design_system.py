from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import theme
from etf_cockpit.app import router
from etf_cockpit.app.components.shell.page_menu import build_page_menu
from etf_cockpit.app.components.states import STATE_NAMES, state_panel
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS, build_shell, uses_narrow_layout, workspace_for_route
from etf_cockpit.app.state import AppState
from etf_cockpit.core.ui_acceptance import build_main_ui_action_inventory, ui_command_contracts
from etf_cockpit.application.snapshot_builder import build_snapshot


_SNAPSHOT_TEMPLATE = None


@pytest.fixture(scope="module", autouse=True)
def _snapshot_template():
    global _SNAPSHOT_TEMPLATE
    _SNAPSHOT_TEMPLATE = build_snapshot()
    yield
    _SNAPSHOT_TEMPLATE = None


def _snapshot_copy():
    assert _SNAPSHOT_TEMPLATE is not None
    snapshot = _SNAPSHOT_TEMPLATE
    return replace(
        snapshot,
        config=copy.deepcopy(snapshot.config),
        prices=snapshot.prices.copy(deep=True),
        holdings=snapshot.holdings.copy(deep=True),
        features=snapshot.features.copy(deep=True),
        latest_features=snapshot.latest_features.copy(deep=True),
        data_report=replace(
            snapshot.data_report,
            issues=copy.deepcopy(snapshot.data_report.issues),
            dataset_metadata=copy.deepcopy(snapshot.data_report.dataset_metadata),
        ),
        signals=[
            replace(
                signal,
                blocked_by=copy.deepcopy(signal.blocked_by),
                warnings=copy.deepcopy(signal.warnings),
                supporting_metrics=copy.deepcopy(signal.supporting_metrics),
                model_versions_used=copy.deepcopy(signal.model_versions_used),
                authority_decision=copy.deepcopy(signal.authority_decision),
                canonical_score=copy.deepcopy(signal.canonical_score),
            )
            for signal in snapshot.signals
        ],
        forecasts=snapshot.forecasts.copy(deep=True),
        model_status=copy.deepcopy(snapshot.model_status),
        model_inventory=copy.deepcopy(snapshot.model_inventory),
        candidate_price_binding=copy.deepcopy(snapshot.candidate_price_binding),
        etf_economics_records=copy.deepcopy(snapshot.etf_economics_records),
        etf_fund_total_return=copy.deepcopy(snapshot.etf_fund_total_return),
        etf_benchmark_total_return=copy.deepcopy(snapshot.etf_benchmark_total_return),
        etf_closure_policy=copy.deepcopy(snapshot.etf_closure_policy),
        benchmark_reference_registry=copy.copy(snapshot.benchmark_reference_registry),
        benchmark_reference_instrument=copy.deepcopy(snapshot.benchmark_reference_instrument),
        benchmark_reference_portfolio_ids=copy.deepcopy(snapshot.benchmark_reference_portfolio_ids),
        vwce_anchor_evidence=copy.copy(snapshot.vwce_anchor_evidence),
        vwce_conversion_evidence=copy.deepcopy(snapshot.vwce_conversion_evidence),
        backtest=replace(
            snapshot.backtest,
            results=snapshot.backtest.results.copy(deep=True),
            equity_curves=snapshot.backtest.equity_curves.copy(deep=True),
            trade_log=snapshot.backtest.trade_log.copy(deep=True),
            signal_log=snapshot.backtest.signal_log.copy(deep=True),
            quality_notes=(
                None
                if snapshot.backtest.quality_notes is None
                else copy.deepcopy(snapshot.backtest.quality_notes)
            ),
            metadata=copy.deepcopy(snapshot.backtest.metadata),
            quality_momentum_evidence=snapshot.backtest.quality_momentum_evidence.copy(deep=True),
        ),
    )


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def test_state_panel_names_each_state_without_relying_on_colour() -> None:
    for state in STATE_NAMES:
        rendered = state_panel(state, "Test state", "A readable state message")
        text = " ".join(str(control.value) for control in _walk(rendered) if isinstance(control, ft.Text))
        assert f"State: {state}" in text
        assert "A readable state message" in text


def test_workspace_groups_cover_each_registered_route_once() -> None:
    grouped_routes = [route for _workspace, routes in WORKSPACE_GROUPS for route in routes]
    assert set(grouped_routes) == set(PAGES)
    assert len(grouped_routes) == len(set(grouped_routes))
    assert tuple(workspace for workspace, _routes in WORKSPACE_GROUPS) == (
        "Home",
        "Universe",
        "Research",
        "Portfolio",
        "Compare",
        "Lab",
        "Map",
        "Changes",
        "Help",
    )
    assert workspace_for_route("/instrument/VWCE") == "Research"


def test_evidence_mode_is_presentation_only_and_validated() -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    for mode in theme.EVIDENCE_MODES:
        assert state.set_evidence_mode(mode) == mode
        assert state.evidence_mode == mode
        assert theme.EVIDENCE_MODE_LABELS[mode] in state.last_message
    with pytest.raises(ValueError, match="Unsupported evidence mode"):
        state.set_evidence_mode("execute")


@pytest.mark.parametrize("width", [640, 759, 760, 900, 1100, 1200])
def test_shell_has_grouped_navigation_and_evidence_mode_at_responsive_widths(width: int) -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=width, route="/")

    view = build_shell(page, state, "/")
    controls = list(_walk(view))
    # Evidence mode moved from the header into the Analysis depth dialog (spec 5.5), opened from the footer rail.
    assert any(getattr(control, "key", None) == "shell.as-of.analysis-depth" for control in controls)
    keys = {str(control.key) for control in controls if getattr(control, "key", None)}
    dock_items = [control for control in controls if str(getattr(control, "key", "")).startswith("nav.workspace.")]

    assert "shell.command-palette" in keys
    assert len(dock_items) == 9
    assert all(item.tooltip.startswith(f"{workspace} — ") for item, (workspace, _routes) in zip(dock_items, WORKSPACE_GROUPS))
    assert sum(item.data == "active" for item in dock_items) == 1
    dock_label = next(control for control in controls if getattr(control, "key", None) == "shell.dock.label.Home")
    assert dock_label.visible is (width >= 1100)
    assert uses_narrow_layout(page, state) is (width < 1100)


def test_shell_command_palette_exposes_search_and_enter_instructions() -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/")

    view = build_shell(page, state, "/")
    text = " ".join(str(control.value) for control in _walk(view) if isinstance(control, ft.Text))
    fields = [control for control in _walk(view) if isinstance(control, ft.TextField)]

    assert any(field.hint_text == "Search or jump to…" for field in fields)
    palette = next(field for field in fields if field.key == "shell.command-palette")
    assert palette.on_change.__name__ == "render_palette_results"
    assert palette.on_submit.__name__ == "submit_palette"
    assert "Home" in text


def test_shell_command_palette_filters_and_navigates(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/", update=lambda: None)
    selected: list[str] = []
    monkeypatch.setattr(router, "navigate_to", lambda _page, _state, route: selected.append(route))

    view = build_shell(page, state, "/")
    palette = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command-palette")
    palette.value = "comparison"
    palette.on_change(SimpleNamespace(control=palette))

    result = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command.comparison")
    result.on_click(SimpleNamespace(control=result))
    assert selected == ["/comparison"]

    palette.value = "data"
    palette.on_change(SimpleNamespace(control=palette))
    later_result = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command.data-health")
    later_result.on_click(SimpleNamespace(control=later_result))
    assert selected == ["/comparison", "/data-health"]

    palette.value = "backtests"
    palette.on_submit(SimpleNamespace(control=palette))
    assert selected == ["/comparison", "/data-health", "/backtests"]

    palette.value = "no such route"
    palette.on_change(SimpleNamespace(control=palette))
    palette.on_submit(SimpleNamespace(control=palette))
    assert any(
        isinstance(control, ft.Text) and control.value == "No matching workspace"
        for control in _walk(view)
    )
    assert selected == ["/comparison", "/data-health", "/backtests"]

    palette.value = ""
    palette.on_submit(SimpleNamespace(control=palette))
    assert any(
        isinstance(control, ft.Text) and control.value == "Enter a page or workspace to search"
        for control in _walk(view)
    )
    assert selected == ["/comparison", "/data-health", "/backtests"]


def test_palette_control_dispatch_preserves_terminal_result_and_prevents_reinvocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/", update=lambda: None)
    selected: list[str] = []
    monkeypatch.setattr(router, "navigate_to", lambda _page, _state, route: selected.append(route))

    view = build_shell(page, state, "/")
    palette = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command-palette")
    palette.value = "comparison"
    palette.on_change(SimpleNamespace(control=palette))
    result = next(control for control in _walk(view) if getattr(control, "key", None) == "shell.command.comparison")
    contract = next(
        item
        for item in ui_command_contracts(build_main_ui_action_inventory())
        if item.action_id == "command:palette:comparison"
    )
    assert result.on_click.__name__ == "select_palette_command"
    assert contract.callback == "navigate_palette_command"
    event = SimpleNamespace(control=result)
    completed = result.on_click(event)
    replayed = result.on_click(event)
    assert selected == ["/comparison"]
    assert completed.status == replayed.status == "completed"
    assert completed.replayed is False and replayed.replayed is True
    assert (replayed.signal, replayed.visible_message) == (completed.signal, completed.visible_message)

    attempts: list[str] = []

    def fail_navigation(_page: object, _state: object, route: str) -> None:
        attempts.append(route)
        raise RuntimeError("controlled palette failure")

    monkeypatch.setattr(router, "navigate_to", fail_navigation)
    failed_state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    failed_view = build_shell(page, failed_state, "/")
    failed_palette = next(
        control for control in _walk(failed_view) if getattr(control, "key", None) == "shell.command-palette"
    )
    failed_palette.value = "comparison"
    failed_palette.on_change(SimpleNamespace(control=failed_palette))
    failed_result = next(
        control for control in _walk(failed_view) if getattr(control, "key", None) == "shell.command.comparison"
    )
    failed_event = SimpleNamespace(control=failed_result)
    failed = failed_result.on_click(failed_event)
    first_failure = failed_state.last_message
    failed_replay = failed_result.on_click(failed_event)
    assert attempts == ["/comparison"]
    assert failed.status == failed_replay.status == "failed"
    assert failed.replayed is False and failed_replay.replayed is True
    assert (failed_replay.signal, failed_replay.visible_message) == (failed.signal, failed.visible_message)
    assert failed_state.last_message == first_failure
    assert contract.controlled_error_signal in first_failure
    assert "Action failed safely: RuntimeError: controlled palette failure" in first_failure
    visible = " ".join(
        str(control.value)
        for control in _walk(failed_view)
        if isinstance(control, ft.Text)
    )
    assert first_failure in visible

def test_unknown_and_failed_routes_render_a_visible_controlled_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1200, route="/missing")
    monkeypatch.setattr(router, "log_event", lambda **_kwargs: None)

    unknown = build_shell(page, state, "/missing")
    unknown_controls = list(_walk(unknown))
    assert any(getattr(control, "key", None) == "router.route-error" for control in unknown_controls)
    assert any(isinstance(control, ft.Text) and "not registered" in str(control.value) for control in unknown_controls)

    def broken_page(_page: object, _state: object) -> ft.Control:
        raise RuntimeError("private detail")

    monkeypatch.setitem(PAGES, "/broken", ("Broken", broken_page))
    failed = build_shell(page, state, "/broken")
    failed_controls = list(_walk(failed))
    assert any(getattr(control, "key", None) == "router.route-error" for control in failed_controls)
    visible = " ".join(str(control.value) for control in failed_controls if isinstance(control, ft.Text))
    assert "could not be rendered safely (RuntimeError)" in visible
    assert "private detail" not in visible


def test_dashboard_summary_cards_are_inherently_responsive():
    from etf_cockpit.app.pages.dashboard import _summary_cards

    state = SimpleNamespace(snapshot=SimpleNamespace(data_report=SimpleNamespace(status="Clean", as_of_date="2026-07-01")))
    cards = _summary_cards(state, None, 1, 2, 3, 0, narrow=False)
    assert isinstance(cards, ft.ResponsiveRow)
    assert len(cards.controls) == 6
    assert all(card.col == {"xs": 12, "sm": 6, "md": 4, "xl": 2} for card in cards.controls)


def test_mobile_dock_is_icons_only_and_subnavigation_stays_bounded(monkeypatch):
    monkeypatch.setitem(router.PAGES, "/", ("Home", lambda *_: ft.Text("Page")))
    state = SimpleNamespace(snapshot=SimpleNamespace(config=SimpleNamespace(ui=SimpleNamespace(window_width=390)),
        data_report=SimpleNamespace(as_of_date="2026-07-01")), evidence_mode="simple", current_activity=None, last_message="Ready")
    view = build_shell(SimpleNamespace(width=390), state, "/")
    controls = list(_walk(view))
    dock = next(control for control in controls if getattr(control, "key", None) == "shell.dock")
    dock_items = [control for control in _walk(dock) if str(getattr(control, "key", "")).startswith("nav.workspace.")]
    label = next(control for control in controls if getattr(control, "key", None) == "shell.dock.label.Home")
    assert len(dock_items) == 9
    assert label.visible is False
    assert dock.width == 64
    # The sub-page chips moved into the page menu (spec 5.3); the Home workspace still lists both pages.
    menu = build_page_menu(dict(WORKSPACE_GROUPS)["Home"], "/", PAGES, navigate_to=lambda _route: None)
    assert {control.key for control in _walk(menu.panel) if getattr(control, "key", None)} >= {"navigation.home", "navigation.onboarding"}
