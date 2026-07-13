from __future__ import annotations

import pandas as pd

from etf_cockpit.signals.feature_drivers import build_feature_drivers


def test_feature_drivers_cover_positive_negative_missing_and_low_authority() -> None:
    scores = pd.DataFrame({"instrument_id": ["A", "A"], "component": ["momentum", "quality"], "normalised_score_10": [8.0, None], "authority": ["vendor", "low"], "why": ["positive", "missing"]})
    drivers = build_feature_drivers(scores)
    assert {"instrument_id", "component", "direction", "driver_text"} <= set(drivers.columns)
    assert set(drivers["direction"]) == {"positive", "missing"}


def test_feature_drivers_emit_required_schema_and_classify_stale_partial_rows() -> None:
    scores = pd.DataFrame(
        {
            "instrument_id": ["A", "A", "A"],
            "component": ["momentum", "quality", "forecast"],
            "raw_metric": [0.8, None, 0.1],
            "normalised_score_10": [8.0, None, 5.0],
            "authority": ["high", "low", "medium"],
            "source_id": ["yfinance:prices", "", "model:baseline"],
            "why": ["positive", "missing", "partial"],
            "freshness_status": ["ok", "stale_block", "partial"],
            "as_of_date": ["2026-07-10", "2026-06-01", ""],
        }
    )

    drivers = build_feature_drivers(scores)

    required = {
        "instrument", "component", "raw_metric", "normalised_score", "direction",
        "authority", "driver_text", "source_dataset", "as_of_date", "freshness_status",
    }
    assert required <= set(drivers.columns)
    assert set(drivers["direction"]) == {"positive", "missing", "mixed"}
    assert "low_authority" in set(drivers["authority_classification"])
    assert "stale" in set(drivers["freshness_classification"])
    assert drivers["execution_allowed"].eq(False).all()
