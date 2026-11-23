"""S7a: the compiled etf_kernels are bit-exact against the numpy/pandas forms they replaced (kept here as oracles)."""

from dataclasses import replace

import numpy as np
import pandas as pd

import etf_kernels
from etf_cockpit.features.crowding import build_correlation_clusters, correlation_matrix
from etf_cockpit.features.drawdown import rolling_max_drawdown


def _max_drawdown_oracle(prices: pd.Series, window: int) -> pd.Series:
    """The replaced numpy sliding-window form."""

    values = prices.astype(float).to_numpy()
    out = np.full(len(values), np.nan)
    if len(values) >= window:
        windows = np.lib.stride_tricks.sliding_window_view(values, window)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[window - 1:] = (windows / np.maximum.accumulate(windows, axis=1) - 1.0).min(axis=1)
    return pd.Series(out, index=prices.index, name=prices.name)


def _prices(seed: int, n: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n))), index=pd.bdate_range("2020-01-01", periods=n), name="px")


def test_rolling_max_drawdown_kernel_equals_the_numpy_oracle():
    prices = _prices(11, 400)
    prices.iloc[[0, 5, 150, 151, 390]] = np.nan
    edge = pd.Series([0.0, 0.0, 1.0, np.inf, 2.0, -1.0, 3.0], name="edge")
    for series in (prices, prices.iloc[:59], prices.iloc[:60], prices.iloc[:1], prices.iloc[:0], edge):
        for window in (1, 3, 60, 120):
            pd.testing.assert_series_equal(rolling_max_drawdown(series, window), _max_drawdown_oracle(series, window), check_exact=True)


def test_rolling_max_drawdown_kernel_keeps_groups_apart():
    parts = [_prices(seed, n) for seed, n in ((1, 130), (2, 0), (3, 61), (4, 7))]
    values = np.concatenate([part.to_numpy() for part in parts])
    offsets = np.cumsum([0] + [len(part) for part in parts]).astype(np.int64)
    expected = np.concatenate([_max_drawdown_oracle(part, 60).to_numpy() for part in parts])
    np.testing.assert_array_equal(etf_kernels.rolling_max_drawdown(values, offsets, 60), expected)


def test_nancorr_kernel_equals_pandas_corr():
    rng = np.random.default_rng(5)
    base = rng.normal(0.0, 0.01, 130)
    returns = pd.DataFrame({name: base * scale + rng.normal(0.0, noise, 130) for name, scale, noise in (("A", 1.0, 0.002), ("B", 0.5, 0.01), ("C", -1.0, 0.004), ("D", 0.0, 0.01))})
    returns.iloc[[0, 7, 8, 90], 0] = np.nan
    returns.iloc[40:, 1] = np.nan  # too few pairs for min_periods
    returns.iloc[3, 2] = np.inf  # pandas skips non-finite values
    returns["E"] = 0.25  # zero variance: no divisor
    for min_periods in (1, 20, 60):
        oracle = returns.corr(min_periods=min_periods).to_numpy()
        for threads in (1, 3):
            np.testing.assert_array_equal(etf_kernels.nancorr(np.ascontiguousarray(returns.to_numpy()), min_periods, threads), oracle)
    assert etf_kernels.nancorr(np.empty((5, 0)), 20, 1).shape == (0, 0)


def test_correlation_clusters_are_unchanged_by_the_nancorr_kernel():
    rng = np.random.default_rng(9)
    common = np.cumsum(rng.normal(0.0, 0.01, 150))
    prices = pd.DataFrame(
        {name: 100.0 * np.exp(common * scale + np.cumsum(rng.normal(0.0, noise, 150))) for name, scale, noise in (("A", 1.0, 0.001), ("B", 1.0, 0.002), ("C", 0.2, 0.01), ("D", -1.0, 0.001))},
        index=pd.date_range("2026-01-01", periods=150, freq="D"),
    )
    prices.iloc[[10, 11, 70], 2] = np.nan
    built = correlation_matrix(prices, window=120)
    oracle = replace(built, correlations=built.returns.corr(min_periods=built.min_pair_samples).to_numpy(dtype=float))
    np.testing.assert_array_equal(built.correlations, oracle.correlations)
    report = build_correlation_clusters(prices, window=120, matrix=built)
    assert report == build_correlation_clusters(prices, window=120, matrix=oracle)
    assert {row.cluster_id for row in report.rows} == {"cluster_A_B", "cluster_C", "cluster_D"}
