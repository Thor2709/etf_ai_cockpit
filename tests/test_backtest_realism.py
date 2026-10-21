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
BROKER_PROVENANCE = {"sample_count": 12, "source_authority": "imported_broker_fills"}


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture(scope="module")
def prices(config) -> pd.DataFrame:
    return generate_sample_prices(config, periods=340, end_date=END)


@pytest.fixture(scope="module")
def regimes(config, prices):
    return run_backtest_cost_regimes(config, prices, rebalance_frequency_days=42)


@pytest.fixture(scope="module")
def eur_regimes(config, prices):
    """EUR-only universe: every instrument has a capacity check, so the modelled regime can qualify."""

    eur_ids = {item.id for item in config.universe.etfs if item.currency == "EUR"}
    return run_backtest_cost_regimes(config, prices[prices["etf_id"].isin(eur_ids)], rebalance_frequency_days=42)


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
    # Complete history keeps the unconditional label only with explicit point-in-time membership evidence.
    evidence = {"status": "point_in_time_verified", "source_id": "membership-fixture"}
    enabled_panel = prices[prices["etf_id"].isin(config.universe.enabled_ids)]
    full = run_backtest(config, enabled_panel, rebalance_frequency_days=42, point_in_time_membership_evidence=evidence)
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

    # Engine: with zero volume on every listing, no order fills.
    zero = prices.assign(volume=0.0)
    report = run_backtest(config, zero, rebalance_frequency_days=42, enforce_capacity=True)
    assert report.metadata["capacity_enforcement"] == "enforced"
    # The initial allocation is a capacity-checked purchase too: nothing fills, so
    # the book carries no simulated exposure.
    initial = report.metadata["initial_allocation"]["equal_weight"]
    assert "no_fill_zero_volume" in initial["fill_status"] and initial["unfilled_eur"] > 0
    assert np.allclose(report.equity_curves["equal_weight"].dropna(), 10_000.0)
    assert (report.trade_log.get("unfilled_eur", pd.Series(dtype=float)) >= 0).all()


def test_flat_override_run_is_flagged_non_qualifying(config, prices, regimes, eur_regimes) -> None:
    legacy = regimes.reports[COST_REGIME_LEGACY]
    assert legacy.metadata["cost_regime"] == COST_REGIME_LEGACY
    assert legacy.metadata["qualifying_cost_regime"] is False
    assert legacy.metadata["is_execution_evidence"] is False
    assert "not execution evidence" in legacy.metadata["cost_regime_note"]
    assert eur_regimes.reports[COST_REGIME_MODELLED].metadata["qualifying_cost_regime"] is True
    assert eur_regimes.reports[COST_REGIME_STRESS].metadata["qualifying_cost_regime"] is False
    # Non-EUR listings fill whenever canonical FX exists, so the mixed universe is not blocked on FX ...
    mixed = regimes.reports[COST_REGIME_MODELLED]
    assert mixed.metadata["capacity_fx_unavailable_instruments"] == []
    assert "fx_unavailable_instruments_unfillable" not in mixed.metadata["qualification_blockers"]
    # ... but instruments without any FX evidence can never fill, so a universe containing them cannot qualify.
    no_fx = run_backtest(config, prices, rebalance_frequency_days=42, enforce_capacity=True, fx_rates=pd.DataFrame())
    assert no_fx.metadata["capacity_fx_unavailable_instruments"]
    assert no_fx.metadata["qualifying_cost_regime"] is False
    assert "fx_unavailable_instruments_unfillable" in no_fx.metadata["qualification_blockers"]
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
    thin["volume"] = 2.0  # a few shares a day: the participation cap binds
    free = run_backtest(config, thin, rebalance_frequency_days=42, min_trade_value_eur=0.0)
    capped = run_backtest(config, thin, rebalance_frequency_days=42, enforce_capacity=True, min_trade_value_eur=0.0)
    assert "capacity_enforced" not in free.trade_log.columns
    assert capped.metadata["participation_cap"] == config.costs.cost_model.max_participation_rate
    assert capped.trade_log["capacity_enforced"].all()
    assert capped.trade_log["capacity_fill_status"].str.contains("partial_fill|no_fill").any()
    assert (capped.trade_log["unfilled_eur"] > 0).any()
    assert (capped.trade_log["max_days_to_fill"] >= 1).all()
    # Unfilled orders cut the traded turnover against the unconstrained run.
    def traded(report) -> float:
        log = report.trade_log
        return float(log.loc[log["strategy"] == "equal_weight", "turnover"].sum())

    assert traded(capped) < traded(free)
    assert (capped.trade_log["remainder_policy"] == "cancelled_at_session_end").all()


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
        config, "VWCE", 5_000.0, calibration={"spread_bps": 0.5, "slippage_bps": 0.5, "evidence_class": "imported_broker_fill", **BROKER_PROVENANCE}, **kwargs
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


def test_investable_comparators_share_universe_dates_and_costs(config, prices, monkeypatch) -> None:
    # The sample universe has no canonical benchmark registry; bind one instrument as the validated VWCE stand-in.
    from etf_cockpit.backtest import engine as engine_module

    benchmark_id = str(prices["etf_id"].iloc[0])
    monkeypatch.setattr(engine_module, "_validated_benchmark_data_id", lambda *_args, **_kwargs: benchmark_id)
    regimes = run_backtest_cost_regimes(config, prices, rebalance_frequency_days=42)
    report = regimes.reports[COST_REGIME_MODELLED]
    summary = report.metadata["investable_comparators"]
    assert summary["long_only"] is True and summary["short_legs_excluded"] is True
    assert {"buy_and_hold", "quality_only", "quality_momentum", "signal_strategy"} <= set(summary["strategies"])
    assert summary["cash"] == 10_000.0 and summary["cost_regime"] == COST_REGIME_MODELLED
    assert summary["cost_model_id"] == "execution-cost-v1"
    assert all(math.isfinite(value["final_value_eur"]) for value in summary["strategies"].values())
    # Fixed baselines are named by identity and read from the same simulated books.
    assert {label: item["strategy"] for label, item in summary["baselines"].items()} == {
        "QV": "quality_only", "QVM": "quality_momentum", "v3": "signal_strategy", "top_n_long_only": "momentum_only"
    }
    results = report.results.set_index("strategy_name")["final_value_eur"]
    for item in summary["baselines"].values():
        if item["status"] == "unavailable":  # quality books without evidence are not results
            assert item["strategy"] in {"quality_only", "quality_momentum"} and item["reason"]
            continue
        assert item["final_value_eur"] == pytest.approx(results[item["strategy"]])
    # VWCE pays the same modelled acquisition cost a trading strategy would, over the same window.
    vwce = summary["vwce"]
    assert vwce["status"] == "available" and vwce["cost_eur"] > 0 and vwce["cost_regime"] == COST_REGIME_MODELLED
    assert vwce["instrument_id"] == report.results["benchmark_id"].iloc[0]
    legacy_vwce = regimes.reports[COST_REGIME_LEGACY].metadata["investable_comparators"]["vwce"]
    stress_vwce = regimes.reports[COST_REGIME_STRESS].metadata["investable_comparators"]["vwce"]
    assert legacy_vwce["cost_bps"] == pytest.approx(13.0)
    assert stress_vwce["cost_eur"] > vwce["cost_eur"]
    series = prices[prices["etf_id"] == vwce["instrument_id"]].assign(date=lambda frame: pd.to_datetime(frame["date"]))
    series = series.set_index("date")["adjusted_close"]
    ratio = float(series[report.equity_curves.index.max()] / series[report.equity_curves.index.min()])
    assert vwce["fill_status"] == "full_fill"
    assert vwce["final_value_eur"] == pytest.approx((10_000.0 - vwce["cost_eur"]) * ratio)


# --- correction pass 1 ----------------------------------------------------


def test_capacity_fails_closed_for_fx_unavailable_and_missing_volume(config, prices) -> None:
    from etf_cockpit.backtest.engine import _apply_capacity_limits

    columns = ["EURX", "NOKX"]
    current = pd.Series(0.0, index=columns)
    target = pd.Series({"EURX": 0.5, "NOKX": 0.5})
    executed, info = _apply_capacity_limits(
        current, target, notional_eur=10_000.0,
        volume_row=pd.Series({"EURX": 1e9, "NOKX": 1e9}), price_row=pd.Series({"EURX": 10.0, "NOKX": 10.0}),
        adv_by_instrument={"EURX": 1e9}, participation=0.1, manual_quote_ids=set(), checked_ids={"EURX"},
    )
    assert executed["EURX"] == 0.5 and executed["NOKX"] == 0.0  # no FX evidence: no fill
    assert info["fx_unavailable"] == ["NOKX"] and info["statuses"]["NOKX"] == "no_fill_fx_unavailable"
    assert info["unfilled_eur"] == pytest.approx(5_000.0)
    # Missing volume for a checked instrument is a no fill, not an unrestricted one.
    executed, info = _apply_capacity_limits(
        current, target, notional_eur=10_000.0,
        volume_row=pd.Series({"EURX": float("nan"), "NOKX": 1e9}), price_row=pd.Series({"EURX": 10.0, "NOKX": 10.0}),
        adv_by_instrument={}, participation=0.1, manual_quote_ids=set(), checked_ids={"EURX"},
    )
    assert executed["EURX"] == 0.0 and info["statuses"]["EURX"] == "no_fill_zero_volume"
    # No volume column at all: nothing fills, the result is flagged and cannot qualify.
    from etf_cockpit.backtest.engine import _volume_pivot

    index = pd.DatetimeIndex(sorted(pd.to_datetime(prices["date"]).unique()))
    assert _volume_pivot(prices.drop(columns=["volume"]), index, ["EURX"]) is None
    blank = prices.assign(volume=float("nan"))
    report = run_backtest(config, blank, rebalance_frequency_days=42, enforce_capacity=True)
    assert report.metadata["capacity_enforcement"] == "unavailable_no_volume_data"
    assert report.metadata["qualifying_cost_regime"] is False
    assert "liquidity_evidence_unavailable" in report.metadata["qualification_blockers"]
    assert np.allclose(report.equity_curves.dropna(), 10_000.0)


def test_initial_holdings_and_buy_and_hold_are_capacity_checked_and_costed(config, prices) -> None:
    thin = prices.copy()
    thin["volume"] = 2.0
    free = run_backtest(config, thin, rebalance_frequency_days=42)
    capped = run_backtest(config, thin, rebalance_frequency_days=42, enforce_capacity=True)
    assert free.metadata["initial_allocation"] == {}
    initial = capped.metadata["initial_allocation"]
    assert set(initial) == set(capped.metadata["strategies"])
    assert initial["buy_and_hold"]["unfilled_eur"] > 0
    assert initial["buy_and_hold"]["remainder_policy"] == "cancelled_at_session_end"
    # A buy-and-hold book that could not be bought is mostly cash, so it moves less than the unconstrained one.
    assert capped.equity_curves["buy_and_hold"].pct_change().std() < free.equity_curves["buy_and_hold"].pct_change().std()
    # A fully fillable initial purchase is costed: equity starts below the notional.
    deep = prices.copy()
    deep["volume"] = 1e9
    liquid = run_backtest(config, deep, rebalance_frequency_days=42, enforce_capacity=True)
    allocation = liquid.metadata["initial_allocation"]["buy_and_hold"]
    assert allocation["cost_eur"] > 0
    assert liquid.equity_curves["buy_and_hold"].dropna().iloc[0] == pytest.approx(10_000.0 - allocation["cost_eur"])


def test_execution_day_turnover_uses_the_drifted_book_not_signal_day_weights(config, prices) -> None:
    from etf_cockpit.backtest.engine import _drift_to_execution

    signal = pd.Series({"A": 0.5, "B": 0.5})
    drifted, session_return = _drift_to_execution(signal, pd.Series({"A": 1.0, "B": 0.0}))  # A doubles
    assert session_return == pytest.approx(0.5)
    assert drifted.to_dict() == pytest.approx({"A": 2 / 3, "B": 1 / 3})
    assert float((signal - drifted).abs().sum()) == pytest.approx(1 / 3)
    # Engine: a next-session price jump on one holding creates equal-weight turnover.
    base = run_backtest(config, prices, rebalance_frequency_days=42, min_trade_value_eur=0.0)
    first_execution = pd.Timestamp(base.trade_log["execution_date"].min())
    jumped = prices.copy()
    after_mask = (jumped["etf_id"] == "VWCE") & (pd.to_datetime(jumped["date"]) >= first_execution)
    assert after_mask.any()
    for column in ("adjusted_close", "close", "open", "high", "low"):
        if column in jumped.columns:
            jumped.loc[after_mask, column] *= 1.5
    after = run_backtest(config, jumped, rebalance_frequency_days=42, min_trade_value_eur=0.0)

    def first_turnover(report) -> float:
        log = report.trade_log
        row = log[(log["strategy"] == "equal_weight") & (pd.to_datetime(log["execution_date"]) == first_execution)]
        return float(row["turnover"].sum())

    assert first_turnover(after) > first_turnover(base)


def test_non_broker_calibration_never_sets_spread_or_slippage(config) -> None:
    kwargs = dict(adv_eur=1_000_000.0, daily_volatility=0.01)
    base = estimate_execution_cost(config, "VWCE", 5_000.0, **kwargs)
    for evidence_class in ("configured_assumption", "unclassified_local_calibration", "mystery", None):
        calibration = {"spread_bps": 0.0, "slippage_bps": 0.0}
        if evidence_class is not None:
            calibration["evidence_class"] = evidence_class
        estimate = estimate_execution_cost(config, "VWCE", 5_000.0, calibration=calibration, **kwargs)
        assert estimate.spread_bps == base.spread_bps > 0 and estimate.slippage_bps == base.slippage_bps > 0
        assert estimate.precise_alpha_claims_blocked is True
        assert estimate.evidence_class != EVIDENCE_BROKER_FILL
    # Broker spread alone does not clear the claim restriction while slippage is still assumed.
    spread_only = estimate_execution_cost(
        config, "VWCE", 5_000.0, calibration={"spread_bps": 0.5, "evidence_class": "imported_broker_fill", **BROKER_PROVENANCE}, **kwargs
    )
    assert spread_only.spread_bps == 0.5 and spread_only.slippage_bps == base.slippage_bps
    assert spread_only.precise_alpha_claims_blocked is True
    assert "partial_broker_calibration_remaining_component_assumed" in spread_only.assumptions
    # A bare class label without fill count or broker authority cannot zero a cost or lift the claim block.
    for provenance in ({}, {"sample_count": 0, "source_authority": "imported_broker_fills"},
                       {"sample_count": 5, "source_authority": "local_paper_ledger"}, {"sample_count": 5}):
        forged = estimate_execution_cost(
            config, "VWCE", 5_000.0,
            calibration={"spread_bps": 0, "slippage_bps": 0, "evidence_class": "imported_broker_fill", **provenance}, **kwargs
        )
        assert forged.spread_bps == base.spread_bps > 0 and forged.slippage_bps == base.slippage_bps > 0
        assert forged.precise_alpha_claims_blocked is True and forged.evidence_class != EVIDENCE_BROKER_FILL


def test_reports_qualify_only_with_modelled_costs_and_enforced_capacity(config, prices, regimes, eur_regimes) -> None:
    direct = run_backtest(config, prices, rebalance_frequency_days=42)
    assert direct.metadata["qualifying_cost_regime"] is False
    assert "capacity_not_enforced" in direct.metadata["qualification_blockers"]
    qualified = eur_regimes.reports[COST_REGIME_MODELLED]
    assert qualified.metadata["qualifying_cost_regime"] is True and qualified.metadata["qualification_blockers"] == []
    # The three-regime workflow runs all three through the supplied runner, side by side.
    calls: list[dict[str, object]] = []

    def runner(selected_config, selected_prices, **kwargs):
        calls.append(kwargs)
        return run_backtest(selected_config, selected_prices, rebalance_frequency_days=42, **kwargs)

    eur_ids = {item.id for item in config.universe.etfs if item.currency == "EUR"}
    routed = run_backtest_cost_regimes(config, prices[prices["etf_id"].isin(eur_ids)], runner=runner)
    assert len(calls) == 3 and all(call["enforce_capacity"] is True for call in calls)
    assert set(routed.comparison["cost_regime"]) == {COST_REGIME_MODELLED, COST_REGIME_LEGACY, COST_REGIME_STRESS}
    assert routed.comparison.groupby("cost_regime")["qualifying_cost_regime"].first().to_dict() == {
        COST_REGIME_MODELLED: True, COST_REGIME_LEGACY: False, COST_REGIME_STRESS: False,
    }


def test_future_known_fundamentals_are_excluded_from_the_decision(prices) -> None:
    from etf_cockpit.signals.quality_momentum import build_quality_momentum_frame

    ids = sorted(prices["etf_id"].unique())[:3]
    panel = prices[prices["etf_id"].isin(ids)]
    decision = pd.Timestamp(panel["date"].max()).date()

    def fundamentals(available_at: object) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "instrument_id": ids,
                "as_of_date": [str(decision - pd.Timedelta(days=100))] * len(ids),
                "available_at": [str(available_at)] * len(ids),
                "source_id": ["official"] * len(ids),
                "source_authority": ["official_filing"] * len(ids),
                "sector": ["s"] * len(ids),
            }
        )

    future = build_quality_momentum_frame(panel, fundamentals(decision + pd.Timedelta(days=30)), as_of_date=decision)
    known = build_quality_momentum_frame(panel, fundamentals(decision - pd.Timedelta(days=30)), as_of_date=decision)
    assert (future["status"] == "unavailable").all()
    assert future["reason"].eq("unavailable_missing_official_availability_timestamp").all()
    assert future["quality_score"].isna().all() and future["composite_score"].isna().all()
    # The same rows, once known, are no longer excluded for availability.
    assert not known["reason"].eq("unavailable_missing_official_availability_timestamp").any()


def test_d011_adv_participation_capacity_is_derived_from_eur_adv(config) -> None:
    """D011 (summary-only): the re-derivable part is ADV participation capacity.

    The estimate reports capacity against the configured participation of the
    EUR ADV; an unavailable ADV is reported, never assumed; a multi-day fill
    needs as many sessions as the order exceeds one session's capped value.
    """

    cap = config.costs.cost_model.max_participation_rate
    adv = 100_000.0
    within = estimate_execution_cost(config, "VWCE", adv * cap * 0.5, adv_eur=adv, daily_volatility=0.01)
    beyond = estimate_execution_cost(config, "VWCE", adv * cap * 2.0, adv_eur=adv, daily_volatility=0.01)
    missing = estimate_execution_cost(config, "VWCE", 5_000.0, daily_volatility=0.01)
    assert within.capacity_status == "within_configured_participation"
    assert beyond.capacity_status == "exceeds_configured_participation"
    assert beyond.capacity_eur == pytest.approx(adv * cap)
    assert missing.capacity_status == "unavailable_missing_adv"
    partial = fill_feasibility(
        adv * cap * 2.0, day_volume_shares=adv / 10.0, price_eur=10.0, adv_eur=adv, participation_rate=cap
    )
    assert partial.status == "partial_fill" and partial.days_to_fill == 2


def test_cost_regime_comparison_is_strict_json_safe() -> None:
    import json

    from etf_cockpit.application.backtest_service import _json_safe_records

    frame = pd.DataFrame(
        {"cost_regime": ["a", "b"], "sharpe": [float("nan"), 1.5], "cagr": [float("inf"), -float("inf")], "n": [1, 2]}
    )
    records = _json_safe_records(frame)
    assert records[0]["sharpe"] is None and records[0]["cagr"] is None and records[1]["sharpe"] == 1.5
    json.dumps(records, allow_nan=False)


def test_qualification_needs_volume_evidence_for_every_capacity_checked_instrument(config, prices) -> None:
    eur_ids = sorted(item.id for item in config.universe.etfs if item.currency == "EUR" and item.id in set(prices["etf_id"]))
    panel = prices[prices["etf_id"].isin(eur_ids)].copy()
    assert run_backtest(config, panel, rebalance_frequency_days=42, enforce_capacity=True).metadata["qualifying_cost_regime"] is True
    panel.loc[panel["etf_id"] == eur_ids[0], "volume"] = float("nan")
    report = run_backtest(config, panel, rebalance_frequency_days=42, enforce_capacity=True)
    assert report.metadata["capacity_enforcement"] == "enforced"
    assert report.metadata["qualifying_cost_regime"] is False
    assert "liquidity_evidence_unavailable" in report.metadata["qualification_blockers"]


# --- correction pass 2 ----------------------------------------------------


def test_fully_blocked_orders_are_logged_and_the_trade_log_keeps_its_columns(config, prices) -> None:
    from io import StringIO

    zero = prices.copy()
    zero["volume"] = 0.0
    report = run_backtest(config, zero, rebalance_frequency_days=42, enforce_capacity=True)
    log = report.trade_log
    assert not log.empty and (log["turnover"] == 0.0).all() and (log["unfilled_eur"] > 0.0).all()
    assert log["capacity_fill_status"].str.contains("no_fill").all()
    assert (log["cost_eur"] == 0.0).all() and set(log["remainder_policy"]) == {"cancelled_at_session_end"}
    assert (report.results["trade_count"] == 0).all()  # a blocked order is not a trade
    # With no rows at all the frame still carries the schema and survives the CSV round trip.
    empty_log = report.trade_log.iloc[0:0]
    assert list(pd.read_csv(StringIO(empty_log.to_csv(index=False))).columns) == list(log.columns)
    no_volume = run_backtest(config, prices.assign(volume=float("nan")), rebalance_frequency_days=42, enforce_capacity=True)
    assert "strategy" in no_volume.trade_log.columns and "turnover" in no_volume.trade_log.columns


def test_quality_baselines_without_evidence_are_unavailable_not_all_cash_numbers(config, prices) -> None:
    from etf_cockpit.backtest.benchmarks import investable_comparator_summary

    report = run_backtest(config, prices, rebalance_frequency_days=42)
    assert report.metadata["quality_momentum_evidence_available_rows"] == 0
    baselines = report.metadata["investable_comparators"]["baselines"]
    for label in ("QV", "QVM"):
        assert baselines[label]["status"] == "unavailable" and baselines[label]["reason"]
        assert "final_value_eur" not in baselines[label]
    assert baselines["v3"]["status"] == "available" and baselines["v3"]["final_value_eur"] > 0
    summary = investable_comparator_summary(
        {"quality_only": {"final_value_eur": 10_000.0}, "signal_strategy": {"final_value_eur": 10_500.0}},
        initial_value_eur=10_000.0, vwce=None, universe=["A"], start="2026-01-01", end="2026-06-26",
        cost_regime="modelled", cost_model_id="m", unavailable_strategies={"signal_strategy": "never held a position"},
    )
    assert summary["baselines"]["v3"]["status"] == "unavailable" and summary["baselines"]["QV"]["status"] == "available"


# --- correction pass 3 ----------------------------------------------------


def _eur_universe_with_equity_certificate(config, prices):
    """EUR-only panel plus one equity certificate that is re-labelled EUR-quoted."""

    certificate = next(
        item for item in config.universe.etfs
        if str(item.instrument_type or "").casefold() == "equity_certificate" and item.id in set(prices["etf_id"])
    )
    eur_ids = {
        item.id for item in config.universe.etfs
        if item.currency == "EUR" and str(item.instrument_type or "").casefold() != "equity_certificate"
    }
    etfs = [
        item.model_copy(update={"currency": "EUR"}) if item.id == certificate.id else item for item in config.universe.etfs
    ]
    patched = config.model_copy(update={"universe": config.universe.model_copy(update={"etfs": etfs})})
    return patched, prices[prices["etf_id"].isin(eur_ids | {certificate.id})], certificate.id


def test_equity_certificate_without_quote_fills_flagged_cost_estimated_not_held_as_cash(config, prices) -> None:
    patched, panel, certificate_id = _eur_universe_with_equity_certificate(config, prices)
    report = run_backtest(patched, panel, rebalance_frequency_days=42, enforce_capacity=True)
    assert "fx_unavailable_instruments_unfillable" not in report.metadata["qualification_blockers"]
    assert "manual_quote_instruments_unfillable" not in report.metadata["qualification_blockers"]
    assert report.metadata["cost_estimated_instruments"] == [certificate_id]
    assert "manual_quote_required" not in report.metadata["initial_allocation"]["equal_weight"]["fill_status"]
    assert report.trade_log["cost_estimated"].any()
    # Without the certificate in the universe the same EUR run still qualifies.
    clean = panel[panel["etf_id"] != certificate_id]
    assert run_backtest(config, clean, rebalance_frequency_days=42, enforce_capacity=True).metadata[
        "qualifying_cost_regime"
    ] is True


def test_never_filled_baselines_and_vwce_are_unavailable_not_all_cash_results(config, prices, monkeypatch) -> None:
    from etf_cockpit.backtest import engine as engine_module

    benchmark_id = str(prices["etf_id"].iloc[0])
    monkeypatch.setattr(engine_module, "_validated_benchmark_data_id", lambda *_args, **_kwargs: benchmark_id)
    zero = prices.assign(volume=0.0)
    report = run_backtest(config, zero, rebalance_frequency_days=42, enforce_capacity=True)
    assert (report.results["trade_count"] == 0).all()
    comparators = report.metadata["investable_comparators"]
    assert comparators["baselines"]["v3"]["status"] == "unavailable" and comparators["baselines"]["v3"]["reason"]
    assert "final_value_eur" not in comparators["baselines"]["v3"]
    assert comparators["baselines"]["top_n_long_only"]["status"] == "unavailable"
    assert comparators["vwce"]["status"] == "unavailable" and comparators["vwce"]["reason"]
    assert "final_value_eur" not in comparators["vwce"]
    # A run that does fill keeps its comparators available.
    filled = run_backtest(config, prices, rebalance_frequency_days=42, enforce_capacity=True)
    assert filled.metadata["investable_comparators"]["baselines"]["v3"]["status"] == "available"


def test_same_universe_dates_costs_is_derived_from_the_data_never_asserted() -> None:
    def panel(with_cost: bool, with_cash: bool = True) -> pd.DataFrame:
        rows = []
        for day in (1, 2, 3):
            for number in range(1, 8):
                row = {
                    "decision_time": f"2024-01-0{day}T23:59:59Z", "instrument_id": f"E{number}",
                    "ranker": "balanced_challenger", "score": float(number), "net_return": 0.01 * number - 0.03,
                    "benchmark_net_return": 0.0, "cash_net_return": 0.0 if with_cash else float("nan"),
                    "sector": "s", "size_bucket": "b",
                }
                if with_cost:
                    row["round_trip_cost_bps"] = 5.0
                rows.append(row)
        return pd.DataFrame(rows)

    policy = replace(
        load_rank_validation_policy(), minimum_universe_support=5, top_n=3, bottom_n=3, minimum_group_support=1
    )

    def flag(frame: pd.DataFrame):
        return rank_validation_metrics(frame, "balanced_challenger", policy=policy)["investable_long_only"][
            "same_universe_dates_costs"
        ]

    assert flag(panel(with_cost=True)) is True
    assert flag(panel(with_cost=False)) is None  # costs are not evidenced on the rows
    assert flag(panel(with_cost=True, with_cash=False)) is None  # cash comparator missing
