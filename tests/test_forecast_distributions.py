import pandas as pd

from etf_cockpit.models.distribution_store import QUANTILE_FIELDS, net_return_distribution
from etf_cockpit.models.forecast_scores import forecast_return_distributions

DECISION_TIME = "2026-03-01T00:00:00Z"


def _forecast_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "model_name": "baseline",
        "etf_id": "SYNTHETIC-ETF",
        "forecast_date": "2026-02-01T00:00:00Z",
        "horizon_days": 60,
        "expected_return": 0.04,
        "q05_return": -0.12,
        "q10_return": -0.08,
        "q25_return": -0.02,
        "q50_return": 0.04,
        "q75_return": 0.10,
        "q90_return": 0.16,
        "q95_return": 0.20,
        "coverage_ratio": 1.0,
        "price_return": 0.03,
        "income_return": 0.01,
        "fx_return": 0.0,
        "status": "ok",
        "model_allowed_in_score": True,
        "model_id": "synthetic-model-60d",
        "model_horizon_days": 60,
        "target_id": "synthetic-target-60d",
        "target_horizon_days": 60,
        "calibration_status": "limited",
        "calibration_horizon_days": 60,
        "prob_positive_return": 0.6,
        "prob_beat_cash": 0.55,
        "prob_beat_benchmark": 0.52,
    }
    row.update(overrides)
    return row


def test_quantile_monotonicity() -> None:
    forecasts = pd.DataFrame([_forecast_row()])

    distribution = forecast_return_distributions(forecasts, decision_time=DECISION_TIME)["SYNTHETIC-ETF"]
    quantiles = [distribution[field] for field in QUANTILE_FIELDS]

    assert all(value is not None for value in quantiles)
    assert quantiles == sorted(quantiles)
    assert distribution["canonical_status"] == "available"


def test_unsupported_horizon_unavailable() -> None:
    forecasts = pd.DataFrame([_forecast_row(horizon_days=120)])

    distribution = forecast_return_distributions(forecasts, horizon_days=60, decision_time=DECISION_TIME)["SYNTHETIC-ETF"]

    assert distribution["status"] == "unavailable"
    assert distribution["horizon_days"] is None
    assert distribution["canonical_status"] == "unavailable"


def test_unsupported_requested_horizon_is_unavailable_when_row_matches() -> None:
    forecasts = pd.DataFrame([_forecast_row(horizon_days=7)])

    distribution = forecast_return_distributions(
        forecasts,
        horizon_days=7,
        decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]

    assert distribution["status"] == "unavailable"
    assert distribution["horizon_days"] is None
    assert distribution["q50_return"] is None
    assert distribution["canonical_status"] == "unavailable"


def test_net_gross_cost_reconciliation() -> None:
    gross = {field: index / 100 for index, field in enumerate(QUANTILE_FIELDS)}
    costs = {"fee": 0.01, "spread": 0.002, "impact": 0.003, "fx": 0.001}

    net = net_return_distribution(gross, costs)
    projected = forecast_return_distributions(
        pd.DataFrame([_forecast_row()]),
        decision_time=DECISION_TIME,
        cost_deductions_by_instrument={"SYNTHETIC-ETF": costs},
    )["SYNTHETIC-ETF"]

    assert net is not None
    fee_cost_deductions = sum(costs.values())
    for field in QUANTILE_FIELDS:
        assert gross[field] - fee_cost_deductions == net[field]
        assert projected[field] - fee_cost_deductions == projected[f"net_{field}"]
    assert projected["net_status"] == "available"
    assert net_return_distribution(gross, {"fee": costs["fee"]}) is None


def test_probabilities_require_matching_horizon_calibration() -> None:
    uncalibrated = forecast_return_distributions(
        pd.DataFrame([_forecast_row()]), decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]
    calibrated = forecast_return_distributions(pd.DataFrame([_forecast_row(
        calibration_status="good",
        calibration_horizon_days=60,
    )]), decision_time=DECISION_TIME)["SYNTHETIC-ETF"]

    assert uncalibrated["probability_loss"] is None
    assert uncalibrated["probability_beat_cash"] is None
    assert calibrated["probability_loss"] == 0.4
    assert calibrated["probability_beat_cash"] == 0.55
    assert calibrated["probability_beat_benchmark"] == 0.52


def test_probabilities_are_unavailable_for_mixed_calibration() -> None:
    forecasts = pd.DataFrame([
        _forecast_row(
            calibration_status="good",
            calibration_horizon_days=60,
        ),
        _forecast_row(
            model_name="challenger",
            model_id="challenger-model-60d",
            target_id="challenger-target-60d",
            calibration_status="limited",
            calibration_horizon_days=60,
        ),
    ])

    distribution = forecast_return_distributions(
        forecasts,
        decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]

    assert distribution["probability_loss"] is None
    assert distribution["probability_beat_cash"] is None
    assert distribution["probability_beat_benchmark"] is None


def test_model_and_target_identities_must_be_bound_to_one_horizon() -> None:
    forecasts = pd.DataFrame([
        _forecast_row(),
        _forecast_row(
            horizon_days=120,
            model_horizon_days=120,
            target_horizon_days=120,
            expected_return=0.08,
        ),
    ])

    distribution = forecast_return_distributions(
        forecasts,
        decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]

    assert distribution["status"] == "unavailable"
    assert distribution["canonical_status"] == "unavailable"
    assert distribution["target_status"] == "unavailable"
    assert distribution["model_status"] == "unavailable"
    assert distribution["q50_return"] is None

    mismatched = pd.DataFrame([_forecast_row(model_horizon_days=120, target_horizon_days=120)])
    mismatch_distribution = forecast_return_distributions(
        mismatched,
        decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]

    assert mismatch_distribution["canonical_status"] == "unavailable"
    assert mismatch_distribution["q50_return"] is None


def test_low_coverage_widens_uncertainty() -> None:
    full = forecast_return_distributions(
        pd.DataFrame([_forecast_row()]), decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]
    low_coverage = forecast_return_distributions(
        pd.DataFrame([_forecast_row(coverage_ratio=0.25)]), decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]

    assert low_coverage["q05_return"] < full["q05_return"]
    assert low_coverage["q50_return"] == full["q50_return"]
    assert low_coverage["q95_return"] > full["q95_return"]


def test_forecasts_after_decision_time_are_unavailable() -> None:
    forecasts = pd.DataFrame([_forecast_row(forecast_date="2026-04-01T00:00:00Z")])

    distribution = forecast_return_distributions(forecasts, decision_time=DECISION_TIME)["SYNTHETIC-ETF"]

    assert distribution["status"] == "unavailable"
    assert distribution["canonical_status"] == "unavailable"
    assert distribution["point_in_time_status"] == "available"
    assert distribution["q10_return"] is None
    assert distribution["q50_return"] is None
    assert distribution["q90_return"] is None


def test_missing_decision_time_or_usable_forecast_date_is_unavailable() -> None:
    forecasts = pd.DataFrame([_forecast_row()])

    no_decision_time = forecast_return_distributions(forecasts)["SYNTHETIC-ETF"]
    invalid_decision_time = forecast_return_distributions(
        forecasts,
        decision_time="not-a-time",
    )["SYNTHETIC-ETF"]
    non_scalar_decision_times = [
        forecast_return_distributions(forecasts, decision_time=value)["SYNTHETIC-ETF"]
        for value in (["not-a-time"], {"at": DECISION_TIME})
    ]
    missing_date = forecast_return_distributions(
        forecasts.drop(columns=["forecast_date"]),
        decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]
    invalid_date = forecast_return_distributions(
        pd.DataFrame([_forecast_row(forecast_date="not-a-date")]),
        decision_time=DECISION_TIME,
    )["SYNTHETIC-ETF"]

    for distribution in (invalid_decision_time, *non_scalar_decision_times, missing_date, invalid_date):
        assert distribution["status"] == "unavailable"
        assert distribution["canonical_status"] == "unavailable"
        assert distribution["point_in_time_status"] == "unavailable"
        assert all(distribution[field] is None for field in QUANTILE_FIELDS)
        assert all(distribution[f"net_{field}"] is None for field in QUANTILE_FIELDS)
    # Legacy callers (no decision time) keep only the pre-existing three-quantile view;
    # the canonical contract and every extended/net quantile stay unavailable.
    assert no_decision_time["canonical_status"] == "unavailable"
    assert no_decision_time["point_in_time_status"] == "unavailable"
    assert no_decision_time["probability_loss"] is None
    assert all(no_decision_time[f"net_{field}"] is None for field in QUANTILE_FIELDS)
    assert all(
        no_decision_time[field] is None
        for field in QUANTILE_FIELDS
        if field not in {"q10_return", "q50_return", "q90_return"}
    )
