"""Bug-fix batch T-UIK: UI and cross-page items K04-K11 (docs/development/BUGFIX-PLAN-2026-10-10.md, section K)."""

from __future__ import annotations

import inspect

import pandas as pd

from etf_cockpit.backtest.engine import run_backtest
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices


# --- K10: slowness -------------------------------------------------------------------------------


def test_k10_backtest_signal_log_only_holds_enabled_instruments() -> None:
    """A disabled instrument with price rows must not enter the signal log: the cache validator
    only accepts enabled ids, so one such row made every cold start recalculate the backtest (40-60 s)."""

    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    disabled = config.universe.etfs[-1]
    disabled.enabled = False
    assert disabled.id in set(prices["etf_id"]) and disabled.id not in config.universe.enabled_ids

    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert not report.signal_log.empty
    assert set(report.signal_log["etf_id"]) <= set(config.universe.enabled_ids)


def test_k10_heavy_evidence_routes_build_behind_the_skeleton() -> None:
    from etf_cockpit.app import router

    assert {"/signals", "/backtests", "/forward-evidence"} <= router._DEFERRED_RENDER_ROUTES


# --- K04: one canonical value path across pages ---------------------------------------------------

import flet as ft
import pytest

from etf_cockpit.app.state import AppState
from etf_cockpit.application.score_views import confidence_cap_note, score_card_values, snapshot_scores
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "body", ()) or () if isinstance(getattr(control, "body", None), (list, tuple)) else ():
        yield from _walk(child)


def _texts(control) -> list[str]:
    return [str(item.value) for item in _walk(control) if isinstance(item, ft.Text) and item.value]


@pytest.fixture(scope="module")
def state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_k04_components_pair_is_one_value_on_scores_stock_page_and_reason(state: AppState) -> None:
    from etf_cockpit.app.pages import signals
    from etf_cockpit.application.stock_views import build_stock_page_model

    scores = [row for row in snapshot_scores(state.snapshot) if getattr(row, "components", None)]
    assert scores
    for row in scores:
        usable, configured = row.evidence_component_counts
        assert 0 <= usable <= configured
        cell = signals._score_rows([row], None)[0]["components"]
        if cell != signals._not_applicable("Generic components"):
            assert cell == f"{usable}/{configured} valid"
    stock = next((row for row in scores if row.asset_type == "Stock" and row.final_score_10 is not None), None)
    if stock is not None:
        model = build_stock_page_model(state.snapshot, stock.display_id, stock)
        if model.available:
            assert (model.used, model.total) == stock.evidence_component_counts
            assert f"{stock.evidence_component_counts[0]} of {stock.evidence_component_counts[1]} " in stock.one_line_reason


def test_k04_detail_card_numbers_come_from_the_listed_score_row(state: AppState) -> None:
    from etf_cockpit.app.pages import instrument_detail

    row = next(row for row in snapshot_scores(state.snapshot) if row.final_score_10 is not None and row.canonical_score is not None)
    model = instrument_detail._model_for(state, row.display_id)
    texts = _texts(instrument_detail._score_card(model, None, state))
    values = score_card_values(row)

    assert f"Components: {values['valid_components']} of {values['total_components']} usable" in texts
    assert "Evidence quality" in texts and "Evidence confidence" in texts


def test_k04_confidence_cap_is_explained_in_plain_language() -> None:
    note = confidence_cap_note({"confidence_cap": 0.0, "canonical_evidence_confidence_10": 0.0})
    assert note and "fund-structure evidence" in note and "score itself is unchanged" in note
    assert confidence_cap_note({"confidence_cap": None, "canonical_evidence_confidence_10": 3.0}) is None
    assert confidence_cap_note({"confidence_cap": 1.0, "canonical_evidence_confidence_10": 8.0}) is None


# --- K05: Sparebank verdict ----------------------------------------------------------------------

from types import SimpleNamespace


def _bank_score(native: float | None) -> SimpleNamespace:
    gate = SimpleNamespace(gate_id="source_linked_score_evidence", passed=False, message="Source-linked score evidence is available", order=1, severity="warning")
    return SimpleNamespace(
        display_id="NONG",
        final_label="scorecard_owned",
        final_action="manual_review",
        final_score_10=native,
        authority_decision=SimpleNamespace(gates=tuple(SimpleNamespace(**{**gate.__dict__, "gate_id": f"gate_{i}", "order": i}) for i in range(5))),
        risk_friction_10=None,
    )


def test_k05_scorecard_owned_bank_is_not_pending_or_failing_generic_gates() -> None:
    from etf_cockpit.app.pages import _p3_common as common
    from etf_cockpit.app.pages import stock_research

    scored = _bank_score(8.6)
    assert common.evidence_tag(scored) == ("Scorecard", "ok")
    status = stock_research._verdict_status(scored)
    assert "8.6 of 10" in status and "Fails" not in status and "generic gates do not apply" in status

    unscored = _bank_score(None)
    assert common.evidence_tag(unscored)[0] == "No composite"
    assert "more scorecard evidence" in stock_research._verdict_status(unscored)

    # a generic row keeps the gate wording
    generic = SimpleNamespace(**{**scored.__dict__, "final_label": "watchlist"})
    assert stock_research._verdict_status(generic) == "Fails 5 of 5 gates · decision support only"


def test_k05_scorecard_owned_gate_tiles_do_not_show_generic_failures() -> None:
    from etf_cockpit.app.pages import stock_research

    view = SimpleNamespace(max_drawdown=None, range_key="1Y", adjusted_share=None, gap_count=0, last_date=None)
    rows = stock_research._gate_rows(_bank_score(8.6), view, {"ter": ""})
    assert len(rows) == 4 and all(row[0] is not False for row in rows)
    assert any("Not used for banks" in row[2] for row in rows)


# --- K06: Sparebank axes header ------------------------------------------------------------------


def test_k06_axes_header_separates_unrated_from_partially_evidenced_axes() -> None:
    from etf_cockpit.application.sparebank_peers import axis_evidence_groups, axis_evidence_notes, peer_row

    scorecard = {
        "axes": {
            "capital": {"rating_10": 7.3, "coverage": 1.0},
            "credit_concentration": {"rating_10": 9.7, "coverage": 0.5},
            "owner_claim_integrity": {"rating_10": None, "coverage": 0.0},
        },
        "missing_axes": ["credit_concentration", "owner_claim_integrity"],
    }
    without, partial = axis_evidence_groups(scorecard)
    assert (without, partial) == (["owner_claim_integrity"], ["credit_concentration"])
    notes = axis_evidence_notes(without, partial)
    assert notes == [
        "Axes without a rating (no evidence): owner claim integrity.",
        "Axes rated on partial evidence: credit concentration.",
    ]
    assert all("credit concentration" not in note for note in notes if "without" in note)
    # stored rows from before this change only know the undifferentiated list: say so, never "without evidence"
    assert axis_evidence_notes(None, None, ["credit_concentration"]) == ["Axes with incomplete evidence: credit concentration."]
    row = peer_row("NONG", "Nord", {"scorecard": scorecard}, "2026-10-08")
    assert row["axes_without_rating"] == ["owner_claim_integrity"] and row["axes_partial_evidence"] == ["credit_concentration"]


# --- K07: search ---------------------------------------------------------------------------------


def _search(universe_items: list[SimpleNamespace]):
    from etf_cockpit.app.components.shell.search import build_search
    from etf_cockpit.core.navigation import ROUTE_TITLES, WORKSPACE_GROUPS

    visited: list[str] = []
    state = SimpleNamespace(snapshot=SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=universe_items))), last_message="")
    overlay = SimpleNamespace(show=lambda *a, **k: None, hide=lambda *a, **k: None)
    search = build_search(
        SimpleNamespace(),
        state,
        {route: (title, None) for route, title in ROUTE_TITLES},
        WORKSPACE_GROUPS,
        navigate=visited.append,
        overlay=overlay,
        anchor_left=lambda: 0.0,
        anchor_top=0.0,
        compact=False,
    )

    def enter(text: str) -> list[str]:
        visited.clear()
        search.field.on_submit(SimpleNamespace(control=SimpleNamespace(value=text)))
        return list(visited)

    return enter


_UNIVERSE = [
    # the real ETFConfig carries the Yahoo symbol as ``ticker`` / ``provider_symbol`` (no ``yahoo_symbol`` field)
    SimpleNamespace(id="BA", name="BAE Systems", ticker="BA.L", provider_symbol="BA.L", isin="GB0002634946"),
    SimpleNamespace(id="RABO", name="Rabobank certificates", ticker="RABO.AS", provider_symbol=None, isin=None),
    SimpleNamespace(id="VWCE", name="Vanguard FTSE All-World", ticker="VWCE", provider_symbol="VWCE.DE", isin="IE00BK5BQT80"),
]


def test_k07_yahoo_symbols_and_isin_find_the_instrument() -> None:
    from etf_cockpit.app.components.shell.search import exact_instrument_id, instrument_matches

    universe = SimpleNamespace(etfs=_UNIVERSE)
    assert exact_instrument_id(universe, "BA.L") == "BA"
    assert exact_instrument_id(universe, "rabo.as") == "RABO"
    assert exact_instrument_id(universe, "IE00BK5BQT80") == "VWCE"
    assert [item[0] for item in instrument_matches(universe, "RABO.A")] == ["RABO"]
    assert instrument_matches(universe, "zzz") == []

    enter = _search(_UNIVERSE)
    assert enter("BA.L") == ["/instrument/BA"]
    assert enter("RABO.AS") == ["/instrument/RABO"]
    assert enter("BA") == ["/instrument/BA"]  # exact id beats the page "Backtests" that merely contains it


def test_k07_enter_on_a_page_name_opens_that_page_not_the_first_substring_match() -> None:
    from etf_cockpit.core.navigation import ROUTE_TITLES, WORKSPACE_GROUPS, search_commands

    pages = {route: (title, None) for route, title in ROUTE_TITLES}
    assert search_commands(pages, WORKSPACE_GROUPS, "Scores", limit=1)[0].route == "/signals"  # not "Simple Scores" (Home)
    assert search_commands(pages, WORKSPACE_GROUPS, "forecast lab", limit=1)[0].route == "/forecasts"
    enter = _search(_UNIVERSE)
    assert enter("Scores") == ["/signals"]
    assert enter("Data Health") == ["/data-health"]


# --- K08: sectors & countries --------------------------------------------------------------------


def _row(name: str, percentage: float, *contributors: tuple[str, float]) -> dict[str, object]:
    return {
        "name": name,
        "percentage": percentage,
        "value": percentage / 100,
        "contributors": [{"root_instrument_id": key, "weight": weight} for key, weight in contributors],
    }


def test_k08_case_duplicate_buckets_merge_through_one_normaliser() -> None:
    from etf_cockpit.application.ui_views import sectors as view

    rows = [_row("financials", 25.9, ("BA", 0.259)), _row("Financials", 1.7, ("VWCE", 0.017)), _row("  FINANCIALS ", 1.0), _row("Health Care", 3.0), _row("health  care", 2.0)]
    merged = {row["name"]: row for row in view.merge_buckets(rows)}

    assert set(merged) == {"Financials", "Health Care"}
    assert merged["Financials"]["percentage"] == pytest.approx(28.6)
    assert merged["Health Care"]["percentage"] == pytest.approx(5.0)
    assert len(merged["Financials"]["contributors"]) == 2
    # unknown spellings are one bucket; countries merge by ISO code
    unknown = view.merge_buckets([_row("unknown", 5.0), _row("Other/unclassified", 3.0), _row("Unknown/Unmapped", 2.0)])
    assert [(row["name"], row["percentage"]) for row in unknown] == [(view.UNKNOWN, 10.0)]
    countries = view.merge_buckets([_row("United States", 40.0), _row("USA", 10.0)], countries=True)
    assert len(countries) == 1 and countries[0]["percentage"] == 50.0


def test_k08_fund_look_through_replaces_only_that_funds_unknown_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import etf_economics_view
    from etf_cockpit.application.ui_views import sectors as view

    stored = {"VWCE": {"Technology": 0.25, "Financials": 0.15, "Other/unclassified": 0.60}}
    monkeypatch.setattr(etf_economics_view, "fund_split_weights", lambda _snapshot, fund, _dimension: stored.get(fund))
    rows = [
        _row("financials", 10.0, ("BA", 0.10)),
        _row(view.UNKNOWN, 60.0, ("VWCE", 0.50), ("NOSPLIT", 0.10)),
    ]

    result = {row["name"]: row["percentage"] for row in view._with_fund_splits(object(), rows, "sector", countries=False)}

    assert result["Financials"] == pytest.approx(10.0 + 7.5)  # direct "financials" and the fund's 15% merged
    assert result["Technology"] == pytest.approx(12.5)
    assert result[view.UNKNOWN] == pytest.approx(30.0 + 10.0)  # the fund's unclassified remainder + the fund with no split
    assert sum(result.values()) == pytest.approx(70.0)  # nothing created or lost


def test_k08_unknown_share_is_stated_with_its_causes() -> None:
    from etf_cockpit.application.ui_views import sectors as view

    unknown = view.Weight(view.UNKNOWN, 76.0, None, None, None, (("VWCE", 40.0), ("portfolio", 38.0), ("LYP6", 36.0)))
    note = view.unknown_note([unknown], [], known_ids={"VWCE", "LYP6"})
    assert note and "76%" in note and "VWCE, LYP6" in note and "portfolio" not in note and "never estimated" in note
    assert view.unknown_note([view.Weight("USA", 99.5)], []) is None


# --- K09: raw text leaks -------------------------------------------------------------------------


def test_k09_plain_text_maps_developer_text_to_plain_language() -> None:
    from etf_cockpit.app.formatting import plain_text

    assert plain_text("RuntimeError: yfinance is not installed. Run `pip install yfinance` in the project environment.") == (
        "The yfinance price provider is not installed, so prices cannot be refreshed. Install it with “pip install yfinance”."
    )
    assert plain_text("projection failed (financial_decision_time_unavailable)") == (
        "Projection failed (the decision date for the financial statements is not available)"
    )
    assert plain_text("portfolio_snapshot_not_sealed_or_reconciled") == "The portfolio snapshot has not been sealed and reconciled yet"
    assert plain_text("Factor-risk binding unavailable: complete unambiguous snapshot frames are required.").startswith("Factor risk cannot be calculated yet")
    raw = "see https://www.ssga.com/library/holdings.csv, as of 2026-10-08T12:00:00+00:00 (known 2026-10-08T12:00:00Z)"
    shown = plain_text(raw)
    assert "https" not in shown and "T12:00" not in shown and "ssga.com" in shown and "8 Oct 2026" in shown
    # key=value technical suffixes and ordinary text are left alone; the formatter is idempotent
    assert plain_text("Data is stale") == "Data is stale"
    assert plain_text("severity=warning | execution_allowed=false") == "Severity=warning | execution_allowed=false"
    assert plain_text(plain_text(raw)) == shown
    assert plain_text(None) == "Unavailable"


def test_k09_alert_rows_show_plain_message_but_keep_the_pinned_technical_suffix() -> None:
    from etf_cockpit.app.pages import dashboard
    from etf_cockpit.data.alerts import AlertType, build_alert

    alert = build_alert(
        AlertType.STALE_DATA,
        subject_id="VWCE",
        title="Price refresh failed",
        message="RuntimeError: yfinance is not installed. Run `pip install yfinance` in the project environment.",
        severity="warning",
        confidence="high",
        occurred_at="2026-08-01T12:00:00+00:00",
        available_at="2026-08-01T12:00:00+00:00",
        dedupe_key="k09-raw",
    )
    record = SimpleNamespace(alert=alert)
    row = dashboard._alert_row(None, SimpleNamespace(), record, actions=False)  # type: ignore[arg-type]
    text = " ".join(_texts(row))
    assert "RuntimeError" not in text and "The yfinance price provider is not installed" in text
    assert "severity=warning" in text and "execution_allowed=false" in text


def test_k09_evidence_cards_collapse_raw_record_lines() -> None:
    from etf_cockpit.app.pages import instrument_detail

    card = instrument_detail._render_evidence_section(
        "History",
        {"status": "available", "rows": [{"run_id": "score_2026", "na_reason": "Run Refresh yfinance data"}]},
    )
    texts = [str(item.value) for item in _walk(card) if isinstance(item, ft.Text) and item.value]
    assert any("run_id=score_2026" in text for text in texts)  # still available for the technical reader ...
    top_level = [control for control in _walk(card) if isinstance(control, ft.Text) and control.value and "run_id=" in str(control.value)]
    disclosures = [control for control in _walk(card) if isinstance(getattr(control, "data", None), dict) and control.data.get("kit") == "Disclosure"]
    assert any(str(control.data["label"]) == "Evidence records" for control in disclosures)  # ... but inside a collapsed Disclosure
    for text_control in top_level:
        assert any(text_control in set(_walk(disclosure)) for disclosure in disclosures if str(disclosure.data["label"]) == "Evidence records")


def test_k09_unavailable_reasons_on_the_detail_page_are_plain() -> None:
    from etf_cockpit.app.pages import instrument_detail

    reason = instrument_detail._reason({"reason": "Factor-risk binding unavailable: complete unambiguous snapshot frames are required."}, "Risk")
    assert reason.startswith("Factor risk cannot be calculated yet") and "unambiguous" in reason


# --- K11: navigation, status refresh, clipped/overlapping labels ---------------------------------


class _GoPage:
    def __init__(self) -> None:
        self.routes: list[str] = []
        self.views: list = []
        self.route = "/data-models"

    def go(self, route: str) -> None:
        self.routes.append(route)

    def update(self, *_args: object) -> None:
        pass


def test_k11_data_and_models_cards_and_model_rows_navigate(state: AppState) -> None:
    from etf_cockpit.app.pages import data_models

    page = _GoPage()
    view = data_models.data_models_page(page, state)  # type: ignore[arg-type]
    targets = [control for control in _walk(view.body) if str(getattr(control, "tooltip", "") or "").startswith("Open ") and callable(getattr(control, "on_click", None))]
    assert len(targets) >= 12  # every card names the page that owns its data
    for control in targets:
        control.on_click(None)
    assert {"/forecasts", "/data-health", "/catalogue", "/evidence", "/macro", "/news-context", "/diagnostics"} <= set(page.routes)
    # the model status rows (the "chips") open the Forecast Lab too
    page.routes.clear()
    rows = [control for control in _walk(view.body) if getattr(getattr(control, "content", None), "controls", None) is not None and callable(getattr(control, "on_click", None)) and not str(getattr(control, "tooltip", "") or "").startswith("Open ")]
    assert rows
    rows[0].on_click(None)
    assert page.routes == ["/forecasts"]


def test_k11_forecast_lab_status_follows_the_run() -> None:
    from etf_cockpit.app.pages import forecast_lab

    finished = SimpleNamespace(label=forecast_lab.FORECAST_RUN_LABEL, action_id="9f2c", status="completed", message="Configured ETF forecasts refreshed as of 2026-10-08.")
    idle = SimpleNamespace(current_activity=None, recent_activity=[])
    done = SimpleNamespace(current_activity=None, recent_activity=[SimpleNamespace(label="Refresh data", action_id="aa", status="completed", message="x"), finished])
    running = SimpleNamespace(
        current_activity=SimpleNamespace(label=forecast_lab.FORECAST_RUN_LABEL, action_id="9f2c", completed_units=1, total_units=4, step="baseline"),
        recent_activity=[],
    )

    assert "not run in this session" in " ".join(_texts(forecast_lab._run_status(idle)))  # type: ignore[arg-type]
    shown = " ".join(_texts(forecast_lab._run_status(done)))  # type: ignore[arg-type]
    assert "completed" in shown and "refreshed as of" in shown and "not run" not in shown
    assert "in progress" in " ".join(_texts(forecast_lab._run_status(running)))  # type: ignore[arg-type]


def test_k11_table_headers_ellipsise_inside_their_column_and_scores_rank_column_is_narrow() -> None:
    from etf_cockpit.app.components.kit import DataTable, TableColumn
    from etf_cockpit.app.pages import signals

    table = DataTable([TableColumn("a", "Risk/friction", numeric=True), TableColumn("b", "Components")], [{"a": "1", "b": "2"}])
    headers = [control for control in _walk(table) if isinstance(control, ft.Text) and str(control.value).upper() in {"RISK/FRICTION", "COMPONENTS"}]
    assert len(headers) == 2 and {control.tooltip for control in headers} == {"Risk/friction", "Components"}
    assert all(getattr(parent, "expand", None) for parent in _find_parent_containers(table, headers))  # flexible, so it ellipsises
    source = inspect.getsource(signals._score_table)
    assert 'TableColumn("rank", "#", width=36' in source  # the rank column no longer takes a full flex share from the labels


def _find_parent_containers(root, texts):
    parents = []
    for control in _walk(root):
        content = getattr(control, "content", None)
        if any(content is text for text in texts):
            parents.append(control)
    return parents


def test_k11_donut_labels_are_spread_apart_and_inside_the_canvas() -> None:
    import random

    from etf_cockpit.app.components.chartkit.radial import _LABEL_GAP, _spread_labels

    rng = random.Random(7)
    for _ in range(50):
        group = [[True, 0.0, 0.0, 0.0, rng.uniform(20, 260), None] for _ in range(rng.randint(2, 8))]
        _spread_labels(group, 20.0, 260.0)
        ys = [item[4] for item in group]
        assert all(b - a >= _LABEL_GAP - 1e-9 for a, b in zip(ys, ys[1:]))
        assert min(ys) >= 20.0 - 1e-9 and max(ys) <= 260.0 + 1e-9


def test_k11_radar_keeps_axis_labels_clear_of_the_legend_and_inside_the_canvas() -> None:
    from etf_cockpit.app.components.chartkit.radial import _RADAR_BAND, _RADAR_LABEL_ROOM, _radar_geometry

    for width, height in ((380, 170), (400, 320), (320, 220)):
        _cx, cy, r = _radar_geometry(width, height, 0.62, (0.5, 0.54), "top-left")
        assert cy - r - _RADAR_LABEL_ROOM >= _RADAR_BAND - 1e-9  # the top label sits below the legend row
        assert cy + r + _RADAR_LABEL_ROOM <= height + 1e-9  # the bottom label stays inside the canvas


# --- K10 (cont.): the startup trust refresh must not invalidate the shared snapshot ---------------


def test_k10_own_startup_writes_do_not_make_the_next_session_rebuild_the_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from etf_cockpit.app import state as state_module

    fingerprint = {"value": 1}
    monkeypatch.setattr(state_module, "_data_fingerprint", lambda: (fingerprint["value"],))
    monkeypatch.setattr(state_module, "_SHARED_SNAPSHOT", {"snapshot": object(), "key": (1,)})

    assert state_module.shared_snapshot_is_current()
    fingerprint["value"] = 2  # the trust-artifact refresh touches data/derived
    assert not state_module.shared_snapshot_is_current()
    state_module.reseal_shared_snapshot()  # ...and the app acknowledges its own write
    assert state_module.shared_snapshot_is_current()

    # an input that changed before the refresh is NOT acknowledged: the refresh code only reseals when it was current
    monkeypatch.setattr(state_module, "_SHARED_SNAPSHOT", {"snapshot": object(), "key": (1,)})
    fingerprint["value"] = 3
    assert not state_module.shared_snapshot_is_current()


def test_k07_search_universe_adds_the_provider_symbol_from_score_rows(monkeypatch) -> None:
    """VWCE.DE exists only in the provider symbol map the score rows carry, not on the ETFConfig."""

    from etf_cockpit.app.components.shell.search import exact_instrument_id, search_universe
    from etf_cockpit.application import score_views

    etf = SimpleNamespace(id="VWCE", name="Vanguard FTSE All-World", ticker="VWCE", provider_symbol=None, isin="IE00BK5BQT80")
    state = SimpleNamespace(snapshot=SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=[etf]))))
    row = SimpleNamespace(display_id="VWCE", yahoo_symbol="VWCE.DE", isin="IE00BK5BQT80")
    monkeypatch.setattr(score_views, "snapshot_scores", lambda _snapshot: [row])
    assert exact_instrument_id(search_universe(state), "VWCE.DE") == "VWCE"

    def broken(_snapshot):
        raise ValueError("no scores")

    monkeypatch.setattr(score_views, "snapshot_scores", broken)
    assert exact_instrument_id(search_universe(state), "VWCE") == "VWCE"  # falls back to the configured id


def test_k11_verdict_headline_shrinks_to_fit_its_column() -> None:
    from etf_cockpit.app.pages.stock_research import fit_headline_size

    assert fit_headline_size("Watchlist", 230.0) < 68.0  # was cut to "Watc…" at a fixed 68 px
    assert 0.52 * 9 * fit_headline_size("Watchlist", 230.0) <= 230.0
    assert fit_headline_size("Pass", 400.0) == 68.0
    assert fit_headline_size("Unavailable-evidence", 100.0) == 28.0  # never below the floor
