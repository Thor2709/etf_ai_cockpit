from __future__ import annotations

import numpy as np
import pandas as pd


def traded_turnover(price: pd.Series, volume: pd.Series) -> pd.Series:
    """Monetary turnover (quote-currency price x volume) per observation.

    ``price`` must be the unadjusted traded close paired with the volume as quoted: a share
    split rescales both and leaves turnover unchanged. Missing, non-finite, negative or
    non-positive price and negative or non-finite volume are unavailable (NaN), never
    clipped or zero-filled. Zero volume with a valid price is a real no-trade day (0).
    """

    px = pd.to_numeric(price, errors="coerce").astype(float)
    vol = pd.to_numeric(volume, errors="coerce").astype(float)
    valid = np.isfinite(px) & np.isfinite(vol) & (px > 0) & (vol >= 0)
    return (px * vol).where(valid)


def liquidity_score(
    volume: pd.Series,
    window: int = 60,
    *,
    price: pd.Series | None = None,
) -> pd.Series:
    """Liquidity z-score of log money turnover against its rolling median, clipped to [-1, 1].

    Share volume alone is not economically comparable across a split, so without a traded
    ``price`` the score is unavailable (all NaN) rather than a share-volume score. Invalid
    observations are unavailable and excluded from the rolling median.
    """

    if price is None:
        return pd.Series(float("nan"), index=volume.index, dtype=float)
    turnover = traded_turnover(price, volume)
    rolling = turnover.rolling(window, min_periods=20).median()
    z = np.log1p(turnover) - np.log1p(rolling)
    return z.clip(-3, 3) / 3
