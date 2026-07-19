from __future__ import annotations

import pandas as pd

from etf_cockpit.features.forecast_lab import build_forecast_lab_report, build_walk_forward_splits


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=14)
    return pd.DataFrame(
        {
            "etf_id": ["AAA"] * len(dates),
            "date": dates,
            "adjusted_close": [100.0 + index for index in range(len(dates))],
        }
    )


def _forecasts() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=6)
    return pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "model_name": "baseline",
                "model_version": "v1",
                "etf_id": "AAA",
                "forecast_date": forecast_date,
                "horizon_days": 1,
                "expected_return": 0.01,
                "q10_return": -0.01,
                "q90_return": 0.03,
                "status": "ok",
            }
            for forecast_date in dates
        ]
        + [
            {
                "run_id": "run-1",
                "model_name": "timesfm",
                "model_version": "unavailable",
                "etf_id": "AAA",
                "forecast_date": dates[-1],
                "horizon_days": 1,
                "expected_return": None,
                "status": "unavailable",
            }
        ]
    )


def test_forecast_lab_reports_maturity_walk_forward_and_shadow_only_governance() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices())

    assert report["status"] == "ok"
    assert report["execution_allowed"] is False
    assert {"naive_drift", "linear_ridge", "timesfm"}.issubset(set(report["model_catalogue"]["model_id"]))
    assert report["model_catalogue"].set_index("model_id").loc["timesfm", "state"] == "unavailable"
    assert len(report["runs"]) == 1
    baseline = report["models"].set_index("model_name").loc["baseline"]
    assert baseline["forecast_rows"] == 6
    assert baseline["matured_rows"] == 6
    assert baseline["calibration_status"] == "conformal_diagnostic"
    assert baseline["promotion_state"] == "shadow_only"
    assert baseline["conformal_coverage"] is not None
    assert len(report["walk_forward_splits"]) == 3


def test_forecast_lab_excludes_future_forecast_rows_without_claiming_model_performance() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices(), as_of_date="2026-01-06")

    baseline = report["models"].set_index("model_name").loc["baseline"]
    assert baseline["forecast_rows"] == 4
    assert report["as_of_date"] == "2026-01-06"


def test_forecast_lab_rejects_explicitly_unadjusted_prices() -> None:
    prices = _prices()
    prices["is_adjusted"] = False

    report = build_forecast_lab_report(_forecasts(), prices)

    assert report["status"] == "unavailable"
    assert "Unadjusted price rows were rejected" in report["notes"][0]


def test_walk_forward_splits_are_deterministic_and_expanding() -> None:
    splits = build_walk_forward_splits(["2026-01-03", "2026-01-01", "2026-01-02", "2026-01-04"])

    assert list(splits["split_id"]) == ["wf-01"]
    assert splits.iloc[0]["train_end"] == "2026-01-03"
    assert splits.iloc[0]["test_start"] == "2026-01-04"
    assert splits.iloc[0]["status"] == "evaluation_only"
