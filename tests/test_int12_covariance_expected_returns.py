"""ISSUE-0193 (INT-12): OOS-selected optimiser covariance and Black-Litterman with no views."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.portfolio.expected_returns import (
    BlackLittermanView,
    black_litterman_posterior,
    equilibrium_returns,
)
from etf_cockpit.portfolio.optimiser import COVARIANCE_SHRINKAGE_MODES, PortfolioOptimiser
from etf_cockpit.portfolio.robust_risk import ANNUALISATION_FACTOR, _covariance_estimators, _out_of_sample_selection


def _returns(rows: int = 160, assets: int = 4, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    scales = np.linspace(0.008, 0.02, assets)
    common = rng.normal(0.0, 0.006, size=(rows, 1))
    data = rng.normal(0.0004, scales, size=(rows, assets)) + common
    index = pd.bdate_range("2024-01-01", periods=rows)
    return pd.DataFrame(data, index=index, columns=[f"E{i}" for i in range(assets)])


def test_oos_selected_covariance_names_the_selected_estimator_and_ignores_rows_after_the_cutoff() -> None:
    assert "oos_selected" in COVARIANCE_SHRINKAGE_MODES
    returns = _returns()
    cutoff = returns.index[119]
    window = returns.loc[:cutoff]
    # Rows after the decision date are wild; they must not move the selection or the matrix.
    future = returns.loc[returns.index > cutoff] * 50.0
    with_future = pd.concat([window, future])

    optimiser = PortfolioOptimiser(with_future.loc[:cutoff], covariance_shrinkage="oos_selected")
    expected_name = _out_of_sample_selection(window, None, ewma_lambda=0.97, shrinkage_alpha=0.10)[1]
    assert optimiser.covariance_diagnostics["status"] == "available"
    assert optimiser.covariance_diagnostics["estimator"] == expected_name
    assert optimiser.covariance_diagnostics["covariance_mode"] == "oos_selected"
    chosen = _covariance_estimators(window, None, ewma_lambda=0.97, shrinkage_alpha=0.10)[0][expected_name]
    np.testing.assert_allclose(optimiser.covariance.to_numpy(float), chosen.to_numpy(float), rtol=1e-8)
    # Already annualised: the 252 factor is not applied a second time.
    assert float(np.trace(optimiser.covariance)) < ANNUALISATION_FACTOR * 0.05 * len(window.columns)

    reference = PortfolioOptimiser(window, covariance_shrinkage="oos_selected")
    assert reference.covariance_diagnostics["estimator"] == optimiser.covariance_diagnostics["estimator"]

    short = PortfolioOptimiser(returns.iloc[:25], covariance_shrinkage="oos_selected")
    assert short.covariance.empty and short.covariance_diagnostics["status"] != "available"


def test_black_litterman_with_no_views_returns_the_equilibrium_prior() -> None:
    covariance = _returns().cov() * ANNUALISATION_FACTOR
    weights = pd.Series([0.4, 0.3, 0.2, 0.1], index=covariance.index)
    prior = equilibrium_returns(covariance, weights, risk_aversion=2.5)
    np.testing.assert_allclose(prior.to_numpy(float), 2.5 * covariance.to_numpy(float) @ weights.to_numpy(float))

    for no_views in (None, ()):
        posterior = black_litterman_posterior(prior, covariance, no_views)
        pd.testing.assert_series_equal(posterior, prior)

    view = BlackLittermanView(weights={"E0": 1.0}, expected_return=float(prior["E0"]) + 0.05, variance=1e-4)
    moved = black_litterman_posterior(prior, covariance, [view])
    assert moved["E0"] > prior["E0"]
    with pytest.raises(ValueError):
        black_litterman_posterior(prior, covariance, [BlackLittermanView({"E0": 1.0}, 0.1, 0.0)])


def test_skfolio_backend_refuses_oos_selected_instead_of_using_another_covariance() -> None:
    pytest.importorskip("skfolio")
    solution = PortfolioOptimiser(_returns(), covariance_shrinkage="oos_selected").solve("sk_mean_variance")
    assert solution.status == "unavailable"
    assert "covariance_mode_unsupported:oos_selected" in str(solution.diagnostics)
