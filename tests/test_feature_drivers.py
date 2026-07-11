from __future__ import annotations

import pandas as pd

from etf_cockpit.signals.feature_drivers import build_feature_drivers


def test_feature_drivers_cover_positive_negative_missing_and_low_authority() -> None:
    scores = pd.DataFrame({"instrument_id": ["A", "A"], "component": ["momentum", "quality"], "normalised_score_10": [8.0, None], "authority": ["vendor", "low"], "why": ["positive", "missing"]})
    drivers = build_feature_drivers(scores)
    assert {"instrument_id", "component", "direction", "driver_text"} <= set(drivers.columns)
    assert set(drivers["direction"]) == {"positive", "missing"}
