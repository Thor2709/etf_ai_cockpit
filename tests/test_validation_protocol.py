from __future__ import annotations

import numpy as np
import pytest

from etf_cockpit.validation.protocol import (
    ValidationSpec,
    build_walk_forward_splits,
    evaluate_trials,
    report_fingerprint,
)


def test_walk_forward_folds_purge_labels_and_embargo_future_rows() -> None:
    spec = ValidationSpec(n_splits=4, test_size=8, horizon=3, embargo=2, final_test_size=8)
    folds = build_walk_forward_splits(80, spec)

    assert len(folds) == 4
    assert all(set(fold.train_indices).isdisjoint(fold.validation_indices) for fold in folds)
    assert all(max(fold.train_indices) < min(fold.validation_indices) - spec.horizon + 1 for fold in folds)
    assert all(set(fold.train_indices).isdisjoint(fold.embargoed_indices) for fold in folds)
    assert folds[-1].validation_indices[-1] < 80 - spec.final_test_size


def test_validation_retains_discarded_trials_and_never_uses_final_test_for_selection() -> None:
    spec = ValidationSpec(n_splits=3, test_size=10, final_test_size=10, bootstrap_repetitions=30, seed=7)
    baseline = np.full(80, 0.10)
    challenger = np.full(80, 0.20)
    challenger[-10:] = 0.00
    baseline[-10:] = 0.50
    report = evaluate_trials(
        {"baseline": baseline, "challenger": challenger},
        spec=spec,
        parameters={"baseline": {"kind": "naive"}, "challenger": {"kind": "candidate"}},
        regime_labels=["calm" if index % 2 else "stress" for index in range(80)],
        subgroup_labels=["A" if index % 3 else "B" for index in range(80)],
    )

    assert report.selected_trial_id == "challenger"
    assert report.final_test_used_for_selection is False
    assert report.final_test_score == 0.0
    assert len(report.trials) == 2
    assert any(trial.discarded_reason for trial in report.trials if trial.trial_id == "baseline")
    assert report.regime_results and report.subgroup_results
    assert report.effective_independent_trial_count >= 1
    assert report.to_dict()["report_fingerprint"] == report_fingerprint(report)


def test_insufficient_stability_blocks_promotion_for_known_noise() -> None:
    rng = np.random.default_rng(12)
    scores = {"baseline": rng.normal(0, 0.01, 80), "noise_trial": rng.normal(0, 0.01, 80)}
    report = evaluate_trials(scores, spec=ValidationSpec(n_splits=3, test_size=10, final_test_size=10, bootstrap_repetitions=20))

    assert report.promotion_eligible is False
    assert "promotion_evidence_insufficient_or_unstable" in report.warnings
    assert report.uncertainty["status"] == "available"


def test_missing_baseline_is_visible_and_invalid_specs_fail_closed() -> None:
    report = evaluate_trials({"candidate": np.ones(80)}, spec=ValidationSpec(n_splits=3, test_size=10, final_test_size=10))
    assert "baseline_trial_missing" in report.warnings
    assert report.promotion_eligible is False

    with pytest.raises(ValueError, match="at least"):
        build_walk_forward_splits(20, ValidationSpec(n_splits=3, test_size=10, final_test_size=10))
