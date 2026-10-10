"""Missing and insufficient adjusted history has an explicit forecast status."""

from datetime import date

import pandas as pd

from etf_cockpit.application.forecast_service import ForecastService, _config_with_optional_models_disabled
from etf_cockpit.application.reference_context import (
    _benchmark_reference_snapshot_inputs, _reference_context_from_inputs,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.data.duckdb_store import load_holdings, load_prices


def _inputs():
    config = _config_with_optional_models_disabled(load_config())
    prices = load_prices()
    as_of = pd.to_datetime(prices["date"]).max().date()
    context = _reference_context_from_inputs(
        _benchmark_reference_snapshot_inputs(config, as_of, load_holdings()),
        purpose="comparison", analysis_id="forecast-test",
    )
    return config, prices, as_of, context


def test_missing_requested_baseline_publishes_null_unavailable_rows(tmp_path):
    config, prices, as_of, context = _inputs()
    instrument_id = config.universe.enabled_ids[0]
    prices = prices.loc[prices.etf_id != instrument_id].copy()
    output = tmp_path / f"forecast_results_{as_of:%Y%m%d}.csv"
    rows = ForecastService(config, reference_context=context).run_forecasts(
        as_of, [instrument_id], prices, output_path=output,
    )
    baseline = [row for row in rows if row.model_name == "baseline"]
    assert {row.horizon_days for row in baseline} == set(config.models.forecast_horizons_trading_days)
    assert all(row.status == "unavailable" and not row.model_allowed_in_score for row in baseline)
    assert all(row.expected_return is None and row.expected_excess_return is None for row in baseline)
    loaded = pd.read_csv(output)
    assert loaded.loc[loaded.model_name == "baseline", "expected_return"].isna().all()


def test_future_prices_cannot_rescue_insufficient_baseline_history(tmp_path):
    config, prices, _, _ = _inputs()
    instrument_id = config.universe.enabled_ids[0]
    history = prices.loc[prices.etf_id == instrument_id].sort_values("date")
    # Use the existing fixture's dates and prices; retain the future rows to exercise clipping.
    as_of: date = pd.to_datetime(history.iloc[10]["date"]).date()
    rows = ForecastService(config).run_forecasts(
        as_of, [instrument_id], history,
        output_path=tmp_path / f"forecast_results_{as_of:%Y%m%d}.csv",
    )
    baseline = [row for row in rows if row.model_name == "baseline"]
    assert len(baseline) == len(config.models.forecast_horizons_trading_days)
    assert all(row.status == "unavailable" and row.expected_return is None for row in baseline)
    assert all(row.reason_unavailable == "insufficient_adjusted_price_history" for row in baseline)
