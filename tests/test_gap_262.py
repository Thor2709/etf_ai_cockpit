from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path

import pytest

from etf_cockpit.validation.optimisation import (
    DevelopmentOnlyContext,
    OptimisationLedger,
    OptimisationQuota,
    PruningRule,
    render_tuning_report,
    run_bounded_optimisation,
    run_walk_forward_tuning,
    synthetic_tuning_fixture,
)
from etf_cockpit.validation.tuning_registry import TuningDefaults, GuardDefaults, SearchDefaults, SplitDefaults, TuningRegistryError, load_tuning_registry

SETTINGS = """\
ensemble:
  weights:
    x: 0.5
    y: 0.5
    z: 0.5
"""
REGISTRY = """\
schema_version: 1
version: tuning-test
parameters:
  - {key: ens.x, file: settings.yaml, path: [ensemble, weights, x], lower: 0.3, upper: 0.7, step: 0.1, group: ens.xy}
  - {key: ens.y, file: settings.yaml, path: [ensemble, weights, y], lower: 0.3, upper: 0.7, step: 0.1, group: ens.xy}
  - {key: ens.z, file: settings.yaml, path: [ensemble, weights, z], lower: 0.2, upper: 0.9, step: 0.1, model: toto}
"""
PLANTED = {"ens.x": 0.7, "ens.y": 0.3, "ens.z": 0.8}
DEFAULTS = TuningDefaults(
    SearchDefaults(max_trials=60, max_seconds=60.0, seed=11, refine_after=30, patience=None, prune_warmup_trials=5),
    GuardDefaults(min_tune_samples=100, min_eval_samples=40, eval_blocks=4, min_block_win_fraction=0.75, change_penalty=0.01, min_improvement=0.0),
    SplitDefaults(eval_size=120, horizon=5, embargo=0, final_test_size=40),
)


def _registry(tmp_path: Path):
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    (config / "tuning.yaml").write_text(REGISTRY, encoding="utf-8")
    return load_tuning_registry(config / "tuning.yaml"), config


def test_search_recovers_planted_best_parameter_and_proposal_is_flagged_synthetic(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, evaluate = synthetic_tuning_fixture(registry, PLANTED, n_samples=500, noise=0.02)

    proposal = run_walk_forward_tuning(tmp_path / "store", "plant", registry, evaluate, dates, data_provenance="synthetic", defaults=DEFAULTS)
    body = proposal.to_dict()

    assert proposal.decision == "propose_change", proposal.reasons
    assert proposal.candidate is not None
    for key, target in PLANTED.items():
        assert proposal.candidate[key] == pytest.approx(target, abs=0.1)
    assert proposal.candidate["ens.x"] + proposal.candidate["ens.y"] == pytest.approx(1.0)  # group total preserved
    assert body["applied"] is False and body["settings_modified"] is False and body["execution_allowed"] is False
    assert body["evidence"]["promotion_evidence_eligible"] is False  # synthetic is machinery-only
    assert "synthetic_data_not_promotion_evidence" in body["evidence"]["flags"]
    assert "propose_change" in render_tuning_report(proposal)
    # market data with an unknown/pre-cutoff model window is flagged, never promotion evidence
    flagged = run_walk_forward_tuning(tmp_path / "store2", "plant", registry, evaluate, dates, data_provenance="market", defaults=DEFAULTS)
    assert flagged.evidence["promotion_evidence_eligible"] is False
    assert "toto:pretraining_cutoff_unknown" in flagged.evidence["flags"]
    clean = run_walk_forward_tuning(
        tmp_path / "store3", "plant", registry, evaluate, dates, data_provenance="market", model_cutoffs={"toto": date(2019, 1, 1)}, defaults=DEFAULTS
    )
    assert clean.evidence["promotion_evidence_eligible"] is True
    early = run_walk_forward_tuning(
        tmp_path / "store4", "plant", registry, evaluate, dates, data_provenance="market", model_cutoffs={"toto": date(2021, 1, 1)}, defaults=DEFAULTS
    )
    assert "toto:pre_cutoff_window" in early.evidence["flags"]


def test_walk_forward_never_shows_evaluation_or_final_data_to_the_search(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, inner = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    calls: list[tuple[str, tuple[int, ...]]] = []
    phase = {"name": "search"}

    def spy(parameters, indices, context):  # noqa: ANN001
        calls.append((phase["name"], tuple(indices)))
        return inner(parameters, indices, context)

    proposal = run_walk_forward_tuning(tmp_path / "store", "split", registry, spy, dates, data_provenance="synthetic", defaults=DEFAULTS)
    windows = proposal.windows
    n = 500
    eval_start = n - DEFAULTS.split.final_test_size - DEFAULTS.split.eval_size
    search_indices = {i for _, idx in calls[: DEFAULTS.search.max_trials] for i in idx}
    tuning_calls = [idx for _, idx in calls if idx and max(idx) < eval_start - DEFAULTS.split.horizon + 1]
    assert tuning_calls, "search evaluations must stay in the tuning window"
    assert windows["tune"]["end"] < windows["evaluation"]["start"]
    assert windows["purged_gap"] == DEFAULTS.split.horizon - 1
    assert max(search_indices) < eval_start - DEFAULTS.split.horizon + 1
    seen_all = {i for _, idx in calls for i in idx}
    assert max(seen_all) < n - DEFAULTS.split.final_test_size  # reserved tail never evaluated at all
    oos_calls = [idx for _, idx in calls if min(idx) >= eval_start]
    assert oos_calls and all(min(idx) >= eval_start for idx in oos_calls)  # evaluation blocks only after tuning


def test_candidate_that_does_not_beat_current_out_of_sample_keeps_current(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, _ = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    best_at = {"ens.z": 0.9}

    def regime_flip(parameters, indices, context):  # noqa: ANN001
        # Tuning window rewards z=0.9; the later evaluation window rewards the current z=0.5.
        target = 0.9 if max(indices) < 340 else 0.5
        context.report(0, -abs(parameters["ens.z"] - target))
        return -abs(float(parameters["ens.z"]) - target)

    proposal = run_walk_forward_tuning(tmp_path / "store", "flip", registry, regime_flip, dates, data_provenance="synthetic", defaults=DEFAULTS)

    assert best_at["ens.z"] > 0.5
    assert proposal.decision == "keep_current"
    assert proposal.reasons == ("did_not_beat_current_out_of_sample",)
    assert proposal.out_of_sample is not None and proposal.out_of_sample["win_fraction"] < DEFAULTS.guards.min_block_win_fraction
    assert proposal.to_dict()["applied"] is False
    short = run_walk_forward_tuning(tmp_path / "store2", "short", registry, regime_flip, dates[:120], defaults=DEFAULTS)
    assert short.decision == "unavailable" and short.reasons[0].startswith("insufficient_samples")


def test_trial_time_and_pruning_budgets_stop_deterministically(tmp_path: Path) -> None:
    space = {"a": [0, 1, 2, 3], "b": [0, 1, 2, 3]}
    ticks = {"now": 0.0}

    def clock() -> float:
        return ticks["now"]

    def objective(parameters, context):  # noqa: ANN001
        ticks["now"] += 1.0  # each trial costs one fake second
        value = float(parameters["a"] + parameters["b"])
        context.report(0, value)
        return value

    runs = []
    for name in ("one", "two"):
        runs.append(
            run_bounded_optimisation(
                tmp_path / name, "budget", space, objective, quota=OptimisationQuota(max_trials=50, max_seconds=4.5, seed=3), clock=clock
            )
        )
        ticks["now"] = 0.0
    assert [r.stop_reason for r in runs] == ["time_quota_exceeded"] * 2
    assert runs[0].trial_count == runs[1].trial_count == 5
    assert runs[0].best_score == runs[1].best_score

    # median pruning interrupts trials that trail completed peers at the same step; same seed -> same outcome
    pruned = [
        run_bounded_optimisation(
            tmp_path / f"prune{i}", "prune", space, objective, quota=OptimisationQuota(max_trials=30, max_seconds=1e6, seed=5), pruning=PruningRule(warmup_trials=3)
        )
        for i in range(2)
    ]
    assert pruned[0].pruned_count > 0 and pruned[0].pruned_count == pruned[1].pruned_count
    assert pruned[0].trial_count == 30 and pruned[0].stop_reason == "quota_reached"
    rows = OptimisationLedger(tmp_path / "prune0").list("prune")
    assert all(row["score"] is None for row in rows if row["status"] == "pruned" and row["error"].startswith("pruned at step"))

    # patience stops once nothing improves
    flat = run_bounded_optimisation(tmp_path / "flat", "flat", space, lambda _p, _c: 1.0, quota=OptimisationQuota(max_trials=40, seed=1), patience=4)
    assert flat.stop_reason == "no_improvement" and flat.trial_count == 5


def test_settings_files_are_unchanged_and_bad_registry_fails_closed(tmp_path: Path) -> None:
    registry, config = _registry(tmp_path)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in config.iterdir()}
    dates, evaluate = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)

    run_walk_forward_tuning(tmp_path / "store", "safe", registry, evaluate, dates, data_provenance="synthetic", defaults=DEFAULTS)

    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in config.iterdir()}
    assert after == before
    assert registry.current_values() == {"ens.x": 0.5, "ens.y": 0.5, "ens.z": 0.5}
    # a source value outside its bounds or a missing path is unavailable, never guessed
    (config / "settings.yaml").write_text(SETTINGS.replace("z: 0.5", "z: 0.95"), encoding="utf-8")
    with pytest.raises(TuningRegistryError, match="outside"):
        load_tuning_registry(config / "tuning.yaml")
    (config / "settings.yaml").write_text("ensemble: {weights: {x: 0.5}}\n", encoding="utf-8")
    with pytest.raises(TuningRegistryError, match="not found"):
        load_tuning_registry(config / "tuning.yaml")


def test_shipped_registry_reads_current_values_from_real_configs() -> None:
    configs = Path(__file__).resolve().parents[1] / "configs"
    registry = load_tuning_registry(configs / "tuning_v1.yaml")  # against the real settings, read-only

    assert len(registry.parameters) == 16
    current = registry.current_values()
    assert current["ensemble.toto"] == 0.15 and current["score.etf.attractiveness.momentum"] == 0.28
    assert registry.materialise(current) == current
    assert registry.models_in_scope() == ("timesfm", "toto")
    assert all(item.group for item in registry.parameters)
    space = registry.search_space()
    assert all(values[0] == registry.current_values()[key] for key, values in space.items())  # baseline = current
    assert DevelopmentOnlyContext("x").final_test_available is False
