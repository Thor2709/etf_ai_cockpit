from __future__ import annotations

import pandas as pd


def simple_moving_average(prices: pd.Series, window: int) -> pd.Series:
    return prices.astype(float).rolling(window, min_periods=window).mean()


def trend_filter(prices: pd.Series, window: int) -> pd.Series:
    sma = simple_moving_average(prices, window)
    return (prices.astype(float) > sma).astype(float)
