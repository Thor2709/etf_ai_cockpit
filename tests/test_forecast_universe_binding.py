"""Forecast caches must bind to the same enabled-universe prices the snapshot scores read."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from tests.test_work_b_pipeline_runners import _runner


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=5)
    return pd.DataFrame(
        [{"date": d, "etf_id": etf, "adjusted_close": 100.0 + i} for etf in ("ON", "OFF") for i, d in enumerate(dates)]
    )


def test_run_forecasts_passes_only_enabled_universe_prices(monkeypatch):
    runner = _runner(monkeypatch, "run_forecasts")
    monkeypatch.setattr(sys, "argv", ["run_forecasts.py"])
    monkeypatch.delenv("ETF_COCKPIT_ROOT", raising=False)
    monkeypatch.setattr(runner, "require_cached_inputs", lambda *paths: None)
    config = SimpleNamespace(universe=SimpleNamespace(enabled_ids=["ON"]))
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "load_prices", _prices)
    seen: dict[str, set[str]] = {}

    class Stop(Exception):
        pass

    monkeypatch.setattr(runner, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(runner, "_benchmark_reference_snapshot_inputs", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_reference_context_from_inputs", lambda *a, **k: None)
    monkeypatch.setattr(
        runner,
        "configured_forecast_request_identity",
        lambda cfg: {"live_optional_models": True, "requested_horizons": [60]},
    )

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def run_forecasts(self, as_of, ids, prices, **kwargs):
            seen["ids"] = set(prices["etf_id"].astype(str))
            raise Stop

    monkeypatch.setattr(runner, "ForecastService", Service)
    try:
        runner.main()
    except Stop:
        pass
    assert seen["ids"] == {"ON"}
