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
    if any(isinstance(h, bool) or not np.isfinite(h) or h != int(h) or h <= 0 for h in horizons):
        raise ValueError("forecast horizons must be positive integers")
    # Only history known at the forecast date may enter the estimates.
    adjusted_close = adjusted_close.loc[pd.to_datetime(adjusted_close.index, utc=True).date <= forecast_date]
    adjusted_close = adjusted_close.sort_index()
    if isinstance(adjusted_close.index, pd.DatetimeIndex) and not adjusted_close.empty:
        # Legacy direct callers have no certified listing calendar. A week without
        # an endpoint is never accepted as current history; service callers apply
        # the stricter certified-session freshness check before this boundary.
        if (forecast_date - adjusted_close.index[-1].date()).days > 7:
            return []
        forecast_date = adjusted_close.index[-1].date()
    log_returns = daily_log_returns(adjusted_close)
    log_returns = log_returns[np.isfinite(log_returns)]
    if len(log_returns) < MIN_BASELINE_OBSERVATIONS:
        return []
    # Conservative shrinkage toward no edge.
    mean = float(log_returns.tail(180).mean() * 0.35)
    vol = float(log_returns.tail(60).std() * np.sqrt(252))
    coverage = history_coverage_ratio(len(log_returns))
    results: list[ForecastResult] = []
    benchmark_mean = None
    if benchmark_returns is not None and not benchmark_returns.empty:
        if isinstance(benchmark_returns.index, pd.DatetimeIndex):
            benchmark_returns = benchmark_returns.loc[benchmark_returns.index.date <= forecast_date]
            common = pd.concat([log_returns.tail(180).rename("asset"), benchmark_returns.rename("benchmark")], axis=1).reindex(log_returns.tail(180).index)
            if not common.empty and np.isfinite(common.to_numpy()).all():
                benchmark_mean = float(common["benchmark"].mean() * 0.35)
        else:
            # Explicit ordinal return vectors retain their legacy input contract.
            benchmark_mean = float(benchmark_returns.tail(min(180, len(log_returns))).mean() * 0.35)
    for horizon in horizons:
        expected = mean * horizon
        expected_excess = expected - benchmark_mean * horizon if benchmark_mean is not None else None
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
                heuristic_probability_beat_benchmark=(
                    float(1 / (1 + np.exp(-expected_excess / max(horizon_vol, 1e-6))))
                    if expected_excess is not None and expected_excess >= 0 else
                    float(np.exp(expected_excess / max(horizon_vol, 1e-6)) / (1 + np.exp(expected_excess / max(horizon_vol, 1e-6))))
                    if expected_excess is not None else None
                ),
                status="ok",
            )
        )
    return results
