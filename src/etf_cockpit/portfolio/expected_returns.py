"""Equilibrium prior and Black-Litterman posterior expected returns (annual units, numpy only).

Views are an explicit input.  No view source is wired here: forecast-derived views stay
out until a calibrated, promoted forecast contract supplies them, and without views the
posterior is exactly the equilibrium prior.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_RISK_AVERSION = 2.5  # conservative documented default (open parameter)
DEFAULT_TAU = 0.05  # uncertainty of the prior relative to the covariance (open parameter)


@dataclass(frozen=True)
class BlackLittermanView:
    """One view: ``sum(weights[i] * mu[i]) == expected_return`` with an explicit ``variance``."""

    weights: Mapping[str, float]
    expected_return: float
    variance: float


def equilibrium_returns(covariance: pd.DataFrame, market_weights: pd.Series, *, risk_aversion: float = DEFAULT_RISK_AVERSION) -> pd.Series:
    """Reverse-optimised prior ``pi = risk_aversion * Sigma @ w`` for an annual covariance."""

    if covariance.empty or not np.isfinite(covariance.to_numpy(float)).all():
        raise ValueError("covariance must be a finite, non-empty matrix")
    if not math.isfinite(risk_aversion) or risk_aversion <= 0:
        raise ValueError("risk_aversion must be a positive finite number")
    if set(market_weights.index) != set(covariance.index):
        raise ValueError("market_weights must name exactly the covariance assets")
    weights = market_weights.reindex(covariance.index)
    if weights.isna().any() or not np.isfinite(weights.to_numpy(float)).all():
        raise ValueError("market_weights must be finite for every covariance asset")
    return pd.Series(risk_aversion * covariance.to_numpy(float) @ weights.to_numpy(float), index=covariance.index, dtype=float)


def black_litterman_posterior(
    prior: pd.Series,
    covariance: pd.DataFrame,
    views: Sequence[BlackLittermanView] | None = None,
    *,
    tau: float = DEFAULT_TAU,
) -> pd.Series:
    """Posterior mean ``pi + tau S P' (P tau S P' + Omega)^-1 (q - P pi)``; the prior with no views."""

    if not views:
        return prior.copy()
    if not math.isfinite(tau) or tau <= 0:
        raise ValueError("tau must be a positive finite number")
    ids = list(prior.index)
    sigma = covariance.reindex(index=ids, columns=ids).to_numpy(float)
    picks = np.zeros((len(views), len(ids)))
    q = np.zeros(len(views))
    omega = np.zeros(len(views))
    for row, view in enumerate(views):
        unknown = set(view.weights) - set(ids)
        if unknown or not view.weights:
            raise ValueError(f"view must name known assets only: {sorted(unknown)}")
        if not math.isfinite(view.expected_return) or not math.isfinite(view.variance) or view.variance <= 0:
            raise ValueError("view expected_return must be finite and variance positive")
        for asset, weight in view.weights.items():
            picks[row, ids.index(asset)] = float(weight)
        q[row], omega[row] = view.expected_return, view.variance
    if not np.isfinite(sigma).all() or not np.isfinite(picks).all():
        raise ValueError("covariance and view weights must be finite")
    prior_values = prior.to_numpy(float)
    gain = tau * sigma @ picks.T @ np.linalg.inv(picks @ (tau * sigma) @ picks.T + np.diag(omega))
    return pd.Series(prior_values + gain @ (q - picks @ prior_values), index=prior.index, dtype=float)
