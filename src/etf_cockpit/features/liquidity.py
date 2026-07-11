from __future__ import annotations

import numpy as np
import pandas as pd


def liquidity_score(volume: pd.Series, window: int = 60) -> pd.Series:
    rolling = volume.astype(float).rolling(window, min_periods=20).median()
    z = np.log1p(volume.astype(float)) - np.log1p(rolling)
    return z.clip(-3, 3) / 3
