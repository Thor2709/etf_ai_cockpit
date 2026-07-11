from __future__ import annotations

import math

import pandas as pd

from etf_cockpit.features.drawdown import drawdown, rolling_max_drawdown
from etf_cockpit.features.momentum import momentum
from etf_cockpit.features.returns import daily_log_returns, horizon_log_returns
from etf_cockpit.features.volatility import realised_volatility


def test_log_returns_use_adjusted_close_series() -> None:
    adjusted = pd.Series([100.0, 105.0, 110.25])
    returns = daily_log_returns(adjusted)
    assert math.isclose(returns.iloc[1], math.log(1.05), rel_tol=1e-12)
    assert math.isclose(returns.iloc[2], math.log(1.05), rel_tol=1e-12)


def test_momentum_and_horizon_return_match() -> None:
    prices = pd.Series([100.0, 101.0, 103.0, 106.0])
    assert math.isclose(momentum(prices, 3).iloc[-1], horizon_log_returns(prices, 3).iloc[-1])


def test_volatility_and_drawdown_outputs() -> None:
    prices = pd.Series([100, 110, 105, 120, 90, 95], dtype=float)
    returns = daily_log_returns(prices)
    assert realised_volatility(returns, 3).dropna().iloc[-1] > 0
    assert drawdown(prices).iloc[-2] == -0.25
    assert rolling_max_drawdown(prices, 3).dropna().iloc[-1] <= -0.25
