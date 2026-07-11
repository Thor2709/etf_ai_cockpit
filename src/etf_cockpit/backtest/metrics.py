from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR


def max_drawdown(equity: pd.Series) -> float:
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min())


def performance_metrics(equity: pd.Series, benchmark: pd.Series | None = None, turnover: float = 0.0, cost_drag: float = 0.0) -> dict[str, object]:
    equity = equity.dropna()
    if len(equity) < 3:
        return {
            "cagr": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "turnover": turnover,
            "cost_drag": cost_drag,
            "information_ratio": 0.0,
            **_payoff_diagnostics(pd.Series(dtype=float)),
        }
    returns = np.log(equity / equity.shift(1)).dropna()
    years = len(returns) / TRADING_DAYS_PER_YEAR
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / max(years, 1e-9)) - 1)
    vol = float(returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    sharpe = float((returns.mean() * TRADING_DAYS_PER_YEAR) / vol) if vol > 0 else 0.0
    downside = returns[returns < 0].std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    sortino = float((returns.mean() * TRADING_DAYS_PER_YEAR) / downside) if downside and downside > 0 else 0.0
    mdd = max_drawdown(equity)
    calmar = float(cagr / abs(mdd)) if mdd < 0 else 0.0
    information = 0.0
    if benchmark is not None and not benchmark.empty:
        aligned = pd.concat([returns, np.log(benchmark / benchmark.shift(1))], axis=1, sort=False).dropna()
        if not aligned.empty:
            active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
            tracking_error = active.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
            information = float(active.mean() * TRADING_DAYS_PER_YEAR / tracking_error) if tracking_error > 0 else 0.0
    return {
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": calmar,
        "turnover": turnover,
        "cost_drag": cost_drag,
        "information_ratio": information,
        **_payoff_diagnostics(returns),
    }


def _payoff_diagnostics(returns: pd.Series) -> dict[str, object]:
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    nonzero = clean[clean != 0]
    if nonzero.empty:
        return {
            "return_hit_rate": None,
            "average_win_return": None,
            "average_loss_return": None,
            "payoff_ratio": None,
            "expected_value_per_period": None,
            "payoff_asymmetry_warning": "insufficient_return_distribution",
        }
    wins = nonzero[nonzero > 0]
    losses = nonzero[nonzero < 0]
    hit_rate = float(len(wins) / len(nonzero))
    average_win = float(wins.mean()) if not wins.empty else None
    average_loss = abs(float(losses.mean())) if not losses.empty else None
    payoff_ratio = None
    if average_win is not None and average_loss is not None and average_loss > 0:
        payoff_ratio = float(average_win / average_loss)
    expected_value = None
    if average_win is not None and average_loss is not None:
        expected_value = float(hit_rate * average_win - (1.0 - hit_rate) * average_loss)
    warning = "balanced_or_positive_payoff"
    if average_loss is None:
        warning = "no_losing_periods_in_sample"
    elif average_win is None:
        warning = "no_winning_periods_in_sample"
    elif payoff_ratio is None:
        warning = "insufficient_return_distribution"
    elif payoff_ratio < 0.75:
        warning = "negative_payoff_asymmetry"
    elif hit_rate >= 0.60 and payoff_ratio < 1.0:
        warning = "high_hit_rate_low_payoff"
    return {
        "return_hit_rate": round(hit_rate, 4),
        "average_win_return": None if average_win is None else round(average_win, 6),
        "average_loss_return": None if average_loss is None else round(average_loss, 6),
        "payoff_ratio": None if payoff_ratio is None else round(payoff_ratio, 4),
        "expected_value_per_period": None if expected_value is None else round(expected_value, 6),
        "payoff_asymmetry_warning": warning,
    }
