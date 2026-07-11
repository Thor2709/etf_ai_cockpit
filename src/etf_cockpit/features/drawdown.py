from __future__ import annotations

import pandas as pd


def drawdown(prices: pd.Series) -> pd.Series:
    running_peak = prices.astype(float).cummax()
    return prices.astype(float) / running_peak - 1.0


def rolling_max_drawdown(prices: pd.Series, window: int) -> pd.Series:
    dd = drawdown(prices)
    return dd.rolling(window, min_periods=window).min()
