from __future__ import annotations

import pandas as pd


def simple_moving_average(prices: pd.Series, window: int) -> pd.Series:
    return prices.astype(float).rolling(window, min_periods=window).mean()
