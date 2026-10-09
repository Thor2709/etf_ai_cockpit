from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import flet as ft
import flet.canvas as cv
import pandas as pd

from etf_cockpit.app.components.chartkit import Series, price_drawdown_chart, scene_of
from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import (
    backtests,
    diagnostics,
    feature_catalogue,
    macro_factors,
    news_context,
    portfolio,
    provider_status,
    risk,
)
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.ui_views.portfolio import HoldingLine


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None and content is not control:
        yield from _walk(content)


@lru_cache(maxsize=1)
def _sample_state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_crash_pages_build_cards_without_none_children() -> None:
    news = news_context.news_context_page(None, _sample_state())
    diagnostics_view = diagnostics.diagnostics_page(None, _sample_state())

    assert isinstance(news, PageView)
    assert isinstance(diagnostics_view, PageView)
    for view in (news, diagnostics_view):
        controls = list(_walk(view.body))
        assert controls
        assert all(control is not None for control in controls)
        assert all(
            child is not None
            for control in controls
            for child in (getattr(control, "controls", ()) or ())
        )

    news_card = next(
        control
        for control in _walk(news.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("title") == "News/macro contradictions"
    )
    assert news_card.content is not None
    duration_tile = next(
        control
        for control in _walk(diagnostics_view.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "KpiTile"
        and control.data.get("label") == "Durations"
    )
    assert duration_tile.content is not None
    assert duration_tile.data["value"] is None or isinstance(duration_tile.data["value"], str)


def test_provider_capabilities_keep_strings_as_whole_names() -> None:
    assert provider_status._capability_text("alphavantage") == "alphavantage"
    assert provider_status._capability_text(("etf_holdings", "prices")) == "etf_holdings, prices"


def test_missing_portfolio_and_risk_values_stay_unavailable() -> None:
    missing = {"status": "unavailable", "value": 0.0, "reason": "source_value_unavailable"}
    assert portfolio._cell_number(missing) is None
    assert portfolio._short(missing) is None

    allocation = pd.DataFrame([{"etf_id": "ETF-A", "asset_class": "equity"}])
    availability = risk._current_weight_availability(
        pd.DataFrame([{"etf_id": "ETF-A", "current_weight": None}])
    )
    assert not risk._bucket_weight_available(allocation, "asset_class", "equity", availability)
    assert not risk._bucket_weight_available(allocation, "etf_id", "ETF-A", availability)

    no_exposure = [HoldingLine("ETF-A", "ETF-A", 0.0, None, None, 0.0)]
    assert portfolio._risk_chart_unavailable_reason(no_exposure, None)


def test_feature_preview_formats_missing_cells_and_keeps_chart_labels_unsigned() -> None:
    assert feature_catalogue._display_value(float("nan")) == "—"
    assert feature_catalogue._display_value(pd.NaT) == "—"
    assert feature_catalogue._display_value("nan") == "—"

    chart = feature_catalogue.ck.grouped_bar_chart(
        ["drawdown_current"],
        [
            feature_catalogue.ck.BarSeries("Coverage at least 80%", [100.0], kind="blue"),
            feature_catalogue.ck.BarSeries("Coverage below 80%", [None], kind="gold"),
        ],
        x_name="Feature",
        y_name="Coverage (%)",
        unit="%",
        width=900,
    )
    assert not any(text.startswith("+") for text in scene_of(chart).texts())


def test_backtest_rates_format_as_percent_and_time_axis_keeps_right_label() -> None:
    keys = (
        ("strategy_name", "Strategy"),
        ("cagr", "CAGR"),
        ("volatility", "Vol"),
        ("sharpe", "Sharpe"),
        ("max_drawdown", "Max DD"),
    )
    rows = backtests._normalized_strategy_rows(
        [
            {"strategy_name": "signal_strategy", "cagr": 0.0445, "volatility": 0.103946, "sharpe": 0.8, "max_drawdown": -0.125},
            {"strategy_name": "quality_only", "cagr": 0.0, "volatility": 0.0, "sharpe": 0.0, "max_drawdown": 0.0},
        ],
        keys,
    )
    assert rows[0]["cagr"] == "4.45%"
    assert rows[0]["volatility"] == "10.39%"
    assert rows[0]["max_drawdown"] == "-12.50%"
    assert all(rows[1][key] is None for key, _label in keys if key != "strategy_name")

    chart = price_drawdown_chart(
        [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc)],
        [Series("Equity", [100.0, 101.0])],
        [0.0, -0.01],
    )
    right_label = next(
        shape
        for shape in scene_of(chart).shapes
        if isinstance(shape, cv.Text) and shape.value == "Feb 26"
    )
    assert right_label.alignment.x == 1


def test_macro_regime_tag_tracks_value_availability() -> None:
    unavailable = macro_factors._regime_tag("Unavailable")
    available = macro_factors._regime_tag("Risk-on")
    assert unavailable.data["text"] == "Unavailable"
    assert available.data["text"] == "Available"
