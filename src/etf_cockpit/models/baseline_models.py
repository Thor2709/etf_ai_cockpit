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
MAX_MISSING_SESSION_SHARE = 0.10
MAX_OBSERVED_GAP_DAYS = 7


def observed_history_is_sparse(series: pd.Series) -> bool:
    """True when observed dates are too gappy to be read as consecutive-session returns.

    Measured on non-NaN observations only: a gap over 7 calendar days or fewer than 90% of the
    weekdays between the first and last observation present.
    """
    days = pd.DatetimeIndex(series.dropna().index)
    if len(days) < 2:
        return False
    days = (days.tz_convert("UTC").tz_localize(None) if days.tz is not None else days).normalize()
    weekdays = len(pd.bdate_range(days[0], days[-1]))
    return bool(
        int(pd.Series(days).diff().dt.days.max()) > MAX_OBSERVED_GAP_DAYS
        or (weekdays > 1 and len(days) / weekdays < 1 - MAX_MISSING_SESSION_SHARE)
    )


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
        if (forecast_date - adjusted_close.index[-1].date()).days > MAX_OBSERVED_GAP_DAYS:
            return []
        # Sparse (e.g. weekly) observations would be read as daily returns and overscale horizons.
        if observed_history_is_sparse(adjusted_close):
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
    # No benchmark supplied keeps the legacy zero-benchmark contract (the service nulls relative
    # fields itself); a supplied benchmark that cannot be aligned to the training window gives None.
    benchmark_mean: float | None = 0.0
    if benchmark_returns is not None and not benchmark_returns.empty:
        benchmark_mean = None
        if isinstance(benchmark_returns.index, pd.DatetimeIndex):
            benchmark_returns = benchmark_returns.loc[benchmark_returns.index.date <= forecast_date]
            aligned = (
                benchmark_returns.reindex(log_returns.tail(180).index)
                if benchmark_returns.index.is_unique else None
            )
            if aligned is not None and np.isfinite(aligned.to_numpy(dtype=float)).all():
                benchmark_mean = float(aligned.mean() * 0.35)
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
