"""Forecast CLI/cache integration and explicit missing-data publication."""

import importlib
from pathlib import Path
import sys

import pandas as pd

from etf_cockpit.application.derived_cache import (
    _calculation_window, _current_universe_revision, _price_snapshot_binding,
)
from etf_cockpit.application.forecast_service import _config_with_optional_models_disabled
from etf_cockpit.application.reference_context import (
    _benchmark_reference_snapshot_inputs, _reference_context_from_inputs,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.data.duckdb_store import load_holdings, load_prices
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity, load_latest_forecasts


def _inputs():
    config = _config_with_optional_models_disabled(load_config())
    prices = load_prices()
    as_of = pd.to_datetime(prices["date"]).max().date()
    context = _reference_context_from_inputs(
        _benchmark_reference_snapshot_inputs(config, as_of, load_holdings()),
        purpose="comparison", analysis_id="forecast-test",
    )
    return config, prices, as_of, context


def test_forecast_runner_output_is_accepted_by_app_loader(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runner = importlib.import_module("run_forecasts")
    from etf_cockpit.application import forecast_service

    config, prices, as_of, context = _inputs()
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "require_cached_inputs", lambda *paths: None)
    monkeypatch.setattr(runner, "load_prices", lambda: prices)
    monkeypatch.setattr(forecast_service, "FORECASTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_forecasts.py"])
    assert runner.main() == 0
    window = _calculation_window(context, as_of, prices)
    loaded = load_latest_forecasts(
        directory=tmp_path, universe_revision=_current_universe_revision(),
        reference_identity=context.identity,
        price_binding=_price_snapshot_binding(prices, calculation_window=window),
        forecast_request_identity=configured_forecast_request_identity(config),
    )
    assert not loaded.empty
    assert (loaded.loc[loaded.model_name == "baseline", "status"] == "ok").any()
    assert set(loaded.loc[loaded.model_name != "baseline", "status"]) == {"unavailable"}

