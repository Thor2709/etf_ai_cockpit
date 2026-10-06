from __future__ import annotations

from collections.abc import Mapping


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
