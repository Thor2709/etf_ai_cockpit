from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.portfolio.optimiser import (
    METHODS,
    OptimiserConstraints,
    PortfolioOptimiser,
    optimiser_fingerprint,
    returns_from_adjusted_prices,
)


def _returns(rows: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    return pd.DataFrame(
        rng.normal(0.0003, [0.008, 0.012, 0.018], size=(rows, 3)),
        columns=["AAA", "BBB", "CCC"],
    )


def test_all_methods_are_reproducible_feasible_and_reconcile_weights() -> None:
    optimiser = PortfolioOptimiser(_returns())
    constraints = OptimiserConstraints(cash_weight=0.1, min_weight=0.05, max_weight=0.6)

    first = {method: optimiser.solve(method, constraints=constraints) for method in METHODS}
    second = {method: optimiser.solve(method, constraints=constraints) for method in METHODS}

    assert all(solution.feasible for solution in first.values())
    assert all(np.isclose(solution.weight_sum, 0.9) for solution in first.values())
    assert all(first[method].weights.equals(second[method].weights) for method in METHODS)
    assert optimiser_fingerprint(first["hrp"]) == optimiser_fingerprint(second["hrp"])


def test_group_and_turnover_constraints_are_reported() -> None:
    optimiser = PortfolioOptimiser(_returns())
    constraints = OptimiserConstraints(
        max_weight=0.8,
        turnover_limit=0.15,
        group_labels={"AAA": "equity", "BBB": "equity", "CCC": "bond"},
        group_max_weights={"equity": 0.65},
    )
    current = {"AAA": 0.55, "BBB": 0.10, "CCC": 0.35}
    solution = optimiser.solve("robust_mean_risk", constraints=constraints, current_weights=current)

    assert solution.feasible
    assert float(solution.weights[["AAA", "BBB"]].sum()) <= 0.65 + 1e-6
    assert float(np.abs(solution.weights - pd.Series(current)).sum()) <= 0.15 + 1e-6
    assert "group:equity" in solution.diagnostics["binding_constraints"]


def test_unknown_method_has_visible_equal_weight_fallback() -> None:
    solution = PortfolioOptimiser(_returns()).solve("broken_solver")

    assert solution.status == "fallback"
    assert solution.feasible
    assert "visible_equal_weight_fallback" in solution.warnings
    assert solution.diagnostics["fallback_method"] == "equal_weight"


def test_held_out_comparison_keeps_equal_weight_baseline_and_sensitivity() -> None:
    optimiser = PortfolioOptimiser(_returns())
    comparison = optimiser.compare(["minimum_variance"])
    sensitivity = optimiser.sensitivity("minimum_variance", shock=0.1)

    assert list(comparison["method"]) == ["equal_weight", "minimum_variance"]
    assert set(comparison["status"]) <= {"success", "fallback"}
    assert 0 <= sensitivity["max_abs_weight_change"] <= 1


def test_returns_require_adjusted_close_and_never_substitute_raw_close() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=3),
            "etf_id": ["AAA", "AAA", "AAA"],
            "close": [100, 105, 110],
        }
    )
    assert returns_from_adjusted_prices(prices).empty

    prices["adjusted_close"] = [100, 105, 110]
    returns = returns_from_adjusted_prices(prices)
    assert list(returns.columns) == ["AAA"]
    assert len(returns) == 2
