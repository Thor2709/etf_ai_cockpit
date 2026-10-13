from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.core.types import ForecastResult
from etf_cockpit.features.returns import daily_log_returns
from etf_cockpit.models.calibration import adjusted_log_return_target
from etf_cockpit.models.distribution_store import (
    QUANTILE_METHOD_NORMAL,
    complete_return_quantiles,
    derived_quantile_columns,
    history_coverage_ratio,
)

MIN_BASELINE_OBSERVATIONS = 20


def baseline_forecast(
    etf_id: str,
    adjusted_close: pd.Series,
    horizons: list[int],
    forecast_date: date,
    run_id: str,
    benchmark_returns: pd.Series | None = None,
) -> list[ForecastResult]:
    # Only history known at the forecast date may enter the estimates.
    adjusted_close = adjusted_close.loc[pd.to_datetime(adjusted_close.index, utc=True).date <= forecast_date]
    log_returns = daily_log_returns(adjusted_close)
    log_returns = log_returns[np.isfinite(log_returns)]
    if len(log_returns) < MIN_BASELINE_OBSERVATIONS:
        return []
    # Conservative shrinkage toward no edge.
    mean = float(log_returns.tail(180).mean() * 0.35)
    vol = float(log_returns.tail(60).std() * np.sqrt(252))
    coverage = history_coverage_ratio(len(log_returns))
    results: list[ForecastResult] = []
    benchmark_mean = float(benchmark_returns.tail(180).mean() * 0.35) if benchmark_returns is not None and not benchmark_returns.empty else 0.0
    for horizon in horizons:
        expected = mean * horizon
        expected_excess = expected - benchmark_mean * horizon
        horizon_vol = vol * np.sqrt(horizon / 252) if vol else 0.0
        q10 = expected - 1.2816 * horizon_vol
        q90 = expected + 1.2816 * horizon_vol
        results.append(
            ForecastResult(
                run_id=run_id,
                model_name="baseline",
                model_version="momentum_shrunk_v1",
                etf_id=etf_id,
                forecast_date=forecast_date,
                horizon_days=horizon,
                target_id=adjusted_log_return_target(horizon).target_id,
                expected_return=expected,
                expected_excess_return=expected_excess,
                q10_return=q10,
                q50_return=expected,
                q90_return=q90,
                **derived_quantile_columns(complete_return_quantiles(q10, expected, q90), QUANTILE_METHOD_NORMAL),
                coverage_ratio=coverage,
                forecast_vol=horizon_vol,
                # Logistic scores are heuristics: no out-of-sample calibration backs them, so the
                # calibrated-probability fields stay unavailable (None).
                heuristic_probability_positive=float(1 / (1 + np.exp(-expected / max(horizon_vol, 1e-6)))),
                heuristic_probability_beat_benchmark=float(1 / (1 + np.exp(-expected_excess / max(horizon_vol, 1e-6)))),
                status="ok",
            )
        )
    return results
