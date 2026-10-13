from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.features.drawdown import drawdown, rolling_max_drawdown
from etf_cockpit.features.liquidity import liquidity_score
from etf_cockpit.features.returns import daily_log_returns, horizon_log_returns
from etf_cockpit.features.trend import simple_moving_average
from etf_cockpit.features.volatility import ewma_volatility, realised_volatility


# Broad-market anchor for relative strength when no canonical benchmark evidence is bound:
# the accumulating FTSE All-World tracker, whose adjusted close is a total-return series.
RELATIVE_STRENGTH_FALLBACK_ANCHOR = "VWCE"


# Bumped whenever a feature formula changes so derived feature caches written by an older
# algorithm are never reused (the cache key binds this version).
FEATURE_ALGORITHM_VERSION = "features-2"

# Scale of a normal distribution from the mean absolute deviation (sqrt(pi / 2)); used only when
# more than half of the values are equal and the median absolute deviation collapses to zero.
_MEAN_ABS_DEVIATION_SCALE = 1.2533


def robust_zscore(values: pd.Series) -> pd.Series:
    """Robust z-score clipped to +-3; unavailable (all NaN) when no finite scale exists.

    A zero MAD (over half of the values equal) falls back to the scaled mean absolute
    deviation so real outliers keep their sign; a constant series has no scale and is
    unavailable rather than neutral.
    """

    median = values.median(skipna=True)
    deviation = (values - median).abs()
    denom = 1.4826 * deviation.median(skipna=True)
    if not np.isfinite(denom) or denom == 0:
        denom = _MEAN_ABS_DEVIATION_SCALE * deviation.mean(skipna=True)
    if not np.isfinite(denom) or denom == 0:
        return pd.Series(float("nan"), index=values.index)
    return ((values - median) / denom).clip(-3, 3)


def compute_features(prices: pd.DataFrame, benchmark_etf_id: str | None = None) -> pd.DataFrame:
    frame = prices.copy().sort_values(["etf_id", "date"])
    if frame.empty:
        return pd.DataFrame(columns=["date", "etf_id"])
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    # One row per (instrument, date): an equal duplicate must not shift every rolling horizon by a row.
    # Conflicting duplicates are blocked by price validation before features are computed.
    frame = frame.drop_duplicates(["etf_id", "date"], keep="last")
    feature_frames: list[pd.DataFrame] = []
    benchmark_prices: pd.Series | None = None

    if benchmark_etf_id and benchmark_etf_id in set(frame["etf_id"]):
        benchmark_prices = frame[frame["etf_id"] == benchmark_etf_id].set_index("date")["adjusted_close"].astype(float)

    for etf_id, group in frame.groupby("etf_id", sort=False):
        group = group.sort_values("date").copy()
        price = group["adjusted_close"].astype(float)
        log_ret = daily_log_returns(price)
        sma_100 = simple_moving_average(price, 100)
        sma_200 = simple_moving_average(price, 200)
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
                "sma_50": simple_moving_average(price, 50).values,
                "sma_100": sma_100.values,
                "sma_200": sma_200.values,
                "trend_100": (price > sma_100).where(sma_100.notna()).astype(float).values,
                "trend_200": (price > sma_200).where(sma_200.notna()).astype(float).values,
                "trend_slope": (sma_100 / sma_200 - 1).values,
                "vol_20d_ann": realised_volatility(log_ret, 20).values,
                "vol_60d_ann": realised_volatility(log_ret, 60).values,
                "vol_120d_ann": realised_volatility(log_ret, 120).values,
                "ewma_vol_ann": ewma_volatility(log_ret).values,
                "drawdown_current": drawdown(price).values,
                "drawdown_60d_max": rolling_max_drawdown(price, 60).values,
                "drawdown_120d_max": rolling_max_drawdown(price, 120).values,
                "liquidity_score": liquidity_score(group["volume"]).values,
                "last_price": price.values,
            }
        )
        if benchmark_prices is not None and etf_id == benchmark_etf_id:
            # The benchmark measured against itself carries no information: unavailable, not neutral.
            out["relative_strength_60d"] = float("nan")
            out["relative_strength_120d"] = float("nan")
        elif benchmark_prices is not None:
            dates = pd.Index(group["date"].values)
            out["relative_strength_60d"] = _relative_strength(price.values, dates, benchmark_prices, 60)
            out["relative_strength_120d"] = _relative_strength(price.values, dates, benchmark_prices, 120)
        else:
            out["relative_strength_60d"] = out["return_60d_log"]
            out["relative_strength_120d"] = out["momentum_120d"]
        feature_frames.append(out)

    result = pd.concat(feature_frames, ignore_index=True)
    return result.sort_values(["date", "etf_id"]).reset_index(drop=True)


# Exchanges close on different days; a benchmark close is reused for at most this many
# calendar days after it was observed (never a later close, so no look-ahead).
BENCHMARK_AS_OF_MAX_GAP_DAYS = 5


def _relative_strength(prices: np.ndarray, dates: pd.Index, benchmark: pd.Series, horizon: int) -> np.ndarray:
    """Own horizon log return minus the benchmark return over the same calendar window.

    The window starts on the instrument's own observation ``horizon`` sessions back; the
    benchmark is read as-of that same start and end instant, so exchanges with different
    holiday calendars are never compared over mismatched dates.
    """

    own = pd.Series(prices, dtype=float)
    own_return = np.log(own / own.shift(horizon)).to_numpy()
    start_dates = pd.Series(list(dates)).shift(horizon)
    valid = start_dates.notna().to_numpy()
    benchmark_end = _benchmark_as_of(benchmark, dates).to_numpy(dtype=float)
    benchmark_start = np.full(len(dates), np.nan)
    if valid.any():
        benchmark_start[valid] = _benchmark_as_of(benchmark, pd.Index(start_dates[valid])).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        benchmark_return = np.log(benchmark_end / benchmark_start)
    return own_return - benchmark_return


def _benchmark_as_of(benchmark: pd.Series, dates: pd.Index) -> pd.Series:
    """Benchmark value at its latest observation on or before each date (as-of join)."""

    source = benchmark.dropna()
    source.index = pd.to_datetime(source.index)
    source = source[~source.index.duplicated(keep="last")].sort_index()
    target = pd.to_datetime(pd.Index(dates))
    if source.empty:
        return pd.Series(float("nan"), index=dates)
    aligned = source.reindex(target, method="ffill", tolerance=pd.Timedelta(days=BENCHMARK_AS_OF_MAX_GAP_DAYS))
    return pd.Series(aligned.values, index=dates)


def latest_features(features: pd.DataFrame, as_of_date: date | None = None) -> pd.DataFrame:
    frame = features.copy()
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    if as_of_date is not None:
        frame = frame[frame["date"] <= as_of_date]
    return frame.sort_values("date").groupby("etf_id", as_index=False).tail(1).reset_index(drop=True)
