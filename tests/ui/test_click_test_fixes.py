from __future__ import annotations

import asyncio
from time import perf_counter
from types import SimpleNamespace

import flet as ft
import msgpack
import pandas as pd
import pytest
from flet.messaging.protocol import configure_encode_object_for_msgpack

from etf_cockpit.app.components.shell.overlay import Overlay
from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.components.shell.search import build_search
from etf_cockpit.app.pages import backtests, comparison, dashboard, decision_journal, forecast_lab, help_glossary, settings, training_centre, what_changed
from etf_cockpit.app.pages.onboarding import onboarding_page
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS, build_shell, navigate_to
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.ui_views.home import data_health_label, evidence_tag
from etf_cockpit.application.ui_facade import build_data_health
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.decision_journal import DecisionJournal


_PROTOCOL_ENCODER = configure_encode_object_for_msgpack(ft.Control)


def _walk(control):
    if isinstance(control, PageView):
        control = control.body
    if not isinstance(control, ft.Control):
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(
        str(value)
        for item in _walk(control)
        if (value := getattr(item, "value", None)) is not None
    )


def _encode(control) -> bytes:
    return msgpack.packb(control, default=_PROTOCOL_ENCODER, use_bin_type=True)


class _Page:
    def __init__(self, route: str = "/") -> None:
        self.route = route
        self.width = 1280
        self.height = 900
        self.views = []

    def update(self) -> None:
        pass

    def go(self, route: str) -> None:
        self.route = route


class _NavigablePage(_Page):
    def __init__(self, route: str = "/") -> None:
        super().__init__(route)
        self.last_scroll_key = None

    async def scroll_to(self, *, scroll_key: str, duration: int = 0) -> None:
        self.last_scroll_key = scroll_key

    def run_task(self, callback) -> None:
        asyncio.run(callback())


@pytest.fixture(scope="module")
def _snapshot():
    return build_snapshot()


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


@pytest.mark.parametrize("section", ["Risk & forecasts", "History"])
def test_instrument_section_switches_in_place(_snapshot, section: str) -> None:
    """Owner click test 2: full rebuilds took 8-75 s per segment click; sections now toggle in place."""
    state = _state(_snapshot)
    route = f"/instrument/{state.selected_etf}"
    page = _Page(route)
    page.views = [build_shell(page, state, route)]
    initial = page.views[-1]
    segment = next(
        control
        for control in _walk(initial)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "Segment"
        and control.data.get("value") == section
    )

    segment.on_click(None)

    assert page.views[-1] is initial
    assert state.selected_instrument_section == section
    assert page.views[-1].route == route
    assert _encode(page.views[-1])


_SERIALIZATION_CASES = (
    ("/portfolio-optimiser", ()),
    ("/stress-lab", ()),
    ("/risk", ("Tail & regimes",)),
    ("/operations", ("Overview",)),
    ("/operations", ("Paper ledger",)),
    ("/jobs", ()),
    ("/settings", ("Privacy",)),
    ("/import-export", ("Import",)),
    ("/import-export", ("Reconcile",)),
    ("/import-export", ("Backup",)),
    ("/data-health", ("All",)),
    ("/filings", ("SEC", "ESEF", "National OAM", "Manual")),
    ("/etf-disclosures", ("Documents", "Reports", "Holdings", "SFDR")),
    ("/news-context", ("Contradictions",)),
    ("/screener", ()),
)


@pytest.mark.parametrize(("route", "segments"), _SERIALIZATION_CASES)
def test_click_test_page_control_tree_encodes_with_flet_protocol(_snapshot, route: str, segments: tuple[str, ...]) -> None:
    view = PAGES[route][1](_Page(route), _state(_snapshot))
    assert isinstance(view, PageView)
    assert "could not be rendered safely" not in _text(view).casefold()
    assert _encode(view.body)
    for segment in segments:
        group = next(group for group in view.chrome.segment_groups if segment in group.items)
        if group.on_change is not None:
            group.on_change(segment)
        assert _encode(view.body)


def test_training_tabs_and_first_run_setup_render_content(monkeypatch, _snapshot) -> None:
    empty_evidence = {
        key: ()
        for key in (
            "training.run",
            "training.model",
            "training.metric",
            "validation.report",
            "validation.trial",
            "validation.researcher_decision",
            "validation.promotion_result",
        )
    }
    monkeypatch.setattr(training_centre, "load_training_evidence", lambda _root: empty_evidence)
    monkeypatch.setattr(training_centre, "load_optimisation_evidence", lambda _root: {"trials": (), "summaries": ()})
    monkeypatch.setattr(training_centre.DurableJobScheduler, "list_workflows", lambda _self, limit=100: ())
    training = training_centre.training_centre_page(_Page("/training-centre"), SimpleNamespace(snapshot=_snapshot))
    expected = {"Runs": "Run list", "Validation": "Validation Designer", "Optimisation": "Bounded optimisation"}
    for section, title in expected.items():
        training.chrome.segment_groups[0].on_change(section)
        assert title in _text(training.body)
    setup = onboarding_page(None, _state(_snapshot))
    assert isinstance(setup, PageView)
    assert all(title in _text(setup.body) for title in ("Data source", "Watchlist", "Review & save"))


def test_audit_notes_navigation_reaches_system_map_and_release_readiness(monkeypatch, _snapshot) -> None:
    from etf_cockpit.app import router

    monkeypatch.setattr(router, "log_event", lambda **_kwargs: None)
    state = _state(_snapshot)
    page = _Page("/chatgpt")
    page.views = [build_shell(page, state, "/chatgpt")]
    for route, title in (("/system-map", "System Map"), ("/release-readiness", "Release Readiness")):
        started = perf_counter()
        navigate_to(page, state, route)
        elapsed = perf_counter() - started
        assert page.views[-1].route == route
        assert title in _text(page.views[-1])
        assert elapsed < 3


def test_search_enter_opens_best_instrument_or_page_match(_snapshot) -> None:
    state = _state(_snapshot)
    state.last_message = "No matching workspace"
    routes: list[str] = []
    page = _Page()
    search = build_search(
        page,
        state,
        PAGES,
        WORKSPACE_GROUPS,
        navigate=routes.append,
        overlay=Overlay(lambda: None),
        anchor_left=lambda: 0,
        anchor_top=0,
        compact=False,
    )
    search.field.value = "VWCE"
    search.field.on_submit(SimpleNamespace(control=search.field))
    assert routes[-1] == "/instrument/VWCE"
    assert state.last_message == ""
    search.field.value = "System Map"
    search.field.on_submit(SimpleNamespace(control=search.field))
    assert routes[-1] == "/system-map"


def test_home_uses_detail_score_rows_and_data_health_sources(_snapshot) -> None:
    from etf_cockpit.app.pages.dashboard import _digest_parts
    from etf_cockpit.app.pages.signals import _scores

    state = _state(_snapshot)
    home, _scores_used = dashboard._home_view(state)
    detail_scores = _scores(_snapshot)
    assert home.instrument_total == len(detail_scores)
    assert {row.instrument_id for row in home.scores} == {str(score.display_id) for score in detail_scores}
    assert len(home.scores) == len({row.instrument_id for row in home.scores})
    assert len(detail_scores) == len({str(score.display_id) for score in detail_scores})
    details_by_id = {str(score.display_id): score for score in detail_scores}
    blocked_ids = set(_snapshot.data_report.blocked_etfs or ())
    for row in home.scores:
        score = details_by_id[row.instrument_id]
        assert row.score == score.final_score_10
        assert row.evidence_text == evidence_tag(
            score.final_label,
            score.final_action,
            row.instrument_id in blocked_ids,
        )[0]
    _as_of, _records, report = _digest_parts(state, detail_scores)
    if report is not None:
        for change in report.changes:
            row = next((item for item in home.scores if item.instrument_id == change.instrument_id), None)
            if row is not None and change.previous_rank is not None and change.current_rank is not None:
                assert row.rank_delta == int(round(change.previous_rank - change.current_rank))
    comparison_view = comparison.comparison_page(_Page("/comparison"), state)
    comparison_dropdowns = [control for control in _walk(comparison_view.body) if isinstance(control, ft.PopupMenuButton)]
    assert len(comparison_dropdowns) == 2
    for dropdown in comparison_dropdowns:
        identities = [
            str(getattr(getattr(option, "content", None), "value", "")).split(" ", 1)[0]
            for option in dropdown.items
        ]
        assert identities
        assert len(identities) == len(set(identities))
    health = build_data_health(
        _snapshot.config,
        ROOT,
        as_of_date=_snapshot.data_report.as_of_date,
    )
    assert home.data_status == data_health_label(health.rows)


def test_backtests_use_readable_strategy_names_and_percent_rates() -> None:
    report = SimpleNamespace(
        results=pd.DataFrame([{"strategy_name": "signal_strategy", "cagr": 0.04, "volatility": 0.1, "max_drawdown": -0.12, "sharpe": 0.9}]),
        quality_label="medium",
        ai_added_value=None,
        equity_curves=pd.DataFrame(),
        operational_evidence=pd.DataFrame(),
        trade_log=pd.DataFrame(),
    )
    view = backtests.backtests_page(None, SimpleNamespace(snapshot=SimpleNamespace(backtest=report, config=None)))
    table = next(
        control
        for control in _walk(view.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "DataTable"
        and "strategy_name" in control.data.get("columns", ())
    )
    table_text = _text(table)
    assert "Signal Strategy" in table_text
    assert "4.00%" in table_text
    assert "10.00%" in table_text
    assert "-12.00%" in table_text


def test_settings_preview_resolves_previous_and_proposed_values(_snapshot) -> None:
    view = settings.settings_page(None, _state(_snapshot))
    controls = list(_walk(view.body))
    horizon_segments = next(control for control in controls if getattr(control, "key", None) == "settings.horizon")
    selected = next(
        control
        for control in _walk(horizon_segments)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "Segment"
        and not control.data.get("selected")
    )
    selected.on_click(None)
    preview = next(
        control
        for control in _walk(view.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "Button"
        and control.data.get("text") == "Preview changes"
    )
    preview.on_click(None)
    table = next(
        control
        for control in _walk(view.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "DataTable"
        and control.data.get("columns") == ["setting", "previous", "proposed"]
    )
    row = next(
        control
        for control in _walk(table)
        if (getattr(control, "data", None) or {}).get("kit") == "DataTableRow"
        and "Horizon" in _text(control)
    )
    values = [value for value in _text(row).splitlines() if value.strip()]
    assert len(values) >= 3
    assert values[1] != "—"
    assert values[2] != "—"
    assert values[1] != values[2]


def test_decision_journal_keeps_the_typed_title(monkeypatch, tmp_path, _snapshot) -> None:
    monkeypatch.setattr(decision_journal, "DATA_DIR", tmp_path)
    monkeypatch.setattr(DecisionJournal, "list_entries", lambda *_args, **_kwargs: ())
    view = decision_journal.decision_journal_page(None, _state(_snapshot))
    title = next(control for control in _walk(view.body) if getattr(control, "key", None) == "decision-journal.title")
    title.value = "UAT test"
    save = next(
        control
        for control in _walk(view.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "Button"
        and control.data.get("text") == "Save note"
    )
    save.on_click(None)
    assert "UAT test" in _text(view.body)


def test_what_changed_detail_uses_places_gained_sign_convention() -> None:
    change = SimpleNamespace(
        instrument_id="DB1",
        score_delta=0.7,
        score_rank_delta=-20,
        current_action="Review",
        dimension_statuses={},
        upstream_changes={},
    )
    controls = what_changed._below_the_fold(SimpleNamespace(empty_reason="", extras={}), SimpleNamespace(changes=[change]), None)
    table = next(
        control
        for root in controls
        for control in _walk(root)
        if (getattr(control, "data", None) or {}).get("kit") == "DataTable"
    )
    row = next(control for control in _walk(table) if (getattr(control, "data", None) or {}).get("kit") == "DataTableRow")
    assert "+20" in _text(row)


def test_forecast_lab_governance_action_scrolls_to_section_and_reports_feedback(_snapshot, monkeypatch) -> None:
    import flet as ft

    scrolled: list[tuple[object, object]] = []

    async def fake_scroll_to(self, *, scroll_key=None, **_kwargs):
        scrolled.append((self, scroll_key))

    # The Flet page itself does not scroll in this app: the page grid's own column must be scrolled,
    # and Flet only scrolls to a control whose key is a ScrollKey (a plain string key is ignored).
    monkeypatch.setattr(ft.Column, "scroll_to", fake_scroll_to)
    page = _NavigablePage("/forecasts")
    view = forecast_lab.forecast_lab_page(page, _state(_snapshot))
    button = next(control for control in _walk(view.body) if getattr(control, "key", None) == "forecast-lab.open-governance")

    button.on_click(None)

    assert len(scrolled) == 1
    column, key = scrolled[0]
    assert isinstance(column, ft.Column) and column.scroll is not None
    assert isinstance(key, ft.ScrollKey)
    anchors = [c for c in _walk(column) if isinstance(getattr(c, "key", None), ft.ScrollKey)]
    assert [a.key.value for a in anchors] == [key.value]
    assert "Governance section opened below." in _text(view.body)


def test_glossary_term_selection_updates_the_selected_definition(_snapshot) -> None:
    view = help_glossary.help_glossary_page(_Page("/help"), _state(_snapshot))
    before = _text(view.body).count("Evidence quality")
    item = next(control for control in _walk(view.body) if getattr(control, "key", None) == "help.glossary-term.evidence-quality")

    item.on_click(None)

    assert _text(view.body).count("Evidence quality") > before
