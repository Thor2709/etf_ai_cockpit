from __future__ import annotations

import etf_kernels
import numpy as np
import pandas as pd

from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR


def realised_volatility(log_returns: pd.Series, window: int, *, offsets: np.ndarray | None = None) -> pd.Series:
    """Annualised pandas ``rolling(window, min_periods=window).std()``, computed by the compiled kernel. ``offsets`` splits a frame sorted by (id, date) into instrument groups ``[offsets[g], offsets[g + 1])``."""

    values = np.ascontiguousarray(log_returns.astype(float).to_numpy())
    bounds = np.array([0, len(values)], dtype=np.int64) if offsets is None else offsets
    std = pd.Series(etf_kernels.rolling_std(values, bounds, window), index=log_returns.index, name=log_returns.name)
    return std * np.sqrt(TRADING_DAYS_PER_YEAR)


def ewma_volatility(log_returns: pd.Series, lambda_: float = 0.97, *, offsets: np.ndarray | None = None) -> pd.Series:
    """pandas ``ewm(alpha=1 - lambda_, adjust=False, ignore_na=True)`` variance, computed by the compiled kernel. ``offsets`` splits a frame sorted by (id, date) into instrument groups ``[offsets[g], offsets[g + 1])``."""

    alpha = 1 - lambda_
    if not 0 < alpha <= 1:
        raise ValueError("alpha must satisfy: 0 < alpha <= 1")
    centre_of_mass = (1 - alpha) / alpha  # pandas turns alpha into a centre of mass and back
    values = np.ascontiguousarray(log_returns.pow(2).astype(float).to_numpy())
    bounds = np.array([0, len(values)], dtype=np.int64) if offsets is None else offsets
    variance = pd.Series(etf_kernels.ewm_mean(values, bounds, 1.0 / (1.0 + centre_of_mass)), index=log_returns.index, name=log_returns.name)
    return np.sqrt(variance * TRADING_DAYS_PER_YEAR).where(log_returns.notna())
