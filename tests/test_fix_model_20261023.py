from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.core.config import ModelPromotionSettings
from etf_cockpit.models.calibration import (
    calibrate_forecast_distribution,
    evaluate_forecast_calibration,
    horizon_calibration_scores,
    probability_admission,
)
from etf_cockpit.models.forecast_scores import _scoreable_forecast_rows, forecast_return_distributions
from etf_cockpit.models.model_promotion import _normalised_history, evaluate_model_promotions
from tests.test_work_q_promotion import _days, _forecasts, _prices


def _calibration_prices(periods: int = 16) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=periods)
    return pd.DataFrame({"etf_id": "AAA", "date": dates, "adjusted_close": 100.0 * 1.01 ** np.arange(periods)})


def _calibration_history(prices: pd.DataFrame, count: int) -> pd.DataFrame:
    return pd.DataFrame({
        "etf_id": "AAA",
        "model_name": "baseline",
        "model_id": "model-A",
        "model_version": "v1",
        "target_id": "target-1",
        "prediction_id": [f"prediction-{index}" for index in range(count)],
        "fold_id": "wf-01",
        "out_of_fold": True,
        "forecast_date": prices["date"].iloc[:count].to_numpy(),
        "created_at": prices["date"].iloc[:count].to_numpy() + pd.Timedelta(hours=9),
        "horizon_days": 1,
        "expected_return": 0.01,
        "q10_return": -0.1,
        "q90_return": 0.1,
        "status": "ok",
        "model_allowed_in_score": True,
    })


def _calibration_distribution() -> dict[str, object]:
    return {
        "model_name": "baseline",
        "model_id": "model-A",
        "model_version": "v1",
        "target_id": "target-1",
        "horizon_days": 1,
        "q10_return": -0.1,
        "q50_return": 0.0,
        "q90_return": 0.1,
    }


def test_calibration_rejects_post_maturity_backfill() -> None:
    prices = _calibration_prices()
    forecasts = _calibration_history(prices, 7)
    forecasts["known_at"] = forecasts["created_at"]
    forecasts.loc[0, "known_at"] = prices.loc[1, "date"] + pd.Timedelta(days=1)
    forecasts.loc[1, "created_at"] = prices.loc[2, "date"] + pd.Timedelta(days=1)

    result = calibrate_forecast_distribution(
        forecasts,
        prices,
        _calibration_distribution(),
        instrument_id="AAA",
        decision_time=prices.loc[10, "date"],
        settings={"minimum_matured_samples": 2, "coverage_tolerance": 0.05},
    )

    assert result["conformal_calibration"]["sample_count"] == 5


def test_promotion_ignores_future_version() -> None:
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2023-12-04", 12)})
    history["known_at"] = history["created_at"]
    as_of = prices["date"].max().date()
    history = pd.concat([
        history,
        pd.DataFrame([{
            "run_id": "future-run",
            "model_name": "timesfm3",
            "model_version": "v2",
            "created_at": pd.Timestamp(as_of) + pd.Timedelta(days=30),
            "known_at": pd.Timestamp(as_of) + pd.Timedelta(days=30),
            "etf_id": "E1",
            "forecast_date": "2024-01-02",
            "horizon_days": 60,
            "target_id": "adj_close_log_return_60d",
            "expected_return": 0.01,
            "status": "ok",
        }]),
    ], ignore_index=True)

    decision = evaluate_model_promotions(history, prices, as_of, ModelPromotionSettings())["timesfm3"]

    assert decision.model_version == "v"


def test_probability_admission_embargoes_unmatured_prior() -> None:
    dates = pd.bdate_range("2024-01-01", periods=4)
    frame = pd.DataFrame({
        "forecast_date": dates,
        "target_date": [dates[1], dates[2], dates[3], dates[3]],
        "probability": [0.5] * 4,
        "outcome": [0, 1, 0, 1],
    })

    result = probability_admission(frame, folds=2, minimum_dates_per_fold=2)

    assert result["folds"][1]["prior_matured_forecasts"] == 1
    assert result["folds"][1]["base_rate_brier"] == 0.5


def _distribution_row(model_name: str, version: str, forecast_date: str, centre: float) -> dict[str, object]:
    return {
        "model_name": model_name,
        "model_id": f"{model_name}-model",
        "model_version": version,
        "etf_id": "SYNTHETIC-ETF",
        "forecast_date": forecast_date,
        "horizon_days": 60,
        "expected_return": centre,
        "q05_return": centre - 0.20,
        "q10_return": centre - 0.10,
        "q25_return": centre - 0.05,
        "q50_return": centre,
        "q75_return": centre + 0.05,
        "q90_return": centre + 0.10,
        "q95_return": centre + 0.20,
        "coverage_ratio": 1.0,
        "price_return": centre,
        "income_return": 0.0,
        "fx_return": 0.0,
        "status": "ok",
        "model_allowed_in_score": True,
        "model_horizon_days": 60,
        "target_id": f"{model_name}-target",
        "target_horizon_days": 60,
        "calibration_status": "good",
        "calibration_horizon_days": 60,
    }


def test_timesfm_family_counts_once() -> None:
    forecasts = pd.DataFrame([
        _distribution_row("baseline", "base-v1", "2024-01-01", 0.0),
        _distribution_row("timesfm", "tfm-v1", "2024-01-01", -0.20),
        _distribution_row("timesfm3", "tfm3-v1", "2024-02-01", 0.20),
    ])
    expected = forecast_return_distributions(
        forecasts.loc[forecasts["model_name"].ne("timesfm")],
        decision_time="2024-03-01",
    )["SYNTHETIC-ETF"]

    combined = forecast_return_distributions(forecasts, decision_time="2024-03-01")["SYNTHETIC-ETF"]

    assert combined["model_count"] == 2, combined["reason"]
    assert combined["q10_return"] == expected["q10_return"]
    assert combined["q50_return"] == expected["q50_return"]
    assert combined["q90_return"] == expected["q90_return"]
    assert [row["model_version"] for row in combined["per_model_distributions"] if row["model_name"].startswith("timesfm")] == ["tfm3-v1"]


def test_origin_timezone_session_end() -> None:
    history = pd.DataFrame([{
        "model_name": "timesfm3",
        "etf_id": "AAA",
        "forecast_date": "2024-01-02T20:00:00-05:00",
        "horizon_days": 60,
        "expected_return": 0.01,
        "status": "ok",
        "model_version": "v1",
        "created_at": "2024-01-02T20:00:00-05:00",
        "run_id": "run-1",
    }])

    normalized = _normalised_history(history, date(2024, 1, 3))

    assert bool(normalized.loc[0, "provenance_verified"])


def test_calibration_mixed_timezone_horizons() -> None:
    dates = [pd.Timestamp(day) for day in ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-08", "2024-01-09")]
    prices = _calibration_prices(20)
    rows = []
    for index, day in enumerate(dates):
        for horizon in (1, 2):
            rows.append({
                "model_name": "baseline",
                "etf_id": "AAA",
                "forecast_date": f"{day:%Y-%m-%d}T20:00:00-05:00",
                "horizon_days": horizon,
                "expected_return": 0.01,
                "target_id": f"adj_close_log_return_{horizon}d",
                "q10_return": None if horizon == 1 and index == 0 else -0.5,
                "q90_return": None if horizon == 1 and index == 0 else 0.5,
                "status": "ok",
                "model_allowed_in_score": True,
            })

    evaluated = evaluate_forecast_calibration(pd.DataFrame(rows), prices).sort_values("horizon_days")

    assert evaluated["horizon_days"].tolist() == [1, 2]
    partial = evaluated.loc[evaluated["horizon_days"].eq(1)].iloc[0]
    assert pd.isna(partial["grade_coverage"])
    assert partial["calibration_status"] != "good"


def test_horizon_scores_optional_probability() -> None:
    rows = [
        {
            "forecast_date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
            "horizon_days": 5,
            "actual": 0.02,
            "probability": np.nan,
            "q10_return": -0.1,
            "q50_return": 0.0,
            "q90_return": 0.1,
        }
        for index in range(5)
    ]
    rows.append({
        "forecast_date": pd.Timestamp("2024-01-06"),
        "horizon_days": 5,
        "actual": 0.02,
        "probability": np.nan,
        "q10_return": 0.1,
        "q50_return": 0.0,
        "q90_return": -0.05,
    })

    result = horizon_calibration_scores(pd.DataFrame(rows), minimum_dates=5).iloc[0]

    assert result["forecasts"] == 5
    assert result["effective_dates"] == 5
    assert pd.isna(result["brier"])
    assert result["status"] == "ok"
    assert result["sharpness_80"] >= 0


def test_fractional_horizon_rejected() -> None:
    forecasts = pd.DataFrame([
        {"etf_id": "AAA", "model_name": "baseline", "horizon_days": 0.5, "expected_return": 0.05,
         "status": "ok", "model_allowed_in_score": True, "forecast_date": "2024-01-01"},
        {"etf_id": "AAA", "model_name": "baseline", "horizon_days": 60, "expected_return": 0.05,
         "status": "ok", "model_allowed_in_score": True, "forecast_date": "2024-01-02"},
    ])

    scoreable = _scoreable_forecast_rows(forecasts)

    assert scoreable["horizon_days"].tolist() == [60]
