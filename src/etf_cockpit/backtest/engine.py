from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
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
from etf_cockpit.data.provenance import sha256_dataframe
from etf_cockpit.data.etf_structure import structure_confidence_caps, structure_input_checksum
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.portfolio.costs import COST_MODEL_ID, estimate_rebalance_cost
from etf_cockpit.signals.quality_momentum import FRAME_COLUMNS, QUALITY_MOMENTUM_VERSION, build_quality_momentum_frame, quality_momentum_weights
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
    metadata: dict[str, object] = field(default_factory=dict)
    quality_momentum_evidence: pd.DataFrame = field(default_factory=pd.DataFrame)


class BacktestDataUnavailableError(ValueError):
    """Raised when a backtest cannot be evaluated from a complete price panel."""


def backtest_input_checksum(
    config: AppConfig,
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame | None,
    *,
    structure_document_registry: object = None,
    structure_report_records: object = None,
    structure_supplemental_rows: object = None,
    structure_holdings: object = None,
) -> str:
    """Fingerprint every local input that can change a cached backtest."""

    def _stable(frame: pd.DataFrame | None, preferred_sort: tuple[str, ...]) -> str:
        if not isinstance(frame, pd.DataFrame):
            return sha256_dataframe(pd.DataFrame())
        result = frame.copy()
        sort_columns = [column for column in preferred_sort if column in result.columns]
        if sort_columns and not result.empty:
            result = result.sort_values(sort_columns, kind="stable").reset_index(drop=True)
        return sha256_dataframe(result)

    universe_payload = {
        "enabled_ids": list(config.universe.enabled_ids),
        "sectors": {
            item.id: item.sector
            for item in config.universe.etfs
            if item.id in config.universe.enabled_ids
        },
        "costs": config.costs.model_dump(mode="json"),
    }
    payload = {
        "prices": _stable(prices, ("date", "etf_id", "instrument_id")),
        "fundamentals": _stable(fundamentals, ("instrument_id", "as_of_date", "available_at", "evidence_checksum")),
        "structure": structure_input_checksum(
            document_registry=structure_document_registry,
            report_records=structure_report_records,
            supplemental_rows=structure_supplemental_rows,
            holdings=structure_holdings,
        ),
        "universe": universe_payload,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def quality_momentum_evidence_checksum(evidence: pd.DataFrame | bytes) -> str:
    """Checksum quality-momentum evidence before or after CSV persistence."""

    payload = evidence if isinstance(evidence, bytes) else evidence.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _price_pivot(prices: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        raise BacktestDataUnavailableError("not_enough_data: no price rows were supplied")
    required = {"date", "etf_id", "adjusted_close"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise BacktestDataUnavailableError(f"invalid_price_data: missing required columns {', '.join(missing)}")
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    return frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().dropna(how="all")


def _optional_price_pivot(prices: pd.DataFrame, value: str, columns: list[str]) -> pd.DataFrame:
    if value not in prices.columns:
        return pd.DataFrame(index=pd.to_datetime(prices["date"]).drop_duplicates().sort_values(), columns=columns, dtype=float)
    frame = prices.loc[:, ["date", "etf_id", value]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame[value] = pd.to_numeric(frame[value], errors="coerce")
    return frame.pivot(index="date", columns="etf_id", values=value).sort_index().reindex(columns=columns)


def _weighted_reference_price(values: pd.Series, weights: pd.Series) -> float | None:
    observed = pd.to_numeric(values, errors="coerce").reindex(weights.index)
    usable = observed.notna() & np.isfinite(observed)
    if not usable.any():
        return None
    allocation = pd.to_numeric(weights, errors="coerce").abs().reindex(weights.index).fillna(0.0)
    allocation = allocation.where(usable, 0.0)
    if float(allocation.sum()) <= 0:
        allocation = usable.astype(float)
    allocation = allocation / allocation.sum()
    return float((observed.fillna(0.0) * allocation).sum())


def _execution_evidence(
    *,
    current_prices: pd.Series,
    next_adjusted_close: pd.Series,
    next_open: pd.Series,
    next_high: pd.Series,
    next_low: pd.Series,
    changed_weights: pd.Series,
) -> dict[str, object]:
    decision_price = _weighted_reference_price(current_prices, changed_weights)
    next_open_reference = _weighted_reference_price(next_open, changed_weights)
    next_close_reference = _weighted_reference_price(next_adjusted_close, changed_weights)
    spread_values = (
        pd.to_numeric(next_high, errors="coerce") - pd.to_numeric(next_low, errors="coerce")
    ) / pd.to_numeric(next_open, errors="coerce")
    spread_proxy = _weighted_reference_price(spread_values, changed_weights)
    arrival_assumption = "next_adjusted_close" if next_close_reference is not None else "unavailable"
    close_to_next_open = None
    if decision_price is not None and next_open_reference is not None and decision_price != 0:
        close_to_next_open = float(next_open_reference / decision_price - 1.0)
    return {
        "decision_price": decision_price,
        "next_open_reference_price": next_open_reference,
        "next_period_reference_price": next_close_reference,
        "close_to_next_open_gap": close_to_next_open,
        "arrival_price_assumption": arrival_assumption,
        "spread_proxy": spread_proxy,
        "execution_delay_sessions": 1,
        "same_bar_execution_avoided": True,
    }


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
    fundamentals: pd.DataFrame | None = None,
    initial_value_eur: float = 10000,
    rebalance_frequency_days: int = 21,
    transaction_cost_bps: float | None = None,
    structure_document_registry: object = None,
    structure_report_records: object = None,
    structure_supplemental_rows: object = None,
    structure_holdings: object = None,
) -> BacktestReport:
    pivot_raw = _price_pivot(prices)
    columns = [column for column in config.universe.enabled_ids if column in pivot_raw.columns]
    if not columns:
        raise BacktestDataUnavailableError("not_enough_data: no configured instruments have adjusted-close history")
    selected_raw = pivot_raw.reindex(columns=columns)
    complete_mask = selected_raw.notna().all(axis=1)
    missing_observation_rows = int((~complete_mask).sum())
    pivot = selected_raw.loc[complete_mask].copy()
    if len(pivot) < 260:
        raise BacktestDataUnavailableError(
            "not_enough_data: backtest requires at least 260 complete adjusted-price sessions; "
            f"available={len(pivot)}, missing_observation_rows={missing_observation_rows}"
        )
    open_pivot = _optional_price_pivot(prices, "open", columns)
    high_pivot = _optional_price_pivot(prices, "high", columns)
    low_pivot = _optional_price_pivot(prices, "low", columns)
    metadata: dict[str, object] = {
        "strategy": "signal_strategy",
        "benchmark_strategy": "buy_and_hold",
        "price_field": "adjusted_close",
        "raw_price_rows": int(len(selected_raw)),
        "complete_price_rows": int(len(pivot)),
        "missing_observation_rows": missing_observation_rows,
        "data_status": "warning" if missing_observation_rows else "clean",
        "forward_fill_used": False,
        "lookahead_protection": "history_truncated_at_signal_date",
        "execution_delay_sessions": 1,
        "same_bar_execution_avoided": True,
        "cost_model_id": COST_MODEL_ID,
        "cost_model_execution_allowed": False,
        "cost_model_mode": "consistent_local_research_estimates",
        "date_range_start": pivot.index.min().date(),
        "date_range_end": pivot.index.max().date(),
        "not_enough_data_policy": "fail_closed",
        "quality_momentum_strategy_version": QUALITY_MOMENTUM_VERSION,
        "quality_momentum_evidence": "pending",
        "input_checksum": backtest_input_checksum(
            config,
            prices,
            fundamentals,
            structure_document_registry=structure_document_registry,
            structure_report_records=structure_report_records,
            structure_supplemental_rows=structure_supplemental_rows,
            structure_holdings=structure_holdings,
        ),
    }
    if missing_observation_rows:
        metadata["data_warning"] = "Incomplete adjusted-price rows were excluded; no forward-fill was applied."
    log_returns = np.log(pivot / pivot.shift(1)).fillna(0.0)
    start_index = 220
    rebalance_indexes = set(range(start_index, len(pivot), rebalance_frequency_days))
    strategies = [
        "buy_and_hold",
        "equal_weight",
        "momentum_only",
        "trend_only",
        "quality_only",
        "quality_momentum",
        "signal_strategy",
    ]
    weights = {name: target_weights(config, columns) for name in strategies}
    if "equal_weight" in weights:
        weights["equal_weight"] = equal_weights(columns)
    weights["quality_only"] = pd.Series(0.0, index=columns, dtype=float)
    weights["quality_momentum"] = pd.Series(0.0, index=columns, dtype=float)
    equity = {name: [initial_value_eur] for name in strategies}
    index_values = [pivot.index[start_index]]
    turnover = {name: 0.0 for name in strategies}
    cost_drag = {name: 0.0 for name in strategies}
    pending_weights: dict[str, pd.Series] = {}
    pending_costs: dict[str, float] = {}
    pending_execution_date: pd.Timestamp | None = None
    trade_rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    quality_evidence_rows: list[dict[str, object]] = []

    for i in range(start_index + 1, len(pivot)):
        dt = pivot.index[i]
        execution_costs: dict[str, float] = {}
        if pending_execution_date is not None and dt == pending_execution_date:
            execution_costs = pending_costs

        day_return = log_returns.loc[dt, columns]
        for name in strategies:
            previous_equity = equity[name][-1]
            portfolio_return = float((weights[name].reindex(columns).fillna(0) * day_return).sum())
            new_equity = previous_equity * np.exp(portfolio_return)
            if execution_costs.get(name, 0.0):
                new_equity = max(new_equity - execution_costs[name], 0.0)
            equity[name].append(max(new_equity, 0.0))
        index_values.append(dt)

        # Orders are filled at the next session's adjusted close.  The
        # signal-day return therefore remains attributed to the old weights;
        # the new weights affect the following session only.
        if pending_execution_date is not None and dt == pending_execution_date:
            for name, new_weight in pending_weights.items():
                weights[name] = new_weight.reindex(columns).fillna(0)
            pending_weights = {}
            pending_costs = {}
            pending_execution_date = None

        if i in rebalance_indexes and i + 1 < len(pivot):
            history = pivot.iloc[: i + 1]
            new_weights = {
                "buy_and_hold": weights["buy_and_hold"],
                "equal_weight": equal_weights(columns),
                "momentum_only": momentum_weights(history, columns),
                "trend_only": trend_weights(config, history, columns),
                "quality_only": pd.Series(0.0, index=columns, dtype=float),
                "quality_momentum": pd.Series(0.0, index=columns, dtype=float),
                "signal_strategy": weights["signal_strategy"],
            }
            quality_prices = history.rename_axis("date").reset_index().melt(
                id_vars=["date"], var_name="etf_id", value_name="adjusted_close"
            )
            sector_map = {
                item.id: str(item.sector or "")
                for item in config.universe.etfs
                if item.id in columns and item.sector
            }
            quality_evidence = build_quality_momentum_frame(
                quality_prices,
                fundamentals if fundamentals is not None else pd.DataFrame(),
                as_of_date=dt.date(),
                sector_by_instrument=sector_map,
            )
            quality_evidence_rows.extend(quality_evidence.to_dict("records"))
            new_weights["quality_only"] = quality_momentum_weights(quality_evidence, columns, mode="quality")
            new_weights["quality_momentum"] = quality_momentum_weights(quality_evidence, columns, mode="quality_momentum")
            if not quality_evidence.empty and (quality_evidence["status"] == "available").any():
                metadata["quality_momentum_evidence"] = "available"
            elif metadata.get("quality_momentum_evidence") != "available":
                metadata["quality_momentum_evidence"] = "unavailable"
            # The signal strategy uses the same live signal pipeline, then tilts around targets.
            truncated_prices = prices[pd.to_datetime(prices["date"]) <= dt].copy()
            features = compute_features(truncated_prices, benchmark_etf_id=columns[0])
            latest = latest_features(features, as_of_date=dt.date())
            holdings = _holdings_from_weights(weights["signal_strategy"], pivot.iloc[i], equity["signal_strategy"][-1], dt.date())
            report = validate_prices(truncated_prices, as_of_date=dt.date(), min_history_days=180)
            if report.status == "Blocked":
                report = DataQualityReport(as_of_date=dt.date(), issues=[issue for issue in report.issues if issue.code != "insufficient_history"])
            structure_caps = structure_confidence_caps(
                columns,
                document_registry=structure_document_registry,
                report_records=structure_report_records,
                supplemental_rows=structure_supplemental_rows,
                holdings=structure_holdings,
                decision_time=dt.date(),
            )
            signals = generate_signals(
                config,
                latest,
                holdings,
                report,
                as_of_date=dt.date(),
                run_id=f"backtest_{dt:%Y%m%d}",
                structure_confidence_caps=structure_caps,
            )
            signal_weight = weights["signal_strategy"].copy()
            target = target_weights(config, columns)
            for signal in signals:
                canonical = signal.canonical_score
                signal_rows.append(
                    {
                        "date": dt.date(),
                        "etf_id": signal.etf_id,
                        "action": signal.action,
                        "score": signal.total_score,
                        "canonical_attractiveness_10": canonical.attractiveness_10 if canonical else None,
                        "canonical_expected_return_10": canonical.expected_return_10 if canonical else None,
                        "canonical_risk_implementation_10": canonical.risk_implementation_10 if canonical else None,
                        "canonical_evidence_confidence_10": canonical.evidence_confidence_10 if canonical else None,
                        "canonical_coverage": canonical.coverage if canonical else 0.0,
                        "formula_version": canonical.formula_version if canonical else "unavailable",
                        "formula_checksum": canonical.formula_checksum if canonical else "unavailable",
                        "source_vintage_hash": canonical.source_vintage_hash if canonical else "unavailable",
                    }
                )
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
                if transaction_cost_bps is None:
                    portfolio_cost = estimate_rebalance_cost(config, equity[name][-1], diff.to_dict())
                    step_cost = portfolio_cost.total_cost_eur
                    step_cost_bps = portfolio_cost.weighted_cost_bps
                    step_cost_quality = ", ".join(sorted({item.data_quality for item in portfolio_cost.estimates})) or "no_trade"
                    step_capacity_eur = portfolio_cost.capacity_eur
                else:
                    step_cost = equity[name][-1] * step_turnover * max(0.0, transaction_cost_bps) / 10_000
                    step_cost_bps = max(0.0, transaction_cost_bps)
                    step_cost_quality = "legacy_explicit_override"
                    step_capacity_eur = None
                turnover[name] += step_turnover
                cost_drag[name] += step_cost
                pending_weights[name] = new_weight.reindex(columns).fillna(0)
                pending_costs[name] = step_cost
                if step_turnover > 0:
                    empty_reference = pd.Series(index=columns, dtype=float)
                    execution_evidence = _execution_evidence(
                        current_prices=pivot.iloc[i].reindex(columns),
                        next_adjusted_close=pivot.iloc[i + 1].reindex(columns),
                        next_open=open_pivot.loc[execution_dt].reindex(columns)
                        if execution_dt in open_pivot.index
                        else empty_reference,
                        next_high=high_pivot.loc[execution_dt].reindex(columns)
                        if execution_dt in high_pivot.index
                        else empty_reference,
                        next_low=low_pivot.loc[execution_dt].reindex(columns)
                        if execution_dt in low_pivot.index
                        else empty_reference,
                        changed_weights=diff,
                    )
                    trade_rows.append(
                        {
                            "date": execution_dt.date(),
                            "signal_date": dt.date(),
                            "execution_date": execution_dt.date(),
                            "strategy": name,
                            "turnover": step_turnover,
                            "cost_eur": step_cost,
                            "estimated_cost_bps": step_cost_bps,
                            "cost_model_id": COST_MODEL_ID if transaction_cost_bps is None else "explicit_transaction_cost_bps",
                            "cost_data_quality": step_cost_quality,
                            "capacity_eur": step_capacity_eur,
                            **execution_evidence,
                        }
                    )

    equity_curves = pd.DataFrame({name: values for name, values in equity.items()}, index=index_values)
    benchmark = equity_curves["buy_and_hold"]
    pbo_probability = _pbo_probability_proxy(equity_curves, strategies)
    parameter_sensitivity = _parameter_sensitivity_status(equity_curves, trade_rows, strategies)
    result_rows = []
    years = max((len(equity_curves) - 1) / TRADING_DAYS_PER_YEAR, 1e-9)
    rebalance_count = sum(1 for index in rebalance_indexes if start_index < index < len(pivot))
    metadata["walk_forward_periods"] = rebalance_count
    metadata["strategies"] = strategies
    metadata["same_bar_execution_count"] = 0
    metadata["quality_momentum_evidence_rows"] = len(quality_evidence_rows)
    metadata["quality_momentum_evidence_available_rows"] = sum(
        row.get("status") == "available" for row in quality_evidence_rows
    )
    quality_evidence_frame = pd.DataFrame(quality_evidence_rows, columns=FRAME_COLUMNS)
    metadata["quality_momentum_evidence_checksum"] = quality_momentum_evidence_checksum(quality_evidence_frame)
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
        metrics["overfitting_warning"] = _overfitting_warning(
            pbo_probability,
            parameter_sensitivity.get(name, "not_available"),
        )
        metrics["data_quality_status"] = metadata["data_status"]
        metrics["benchmark_strategy"] = metadata["benchmark_strategy"]
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
            "Signals are evaluated only with history available at the signal date and executed on the next complete session.",
            "Next-open and spread evidence is unavailable when the source panel does not provide OHLC fields.",
        ],
        metadata=metadata,
        quality_momentum_evidence=quality_evidence_frame,
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


def _overfitting_warning(pbo_probability: float, parameter_sensitivity_status: str) -> str:
    if pbo_probability >= 0.66:
        return "high_overfitting_risk: selected results often fail out-of-sample rank checks"
    if pbo_probability >= 0.33 or parameter_sensitivity_status in {"fragile", "mixed"}:
        return "review_required: performance is sensitive to folds or transaction-cost stress"
    return "no_material_warning_in_local_proxy: out-of-sample evidence remains limited"


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
