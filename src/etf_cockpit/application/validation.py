"""Application facade for read-only validation evidence previews."""

from __future__ import annotations

import pandas as pd

from etf_cockpit.portfolio.optimiser import returns_from_adjusted_prices
from etf_cockpit.validation.protocol import ValidationReport, ValidationSpec, evaluate_trials


def build_validation_preview(prices: pd.DataFrame | None, *, spec: ValidationSpec | None = None) -> ValidationReport | None:
    """Build a transparent protocol report from local adjusted-price returns.

    The preview deliberately does not train or promote a model.  It proves the
    split/report contract in the user-facing workspaces and keeps promotion
    false until a caller supplies real, separately versioned trial scores.
    """

    returns = returns_from_adjusted_prices(prices if prices is not None else pd.DataFrame(), window=0)
    if returns.empty:
        return None
    values = returns.mean(axis=1).to_numpy(float)
    definition = spec or ValidationSpec(n_splits=3, test_size=10, final_test_size=10, horizon=1, embargo=2, bootstrap_repetitions=40, seed=42)
    if len(values) < definition.final_test_size + definition.n_splits * definition.test_size + definition.horizon + definition.embargo:
        return None
    regime_threshold = float(pd.Series(values).abs().median())
    regimes = ["stress" if abs(value) >= regime_threshold else "calm" for value in values]
    subgroups = ["local_adjusted_price" for _ in values]
    return evaluate_trials(
        {"baseline": values, "current_pipeline": values},
        spec=definition,
        parameters={"baseline": {"kind": "naive"}, "current_pipeline": {"kind": "preview_only"}},
        regime_labels=regimes,
        subgroup_labels=subgroups,
    )


__all__ = ["build_validation_preview"]
