from __future__ import annotations

import inspect
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages import forecast_lab
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS
from etf_cockpit.core.config import load_config


def test_forecast_lab_workspace_is_registered_and_safe() -> None:
    assert PAGES["/forecasts"][0] == "Forecast Lab"
    assert any("/forecasts" in routes for _, routes in WORKSPACE_GROUPS)
    source = inspect.getsource(forecast_lab)
    for label in (
        "Experiment runs",
        "Model comparison",
        "Model cards",
        "Walk-forward protocol",
        "shadow_only",
        "execution_allowed=false",
        "Run forecasting models",
    ):
        assert label in source


def _texts(control: object) -> list[str]:
    found: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        found.append(value)
    for name in ("controls", "rows", "cells", "columns"):
        for child in getattr(control, name, None) or ():
            found.extend(_texts(child))
    for name in ("content", "label"):
        child = getattr(control, name, None)
        if child is not None and not isinstance(child, str):
            found.extend(_texts(child))
    return found


def test_forecast_lab_renders_net_value_coverage_runtime_and_fold_evaluation(monkeypatch) -> None:
    config = load_config()
    instrument_id = config.universe.enabled_ids[0]
    dates = pd.bdate_range("2026-01-01", periods=14)
    prices = pd.DataFrame(
        {"etf_id": instrument_id, "date": dates, "adjusted_close": [100.0 + index for index in range(14)]}
    )
    forecasts = pd.DataFrame(
        {
            "run_id": "run-1",
            "model_name": "baseline",
            "etf_id": instrument_id,
            "forecast_date": dates[:6],
            "horizon_days": 1,
            "expected_return": 0.01,
            "q10_return": -0.01,
            "q90_return": 0.03,
            "status": "ok",
        }
    )
    monkeypatch.setattr(
        "etf_cockpit.features.forecast_lab.timing_summary",
        lambda **_kwargs: {"records": [{"action_id": "forecasts", "step": "model:baseline", "duration_ms": 42.0}]},
    )
    state = SimpleNamespace(
        snapshot=SimpleNamespace(
            forecasts=forecasts,
            prices=prices,
            config=config,
            model_status={"baseline": True},
        ),
        run_forecasting_models=lambda *_args, **_kwargs: None,
    )

    text = "\n".join(_texts(forecast_lab.forecast_lab_page(None, state)))

    for label in ("Net value", "Coverage int/conf", "Runtime", "42 ms", "positive_net_edge", "wf-01", "Matured"):
        assert label in text
    assert "Resource and latency metadata: not recorded" not in text
