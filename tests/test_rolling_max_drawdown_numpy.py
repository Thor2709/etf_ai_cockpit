"""S5: the numpy rolling max drawdown equals the former pandas rolling-apply form exactly."""

import numpy as np
import pandas as pd

from etf_cockpit.features.drawdown import rolling_max_drawdown


def _oracle(prices: pd.Series, window: int) -> pd.Series:
    """The replaced pandas form, kept only as the test oracle."""

    def worst(values: np.ndarray) -> float:
        return float((values / np.maximum.accumulate(values) - 1.0).min())

    return prices.astype(float).rolling(window, min_periods=window).apply(worst, raw=True)


def test_numpy_rolling_max_drawdown_equals_the_pandas_oracle():
    rng = np.random.default_rng(7)
    prices = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, 400))), index=pd.bdate_range("2020-01-01", periods=400), name="px")
    prices.iloc[[5, 150, 151, 390]] = np.nan
    for series in (prices, prices.iloc[:59], prices.iloc[:60], prices.iloc[:0]):
        for window in (1, 3, 60, 120):
            pd.testing.assert_series_equal(rolling_max_drawdown(series, window), _oracle(series, window), check_exact=True)
