"""Bughunt D (#979): portfolio risk estimators in robust_risk / risk_analytics / risk page."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.portfolio import robust_risk
from etf_cockpit.portfolio.factor_risk import build_factor_risk_report
from etf_cockpit.portfolio.risk_analytics import return_correlation_matrix
from etf_cockpit.portfolio.robust_risk import build_robust_risk_report
from test_factor_risk import _fixture as _factor_fixture


def _prices(series: dict[str, np.ndarray], *, start: str = "2025-01-01", volume: float | None = None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for etf_id, log_returns in series.items():
        dates = pd.bdate_range(start, periods=len(log_returns) + 1)
        values = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(log_returns)]))
        for dt, value in zip(dates, values):
            row: dict[str, object] = {"date": dt.date(), "etf_id": etf_id, "adjusted_close": float(value)}
            if volume is not None:
                row["volume"] = volume
            rows.append(row)
    return pd.DataFrame(rows)


def _random_series(count: int = 60, seed: int = 3) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {"A": rng.normal(0.0003, 0.01, count), "B": rng.normal(0.0002, 0.012, count)}


def _allocation(**weights: float) -> pd.DataFrame:
    return pd.DataFrame({"etf_id": list(weights), "current_weight": list(weights.values())})


# --- the five focused tests from the issue -------------------------------------------------------


def test_d008_n001_factor_covariance_fit_excludes_validation_window() -> None:
    prices, allocation, features = _factor_fixture()
    factor_report = build_factor_risk_report(prices, allocation, features)
    report = build_robust_risk_report(prices, allocation, factor_report=factor_report, bootstrap_reps=0)

    assert not report["covariances"]["factor_model"].empty
    assert "factor_model" not in set(report["estimator_comparison"]["estimator"])
    assert report["selected_estimator"] != "factor_model"
    assert report["diagnostics"]["factor_model_validation"] == robust_risk.FACTOR_MODEL_VALIDATION_NOTE

    # The held-out comparison cannot depend on a factor fit that already saw the validation window.
    tampered = dict(factor_report)
    tampered["factor_covariance"] = factor_report["factor_covariance"] * 50.0
    returns = report["returns"]
    first = robust_risk._out_of_sample_selection(returns, factor_report, ewma_lambda=0.97, shrinkage_alpha=0.1)
    second = robust_risk._out_of_sample_selection(returns, tampered, ewma_lambda=0.97, shrinkage_alpha=0.1)
    pd.testing.assert_frame_equal(first[0], second[0])
    assert first[1] == second[1]


def test_d008_n002_max_drawdown_starts_from_initial_wealth() -> None:
    steady_loss = np.full(40, -0.005)
    prices = _prices({"A": steady_loss, "B": np.random.default_rng(1).normal(0.0, 0.01, 40)})
    report = build_robust_risk_report(prices, _allocation(A=1.0, B=0.0), bootstrap_reps=0)

    expected = float(np.exp(steady_loss.sum()) - 1.0)
    assert report["tail_risk"]["portfolio"]["max_drawdown"] == pytest.approx(expected)


def test_d108_n001_unpriced_half_holding_gives_partial_coverage_not_a_silent_drop() -> None:
    report = build_robust_risk_report(_prices(_random_series()), _allocation(A=0.25, B=0.25, C=0.5), bootstrap_reps=0)

    portfolio = report["portfolio"]
    assert report["status"] == "partial"
    assert "unpriced_holdings_excluded" in report["warnings"]
    assert portfolio["unpriced_instruments"] == ["C"]
    assert portfolio["weight_coverage"] == pytest.approx(0.5)
    assert portfolio["unpriced_weight"] == pytest.approx(0.5)
    # The headline volatility is withheld; the priced subset stays visible under its own name.
    assert portfolio["annualised_volatility"] is None
    assert portfolio["priced_annualised_volatility"] > 0


def test_d108_n002_missing_price_day_is_a_gap_not_a_bridged_return() -> None:
    prices = _prices(_random_series(count=40, seed=11))
    gap_date = sorted(prices["date"].unique())[20]
    gapped = prices[~((prices["etf_id"] == "B") & (prices["date"] == gap_date))]

    returns = robust_risk._return_matrix(gapped, window=0)
    assert returns["B"].isna().sum() == 2  # the gap day and the day after: no multi-day return
    assert pd.Timestamp(gap_date) in returns.index and np.isnan(returns.loc[pd.Timestamp(gap_date), "B"])

    pivot = gapped.pivot(index="date", columns="etf_id", values="adjusted_close")
    gap_free = np.log(pivot / pivot.shift(1)).dropna(how="any")
    expected = float(gap_free["A"].corr(gap_free["B"]))
    bridged_pivot = pivot.dropna()
    bridged = np.log(bridged_pivot / bridged_pivot.shift(1)).dropna()
    assert expected != pytest.approx(float(bridged["A"].corr(bridged["B"])), abs=1e-6)  # the defect would show

    matrix = return_correlation_matrix(gapped, ["A", "B"], window=0)
    assert matrix.attrs["status"] == "available"
    assert matrix.loc["A", "B"] == pytest.approx(expected)


def test_d108_n004_tail_dependence_is_symmetric_under_column_swap_with_tied_quantiles() -> None:
    rng = np.random.default_rng(5)
    tied = np.where(np.arange(60) < 40, -0.01, 0.01)  # 40 tied observations at the 5% quantile
    frame = pd.DataFrame({"TIED": tied, "CONT": rng.normal(0.0, 0.01, 60)})

    forward = robust_risk._tail_dependence(frame)
    swapped = robust_risk._tail_dependence(frame[["CONT", "TIED"]])
    assert forward["mean_lower_tail_dependence"] == pytest.approx(swapped["mean_lower_tail_dependence"])
    assert 0.0 <= forward["mean_lower_tail_dependence"] <= 1.0


# --- remaining findings -------------------------------------------------------------------------


def test_d008_n004_var_is_loss_positive_and_floored_with_explicit_signed_quantile() -> None:
    returns = pd.DataFrame({"A": np.linspace(0.001, 0.02, 40), "B": np.linspace(0.002, 0.03, 40)})
    portfolio = robust_risk._tail_risk_report(returns, pd.Series({"A": 0.5, "B": 0.5}), pd.DataFrame(), None)["portfolio"]

    assert portfolio["var_sign_convention"] == "loss_positive_floored_at_zero"
    assert portfolio["return_quantile_05"] > 0
    assert portfolio["var_95"] == 0.0
    assert portfolio["expected_shortfall_95"] == 0.0


def test_d008_n005_single_bootstrap_repetition_is_insufficient_not_a_nan_sd() -> None:
    prices = _prices(_random_series(count=60))
    bootstrap = build_robust_risk_report(prices, _allocation(A=0.5, B=0.5), bootstrap_reps=1)["bootstrap"]

    assert bootstrap["status"] == "unavailable"
    assert bootstrap["reason_code"] == "bootstrap_repetitions_insufficient"
    assert "standard_deviation" not in bootstrap
    two = build_robust_risk_report(prices, _allocation(A=0.5, B=0.5), bootstrap_reps=2)["bootstrap"]
    assert two["status"] == "available" and np.isfinite(two["standard_deviation"])


def test_d108_n003_downside_deviation_uses_all_observations_against_zero_target() -> None:
    values = np.array([-0.01, -0.01, -0.01, -0.01, 0.02, 0.03, 0.01, 0.0])
    returns = pd.DataFrame({"A": values, "B": values})
    portfolio = robust_risk._tail_risk_report(returns, pd.Series({"A": 0.5, "B": 0.5}), pd.DataFrame(), None)["portfolio"]

    expected = float(np.sqrt(np.mean(np.minimum(values, 0.0) ** 2) * 252.0))
    assert expected > 0
    assert portfolio["downside_vol_ann"] == pytest.approx(expected)  # old negative-only SD of equal losses was 0


def test_d108_n005_ewma_effective_sample_is_the_weighted_ess() -> None:
    report = build_robust_risk_report(_prices(_random_series(count=300, seed=8)), _allocation(A=0.5, B=0.5), bootstrap_reps=0)
    meta = report["diagnostics"]["estimators"]
    count = meta["ewma"]["sample_count"]
    weights = 0.97 ** np.arange(count - 1, -1, -1)
    kish = float(weights.sum() ** 2 / (weights**2).sum())

    assert meta["ewma"]["effective_sample"] == pytest.approx(kish)
    assert meta["ewma"]["effective_sample"] < count
    assert meta["sample"]["effective_sample"] == count


def test_d111_n003_liquidity_mean_uses_the_same_lookback_as_returns() -> None:
    prices = _prices(_random_series(count=120, seed=2), volume=1_000.0)
    old = pd.to_datetime(prices["date"]) < pd.Timestamp("2025-04-01")
    prices.loc[old, "volume"] = 1_000_000.0  # very liquid long ago, thin inside the window
    window = robust_risk._return_matrix(prices, window=40).dropna(how="any")
    weights = np.array([0.5, 0.5])

    windowed = robust_risk._liquidity_adjusted_risk(prices, None, window, weights)
    recent_only = prices[pd.to_datetime(prices["date"]).between(window.index.min(), window.index.max())]
    reference = robust_risk._liquidity_adjusted_risk(recent_only, None, window, weights)
    full_history = prices.copy()
    assert windowed["multiplier"] == pytest.approx(reference["multiplier"])
    assert windowed["multiplier"] > 1.0
    # The unwindowed mean would have understated the multiplier (older rows are far more liquid).
    average = full_history.assign(v=full_history["adjusted_close"] * full_history["volume"]).groupby("etf_id")["v"].mean()
    unwindowed = float(np.sqrt(1.0 + np.mean(np.clip(weights / average.to_numpy(float) * 10_000.0, 0.0, 100.0))))
    assert windowed["multiplier"] > unwindowed


@pytest.mark.parametrize("bad", ["abc", None, float("nan"), float("inf")])
def test_d_c2_s08_n001_invalid_explicit_weight_makes_robust_risk_unavailable(bad: object) -> None:
    allocation = pd.DataFrame({"etf_id": ["A", "B"], "current_weight": [bad, 0.5]})
    report = build_robust_risk_report(_prices(_random_series()), allocation, bootstrap_reps=0)

    assert report["status"] == "unavailable"
    assert report["reason_code"] == "invalid_allocation_weight"
    assert report["portfolio"]["annualised_volatility"] is None


def test_d_c2_s08_n005_short_positions_are_not_clipped_out_of_the_liquidity_multiplier() -> None:
    prices = _prices(_random_series(count=60), volume=500.0)
    window = robust_risk._return_matrix(prices, window=0).dropna(how="any")

    long_only = robust_risk._liquidity_adjusted_risk(prices, None, window, np.array([0.5, 0.5]))
    long_short = robust_risk._liquidity_adjusted_risk(prices, None, window, np.array([-0.5, 0.5]))
    assert long_short["multiplier"] == pytest.approx(long_only["multiplier"])
    assert long_short["multiplier"] > 1.0


def test_risk_page_binds_computed_tail_metrics_and_keeps_unavailable_with_reason() -> None:
    from etf_cockpit.app.pages.risk import _tail_metric_tiles

    report = build_robust_risk_report(_prices(_random_series(), volume=10_000.0), _allocation(A=0.5, B=0.5), bootstrap_reps=0)
    tiles = _tail_metric_tiles(report)
    assert len(tiles) == 6
    text = repr([_texts(tile) for tile in tiles])
    assert "Unavailable" not in text and "No existing result provides" not in text

    empty = _tail_metric_tiles({"message": "Joint returns missing.", "tail_risk": {"status": "unavailable"}})
    assert all("Unavailable" in repr(_texts(tile)) and "Joint returns missing." in repr(_texts(tile)) for tile in empty)


def _texts(control: object) -> list[str]:
    found: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        found.append(value)
    for attribute in ("content", "controls"):
        child = getattr(control, attribute, None)
        if child is None:
            continue
        for item in child if isinstance(child, list) else [child]:
            found.extend(_texts(item))
    return found
