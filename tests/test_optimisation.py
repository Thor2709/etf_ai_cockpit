from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.validation.optimisation import DevelopmentOnlyContext, OptimisationError, OptimisationLedger, OptimisationQuota, run_bounded_optimisation


def test_bounded_search_is_seeded_durable_and_resume_safe(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []

    def objective(parameters: dict[str, object], context: DevelopmentOnlyContext) -> float:
        assert context.final_test_available is False
        seen.append(parameters)
        return float(parameters["depth"]) - float(parameters["rate"])

    quota = OptimisationQuota(max_trials=5, max_seconds=10, seed=7)
    first = run_bounded_optimisation(
        tmp_path,
        "run-optimisation",
        {"depth": [1, 2, 3], "rate": [0.1, 0.2]},
        objective,
        quota=quota,
    )

    assert first.status == "completed"
    assert first.trial_count == 5
    assert first.baseline_score == pytest.approx(0.9)
    assert first.best_trial_id is not None
    assert first.selection_scope == "development_validation_only"
    assert first.promotion_eligible is False
    assert first.execution_allowed is False
    assert len(seen) == 5
    rows = OptimisationLedger(tmp_path).list("run-optimisation")
    assert len(rows) == 5
    assert {row["trial_id"] for row in rows} == {"baseline", "trial-0001", "trial-0002", "trial-0003", "trial-0004"}
    assert all(row["final_test_score"] is None for row in rows)

    resumed = run_bounded_optimisation(tmp_path, "run-optimisation", {"depth": [1, 2, 3], "rate": [0.1, 0.2]}, objective, quota=quota)
    assert resumed.trial_count == 5
    assert len(seen) == 5

    with pytest.raises(OptimisationError, match="different seed or parameter space"):
        run_bounded_optimisation(tmp_path, "run-optimisation", {"depth": [1, 2]}, objective, quota=quota)


def test_pruned_failed_cancelled_trials_are_retained(tmp_path: Path) -> None:
    calls = 0

    def objective(parameters: dict[str, object], _context: DevelopmentOnlyContext) -> float:
        value = int(parameters["value"])
        if value == 2:
            raise RuntimeError("known objective failure")
        return float(value)

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 8

    summary = run_bounded_optimisation(
        tmp_path,
        "run-outcomes",
        {"value": [0, 1, 2, 3, 4]},
        objective,
        quota=OptimisationQuota(max_trials=5, max_seconds=10),
        prune_below=1.0,
        cancel_check=cancel,
    )

    assert summary.pruned_count >= 1
    assert summary.failed_count >= 1
    assert summary.cancelled_count >= 1
    assert summary.stop_reason == "cancel_requested"


def test_resume_preserves_seeded_sequence_when_quota_expands(tmp_path: Path) -> None:
    space = {"depth": [1, 2, 3], "rate": [0.1, 0.2]}

    def objective(parameters: dict[str, object], context: DevelopmentOnlyContext) -> float:
        assert context.final_test_available is False
        return float(parameters["depth"]) - float(parameters["rate"])

    run_bounded_optimisation(tmp_path, "run-resume", space, objective, quota=OptimisationQuota(max_trials=3, seed=11))
    resumed = run_bounded_optimisation(tmp_path, "run-resume", space, objective, quota=OptimisationQuota(max_trials=5, seed=11))

    fresh_root = tmp_path / "fresh"
    fresh = run_bounded_optimisation(fresh_root, "run-fresh", space, objective, quota=OptimisationQuota(max_trials=5, seed=11))

    assert resumed.best_trial_id == fresh.best_trial_id
    assert resumed.best_score == fresh.best_score
    resumed_rows = OptimisationLedger(tmp_path).list("run-resume")
    fresh_rows = OptimisationLedger(fresh_root).list("run-fresh")
    assert [row["parameters"] for row in resumed_rows] == [row["parameters"] for row in fresh_rows]


def test_memory_quota_fails_closed(tmp_path: Path) -> None:
    def objective(_parameters: dict[str, object], _context: DevelopmentOnlyContext) -> float:
        allocation = bytearray(2 * 1024 * 1024)
        return float(len(allocation))

    summary = run_bounded_optimisation(
        tmp_path,
        "run-memory",
        {"value": [1]},
        objective,
        quota=OptimisationQuota(max_trials=1, max_seconds=10, max_memory_mb=1),
    )

    assert summary.failed_count == 1
    assert summary.best_trial_id is None
    assert summary.stop_reason == "quota_reached"


def test_time_quota_overrun_is_recorded_and_fails_closed(tmp_path: Path) -> None:
    def objective(_parameters: dict[str, object], _context: DevelopmentOnlyContext) -> float:
        import time

        time.sleep(0.02)
        return 1.0

    summary = run_bounded_optimisation(
        tmp_path,
        "run-time",
        {"value": [1]},
        objective,
        quota=OptimisationQuota(max_trials=1, max_seconds=0.001),
    )

    assert summary.stop_reason == "time_quota_exceeded"
    assert summary.failed_count == 1
    assert summary.elapsed_seconds > 0.001


def test_unsupported_parallel_quota_and_unsafe_parameter_values_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        OptimisationQuota(max_concurrency=2)

    with pytest.raises(ValueError, match="non-JSON"):
        run_bounded_optimisation(tmp_path, "run-unsafe", {"value": [object()]}, lambda _parameters, _context: 1.0)
