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

    values = prices.astype(float).to_numpy()
    out = np.full(len(values), np.nan)
    if len(values) >= window:
        windows = np.lib.stride_tricks.sliding_window_view(values, window)
        # NaN propagates through the running peak and the min, so a window with a missing price stays NaN
        out[window - 1:] = (windows / np.maximum.accumulate(windows, axis=1) - 1.0).min(axis=1)
    return pd.Series(out, index=prices.index, name=prices.name)
