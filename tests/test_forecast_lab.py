from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.core.timing import read_timing_records, timed_step
from etf_cockpit.features import forecast_lab
from etf_cockpit.features.forecast_lab import (
    build_forecast_lab_report,
    build_forecast_lab_workspace,
    build_walk_forward_splits,
    forecast_round_trip_cost_bps,
    latest_forecast_runtimes,
)
from etf_cockpit.portfolio.costs import estimated_cost_bps


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
    assert "cannot rescue or upgrade weak deterministic evidence" in " ".join(report["notes"])


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


def _baseline_actual_returns() -> list[float]:
    # _prices() closes are 100 + i, so a one-day forecast made on day i earns this.
    return [(101.0 + index) / (100.0 + index) - 1.0 for index in range(6)]


def test_net_forward_value_deducts_canonical_round_trip_cost() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices(), round_trip_cost_bps={"AAA": 20.0})

    baseline = report["models"].set_index("model_name").loc["baseline"]
    expected = sum(value - 0.002 for value in _baseline_actual_returns()) / 6
    assert baseline["net_forward_value"] == pytest.approx(round(expected, 4))
    assert baseline["net_value_status"] == "positive_net_edge"


def test_net_forward_value_is_unavailable_without_a_cost_not_zero_filled() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices())

    baseline = report["models"].set_index("model_name").loc["baseline"]
    assert baseline["net_forward_value"] is None
    assert baseline["net_value_status"] == "cost_unavailable"


def test_costs_that_exceed_the_edge_report_no_net_edge() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices(), round_trip_cost_bps={"AAA": 500.0})

    baseline = report["models"].set_index("model_name").loc["baseline"]
    assert baseline["net_forward_value"] < 0
    assert baseline["net_value_status"] == "no_net_edge"


def test_flat_forecast_implies_no_trade_and_no_cost() -> None:
    forecasts = _forecasts()
    forecasts.loc[forecasts["model_name"] == "baseline", "expected_return"] = 0.0

    report = build_forecast_lab_report(forecasts, _prices())

    baseline = report["models"].set_index("model_name").loc["baseline"]
    assert baseline["net_forward_value"] == 0.0
    assert baseline["net_value_status"] == "no_net_edge"


def test_historical_as_of_matures_only_on_prices_known_at_that_date() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices(), as_of_date="2026-01-06")

    baseline = report["models"].set_index("model_name").loc["baseline"]
    # Forecasts on Jan 1, 2, 5 and 6; the Jan 6 one-day target (Jan 7) lies after
    # the as-of date, so it cannot be graded in a replay at Jan 6.
    assert baseline["forecast_rows"] == 4
    assert baseline["matured_rows"] == 3


def test_walk_forward_folds_are_evaluated_per_model() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices(), round_trip_cost_bps={"AAA": 20.0})

    evaluation = report["walk_forward_evaluation"]
    assert list(evaluation["split_id"]) == ["wf-01", "wf-02", "wf-03"]
    assert set(evaluation["model_name"]) == {"baseline"}
    assert evaluation["matured_rows"].tolist() == [1, 1, 1]
    first = evaluation.iloc[0]
    assert first["test_start"] == first["test_end"] == "2026-01-06"
    assert first["directional_accuracy"] == 1.0
    assert first["net_forward_value"] == pytest.approx(round(_baseline_actual_returns()[3] - 0.002, 4))


def test_resource_use_reports_latest_measured_runtime_per_model_family() -> None:
    records = [
        {"action_id": "forecasts", "step": "model:baseline", "run_id": "run-1", "duration_ms": 90.0},
        {"action_id": "forecasts", "step": "write_output", "duration_ms": 5.0},
        {"action_id": "backtest", "step": "model:baseline", "run_id": "backtest-1", "duration_ms": 999.0},
        {"action_id": "forecasts", "step": "model:baseline", "run_id": "run-1", "duration_ms": 120.44},
        {"action_id": "forecasts", "step": "model:toto", "run_id": "run-1", "duration_ms": "not-a-number"},
        {"action_id": "forecasts", "step": "model:timesfm", "run_id": "run-2", "duration_ms": 0.05},
        # This newer failed attempt must not provide runtime for the displayed run-1 artifact.
        {"action_id": "forecasts", "step": "model:baseline", "run_id": "run-2", "duration_ms": 9999.0},
    ]
    assert latest_forecast_runtimes(records) == {("run-1", "baseline"): 120.44, ("run-2", "timesfm"): 0.05, ("run-2", "baseline"): 9999.0}

    report = build_forecast_lab_workspace(load_config(), _forecasts(), _prices(), timing_records=records)

    models = report["models"].set_index("model_name")
    assert models.loc["baseline", "resource_status"] == "measured"
    assert models.loc["baseline", "runtime_ms"] == 120.4
    # TimesFM produced no ok rows, so its near-zero skip timing is not resource use.
    assert models.loc["timesfm", "resource_status"] == "not_run"
    assert pd.isna(models.loc["timesfm", "runtime_ms"])
    assert models.loc["baseline", "net_value_status"] in {"positive_net_edge", "no_net_edge"}


def test_forecast_runtime_is_not_borrowed_without_a_matching_artifact_run() -> None:
    forecasts = _forecasts()
    forecasts.loc[forecasts["model_name"] == "baseline", "run_id"] = "older-success"
    records = [
        {"action_id": "forecasts", "step": "model:baseline", "run_id": "newer-failed", "duration_ms": 900.0}
    ]

    report = build_forecast_lab_workspace(load_config(), forecasts, _prices(), timing_records=records)
    baseline = report["models"].set_index("model_name").loc["baseline"]

    assert baseline["resource_status"] == "not_recorded"
    assert pd.isna(baseline["runtime_ms"])


def test_timing_records_keep_forecast_run_identity(tmp_path) -> None:
    destination = tmp_path / "timings.jsonl"

    with timed_step("forecasts", "model:baseline", store_path=destination, run_id="run-1"):
        pass

    records = read_timing_records(destination)
    assert records[0]["run_id"] == "run-1"


def test_conformal_calibration_uses_only_residuals_whose_target_has_passed() -> None:
    dates = pd.bdate_range("2026-01-01", periods=7)
    forecasts = pd.DataFrame(
        {
            "model_name": "baseline",
            "etf_id": "AAA",
            "forecast_date": dates,
            "horizon_days": 5,
            "expected_return": 0.01,
            "status": "ok",
        }
    )

    report = build_forecast_lab_report(forecasts, _prices())

    baseline = report["models"].set_index("model_name").loc["baseline"]
    # All seven overlapping 5-day forecasts mature, but at the last forecast
    # date only two earlier targets have passed: fewer than three samples.
    assert baseline["matured_rows"] == 7
    assert baseline["calibration_status"] == "conformal_pending"
    assert baseline["conformal_coverage"] is None


def test_timezone_aware_prices_compare_with_naive_forecasts_and_as_of() -> None:
    prices = _prices()
    prices["date"] = pd.to_datetime(prices["date"]).dt.tz_localize("UTC")

    report = build_forecast_lab_report(_forecasts(), prices, as_of_date="2026-01-06")

    baseline = report["models"].set_index("model_name").loc["baseline"]
    assert baseline["matured_rows"] == 3
    assert report["outcomes_through"] == "2026-01-06"


def test_round_trip_cost_uses_the_canonical_one_way_cost_twice() -> None:
    config = load_config()
    instrument_id = config.universe.enabled_ids[0]

    costs = forecast_round_trip_cost_bps(config, [instrument_id, instrument_id])

    assert costs == {instrument_id: pytest.approx(2.0 * estimated_cost_bps(config, instrument_id))}


@pytest.mark.parametrize(
    ("values", "status"),
    [
        ([0.01, 0.01, 0.01], "drift_pending"),
        ([0.01, 0.011, 0.01, 0.011, 0.01, 0.011], "stable"),
        ([0.0, 0.0, 0.0, 0.05, 0.05, 0.05], "monitor"),
    ],
)
def test_drift_thresholds(values: list[float], status: str) -> None:
    score, observed = forecast_lab._drift(pd.Series(values))

    assert observed == status
    assert (score is None) == (status == "drift_pending")


def test_drift_is_chronological_and_independent_of_forecast_row_order() -> None:
    dates = pd.bdate_range("2026-01-01", periods=8)
    forecasts = pd.DataFrame(
        {
            "run_id": ["run-1"] * len(dates),
            "model_name": ["baseline"] * len(dates),
            "etf_id": ["AAA"] * len(dates),
            "forecast_date": dates,
            "horizon_days": [1] * len(dates),
            "expected_return": [0.01] * 4 + [0.05] * 4,
            "status": ["ok"] * len(dates),
        }
    )

    in_order = build_forecast_lab_report(forecasts, _prices())
    shuffled = build_forecast_lab_report(forecasts.sample(frac=1, random_state=18), _prices())
    first = in_order["models"].set_index("model_name").loc["baseline"]
    second = shuffled["models"].set_index("model_name").loc["baseline"]

    assert first["drift_score"] == second["drift_score"]
    assert first["drift_status"] == second["drift_status"]


def test_forecast_horizon_report_includes_latest_configured_observed_and_skipped_data() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices(), configured_horizons=[1, 3, 5])
    baseline = report["models"].set_index("model_name").loc["baseline"]

    assert baseline["latest_forecast_value"] == pytest.approx(0.01)
    assert baseline["latest_forecast_date"] == "2026-01-08"
    assert baseline["latest_forecast_horizon_days"] == 1
    assert baseline["configured_horizons"] == [1, 3, 5]
    assert baseline["observed_horizons"] == [1]
    assert {row["horizon_days"]: row["reason"] for row in baseline["skipped_horizons"]} == {
        3: "no_forecast_row",
        5: "no_forecast_row",
    }


def test_missing_origin_session_is_unavailable_and_excluded_from_metrics_and_net_value() -> None:
    forecasts = pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "model_name": "baseline",
                "etf_id": "AAA",
                "forecast_date": "2026-01-06",
                "horizon_days": 1,
                "expected_return": 0.01,
                "status": "ok",
            }
        ]
    )
    prices = pd.DataFrame(
        {
            "etf_id": ["AAA", "AAA"],
            "date": pd.to_datetime(["2026-01-05", "2026-01-07"]),
            "adjusted_close": [100.0, 110.0],
        }
    )

    report = build_forecast_lab_report(
        forecasts,
        prices,
        configured_horizons=[1],
        round_trip_cost_bps={"AAA": 20.0},
    )
    baseline = report["models"].set_index("model_name").loc["baseline"]
    outcome = report["forecast_outcomes"].iloc[0]

    assert outcome["outcome_status"] == "unavailable"
    assert outcome["outcome_reason"] == "origin_session_missing"
    assert baseline["matured_rows"] == 0
    assert baseline["mae"] is None
    assert baseline["net_forward_value"] is None
    assert baseline["net_value_status"] == "net_value_pending"
    assert baseline["skipped_horizons"] == [{"horizon_days": 1, "reason": "origin_session_missing"}]


@pytest.mark.parametrize(
    ("stale_date", "expected_reason"),
    [("2026-01-06", "origin_session_stale"), ("2026-01-07", "target_session_stale")],
)
def test_stale_origin_or_target_session_is_explicitly_unavailable(stale_date: str, expected_reason: str) -> None:
    forecasts = pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "model_name": "baseline",
                "etf_id": "AAA",
                "forecast_date": "2026-01-06",
                "horizon_days": 1,
                "expected_return": 0.01,
                "status": "ok",
            }
        ]
    )
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    prices = pd.DataFrame(
        {
            "etf_id": ["AAA"] * len(dates),
            "date": dates,
            "adjusted_close": [100.0, 101.0, 102.0],
            "is_stale": dates.date == pd.Timestamp(stale_date).date(),
        }
    )

    report = build_forecast_lab_report(forecasts, prices)

    assert report["forecast_outcomes"].iloc[0]["outcome_status"] == "unavailable"
    assert report["forecast_outcomes"].iloc[0]["outcome_reason"] == expected_reason
