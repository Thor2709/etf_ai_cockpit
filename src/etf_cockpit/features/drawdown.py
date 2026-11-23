from __future__ import annotations

import etf_kernels
import numpy as np
import pandas as pd


def drawdown(prices: pd.Series, *, offsets: np.ndarray | None = None) -> pd.Series:
    """Price over its running peak minus one. ``offsets`` splits a frame sorted by (id, date) into instrument groups ``[offsets[g], offsets[g + 1])``."""

    values = prices.astype(float)
    bounds = np.array([0, len(values)], dtype=np.int64) if offsets is None else offsets
    running_peak = values.groupby(np.repeat(np.arange(len(bounds) - 1), np.diff(bounds)), sort=False).cummax()
    return values / running_peak - 1.0


def rolling_max_drawdown(prices: pd.Series, window: int, *, offsets: np.ndarray | None = None) -> pd.Series:
    """Worst peak-to-trough drawdown inside each trailing ``window`` of prices.

    The peak is the highest price within the same window, so an older peak
    outside the window never contaminates the result.  Windows with fewer than
    ``window`` observations or any missing price are NaN. ``offsets`` splits a frame sorted by (id, date) into instrument groups ``[offsets[g], offsets[g + 1])``.
    """

    values = np.ascontiguousarray(prices.astype(float).to_numpy())
    out = etf_kernels.rolling_max_drawdown(values, np.array([0, len(values)], dtype=np.int64) if offsets is None else offsets, window)
    return pd.Series(out, index=prices.index, name=prices.name)
