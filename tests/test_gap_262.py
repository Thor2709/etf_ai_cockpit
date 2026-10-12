from __future__ import annotations

from datetime import date
import hashlib
import json
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

    spy.identity = inner.identity  # type: ignore[attr-defined]
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

    regime_flip.identity = "synthetic:regime-flip"  # type: ignore[attr-defined]
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


def _eval_start(n: int = 500) -> int:
    return n - DEFAULTS.split.final_test_size - DEFAULTS.split.eval_size


def _load_cli(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / "run_tuning.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)  # type: ignore[union-attr]
    return cli


def test_resume_refuses_retained_trials_from_a_different_window_or_objective(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, evaluate = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    first = run_walk_forward_tuning(tmp_path / "store", "resume", registry, evaluate, dates, data_provenance="synthetic", defaults=DEFAULTS)
    again = run_walk_forward_tuning(tmp_path / "store", "resume", registry, evaluate, dates, data_provenance="synthetic", defaults=DEFAULTS)
    assert again.to_dict()["proposal_fingerprint"] == first.to_dict()["proposal_fingerprint"]  # identical identity resumes

    longer_dates, longer_eval = synthetic_tuning_fixture(registry, PLANTED, n_samples=560)  # same ID, longer history
    longer = run_walk_forward_tuning(tmp_path / "store", "resume", registry, longer_eval, longer_dates, data_provenance="synthetic", defaults=DEFAULTS)
    other_dates, other_eval = synthetic_tuning_fixture(registry, {**PLANTED, "ens.z": 0.3}, n_samples=500)  # different objective
    other = run_walk_forward_tuning(tmp_path / "store", "resume", registry, other_eval, other_dates, data_provenance="synthetic", defaults=DEFAULTS)
    penalised = run_walk_forward_tuning(
        tmp_path / "store",
        "resume",
        registry,
        evaluate,
        dates,
        data_provenance="synthetic",
        defaults=TuningDefaults(DEFAULTS.search, GuardDefaults(100, 40, 4, 0.75, 0.05, 0.0), DEFAULTS.split),
    )
    for refused in (longer, other, penalised):
        assert refused.decision == "unavailable" and refused.reasons == ("retained_evidence_identity_mismatch",)
        assert refused.candidate is None
    unverified = run_walk_forward_tuning(tmp_path / "store5", "m", registry, lambda p, i, c: 0.0, dates, data_provenance="market", defaults=DEFAULTS)
    assert unverified.decision == "keep_current" and unverified.search["trial_count"] == DEFAULTS.search.max_trials
    assert "evaluator_identity_unverified" in unverified.evidence["flags"]
    assert unverified.evidence["promotion_evidence_eligible"] is False  # fresh machinery runs cannot establish market evidence identity


def test_failed_baseline_cannot_support_a_proposal(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, inner = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    current = registry.current_values()
    held: list[bytearray] = []

    def heavy_baseline(parameters, indices, context):  # noqa: ANN001
        if all(abs(parameters[key] - value) < 1e-9 for key, value in current.items()):
            held.append(bytearray(4 * 1024 * 1024))  # breaches the 1 MB quota, only for the baseline
        return inner(parameters, indices, context)

    heavy_baseline.identity = inner.identity  # type: ignore[attr-defined]
    tight = TuningDefaults(SearchDefaults(60, 60.0, 1, 11, 30, None, 5), DEFAULTS.guards, DEFAULTS.split)
    proposal = run_walk_forward_tuning(tmp_path / "store", "badbase", registry, heavy_baseline, dates, data_provenance="synthetic", defaults=tight)

    rows = OptimisationLedger(tmp_path / "store").list("badbase")
    baseline = next(row for row in rows if row["trial_id"] == "baseline")
    assert baseline["status"] == "failed" and baseline["score"] is None
    assert proposal.decision == "unavailable" and proposal.reasons == ("baseline_trial_did_not_complete",)
    assert proposal.candidate is None and proposal.out_of_sample is None


def test_out_of_sample_evaluation_shares_the_run_budget(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, inner = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    ticks = {"now": 0.0, "oos_calls": 0}

    def slow_oos(parameters, indices, context):  # noqa: ANN001
        if min(indices) >= _eval_start():
            ticks["oos_calls"] += 1
            ticks["now"] += 30.0  # each out-of-sample call costs 30 fake seconds of a 60 s budget
        return inner(parameters, indices, context)

    slow_oos.identity = inner.identity  # type: ignore[attr-defined]
    proposal = run_walk_forward_tuning(
        tmp_path / "store", "budget", registry, slow_oos, dates, data_provenance="synthetic", defaults=DEFAULTS, clock=lambda: ticks["now"]
    )
    assert proposal.decision == "unavailable" and proposal.reasons == ("out_of_sample_interrupted",)
    assert ticks["oos_calls"] <= 2  # stopped at the shared deadline, not after all eight calls

    polls = {"n": 0}

    def cancel_late() -> bool:
        polls["n"] += 1
        return polls["n"] > 70  # lets the search finish, cancels inside out-of-sample judging

    cancelled = run_walk_forward_tuning(
        tmp_path / "store2", "cancel", registry, inner, dates, data_provenance="synthetic", defaults=DEFAULTS, cancel_check=cancel_late
    )
    assert cancelled.decision == "unavailable"  # cancellation is honoured, never turned into a proposal


def test_protected_output_directories_are_refused_before_any_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _load_cli("run_tuning_cli")
    root = Path(__file__).resolve().parents[1]
    forbidden = [
        root / ".owner-root" / "models",
        tmp_path / ".owner-root" / "x",
        tmp_path / "models" / "x",
        tmp_path / "configs" / "x",
        root / "configs" / "sub",
        "C:/Users/thor2/Desktop/Trading App/etf_ai_cockpit",
        "C:\\Users\\thor2\\Desktop\\Trading App\\out",
    ]
    for target in forbidden:
        assert cli.main(["--output-dir", str(target)]) == 2
        assert "tuning_status=refused" in capsys.readouterr().out
    assert not (tmp_path / "models").exists() and not (tmp_path / ".owner-root").exists() and not (tmp_path / "configs").exists()
    assert not (root / ".owner-root" / "models").exists() and not (root / "configs" / "sub").exists()


def test_invalid_registry_configuration_fails_closed_as_unavailable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _registry(tmp_path)
    config = tmp_path / "cfg"
    broken_bounds = REGISTRY.replace("lower: 0.3, upper: 0.7, step: 0.1, group: ens.xy}\n  - {key: ens.y", "lower: low, upper: 0.7, step: 0.1, group: ens.xy}\n  - {key: ens.y")
    cases = {
        "schema_version: invalid\n": "schema_version",
        REGISTRY + "defaults: {guards: {eval_blocks: 0}}\n": "eval_blocks",
        REGISTRY + "defaults: {guards: {change_penalty: -1}}\n": "change_penalty",
        REGISTRY + "defaults: {guards: {min_block_win_fraction: 0}}\n": "min_block_win_fraction",
        REGISTRY + "defaults: {search: [1]}\n": "mapping",
        REGISTRY + "defaults: {split: {horizon: abc}}\n": "horizon",
        broken_bounds: "numbers",
        REGISTRY + "  - just-a-string\n": "mapping",
    }
    for text, fragment in cases.items():
        (config / "bad.yaml").write_text(text, encoding="utf-8")
        with pytest.raises(TuningRegistryError, match=fragment):
            load_tuning_registry(config / "bad.yaml")
    cli = _load_cli("run_tuning_cli2")
    (config / "bad.yaml").write_text("schema_version: invalid\n", encoding="utf-8")
    assert cli.main(["--registry", str(config / "bad.yaml"), "--output-dir", str(tmp_path / "out")]) == 2
    assert "tuning_status=unavailable" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_out_of_sample_exception_text_never_reaches_exports(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, inner = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)

    def leaky(parameters, indices, context):  # noqa: ANN001
        if min(indices) >= _eval_start():
            raise RuntimeError("request failed: https://host/?api_key=SECRET123")
        return inner(parameters, indices, context)

    leaky.identity = inner.identity  # type: ignore[attr-defined]
    proposal = run_walk_forward_tuning(tmp_path / "store", "leak", registry, leaky, dates, data_provenance="synthetic", defaults=DEFAULTS)

    assert proposal.decision == "unavailable" and proposal.reasons == ("out_of_sample_evaluation_failed: RuntimeError",)
    exported = json.dumps(proposal.to_dict()) + render_tuning_report(proposal)
    assert "SECRET123" not in exported and "api_key" not in exported


def test_unverifiable_objective_identity_never_reuses_retained_evidence_even_for_synthetic(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, _inner = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)

    def make_objective(target: float):
        def objective(parameters, indices, context):  # noqa: ANN001  # same module + qualname for every target
            return -abs(parameters["ens.z"] - target)

        return objective

    first, second = make_objective(0.8), make_objective(0.3)
    assert first.__qualname__ == second.__qualname__ and not hasattr(first, "identity")
    fresh_ids = []
    for objective in (first, second):
        proposal = run_walk_forward_tuning(tmp_path / "store", "anon", registry, objective, dates, data_provenance="synthetic", defaults=DEFAULTS)
        assert proposal.decision == "propose_change" and proposal.candidate is not None
        assert proposal.search["resume_allowed"] is False
        fresh_ids.append(proposal.search["run_id"])
        assert len(OptimisationLedger(tmp_path / "store").list(proposal.search["run_id"])) == DEFAULTS.search.max_trials
    assert len(set(fresh_ids)) == 2
    assert OptimisationLedger(tmp_path / "store").list("anon") == ()  # original namespace is untouched
    named = run_walk_forward_tuning(tmp_path / "store", "anon", registry, first, dates, data_provenance="synthetic", defaults=DEFAULTS, evaluator_identity="synthetic:z=0.8")
    assert named.decision == "propose_change" and named.search["resume_allowed"] is True


def test_retained_evidence_is_bound_to_every_effective_search_setting(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, evaluate = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    first = run_walk_forward_tuning(tmp_path / "store", "bound", registry, evaluate, dates, data_provenance="synthetic", defaults=DEFAULTS)
    assert first.decision == "propose_change"
    search = DEFAULTS.search
    variants = {
        "max_memory_mb": SearchDefaults(search.max_trials, search.max_seconds, 1, search.seed, search.refine_after, search.patience, search.prune_warmup_trials),
        "patience": SearchDefaults(search.max_trials, search.max_seconds, search.max_memory_mb, search.seed, search.refine_after, 40, search.prune_warmup_trials),
        "prune_warmup_trials": SearchDefaults(search.max_trials, search.max_seconds, search.max_memory_mb, search.seed, search.refine_after, search.patience, 9),
    }
    for name, changed in variants.items():
        resumed = run_walk_forward_tuning(
            tmp_path / "store", "bound", registry, evaluate, dates, data_provenance="synthetic", defaults=TuningDefaults(changed, DEFAULTS.guards, DEFAULTS.split)
        )
        assert resumed.decision == "unavailable" and resumed.reasons == ("retained_evidence_identity_mismatch",), name
        assert resumed.candidate is None


def test_invalid_knob_metadata_is_rejected_as_unavailable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _registry(tmp_path)
    config = tmp_path / "cfg"
    cases = {
        REGISTRY.replace("group: ens.xy}", "group: [ens]}", 1): "group",
        REGISTRY.replace("model: toto}", "model: {a: 1}}"): "model",
        REGISTRY.replace("key: ens.z,", "key: 'bad key!',"): "knob key",
        REGISTRY.replace("key: ens.z,", "key: [ens.z],"): "knob key",
        REGISTRY.replace("key: ens.z,", "key: 7,"): "knob key",
    }
    cli = _load_cli("run_tuning_cli3")
    for text, fragment in cases.items():
        (config / "bad.yaml").write_text(text, encoding="utf-8")
        with pytest.raises(TuningRegistryError, match=fragment):
            load_tuning_registry(config / "bad.yaml")
        assert cli.main(["--registry", str(config / "bad.yaml"), "--output-dir", str(tmp_path / "out")]) == 2
        assert "tuning_status=unavailable" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_cancellation_during_the_final_out_of_sample_call_never_proposes(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    dates, inner = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    baseline = run_walk_forward_tuning(tmp_path / "store0", "plain", registry, inner, dates, data_provenance="synthetic", defaults=DEFAULTS)
    assert baseline.decision == "propose_change"  # the same evaluator wins when nothing cancels

    state = {"calls": 0, "cancelled": False}

    def cancels_on_last_call(parameters, indices, context):  # noqa: ANN001
        score = inner(parameters, indices, context)
        if min(indices) >= _eval_start():
            state["calls"] += 1
            if state["calls"] == 8:  # last candidate block: the evaluator never reports after this point
                state["cancelled"] = True
        return score

    cancels_on_last_call.identity = inner.identity  # type: ignore[attr-defined]
    proposal = run_walk_forward_tuning(
        tmp_path / "store1", "late", registry, cancels_on_last_call, dates, data_provenance="synthetic", defaults=DEFAULTS, cancel_check=lambda: state["cancelled"]
    )
    assert state["calls"] == 8
    assert proposal.decision == "unavailable" and proposal.reasons == ("out_of_sample_interrupted",)
    assert proposal.candidate is None


@pytest.mark.parametrize("heavy_phase,expected_calls", [("current", 1), ("candidate", 5)])
@pytest.mark.parametrize("report_after_allocation", [False, True])
def test_every_out_of_sample_call_enforces_the_memory_quota(tmp_path: Path, heavy_phase: str, expected_calls: int, report_after_allocation: bool) -> None:
    registry, _ = _registry(tmp_path)
    dates, inner = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    current = registry.current_values()
    calls = []

    def heavy_oos(parameters, indices, context):  # noqa: ANN001
        score = inner(parameters, indices, context)
        if min(indices) >= _eval_start():
            phase = "current" if parameters == current else "candidate"
            calls.append(phase)
            if phase == heavy_phase:
                allocation = bytearray(4 * 1024 * 1024)
                if report_after_allocation:
                    context.report(99, score)
                assert len(allocation) == 4 * 1024 * 1024  # freed before returning; its peak still counts
        return score

    heavy_oos.identity = inner.identity  # type: ignore[attr-defined]
    tight = TuningDefaults(SearchDefaults(60, 60.0, 1, 11, 30, None, 5), DEFAULTS.guards, DEFAULTS.split)
    proposal = run_walk_forward_tuning(tmp_path / "store", "heavy-oos", registry, heavy_oos, dates, data_provenance="synthetic", defaults=tight)

    rows = OptimisationLedger(tmp_path / "store").list("heavy-oos")
    assert rows[0]["status"] == "completed" and max(row["peak_memory_mb"] for row in rows) < 1
    assert len(calls) == expected_calls and calls[-1] == heavy_phase
    assert proposal.decision == "unavailable" and proposal.reasons == ("out_of_sample_memory_quota_exceeded",)
    assert proposal.search["peak_memory_mb"] > 1
    assert proposal.candidate is None and proposal.out_of_sample is None


@pytest.mark.parametrize("provenance", ["synthetic", "market", "private"])
def test_unknown_identity_executes_fresh_tuning_and_preserves_prior_scores(tmp_path: Path, provenance: str) -> None:
    registry, _ = _registry(tmp_path)
    dates, known = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    root = tmp_path / "store"
    original = run_walk_forward_tuning(root, "same-run", registry, known, dates, data_provenance=provenance, defaults=DEFAULTS)
    ledger = OptimisationLedger(root)
    prior_rows, prior_summaries = ledger.list("same-run"), ledger.list_summaries()
    assert original.search["resume_allowed"] is True
    fresh_ids = []

    def anonymous(target: float):
        calls = []

        def evaluate(parameters, indices, context):  # noqa: ANN001
            calls.append(tuple(indices))
            return -abs(parameters["ens.z"] - target)

        return evaluate, calls

    for target in (0.8, 0.3):
        evaluate, calls = anonymous(target)
        proposal = run_walk_forward_tuning(root, "same-run", registry, evaluate, dates, data_provenance=provenance, defaults=DEFAULTS)
        assert proposal.decision == "propose_change" and proposal.candidate is not None
        assert sum(max(indices) < _eval_start() for indices in calls) == DEFAULTS.search.max_trials
        assert proposal.in_sample["baseline_score"] == pytest.approx(-abs(0.5 - target))
        assert proposal.candidate["ens.z"] == pytest.approx(target, abs=0.1)
        assert proposal.search["resume_allowed"] is False
        assert proposal.evidence["promotion_evidence_eligible"] is False
        fresh_id = proposal.search["run_id"]
        fresh_ids.append(fresh_id)
        assert ledger.list(fresh_id)[0]["score"] == pytest.approx(-abs(0.5 - target))
        assert ledger.list("same-run") == prior_rows
        assert next(item for item in ledger.list_summaries() if item["run_id"] == "same-run") == prior_summaries[0]
    assert len(set(fresh_ids)) == 2 and "same-run" not in fresh_ids


@pytest.mark.parametrize("early_reason", ["no_in_sample_improvement_over_current", "candidate_equals_current"])
@pytest.mark.parametrize("cancel_poll", [1, 3])
def test_resumed_early_decisions_poll_cancellation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, early_reason: str, cancel_poll: int) -> None:
    registry, _ = _registry(tmp_path)
    dates, _ = synthetic_tuning_fixture(registry, PLANTED, n_samples=500)
    calls = []
    if early_reason == "candidate_equals_current":
        # Repeated current settings can receive different scores from a noisy evaluator.
        monkeypatch.setattr(type(registry), "search_space", lambda self: {key: (value,) for key, value in self.current_values().items()})

    def evaluate(parameters, indices, context):  # noqa: ANN001
        calls.append(tuple(indices))
        return float(len(calls)) if early_reason == "candidate_equals_current" else 1.0

    evaluate.identity = "synthetic:early-decisions"  # type: ignore[attr-defined]
    defaults = TuningDefaults(SearchDefaults(2, 60.0, 256, 11, None, None, 5), DEFAULTS.guards, DEFAULTS.split)
    root = tmp_path / "store"
    first = run_walk_forward_tuning(root, "early", registry, evaluate, dates, data_provenance="synthetic", defaults=defaults)
    assert first.decision == "keep_current" and first.reasons == (early_reason,)
    prior_rows = OptimisationLedger(root).list("early")
    polls = 0

    def cancel() -> bool:
        nonlocal polls
        polls += 1
        return polls >= cancel_poll  # either already cancelled, or cancelled at the decision gate

    resumed = run_walk_forward_tuning(root, "early", registry, evaluate, dates, data_provenance="synthetic", defaults=defaults, cancel_check=cancel)
    assert len(calls) == 2  # retained scores were read without a new evaluator call
    assert resumed.decision == "unavailable"
    assert resumed.reasons == (("search_cancelled",) if cancel_poll == 1 else ("decision_interrupted",))
    assert resumed.candidate is None and resumed.out_of_sample is None
    assert OptimisationLedger(root).list("early") == prior_rows
