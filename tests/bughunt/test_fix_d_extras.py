"""Edge-case guards for the group D fixes (S2-03..S2-08)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tests.bughunt.test_repro_s2 import _two_asset_prices


def test_s2_03_absent_allocation_is_labelled_equal_weight_fallback() -> None:
    from etf_cockpit.portfolio.robust_risk import build_robust_risk_report

    report = build_robust_risk_report(_two_asset_prices(), None, bootstrap_reps=0)
    assert report["portfolio"]["weight_sum"] == 1.0
    assert str(report["portfolio"]["weights_basis"]).startswith("equal_weight_illustrative_fallback")
    assert any(str(w).startswith("equal_weight_illustrative_fallback") for w in report["warnings"])


def test_s2_03_cash_only_allocation_is_not_labelled_fallback() -> None:
    from etf_cockpit.portfolio.robust_risk import build_robust_risk_report

    allocation = pd.DataFrame({"etf_id": ["A", "B"], "current_weight": [0.0, 0.0]})
    report = build_robust_risk_report(_two_asset_prices(), allocation, bootstrap_reps=0)
    assert report["portfolio"]["weights_basis"] == "allocation_weights"
    assert report["portfolio"]["annualised_volatility"] == 0.0


def test_s2_05_non_finite_historical_return_is_not_covered() -> None:
    from etf_cockpit.portfolio.stress_testing import StressScenario, run_stress_scenario

    allocation = pd.DataFrame({"instrument_id": ["A", "B"], "weight": [0.5, 0.5]})
    hist = pd.DataFrame(
        {"date": ["2024-02-01"] * 2, "instrument_id": ["A", "B"], "adjusted_return": [-0.1, float("nan")]}
    )
    result = run_stress_scenario(
        StressScenario("s", "s", {"equity": 0}, historical_date="2024-02-01"), allocation, historical_returns=hist
    )
    assert result.status == "partial"
    assert result.total_pnl is not None and np.isfinite(result.total_pnl)


def test_s2_06_materially_negative_eigenvalue_stays_rejected() -> None:
    from etf_cockpit.portfolio.forecast_aggregation import _correlation_root

    matrix = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    assert np.linalg.eigvalsh(matrix).min() < -0.1
    assert _correlation_root(matrix) is None


def test_s2_06_clipped_root_reproduces_matrix() -> None:
    from etf_cockpit.portfolio.forecast_aggregation import _correlation_root

    matrix = np.ones((3, 3))
    root = _correlation_root(matrix)
    assert root is not None and np.allclose(root @ root.T, matrix, atol=1e-12)


def test_s2_07_unheld_instruments_do_not_dilute_factor_exposure() -> None:
    from etf_cockpit.portfolio.attribution import _factor_attribution

    dates = pd.bdate_range("2024-01-01", periods=4)
    daily = pd.DataFrame({"wealth": [1.0, 1.0, 1.0, 1.0]}, index=dates)
    factor_returns = pd.DataFrame({"date": dates, "factor": "momentum", "factor_return": 0.01})
    exposures = pd.DataFrame({"momentum": [2.0, -2.0]}, index=["A", "B"])
    result = _factor_attribution(daily, daily["wealth"], factor_returns, exposures, pd.Series({"A": 1.0}))
    # Held A only: exposure 2.0 x 0.01 x wealth 1.0 over the 3 days with a prior wealth observation.
    assert np.isclose(float(result.loc[0, "contribution"]), 3 * 0.01 * 2.0)
