from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.features.returns import horizon_log_returns


def momentum(prices: pd.Series, horizon: int, *, skip: int = 0) -> pd.Series:
    """Trailing log return from t-horizon to t-skip; skip never reads a future price."""
    if not 0 <= skip < horizon:
        raise ValueError("skip must be nonnegative and smaller than horizon")
    return horizon_log_returns(prices, horizon - skip).shift(skip)


def weighted_momentum(frame: pd.DataFrame, *, volatility: pd.Series | None = None) -> pd.Series:
    """Fixed live blend, optionally volatility-scaled for research only (B-04)."""
    result = (
        0.15 * frame["momentum_20d"]
        + 0.35 * frame["momentum_60d"]
        + 0.35 * frame["momentum_120d"]
        + 0.15 * frame["momentum_180d"]
    )
    if volatility is None:
        return result
    vol = pd.to_numeric(volatility, errors="coerce")
    scaled = result / vol.where(np.isfinite(vol) & (vol > 0))
    return scaled.where(np.isfinite(scaled))
