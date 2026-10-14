"""#946 backtest and cost realism: modelled costs, long-only comparators, PIT/survivor integrity, capacity."""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.analysis.decision.rank_validation import load_rank_validation_policy, rank_validation_metrics
from etf_cockpit.backtest.benchmarks import assert_long_only, investable_comparison, long_only_top_n_weights
from etf_cockpit.backtest.engine import (
    BacktestDataUnavailableError,
    COST_REGIME_LEGACY,
    COST_REGIME_MODELLED,
    COST_REGIME_STRESS,
    SURVIVORSHIP_CONDITIONAL,
    _exclude_late_listed_short_history,
    load_backtest_realism_settings,
    run_backtest,
    run_backtest_cost_regimes,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.portfolio.costs import (
    EVIDENCE_BROKER_FILL,
    EVIDENCE_CONFIGURED,
    EVIDENCE_PAPER_FILL,
    average_daily_value_eur,
    estimate_execution_cost,
    estimated_cost_bps,
    fill_feasibility,
)
from etf_cockpit.signals.friction_edge import evaluate_friction_gate
from etf_cockpit.trading.tca import calibrate_completed_fills

END = pd.Timestamp("2026-06-26").date()


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture(scope="module")
def prices(config) -> pd.DataFrame:
    return generate_sample_prices(config, periods=340, end_date=END)


@pytest.fixture(scope="module")
def regimes(config, prices):
    return run_backtest_cost_regimes(config, prices, rebalance_frequency_days=42)


# --- the five issue tests -------------------------------------------------


def test_same_strategy_is_reported_separately_under_three_cost_regimes(regimes) -> None:
    assert set(regimes.reports) == {COST_REGIME_MODELLED, COST_REGIME_LEGACY, COST_REGIME_STRESS}
    comparison = regimes.comparison
    assert set(comparison["cost_regime"]) == set(regimes.reports)
    per_regime = comparison.groupby("cost_regime")["strategy_name"].apply(set)
    assert per_regime[COST_REGIME_MODELLED] == per_regime[COST_REGIME_LEGACY] == per_regime[COST_REGIME_STRESS]
    drag = comparison.pivot(index="strategy_name", columns="cost_regime", values="cost_drag")
    # Stress costs more than the modelled default for any strategy that trades.
    traded = drag[drag[COST_REGIME_MODELLED] > 0]
    assert not traded.empty
    assert (traded[COST_REGIME_STRESS] > traded[COST_REGIME_MODELLED]).all()
    assert regimes.reports[COST_REGIME_MODELLED].trade_log["cost_model_id"].eq("execution-cost-v1").all()
    assert regimes.reports[COST_REGIME_LEGACY].trade_log["cost_model_id"].eq("explicit_transaction_cost_bps").all()


def test_short_leg_is_excluded_from_the_investable_result() -> None:
    result = investable_comparison(0.02, short_leg_return=-0.03, benchmark_return=0.01, cash_return=0.001)
    assert result["investable_return"] == 0.02
    assert result["short_leg_included"] is False
    assert result["research_only"]["long_short_spread"] == pytest.approx(0.05)
    assert result["research_only"]["label"] == "research_only_not_investable"
    weights = long_only_top_n_weights(pd.Series({"A": 3.0, "B": 2.0, "C": -1.0, "D": float("nan")}), 2)
    assert weights.to_dict() == {"A": 0.5, "B": 0.5, "C": 0.0, "D": 0.0}
    with pytest.raises(ValueError):
        assert_long_only(pd.Series({"A": 1.2, "B": -0.2}))

    rows = [
        {
            "decision_time": f"2024-01-0{day}T23:59:59Z",
            "instrument_id": f"E{number}",
            "ranker": "balanced_challenger",
            "score": float(number),
            "net_return": 0.01 * number - 0.03,
            "benchmark_net_return": 0.0,
            "cash_net_return": 0.0,
            "sector": "s",
            "size_bucket": "b",
        }
        for day in (1, 2, 3)
        for number in range(1, 8)
    ]
    policy = replace(
        load_rank_validation_policy(), minimum_universe_support=5, top_n=3, bottom_n=3, minimum_group_support=1
    )
    metrics = rank_validation_metrics(pd.DataFrame(rows), "balanced_challenger", policy=policy)
    assert metrics["top_minus_bottom_status"] == "research_only_not_investable"
    investable = metrics["investable_long_only"]
    assert investable["short_leg_included"] is False
    assert investable["top_net_return_mean"] == metrics["top_net_return_mean"]
    assert investable["top_net_return_mean"] != metrics["top_minus_bottom_mean"]


def test_delisted_asset_missing_prices_gives_conditional_label_never_zero_pnl(config, prices) -> None:
    ids = [item for item in config.universe.enabled_ids if item in set(prices["etf_id"])]
    delisted = ids[0]
    dates = sorted(prices["date"].unique())
    cutoff = dates[300]
    panel = prices.loc[~((prices["etf_id"] == delisted) & (prices["date"] > cutoff))]
    report = run_backtest(config, panel, rebalance_frequency_days=21)
    assert report.metadata["survivorship_label"] == SURVIVORSHIP_CONDITIONAL
    assert delisted in report.metadata["delisted_instruments"]
    assert report.metadata["missing_prices_zero_filled"] is False
    assert report.metadata["forward_fill_used"] is False
    # Rows without a price are dropped, not valued at zero P&L.
    assert report.metadata["date_range_end"] <= pd.Timestamp(cutoff).date()
    assert np.isfinite(report.equity_curves.dropna().to_numpy()).all()
    # Complete history keeps the unconditional label.
    full = run_backtest(config, prices, rebalance_frequency_days=42)
    assert full.metadata["survivorship_label"] != SURVIVORSHIP_CONDITIONAL


def test_zero_volume_day_gives_no_fill_and_thin_ec_needs_a_manual_quote(config, prices) -> None:
    thin = fill_feasibility(
        5_000.0, day_volume_shares=0.0, price_eur=10.0, adv_eur=50_000.0, participation_rate=0.1
    )
    assert thin.status == "no_fill_zero_volume" and thin.fillable_eur == 0.0 and thin.unfilled_eur == 5_000.0
    missing = fill_feasibility(5_000.0, day_volume_shares=None, price_eur=10.0, adv_eur=None, participation_rate=0.1)
    assert missing.fillable_eur == 0.0
    ec = fill_feasibility(
        5_000.0, day_volume_shares=10_000.0, price_eur=10.0, adv_eur=50_000.0, participation_rate=0.1,
        manual_quote_required=True,
    )
    assert ec.status == "manual_quote_required" and ec.fillable_eur == 0.0
    quoted = fill_feasibility(
        1_000.0, day_volume_shares=10_000.0, price_eur=10.0, adv_eur=50_000.0, participation_rate=0.1,
        manual_quote_required=True, manual_quote_eur=10.0,
    )
    assert quoted.status == "full_fill"

    # Engine: with zero volume on every EUR listing, no order fills.
    eur_ids = {item.id for item in config.universe.etfs if item.currency == "EUR"}
    zero = prices.copy()
    zero.loc[zero["etf_id"].isin(eur_ids), "volume"] = 0.0
    report = run_backtest(config, zero, rebalance_frequency_days=42, enforce_capacity=True)
    log = report.trade_log
    assert report.metadata["capacity_enforcement"] == "enforced"
    assert log["capacity_fill_status"].str.contains("no_fill_zero_volume").any()
    assert (log["unfilled_eur"] > 0).any()


def test_flat_override_run_is_flagged_non_qualifying(config, prices, regimes) -> None:
    legacy = regimes.reports[COST_REGIME_LEGACY]
    assert legacy.metadata["cost_regime"] == COST_REGIME_LEGACY
    assert legacy.metadata["qualifying_cost_regime"] is False
    assert legacy.metadata["is_execution_evidence"] is False
    assert "not execution evidence" in legacy.metadata["cost_regime_note"]
    assert regimes.reports[COST_REGIME_MODELLED].metadata["qualifying_cost_regime"] is True
    assert regimes.reports[COST_REGIME_STRESS].metadata["qualifying_cost_regime"] is False
    assert load_backtest_realism_settings()["legacy_override_qualifies"] is False
    assert run_backtest(config, prices, rebalance_frequency_days=42, transaction_cost_bps=13).metadata[
        "qualifying_cost_regime"
    ] is False


# --- bughunt entries ------------------------------------------------------


def test_c018_n001_cost_gate_is_size_aware(config) -> None:
    assert estimated_cost_bps(config, "VWCE", 250_000.0) > estimated_cost_bps(config, "VWCE")
    neutral = estimate_execution_cost(config, "VWCE", 0.0).as_dict()
    blocked = evaluate_friction_gate(50.0, order_value_eur=5_000.0, cost_estimate=neutral)
    assert blocked.status == "unavailable" and blocked.propose is False
    small = estimate_execution_cost(config, "VWCE", 5_000.0, adv_eur=1_000_000.0, daily_volatility=0.01).as_dict()
    big = estimate_execution_cost(config, "VWCE", 400_000.0, adv_eur=1_000_000.0, daily_volatility=0.01).as_dict()
    benefit = float(small["total_cost_bps"]) + 5.0
    assert evaluate_friction_gate(benefit, order_value_eur=5_000.0, cost_estimate=small).propose is True
    assert evaluate_friction_gate(benefit, order_value_eur=400_000.0, cost_estimate=big).propose is False
    assert evaluate_friction_gate(float("nan"), order_value_eur=5_000.0, cost_estimate=small).status == "unavailable"
    exact = evaluate_friction_gate(float(small["total_cost_bps"]), order_value_eur=5_000.0, cost_estimate=small)
    assert exact.propose is False  # benefit must EXCEED the friction


def test_c018_n002_capacity_is_enforced_in_the_vector_backtest(config, prices) -> None:
    thin = prices.copy()
    eur_ids = [item.id for item in config.universe.etfs if item.currency == "EUR" and item.id in set(prices["etf_id"])]
    thin.loc[thin["etf_id"].isin(eur_ids), "volume"] = 2.0  # a few shares a day: the participation cap binds
    free = run_backtest(config, thin, rebalance_frequency_days=42)
    capped = run_backtest(config, thin, rebalance_frequency_days=42, enforce_capacity=True)
    assert "capacity_enforced" not in free.trade_log.columns
    assert capped.metadata["participation_cap"] == config.costs.cost_model.max_participation_rate
    assert capped.trade_log["capacity_enforced"].all()
    assert capped.trade_log["capacity_fill_status"].str.contains("partial_fill|no_fill").any()
    assert (capped.trade_log["unfilled_eur"] > 0).any()
    assert (capped.trade_log["max_days_to_fill"] >= 1).all()
    # Unfilled orders cut turnover and fees against the unconstrained run.
    capped_turnover = capped.results.set_index("strategy_name")["turnover"]
    free_turnover = free.results.set_index("strategy_name")["turnover"]
    assert capped_turnover["equal_weight"] < free_turnover["equal_weight"]


def test_c018_n003_trade_cost_uses_execution_notional_not_signal_day_equity(config, prices) -> None:
    report = run_backtest(config, prices, rebalance_frequency_days=42, transaction_cost_bps=13)
    equity = report.equity_curves
    checked = 0
    for row in report.trade_log.itertuples():
        strategy = row.strategy
        execution_date = pd.Timestamp(row.execution_date)
        if execution_date not in equity.index or row.cost_eur <= 0:
            continue
        rate = row.turnover * 13 / 10_000
        # Equity after the fill = notional_at_execution - cost, with cost = rate * notional.
        notional = (float(equity.loc[execution_date, strategy]) + row.cost_eur)
        assert row.cost_eur == pytest.approx(rate * notional, rel=1e-9)
        checked += 1
    assert checked > 0


def test_c020_n002_late_starting_delisted_loser_is_not_dropped_by_short_history_filter() -> None:
    dates = pd.bdate_range("2024-01-01", periods=400)
    frame = pd.DataFrame({"OLD": np.linspace(100, 120, 400), "LOSER": np.nan, "NEW": np.nan}, index=dates)
    frame.loc[dates[100:250], "LOSER"] = np.linspace(20, 2, 150)  # listed late, delisted before the end
    frame.loc[dates[-5:], "NEW"] = 10.0  # listed late, still trading
    kept, excluded = _exclude_late_listed_short_history(frame, ["OLD", "LOSER", "NEW"])
    assert "LOSER" in kept
    assert excluded == ("NEW",)


def test_c020_n002_run_fails_closed_instead_of_hiding_a_delisted_loser(config, prices) -> None:
    ids = [item for item in config.universe.enabled_ids if item in set(prices["etf_id"])]
    loser = ids[0]
    dates = sorted(prices["date"].unique())
    panel = prices.loc[
        ~((prices["etf_id"] == loser) & ((prices["date"] < dates[60]) | (prices["date"] > dates[200])))
    ]
    with pytest.raises(BacktestDataUnavailableError):
        run_backtest(config, panel, rebalance_frequency_days=21)


def test_d111_n001_sell_costs_the_same_as_buy(config) -> None:
    buy = estimate_execution_cost(config, "VWCE", 5_000.0)
    sell = estimate_execution_cost(config, "VWCE", -5_000.0)
    assert sell.total_cost_eur == buy.total_cost_eur > 0
    assert sell.order_value_eur == 5_000.0 and sell.side == "sell" and buy.side == "buy"


def test_c118_n001_nan_quote_never_overrides_configured_assumption(config) -> None:
    base = estimate_execution_cost(config, "VWCE", 5_000.0, adv_eur=1_000_000.0, daily_volatility=0.01)
    nan_quote = estimate_execution_cost(
        config, "VWCE", 5_000.0, adv_eur=1_000_000.0, daily_volatility=0.01,
        quoted_spread_bps=float("nan"), realised_slippage_bps=float("nan"),
    )
    negative = estimate_execution_cost(
        config, "VWCE", 5_000.0, adv_eur=1_000_000.0, daily_volatility=0.01,
        quoted_spread_bps=-3.0, realised_slippage_bps=float("inf"),
    )
    assert nan_quote.total_cost_eur == base.total_cost_eur > 0
    assert nan_quote.spread_bps == base.spread_bps > 0 and nan_quote.slippage_bps == base.slippage_bps > 0
    assert negative.total_cost_eur == base.total_cost_eur
    assert any(item.startswith("invalid_quoted_spread") for item in nan_quote.assumptions)
    good = estimate_execution_cost(config, "VWCE", 5_000.0, adv_eur=1_000_000.0, daily_volatility=0.01, quoted_spread_bps=10.0)
    assert good.spread_bps == 10.0


def test_c118_n002_estimate_id_covers_order_type_and_commission(config) -> None:
    market = estimate_execution_cost(config, "VWCE", 5_000.0, order_type="market")
    limit = estimate_execution_cost(config, "VWCE", 5_000.0, order_type="limit")
    assert market.estimate_id != limit.estimate_id
    cheap = config.model_copy(deep=True)
    dear = config.model_copy(deep=True)
    dear.costs.cost_model.default_commission_eur = cheap.costs.cost_model.default_commission_eur + 4.0
    assert estimate_execution_cost(cheap, "VWCE", 5_000.0).estimate_id != estimate_execution_cost(dear, "VWCE", 5_000.0).estimate_id


def test_c118_n003_nan_calibration_does_not_claim_calibrated(config) -> None:
    estimate = estimate_execution_cost(
        config, "VWCE", 5_000.0, adv_eur=1_000_000.0, daily_volatility=0.01,
        calibration={"spread_bps": float("nan"), "slippage_bps": float("nan")},
    )
    assert estimate.data_quality != "calibrated_local_inputs"
    assert estimate.evidence_class == EVIDENCE_CONFIGURED


# --- cost evidence classes, liquidity, friction ---------------------------


def test_cost_evidence_classes_are_kept_apart(config) -> None:
    kwargs = dict(adv_eur=1_000_000.0, daily_volatility=0.01)
    base = estimate_execution_cost(config, "VWCE", 5_000.0, **kwargs)
    paper = estimate_execution_cost(
        config, "VWCE", 5_000.0, calibration={"spread_bps": 0.5, "slippage_bps": 0.5, "evidence_class": "paper_fill"}, **kwargs
    )
    broker = estimate_execution_cost(
        config, "VWCE", 5_000.0, calibration={"spread_bps": 0.5, "slippage_bps": 0.5, "evidence_class": "imported_broker_fill"}, **kwargs
    )
    assert paper.spread_bps == base.spread_bps and paper.evidence_class == EVIDENCE_PAPER_FILL
    assert broker.spread_bps == 0.5 and broker.evidence_class == EVIDENCE_BROKER_FILL
    assert base.precise_alpha_claims_blocked and paper.precise_alpha_claims_blocked
    assert not broker.precise_alpha_claims_blocked
    # An instrument without a configured spread gets a conservative range.
    unknown = estimate_execution_cost(config, "NOT_CONFIGURED", 5_000.0, **kwargs)
    assert unknown.spread_range_bps[1] > unknown.spread_range_bps[0]
    assert "spread_unknown_conservative_range" in unknown.assumptions
    assert unknown.precise_alpha_claims_blocked
    summary = calibrate_completed_fills(
        [
            {"calibration_eligible": True, "completed_order": True, "realised_cost_bps": 6.0, "source_authority": "local_paper_ledger"},
            {"calibration_eligible": True, "completed_order": True, "realised_cost_bps": 9.0, "source_authority": "imported_broker_fills"},
        ]
    )
    assert summary["evidence_classes"]["paper_fill"]["mean_realised_cost_bps"] == 6.0
    assert summary["evidence_classes"]["imported_broker_fill"]["mean_realised_cost_bps"] == 9.0
    assert summary["spread_slippage_calibration_source"] == "imported_broker_fill"
    assert calibrate_completed_fills(())["spread_slippage_calibration_source"] == "unavailable_no_broker_fills"


def test_adv_is_eur_denominated_and_counts_zero_volume_days() -> None:
    volume = pd.Series([1_000.0] * 10 + [0.0] * 10)
    close = pd.Series([10.0] * 20)
    assert average_daily_value_eur(volume, close) == pytest.approx(5_000.0)
    assert average_daily_value_eur(volume, close, currency="NOK") is None
    assert average_daily_value_eur(volume, close, currency="NOK", fx_to_eur=0.1) == pytest.approx(500.0)
    assert average_daily_value_eur(pd.Series([float("nan")] * 20), close) is None
    partial = fill_feasibility(
        100_000.0, day_volume_shares=10_000.0, price_eur=10.0, adv_eur=100_000.0, participation_rate=0.1
    )
    assert partial.status == "partial_fill" and partial.fillable_eur == pytest.approx(10_000.0)
    assert partial.days_to_fill == 10 and partial.unfilled_eur == pytest.approx(90_000.0)


def test_signals_are_executed_after_the_decision_never_on_the_same_close(regimes) -> None:
    for report in regimes.reports.values():
        log = report.trade_log
        assert (pd.to_datetime(log["execution_date"]) > pd.to_datetime(log["signal_date"])).all()
        assert report.metadata["same_bar_execution_avoided"] is True
        assert report.metadata["same_bar_execution_count"] == 0


def test_investable_comparators_share_universe_dates_and_costs(regimes) -> None:
    summary = regimes.reports[COST_REGIME_MODELLED].metadata["investable_comparators"]
    assert summary["long_only"] is True and summary["short_legs_excluded"] is True
    assert {"buy_and_hold", "quality_only", "quality_momentum", "signal_strategy"} <= set(summary["strategies"])
    assert summary["cash"] == 10_000.0 and summary["cost_regime"] == COST_REGIME_MODELLED
    assert all(math.isfinite(value) for value in summary["strategies"].values())
