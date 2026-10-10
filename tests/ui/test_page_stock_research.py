"""Stock Research first screen: view-model rules and rendered cards (FINAL_UI_SPEC 6.3)."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pandas as pd

from etf_cockpit.app.pages import _p3_common as common
from etf_cockpit.app.pages.stock_research import stock_research_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.ui_views.stock_research import build_stock_view, scenario_surface_reason


def _walk(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(c, "value", "") or "") for c in _walk(control))


def _prices(days: int = 400) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=days)
    close = 100 + np.cumsum(np.sin(np.arange(days) / 7.0))
    return pd.DataFrame({"etf_id": "AAA", "date": dates, "close": close, "adjusted_close": close, "is_adjusted": True})


def _forecasts(with_q25: bool = True) -> pd.DataFrame:
    rows = []
    for horizon in (21, 63, 126):
        spread = 0.03 * (horizon / 63) ** 0.5
        rows.append({
            "etf_id": "AAA", "model_name": "toto", "horizon_days": horizon,
            "forecast_date": _prices()["date"].iloc[-1],
            "q10_return": -spread, "q25_return": -spread / 2 if with_q25 else None, "q50_return": 0.0,
            "q75_return": spread / 2 if with_q25 else None, "q90_return": spread,
        })
    return pd.DataFrame(rows)


def test_sharpe_is_unavailable_without_a_risk_free_rate() -> None:
    view = build_stock_view(_prices(), pd.DataFrame(), "AAA", "1Y")
    assert view.volatility is not None and view.sharpe is None
    assert "risk-free" in view.stat_reasons["sharpe"]
    with_rate = build_stock_view(_prices(), pd.DataFrame(), "AAA", "1Y", cash_return=0.02, cash_horizon_years=1.0)
    assert with_rate.sharpe is not None


def test_forecast_quantiles_are_passed_through_never_interpolated() -> None:
    view = build_stock_view(_prices(), _forecasts(with_q25=False), "AAA", "1Y")
    assert len(view.forecasts) == 1
    assert view.forecasts[0].q25 == [None, None, None]
    assert view.forecasts[0].q75 == [None, None, None]
    complete = build_stock_view(_prices(), _forecasts(), "AAA", "1Y")
    assert len(complete.forecasts) == 1
    assert all(value is not None for value in complete.forecasts[0].q25)
    assert all(value is not None for value in complete.forecasts[0].q75)
    anchor = _prices()["close"].iloc[-1]
    np.testing.assert_allclose(complete.forecasts[0].q25, anchor * (1 + _forecasts()["q25_return"]))
    np.testing.assert_allclose(complete.forecasts[0].q75, anchor * (1 + _forecasts()["q75_return"]))
    broken = _forecasts()
    broken.loc[0, "q50_return"] = np.nan
    unavailable = build_stock_view(_prices(), broken, "AAA", "1Y")
    assert len(unavailable.forecasts) == 1
    assert len(unavailable.forecasts[0].dates) == 2
    assert unavailable.forecasts[0].dates == complete.forecasts[0].dates[1:]


def test_missing_attribution_components_stay_unavailable_and_empty_prices_are_explained() -> None:
    view = build_stock_view(_prices(), pd.DataFrame(), "AAA", "1Y")
    assert view.attribution["Price"] is not None
    assert all(view.attribution[name] is None for name in ("FX", "Fees", "Tax"))
    empty = build_stock_view(pd.DataFrame(), pd.DataFrame(), "AAA", "1Y")
    assert empty.unavailable_price and empty.total_return is None and not empty.close


def test_scenario_surface_reason_names_what_is_missing() -> None:
    assert "3 horizons" in scenario_surface_reason(pd.DataFrame(), "AAA", 5)
    assert "2 saved" in scenario_surface_reason(_forecasts(), "AAA", 1)
    assert "volatility" in scenario_surface_reason(_forecasts(), "AAA", 3)


def _state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_page_renders_the_five_reference_cards_and_chrome() -> None:
    state = _state()
    page = SimpleNamespace(width=1920, height=1200, update=lambda: None)
    view = stock_research_page(page, state)
    text = _text(view.body)
    for title in ("Price, forecast & drawdown", "Return attribution", "Rolling 12-month return vs. benchmark", "Factor profile & screening", "RESEARCH VERDICT"):
        assert title.casefold() in text.casefold()
    assert view.chrome.title.startswith("Stock Research · ")
    assert [group.items[-1] for group in view.chrome.segment_groups][1] == "5Y"
    assert "Traceback" not in text and "Error" not in text


def test_scenarios_segment_switches_in_place_to_an_unavailable_surface() -> None:
    state = _state()
    page = SimpleNamespace(width=1920, height=1200, update=lambda: None)
    view = stock_research_page(page, state)
    scenarios = [c for c in _walk(view.body) if isinstance(getattr(c, "data", None), dict) and c.data.get("value") == "Scenarios (3D)"]
    assert scenarios, "the rolling card exposes its in-card Segmented"
    scenarios[0].on_click(None)
    assert "No scenario surface" in _text(view.body)


def test_range_segment_rebuilds_the_page_and_empty_scores_show_an_empty_state(monkeypatch) -> None:
    state = _state()
    page = SimpleNamespace(width=1920, height=1200, update=lambda: None)
    view = stock_research_page(page, state)
    range_group = view.chrome.segment_groups[1]
    range_group.on_change("3M")
    assert "Return 3M".casefold() in _text(view.body).casefold()
    monkeypatch.setattr(common, "scores_for", lambda _state: [])
    empty = stock_research_page(page, state)
    assert "No scored instruments" in _text(empty.body)
    assert dataclasses.is_dataclass(empty.chrome)
