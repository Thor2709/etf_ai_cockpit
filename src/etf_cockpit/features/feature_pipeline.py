from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.features.drawdown import drawdown, rolling_max_drawdown
from etf_cockpit.features.liquidity import liquidity_score
from etf_cockpit.features.returns import daily_log_returns, horizon_log_returns
from etf_cockpit.features.trend import simple_moving_average
from etf_cockpit.features.volatility import ewma_volatility, realised_volatility


def robust_zscore(values: pd.Series) -> pd.Series:
    median = values.median(skipna=True)
    mad = (values - median).abs().median(skipna=True)
    denom = 1.4826 * mad
    if not np.isfinite(denom) or denom == 0:
        return pd.Series(0.0, index=values.index)
    return ((values - median) / denom).clip(-3, 3)


def compute_features(prices: pd.DataFrame, benchmark_etf_id: str | None = None) -> pd.DataFrame:
    frame = prices.copy().sort_values(["etf_id", "date"])
    if frame.empty:
        return pd.DataFrame(columns=["date", "etf_id"])
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    feature_frames: list[pd.DataFrame] = []
    benchmark_returns: pd.Series | None = None

    if benchmark_etf_id and benchmark_etf_id in set(frame["etf_id"]):
        benchmark = frame[frame["etf_id"] == benchmark_etf_id].set_index("date")["adjusted_close"]
        benchmark_returns = horizon_log_returns(benchmark, 60)

    for etf_id, group in frame.groupby("etf_id", sort=False):
        group = group.sort_values("date").copy()
        price = group["adjusted_close"].astype(float)
        log_ret = daily_log_returns(price)
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
                "sma_100": simple_moving_average(price, 100).values,
                "sma_200": simple_moving_average(price, 200).values,
                "trend_100": (price > simple_moving_average(price, 100)).astype(float).values,
                "trend_200": (price > simple_moving_average(price, 200)).astype(float).values,
                "trend_slope": (simple_moving_average(price, 100) / simple_moving_average(price, 200) - 1).values,
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
        if benchmark_returns is not None:
            own_returns = pd.Series(out["return_60d_log"].values, index=group["date"])
            relative = own_returns - benchmark_returns.reindex(own_returns.index)
            out["relative_strength_60d"] = relative.values
            own_returns_120 = pd.Series(horizon_log_returns(price, 120).values, index=group["date"])
            bench_price = frame[frame["etf_id"] == benchmark_etf_id].set_index("date")["adjusted_close"]
            bench_120 = horizon_log_returns(bench_price, 120)
            out["relative_strength_120d"] = (own_returns_120 - bench_120.reindex(own_returns_120.index)).values
        else:
            out["relative_strength_60d"] = out["return_60d_log"]
            out["relative_strength_120d"] = out["momentum_120d"]
        feature_frames.append(out)

    result = pd.concat(feature_frames, ignore_index=True)
    return result.sort_values(["date", "etf_id"]).reset_index(drop=True)


def latest_features(features: pd.DataFrame, as_of_date: date | None = None) -> pd.DataFrame:
    frame = features.copy()
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    if as_of_date is not None:
        frame = frame[frame["date"] <= as_of_date]
    return frame.sort_values("date").groupby("etf_id", as_index=False).tail(1).reset_index(drop=True)
