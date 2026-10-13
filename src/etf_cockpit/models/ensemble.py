from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from etf_cockpit.models.distribution_store import (
    NORMAL_Z_95,
    QUANTILE_FIELDS,
    QUANTILE_LEVELS,
    normalise_quantiles,
)


def effective_ensemble_weights(weights: Mapping[str, float], *, toto_available: bool, timesfm_available: bool) -> dict[str, float]:
    result = dict(weights)
    if not toto_available:
        toto_weight = result.get("toto", 0.0)
        result["toto"] = 0.0
        result["momentum"] = result.get("momentum", 0.0) + toto_weight * 0.47
        result["trend"] = result.get("trend", 0.0) + toto_weight * 0.27
        result["baseline_ml"] = result.get("baseline_ml", 0.0) + toto_weight * 0.26
    if not timesfm_available:
        timesfm_weight = result.get("timesfm", 0.0)
        result["timesfm"] = 0.0
        result["momentum"] = result.get("momentum", 0.0) + timesfm_weight * 0.50
        result["baseline_ml"] = result.get("baseline_ml", 0.0) + timesfm_weight * 0.50
    total = sum(value for key, value in result.items() if key not in {"cost_penalty", "turnover_penalty", "concentration_penalty"})
    if total > 0:
        for key in list(result):
            if key not in {"cost_penalty", "turnover_penalty", "concentration_penalty"}:
                result[key] = result[key] / total
    return result


MIXTURE_QUANTILE_METHOD = "weighted_mixture_cdf.v1"
_MIXTURE_TOLERANCE = 1e-13


def mixture_quantiles(
    models: Sequence[Mapping[str, object]],
    weights: Sequence[float] | None = None,
    *,
    space: str = "log",
) -> dict[str, float] | None:
    """Quantiles of the weighted mixture of the models' return distributions, or ``None``.

    Each model's CDF is piecewise linear through its own quantile vector (``QUANTILE_FIELDS``) with
    normal tails beyond q05/q95 anchored at the model's own tail width, so the mixture CDF is the
    weighted sum of those CDFs and each mixture quantile is the point where that sum reaches the
    level. This is not the median (or mean) of the models' quantiles, which is not the ensemble's
    quantile. ``weights`` default to equal weights. An inverted, incomplete or non-finite quantile
    set, an invalid weight vector, or (``space="simple"``) support below -100% yields ``None``;
    ``space="log"`` values are log returns, whose simple-return image ``exp(y) - 1`` is always > -100%.
    """

    if space not in {"log", "simple"} or not models:
        return None
    if weights is None:
        weights = [1.0] * len(models)
    if len(weights) != len(models) or any(not math.isfinite(w) or w < 0 for w in weights):
        return None
    total = math.fsum(weights)
    if total <= 0:
        return None
    normalised_weights = [w / total for w in weights]
    vectors: list[list[float]] = []
    for model in models:
        vector = normalise_quantiles(model)
        if vector is None or (space == "simple" and vector[QUANTILE_FIELDS[0]] < -1.0):
            return None
        vectors.append(list(vector.values()))
    if len(vectors) == 1:
        return dict(zip(QUANTILE_FIELDS, vectors[0]))
    low = min(vector[0] - _tail_sigma(vector, lower=True) * 40 for vector in vectors)
    high = max(vector[-1] + _tail_sigma(vector, lower=False) * 40 for vector in vectors)
    if space == "simple":
        low = max(low, -1.0)
    result: dict[str, float] = {}
    for level, field in zip(QUANTILE_LEVELS, QUANTILE_FIELDS):
        target = level / 100.0
        lo, hi = low, high
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if sum(w * _model_cdf(v, mid) for w, v in zip(normalised_weights, vectors)) < target:
                lo = mid
            else:
                hi = mid
            if hi - lo <= _MIXTURE_TOLERANCE * max(1.0, abs(mid)):
                break
        result[field] = hi
    return normalise_quantiles(result)


def _tail_sigma(vector: Sequence[float], *, lower: bool) -> float:
    width = vector[3] - vector[0] if lower else vector[-1] - vector[3]
    return max(width / NORMAL_Z_95, 0.0)


def _model_cdf(vector: Sequence[float], x: float) -> float:
    levels = [level / 100.0 for level in QUANTILE_LEVELS]
    if x < vector[0]:
        sigma = _tail_sigma(vector, lower=True)
        return 0.0 if sigma == 0 else 0.5 * math.erfc(-(x - vector[3]) / (sigma * math.sqrt(2.0)))
    if x >= vector[-1]:
        sigma = _tail_sigma(vector, lower=False)
        if sigma == 0:
            return 1.0
        return 0.5 * math.erfc(-(x - vector[3]) / (sigma * math.sqrt(2.0)))
    return float(np.interp(x, vector, levels))
