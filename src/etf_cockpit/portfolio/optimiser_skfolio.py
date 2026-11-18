"""Optional skfolio backend for the local portfolio optimiser (ISSUE-0192).

skfolio is imported lazily inside the solve path, so the base install works
without the ``quant`` extra.  This module never imports ``optimiser``: the
caller passes plain values and maps :class:`SkfolioUnavailable` to its own
unavailable state.  A constraint a method cannot honour is a reason code,
never a silent drop or rescale.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

SKFOLIO_METHODS = ("sk_mean_variance", "sk_min_cvar", "sk_hrp")


class SkfolioUnavailable(Exception):
    """The skfolio backend cannot produce weights; ``reason_code`` says why."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def solve_skfolio(
    method: str,
    returns: pd.DataFrame,
    *,
    cash_weight: float,
    min_weight: float,
    max_weight: float,
    group_masks: Sequence[tuple[np.ndarray, float]],
    turnover_limit: float | None,
    current: pd.Series,
    covariance_shrinkage: str,
) -> tuple[pd.Series, str]:
    """Return ``(weights, model_version)`` or raise :class:`SkfolioUnavailable`."""

    if method not in SKFOLIO_METHODS:
        raise SkfolioUnavailable("unsupported_method", f"unsupported skfolio method: {method}")
    if method == "sk_hrp":
        # Decided before the import: the package may be absent.
        unsupported = [
            name
            for name, used in (("cash_weight", cash_weight > 0), ("group_max_weights", bool(group_masks)), ("turnover_limit", turnover_limit is not None))
            if used
        ]
        if unsupported:
            raise SkfolioUnavailable(f"constraint_unsupported:{unsupported[0]}", f"sk_hrp cannot honour: {', '.join(unsupported)}")
    try:
        import cvxpy
        import skfolio
        from skfolio import RiskMeasure
        from skfolio.moments import LedoitWolf
        from skfolio.optimization import HierarchicalRiskParity, MeanRisk, ObjectiveFunction
        from skfolio.prior import EmpiricalPrior
    except ImportError as exc:
        raise SkfolioUnavailable("skfolio_unavailable", f"skfolio is not installed: {exc}") from exc
    try:
        prior = EmpiricalPrior(covariance_estimator=LedoitWolf()) if covariance_shrinkage == "ledoit_wolf" else None
        if method == "sk_hrp":
            estimator = HierarchicalRiskParity(prior_estimator=prior, min_weights=min_weight, max_weights=max_weight)
        else:
            options: dict[str, object] = {}
            if group_masks:
                options["left_inequality"] = np.vstack([mask.astype(float) for mask, _ in group_masks])
                options["right_inequality"] = np.array([float(limit) for _, limit in group_masks])
            if turnover_limit is not None:
                # skfolio's own ``max_turnover`` caps each asset's trade; the native limit is the L1 sum.
                previous = current.to_numpy(float)
                options["add_constraints"] = lambda w: [cvxpy.norm1(w - previous) <= float(turnover_limit)]
            estimator = MeanRisk(
                objective_function=ObjectiveFunction.MINIMIZE_RISK,
                risk_measure=RiskMeasure.CVAR if method == "sk_min_cvar" else RiskMeasure.VARIANCE,
                prior_estimator=prior,
                budget=1.0 - cash_weight,
                min_weights=min_weight,
                max_weights=max_weight,
                **options,
            )
        weights = np.asarray(estimator.fit(returns).weights_, dtype=float)
    except Exception as exc:  # infeasible, solver error or non-convergence: never escapes
        raise SkfolioUnavailable("skfolio_solve_failed", f"{type(exc).__name__}: {exc}") from exc
    if weights.shape != (returns.shape[1],) or not np.isfinite(weights).all():
        raise SkfolioUnavailable("skfolio_solve_failed", "skfolio returned a non-finite or mis-shaped weight vector")
    return pd.Series(weights, index=returns.columns, dtype=float), f"skfolio-{skfolio.__version__}"
