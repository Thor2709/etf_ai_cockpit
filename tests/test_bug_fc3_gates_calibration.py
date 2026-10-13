"""Bughunt C (#966): evidence/model gates, poor calibration, calibration matching and conformal events."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.core.config import ForecastCalibrationSettings, load_config
from etf_cockpit.core.types import DataQualityIssue, DataQualityReport, DatasetMetadata, SignalResult
from etf_cockpit.models.calibration import calibrate_forecast_distribution, conformal_quantile_adjustment
from etf_cockpit.models.forecast_scores import (
    _choose_horizon_row,
    forecast_component_maps,
    forecast_return_distributions,
)
from etf_cockpit.signals import signal_pipeline
from etf_cockpit.signals.scoring import component_scores

SIGNAL_DATE = date(2026, 3, 2)


# ---------------------------------------------------------------- evidence / model gates
def _metadata(**overrides: object) -> DatasetMetadata:
    values: dict[str, object] = dict(
        source_name="prices",
        source_type="prices",
        as_of_date=SIGNAL_DATE,
        ingested_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        currency="EUR",
        timezone="UTC",
        provider_or_manual_source="fixture",
        checksum="a" * 64,
        staleness_status="ok",
        age_days=0,
    )
    values.update(overrides)
    return DatasetMetadata(**values)  # type: ignore[arg-type]


def _canonical(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = dict(formula_version="test_v1", formula_checksum="b" * 64)
    values.update(overrides)
    return SimpleNamespace(**values)


def _signal(**overrides: object) -> SignalResult:
    values: dict[str, object] = dict(
        run_id="r",
        signal_date=SIGNAL_DATE,
        etf_id="AAA",
        action="hold",
        confidence=0.5,
        total_score=0.7,
        components=None,
        blocked_by=[],
        warnings=[],
        reason_short="",
        reason_long="",
        horizon_primary="1-3 months",
        model_versions_used={"baseline": signal_pipeline.BASELINE_MODEL_VERSION},
        canonical_score=_canonical(),
    )
    values.update(overrides)
    return SignalResult(**values)  # type: ignore[arg-type]


def _gate(signal: SignalResult, report: DataQualityReport, gate_id: str):
    decision = signal_pipeline._attach_authority(signal, report).authority_decision
    return next(gate for gate in decision.gates if gate.gate_id == gate_id)


def _report(*metadata: DatasetMetadata, issues: list[DataQualityIssue] | None = None) -> DataQualityReport:
    return DataQualityReport(as_of_date=SIGNAL_DATE, issues=issues or [], dataset_metadata=list(metadata))


@pytest.mark.parametrize(
    "metadata, issues",
    [
        (_metadata(source_type="etf_holdings", staleness_status="block"), None),  # stale holdings-only (C014-N002)
        (_metadata(source_type="portfolio_holdings"), None),  # wrong type, fresh
        (_metadata(staleness_status="warning"), None),
        (_metadata(staleness_status="block"), None),
        (_metadata(as_of_date=None), None),
        (_metadata(as_of_date=date(2026, 3, 3)), None),  # post-dates the signal
        (_metadata(checksum=" "), None),
        (_metadata(), [DataQualityIssue("AAA", "warning", "stale_data_warning", "stale")]),  # instrument-bound
    ],
)
def test_evidence_gate_rejects_stale_or_wrong_type_metadata_with_checksum(metadata, issues) -> None:
    assert not _gate(_signal(), _report(metadata, issues=issues), "evidence").passed


def test_evidence_gate_accepts_fresh_dated_price_evidence_and_ignores_other_instruments_issues() -> None:
    other = DataQualityIssue("BBB", "warning", "stale_data_warning", "stale")
    assert _gate(_signal(), _report(_metadata(), issues=[other]), "evidence").passed


def test_model_validity_requires_validated_baseline_version_and_score_fingerprint() -> None:
    report = _report(_metadata())
    assert _gate(_signal(), report, "model_validity").passed
    assert not _gate(_signal(model_versions_used={"baseline": "other_v9"}), report, "model_validity").passed
    assert not _gate(_signal(model_versions_used={}), report, "model_validity").passed
    assert not _gate(_signal(canonical_score=None), report, "model_validity").passed
    assert not _gate(_signal(canonical_score=_canonical(formula_checksum="")), report, "model_validity").passed
    assert not _gate(_signal(total_score=float("nan")), report, "model_validity").passed


# ---------------------------------------------------------------- calibration helpers
def _prices(periods: int = 70, *, daily_return: float = 0.01, etf_id: str = "AAA") -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=periods)
    return pd.DataFrame(
        {"etf_id": etf_id, "date": dates, "adjusted_close": 100.0 * (1.0 + daily_return) ** np.arange(periods)}
    )


def _forecasts(prices: pd.DataFrame, count: int, *, lower: float = -0.1, upper: float = 0.1, runs: int = 1) -> pd.DataFrame:
    frames = []
    for run in range(runs):
        frames.append(
            pd.DataFrame(
                {
                    "etf_id": "AAA",
                    "run_id": f"run-{run}",
                    "model_name": "baseline",
                    "model_id": "model-A",
                    "model_version": "v1",
                    "target_id": "target-1",
                    "prediction_id": [f"prediction-{run}-{index}" for index in range(count)],
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
        )
    return pd.concat(frames, ignore_index=True)


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


def _settings(minimum: int = 4, tolerance: float = 0.05) -> dict[str, object]:
    return {"minimum_matured_samples": minimum, "coverage_tolerance": tolerance}


def _calibrate(forecasts: pd.DataFrame, prices: pd.DataFrame, distribution=None, *, decision_index: int = 45, minimum: int = 4):
    return calibrate_forecast_distribution(
        forecasts,
        prices,
        distribution or _distribution(),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[decision_index],
        settings=_settings(minimum),
    )


# ---------------------------------------------------------------- C109-N001 poor calibration has effect
def _run_signal(monkeypatch: pytest.MonkeyPatch, calibration: dict[str, object]) -> tuple[SignalResult, list[float]]:
    config = load_config()
    scores = pd.DataFrame(
        [{
            "etf_id": "AAA", "total_score": 8.0, "confidence": 0.8, "current_weight": 0.0, "target_weight": 0.2,
            "hard_band": 0.05, "momentum_20d": 1.0, "momentum_60d": 1.0, "momentum_120d": 1.0, "trend_200": 1.0,
            "ewma_vol_ann": 0.1,
        }]
    )
    canonical = SimpleNamespace(
        legacy_composite_raw=8.0, decision_distribution={}, attractiveness_10=8.0, expected_return_10=8.0,
        risk_implementation_10=8.0, evidence_confidence_10=8.0, coverage=1.0, formula_version="test_v1",
        formula_checksum="a" * 64, source_vintage_hash="test-vintage",
    )
    seen: list[float] = []

    def action(*_args, confidence, **_kwargs):
        seen.append(confidence)
        return "buy"

    def calibrated(*_args, **_kwargs):
        return {**_distribution(), "conformal_calibration": calibration}

    monkeypatch.setattr(signal_pipeline, "component_scores", lambda *a, **k: scores.copy())
    monkeypatch.setattr(
        signal_pipeline, "allocation_frame",
        lambda *a, **k: pd.DataFrame([{"etf_id": "AAA", "drift": 0.1, "role": "core", "name": "AAA"}]),
    )
    monkeypatch.setattr(signal_pipeline, "canonical_score_from_signal_row", lambda *a, **k: canonical)
    monkeypatch.setattr(signal_pipeline, "_technical_expected_edge", lambda _f: 0.1)
    monkeypatch.setattr(signal_pipeline, "portfolio_value", lambda _h: 1000.0)
    monkeypatch.setattr(signal_pipeline, "calibrate_forecast_distribution", calibrated)
    monkeypatch.setattr(signal_pipeline, "preliminary_action", action)
    monkeypatch.setattr(signal_pipeline, "proposed_new_weight", lambda *a, **k: 0.2)
    monkeypatch.setattr(signal_pipeline, "evaluate_risk_gates", lambda *a, **k: ([], []))
    monkeypatch.setattr(signal_pipeline, "suggested_trade_value", lambda *a, **k: 100.0)
    monkeypatch.setattr(
        signal_pipeline, "estimate_execution_cost",
        lambda *a, **k: SimpleNamespace(total_cost_bps=1.0, model_id="t", data_quality="t", capacity_eur=1000.0),
    )
    monkeypatch.setattr(signal_pipeline, "_cost_stress_metrics", lambda *a, **k: {})
    monkeypatch.setattr(signal_pipeline, "row_components", lambda _r: {})
    monkeypatch.setattr(signal_pipeline, "explain_signal", lambda *a, **k: ("Review", "Detail"))
    monkeypatch.setattr(
        signal_pipeline, "decompose_forecast_uncertainty",
        lambda *a, **k: {"status": "available", "adjusted_confidence": 0.8},
    )
    monkeypatch.setattr(signal_pipeline, "generate_scenarios", lambda *a, **k: {"status": "available"})
    monkeypatch.setattr(
        signal_pipeline, "classification_score_state",
        lambda *a, **k: {"status": "current", "version_id": "t", "invalidation_token": "t"},
    )
    monkeypatch.setattr(signal_pipeline, "_structure_cap_for_row", lambda *a, **k: 1.0)
    signals = signal_pipeline.generate_signals(
        config,
        pd.DataFrame([{"etf_id": "AAA"}]),
        pd.DataFrame([{"etf_id": "AAA", "current_weight": 0.0}]),
        _report(_metadata()),
        as_of_date=SIGNAL_DATE,
        run_id="fc3",
        publish=False,
        forecast_distributions={"AAA": _distribution()},
        decision_time=pd.Timestamp("2026-03-02"),
        structure_confidence_caps={"AAA": 1.0},
    )
    return signals[0], seen


def test_poor_calibration_haircuts_action_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    clean, clean_seen = _run_signal(monkeypatch, {"status": "calibrated", "poor_calibration": False})
    poor, poor_seen = _run_signal(monkeypatch, {"status": "poor_calibration", "poor_calibration": True, "reason": "poor"})
    haircut = load_config().models.forecast_uncertainty.confidence_haircut
    assert clean_seen == [0.8] and clean.confidence == 0.8
    assert poor_seen == [pytest.approx(0.8 * haircut)]
    assert poor.confidence == pytest.approx(0.8 * haircut, abs=1e-4)
    assert "forecast_calibration_poor" in poor.warnings


def test_inconclusive_calibration_is_warned_but_not_haircut(monkeypatch: pytest.MonkeyPatch) -> None:
    signal, seen = _run_signal(monkeypatch, {"status": "inconclusive", "poor_calibration": False})
    assert "forecast_calibration_inconclusive" in signal.warnings
    assert seen == [0.8]


# ---------------------------------------------------------------- C109-N002 Wilson overlap is not "calibrated"
def test_overlapping_wilson_interval_alone_is_not_calibrated() -> None:
    # 18 of 30 hits: 60% coverage, Wilson 95% interval [42.3%, 75.4%] overlaps the 75-85% band.
    prices = _prices(80)
    base = _forecasts(prices, 30, lower=-0.5, upper=0.5)
    # Make 12 of the 30 events miss: forecast band excludes the 1% realised daily return.
    base.loc[base.index[:12], ["q10_return", "q90_return"]] = [-0.5, 0.005]
    result = _calibrate(base, prices, decision_index=45, minimum=30)["conformal_calibration"]
    assert result["sample_count"] == 30
    assert result["empirical_coverage"] == pytest.approx(0.6)
    assert result["coverage_confidence_interval"][1] >= 0.75
    assert result["status"] == "inconclusive"
    assert result["poor_calibration"] is False


# ---------------------------------------------------------------- C109-N003 evidence bound to instrument/horizon
def _probability_evidence(prices: pd.DataFrame, **overrides: object) -> dict[str, object]:
    evidence: dict[str, object] = {
        "status": "calibrated",
        "sample_count": 5,
        "matured_through": prices["date"].iloc[6],
        "instrument_id": "AAA",
        "horizon_days": 1,
        "model_construction": [
            {"model_name": "baseline", "model_id": "model-A", "model_version": "v1", "target_id": "target-1"}
        ],
        "probabilities": {"probability_loss": 0.2, "probability_beat_cash": 0.6, "probability_beat_benchmark": 0.7},
    }
    evidence.update(overrides)
    return evidence


@pytest.mark.parametrize(
    "binding, accepted",
    [
        ({}, True),
        ({"instrument_id": "BBB"}, False),
        ({"horizon_days": 5}, False),
        ({"instrument_id": "BBB", "horizon_days": 20}, False),
        ({"instrument_id": None}, False),
        ({"horizon_days": None}, False),
    ],
)
def test_probability_evidence_is_not_reused_across_instrument_or_horizon(binding, accepted) -> None:
    prices = _prices(30)
    forecasts = _forecasts(prices, 10)
    forecasts.loc[forecasts.index[:2], ["q10_return", "q90_return"]] = [-0.5, 0.005]  # 2 of 10 miss: 80% coverage
    evidence = _probability_evidence(prices, **binding)
    result = calibrate_forecast_distribution(
        forecasts,
        prices,
        _distribution(probability_calibration_evidence=evidence),
        instrument_id="AAA",
        decision_time=prices["date"].iloc[20],
        settings=_settings(4),
    )
    assert result["conformal_calibration"]["status"] == "calibrated"
    assert (result["probability_loss"] == 0.2) is accepted
    assert (result["probability_calibration_status"] == "available") is accepted


def test_probability_evidence_without_binding_keys_is_rejected() -> None:
    prices = _prices(30)
    forecasts = _forecasts(prices, 10)
    forecasts.loc[forecasts.index[:2], ["q10_return", "q90_return"]] = [-0.5, 0.005]
    evidence = _probability_evidence(prices)
    del evidence["instrument_id"], evidence["horizon_days"]
    result = calibrate_forecast_distribution(
        forecasts, prices, _distribution(probability_calibration_evidence=evidence),
        instrument_id="AAA", decision_time=prices["date"].iloc[20], settings=_settings(4),
    )
    assert result["conformal_calibration"]["status"] == "calibrated"
    assert result["probability_loss"] is None


# ---------------------------------------------------------------- C009 conformal events
@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_conformal_rank_beyond_sample_count_is_insufficient(count: int) -> None:
    # ceil((n+1)*0.8) > n for n <= 3: no finite-sample guarantee, never silently capped.
    result = conformal_quantile_adjustment([0.1, 0.2, 0.3][:count], minimum_matured_samples=1)
    assert result["status"] == "unavailable"
    assert result["adjustment"] is None


def test_conformal_rank_within_sample_count_is_available() -> None:
    result = conformal_quantile_adjustment([0.1, 0.2, 0.3, 0.4], minimum_matured_samples=2)
    assert result["status"] == "available"
    assert result["adjustment"] == pytest.approx(0.4)


def test_calibration_config_floor_requires_a_supportable_sample_count() -> None:
    with pytest.raises(ValueError):
        ForecastCalibrationSettings(minimum_matured_samples=3)
    assert ForecastCalibrationSettings(minimum_matured_samples=4).minimum_matured_samples == 4


def test_runs_on_one_outcome_count_as_one_calibration_event() -> None:
    prices = _prices(70)
    many_runs = _forecasts(prices, 6, runs=30)
    single_run = _forecasts(prices, 6, runs=1)
    many = _calibrate(many_runs, prices, minimum=4)["conformal_calibration"]
    single = _calibrate(single_run, prices, minimum=4)["conformal_calibration"]
    assert single["sample_count"] == 6
    assert many["sample_count"] == 6
    # 30 runs of only 3 outcomes must not clear a 4-event floor.
    short = _calibrate(_forecasts(prices, 3, runs=30), prices, minimum=4)["conformal_calibration"]
    assert short["sample_count"] == 3
    assert short["status"] == "unavailable"


# ---------------------------------------------------------------- C009-N001 / C008-N001 / C114 score map
def _score_frame(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = dict(
        etf_id="AAA", model_name="baseline", forecast_date="2026-02-02", horizon_days=60, expected_return=0.05,
        status="ok", model_allowed_in_score=True, run_id="r1",
    )
    row.update(overrides)
    return pd.DataFrame([row])


def test_positive_infinity_horizon_row_is_ignored_without_crash() -> None:
    frame = pd.concat([_score_frame(horizon_days=float("inf")), _score_frame(horizon_days=60, run_id="r2")], ignore_index=True)
    maps = forecast_component_maps(frame)
    assert set(maps["baseline"]) == {"AAA"}
    assert forecast_component_maps(_score_frame(horizon_days=float("inf")))["baseline"] == {}
    assert _choose_horizon_row(_score_frame(horizon_days=float("inf"))) is None
    distribution = forecast_return_distributions(_score_frame(horizon_days=float("inf")), decision_time="2026-03-01")
    assert distribution["AAA"]["status"] == "unavailable"


def test_mock_forecasts_are_never_scoreable() -> None:
    mock = _score_frame(model_name="toto", model_version="toto_2_0_mock", calibration_status="mock_not_for_live_scoring")
    real = _score_frame(model_name="toto", model_version="toto_2_0", calibration_status="limited")
    assert forecast_component_maps(mock)["toto"] == {}
    assert set(forecast_component_maps(real)["toto"]) == {"AAA"}
    only_version = _score_frame(model_name="timesfm", model_version="x_mock")
    assert forecast_component_maps(only_version)["timesfm"] == {}


def test_score_map_applies_point_in_time_cutoff() -> None:
    frame = pd.concat(
        [
            _score_frame(forecast_date="2026-02-02", expected_return=0.01, run_id="old"),
            _score_frame(forecast_date="2026-04-01", expected_return=0.20, run_id="future"),
        ],
        ignore_index=True,
    )
    unbound = forecast_component_maps(frame)["baseline"]["AAA"]
    bound = forecast_component_maps(frame, decision_time="2026-03-02")["baseline"]["AAA"]
    assert bound < unbound
    assert forecast_component_maps(_score_frame(forecast_date="2026-04-01"), decision_time="2026-03-02")["baseline"] == {}
    assert forecast_component_maps(frame, decision_time="not-a-time") == {"toto": {}, "timesfm": {}, "baseline": {}}


def test_empty_optional_forecasts_do_not_block_the_baseline() -> None:
    features = pd.DataFrame(
        [{
            "etf_id": "AAA", "momentum_20d": 0.01, "momentum_60d": 0.02, "momentum_120d": 0.03, "momentum_180d": 0.04,
            "trend_slope": 0.01, "trend_100": 1.0, "trend_200": 1.0, "vol_60d_ann": 0.2, "ewma_vol_ann": 0.2,
            "drawdown_60d_max": -0.05, "relative_strength_60d": 0.02,
        }]
    )
    allocation = pd.DataFrame(
        [{"etf_id": "AAA", "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}]
    )
    maps = forecast_component_maps(pd.DataFrame())
    row = component_scores(
        features, allocation, load_config(), toto_available=True, timesfm_available=True, forecast_scores=maps
    ).iloc[0]
    assert np.isfinite(row["score_baseline_ml"])
    assert np.isfinite(row["total_score"])


def test_lab_conformal_diagnostic_needs_a_supportable_sample_count() -> None:
    from etf_cockpit.features.forecast_lab import _conformal_diagnostics

    def evaluated(rows: int) -> pd.DataFrame:
        dates = pd.bdate_range("2026-01-01", periods=rows)
        return pd.DataFrame(
            {
                "etf_id": "AAA", "horizon_days": 1, "forecast_date": dates, "target_date": dates + pd.Timedelta(days=1),
                "actual_return": 0.01, "expected_return": 0.0, "absolute_error": 0.01,
            }
        )

    assert _conformal_diagnostics(evaluated(6), 2)["status"] == "conformal_pending"
    assert _conformal_diagnostics(evaluated(14), 2)["status"] == "conformal_diagnostic"
