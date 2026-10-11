"""Forecast Lab page: view-model rules and rendered cards (FINAL_UI_SPEC 6.6)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages.forecast_lab import forecast_lab_page
from etf_cockpit.application.ui_views import forecast_lab as view
from etf_cockpit.core.config import load_config
from tests.ui._p4_helpers import all_text, card_titles


def _state(forecasts: pd.DataFrame, prices: pd.DataFrame) -> SimpleNamespace:
    config = load_config()
    snapshot = SimpleNamespace(forecasts=forecasts, prices=prices, config=config, model_status={"baseline": True})
    return SimpleNamespace(snapshot=snapshot, run_forecasting_models=lambda *_a, **_k: None, current_activity=None, recent_activity=())


def _data():
    config = load_config()
    etf = config.universe.enabled_ids[0]
    dates = pd.bdate_range("2026-01-01", periods=30)
    prices = pd.DataFrame({"etf_id": etf, "date": dates, "adjusted_close": [100.0 + i for i in range(30)]})
    rows = [
        {"run_id": "r", "model_name": m, "etf_id": etf, "forecast_date": d, "horizon_days": 1, "expected_return": e, "status": "ok"}
        for m, e in (("baseline", 0.01), ("toto", 0.02))
        for d in dates[:10]
    ]
    return pd.DataFrame(rows), prices


def test_error_series_needs_a_baseline_and_never_invents_values() -> None:
    forecasts, _ = _data()
    none = view.error_vs_baseline(forecasts, pd.DataFrame(), ["toto"], max_horizon=252)
    assert none.baseline is None and none.reason and not none.lines
    empty = view.error_vs_baseline(forecasts, pd.DataFrame(), ["baseline", "toto"], max_horizon=252)
    assert empty.reason and "matured" in empty.reason


def test_fold_bars_report_a_reason_without_splits() -> None:
    assert view.fold_bars(pd.DataFrame(), None).reason
    splits = pd.DataFrame({"split_id": ["wf-01"], "train_end": ["2026-03-01"], "test_start": ["2026-03-02"], "test_end": ["2026-03-02"]})
    bars = view.fold_bars(splits, "2026-01-01")
    assert bars.labels == ("Fold 1",) and bars.train_months[0] > 1.5 and bars.test_months[0] > 0


def test_page_renders_cards_segments_and_run_key() -> None:
    result = forecast_lab_page(SimpleNamespace(width=1920, height=1200), _state(*_data()))
    titles = card_titles(result.body)
    for title in ("Run forecasting models", "Model comparison", "Walk-forward protocol", "Forecast error vs. baseline", "Model cards"):
        assert title in titles
    assert [list(g.items)[:2] for g in result.chrome.segment_groups][0] == ["All models", "Baseline"]
    assert list(result.chrome.segment_groups[1].items) == ["1M", "3M", "1Y"]
    assert "shadow_only" in all_text(result.body)
    result.chrome.segment_groups[0].on_change("Baseline")
    result.chrome.segment_groups[1].on_change("1M")


def test_empty_forecasts_show_unavailable_states_not_zeros() -> None:
    state = _state(pd.DataFrame(columns=["model_name", "etf_id", "forecast_date", "horizon_days", "expected_return", "status"]), pd.DataFrame(columns=["etf_id", "date", "adjusted_close"]))
    result = forecast_lab_page(SimpleNamespace(width=1100, height=900), state)
    text = all_text(result.body)
    assert "Unavailable" in text
    assert "FORECAST ROWS" in text
