from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pytest

from etf_cockpit.features.training_centre import LocalTrainingRegistry
from etf_cockpit.validation.protocol import (
    ValidationSpec,
    build_walk_forward_splits,
    evaluate_trials,
)


def _spec(**changes: object) -> ValidationSpec:
    options: dict[str, object] = {
        "n_splits": 3,
        "test_size": 10,
        "final_test_size": 10,
        "horizon": 1,
        "bootstrap_repetitions": 100,
        "block_size": 5,
        "seed": 17,
    }
    options.update(changes)
    if options.get("periods_per_year") is None:
        options.pop("periods_per_year", None)
    return ValidationSpec(**options)  # type: ignore[arg-type]


def test_dsr_uses_skew_kurtosis_trial_count_and_declared_frequency() -> None:
    values = np.array([-0.01, 0.00, 0.01, 0.02, -0.005, 0.015] * 10, dtype=float)
    spec = _spec(n_splits=2, test_size=10, final_test_size=10, periods_per_year=12)
    report = evaluate_trials({"baseline": np.zeros(80), "candidate": np.resize(values, 80)}, spec=spec)

    selected = np.resize(values, 80)
    validation = np.concatenate([selected[list(fold.validation_indices)] for fold in report.folds])
    sample_std = validation.std(ddof=1)
    periodic_sr = validation.mean() / sample_std
    annual_sr = periodic_sr * np.sqrt(12)
    standardized = (validation - validation.mean()) / sample_std
    skew = np.mean(standardized**3)
    pearson_kurtosis = np.mean(standardized**4)
    variance = (1 - skew * annual_sr + ((pearson_kurtosis - 1) / 4) * annual_sr**2) / (len(validation) - 1)
    trials = report.effective_independent_trial_count
    gamma = 0.5772156649015329
    normal = NormalDist()
    expected_max = np.sqrt(variance) * (
        (1 - gamma) * normal.inv_cdf(1 - 1 / trials)
        + gamma * normal.inv_cdf(1 - 1 / (trials * np.e))
    )
    expected_probability = normal.cdf((annual_sr - expected_max) / np.sqrt(variance))

    assert report.deflated_sharpe == pytest.approx(expected_probability)
    assert 0 <= report.deflated_sharpe <= 1


def test_pbo_uses_cscv_winner_ranks_not_full_run_rank_disagreement() -> None:
    # The first strategy wins every complementary split. The two inferior
    # strategies exchange order between development and the reserved window.
    anchor = np.full(80, 0.03)
    lower_a = np.tile(np.r_[np.full(10, 0.02), np.full(10, 0.00)], 4)
    lower_b = np.tile(np.r_[np.full(10, 0.00), np.full(10, 0.02)], 4)
    lower_a[-10:] = 0.00
    lower_b[-10:] = 0.02
    report = evaluate_trials(
        {"anchor": anchor, "lower_a": lower_a, "lower_b": lower_b},
        spec=_spec(n_splits=3, test_size=10, final_test_size=10),
    )

    assert report.probability_of_backtest_overfitting == pytest.approx(0.0)


def test_single_trial_pbo_is_unavailable_with_a_reason() -> None:
    report = evaluate_trials({"only": np.linspace(-0.01, 0.02, 80)}, spec=_spec())

    assert report.probability_of_backtest_overfitting is None
    assert any("pbo_unavailable" in warning for warning in report.warnings)


def test_fdr_responds_to_paired_p_value_evidence() -> None:
    rng = np.random.default_rng(29)
    baseline = np.zeros(80)
    strong = baseline + 0.01
    weak = rng.normal(0.0, 0.02, 80)
    spec = _spec(n_splits=3, test_size=10, final_test_size=10)
    strong_report = evaluate_trials({"baseline": baseline, "candidate": strong}, spec=spec)
    weak_report = evaluate_trials({"baseline": baseline, "candidate": weak}, spec=spec)

    assert strong_report.false_discovery_rate is not None
    assert weak_report.false_discovery_rate is not None
    assert strong_report.false_discovery_rate < weak_report.false_discovery_rate


def test_only_frozen_candidate_and_predeclared_comparators_read_holdout() -> None:
    baseline = np.full(80, 0.01)
    frozen = np.full(80, 0.02)
    unregistered = np.full(80, 0.03)
    report = evaluate_trials(
        {"baseline": baseline, "frozen": frozen, "unregistered": unregistered},
        spec=_spec(),
        frozen_candidate_id="frozen",
        predeclared_comparator_ids=("baseline",),
        holdout_id="holdout-928",
    )

    final_scores = {trial.trial_id: trial.final_test_score for trial in report.trials}
    assert final_scores == {"baseline": 0.01, "frozen": 0.02, "unregistered": None}


def test_training_label_windows_do_not_overlap_sealed_holdout() -> None:
    spec = _spec(n_splits=3, test_size=10, final_test_size=10, horizon=3)
    folds = build_walk_forward_splits(100, spec)
    holdout_start = 100 - spec.final_test_size

    assert all(max(fold.validation_indices) + spec.horizon < holdout_start for fold in folds)


def test_candidate_champion_inference_bootstraps_paired_improvement() -> None:
    baseline = np.full(80, 0.02)
    candidate = baseline + 0.004
    report = evaluate_trials(
        {"baseline": baseline, "candidate": candidate},
        spec=_spec(),
    )

    assert report.uncertainty["mean"] == pytest.approx(0.004)
    assert report.uncertainty["paired_with"] == "baseline"


def test_train_label_purge_excludes_the_first_validation_label_observation() -> None:
    spec = _spec(n_splits=3, test_size=10, final_test_size=10, horizon=3)
    folds = build_walk_forward_splits(100, spec)

    assert all(max(fold.train_indices) + spec.horizon < min(fold.validation_indices) for fold in folds)


def test_final_holdout_does_not_inflate_trial_correlation_count() -> None:
    baseline = np.linspace(-0.01, 0.01, 80)
    correlated = baseline + np.sin(np.arange(80)) * 0.0001
    altered = correlated.copy()
    altered[-10:] = np.linspace(-10, 10, 10)
    spec = _spec()
    before = evaluate_trials({"baseline": baseline, "trial": correlated}, spec=spec)
    after = evaluate_trials({"baseline": baseline, "trial": altered}, spec=spec)

    assert before.effective_independent_trial_count == pytest.approx(after.effective_independent_trial_count)


def test_minimum_split_rejects_fewer_than_two_post_purge_training_rows() -> None:
    spec = _spec(n_splits=2, test_size=5, final_test_size=5, horizon=2, periods_per_year=None)

    with pytest.raises(ValueError, match="two training observations"):
        build_walk_forward_splits(17, spec)


def test_two_dimensional_trial_scores_are_rejected() -> None:
    with pytest.raises(ValueError, match="one-dimensional"):
        evaluate_trials({"baseline": np.ones((80, 2))}, spec=_spec())


def test_date_clustered_bootstrap_counts_origins_not_cross_section_rows() -> None:
    dates = [date for date in range(20) for _ in range(5)]
    baseline = np.zeros(100)
    candidate = np.tile(np.array([-0.01, 0.00, 0.01, 0.02, -0.02]), 20) + 0.01
    report = evaluate_trials(
        {"baseline": baseline, "candidate": candidate},
        spec=_spec(n_splits=2, test_size=2, final_test_size=2),
        date_labels=dates,
    )

    assert report.uncertainty["observations"] == 16
    assert report.uncertainty["effective_dates"] == 16


def test_prior_validation_trials_join_the_multiple_testing_family() -> None:
    rng = np.random.default_rng(7)
    scores = {"baseline": np.zeros(80), "candidate": rng.normal(0.001, 0.01, 80)}
    prior = {f"prior-{index}": rng.normal(0.0, 0.01, 80) for index in range(4)}
    report = evaluate_trials(scores, spec=_spec(), prior_trial_scores=prior)

    assert report.effective_independent_trial_count >= len(scores) + len(prior)


def test_holdout_use_audit_is_append_only_and_detects_reuse(tmp_path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    first = registry.record_validation_holdout_use(
        "holdout-928", run_id="validation-run-1", candidate_id="candidate", comparator_ids=("baseline",)
    )
    second = registry.record_validation_holdout_use(
        "holdout-928", run_id="validation-run-2", candidate_id="candidate", comparator_ids=("baseline",)
    )

    assert first["reused"] is False
    assert second["reused"] is True
    assert registry.list_validation_holdout_uses("holdout-928") == (first, second)
