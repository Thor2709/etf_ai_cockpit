from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityReport, DatasetMetadata
from etf_cockpit.features.forecast_lab import _mark_walk_forward_provenance, build_walk_forward_splits
from etf_cockpit.models.calibration import calibrate_forecast_distribution
from etf_cockpit.signals import signal_pipeline


def _prices(periods: int = 70, *, daily_return: float = 0.01) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=periods)
    return pd.DataFrame(
        {
            "etf_id": "AAA",
            "date": dates,
            "adjusted_close": 100.0 * (1.0 + daily_return) ** np.arange(periods),
        }
    )


def _forecasts(prices: pd.DataFrame, count: int, *, lower: float = -0.1, upper: float = 0.1) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "etf_id": "AAA",
            "model_name": "baseline",
            "model_id": "model-A",
            "model_version": "v1",
            "target_id": "target-1",
            "prediction_id": [f"prediction-{index}" for index in range(count)],
            "fold_id": "wf-01",
            "out_of_fold": True,
            "forecast_date": prices["date"].iloc[:count].to_numpy(),
            "horizon_days": 1,
            "expected_return": 0.01,
            "q10_return": lower,
            "q90_return": upper,
            "status": "ok",
            "model_allowed_in_score": True,
        }
    )


def _distribution(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "status": "available",
        "model_name": "baseline",
        "model_id": "model-A",
        "model_version": "v1",
        "target_id": "target-1",
        "horizon_days": 1,
        "q05_return": -0.2,
        "q10_return": -0.1,
        "q25_return": -0.05,
        "q50_return": 0.0,
        "q75_return": 0.05,
        "q90_return": 0.1,
        "q95_return": 0.2,
        "probability_loss": 0.4,
        "probability_beat_cash": 0.55,
        "probability_beat_benchmark": 0.52,
    }
    values.update(overrides)
    return values


def _settings(*, minimum: int = 2, tolerance: float = 0.05) -> dict[str, object]:
    return {"minimum_matured_samples": minimum, "coverage_tolerance": tolerance}


def test_calibration_excludes_outcomes_maturing_at_decision_time() -> None:
    prices = _prices(12)
    forecasts = _forecasts(prices, 4)
    calibrated = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[3],
        settings=_settings(minimum=2),
    )

    evidence = calibrated["conformal_calibration"]
    assert evidence["status"] == "calibrated"
    assert evidence["sample_count"] == 2


def test_calibration_rejects_in_sample_rows_and_accepts_out_of_fold_rows() -> None:
    prices = _prices(12)
    forecasts = _forecasts(prices, 5)
    forecasts["out_of_fold"] = False
    splits = build_walk_forward_splits(forecasts["forecast_date"].dt.date.unique())

    in_sample = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[6],
        settings=_settings(minimum=2),
    )
    assert in_sample["conformal_calibration"]["status"] == "unavailable"
    assert "out-of-fold" in in_sample["conformal_calibration"]["reason"]

    forecasts = _mark_walk_forward_provenance(forecasts, splits)
    assert forecasts["out_of_fold"].tolist() == [False, False, False, True, True]
    assert forecasts.loc[forecasts["out_of_fold"], "fold_id"].notna().all()
    out_of_fold = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[6],
        settings=_settings(minimum=2),
    )
    assert out_of_fold["conformal_calibration"]["status"] == "calibrated"
    assert out_of_fold["conformal_calibration"]["sample_count"] == 2


def test_duplicate_predictions_do_not_meet_floor_and_other_model_evidence_is_ignored() -> None:
    prices = _prices(12)
    one_prediction = _forecasts(prices, 1)
    duplicates = pd.concat([one_prediction] * 30, ignore_index=True)
    duplicated = calibrate_forecast_distribution(
        duplicates,
        prices,
        _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[3],
        settings=_settings(minimum=30),
    )
    assert duplicated["conformal_calibration"]["status"] == "unavailable"
    assert duplicated["conformal_calibration"]["sample_count"] == 1

    other_model = calibrate_forecast_distribution(
        one_prediction,
        prices,
        _distribution(model_id="model-B", model_version="v2"),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[3],
        settings=_settings(minimum=2),
    )
    assert other_model["conformal_calibration"]["status"] == "unavailable"
    assert other_model["conformal_calibration"]["sample_count"] == 0


def test_calibrated_quantiles_are_repaired_to_monotonic_order() -> None:
    prices = _prices(12)
    forecasts = _forecasts(prices, 5)
    calibrated = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(q10_return=0.3, q25_return=0.25, q50_return=0.1, q75_return=0.05, q90_return=0.4),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[8],
        settings=_settings(minimum=2),
    )

    quantiles = [calibrated[f"q{level:02d}_return"] for level in (5, 10, 25, 50, 75, 90, 95)]
    assert quantiles == sorted(quantiles)


def test_poor_calibration_widens_band_and_reduces_signal_authority(monkeypatch) -> None:
    prices = _prices()
    forecasts = _forecasts(prices, 40, lower=-0.005, upper=0.005)
    calibrated = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(q10_return=-0.01, q90_return=0.01),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[45],
        settings=_settings(minimum=20),
    )

    evidence = calibrated["conformal_calibration"]
    assert evidence["status"] == "poor_calibration"
    assert calibrated["q90_return"] - calibrated["q10_return"] > 0.02
    assert calibrated["probability_loss"] is None
    assert calibrated["probability_beat_cash"] is None
    assert calibrated["probability_beat_benchmark"] is None
    assert calibrated["probability_calibration_status"] == "unavailable"
    assert "poor" in calibrated["probability_calibration_reason"]

    config = load_config()
    scores = pd.DataFrame(
        [{
            "etf_id": "AAA",
            "total_score": 8.0,
            "confidence": 0.8,
            "current_weight": 0.0,
            "target_weight": 0.2,
            "hard_band": 0.05,
            "momentum_20d": 1.0,
            "momentum_60d": 1.0,
            "momentum_120d": 1.0,
            "trend_200": 1.0,
            "ewma_vol_ann": 0.1,
        }]
    )
    canonical = SimpleNamespace(
        legacy_composite_raw=8.0,
        decision_distribution={},
        attractiveness_10=8.0,
        expected_return_10=8.0,
        risk_implementation_10=8.0,
        evidence_confidence_10=8.0,
        coverage=1.0,
        formula_version="test_v1",
        formula_checksum="a" * 64,
        source_vintage_hash="test-vintage",
    )
    monkeypatch.setattr(signal_pipeline, "component_scores", lambda *args, **kwargs: scores.copy())
    monkeypatch.setattr(
        signal_pipeline,
        "allocation_frame",
        lambda *args, **kwargs: pd.DataFrame(
            [{"etf_id": "AAA", "drift": 0.1, "role": "core", "name": "AAA"}]
        ),
    )
    monkeypatch.setattr(signal_pipeline, "canonical_score_from_signal_row", lambda *args, **kwargs: canonical)
    monkeypatch.setattr(signal_pipeline, "_technical_expected_edge", lambda _frame: 0.1)
    monkeypatch.setattr(signal_pipeline, "portfolio_value", lambda _holdings: 1000.0)
    monkeypatch.setattr(signal_pipeline, "preliminary_action", lambda *args, **kwargs: "buy")
    monkeypatch.setattr(signal_pipeline, "proposed_new_weight", lambda *args, **kwargs: 0.2)
    monkeypatch.setattr(signal_pipeline, "evaluate_risk_gates", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(signal_pipeline, "suggested_trade_value", lambda *args, **kwargs: 100.0)
    monkeypatch.setattr(signal_pipeline, "estimate_execution_cost", lambda *args, **kwargs: SimpleNamespace(
        total_cost_bps=1.0, model_id="test", data_quality="test", capacity_eur=1000.0
    ))
    monkeypatch.setattr(signal_pipeline, "_cost_stress_metrics", lambda *args, **kwargs: {})
    monkeypatch.setattr(signal_pipeline, "row_components", lambda _row: {})
    monkeypatch.setattr(signal_pipeline, "explain_signal", lambda *args, **kwargs: ("Review", "Signal detail"))
    monkeypatch.setattr(signal_pipeline, "decompose_forecast_uncertainty", lambda *args, **kwargs: {
        "status": "available", "adjusted_confidence": 0.8
    })
    monkeypatch.setattr(signal_pipeline, "generate_scenarios", lambda *args, **kwargs: {"status": "available"})
    monkeypatch.setattr(signal_pipeline, "classification_score_state", lambda *args, **kwargs: {
        "status": "current", "version_id": "test", "invalidation_token": "test"
    })
    monkeypatch.setattr(signal_pipeline, "_structure_cap_for_row", lambda *args, **kwargs: 1.0)
    report = DataQualityReport(
        as_of_date=date(2026, 1, 1),
        issues=[],
        dataset_metadata=[
            DatasetMetadata(
                source_name="prices",
                source_type="market_data",
                as_of_date=date(2026, 1, 1),
                ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                currency="EUR",
                timezone="UTC",
                provider_or_manual_source="local test fixture",
                checksum="a" * 64,
                staleness_status="fresh",
            )
        ],
    )
    signals = signal_pipeline.generate_signals(
        config,
        pd.DataFrame([{"etf_id": "AAA"}]),
        pd.DataFrame([{"etf_id": "AAA", "current_weight": 0.0}]),
        report,
        as_of_date=prices["date"].iloc[45].date(),
        run_id="calibration-test",
        publish=False,
        forecast_distributions={"AAA": _distribution(q10_return=-0.01, q90_return=0.01)},
        historical_forecasts=forecasts,
        calibration_prices=prices,
        decision_time=prices["date"].iloc[45],
        structure_confidence_caps={"AAA": 1.0},
    )
    authorised = signals[0]
    assert authorised.supporting_metrics["q90_expected_return"] - authorised.supporting_metrics[
        "q10_expected_return"
    ] > 0.02
    assert "forecast_calibration_poor" in authorised.warnings
    assert "outside the configured tolerance" in authorised.reason_long
    signal_gate = next(gate for gate in authorised.authority_decision.gates if gate.gate_id == "signal")
    assert not signal_gate.passed
    assert not authorised.research_promotion_allowed


def test_coverage_reports_a_wilson_confidence_interval() -> None:
    prices = _prices(14)
    forecasts = _forecasts(prices, 8)
    calibrated = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[10],
        settings=_settings(minimum=2),
    )

    evidence = calibrated["conformal_calibration"]
    interval = evidence["coverage_confidence_interval"]
    assert evidence["confidence_interval_method"] == "wilson_95"
    assert interval is not None
    assert 0.0 <= interval[0] <= evidence["empirical_coverage"] <= interval[1] <= 1.0


def test_too_few_matured_samples_remain_unavailable() -> None:
    prices = _prices(12)
    forecasts = _forecasts(prices, 3)
    calibrated = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[4],
        settings=_settings(minimum=4),
    )

    evidence = calibrated["conformal_calibration"]
    assert evidence["status"] == "unavailable"
    assert evidence["adjustment"] is None
    assert evidence["sample_count"] == 3


def test_missing_calibration_configuration_fails_closed() -> None:
    prices = _prices(12)
    forecasts = _forecasts(prices, 5)
    calibrated = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[8],
        settings=None,
    )

    evidence = calibrated["conformal_calibration"]
    assert evidence["status"] == "unavailable"
    assert evidence["adjustment"] is None
    assert "configuration" in evidence["reason"]


def test_probabilities_restore_only_from_matching_matured_calibration_evidence() -> None:
    prices = _prices(12)
    forecasts = _forecasts(prices, 5)
    construction = [{
        "model_name": "baseline",
        "model_id": "model-A",
        "model_version": "v1",
        "target_id": "target-1",
    }]
    probability_evidence = {
        "status": "calibrated",
        "sample_count": 2,
        "matured_through": prices["date"].iloc[6],
        "model_construction": construction,
        "probabilities": {
            "probability_loss": 0.2,
            "probability_beat_cash": 0.6,
            "probability_beat_benchmark": 0.7,
        },
    }
    calibrated = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(probability_calibration_evidence=probability_evidence),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[8],
        settings=_settings(minimum=2),
    )
    assert calibrated["probability_loss"] == 0.2
    assert calibrated["probability_beat_cash"] == 0.6
    assert calibrated["probability_beat_benchmark"] == 0.7
    assert calibrated["probability_calibration_status"] == "available"

    same_day_evidence = _distribution(
        probability_calibration_evidence={
            **probability_evidence,
            "matured_through": prices["date"].iloc[8],
        }
    )
    same_day = calibrate_forecast_distribution(
        forecasts,
        prices,
        same_day_evidence,
        instrument_id="AAA",
        decision_time=prices["date"].iloc[8] + pd.Timedelta(hours=12),
        settings=_settings(minimum=2),
    )
    assert same_day["probability_loss"] is None
    assert same_day["probability_calibration_status"] == "unavailable"

    mismatched = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(probability_calibration_evidence={**probability_evidence, "model_construction": []}),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[8],
        settings=_settings(minimum=2),
    )
    assert mismatched["probability_loss"] is None
    assert mismatched["probability_calibration_status"] == "unavailable"
