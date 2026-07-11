from __future__ import annotations


def overfitting_warnings(ai_added_value: bool) -> list[str]:
    if ai_added_value:
        return ["AI-added-value flag is based on sample data only; validate on real out-of-sample data before relying on it."]
    return ["AI forecasts are informational only until they improve walk-forward baselines after costs."]
