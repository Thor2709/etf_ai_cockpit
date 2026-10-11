"""Work-R: every forecast producer fills the full return-distribution contract so the uncertainty gate can evaluate."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import _forecast_to_row
from etf_cockpit.core.config import ModelRuntimeConfig
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.distribution_store import (
    DERIVED_QUANTILE_FIELDS,
    NORMAL_Z_90,
    NORMAL_Z_95,
    QUANTILE_FIELDS,
    QUANTILE_METHOD_DECILES,
    QUANTILE_METHOD_NORMAL,
    REQUIRED_HISTORY_RETURNS,
    complete_return_quantiles,
    history_coverage_ratio,
)
from etf_cockpit.models.timesfm_adapter import TimesFMAdapter, timesfm_level_forecast_to_results
from etf_cockpit.models.toto_adapter import TotoAdapter, toto_quantiles_to_log_return_results

FORECAST_DATE = date(2026, 9, 30)
HORIZONS = [5, 60]
TAIL_SCALE = NORMAL_Z_95 / NORMAL_Z_90


def _prices(days: int = 300, seed: int = 3) -> pd.Series:
    index = pd.bdate_range(end=pd.Timestamp(FORECAST_DATE), periods=days)
    steps = np.random.default_rng(seed).normal(0.0004, 0.01, days)
    return pd.Series(100.0 * np.exp(np.cumsum(steps)), index=index)


def _assert_full_contract(row) -> None:
    assert row.status == "ok"
    values = [getattr(row, field) for field in QUANTILE_FIELDS]
    assert all(value is not None and np.isfinite(value) for value in values), values
    assert values == sorted(values)
    assert row.coverage_ratio is not None and 0.0 <= row.coverage_ratio <= 1.0
    assert row.quantile_method is not None


def _fan(steps: int = 60) -> np.ndarray:
    """Deciles q10..q90 of a level forecast around 100 that widens with the step."""

    offsets = (np.arange(1, 10) - 5) / 10.0
    return np.asarray([100.0 * (1.0 + 0.001 * (step + 1) + 0.02 * np.sqrt(step + 1) * offsets) for step in range(steps)])


def _head(width: int) -> tuple[np.ndarray, np.ndarray]:
    deciles = _fan()
    if width == 10:
        matrix = np.concatenate([deciles[:, 4:5], deciles], axis=1)  # [mean, q10 .. q90]
        return deciles[:, 4], matrix
    return deciles[:, 4], deciles


def test_every_producer_ok_row_has_the_full_monotone_distribution_and_coverage() -> None:
    series = _prices()
    mock = ModelRuntimeConfig(enabled=True, mode="mock")
    frame = pd.DataFrame({"date": series.index, "etf_id": "ETF", "adjusted_close": series.to_numpy()})
    rows = list(baseline_forecast("ETF", series, HORIZONS, FORECAST_DATE, "r"))
    rows += TimesFMAdapter(mock).forecast_series(series, HORIZONS, etf_id="ETF", forecast_date=FORECAST_DATE, run_id="r")
    rows += TotoAdapter(mock).forecast_etf("ETF", FORECAST_DATE, HORIZONS, prices=frame, run_id="r")
    for model_name in ("timesfm", "timesfm3"):
        for width in (10, 9):
            mean, matrix = _head(width)
            rows += timesfm_level_forecast_to_results(
                mean_predictions=mean, quantile_predictions=matrix[None], last_value=100.0, horizons=HORIZONS,
                etf_id="ETF", forecast_date=FORECAST_DATE, run_id="r", model_version="v",
                model_name=model_name, observed_returns=400,
            )
    toto = np.sort(np.random.default_rng(1).normal(0.0, 0.01, (9, 1, 1, 60)), axis=0)
    rows += toto_quantiles_to_log_return_results(
        quantiles=toto, horizons=HORIZONS, etf_id="ETF", forecast_date=FORECAST_DATE, run_id="r",
        model_version="v", observed_returns=100,
    )
    assert len(rows) == 2 + 2 + 2 + 8 + 2
    for row in rows:
        _assert_full_contract(row)
        assert {*QUANTILE_FIELDS, "coverage_ratio", "quantile_method"} <= set(_forecast_to_row(row))


def test_model_without_native_tails_gets_the_documented_normal_values_with_provenance() -> None:
    quantiles = complete_return_quantiles(-0.08, 0.02, 0.12)
    assert quantiles is not None
    assert quantiles["q05_return"] == pytest.approx(0.02 - 0.10 * TAIL_SCALE)
    assert quantiles["q95_return"] == pytest.approx(0.02 + 0.10 * TAIL_SCALE)
    assert quantiles["q10_return"] == -0.08 and quantiles["q90_return"] == 0.12
    # A native q25/q75 is kept; only the missing levels are derived.
    native = complete_return_quantiles(-0.08, 0.02, 0.12, q25=-0.03, q75=0.07)
    assert native is not None and native["q25_return"] == -0.03 and native["q75_return"] == 0.07
    # Crossing or missing input is never repaired or zero-filled.
    assert complete_return_quantiles(0.05, 0.02, 0.12) is None
    assert complete_return_quantiles(None, 0.02, 0.12) is None

    baseline = baseline_forecast("ETF", _prices(), [20], FORECAST_DATE, "r")[0]
    assert baseline.quantile_method == QUANTILE_METHOD_NORMAL
    expected = complete_return_quantiles(baseline.q10_return, baseline.q50_return, baseline.q90_return)
    assert expected is not None
    assert [getattr(baseline, field) for field in DERIVED_QUANTILE_FIELDS] == [expected[f] for f in DERIVED_QUANTILE_FIELDS]

    mean, matrix = _head(10)
    live = timesfm_level_forecast_to_results(
        mean_predictions=mean, quantile_predictions=matrix[None], last_value=100.0, horizons=[5], etf_id="ETF",
        forecast_date=FORECAST_DATE, run_id="r", model_version="v", observed_returns=400,
    )[0]
    assert live.quantile_method == QUANTILE_METHOD_DECILES
    q20, q30 = np.log(matrix[4, 2] / 100.0), np.log(matrix[4, 3] / 100.0)
    assert live.q25_return == pytest.approx((q20 + q30) / 2.0)
    assert live.q05_return == pytest.approx(live.q50_return - (live.q50_return - live.q10_return) * TAIL_SCALE)


def test_missing_history_leaves_coverage_missing() -> None:
    assert history_coverage_ratio(None) is None
    assert history_coverage_ratio(0) is None
    assert history_coverage_ratio(REQUIRED_HISTORY_RETURNS // 2) == pytest.approx(0.5)
    assert history_coverage_ratio(10 * REQUIRED_HISTORY_RETURNS) == 1.0
    short = baseline_forecast("ETF", _prices(days=100), [5], FORECAST_DATE, "r")[0]
    assert short.coverage_ratio == pytest.approx(99 / REQUIRED_HISTORY_RETURNS)
    assert baseline_forecast("ETF", _prices(days=10), [5], FORECAST_DATE, "r") == []


def test_baseline_ignores_prices_after_the_forecast_date() -> None:
    series = _prices(days=300)
    future = pd.Series(
        series.iloc[-1] * np.exp(np.cumsum(np.full(40, 0.05))),
        index=pd.bdate_range(start=series.index[-1] + pd.offsets.BDay(1), periods=40),
    )
    with_future = baseline_forecast("ETF", pd.concat([series, future]), [20], FORECAST_DATE, "r")[0]
    assert with_future == baseline_forecast("ETF", series, [20], FORECAST_DATE, "r")[0]
