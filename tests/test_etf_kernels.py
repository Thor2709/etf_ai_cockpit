"""S7a: the compiled etf_kernels are bit-exact against the numpy/pandas forms they replaced (kept here as oracles)."""

from dataclasses import replace

import numpy as np
import pandas as pd

import etf_kernels
from etf_cockpit.features.crowding import build_correlation_clusters, correlation_matrix
from etf_cockpit.features.drawdown import rolling_max_drawdown
from etf_cockpit.features.feature_pipeline import _benchmark_as_of, compute_features
from etf_cockpit.features.momentum import momentum, weighted_momentum
from etf_cockpit.features.returns import daily_log_returns, horizon_log_returns


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


def test_rolling_kernels_equal_pandas_per_group():
    rng = np.random.default_rng(3)
    parts = [pd.Series(rng.normal(0.0, 0.02, n)) for n in (90, 0, 1, 25)]
    parts[0].iloc[[3, 4, 40]] = np.nan
    parts[0].iloc[50:58] = 0.01  # a run of equal values
    parts[0].iloc[60] = np.inf  # pandas rolling and ewm treat inf as missing
    parts[0].iloc[70:75] = -0.02
    parts[3].iloc[5] = -np.inf
    values = np.concatenate([part.to_numpy() for part in parts])
    offsets = np.cumsum([0] + [len(part) for part in parts]).astype(np.int64)

    def per_group(func):
        return np.concatenate([func(part).to_numpy() for part in parts])

    for window in (1, 2, 3, 20, 50):
        np.testing.assert_array_equal(etf_kernels.rolling_mean(values, offsets, window), per_group(lambda s: s.rolling(window, min_periods=window).mean()))
        np.testing.assert_array_equal(etf_kernels.rolling_std(values, offsets, window), per_group(lambda s: s.rolling(window, min_periods=window).std()))
    for window, min_periods in ((60, 20), (4, 1), (5, 5)):
        np.testing.assert_array_equal(
            etf_kernels.rolling_median(values, offsets, window, min_periods), per_group(lambda s: s.rolling(window, min_periods=min_periods).median())
        )
    for alpha in (0.03, 0.5, 1.0):
        com = (1 - alpha) / alpha
        np.testing.assert_array_equal(
            etf_kernels.ewm_mean(values, offsets, 1.0 / (1.0 + com)), per_group(lambda s: s.ewm(alpha=alpha, adjust=False, ignore_na=True).mean())
        )


def _compute_features_oracle(prices: pd.DataFrame, benchmark_etf_id: str | None = None) -> pd.DataFrame:
    """The replaced per-instrument pandas loop of ``compute_features``."""

    def sma(price, window):
        return price.rolling(window, min_periods=window).mean()

    def vol(log_ret, window):
        return log_ret.rolling(window, min_periods=window).std() * np.sqrt(252)

    def liquidity(volume, close):
        if close is None:
            return pd.Series(float("nan"), index=volume.index, dtype=float)
        px, vv = pd.to_numeric(close, errors="coerce").astype(float), pd.to_numeric(volume, errors="coerce").astype(float)
        turnover = (px * vv).where(np.isfinite(px) & np.isfinite(vv) & (px > 0) & (vv >= 0))
        return (np.log1p(turnover) - np.log1p(turnover.rolling(60, min_periods=20).median())).clip(-3, 3) / 3

    def relative_strength(values, dates, benchmark, horizon):
        own = pd.Series(values, dtype=float)
        start_dates = pd.Series(list(dates)).shift(horizon)
        valid = start_dates.notna().to_numpy()
        end = _benchmark_as_of(benchmark, dates).to_numpy(dtype=float)
        start = np.full(len(dates), np.nan)
        if valid.any():
            start[valid] = _benchmark_as_of(benchmark, pd.Index(start_dates[valid])).to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.log(own / own.shift(horizon)).to_numpy() - np.log(end / start)

    frame = prices.copy().sort_values(["etf_id", "date"])
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.drop_duplicates(["etf_id", "date"], keep="last")
    benchmark = None
    if benchmark_etf_id and benchmark_etf_id in set(frame["etf_id"]):
        benchmark = frame[frame["etf_id"] == benchmark_etf_id].set_index("date")["adjusted_close"].astype(float)
    frames = []
    for etf_id, group in frame.groupby("etf_id", sort=False):
        group = group.sort_values("date").copy()
        price = group["adjusted_close"].astype(float)
        log_ret = daily_log_returns(price)
        sma_100, sma_200 = sma(price, 100), sma(price, 200)
        out = pd.DataFrame(
            {
                "date": group["date"].values,
                "etf_id": etf_id,
                "return_1d_log": log_ret.values,
                "return_5d_log": horizon_log_returns(price, 5).values,
                "return_20d_log": horizon_log_returns(price, 20).values,
                "return_60d_log": horizon_log_returns(price, 60).values,
                "momentum_20d": horizon_log_returns(price, 20).values,
                "momentum_60d": horizon_log_returns(price, 60).values,
                "momentum_120d": horizon_log_returns(price, 120).values,
                "momentum_180d": horizon_log_returns(price, 180).values,
                "momentum_252d_skip_20d": momentum(price, 252, skip=20).values,
                "sma_50": sma(price, 50).values,
                "sma_100": sma_100.values,
                "sma_200": sma_200.values,
                "trend_100": (price > sma_100).where(sma_100.notna()).astype(float).values,
                "trend_200": (price > sma_200).where(sma_200.notna()).astype(float).values,
                "trend_slope": (sma_100 / sma_200 - 1).values,
                "vol_20d_ann": vol(log_ret, 20).values,
                "vol_60d_ann": vol(log_ret, 60).values,
                "vol_120d_ann": vol(log_ret, 120).values,
                "ewma_vol_ann": np.sqrt(log_ret.pow(2).ewm(alpha=1 - 0.97, adjust=False, ignore_na=True).mean() * 252).where(log_ret.notna()).values,
                "drawdown_current": (price / price.cummax() - 1.0).values,
                "drawdown_60d_max": _max_drawdown_oracle(price, 60).values,
                "drawdown_120d_max": _max_drawdown_oracle(price, 120).values,
                "liquidity_score": liquidity(group["volume"], group["close"] if "close" in group.columns else None).values,
                "last_price": price.values,
            }
        )
        out["weighted_momentum_vol_scaled"] = weighted_momentum(out, volatility=out["vol_60d_ann"])
        if benchmark is not None and etf_id == benchmark_etf_id:
            out["relative_strength_60d"] = float("nan")
            out["relative_strength_120d"] = float("nan")
        elif benchmark is not None:
            dates = pd.Index(group["date"].values)
            out["relative_strength_60d"] = relative_strength(price.values, dates, benchmark, 60)
            out["relative_strength_120d"] = relative_strength(price.values, dates, benchmark, 120)
        else:
            out["relative_strength_60d"] = out["return_60d_log"]
            out["relative_strength_120d"] = out["momentum_120d"]
        frames.append(out)
    return pd.concat(frames, ignore_index=True).sort_values(["date", "etf_id"]).reset_index(drop=True)


def test_compute_features_equals_the_per_instrument_oracle():
    rng = np.random.default_rng(21)
    rows = []
    for etf_id, n, start in (("VWCE", 320, "2023-01-02"), ("AAA", 300, "2023-01-09"), ("BBB", 140, "2023-03-01"), ("CCC", 30, "2023-06-01")):
        price = 50.0 * np.exp(np.cumsum(rng.normal(0.0, 0.015, n)))
        rows.append(
            pd.DataFrame(
                {"date": pd.bdate_range(start, periods=n), "etf_id": etf_id, "adjusted_close": price, "close": price * 1.01, "volume": rng.integers(0, 5000, n).astype(float)}
            )
        )
    prices = pd.concat(rows, ignore_index=True)
    prices.loc[[10, 400, 401, 700], "adjusted_close"] = np.nan
    prices.loc[[20, 650], "volume"] = np.nan
    prices = pd.concat([prices, prices.iloc[[5, 500]]]).sample(frac=1.0, random_state=4)  # equal duplicates, shuffled rows
    for benchmark in ("VWCE", None, "MISSING"):
        pd.testing.assert_frame_equal(compute_features(prices, benchmark_etf_id=benchmark), _compute_features_oracle(prices, benchmark), check_exact=True)
    no_close = prices.drop(columns=["close"])
    pd.testing.assert_frame_equal(compute_features(no_close, "VWCE"), _compute_features_oracle(no_close, "VWCE"), check_exact=True)
