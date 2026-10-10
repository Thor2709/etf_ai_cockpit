"""Bug-fix batch T-UIK: UI and cross-page items K04-K11 (docs/development/BUGFIX-PLAN-2026-10-10.md, section K)."""

from __future__ import annotations

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
