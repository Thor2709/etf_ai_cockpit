"""Work-R: a live optional model that no promoted forecast row backs must not turn the composite score into NaN."""

from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.signals.scoring import component_scores


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    features = pd.DataFrame([
        {
            "etf_id": etf_id, "momentum_20d": 0.01, "momentum_60d": 0.02, "momentum_120d": 0.03 * scale,
            "momentum_180d": 0.04, "trend_slope": 0.01 * scale, "trend_100": 1.0, "trend_200": 1.0,
            "vol_60d_ann": 0.2, "ewma_vol_ann": 0.2, "drawdown_60d_max": -0.05, "relative_strength_60d": 0.02 * scale,
        }
        for etf_id, scale in (("AAA", 1.0), ("BBB", 2.0), ("CCC", 3.0))
    ])
    allocation = pd.DataFrame([
        {"etf_id": etf_id, "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}
        for etf_id in ("AAA", "BBB", "CCC")
    ])
    return features, allocation


def test_live_models_without_promoted_scores_do_not_nan_the_composite() -> None:
    features, allocation = _inputs()
    config = load_config()
    shadow = component_scores(
        features, allocation, config, toto_available=True, timesfm_available=True,
        forecast_scores={"toto": {}, "timesfm": {}, "baseline": {"AAA": 0.1, "BBB": 0.2, "CCC": 0.3}},
    )
    assert shadow["total_score"].notna().all() and shadow["confidence"].notna().all()
    # The same weights as models that are simply not available.
    off = component_scores(
        features, allocation, config, toto_available=False, timesfm_available=False,
        forecast_scores={"baseline": {"AAA": 0.1, "BBB": 0.2, "CCC": 0.3}},
    )
    pd.testing.assert_series_equal(shadow["total_score"], off["total_score"])
    # A promoted model with scores still counts.
    counting = component_scores(
        features, allocation, config, toto_available=True, timesfm_available=True,
        forecast_scores={"toto": {"AAA": 0.5, "BBB": 0.5, "CCC": 0.5}, "baseline": {"AAA": 0.1, "BBB": 0.2, "CCC": 0.3}},
    )
    assert counting["total_score"].notna().all()
    assert not counting["total_score"].equals(off["total_score"])
