"""Forecast honesty (#943): target registry, return space, heuristic probabilities, mixture quantiles, provenance."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

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
from etf_cockpit.models.forecast_scores import forecast_return_distributions
from etf_cockpit.models.model_promotion import checkpoint_provenance


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
        "expected_return": 0.0, "status": "ok", "model_allowed_in_score": True,
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
            "status": "ok", "model_allowed_in_score": True,
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
        "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1, "status": "ok", "model_allowed_in_score": True,
        "calibration_status": "not_evaluated", "calibration_horizon_days": 60, "prob_positive_return": 0.9,
        "prob_beat_cash": 0.9, "prob_beat_benchmark": 0.9,
    }])
    distribution = forecast_return_distributions(uncalibrated)["X"]
    assert distribution["probability_loss"] is None and distribution["probability_beat_benchmark"] is None


def test_probability_admission_requires_chronological_out_of_sample_evidence() -> None:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2025-01-01", periods=60)
    probability = rng.uniform(0.05, 0.95, len(dates))
    informative = pd.DataFrame({
        "forecast_date": dates, "probability": probability, "outcome": (rng.uniform(size=len(dates)) < probability).astype(int),
    })
    assert probability_admission(informative)["status"] in {"calibrated", "unavailable"}
    constant = pd.DataFrame({"forecast_date": dates, "probability": 0.9, "outcome": (np.arange(len(dates)) % 2)})
    assert probability_admission(constant)["status"] == "unavailable"
    short = informative.head(6)
    assert probability_admission(short)["status"] == "unavailable"
    assert probability_admission(pd.DataFrame({"x": [1]}))["status"] == "unavailable"


# 4. Target registry ----------------------------------------------------------------------------
def test_target_mismatch_is_rejected() -> None:
    sixty = adjusted_log_return_target(60)
    assert require_same_target(sixty.target_id, sixty.target_id) is sixty or require_same_target(sixty.target_id, sixty.target_id) == sixty
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
        "expected_return": 0.02, "status": "ok", "model_allowed_in_score": True,
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
