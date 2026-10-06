from __future__ import annotations

import numpy as np
import pandas as pd


def drawdown(prices: pd.Series) -> pd.Series:
    running_peak = prices.astype(float).cummax()
    return prices.astype(float) / running_peak - 1.0


def rolling_max_drawdown(prices: pd.Series, window: int) -> pd.Series:
    """Worst peak-to-trough drawdown inside each trailing ``window`` of prices.

    The peak is the highest price within the same window, so an older peak
    outside the window never contaminates the result.  Windows with fewer than
    ``window`` observations or any missing price are NaN.
    """

    values = prices.astype(float)

    def _window_max_drawdown(window_prices: np.ndarray) -> float:
        return float((window_prices / np.maximum.accumulate(window_prices) - 1.0).min())

    return values.rolling(window, min_periods=window).apply(_window_max_drawdown, raw=True)
