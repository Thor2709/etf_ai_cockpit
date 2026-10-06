from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.core.types import ForecastResult
from etf_cockpit.features.returns import daily_log_returns


def baseline_forecast(
    etf_id: str,
    adjusted_close: pd.Series,
    horizons: list[int],
    forecast_date: date,
    run_id: str,
    benchmark_returns: pd.Series | None = None,
) -> list[ForecastResult]:
    log_returns = daily_log_returns(adjusted_close).dropna()
    if log_returns.empty:
        mean = 0.0
        vol = 0.0
    else:
        # Conservative shrinkage toward no edge.
        mean = float(log_returns.tail(180).mean() * 0.35)
        vol = float(log_returns.tail(60).std() * np.sqrt(252))
    results: list[ForecastResult] = []
    benchmark_mean = float(benchmark_returns.tail(180).mean() * 0.35) if benchmark_returns is not None and not benchmark_returns.empty else 0.0
    for horizon in horizons:
        expected = mean * horizon
        expected_excess = expected - benchmark_mean * horizon
        horizon_vol = vol * np.sqrt(horizon / 252) if vol else 0.0
        results.append(
            ForecastResult(
                run_id=run_id,
                model_name="baseline",
                model_version="momentum_shrunk_v1",
                etf_id=etf_id,
                forecast_date=forecast_date,
                horizon_days=horizon,
                expected_return=expected,
                expected_excess_return=expected_excess,
                q10_return=expected - 1.28 * horizon_vol,
                q50_return=expected,
                q90_return=expected + 1.28 * horizon_vol,
                forecast_vol=horizon_vol,
                prob_positive_return=float(1 / (1 + np.exp(-expected / max(horizon_vol, 1e-6)))),
                prob_beat_benchmark=float(1 / (1 + np.exp(-expected_excess / max(horizon_vol, 1e-6)))),
                status="ok",
            )
        )
    return results
