from __future__ import annotations

import pandas as pd

from etf_cockpit.features.returns import horizon_log_returns


def momentum(prices: pd.Series, horizon: int) -> pd.Series:
    return horizon_log_returns(prices, horizon)


def weighted_momentum(frame: pd.DataFrame) -> pd.Series:
    return (
        0.15 * frame["momentum_20d"]
        + 0.35 * frame["momentum_60d"]
        + 0.35 * frame["momentum_120d"]
        + 0.15 * frame["momentum_180d"]
    )
