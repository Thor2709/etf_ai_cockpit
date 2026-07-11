from __future__ import annotations

import numpy as np
import pandas as pd


def daily_log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices.astype(float) / prices.astype(float).shift(1))


def horizon_log_returns(prices: pd.Series, horizon: int) -> pd.Series:
    return np.log(prices.astype(float) / prices.astype(float).shift(horizon))


def forward_log_returns(prices: pd.Series, horizon: int) -> pd.Series:
    return np.log(prices.astype(float).shift(-horizon) / prices.astype(float))


def excess_return(asset_returns: pd.Series, benchmark_returns: pd.Series) -> pd.Series:
    aligned = pd.concat([asset_returns, benchmark_returns], axis=1).dropna()
    result = asset_returns.copy() * np.nan
    result.loc[aligned.index] = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    return result
