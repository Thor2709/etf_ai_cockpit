from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR


MIN_STRESS_OBSERVATIONS = 20
CONCENTRATION_THRESHOLD = 0.5
STRESS_QUANTILE = 0.75


def max_drawdown(equity: pd.Series) -> float:
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min())


def tail_event_diagnostics(
    equity: pd.Series,
    benchmark: pd.Series | None = None,
    *,
    volatility: pd.Series | None = None,
    regime: pd.Series | None = None,
) -> dict[str, object]:
    """Return deterministic, descriptive tail and loss-cluster evidence.

    ``benchmark`` is retained for API compatibility but is not used: benchmark
    tail dependence is outside this slice. Optional volatility and regime
    observations are only used when explicitly supplied; no regime is inferred
    from returns. Missing values are never filled.
    """

    del benchmark
    raw = _normalise_series(equity)
    observed_returns = _observed_returns(raw)
    returns = observed_returns.dropna()
    if returns.empty:
        return _empty_tail_diagnostics()

    drawdown_start, drawdown_end, drawdown_duration = _worst_drawdown_window(raw)
    longest_cluster = 0
    current_cluster = 0
    for value in observed_returns:
        if pd.notna(value) and float(value) < 0:
            current_cluster += 1
            longest_cluster = max(longest_cluster, current_cluster)
        else:
            current_cluster = 0

    negative_returns = returns[returns < 0]
    largest_negative_date = negative_returns.idxmin() if not negative_returns.empty else None
    concentration = _negative_return_concentration(negative_returns)
    performance_concentration = _performance_concentration(returns)
    negative_contributions = _largest_negative_contributions(returns)
    high_volatility = _losses_during_high_volatility(observed_returns, volatility)
    regime_stress = _losses_during_regime_stress(observed_returns, regime)

    return {
        "diagnostic_method": "historical_tail_diagnostics.v2",
        "diagnostic_status": "available",
        "execution_allowed": False,
        "worst_1d_return": _window_return(observed_returns, 1),
        "worst_5d_return": _window_return(observed_returns, 5),
        "worst_10d_return": _window_return(observed_returns, 10),
        "worst_drawdown_start": _as_date(drawdown_start),
        "worst_drawdown_end": _as_date(drawdown_end),
        "worst_drawdown_duration_days": drawdown_duration,
        "worst_drawdown_duration_sessions": drawdown_duration,
        "observed_session_count": int((raw.notna() & (raw > 0)).sum()),
        "loss_cluster_max_days": longest_cluster,
        "largest_negative_period_return": float(returns.min()) if not negative_returns.empty else None,
        "largest_negative_period_date": _as_date(largest_negative_date) if not negative_returns.empty else None,
        "largest_negative_contribution_periods": negative_contributions,
        "negative_return_concentration_share": concentration["share"],
        "negative_return_concentration_status": concentration["status"],
        "negative_return_concentration_reason": concentration["reason"],
        "negative_return_concentration_method": concentration["method"],
        "few_days_explain_most_performance": performance_concentration["positive_performance_few_sessions_explain_most"],
        **performance_concentration,
        **high_volatility,
        **regime_stress,
    }


def _as_date(value: object) -> object:
    return value.date() if hasattr(value, "date") else value


def _clean_series(values: pd.Series | None) -> pd.Series:
    clean = _normalise_series(values)
    return clean[clean > 0].dropna()


def _normalise_series(values: pd.Series | None) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).sort_index(kind="mergesort")


def _observed_returns(values: pd.Series) -> pd.Series:
    valid = values.notna() & (values > 0)
    returns = values.pct_change(fill_method=None)
    adjacent_valid = valid & valid.shift(1, fill_value=False)
    return returns.where(adjacent_valid).replace([np.inf, -np.inf], np.nan)


def _valid_segments(values: pd.Series) -> list[pd.Series]:
    valid = (values.notna() & (values > 0)).to_numpy(dtype=bool)
    segments: list[pd.Series] = []
    start: int | None = None
    for position, is_valid in enumerate(valid):
        if is_valid and start is None:
            start = position
        elif not is_valid and start is not None:
            segments.append(values.iloc[start:position])
            start = None
    if start is not None:
        segments.append(values.iloc[start:])
    return segments


def _worst_drawdown_window(values: pd.Series) -> tuple[object, object, int]:
    worst_drawdown = float("inf")
    worst_start: object = None
    worst_end: object = None
    worst_duration = 0
    for segment in _valid_segments(values):
        drawdown = segment / segment.cummax() - 1.0
        end_position = int(np.argmin(drawdown.to_numpy()))
        start_position = int(np.argmax(segment.iloc[: end_position + 1].to_numpy()))
        candidate = float(drawdown.iloc[end_position])
        if candidate < worst_drawdown:
            worst_drawdown = candidate
            worst_start = segment.index[start_position]
            worst_end = segment.index[end_position]
            worst_duration = end_position - start_position + 1
    return worst_start, worst_end, worst_duration


def _window_return(returns: pd.Series, window: int) -> float | None:
    if len(returns) < window:
        return None
    values = (1.0 + returns).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1.0
    return float(values.min()) if values.notna().any() else None


def _empty_tail_diagnostics() -> dict[str, object]:
    return {
        "diagnostic_method": "historical_tail_diagnostics.v2",
        "diagnostic_status": "unavailable",
        "execution_allowed": False,
        "worst_1d_return": None,
        "worst_5d_return": None,
        "worst_10d_return": None,
        "worst_drawdown_start": None,
        "worst_drawdown_end": None,
        "worst_drawdown_duration_days": None,
        "worst_drawdown_duration_sessions": None,
        "observed_session_count": 0,
        "loss_cluster_max_days": 0,
        "largest_negative_period_return": None,
        "largest_negative_period_date": None,
        "largest_negative_contribution_periods": [],
        "negative_return_concentration_share": None,
        "negative_return_concentration_status": "unavailable",
        "negative_return_concentration_reason": "no finite negative return observations are available",
        "negative_return_concentration_method": "five worst observed loss sessions divided by total observed loss magnitude",
        "few_days_explain_most_performance": None,
        "performance_concentration_basis": "unavailable",
        "performance_concentration_method": "best/worst up-to-five observed sessions divided by same-sign gross log contribution",
        "performance_concentration_status": "unavailable",
        "performance_concentration_share": None,
        "positive_performance_concentration_share": None,
        "positive_performance_concentration_status": "unavailable",
        "positive_performance_few_sessions_explain_most": None,
        "negative_performance_concentration_share": None,
        "negative_performance_concentration_status": "unavailable",
        "negative_performance_few_sessions_explain_most": None,
        "losses_during_high_volatility": None,
        "high_volatility_loss_status": "unavailable",
        "high_volatility_loss_reason": "at least 20 finite return observations and 20 aligned realized-volatility observations are required",
        "high_volatility_loss_method": "loss-session alignment with 20-session realized volatility at or above its 75th percentile",
        "losses_during_regime_stress": None,
        "regime_stress_loss_status": "unavailable",
        "regime_stress_loss_reason": "regime observations were not supplied",
        "regime_stress_loss_method": "loss-session alignment with explicitly labelled stress regimes",
    }


def _negative_return_concentration(negative_returns: pd.Series) -> dict[str, object]:
    method = "five worst observed loss sessions divided by total observed loss magnitude"
    if negative_returns.empty:
        return {
            "share": None,
            "few_days_explain_most": None,
            "status": "unavailable",
            "reason": "no finite negative return observations are available",
            "method": method,
        }
    total_loss = float(-negative_returns.sum())
    if not np.isfinite(total_loss) or total_loss <= 0:
        return {
            "share": None,
            "few_days_explain_most": None,
            "status": "unavailable",
            "reason": "negative return magnitude is not finite",
            "method": method,
        }
    worst_losses = negative_returns.nsmallest(min(5, len(negative_returns)))
    share = float(min(1.0, -worst_losses.sum() / total_loss))
    return {
        "share": share,
        "few_days_explain_most": bool(share >= CONCENTRATION_THRESHOLD),
        "status": "available",
        "reason": "",
        "method": method,
    }


def _performance_concentration(returns: pd.Series) -> dict[str, object]:
    """Measure concentration of positive and negative gross log performance."""

    log_returns = np.log1p(returns).replace([np.inf, -np.inf], np.nan).dropna()
    positive = log_returns[log_returns > 0]
    negative = log_returns[log_returns < 0]
    positive_share = _same_sign_concentration_share(positive, positive=True)
    negative_share = _same_sign_concentration_share(negative, positive=False)
    positive_status = "available" if positive_share is not None else "unavailable"
    negative_status = "available" if negative_share is not None else "unavailable"
    gross_log_return = float(log_returns.sum()) if not log_returns.empty else 0.0
    if gross_log_return > 0:
        basis = "positive_gross_log_return"
        selected_share = positive_share
    elif gross_log_return < 0:
        basis = "negative_gross_log_return"
        selected_share = negative_share
    else:
        basis = "flat_gross_log_return"
        selected_share = None
    return {
        "performance_concentration_basis": basis,
        "performance_concentration_method": "best/worst up-to-five observed sessions divided by same-sign gross log contribution",
        "performance_concentration_status": "available" if selected_share is not None else "unavailable",
        "performance_concentration_share": selected_share,
        "gross_log_return": gross_log_return,
        "positive_performance_concentration_share": positive_share,
        "positive_performance_concentration_status": positive_status,
        "positive_performance_few_sessions_explain_most": None if positive_share is None else bool(round(positive_share, 12) > 0.5),
        "negative_performance_concentration_share": negative_share,
        "negative_performance_concentration_status": negative_status,
        "negative_performance_few_sessions_explain_most": None if negative_share is None else bool(round(negative_share, 12) > 0.5),
        "few_days_explain_most_performance": None if selected_share is None else bool(round(selected_share, 12) > 0.5),
    }


def _same_sign_concentration_share(values: pd.Series, *, positive: bool) -> float | None:
    if values.empty:
        return None
    gross = float(values.sum() if positive else -values.sum())
    if not np.isfinite(gross) or gross <= 0:
        return None
    selected = values.nlargest(min(5, len(values))) if positive else values.nsmallest(min(5, len(values)))
    share = float((selected.sum() if positive else -selected.sum()) / gross)
    return min(1.0, share)


def _largest_negative_contributions(returns: pd.Series) -> list[dict[str, object]]:
    losses = returns[returns < 0].sort_values(kind="mergesort").head(5)
    return [
        {"date": _as_date(index), "return": float(value)}
        for index, value in losses.items()
    ]


def _losses_during_high_volatility(
    returns: pd.Series,
    volatility: pd.Series | None,
) -> dict[str, object]:
    prefix = "high_volatility_loss"
    method = "loss-session alignment with 20-session realized volatility at or above its 75th percentile"
    if volatility is None:
        observed_volatility = returns.rolling(20, min_periods=20).std()
    else:
        method = "loss-session alignment with supplied volatility at or above its 75th percentile"
        observed_volatility = pd.to_numeric(volatility, errors="coerce").replace([np.inf, -np.inf], np.nan)
    aligned = pd.concat(
        [returns.rename("return"), observed_volatility.rename("volatility")], axis=1, join="inner"
    ).dropna()
    if len(aligned) < MIN_STRESS_OBSERVATIONS:
        return {
            "losses_during_high_volatility": None,
            f"{prefix}_status": "unavailable",
            f"{prefix}_reason": f"at least {MIN_STRESS_OBSERVATIONS} aligned finite observations are required",
            f"{prefix}_method": method,
        }
    threshold = float(aligned["volatility"].quantile(STRESS_QUANTILE))
    if not np.isfinite(threshold):
        return {
            "losses_during_high_volatility": None,
            f"{prefix}_status": "unavailable",
            f"{prefix}_reason": "volatility threshold is not finite",
            f"{prefix}_method": method,
        }
    losses = aligned["return"] < 0
    high_volatility_losses = losses & (aligned["volatility"] >= threshold)
    return {
        "losses_during_high_volatility": bool(high_volatility_losses.any()),
        f"{prefix}_status": "available",
        f"{prefix}_reason": "",
        f"{prefix}_method": method,
        "high_volatility_threshold": threshold,
        "high_volatility_loss_sessions": int(high_volatility_losses.sum()),
        "loss_sessions_observed": int(losses.sum()),
    }


def _losses_during_regime_stress(
    returns: pd.Series,
    regime: pd.Series | None,
) -> dict[str, object]:
    prefix = "regime_stress_loss"
    method = "loss-session alignment with explicitly labelled stress regimes"
    if regime is None:
        return {
            "losses_during_regime_stress": None,
            f"{prefix}_status": "unavailable",
            f"{prefix}_reason": "regime observations were not supplied",
            f"{prefix}_method": method,
        }
    labels = regime.astype("string").str.strip().str.lower()
    aligned = pd.concat([returns.rename("return"), labels.rename("regime")], axis=1, join="inner").dropna()
    if len(aligned) < MIN_STRESS_OBSERVATIONS:
        return {
            "losses_during_regime_stress": None,
            f"{prefix}_status": "unavailable",
            f"{prefix}_reason": f"at least {MIN_STRESS_OBSERVATIONS} aligned finite observations are required",
            f"{prefix}_method": method,
        }
    stress_labels = {"stress", "stressed", "crisis", "risk-off", "risk_off", "defensive"}
    stress = aligned["regime"].isin(stress_labels)
    if not stress.any():
        return {
            "losses_during_regime_stress": None,
            f"{prefix}_status": "unavailable",
            f"{prefix}_reason": "no recognised regime-stress labels are available",
            f"{prefix}_method": method,
        }
    return {
        "losses_during_regime_stress": bool(((aligned["return"] < 0) & stress).any()),
        f"{prefix}_status": "available",
        f"{prefix}_reason": "",
        f"{prefix}_method": method,
        "regime_stress_loss_sessions": int(((aligned["return"] < 0) & stress).sum()),
        "regime_stress_sessions_observed": int(stress.sum()),
    }


def performance_metrics(
    equity: pd.Series,
    benchmark: pd.Series | None = None,
    turnover: float = 0.0,
    cost_drag: float = 0.0,
) -> dict[str, object]:
    raw_equity = _normalise_series(equity)
    equity = _clean_series(raw_equity)
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
            **tail_event_diagnostics(raw_equity, benchmark=benchmark),
        }
    returns = np.log(equity / equity.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
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
        **tail_event_diagnostics(raw_equity, benchmark=benchmark),
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
