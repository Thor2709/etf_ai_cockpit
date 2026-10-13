from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pytest

from etf_cockpit.application.validation import evaluate_registered_trials
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.features.training_centre import LocalTrainingRegistry, TrainingRegistryError
from etf_cockpit.validation.optimisation import OptimisationLedger, TrialRecord
from etf_cockpit.validation.protocol import (
    ValidationSpec,
    _deflated_sharpe,
    _false_discovery_rate,
    _paired_block_bootstrap,
    _pbo_probability,
    build_walk_forward_splits,
    evaluate_trials,
)


def _run(root, run_id="run-928", *, data="aligned-date-panel"):
    registry = LocalTrainingRegistry(root)
    experiment = registry.create_experiment("issue928", experiment_id="experiment-928")
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()
    registry.create_run(
        str(experiment["experiment_id"]), run_id=run_id, dataset_hash=digest(data),
        feature_hash=digest("features"), code_hash=digest("code"), environment_hash=digest("environment"),
    )
    return registry


def _registered(root, scores, *, run_id="run-928", **options):
    _run(root, run_id)
    # Sealed scoring requires actual calendar identities, never row offsets.
    options.setdefault("date_labels", [date(2025, 1, 1) + timedelta(days=i) for i in range(len(next(iter(scores.values()))))])
    return evaluate_registered_trials(root, run_id, scores, **options)


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


def test_dsr_uses_skew_kurtosis_trial_count_and_declared_frequency(tmp_path) -> None:
    values = np.array([-0.01, 0.00, 0.01, 0.02, -0.005, 0.015] * 10, dtype=float)
    spec = _spec(n_splits=2, test_size=10, final_test_size=10, periods_per_year=12)
    baseline = np.resize(values, 80) - 0.004
    report = _registered(tmp_path, {"baseline": baseline, "candidate": np.resize(values, 80)}, spec=spec)

    selected = np.resize(values, 80)
    validation = np.concatenate([selected[list(fold.validation_indices)] for fold in report.folds])
    sample_std = validation.std(ddof=1)
    periodic_sr = validation.mean() / sample_std
    standardized = (validation - validation.mean()) / validation.std(ddof=0)
    skew = np.mean(standardized**3)
    pearson_kurtosis = np.mean(standardized**4)
    variance = (1 - skew * periodic_sr + ((pearson_kurtosis - 1) / 4) * periodic_sr**2) / (len(validation) - 1)
    baseline_validation = np.concatenate([baseline[list(fold.validation_indices)] for fold in report.folds])
    trial_variance = np.var([periodic_sr, baseline_validation.mean() / baseline_validation.std(ddof=1)], ddof=1)
    trials = report.effective_independent_trial_count
    gamma = 0.5772156649015329
    normal = NormalDist()
    expected_max = np.sqrt(trial_variance) * (
        (1 - gamma) * normal.inv_cdf(1 - 1 / trials)
        + gamma * normal.inv_cdf(1 - 1 / (trials * np.e))
    )
    expected_probability = normal.cdf((periodic_sr - expected_max) / np.sqrt(variance))

    assert report.deflated_sharpe == pytest.approx(expected_probability)
    assert 0 <= report.deflated_sharpe <= 1


def test_pbo_uses_cscv_winner_ranks_not_full_run_rank_disagreement(tmp_path) -> None:
    # The first strategy wins every complementary split. The two inferior
    # strategies exchange order between development and the reserved window.
    anchor = np.full(80, 0.03)
    lower_a = np.tile(np.r_[np.full(10, 0.02), np.full(10, 0.00)], 4)
    lower_b = np.tile(np.r_[np.full(10, 0.00), np.full(10, 0.02)], 4)
    lower_a[-10:] = 0.00
    lower_b[-10:] = 0.02
    report = _registered(
        tmp_path, {"anchor": anchor, "lower_a": lower_a, "lower_b": lower_b},
        spec=_spec(n_splits=3, test_size=10, final_test_size=10),
    )

    assert report.probability_of_backtest_overfitting == pytest.approx(0.0)


def test_single_trial_pbo_is_unavailable_with_a_reason() -> None:
    report = evaluate_trials({"only": np.linspace(-0.01, 0.02, 80)}, spec=_spec())

    assert report.probability_of_backtest_overfitting is None
    assert any("pbo_unavailable" in warning for warning in report.warnings)


def test_fdr_responds_to_paired_p_value_evidence(tmp_path) -> None:
    rng = np.random.default_rng(29)
    baseline = np.zeros(80)
    strong = baseline + 0.01
    weak = rng.normal(0.0, 0.02, 80)
    spec = _spec(n_splits=3, test_size=10, final_test_size=10)
    strong_report = _registered(tmp_path / "strong", {"baseline": baseline, "candidate": strong}, spec=spec)
    weak_report = _registered(tmp_path / "weak", {"baseline": baseline, "candidate": weak}, spec=spec)

    assert strong_report.false_discovery_rate is not None
    assert weak_report.false_discovery_rate is not None
    assert strong_report.false_discovery_rate < weak_report.false_discovery_rate


def test_only_frozen_candidate_and_predeclared_comparators_read_holdout(tmp_path) -> None:
    baseline = np.full(80, 0.01)
    frozen = np.full(80, 0.02)
    unregistered = np.full(80, 0.03)
    report = _registered(
        tmp_path, {"baseline": baseline, "frozen": frozen, "unregistered": unregistered},
        spec=_spec(),
        frozen_candidate_id="frozen",
        predeclared_comparator_ids=("baseline",),
        holdout_id="holdout-928",
    )

    final_scores = {trial.trial_id: trial.final_test_score for trial in report.trials}
    assert final_scores == {"baseline": 0.01, "frozen": 0.02, "unregistered": None}


@pytest.mark.parametrize("periods_per_year", [None, 12])
def test_promotion_requires_available_statistical_evidence(tmp_path, periods_per_year) -> None:
    report = _registered(
        tmp_path, {"baseline": np.zeros(80), "candidate": np.full(80, 0.01)},
        spec=_spec(periods_per_year=periods_per_year),
        frozen_candidate_id="candidate", predeclared_comparator_ids=("baseline",),
        holdout_id="unavailable-statistics-928",
    )

    assert report.uncertainty["trial_family_status"] == "available"
    assert report.uncertainty["lower_5"] > 0
    assert len(report.folds) == 3
    assert report.holdout_status == "scored"
    assert report.final_test_score == pytest.approx(0.01)
    assert report.deflated_sharpe is None
    assert report.probability_of_backtest_overfitting is not None
    assert report.false_discovery_rate is not None
    reason = report.uncertainty["unavailable_reasons"]["deflated_sharpe"]
    expected_reason = (
        "periods_per_year_required" if periods_per_year is None
        else "multiple_trials_with_finite_sharpe_and_positive_variance_required"
    )
    assert reason == expected_reason
    assert f"dsr_unavailable:{reason}" in report.warnings
    assert report.promotion_eligible is False
    assert "promotion_required_statistics_unavailable" in report.warnings


def test_training_label_windows_do_not_overlap_sealed_holdout() -> None:
    spec = _spec(n_splits=3, test_size=10, final_test_size=10, horizon=3)
    folds = build_walk_forward_splits(100, spec, strict_label_purge=True)
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
    # Convention: the label of row t spans t+1..t+horizon, so training row t is
    # usable only if t + horizon < first validation row.
    spec = _spec(n_splits=3, test_size=10, final_test_size=10, horizon=3)
    folds = build_walk_forward_splits(100, spec, strict_label_purge=True)

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
    assert before.effective_independent_trial_count == before.total_trial_count == 2  # no correlation discount


def test_minimum_split_rejects_fewer_than_two_post_purge_training_rows() -> None:
    spec = _spec(n_splits=2, test_size=5, final_test_size=5, horizon=2, periods_per_year=None)

    with pytest.raises(ValueError, match="two post-purge training observations"):
        build_walk_forward_splits(17, spec, strict_label_purge=True)


def test_paired_bootstrap_block_covers_the_label_horizon() -> None:
    rng = np.random.default_rng(3)
    noise = np.convolve(rng.normal(size=120), np.ones(8) / 8, mode="same")
    short = _paired_block_bootstrap(noise, _spec(block_size=2, horizon=1, bootstrap_repetitions=400), paired_with="baseline")
    long_horizon = _paired_block_bootstrap(noise, _spec(block_size=2, horizon=8, bootstrap_repetitions=400), paired_with="baseline")
    capped = _paired_block_bootstrap(noise[:6], _spec(block_size=2, horizon=8), paired_with="baseline")

    assert short["block_size"] == 2
    assert long_horizon["block_size"] == 8  # effective block = max(block_size, horizon)
    assert capped["block_size"] == 3  # but at least two blocks must still fit (n // 2)
    assert (long_horizon["upper_95"] - long_horizon["lower_5"]) >= (short["upper_95"] - short["lower_5"])


def test_periods_per_year_keeps_pre_change_spec_fingerprints() -> None:
    legacy_payload = {
        "n_splits": 5, "test_size": 20, "horizon": 1, "embargo": 0, "final_test_size": 20,
        "expanding": True, "train_size": None, "bootstrap_repetitions": 200, "block_size": 5, "seed": 42,
    }
    expected = hashlib.sha256(
        json.dumps(legacy_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    assert ValidationSpec().fingerprint == expected
    assert ValidationSpec(periods_per_year=12).fingerprint != expected


def test_unavailable_metrics_carry_concrete_reasons(tmp_path) -> None:
    scores = {"baseline": np.linspace(-0.02, 0.02, 80), "candidate": np.linspace(-0.01, 0.03, 80)}
    _run(tmp_path, "unrecorded-run")
    missing = _registered(tmp_path, scores, run_id="current-run", spec=_spec(periods_per_year=12))
    reasons = missing.uncertainty["unavailable_reasons"]

    assert set(reasons) == {"deflated_sharpe", "probability_of_backtest_overfitting", "false_discovery_rate"}
    assert all("unrecorded-run" in text for text in reasons.values())
    assert "unrecorded-run" in missing.uncertainty["trial_family_detail"]
    other = tmp_path / "alignment"
    _registered(other, scores, run_id="prior", spec=_spec(), date_labels=list(range(80)))
    changed = _registered(other, scores, run_id="later", spec=_spec(), date_labels=list(range(1, 81)))
    detail = changed.uncertainty["trial_family_detail"]
    assert "run=prior" in detail and "alignment mismatch" in detail
    assert "alignment mismatch" in changed.uncertainty["unavailable_reasons"]["false_discovery_rate"]
    no_frequency = evaluate_trials(scores, spec=_spec())
    assert "trial_family_unverified" in no_frequency.uncertainty["unavailable_reasons"]["deflated_sharpe"]


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

    assert report.uncertainty["observations"] == 4
    assert report.uncertainty["effective_dates"] == 4


def test_prior_validation_trials_join_the_multiple_testing_family(tmp_path) -> None:
    rng = np.random.default_rng(7)
    scores = {"baseline": np.zeros(80), "candidate": rng.normal(0.001, 0.01, 80)}
    prior = {f"prior-{index}": rng.normal(0.0, 0.01, 80) for index in range(4)}
    _registered(tmp_path, prior, run_id="rejected-run", spec=_spec())
    # A fresh registry/application instance discovers all rejected trials itself.
    report = _registered(tmp_path, scores, run_id="later-run", spec=_spec())

    assert report.effective_independent_trial_count >= len(scores) + len(prior)


def test_holdout_use_audit_is_append_only_and_detects_reuse(tmp_path) -> None:
    registry = _run(tmp_path, "validation-run-1")
    _run(tmp_path, "validation-run-2")
    first = registry.record_validation_holdout_use(
        "holdout-928", run_id="validation-run-1", candidate_id="candidate", comparator_ids=("baseline",)
    )
    second = registry.record_validation_holdout_use(
        "holdout-928", run_id="validation-run-2", candidate_id="candidate", comparator_ids=("baseline",)
    )

    assert first["reused"] is False
    assert second["reused"] is True
    assert registry.list_validation_holdout_uses("holdout-928") == (first, second)
    with pytest.raises(TrainingRegistryError, match="immutable"):
        registry._put_immutable("validation.holdout_use", first["use_id"], {**first, "reused": True})
    assert registry.list_validation_holdout_uses("holdout-928") == (first, second)


def test_issue928_1_chronological_clusters_and_paired_block_reference() -> None:
    # Reversing complete date clusters preserves chronological folds and paired evidence.
    dates = np.repeat(np.arange(20), 2)
    scores = {"baseline": np.sin(dates), "candidate": np.sin(dates) + 0.025}
    spec = _spec(n_splits=2, test_size=2, final_test_size=2, block_size=1)
    ascending = evaluate_trials(scores, spec=spec, date_labels=dates)
    reversed_report = evaluate_trials({key: value[::-1] for key, value in scores.items()}, spec=spec, date_labels=dates[::-1])
    assert reversed_report.uncertainty == ascending.uncertainty
    assert ascending.uncertainty["mean"] == pytest.approx(0.025)
    assert ascending.uncertainty["lower_5"] == pytest.approx(0.025)
    assert ascending.uncertainty["p_value"] == pytest.approx(1 / 101)
    assert ascending.uncertainty["observations"] == 4


def test_issue928_2_published_method_numeric_references() -> None:
    # These DSR/CSCV oracles are hand-derived from the named methods, not
    # reproduced published worked examples or independent implementations.
    # DSR: symmetric returns give SR=0, skew=0, Pearson kurtosis=1.36,
    # estimator variance=1/3; two trial SRs (-1,+1) give variance=2.
    # Bailey/Lopez de Prado expected-max formula => probability below.
    values = np.array([-2., -1., 1., 2.])
    assert _deflated_sharpe(values, 2, 12, [-1., 1.]) == pytest.approx(0.10148500228858098)
    assert _deflated_sharpe(values, 2, 252, [-1., 1.]) == pytest.approx(0.10148500228858098)
    # CSCV: six complementary 2-of-4 splits; OOS relative winner ranks
    # (1/4, 3/8, 5/8, 5/8, 3/8, 1/4) have four non-positive logits.
    probability, reason = _pbo_probability({
        "a": np.array([3., 2., 1., 0.]), "b": np.array([0., 1., 2., 3.]), "c": np.ones(4),
    })
    assert probability == pytest.approx(2 / 3)
    assert reason is None
    # BY m=4, H_m=25/12: ordered step-up values are
    # (1/12, 1/12, 5/36, 5/3); minimum adjusted q = 1/12.
    assert _false_discovery_rate([0.8, 0.01, 0.05, 0.02]) == pytest.approx(1 / 12)


def test_issue928_fdr_matches_independent_scipy_reference() -> None:
    # SciPy's independently maintained BY implementation, not a hand-derived oracle.
    from scipy.stats import false_discovery_control

    for values in ([0.8, 0.01, 0.05, 0.02], [0.0, 0.5, 1.0], [0.03, 0.03, 0.9], [0.01]):
        adjusted = false_discovery_control(values, method="by")
        assert _false_discovery_rate(values) == pytest.approx(float(np.min(adjusted)))
    # Published TAPS p-values reproduced in SciPy's documented example;
    # compare BY here (the documentation's displayed adjustment uses BH).
    taps = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
            0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0]
    assert _false_discovery_rate(taps) == pytest.approx(
        float(np.min(false_discovery_control(taps, method="by")))
    )


def test_issue928_3_incomplete_or_misaligned_durable_family_fails_closed(tmp_path) -> None:
    scores = {"baseline": np.linspace(-0.02, 0.02, 80), "candidate": np.linspace(-0.01, 0.03, 80)}
    _run(tmp_path, "unrecorded-run")
    missing = _registered(tmp_path, scores, run_id="current-run", spec=_spec(periods_per_year=12))
    assert missing.uncertainty["trial_family_reason"] == "prior_run_trial_evidence_missing"
    assert missing.deflated_sharpe is missing.probability_of_backtest_overfitting is missing.false_discovery_rate is None
    assert missing.promotion_eligible is False
    other = tmp_path / "alignment"
    _registered(other, scores, run_id="prior", spec=_spec(), date_labels=list(range(80)))
    changed = _registered(other, scores, run_id="later", spec=_spec(), date_labels=list(range(1, 81)))
    assert changed.uncertainty["trial_family_reason"] == "trial_family_alignment_unverifiable"
    assert changed.false_discovery_rate is None
    bare = evaluate_trials(scores, spec=_spec(), prior_trial_scores=scores)
    assert bare.uncertainty["trial_family_status"] == "unavailable"
    deleted_root = tmp_path / "deleted-member"
    _registered(deleted_root, scores, spec=_spec())
    row = LocalTrainingRegistry(deleted_root).list_validation_trials()[0]
    with TransactionalStore(deleted_root) as store:
        store.delete("validation.trial", row["evidence_id"])
    deleted = _registered(deleted_root, scores, spec=_spec())
    assert deleted.uncertainty["trial_family_status"] == "unavailable"
    assert deleted.false_discovery_rate is None


def test_issue928_4_caller_flags_cannot_authorize_or_reset_holdout(tmp_path) -> None:
    scores = {"baseline": np.full(80, 0.01), "candidate": np.full(80, 0.02)}
    declaration = dict(spec=_spec(), frozen_candidate_id="candidate", predeclared_comparator_ids=("baseline",), holdout_id="sealed-928")
    denied = evaluate_trials(scores, **declaration, holdout_use_recorded=True, holdout_reused=False)
    assert denied.final_test_score is None
    assert "holdout_audit_missing" in denied.warnings
    first = _registered(tmp_path, scores, **declaration)
    assert first.holdout_status == "scored"
    audit = LocalTrainingRegistry(tmp_path).list_validation_holdout_uses()[0]
    assert audit["candidate_id"] == "candidate"
    assert audit["comparator_ids"] == ["baseline"]
    assert audit["evaluation_id"] == first.uncertainty["evaluation_id"]
    assert len(audit["candidate_fingerprint"]) == len(audit["holdout_fingerprint"]) == 64
    declaration["holdout_id"] = "renamed-sealed-928"
    reused = _registered(tmp_path, scores, **declaration, holdout_use_recorded=True, holdout_reused=False)
    assert reused.holdout_status == "development_reuse"
    assert reused.final_test_score is None
    assert all(trial.final_test_score is None for trial in reused.trials)
    assert max(reused.folds[-1].validation_indices) == 79
    assert reused.total_trial_count == 4
    assert len(LocalTrainingRegistry(tmp_path).list_validation_holdout_uses()) == 2


def test_issue928_8_single_trial_and_too_small_inference_guards(tmp_path) -> None:
    one = _registered(tmp_path, {"only": np.linspace(-0.01, 0.02, 80)}, spec=_spec(periods_per_year=12))
    assert one.deflated_sharpe is one.false_discovery_rate is one.probability_of_backtest_overfitting is None
    assert any("dsr_unavailable" in warning for warning in one.warnings)
    assert any("fdr_unavailable" in warning for warning in one.warnings)
    tiny = _registered(tmp_path / "tiny", {"baseline": np.arange(8.), "candidate": np.arange(8.) + 1},
                       spec=_spec(n_splits=1, test_size=1, final_test_size=1, periods_per_year=12))
    assert tiny.deflated_sharpe is tiny.false_discovery_rate is tiny.probability_of_backtest_overfitting is None
    assert tiny.uncertainty["status"] == "unavailable"
    assert tiny.uncertainty["reason"] == "at_least_two_finite_paired_dates_required"
    assert _false_discovery_rate([]) is None
    assert _false_discovery_rate([float("nan")]) is None
    assert _deflated_sharpe(np.array([1., 2.]), 2, 12, [0., 1.]) is None


def test_non_inference_split_keeps_the_legacy_horizon_minus_one_contract() -> None:
    spec = _spec(n_splits=1, test_size=20, final_test_size=10, horizon=5)
    legacy = build_walk_forward_splits(100, spec, strict_label_purge=False)[0]
    strict = build_walk_forward_splits(100, spec, strict_label_purge=True)[0]
    assert build_walk_forward_splits(100, spec)[0] == legacy  # strict purge is opt-in

    assert len(legacy.purged_indices) == spec.horizon - 1
    assert legacy.validation_indices[-1] == 100 - spec.final_test_size - 1
    assert len(strict.purged_indices) == spec.horizon
    assert strict.validation_indices[-1] == 100 - spec.final_test_size - spec.horizon - 1


def test_issue928_pass2_public_development_evaluation_accepts_41_observations(tmp_path) -> None:
    spec = _spec(n_splits=3, test_size=10, final_test_size=10, horizon=1, embargo=0)
    scores = {"baseline": np.arange(41.) / 100, "candidate": np.arange(41.) / 100 + 0.01}
    report = evaluate_trials(scores, spec=spec)
    assert report.folds == build_walk_forward_splits(41, spec)
    assert report.folds[0].train_indices == (0,)
    assert report.folds[-1].validation_indices[-1] == 30
    assert report.deflated_sharpe is report.probability_of_backtest_overfitting is report.false_discovery_rate is None
    assert report.final_test_score is None and report.promotion_eligible is False
    with pytest.raises(ValueError, match="at least 44 observations"):
        _registered(tmp_path, scores, spec=spec)


def test_issue928_pass2_holdout_dates_survive_cross_experiment_dataset_revisions(tmp_path) -> None:
    registry = _run(tmp_path, "first")
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(80)]
    scores = {"baseline": np.full(80, 0.01), "candidate": np.full(80, 0.02)}
    options = dict(spec=_spec(), frozen_candidate_id="candidate", predeclared_comparator_ids=("baseline",))
    first = registry.evaluate_validation_trials("first", scores, date_labels=dates, holdout_id="original", **options)
    assert first.holdout_status == "scored"
    revised = {key: value.copy() for key, value in scores.items()}
    for values in revised.values():
        values[:70] += 0.001
    experiment = registry.create_experiment("revised-experiment")
    registry.create_run(str(experiment["experiment_id"]), run_id="revised", dataset_hash=hashlib.sha256(b"revised-development").hexdigest(),
                        feature_hash="b" * 64, code_hash="c" * 64, environment_hash="d" * 64)
    # Canonical dates must survive different serialization and input row order.
    second = LocalTrainingRegistry(tmp_path).evaluate_validation_trials(
        "revised", {key: values[::-1] for key, values in revised.items()},
        date_labels=[day.isoformat() + "T12:00:00" for day in dates[::-1]], holdout_id="renamed", **options,
    )
    assert second.holdout_status == "development_reuse"
    assert second.final_test_score is None and all(row.final_test_score is None for row in second.trials)
    assert max(second.folds[-1].validation_indices) == 79
    audits = registry.list_validation_holdout_uses()
    assert len(audits) == 2 and audits[1]["reused"] is True
    assert audits[0]["data_hash"] != audits[1]["data_hash"]
    assert audits[0]["holdout_fingerprint"] == audits[1]["holdout_fingerprint"]
    for labels in (None, list(range(80))):
        unavailable = _registered(tmp_path / str(labels is None), scores, date_labels=labels, holdout_id="unverifiable", **options)
        assert unavailable.holdout_status == "unavailable"
        assert unavailable.final_test_score is None
        assert "holdout_window_identity_unverifiable" in unavailable.warnings
    # Unknown historic declarations cannot certify a new dataset/window either.
    historic_root = tmp_path / "legacy-audit"
    historic = _run(historic_root, "declaration")
    historic.record_validation_holdout_use("legacy", run_id="declaration", candidate_id="candidate", comparator_ids=("baseline",))
    other = historic.create_experiment("another-experiment")
    historic.create_run(str(other["experiment_id"]), run_id="new-data", dataset_hash="e" * 64,
                        feature_hash="b" * 64, code_hash="c" * 64, environment_hash="d" * 64)
    denied = historic.evaluate_validation_trials("new-data", scores, date_labels=dates, holdout_id="new-window", **options)
    assert denied.holdout_status == "unavailable" and denied.final_test_score is None
    assert "holdout_window_history_unverifiable" in denied.warnings
    assert len(historic.list_validation_holdout_uses()) == 1


def test_issue928_pass2_handoff_records_outcomes_base_evidence_and_checked_callers() -> None:
    handoff = (Path(__file__).resolve().parents[1] / "docs/development/st1-issue928-correction-handoff.md").read_text(encoding="utf-8")
    current = handoff.split("## Correction pass 2 — current handoff", 1)[1]
    for finding in ("BLOCKING 1", "BLOCKING 2", "BLOCKING 3", "BLOCKING 4"):
        row = next(line for line in current.splitlines() if line.startswith(f"| {finding} |"))
        assert any(outcome in row for outcome in ("FIXED", "REJECTED", "DEFERRED"))
    for evidence in ("27 passed, 2 failed", "20 passed", "104 passed", "DEFAULTS", "OPEN"):
        assert evidence in current
    for caller in (
        "validation.protocol._evaluate_trials", "features.training_centre.LocalTrainingRegistry.evaluate_validation_trials",
        "validation.optimisation.run_walk_forward_tuning", "application.validation.evaluate_registered_trials",
        "application.validation.build_validation_preview", "validation.__init__",
        "features.forecast_lab.build_forecast_lab_report", "analysis.decision.rank_validation",
        "tests/test_validation_protocol.py", "tests/test_bug_issue928.py", "tests/test_training_centre.py",
        "tests/test_bugfix_t-pit.py", "tests/test_forecast_lab.py", "tests/test_forecast_calibration.py",
    ):
        assert caller in current


def test_optimiser_search_trials_count_in_the_validation_family(tmp_path) -> None:
    registry = _run(tmp_path, "searched-run")
    ledger = OptimisationLedger(tmp_path)
    statuses = ("completed", "pruned", "failed", "completed")
    for sequence, status in enumerate(statuses):
        ledger.record(TrialRecord(
            "searched-run", f"t{sequence}", sequence, {"z": sequence}, status, None if status == "failed" else 0.1,
            1.0, 1.0, None, sequence == 0,
        ))
    ledger.record(TrialRecord("unrelated-run", "t0", 0, {}, "completed", 0.1, 1.0, 1.0, None, False))
    rng = np.random.default_rng(3)
    report = registry.evaluate_validation_trials(
        "searched-run", {"baseline": np.zeros(80), "candidate": rng.normal(0.001, 0.01, 80)}, spec=_spec(),
    )

    assert report.total_trial_count == 2 + len(statuses)  # unattributable runs are not guessed into the family
    assert report.false_discovery_rate is None
    assert any(item.startswith("fdr_unavailable") for item in report.warnings)
    assert report.probability_of_backtest_overfitting is None
    reason = report.uncertainty["unavailable_reasons"]["probability_of_backtest_overfitting"]
    assert reason == f"trial_family_series_unavailable: {len(statuses)} ledger trial(s) lack aligned series"
    assert f"pbo_unavailable:{reason}" in report.warnings
    assert report.promotion_eligible is False
