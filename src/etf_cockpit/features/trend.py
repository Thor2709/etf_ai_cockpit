from __future__ import annotations

import etf_kernels
import numpy as np
import pandas as pd


def simple_moving_average(prices: pd.Series, window: int, *, offsets: np.ndarray | None = None) -> pd.Series:
    """pandas ``rolling(window, min_periods=window).mean()``, computed by the compiled kernel. ``offsets`` splits a frame sorted by (id, date) into instrument groups ``[offsets[g], offsets[g + 1])``."""

    values = np.ascontiguousarray(prices.astype(float).to_numpy())
    bounds = np.array([0, len(values)], dtype=np.int64) if offsets is None else offsets
    return pd.Series(etf_kernels.rolling_mean(values, bounds, window), index=prices.index, name=prices.name)
