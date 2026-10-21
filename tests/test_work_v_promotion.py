"""Work-V: fail-closed promotion, provenance and horizon-bound calibration."""
from dataclasses import replace
from datetime import date
import os
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import ForecastService, _apply_promotion, _forecast_to_row
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.models.calibration import calibration_grade, evaluate_forecast_calibration, load_forecast_history
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity, forecast_return_distributions
from etf_cockpit.models.model_promotion import COUNTING, NOT_PROVEN, ModelPromotion, _normalised_history, evaluate_model_promotions
from tests.test_work_q_promotion import SETTINGS, _days, _forecasts, _prices


def _row(**changes):
    row = ForecastResult("r", "timesfm3", "v", "E1", date(2025, 6, 2), 60, 0.02, 0.02)
    changed = replace(row, **changes)
    return changed if "target_id" in changes else replace(changed, target_id=f"adj_close_log_return_{changed.horizon_days}d")


def _promotion(**changes):
    decision = ModelPromotion("timesfm3", COUNTING, "test", model_version="v", calibration_status="mixed", evidence_after="2024-01-01")
    return replace(decision, **changes)


def _checkpoint_settings(tmp_path, model_name="timesfm3"):
    checkpoint = tmp_path / f"{model_name}-checkpoint"
    checkpoint.mkdir(exist_ok=True)
    (checkpoint / "config.json").write_text("{}", encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"verified fixture weights")
    return {model_name: {"model_path": str(checkpoint)}}


@pytest.mark.usefixtures("synthetic_sample_opt_in")
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("shadow", [False, True])
def test_enabled_and_shadow_flags_fail_closed(tmp_path, monkeypatch, enabled, shadow):
    from etf_cockpit.application.forecast_service import _config_with_optional_models_disabled
    from etf_cockpit.application.reference_context import _benchmark_reference_snapshot_inputs, _reference_context_from_inputs
    from etf_cockpit.data.duckdb_store import load_holdings, load_prices

    config = _config_with_optional_models_disabled(load_config())
    config.models.promotion.enabled = enabled
    config.models.shadow_optional_models = shadow
    config.models.models["timesfm3"] = {**dict(config.models.models.get("timesfm3") or {}), **_checkpoint_settings(tmp_path)["timesfm3"]}
    # Calibration-evidence sufficiency has its own tests (test_forecast_honesty); this one covers the flags.
    monkeypatch.setattr("etf_cockpit.application.forecast_service.horizon_calibration_scores", lambda frame: pd.DataFrame({"status": ["ok"]}))
    prices = load_prices()
    as_of = pd.to_datetime(prices["date"]).max().date()
    context = _reference_context_from_inputs(_benchmark_reference_snapshot_inputs(config, as_of, load_holdings()), purpose="comparison", analysis_id="work-v")
    etf = config.universe.enabled_ids[0]

    def fake_timesfm(self, pivot, etf_ids, horizons, as_of_date, run_id, *, model_name="timesfm"):
        return [_row(run_id=run_id, etf_id=etf, forecast_date=as_of_date)]

    monkeypatch.setattr(ForecastService, "_run_timesfm_forecasts", fake_timesfm)
    monkeypatch.setattr(ForecastService, "_run_toto_forecasts", lambda *args: [])
    service = ForecastService(config, reference_context=context)
    for state in (COUNTING, NOT_PROVEN):
        rows = service.run_forecasts(as_of, [etf], prices, horizons=[60], output_path=tmp_path / f"{state}.csv", promotions={"timesfm3": _promotion(state=state)})
        optional = [row for row in rows if row.model_name != "baseline"]
        assert optional and all(row.model_allowed_in_score == (enabled and state == COUNTING) for row in optional)
        assert all(row.model_allowed_in_score for row in rows if row.model_name == "baseline" and row.status == "ok")
        stored = pd.read_csv(tmp_path / f"{state}.csv")
        assert stored.loc[stored.model_name.ne("baseline"), "model_allowed_in_score"].eq(enabled and state == COUNTING).all()


@pytest.mark.parametrize("status", ["ok", "failed", "unavailable"])
@pytest.mark.parametrize("shadow", [False, True])
def test_missing_decision_or_failed_row_never_counts(status, shadow):
    row = _row(status=status, model_allowed_in_score=True)
    assert not _apply_promotion(row, {}, shadow).model_allowed_in_score
    if status != "ok":
        assert not _apply_promotion(row, {"timesfm3": _promotion()}, shadow).model_allowed_in_score
    assert not _apply_promotion(row, {"timesfm3": _promotion(state=NOT_PROVEN)}, shadow).model_allowed_in_score


def test_optional_defaults_false_and_unknown_optional_is_denied():
    assert not _row().model_allowed_in_score
    assert not _apply_promotion(_row(model_name="lightgbm", model_allowed_in_score=True), {}, False).model_allowed_in_score


def test_late_creation_and_other_versions_are_unverifiable():
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-02", 30)})
    original = evaluate_model_promotions(history, prices, prices.date.max().date(), SETTINGS)["timesfm3"]
    optional = history.model_name.eq("timesfm3")
    late_indices = history.index[optional][-4:]
    history.loc[late_indices, "created_at"] = "2026-01-01T12:00:00Z"
    changed_indices = history.index[optional][4:8]
    history.loc[changed_indices, "model_version"] = "older"
    normalised = _normalised_history(history, prices.date.max().date())
    assert {"created_at", "model_version", "run_id"}.issubset(normalised.columns)
    assert not normalised.loc[normalised.created_at.eq(pd.Timestamp("2026-01-01T12:00:00")), "provenance_verified"].any()
    decision = evaluate_model_promotions(history, prices, prices.date.max().date(), SETTINGS)["timesfm3"]
    versions = {item["model_version"]: item for item in decision.version_evidence}
    assert versions["v"]["matured_forecasts"] == original.matured_forecasts - 8
    # C.C3.S08.N002: only the 4 late rows are unverifiable for "v"; the 4 verified "older" rows are that version's evidence.
    assert versions["v"]["unverifiable_forecasts"] == 4
    assert versions["older"]["unverifiable_forecasts"] == 0
    assert versions["older"]["matured_forecasts"] == 4
    assert not _apply_promotion(_row(), {"timesfm3": _promotion(model_version=None)}, False).model_allowed_in_score
    assert not _apply_promotion(_row(model_version="older"), {"timesfm3": _promotion()}, False).model_allowed_in_score


def test_missing_provenance_is_unverifiable_and_file_time_is_fallback(tmp_path):
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-02", 2)})
    path = tmp_path / "forecasts.csv"
    history.drop(columns="created_at").to_csv(path, index=False)
    written = pd.Timestamp("2026-01-01T12:00:00Z").timestamp()
    os.utime(path, (written, written))
    loaded = load_forecast_history(tmp_path)
    assert pd.to_datetime(loaded.created_at, utc=True).eq(pd.Timestamp("2026-01-01T12:00:00Z")).all()
    decision = evaluate_model_promotions(loaded, prices, prices.date.max().date(), SETTINGS)["timesfm3"]
    assert decision.matured_forecasts == 0 and decision.unverifiable_forecasts == 8
    history.to_csv(path, index=False)
    assert load_forecast_history(tmp_path).created_at.tolist() == history.created_at.tolist()
    missing = evaluate_model_promotions(history.drop(columns=["created_at", "model_version"]), prices, prices.date.max().date(), SETTINGS)["timesfm3"]
    assert missing.matured_forecasts == 0 and missing.unverifiable_forecasts == 8


@pytest.mark.parametrize("horizon", [5, 20, 60, 120, 180])
def test_promotion_grants_only_its_evidence_horizon(horizon):
    row = _apply_promotion(_row(horizon_days=horizon), {"timesfm3": _promotion()}, False)
    assert row.model_allowed_in_score == (horizon == 60)
    assert row.promotion_status == (COUNTING if horizon == 60 else NOT_PROVEN)
    assert row.calibration_horizon_days == (60 if horizon == 60 else None)


def test_promoted_row_has_canonical_horizon_validation(tmp_path):
    row = _apply_promotion(_row(q10_return=-0.1, q50_return=0.02, q90_return=0.1), {"timesfm3": _promotion()}, False)
    stored = _forecast_to_row(row, {"timesfm3": _promotion()}, _checkpoint_settings(tmp_path))
    assert stored["promotion_status"] == COUNTING
    assert stored["calibration_status"] in {"good", "mixed", "weak", "limited"}
    assert stored["calibration_horizon_days"] == 60
    result = forecast_return_distributions(pd.DataFrame([stored]), horizon_days=60, decision_time="2025-06-03T00:00:00Z")["E1"]
    assert result["validation_by_model"]["timesfm3"] == {"calibration_status": "mixed", "horizon_days": 60}
    assert result["validation_status"] == "available"


@pytest.mark.parametrize("coverage", [None, float("nan"), 0.69, 0.91, 1.0])
def test_good_grade_requires_passing_interval_coverage(coverage):
    assert calibration_grade(100, 0.5, 0.8, coverage) == "mixed"
    assert calibration_grade(100, 0.5, 0.8, 0.8) == "good"


def test_calibration_table_without_intervals_never_grades_good():
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-02", 30)}).assign(model_allowed_in_score=True)
    table = evaluate_forecast_calibration(history, prices)
    assert not table.calibration_status.eq("good").any()
    assert table.q10_q90_coverage.isna().all()


def test_every_optional_model_starts_after_verified_local_creation():
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-02", 30)})
    history["created_at"] = history["forecast_date"]
    decision = evaluate_model_promotions(history, prices, prices.date.max().date(), SETTINGS)["timesfm3"]
    assert decision.first_local_run == "2024-01-02"
    assert decision.evidence_after == "2024-01-02"
    assert decision.excluded_pre_cutoff == 4 and decision.matured_forecasts == 116


def test_forecast_request_handles_minimal_configs():
    assert configured_forecast_request_identity(SimpleNamespace())["live_optional_models"] is False
    config = load_config()
    assert configured_forecast_request_identity(config)["live_optional_models"] == config.models.shadow_optional_models
