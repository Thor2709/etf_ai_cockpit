from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR


def realised_volatility(log_returns: pd.Series, window: int) -> pd.Series:
    return log_returns.astype(float).rolling(window, min_periods=window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def ewma_volatility(log_returns: pd.Series, lambda_: float = 0.97) -> pd.Series:
    variance = log_returns.fillna(0).pow(2).ewm(alpha=1 - lambda_, adjust=False).mean()
    return np.sqrt(variance * TRADING_DAYS_PER_YEAR)
