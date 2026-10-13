from __future__ import annotations

import time
from types import SimpleNamespace

import flet as ft
from flet import canvas as cv
import pandas as pd
import pytest

from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import Toggle
from etf_cockpit.app.components import simple_scores
from etf_cockpit.app.pages import backtests, dashboard, etf_detail, feature_catalogue, risk, stock_research
from etf_cockpit.app.pages.portfolio import portfolio_page
from etf_cockpit.app.pages.sectors import sectors_page
from etf_cockpit.app.pages.forecast_lab import forecast_lab_page
from tests.ui.test_page_forecast_lab import _data as forecast_data
from tests.ui.test_page_forecast_lab import _state as forecast_state
from tests.ui.test_page_sectors import reference_view
from tests.ui.test_portfolio_sandbox_ui import _state as portfolio_state


@pytest.fixture
def snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(universe=SimpleNamespace(enabled_ids=("MING", "NONG"))),
        data_report=SimpleNamespace(status="Clean", as_of_date="2026-10-08"),
        holdings=pd.DataFrame(),
        prices=pd.DataFrame(),
        forecasts=pd.DataFrame(),
    )


def _walk(root: ft.Control):
    if not isinstance(root, ft.Control):
        return
    yield root
    for child in getattr(root, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(root, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)
    for row in getattr(root, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _text(root: ft.Control) -> str:
    return "\n".join(str(control.value) for control in _walk(root) if isinstance(control, ft.Text))


def test_finding_1_sectors_page_builds_country_and_sector_views(monkeypatch) -> None:
    from etf_cockpit.app.pages import sectors

    monkeypatch.setattr(sectors.view, "load", lambda *_args, **_kwargs: reference_view())
    result = sectors_page(SimpleNamespace(width=1920, height=1200, update=lambda: None), SimpleNamespace(snapshot=object()))
    assert result.chrome.title == "Sectors & Countries"
    result.chrome.segment_groups[0].on_change("Sector")
    assert "top-1 sector" in _text(result.body).casefold()
    assert "Traceback" not in _text(result.body)


def test_finding_2_forecast_lab_keeps_model_status_and_reasons_visible() -> None:
    result = forecast_lab_page(SimpleNamespace(width=1920, height=1200), forecast_state(*forecast_data()))
    text = _text(result.body)
    assert "Model availability source: snapshot model-status registry" in text
    assert "Cached model status: Baseline." in text
    assert "Walk-forward protocol" in text and "Forecast error vs. baseline" in text


def test_finding_3_empty_portfolio_has_a_next_step() -> None:
    state = portfolio_state()
    state.snapshot.holdings = pd.DataFrame(columns=["etf_id", "current_weight", "market_value_eur"])
    result = portfolio_page(None, state)
    text = _text(result.body)
    assert "No current holdings are available" in text
    assert "Next step: set candidate weights below, then select Analyse candidate." in text
    table = next(control for control in _walk(result.body) if getattr(control, "key", None) == "portfolio.holdings.table")
    assert "No holdings registered" in _text(table)


def test_finding_4_stock_research_keeps_selected_instrument(monkeypatch) -> None:
    scores = [
        SimpleNamespace(display_id="MING", final_score_10=7.0, benchmark_id=None, cash_comparison_status="unavailable", cash_return=None, cash_horizon_years=None),
        SimpleNamespace(display_id="NONG", final_score_10=6.0, benchmark_id=None, cash_comparison_status="unavailable", cash_return=None, cash_horizon_years=None),
    ]
    monkeypatch.setattr(stock_research.common, "scores_for", lambda _state: scores)
    monkeypatch.setattr(stock_research.common, "instrument_meta", lambda _state, key: {"name": key, "currency": "NOK", "venue": "local listing", "type": "stock"})
    monkeypatch.setattr(stock_research.common, "grid", lambda _page: SimpleNamespace(row_a=1, row_b=1))
    monkeypatch.setattr(stock_research.common, "place", lambda *_args, **_kwargs: ft.Container())
    monkeypatch.setattr(stock_research.common, "below_fold", lambda *_args, **_kwargs: ft.Column())
    monkeypatch.setattr(stock_research.research_view, "build_stock_view", lambda *_args, **_kwargs: object())
    state = SimpleNamespace(
        snapshot=SimpleNamespace(prices=pd.DataFrame(), forecasts=pd.DataFrame()),
        selected_etf="MING",
        recent_instruments=["NONG", "MING"],
    )
    page = SimpleNamespace(width=1920, height=1200, update=lambda: None)
    result = stock_research.stock_research_page(page, state)
    chrome = result.chrome.segment_groups[0].on_change("NONG")
    assert state.selected_etf == "NONG"
    assert chrome.title == "Stock Research · NONG"
    assert result.chrome.segment_groups[0].selected == "MING"
    assert chrome.segment_groups[0].selected == "NONG"


def test_finding_5_toggle_thumb_is_centered_inside_track() -> None:
    toggle = Toggle(False)
    knob = toggle.content
    assert (toggle.width, toggle.height) == (40, 22)
    assert toggle.padding.left == toggle.padding.right == 3
    assert toggle.padding.top == toggle.padding.bottom == 2
    assert (knob.width, knob.height) == (18, 18)
    assert toggle.alignment == ft.Alignment(-1, 0)
    toggle.on_click(None)
    assert toggle.alignment == ft.Alignment(1, 0)


def test_finding_6_donut_outside_label_clears_bottom_legend() -> None:
    chart = ck.donut_chart(
        [ck.Slice("Equity ETFs", 46, "#9ad1ff"), ck.Slice("Stocks", 27, "#6fcfa6"), ck.Slice("Bonds", 27, "#f0d79a")],
        width=420,
        height=280,
    )
    shapes = ck.scene_of(chart).shapes
    outside = next(shape for shape in shapes if isinstance(shape, cv.Text) and shape.value == "Stocks\n27")
    legend = next(shape for shape in shapes if isinstance(shape, cv.Text) and shape.value == "Stocks")
    assert outside.y < legend.y - 24


def test_finding_7_missing_ter_has_reason_and_source_zero_stays_zero() -> None:
    missing = etf_detail._ter_label(SimpleNamespace(ter=None))
    assert missing.startswith("TER unavailable:") and "local instrument configuration" in missing
    assert etf_detail._ter_label(SimpleNamespace(ter=0.0)) == "TER 0.00%"


def test_home_build_uses_fixture_snapshot_and_caches_history_per_snapshot(monkeypatch, snapshot) -> None:
    calls: list[str] = []
    monkeypatch.setattr(dashboard, "score_history_frame", lambda: calls.append("history") or pd.DataFrame())
    state = SimpleNamespace(snapshot=snapshot)
    page = SimpleNamespace(run_thread=lambda *_args, **_kwargs: None)
    started = time.perf_counter()
    result = dashboard.dashboard_page(page, state)
    elapsed = time.perf_counter() - started
    assert elapsed < 3.0
    assert "Snapshot loaded" in _text(result.body)
    assert calls == []  # the first Home paint does not reload rows
    dashboard._score_history_for_snapshot(state)
    dashboard._score_history_for_snapshot(state)
    assert calls == ["history"]


def test_p2_3_score_detail_shows_coverage_components_or_reason() -> None:
    score = SimpleNamespace(coverage=0.75, components=({"key": "valuation", "score_eligible": False},))
    item = SimpleNamespace(canonical_score=score, one_line_reason="")
    detail = simple_scores._canonical_score_detail(item)
    assert "75%" in detail and "valuation" in detail
    unavailable = simple_scores._canonical_score_detail(SimpleNamespace(canonical_score=None, one_line_reason="No source payload"))
    assert "unavailable" in unavailable.casefold() and "No source payload" in unavailable


def test_p2_4_source_values_keep_zero_and_explain_missing() -> None:
    assert backtests._format_source_metric(0, percent=True) == "0"
    assert risk._source_percent(0, "source reports zero", source_present=True) == "0"
    missing_backtest = backtests._source_metric_cell(None, "annual_return")
    assert isinstance(missing_backtest, ft.Text) and missing_backtest.value == "Unavailable"
    assert "saved backtest result" in missing_backtest.tooltip
    missing_risk = risk._source_percent(None, "exposure evidence is absent")
    assert isinstance(missing_risk, ft.Text) and missing_risk.value == "Unavailable"
    assert "exposure evidence is absent" in missing_risk.tooltip


def test_p2_9_dashboard_counts_keep_distinct_source_labels() -> None:
    root = dashboard._summary_cards(
        SimpleNamespace(snapshot=SimpleNamespace(data_report=SimpleNamespace(status="Clean"))),
        None,
        2,
        3,
        1,
        4,
        narrow=False,
    )
    text = _text(root)
    assert "Source: configured local universe" in text
    assert "Source: local candidate universe" in text
    assert "Source: Sparebanken scorecard rows" in text
    assert "Source: filtered local forecast rows" in text
    assert feature_catalogue._display_value(0) == "0"
