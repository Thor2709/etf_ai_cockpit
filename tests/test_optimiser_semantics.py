"""Issue #947: optimiser labels, covariance shrinkage, CVaR limits and bughunt regressions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.portfolio.optimiser import (
    METHOD_ALIASES,
    METHODS,
    MIN_CVAR_TAIL_OBSERVATIONS,
    OptimiserConstraints,
    PortfolioOptimiser,
    returns_from_adjusted_prices,
)
from etf_cockpit.portfolio.robust_risk import ledoit_wolf_covariance


def _returns(rows: int = 160, assets: int = 4, drift: float = 0.002, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    scales = np.linspace(0.008, 0.02, assets)
    common = rng.normal(0.0, 0.006, size=(rows, 1))
    data = rng.normal(drift, scales, size=(rows, assets)) + common
    return pd.DataFrame(data, columns=[f"E{index}" for index in range(assets)])


def test_no_method_is_named_hrp_unless_canonical() -> None:
    assert not [name for name in METHODS if "hrp" in name and not name.endswith("_like")]
    assert "hrp_like" in METHODS and METHOD_ALIASES == {"hrp": "hrp_like"}
    # The retired id is still accepted, resolves to the honest name and says so.
    solution = PortfolioOptimiser(_returns()).solve("hrp")
    assert solution.method == "hrp_like"
    assert any(item.startswith("deprecated_method_alias:hrp->hrp_like") for item in solution.warnings)
    assert "not canonical hierarchical risk parity" in str(solution.diagnostics["method_note"])


@pytest.mark.parametrize("shrinkage", ["ledoit_wolf", "none"])
def test_covariance_is_psd_after_shrinkage_and_flags_insufficient_sample(shrinkage: str) -> None:
    # More assets than the rank of the sample: the raw covariance is singular.
    wide = _returns(rows=30, assets=40)
    optimiser = PortfolioOptimiser(wide, covariance_shrinkage=shrinkage)
    eigenvalues = np.linalg.eigvalsh(optimiser.covariance.to_numpy(float))
    assert eigenvalues.min() > 0
    assert optimiser.covariance_diagnostics["positive_semidefinite"] is True
    if shrinkage == "ledoit_wolf":
        assert 0.0 < float(optimiser.covariance_diagnostics["shrinkage_intensity"]) <= 1.0
    daily, details = ledoit_wolf_covariance(wide)
    assert details["status"] == "available" and np.linalg.eigvalsh(daily.to_numpy(float)).min() > 0

    short = PortfolioOptimiser(_returns(rows=10))
    solution = short.solve("minimum_variance")
    assert short.covariance.empty and short.covariance_diagnostics["status"] == "insufficient_sample"
    assert solution.status == "unavailable" and solution.weights.empty
    assert solution.diagnostics["reason_code"] == "covariance_unavailable"
    assert "insufficient_sample" in str(solution.diagnostics["reason_detail"])


def test_cvar_with_too_few_observations_is_insufficient_not_equal_weight() -> None:
    for rows in (3, 40, 70):  # tail sizes 1..4 at the 5% level, and the bughunt short path
        solution = PortfolioOptimiser(_returns(rows=rows, assets=3)).solve("cvar")
        assert solution.status == "unavailable" and solution.weights.empty and not solution.feasible
        assert solution.objective is None
    solution = PortfolioOptimiser(_returns(rows=70, assets=3)).solve("cvar")
    assert solution.diagnostics["sample_status"] == "insufficient"
    assert solution.diagnostics["tail_observations"] < MIN_CVAR_TAIL_OBSERVATIONS
    assert solution.diagnostics["reason_code"] == "insufficient_tail_sample"
    enough = PortfolioOptimiser(_returns(rows=200, assets=3)).solve("cvar")
    assert enough.status == "success" and enough.diagnostics["tail_observations"] == 10


def test_annual_mean_and_annual_covariance_use_the_same_units() -> None:
    data = _returns(rows=200, assets=3)
    plain = PortfolioOptimiser(data, covariance_shrinkage="none")
    np.testing.assert_allclose(plain.covariance.to_numpy(float), data.cov().to_numpy(float) * 252.0, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(plain.historical_mean_annual.to_numpy(float), data.mean().to_numpy(float) * 252.0)
    # The expected return is the historical mean shrunk toward the zero baseline, never "expected alpha".
    factor = plain.return_shrinkage_factor
    assert 0.0 < factor < 1.0
    np.testing.assert_allclose(plain.expected_returns.to_numpy(float), plain.historical_mean_annual.to_numpy(float) * factor)
    assert plain.expected_return_basis == "historical_mean_shrunk_toward_zero_baseline"
    # Ledoit-Wolf stays on the same (annual) scale: the diagonal is within a factor of the sample variance.
    shrunk = PortfolioOptimiser(data)
    ratio = np.diag(shrunk.covariance.to_numpy(float)) / np.diag(plain.covariance.to_numpy(float))
    assert ((ratio > 0.5) & (ratio < 2.0)).all()


def test_robust_penalty_is_an_explicit_standard_error_term_and_fails_closed() -> None:
    optimiser = PortfolioOptimiser(_returns(rows=240, assets=3, drift=0.003))
    solution = optimiser.solve("robust_mean_risk")
    assert solution.status == "success"
    assert solution.diagnostics["penalty"] == "estimation_error_standard_error"
    # Negative scores (D03-C2-N003) are unavailable, never silently equal weights.
    losing = optimiser.solve("robust_mean_risk", expected_returns={"E0": -0.2, "E1": -0.1, "E2": -0.3})
    assert losing.status == "unavailable" and losing.weights.empty
    assert losing.diagnostics["reason_code"] == "no_positive_robust_score"


def test_objective_reports_the_methods_own_criterion() -> None:
    # D03-C2-N002: CVaR / diversification used to report plain variance.
    optimiser = PortfolioOptimiser(_returns(rows=240, assets=3))
    cvar = optimiser.solve("cvar")
    diversification = optimiser.solve("maximum_diversification")
    variance = optimiser.solve("minimum_variance")
    assert cvar.diagnostics["objective_name"] == "cvar_daily_loss_5pct"
    portfolio = optimiser.returns.to_numpy(float) @ cvar.weights.reindex(optimiser.ids).to_numpy(float)
    size = int(np.ceil(0.05 * len(portfolio)))
    assert cvar.objective == pytest.approx(-np.sort(portfolio)[:size].mean())
    assert diversification.diagnostics["objective_name"] == "diversification_ratio"
    assert diversification.objective is not None and diversification.objective >= 1.0 - 1e-9
    assert variance.diagnostics["objective_name"] == "annual_variance"


def test_stringified_mixed_type_ids_are_not_silently_dropped() -> None:
    # D03-C2-N004: column 1 and "1" are distinct instruments that collapse to "1".
    frame = _returns(rows=60, assets=3)
    frame.columns = [1, "1", "E2"]
    solution = PortfolioOptimiser(frame).solve("equal_weight")
    assert solution.status == "unavailable" and solution.weights.empty
    assert "duplicate_instrument_ids:1" in str(solution.diagnostics["reason_detail"])


def test_group_cap_projection_does_not_reject_feasible_allocations() -> None:
    # D103-N001: scaling the capped group below its member minimum used to be clipped back above the cap.
    data = _returns(rows=200, assets=4)
    constraints = OptimiserConstraints(
        min_weight=0.1,
        max_weight=0.6,
        group_labels={"E0": "g", "E1": "g"},
        group_max_weights={"g": 0.2},
    )
    optimiser = PortfolioOptimiser(data)
    for method in ("equal_weight", "minimum_variance", "inverse_volatility", "maximum_diversification"):
        solution = optimiser.solve(method, constraints=constraints)
        assert solution.status == "success", (method, solution.warnings)
        assert solution.feasible and "visible_equal_weight_fallback" not in solution.warnings
        assert float(solution.weights[["E0", "E1"]].sum()) <= 0.2 + 1e-7
        assert solution.weight_sum == pytest.approx(1.0)


def test_capped_minimum_variance_never_exceeds_the_cap() -> None:
    # D103-N002: a capped minimum-variance run produced weights above max_weight.
    rng = np.random.default_rng(5)
    for trial in range(12):
        data = _returns(rows=150, assets=5, seed=100 + trial)
        data["E0"] = data["E0"] * 0.2 + rng.normal(0.0, 0.0005, size=len(data))  # one dominant low-vol asset
        cap = 0.35
        solution = PortfolioOptimiser(data).solve("minimum_variance", constraints=OptimiserConstraints(max_weight=cap))
        assert solution.status == "success"
        assert float(solution.weights.max()) <= cap + 1e-7
        assert float(solution.weights.min()) >= -1e-9
        assert solution.weight_sum == pytest.approx(1.0)


def test_unavailable_solver_reports_none_not_zero_in_comparison() -> None:
    # D103-N003: an unavailable solver used to be scored as a zero-weight portfolio with 0.0 returns.
    comparison = PortfolioOptimiser(_returns(rows=70, assets=3)).compare(("cvar", "minimum_variance"))
    row = comparison.set_index("method").loc["cvar"]
    assert row["status"] == "unavailable"
    assert pd.isna(row["validation_return_ann"]) and pd.isna(row["validation_vol_ann"])
    assert pd.isna(row["weight_sum"]) and pd.isna(row["turnover"])
    assert row["reason_code"] == "insufficient_tail_sample"
    tiny = PortfolioOptimiser(_returns(rows=2, assets=3)).compare(("equal_weight",)).iloc[0]
    assert tiny["status"] == "unavailable" and pd.isna(tiny["validation_return_ann"]) and pd.isna(tiny["weight_sum"])


def test_comparison_reports_references_costs_and_weight_stability() -> None:
    data = _returns(rows=260, assets=4)
    comparison = PortfolioOptimiser(data).compare(METHODS, core_id="E0", cost_bps=25.0, stability_repetitions=6)
    table = comparison.set_index("method")
    assert {"equal_weight", "inverse_volatility", "minimum_variance", "hrp_like", "cvar", "robust_mean_risk", "core_only", "core_sleeve"} <= set(table.index)
    assert table.loc["core_only", "max_weight"] == pytest.approx(1.0)
    assert table.loc["core_sleeve", "max_weight"] == pytest.approx(0.8)
    available = table[table["status"] == "success"]
    assert (available["cost_bps"] == 25.0).all()
    assert np.allclose(available["validation_return_net_ann"], available["validation_return_ann"] - available["turnover"] * 25.0 / 10_000.0)
    stable = table.loc["minimum_variance"]
    assert stable["weight_stability_status"] == "available" and 0.0 <= stable["weight_stability_mean_shift"] <= 1.0
    missing = PortfolioOptimiser(data).compare(("equal_weight",), core_id="VWCE").set_index("method")
    assert missing.loc["core_only", "status"] == "unavailable" and missing.loc["core_only", "reason_code"] == "core_instrument_not_in_universe"


def test_weight_stability_is_deterministic_and_fails_closed() -> None:
    optimiser = PortfolioOptimiser(_returns(rows=200, assets=3))
    first = optimiser.weight_stability("inverse_volatility", repetitions=8)
    second = optimiser.weight_stability("inverse_volatility", repetitions=8)
    assert first == second and first["status"] == "available"
    assert optimiser.weight_stability("cvar", repetitions=1)["status"] == "unavailable"
    short = PortfolioOptimiser(_returns(rows=70, assets=3)).weight_stability("cvar")
    assert short["status"] == "unavailable" and short["reason_code"] == "insufficient_tail_sample"


def test_adjusted_price_returns_feed_the_shrunk_covariance() -> None:
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    rng = np.random.default_rng(3)
    rows = []
    for etf in ("A", "B"):
        price = 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, size=len(dates)))
        rows.extend({"date": day, "etf_id": etf, "adjusted_close": value} for day, value in zip(dates, price))
    optimiser = PortfolioOptimiser(returns_from_adjusted_prices(pd.DataFrame(rows)))
    assert optimiser.covariance_diagnostics["status"] == "available"
    assert optimiser.solve("minimum_variance").status == "success"
