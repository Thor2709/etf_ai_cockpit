"""Forecast honesty (#943): target registry, return space, heuristic probabilities, mixture quantiles, provenance."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import (
    _checkpoint_evidence,
    _identity_gated_forecast,
    _probability_scope,
    ForecastService,
    _demote_unadmitted_probabilities,
    _forecast_to_row,
    _postprocess_forecast_benchmark_fields,
    _shadow_forecast,
    _stamp_adjusted_log_return_target,
    _unavailable_forecast,
)
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.calibration import (
    TargetMismatchError,
    adjusted_log_return_target,
    evaluate_forecast_calibration,
    format_heuristic_probability,
    format_log_return_percent,
    horizon_calibration_scores,
    log_to_simple_return,
    probability_admission,
    require_same_target,
    simple_to_log_return,
    user_facing_probability,
)
from etf_cockpit.models.distribution_store import QUANTILE_FIELDS
from etf_cockpit.models.ensemble import mixture_quantiles
from etf_cockpit.models.forecast_scores import forecast_component_maps, forecast_return_distributions
from etf_cockpit.models.model_promotion import (
    _matured_pairs,
    checkpoint_provenance,
    matured_probability_frame,
    positive_probability_status,
)


def _vector(centre: float, step: float = 0.1) -> dict[str, float]:
    offsets = (-3, -2, -1, 0, 1, 2, 3)
    return {field: centre + offset * step for field, offset in zip(QUANTILE_FIELDS, offsets)}


# 1. Return space -------------------------------------------------------------------------------
def test_log_return_ten_percent_is_shown_as_10_52_percent() -> None:
    assert format_log_return_percent(0.10) == "10.52%"
    assert log_to_simple_return(0.10) == pytest.approx(0.1051709180756477)
    assert simple_to_log_return(log_to_simple_return(-0.25)) == pytest.approx(-0.25)
    assert simple_to_log_return(-1.0) is None
    assert format_log_return_percent(float("nan")) == "unavailable"


# 2. Mixture quantiles --------------------------------------------------------------------------
def test_mixture_quantile_of_disjoint_models_is_not_the_median_of_quantiles() -> None:
    low, high = _vector(0.0), _vector(10.0)
    mixture = mixture_quantiles([low, high])
    assert mixture is not None
    # Half the mass sits below 10 (model A), so mixture q10 is where F_A = 0.2: between A's q10 (-0.2)
    # and q25 (-0.1): -0.2 + (0.2 - 0.1) / (0.25 - 0.10) * 0.1 = -0.13333...; likewise q90 sits at F_B = 0.8.
    assert mixture["q10_return"] == pytest.approx(-0.2 + (0.2 - 0.10) / (0.25 - 0.10) * 0.1, abs=1e-9)
    assert mixture["q90_return"] == pytest.approx(10.0 + 0.1 + (0.8 - 0.75) / (0.90 - 0.75) * 0.1, abs=1e-9)
    median_of_q10 = float(np.median([low["q10_return"], high["q10_return"]]))
    assert median_of_q10 == pytest.approx(4.9 - 0.1)
    assert abs(mixture["q10_return"] - median_of_q10) > 4.0
    values = list(mixture.values())
    assert values == sorted(values)


def test_mixture_weights_and_single_model_passthrough() -> None:
    only = _vector(0.02)
    assert mixture_quantiles([only]) == pytest.approx(only)
    heavy = mixture_quantiles([_vector(0.0), _vector(10.0)], [9.0, 1.0])
    # 0.9 * F_A = 0.10 at F_A = 1/9: -0.2 + (1/9 - 0.10) / 0.15 * 0.1.
    assert heavy is not None and heavy["q10_return"] == pytest.approx(-0.2 + (1 / 9 - 0.10) / 0.15 * 0.1, abs=1e-9)
    assert mixture_quantiles([_vector(0.0)], [0.0]) is None
    assert mixture_quantiles([_vector(0.0), _vector(1.0)], [1.0]) is None


def test_inverted_quantile_set_is_rejected() -> None:
    inverted = _vector(0.0)
    inverted["q90_return"], inverted["q10_return"] = inverted["q10_return"], inverted["q90_return"]
    assert mixture_quantiles([_vector(0.0), inverted]) is None
    assert mixture_quantiles([inverted]) is None

    row = {
        "forecast_date": "2026-01-02", "model_name": "m", "etf_id": "X", "horizon_days": 60,
        "expected_return": 0.0, "status": "ok", "model_allowed_in_score": True, "target_id": "adj_close_log_return_60d",
        **{field: value for field, value in inverted.items()},
    }
    distribution = forecast_return_distributions(pd.DataFrame([row]))["X"]
    assert distribution["canonical_status"] == "unavailable"
    assert distribution["q10_return"] is None or distribution["q10_return"] <= distribution["q90_return"]


def test_simple_return_support_below_minus_100_percent_is_rejected() -> None:
    assert mixture_quantiles([_vector(-1.0, 0.05)], space="simple") is None
    assert mixture_quantiles([_vector(0.0)], space="simple") is not None
    # Log returns have no such limit: exp(y) - 1 stays above -100%.
    assert mixture_quantiles([_vector(-1.0, 0.05)], space="log") is not None


def test_distribution_uses_mixture_not_median_of_model_quantiles() -> None:
    rows = []
    for name, centre in (("a", 0.0), ("b", 1.0)):
        rows.append({
            "forecast_date": "2026-01-02", "model_name": name, "etf_id": "X", "horizon_days": 60,
            "expected_return": centre, "q10_return": centre - 0.2, "q50_return": centre, "q90_return": centre + 0.2,
            "status": "ok", "model_allowed_in_score": True, "target_id": "adj_close_log_return_60d",
        })
    distribution = forecast_return_distributions(pd.DataFrame(rows))["X"]
    assert distribution["quantile_method"] == "weighted_mixture_cdf.v1"
    assert distribution["q10_return"] != pytest.approx(0.4)  # median of -0.2 and 0.8
    assert distribution["q10_return"] < distribution["q50_return"] < distribution["q90_return"]


# 3. Heuristic vs calibrated probability --------------------------------------------------------
def test_uncalibrated_probability_up_is_heuristic_or_unavailable() -> None:
    index = pd.bdate_range(end="2026-03-02", periods=120)
    series = pd.Series(100 * np.exp(np.cumsum(0.001 + 0.01 * np.sin(np.arange(120)))), index=index)
    row = baseline_forecast("AAA", series, [60], date(2026, 3, 2), "run", benchmark_returns=pd.Series([0.001] * 100))[0]
    assert row.prob_positive_return is None and row.prob_beat_benchmark is None
    assert 0.0 < row.heuristic_probability_positive < 1.0
    assert 0.0 < row.heuristic_probability_beat_benchmark < 1.0
    assert format_heuristic_probability(row.heuristic_probability_positive).endswith("(uncalibrated)")
    assert user_facing_probability(row.heuristic_probability_positive, None) is None
    assert user_facing_probability(0.6, {"status": "unavailable"}) is None
    assert user_facing_probability(0.6, {"status": "calibrated"}) == 0.6

    # An uncalibrated model row never yields a user-facing probability in the canonical distribution.
    uncalibrated = pd.DataFrame([{
        "forecast_date": "2026-01-02", "model_name": "m", "etf_id": "X", "horizon_days": 60, "expected_return": 0.0,
        "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1, "status": "ok", "model_allowed_in_score": True, "target_id": "adj_close_log_return_60d",
        "calibration_status": "not_evaluated", "calibration_horizon_days": 60, "prob_positive_return": 0.9,
        "prob_beat_cash": 0.9, "prob_beat_benchmark": 0.9,
    }])
    distribution = forecast_return_distributions(uncalibrated)["X"]
    assert distribution["probability_loss"] is None and distribution["probability_beat_benchmark"] is None


def test_probability_admission_requires_chronological_out_of_sample_evidence() -> None:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2025-01-01", periods=60)
    probability = rng.uniform(0.05, 0.95, len(dates))
    noisy = pd.DataFrame({
        "forecast_date": dates, "probability": probability, "outcome": (rng.uniform(size=len(dates)) < probability).astype(int),
    })
    assert probability_admission(noisy)["status"] in {"calibrated", "unavailable"}
    # Sharp, correct probabilities beat the earlier-fold base rate in every fold and stay reliable.
    outcome = (np.arange(len(dates)) % 3 == 0).astype(int)
    informative = pd.DataFrame({"forecast_date": dates, "probability": np.where(outcome == 1, 0.95, 0.05), "outcome": outcome})
    admitted = probability_admission(informative)
    assert admitted["status"] == "calibrated" and admitted["reason"] is None and len(admitted["folds"]) == 3
    constant = pd.DataFrame({"forecast_date": dates, "probability": 0.9, "outcome": (np.arange(len(dates)) % 2)})
    assert probability_admission(constant)["status"] == "unavailable"
    short = informative.head(6)
    assert probability_admission(short)["status"] == "unavailable"
    assert probability_admission(pd.DataFrame({"x": [1]}))["status"] == "unavailable"


# 4. Target registry ----------------------------------------------------------------------------
def test_target_mismatch_is_rejected() -> None:
    sixty = adjusted_log_return_target(60)
    assert require_same_target(sixty.target_id, sixty.target_id) == sixty
    assert sixty.return_space == "log" and sixty.horizon_days == 60 and sixty.cost_policy
    with pytest.raises(TargetMismatchError):
        require_same_target(sixty.target_id, adjusted_log_return_target(20).target_id)
    with pytest.raises(TargetMismatchError):
        require_same_target(None, sixty.target_id)
    with pytest.raises(TargetMismatchError):
        require_same_target("unregistered", "unregistered")

    index = pd.bdate_range("2025-01-01", periods=120)
    prices = pd.DataFrame({"etf_id": "AAA", "date": index, "adjusted_close": 100 * np.exp(np.arange(120) * 0.001)})
    base = {
        "model_name": "m", "etf_id": "AAA", "forecast_date": "2025-01-02", "horizon_days": 20,
        "expected_return": 0.02, "status": "ok", "model_allowed_in_score": True, "target_id": "adj_close_log_return_60d",
    }
    forecasts = pd.DataFrame([
        {**base, "target_id": adjusted_log_return_target(20).target_id},
        {**base, "forecast_date": "2025-01-03", "target_id": adjusted_log_return_target(60).target_id},
    ])
    evaluated = evaluate_forecast_calibration(forecasts, prices)
    assert int(evaluated["matured_forecasts"].sum()) == 1  # the 60d-target row is not scored on 20 days


# 5. Per-horizon scores with date clustering ----------------------------------------------------
def test_horizon_scores_count_effective_dates_not_forecasts() -> None:
    rows = []
    for date_index in range(5):
        for instrument in range(20):
            rows.append({
                "forecast_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=date_index), "horizon_days": 60,
                "actual": 0.01 * instrument / 20, "probability": 0.6, **{field: value for field, value in _vector(0.0, 0.05).items()},
            })
    scores = horizon_calibration_scores(pd.DataFrame(rows))
    assert len(scores) == 1
    row = scores.iloc[0]
    assert row["forecasts"] == 100 and row["effective_dates"] == 5 and row["status"] == "ok"
    assert row["coverage_80"] == 1.0 and row["sharpness_80"] == pytest.approx(0.2)
    assert row["crps"] == pytest.approx(2 * row["pinball"]) and 0 <= row["brier"] <= 1
    fewer = horizon_calibration_scores(pd.DataFrame(rows[:20]))
    assert fewer.iloc[0]["effective_dates"] == 1 and fewer.iloc[0]["status"] == "insufficient_effective_dates"
    assert fewer.iloc[0]["pinball_se"] is None or np.isnan(fewer.iloc[0]["pinball_se"])


# 6. Checkpoint provenance ----------------------------------------------------------------------
def test_checkpoint_provenance_never_reuses_another_cutoff() -> None:
    timesfm3 = checkpoint_provenance("timesfm3", model_sha="abc123", config={"context_length": 2048})
    assert timesfm3.licence == "non-commercial" and timesfm3.model_sha == "abc123"
    assert timesfm3.cutoff_scope == "partial" and timesfm3.pretraining_cutoff == date(2023, 11, 30)
    assert timesfm3.leakage_flag(date(2023, 11, 30)) == "possibly_leaked"
    assert timesfm3.leakage_flag(date(2024, 1, 2)) == "after_declared_cutoff"
    for other in ("timesfm", "toto"):
        provenance = checkpoint_provenance(other)
        assert provenance.pretraining_cutoff is None and provenance.cutoff_scope == "unknown"
        assert provenance.licence == "unknown" and provenance.model_sha is None
        assert provenance.leakage_flag(date(2030, 1, 1)) == "possibly_leaked"
        assert provenance.as_row()["pretraining_cutoff"] == "unknown"


# 7. Admission wiring (correction pass 1) ---------------------------------------------------------
def _producer_row(name: str = "timesfm", **overrides: object) -> ForecastResult:
    values = dict(
        run_id="r", model_name=name, model_version="v", etf_id="AAA", forecast_date=date(2026, 3, 2), horizon_days=60,
        expected_return=0.02, expected_excess_return=None, forecast_vol=0.1, prob_positive_return=0.8, prob_beat_benchmark=0.7,
    )
    values.update(overrides)
    values.setdefault("target_id", adjusted_log_return_target(values["horizon_days"]).target_id)
    return ForecastResult(**values)


def test_producer_probabilities_stay_heuristic_unless_admitted() -> None:
    benchmark = pd.Series([0.001] * 100)
    for status in (None, {}, {"timesfm": "unavailable"}):
        row = _postprocess_forecast_benchmark_fields([_producer_row()], benchmark, status)[0]
        assert row.prob_positive_return is None and row.prob_beat_benchmark is None
        assert row.heuristic_probability_positive == 0.8 and row.heuristic_probability_beat_benchmark is not None
        assert row.probability_calibration_status == "unavailable"
    # An admission of another model never admits this one.
    other = _postprocess_forecast_benchmark_fields([_producer_row()], benchmark, {"toto": "calibrated"})[0]
    assert other.prob_positive_return is None
    admitted = _postprocess_forecast_benchmark_fields([_producer_row()], benchmark, {_probability_scope(_producer_row()): "calibrated"})[0]
    assert admitted.prob_positive_return == 0.8 and admitted.probability_calibration_status == "calibrated"
    assert admitted.heuristic_probability_positive is None
    assert admitted.prob_beat_benchmark is None  # no matured benchmark-outcome admission exists


def _matured_history(target_id: object = "adj_close_log_return_5d") -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2025-01-01", periods=220)
    prices = pd.DataFrame({"etf_id": "AAA", "date": index, "adjusted_close": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(index))))})
    series = prices.set_index("date")["adjusted_close"]
    rows = []
    for origin in index[:60]:
        actual = float(np.log(series.iloc[series.index.get_loc(origin) + 5] / series.loc[origin]))
        rows.append({
            "model_name": "timesfm", "etf_id": "AAA", "forecast_date": origin, "horizon_days": 5, "status": "ok",
            "expected_return": 0.0, "prob_positive_return": 0.95 if actual > 0 else 0.05, "model_version": "v", "run_id": "r",
            "created_at": origin + pd.Timedelta(hours=9), "target_id": target_id,
            "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1,
        })
    return pd.DataFrame(rows), prices


def test_matured_history_admits_only_calibrated_producers_and_honours_targets() -> None:
    history, prices = _matured_history()
    as_of = date(2025, 12, 31)
    assert positive_probability_status(history, prices, "timesfm", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5) == "calibrated"
    assert positive_probability_status(history, prices, "toto", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5) == "unavailable"
    # Point in time: with prices only up to the first origins, nothing has matured.
    assert positive_probability_status(history, prices, "timesfm", date(2025, 1, 6), model_version="v", target_id="adj_close_log_return_5d", horizon_days=5) == "unavailable"
    # A registered target of another horizon cannot count as probability evidence ...
    mismatched, _ = _matured_history(adjusted_log_return_target(60).target_id)
    assert matured_probability_frame(mismatched, prices, "timesfm", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5).empty
    assert len(matured_probability_frame(_matured_history(adjusted_log_return_target(5).target_id)[0], prices, "timesfm", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5)) == 60
    # ... nor a probability whose forecast was created after its origin day.
    late = history.assign(created_at=history["forecast_date"] + pd.Timedelta(days=3))
    assert positive_probability_status(late, prices, "timesfm", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5) == "unavailable"


def test_promotion_evidence_excludes_mismatched_registered_targets() -> None:
    index = pd.bdate_range("2025-01-01", periods=100)
    series = pd.Series(100 * np.exp(np.arange(100) * 0.001), index=index)
    pairs = pd.DataFrame({
        "etf_id": ["AAA"] * 4, "forecast_date": [index[0], index[1], index[2], index[3]],
        "target_id": [adjusted_log_return_target(20).target_id, adjusted_log_return_target(60).target_id, None, adjusted_log_return_target(20).target_id],
        "baseline_target_id": [adjusted_log_return_target(20).target_id] * 3 + [adjusted_log_return_target(60).target_id],
    })
    kept = _matured_pairs(pairs, {"AAA": series}, 20)
    assert list(kept["forecast_date"]) == [index[0]]  # unidentified and mismatched model or baseline rows cannot count


# 8. Checkpoint evidence (correction pass 1) ------------------------------------------------------
def test_checkpoint_evidence_records_declared_revision_and_config() -> None:
    declared = {"toto": {"revision": "abc123", "backend": "toto2", "context_length": 2048, "model_path": "models/x", "device": "auto"}}
    evidence = _checkpoint_evidence("toto", declared)
    assert evidence["checkpoint_sha"] == "abc123"
    assert json.loads(evidence["checkpoint_config"]) == {"backend": "toto2", "context_length": 2048}  # no paths/devices
    # An absent source stays unknown and is never taken from another model's entry.
    missing = _checkpoint_evidence("timesfm", declared)
    assert missing["checkpoint_sha"] == "unknown" and json.loads(missing["checkpoint_config"]) == {}
    # Without supplied settings the metadata comes from configs/model_settings.yaml.
    shipped = _checkpoint_evidence("timesfm")
    assert json.loads(shipped["checkpoint_config"])["hf_repo_id"] == "google/timesfm-2.5-200m-transformers"
    row = _forecast_to_row(_shadow_forecast(_producer_row("toto")), None, declared)
    assert row["checkpoint_sha"] == "abc123" and json.loads(row["checkpoint_config"])["backend"] == "toto2"
    assert row["checkpoint_licence"] == "unknown" and row["cutoff_scope"] == "unknown"


def test_unadmitted_producer_history_can_earn_calibration_from_heuristic_column() -> None:
    """Demoted rows carry P(up) only as ``heuristic_probability_positive``; admission must still see it."""

    history, prices = _matured_history()
    rows = []
    for record in history.to_dict("records"):
        forecast = _producer_row(
            forecast_date=record["forecast_date"].date(), horizon_days=5, prob_positive_return=record["prob_positive_return"]
        )
        row = _forecast_to_row(_demote_unadmitted_probabilities(forecast, {}))
        assert row["prob_positive_return"] is None and row["heuristic_probability_positive"] is not None
        rows.append({**row, "status": "ok", "created_at": record["created_at"], "target_id": "adj_close_log_return_5d", "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1})
    demoted = pd.DataFrame(rows)
    as_of = date(2025, 12, 31)
    assert len(matured_probability_frame(demoted, prices, "timesfm", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5)) == 60
    assert positive_probability_status(demoted, prices, "timesfm", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5) == "calibrated"
    # A baseline row without any probability column never earns one.
    assert positive_probability_status(demoted.assign(heuristic_probability_positive=None), prices, "timesfm", as_of, model_version="v", target_id="adj_close_log_return_5d", horizon_days=5) == "unavailable"


def test_forecast_consumers_show_simple_return_of_log_forecasts() -> None:
    from etf_cockpit.app.pages.etf_detail import _log_return_label
    from etf_cockpit.app.pages.stock_page import _log_percent
    from etf_cockpit.signals.simple_scores import _forecast_component

    assert _log_return_label(0.10) == "+10.5%" and _log_return_label(float("nan")) == "N/A"
    assert _log_percent(0.10) == "10.5%" and _log_percent(None) != "10.5%"
    details = pd.DataFrame([{"model_name": "timesfm", "etf_id": "AAA", "horizon_days": 60, "expected_return": 0.10}])
    component = _forecast_component("AAA", "timesfm", {"timesfm": {"AAA": 0.5}}, details, details)
    assert "+10.5%" in component.why and "+10.0%" not in component.why


@pytest.mark.parametrize("identity", [None, "unknown-target"])
def test_unidentified_targets_fail_closed_at_publication_and_evidence(identity):
    forecast = _producer_row(target_id=identity)
    row = _forecast_to_row(forecast)
    assert row["status"] == "unavailable" and not row["model_allowed_in_score"]
    assert "target identity" in row["reason_unavailable"] and row["prob_positive_return"] is None
    history, prices = _matured_history(identity)
    assert matured_probability_frame(history, prices, "timesfm", date(2025, 12, 31), model_version="v", target_id=identity, horizon_days=5).empty


@pytest.mark.parametrize("field,value", [("q10_return", 1.0), ("q05_return", float("nan")), ("q95_return", float("inf"))])
def test_any_invalid_selected_member_disables_entire_mixture(field, value):
    good = dict(etf_id="X", model_name="a", horizon_days=60, forecast_date="2026-01-02", expected_return=0.0, status="ok", model_allowed_in_score=True, target_id="adj_close_log_return_60d", **_vector(0.0))
    bad = {**good, "model_name": "b", field: value}
    result = forecast_return_distributions(pd.DataFrame([good, bad]))["X"]
    assert result["canonical_status"] == "unavailable" and result["q50_return"] is None


def test_probability_admission_cannot_transfer_version_target_or_horizon():
    history, prices = _matured_history()
    scope = dict(model_version="v", target_id="adj_close_log_return_5d", horizon_days=5)
    assert positive_probability_status(history, prices, "timesfm", date(2025, 12, 31), **scope) == "calibrated"
    for changed in ({"model_version": "v2"}, {"target_id": "unknown"}, {"horizon_days": 60, "target_id": "adj_close_log_return_60d"}):
        assert positive_probability_status(history, prices, "timesfm", date(2025, 12, 31), **(scope | changed)) == "unavailable"
    forecast = _producer_row()
    assert _demote_unadmitted_probabilities(forecast, {("timesfm", "v", "adj_close_log_return_5d", 5): "calibrated"}).prob_positive_return is None


def test_missing_horizon_metrics_disable_production_forecast_and_probability():
    from types import SimpleNamespace
    history, prices = _matured_history()
    history = history.drop(columns=["q10_return", "q50_return", "q90_return"])
    service = object.__new__(ForecastService)
    service.config = SimpleNamespace(models=SimpleNamespace(models={}))
    forecast = _producer_row("baseline", horizon_days=5)
    result = service._evidence_gated_forecasts([forecast], date(2025, 12, 31), prices, history.assign(model_name="baseline"))[0]
    assert result.status == "unavailable" and not result.model_allowed_in_score
    assert "Insufficient" in result.reason_unavailable and result.prob_positive_return is None
    assert positive_probability_status(history, prices, "timesfm", date(2025, 12, 31), model_version="v", target_id="adj_close_log_return_5d", horizon_days=5) == "unavailable"


@pytest.mark.parametrize("revision", [None, "main", "abc123", "unknown"])
def test_unverifiable_checkpoint_disables_optional_publication(revision):
    forecast = _producer_row(model_allowed_in_score=True)
    settings = {"timesfm": {"revision": revision}}
    gated = _identity_gated_forecast(forecast, settings)
    row = _forecast_to_row(forecast, model_settings=settings)
    assert gated.status == row["status"] == "unavailable"
    assert not row["model_allowed_in_score"] and row["prob_positive_return"] is None
    assert "checkpoint identity" in row["reason_unavailable"]


def test_distribution_target_gate_keeps_declared_horizon_ids_but_rejects_blank_and_mismatched_registry_ids():
    base = dict(etf_id="X", model_name="a", horizon_days=60, forecast_date="2026-01-02", expected_return=0.0, status="ok", model_allowed_in_score=True, **_vector(0.0))
    custom = {**base, "target_id": "custom-target", "target_horizon_days": 60}
    assert forecast_return_distributions(pd.DataFrame([custom]))["X"]["status"] == "available"
    for identity in (None, "  ", "adj_close_log_return_20d"):
        result = forecast_return_distributions(pd.DataFrame([{**custom, "target_id": identity}]))["X"]
        assert result["canonical_status"] == "unavailable" and result["q50_return"] is None


def test_component_maps_exclude_rows_without_expected_return():
    rows = pd.DataFrame([
        dict(etf_id="X", model_name="baseline", horizon_days=60, forecast_date="2026-01-02", expected_return=float("nan"), status="ok", model_allowed_in_score=True),
        dict(etf_id="Y", model_name="baseline", horizon_days=60, forecast_date="2026-01-02", expected_return=0.02, status="ok", model_allowed_in_score=True),
    ])
    scores = forecast_component_maps(rows)["baseline"]
    assert "X" not in scores and "Y" in scores


def test_adapter_forecast_with_immutable_revision_reaches_calibrated_from_heuristic_history():
    from types import SimpleNamespace
    revision = "a" * 40
    settings = {"timesfm": {"revision": revision}}
    service = object.__new__(ForecastService)
    service.config = SimpleNamespace(models=SimpleNamespace(models=settings))
    history, prices = _matured_history()
    as_of = date(2025, 12, 31)
    rows = []
    for record in history.to_dict("records"):
        produced = _stamp_adjusted_log_return_target([_producer_row(
            forecast_date=record["forecast_date"].date(), horizon_days=5, target_id=None,
            prob_positive_return=record["prob_positive_return"],
        )])[0]
        assert produced.target_id == "adj_close_log_return_5d"
        # No stored history yet: insufficient metrics -> unavailable, but P(up) is kept as a heuristic.
        gated = service._evidence_gated_forecasts([produced], as_of, prices, history.iloc[0:0])[0]
        assert gated.status == "unavailable" and gated.prob_positive_return is None
        assert gated.heuristic_probability_positive == record["prob_positive_return"]
        rows.append({**_forecast_to_row(gated, model_settings=settings), "created_at": record["created_at"], "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1})
    stored = pd.DataFrame(rows)
    scope = dict(model_version="v", target_id="adj_close_log_return_5d", horizon_days=5)
    assert positive_probability_status(stored, prices, "timesfm", as_of, **scope) == "calibrated"
    latest = _stamp_adjusted_log_return_target([_producer_row(horizon_days=5, target_id=None, forecast_date=date(2025, 12, 31))])[0]
    assert service._evidence_gated_forecasts([latest], as_of, prices, stored)[0].status == "ok"
    assert _unavailable_forecast(_producer_row(), "x").heuristic_probability_positive == 0.8
