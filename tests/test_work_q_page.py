"""Forecast Lab shows each optional model's automatic promotion state (work-Q)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages.forecast_lab import forecast_lab_page
from etf_cockpit.application.forecast_service import build_forecast_lab_workspace
from etf_cockpit.core.config import load_config
from etf_cockpit.models.model_promotion import COUNTING, NOT_PROVEN
from tests.test_work_q_promotion import INSTRUMENTS, _days, _forecasts, _prices
from tests.ui._p4_helpers import all_text


def test_forecast_lab_page_shows_each_models_promotion_state() -> None:
    config = load_config()
    ids = dict(zip(INSTRUMENTS, config.universe.enabled_ids[:4], strict=True))
    prices = _prices().replace(ids)
    forecasts = _forecasts(prices.replace({v: k for k, v in ids.items()}), {"timesfm3": _days("2023-12-04", 30), "toto": _days("2024-01-02", 2)}).replace(ids)
    forecasts["forecast_date"] = pd.to_datetime(forecasts["forecast_date"])
    snapshot = SimpleNamespace(forecasts=forecasts, prices=prices, config=config, model_status={"baseline": True, "timesfm3": True})
    state = SimpleNamespace(snapshot=snapshot, run_forecasting_models=lambda *_a, **_k: None, current_activity=None, recent_activity=())

    report = build_forecast_lab_workspace(config, forecasts, prices, timing_records=[])
    assert report["promotion"].set_index("model_name")["state"].to_dict() == {"timesfm": NOT_PROVEN, "timesfm3": COUNTING, "toto": NOT_PROVEN}
    assert report["models"].set_index("model_name").loc["baseline", "promotion_state"] == "reference"

    text = all_text(forecast_lab_page(SimpleNamespace(width=1920, height=1200), state).body)
    for expected in ("Promotion and leakage", "Counting in scores", "Not yet proven", "cutoff 2023-11-30", "of 100 matured", "1 of 3 counting"):
        assert expected in text
    assert "shadow only" not in text.lower()


def test_promotion_can_be_switched_off_for_every_model() -> None:
    config = load_config().model_copy(deep=True)
    config.models.promotion.enabled = False
    prices = _prices()
    models = ("timesfm", "timesfm3", "toto")
    report = build_forecast_lab_workspace(config, _forecasts(prices, {model: _days("2024-01-02", 31) for model in models}), prices, timing_records=[])
    assert not report["promotion"]["state"].eq(COUNTING).any()
    assert report["promotion"]["reason"].str.contains("disabled").all()
