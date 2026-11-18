"""Shadow volatility challenger: GJR-GARCH(1,1) against the EWMA baseline.

Both models forecast the variance of the ``horizon``-session log return from
data strictly before the forecast date. Scoring is QLIKE on variance against
the realised-variance proxy (sum of squared daily log returns over the same
sessions), out of sample and on the same dates for every model. ``arch`` is an
optional extra: it is imported lazily and its absence is ``unavailable``,
distinct from a GJR-GARCH non-convergence, which returns the EWMA value with a
``warning`` status.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd

from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR
from etf_cockpit.features.volatility import ewma_volatility

VARIANCE_EPSILON = 1e-12
_RETURN_SCALE = 100.0  # percent returns keep the optimiser well conditioned
_MODELS = ("ewma", "gjr_garch")


class VarianceForecast(NamedTuple):
    variance: float
    status: str  # "ok" | "warning" | "unavailable"
    reason: str = ""


def ewma_variance_forecast(log_returns: pd.Series, horizon: int) -> float:
    daily_vol = float(ewma_volatility(log_returns).iloc[-1])
    return horizon * daily_vol**2 / TRADING_DAYS_PER_YEAR


def gjr_garch_variance_forecast(log_returns: pd.Series, horizon: int) -> VarianceForecast:
    try:
        from arch import arch_model
    except ImportError:
        return VarianceForecast(float("nan"), "unavailable", "arch is not installed")
    fallback = ewma_variance_forecast(log_returns, horizon)
    try:
        model = arch_model(log_returns * _RETURN_SCALE, mean="Zero", vol="GARCH", p=1, o=1, q=1, rescale=False)
        result = model.fit(disp="off", show_warning=False)
        variance = float(result.forecast(horizon=horizon, reindex=False).variance.to_numpy()[-1].sum())
        variance /= _RETURN_SCALE**2
        failure = "" if result.convergence_flag == 0 else "optimiser did not converge"
    except (ValueError, np.linalg.LinAlgError) as exc:
        variance, failure = float("nan"), f"fit failed: {exc}"
    if not failure and not (np.isfinite(variance) and variance > 0.0):
        failure = "non-finite variance forecast"
    if failure:
        return VarianceForecast(fallback, "warning", f"GJR-GARCH {failure}; EWMA value used")
    return VarianceForecast(variance, "ok")


def qlike(forecast_variance: np.ndarray, realised_variance: np.ndarray) -> float:
    """Mean QLIKE on variance; both arguments are floored at ``VARIANCE_EPSILON``."""
    ratio = np.maximum(realised_variance, VARIANCE_EPSILON) / np.maximum(forecast_variance, VARIANCE_EPSILON)
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def _row(model: str, horizon: int, n: int, score: float, status: str, reason: str) -> dict[str, object]:
    return {"model": model, "horizon": horizon, "n_oos_points": n, "qlike": score, "status": status, "reason": reason}


def volatility_model_report(
    log_returns: pd.Series, horizon: int, *, min_train: int = 252, step: int = 21
) -> pd.DataFrame:
    """One row per model, scored by QLIKE over the same rolling-origin forecast dates."""
    returns = log_returns.astype(float)
    problem = ""
    if not np.isfinite(returns.to_numpy()).all():
        problem = "log returns contain missing or non-finite values"
    elif not (returns.index.is_monotonic_increasing and returns.index.is_unique):
        problem = "log return index is not strictly increasing and unique"
    elif len(returns) < min_train + horizon:
        problem = "insufficient history for the requested training window and horizon"
    if problem:
        return pd.DataFrame([_row(m, horizon, 0, float("nan"), "unavailable", problem) for m in _MODELS])

    squares = returns.to_numpy() ** 2
    origins = range(min_train, len(returns) - horizon + 1, step)
    realised = np.array([squares[t : t + horizon].sum() for t in origins])
    forecasts = {
        "ewma": [VarianceForecast(ewma_variance_forecast(returns.iloc[:t], horizon), "ok") for t in origins],
        "gjr_garch": [],
    }
    for t in origins:
        forecasts["gjr_garch"].append(gjr_garch_variance_forecast(returns.iloc[:t], horizon))
        if forecasts["gjr_garch"][-1].status == "unavailable":
            break

    rows = []
    for model in _MODELS:
        items = forecasts[model]
        unavailable = [f for f in items if f.status == "unavailable"]
        if unavailable:
            rows.append(_row(model, horizon, 0, float("nan"), "unavailable", unavailable[0].reason))
            continue
        warned = [f for f in items if f.status == "warning"]
        values = np.array([f.variance for f in items])
        rows.append(
            _row(model, horizon, len(items), qlike(values, realised), "warning" if warned else "ok",
                 f"{len(warned)} of {len(items)} origins used the EWMA fallback" if warned else "")
        )
    return pd.DataFrame(rows)
