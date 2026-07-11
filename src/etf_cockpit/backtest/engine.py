from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations
from statistics import NormalDist

import numpy as np
import pandas as pd

from etf_cockpit.backtest.benchmarks import equal_weights, momentum_weights, target_weights, trend_weights
from etf_cockpit.backtest.metrics import performance_metrics
from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.signals.signal_pipeline import generate_signals


@dataclass(frozen=True)
class BacktestReport:
    results: pd.DataFrame
    equity_curves: pd.DataFrame
    trade_log: pd.DataFrame
    signal_log: pd.DataFrame
    ai_added_value: bool
    quality_label: str = "low"
    quality_notes: list[str] | None = None


def _price_pivot(prices: pd.DataFrame) -> pd.DataFrame:
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().dropna(how="all")


def _holdings_from_weights(weights: pd.Series, price_row: pd.Series, portfolio_value: float, as_of: date) -> pd.DataFrame:
    rows = []
    for etf_id, weight in weights.items():
        price = float(price_row.get(etf_id, 0) or 0)
        value = portfolio_value * float(weight)
        rows.append(
            {
                "as_of_date": as_of,
                "etf_id": etf_id,
                "units": value / price if price else 0.0,
                "market_price": price,
                "market_value_eur": value,
                "current_weight": float(weight),
                "average_cost_eur": price,
                "unrealised_gain_eur": 0.0,
                "unrealised_gain_pct": 0.0,
                "source": "backtest",
            }
        )
    return pd.DataFrame(rows)


def run_backtest(
    config: AppConfig,
    prices: pd.DataFrame,
    *,
    initial_value_eur: float = 10000,
    rebalance_frequency_days: int = 21,
    transaction_cost_bps: float = 13.0,
) -> BacktestReport:
    pivot_raw = _price_pivot(prices)
    columns = [column for column in config.universe.enabled_ids if column in pivot_raw.columns]
    pivot = pivot_raw[columns].dropna()
    pivot = pivot[columns]
    if len(pivot) < 260:
        raise ValueError("Backtest requires at least 260 price rows.")
    log_returns = np.log(pivot / pivot.shift(1)).fillna(0.0)
    start_index = 220
    rebalance_indexes = set(range(start_index, len(pivot), rebalance_frequency_days))
    strategies = ["buy_and_hold", "equal_weight", "momentum_only", "trend_only", "signal_strategy"]
    weights = {name: target_weights(config, columns) for name in strategies}
    if "equal_weight" in weights:
        weights["equal_weight"] = equal_weights(columns)
    equity = {name: [initial_value_eur] for name in strategies}
    index_values = [pivot.index[start_index]]
    turnover = {name: 0.0 for name in strategies}
    cost_drag = {name: 0.0 for name in strategies}
    pending_weights: dict[str, pd.Series] = {}
    pending_costs: dict[str, float] = {}
    pending_execution_date: pd.Timestamp | None = None
    trade_rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []

    for i in range(start_index + 1, len(pivot)):
        dt = pivot.index[i]
        execution_costs: dict[str, float] = {}
        if pending_execution_date is not None and dt == pending_execution_date:
            execution_costs = pending_costs
            for name, new_weight in pending_weights.items():
                weights[name] = new_weight.reindex(columns).fillna(0)
            pending_weights = {}
            pending_costs = {}
            pending_execution_date = None

        day_return = log_returns.loc[dt, columns]
        for name in strategies:
            previous_equity = equity[name][-1]
            portfolio_return = float((weights[name].reindex(columns).fillna(0) * day_return).sum())
            equity_after_cost = max(previous_equity - execution_costs.get(name, 0.0), 0.0)
            new_equity = equity_after_cost * np.exp(portfolio_return)
            equity[name].append(max(new_equity, 0.0))
        index_values.append(dt)

        if i in rebalance_indexes and i + 1 < len(pivot):
            history = pivot.iloc[: i + 1]
            new_weights = {
                "buy_and_hold": weights["buy_and_hold"],
                "equal_weight": equal_weights(columns),
                "momentum_only": momentum_weights(history, columns),
                "trend_only": trend_weights(config, history, columns),
                "signal_strategy": weights["signal_strategy"],
            }
            # The signal strategy uses the same live signal pipeline, then tilts around targets.
            truncated_prices = prices[pd.to_datetime(prices["date"]) <= dt].copy()
            features = compute_features(truncated_prices, benchmark_etf_id=columns[0])
            latest = latest_features(features, as_of_date=dt.date())
            holdings = _holdings_from_weights(weights["signal_strategy"], pivot.iloc[i], equity["signal_strategy"][-1], dt.date())
            report = validate_prices(truncated_prices, as_of_date=dt.date(), min_history_days=180)
            if report.status == "Blocked":
                report = DataQualityReport(as_of_date=dt.date(), issues=[issue for issue in report.issues if issue.code != "insufficient_history"])
            signals = generate_signals(
                config,
                latest,
                holdings,
                report,
                as_of_date=dt.date(),
                run_id=f"backtest_{dt:%Y%m%d}",
            )
            signal_weight = weights["signal_strategy"].copy()
            target = target_weights(config, columns)
            for signal in signals:
                signal_rows.append({"date": dt.date(), "etf_id": signal.etf_id, "action": signal.action, "score": signal.total_score})
                if signal.etf_id not in signal_weight:
                    continue
                if signal.action in {"buy", "add", "add_candidate"}:
                    signal_weight[signal.etf_id] = min(target[signal.etf_id] * 1.20, signal_weight[signal.etf_id] + 0.02)
                elif signal.action in {"trim", "trim_candidate"}:
                    signal_weight[signal.etf_id] = max(0.0, signal_weight[signal.etf_id] - 0.02)
                elif signal.action == "sell":
                    signal_weight[signal.etf_id] = 0.0
            total_signal = signal_weight.sum()
            new_weights["signal_strategy"] = signal_weight / total_signal if total_signal > 0 else signal_weight

            execution_dt = pivot.index[i + 1]
            pending_execution_date = execution_dt
            pending_weights = {}
            pending_costs = {}
            for name, new_weight in new_weights.items():
                diff = (new_weight.reindex(columns).fillna(0) - weights[name].reindex(columns).fillna(0)).abs()
                step_turnover = float(diff.sum())
                step_cost = equity[name][-1] * step_turnover * transaction_cost_bps / 10_000
                turnover[name] += step_turnover
                cost_drag[name] += step_cost
                pending_weights[name] = new_weight.reindex(columns).fillna(0)
                pending_costs[name] = step_cost
                if step_turnover > 0:
                    trade_rows.append(
                        {
                            "date": execution_dt.date(),
                            "signal_date": dt.date(),
                            "execution_date": execution_dt.date(),
                            "strategy": name,
                            "turnover": step_turnover,
                            "cost_eur": step_cost,
                        }
                    )

    equity_curves = pd.DataFrame({name: values for name, values in equity.items()}, index=index_values)
    benchmark = equity_curves["buy_and_hold"]
    pbo_probability = _pbo_probability_proxy(equity_curves, strategies)
    parameter_sensitivity = _parameter_sensitivity_status(equity_curves, trade_rows, strategies)
    result_rows = []
    years = max((len(equity_curves) - 1) / TRADING_DAYS_PER_YEAR, 1e-9)
    rebalance_count = sum(1 for index in rebalance_indexes if start_index < index < len(pivot))
    for name in strategies:
        metrics = performance_metrics(equity_curves[name], benchmark=benchmark, turnover=turnover[name], cost_drag=cost_drag[name])
        strategy_trades = [row for row in trade_rows if row["strategy"] == name]
        returns_252d = equity_curves[name].pct_change(252)
        metrics["n_walk_forward_periods"] = rebalance_count
        metrics["train_periods"] = start_index
        metrics["validation_periods"] = 0
        metrics["test_periods"] = max(0, len(pivot) - start_index)
        metrics["trade_count"] = len(strategy_trades)
        metrics["average_trade_eur"] = float(initial_value_eur * (sum(float(row["turnover"]) for row in strategy_trades) / max(len(strategy_trades), 1)))
        metrics["median_holding_period_days"] = float(rebalance_frequency_days)
        metrics["turnover_annualised"] = float(turnover[name] / years)
        metrics["worst_12m_return"] = float(returns_252d.min()) if returns_252d.notna().any() else 0.0
        strategy_returns = _log_equity_returns(equity_curves[name])
        metrics["probabilistic_sharpe"] = _probabilistic_sharpe(strategy_returns)
        metrics["deflated_sharpe"] = _deflated_sharpe(metrics["sharpe"], len(strategies), len(strategy_returns))
        metrics["pbo_probability_backtest_overfitting"] = pbo_probability
        metrics["parameter_sensitivity_status"] = parameter_sensitivity.get(name, "not_available")
        metrics["backtest_quality"] = _backtest_quality_label(
            pbo_probability,
            parameter_sensitivity.get(name, "not_available"),
            rebalance_count,
        )
        metrics["strategy_name"] = name
        metrics["start_date"] = equity_curves.index.min().date()
        metrics["end_date"] = equity_curves.index.max().date()
        metrics["final_value_eur"] = float(equity_curves[name].iloc[-1])
        result_rows.append(metrics)
    results = pd.DataFrame(result_rows)
    no_ai = results.loc[results["strategy_name"] == "momentum_only", "calmar"].iloc[0]
    signal_calmar = results.loc[results["strategy_name"] == "signal_strategy", "calmar"].iloc[0]
    ai_added_value = bool(signal_calmar > no_ai * 1.03)
    return BacktestReport(
        results=results,
        equity_curves=equity_curves,
        trade_log=pd.DataFrame(trade_rows),
        signal_log=pd.DataFrame(signal_rows),
        ai_added_value=ai_added_value,
        quality_label=_overall_quality_label(results),
        quality_notes=[
            "Uses adjusted-close sample/local series without silent forward-fill.",
            "Advanced diagnostics are deterministic local estimates: probabilistic Sharpe, deflated Sharpe and a CSCV-style PBO proxy.",
            "Parameter sensitivity status reflects period stability plus a 2x transaction-cost stress on realised trade logs.",
        ],
    )


def _log_equity_returns(equity: pd.Series) -> pd.Series:
    clean = equity.dropna().astype(float)
    return np.log(clean / clean.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()


def _probabilistic_sharpe(returns: pd.Series, *, benchmark_sharpe: float = 0.0) -> float:
    returns = returns.dropna()
    if len(returns) < 4 or float(returns.std()) <= 0:
        return 0.5
    sharpe_daily = float(returns.mean() / returns.std())
    benchmark_daily = benchmark_sharpe / np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(returns.skew()) if len(returns) > 2 else 0.0
    kurtosis = float(returns.kurt()) + 3.0 if len(returns) > 3 else 3.0
    denominator = np.sqrt(max(1.0 - skew * sharpe_daily + ((kurtosis - 1.0) / 4.0) * sharpe_daily**2, 1e-9))
    z_score = (sharpe_daily - benchmark_daily) * np.sqrt(len(returns) - 1) / denominator
    return float(np.clip(NormalDist().cdf(z_score), 0.0, 1.0))


def _deflated_sharpe(annualised_sharpe: float, n_trials: int, n_observations: int) -> float:
    if n_observations < 4:
        return 0.0
    trials = max(int(n_trials), 1)
    # Conservative expected best noise Sharpe across tested strategies.
    trial_probability = 1.0 - 1.0 / max(trials + 1, 2)
    expected_noise_daily = NormalDist().inv_cdf(trial_probability) / np.sqrt(max(n_observations - 1, 1))
    expected_noise_annual = expected_noise_daily * np.sqrt(TRADING_DAYS_PER_YEAR)
    return float(annualised_sharpe - expected_noise_annual)


def _pbo_probability_proxy(equity_curves: pd.DataFrame, strategies: list[str], *, folds: int = 4) -> float:
    returns = np.log(equity_curves[strategies] / equity_curves[strategies].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < folds * 5:
        return 1.0
    fold_indexes = np.array_split(np.arange(len(returns)), folds)
    failures = 0
    total = 0
    for in_sample_folds in combinations(range(folds), folds // 2):
        in_index = np.concatenate([fold_indexes[index] for index in in_sample_folds])
        out_index = np.concatenate([fold_indexes[index] for index in range(folds) if index not in in_sample_folds])
        in_scores = _fold_sharpe(returns.iloc[in_index])
        out_scores = _fold_sharpe(returns.iloc[out_index])
        if in_scores.empty or out_scores.empty:
            continue
        selected = str(in_scores.idxmax())
        out_rank = out_scores.rank(ascending=False, method="min").get(selected)
        if out_rank is None:
            continue
        total += 1
        if float(out_rank) > (len(strategies) + 1) / 2:
            failures += 1
    return float(failures / total) if total else 1.0


def _parameter_sensitivity_status(equity_curves: pd.DataFrame, trade_rows: list[dict[str, object]], strategies: list[str]) -> dict[str, str]:
    returns = np.log(equity_curves[strategies] / equity_curves[strategies].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 40:
        return {strategy: "insufficient_history" for strategy in strategies}
    fold_indexes = np.array_split(np.arange(len(returns)), 4)
    statuses: dict[str, str] = {}
    for strategy in strategies:
        fold_scores = [_single_series_sharpe(returns[strategy].iloc[index]) for index in fold_indexes if len(index) > 1]
        positive_folds = sum(1 for score in fold_scores if score > 0)
        cost_drag = sum(float(row["cost_eur"]) for row in trade_rows if row["strategy"] == strategy)
        final_value = float(equity_curves[strategy].iloc[-1])
        doubled_cost_final = final_value - cost_drag
        start_value = float(equity_curves[strategy].iloc[0])
        survives_cost_stress = doubled_cost_final > start_value
        if positive_folds >= 3 and survives_cost_stress:
            statuses[strategy] = "stable"
        elif positive_folds >= 2 or survives_cost_stress:
            statuses[strategy] = "mixed"
        else:
            statuses[strategy] = "fragile"
    return statuses


def _fold_sharpe(returns: pd.DataFrame) -> pd.Series:
    scores = {}
    for column in returns.columns:
        scores[column] = _single_series_sharpe(returns[column])
    return pd.Series(scores)


def _single_series_sharpe(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    std = float(clean.std())
    if len(clean) < 2 or std <= 0:
        return 0.0
    return float((clean.mean() / std) * np.sqrt(TRADING_DAYS_PER_YEAR))


def _backtest_quality_label(pbo_probability: float, parameter_sensitivity_status: str, rebalance_count: int) -> str:
    if rebalance_count < 3:
        return "low"
    if parameter_sensitivity_status == "stable" and pbo_probability <= 0.33:
        return "medium"
    if parameter_sensitivity_status in {"stable", "mixed"} and pbo_probability <= 0.66:
        return "medium"
    return "low"


def _overall_quality_label(results: pd.DataFrame) -> str:
    if results.empty or "backtest_quality" not in results:
        return "low"
    return "medium" if (results["backtest_quality"] == "medium").any() else "low"
