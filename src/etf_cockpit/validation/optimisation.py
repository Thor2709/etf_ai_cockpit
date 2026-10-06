"""Bounded, local-only hyperparameter search evidence.

This module is an optimisation adapter, not a model trainer.  A developer
supplies a local objective that returns a development/validation score; final
test metrics are intentionally not accepted.  Every attempted trial is
durably recorded before a summary is returned, and no result grants model or
execution authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import random
import re
import time
import tracemalloc
from pathlib import Path
from typing import Literal

from etf_cockpit.data.local_storage import TransactionalStore


OPTIMISATION_SCHEMA_VERSION = "optimisation.v1"
_ENTITY_TRIAL = "optimisation.trial"
_ENTITY_SUMMARY = "optimisation.summary"
_SECRET_KEY = re.compile(r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd|authorization|bearer|secret|token)", re.I)
TrialStatus = Literal["completed", "pruned", "failed", "cancelled"]


@dataclass(frozen=True)
class DevelopmentOnlyContext:
    """The only evaluation context exposed to an optimisation objective."""

    run_id: str
    split: str = "nested_development_validation"
    final_test_available: bool = False

    def __post_init__(self) -> None:
        if self.split != "nested_development_validation" or self.final_test_available:
            raise ValueError("optimisation objectives require nested development validation only")


class OptimisationError(RuntimeError):
    """Raised when a search request violates the local optimisation contract."""


@dataclass(frozen=True)
class OptimisationQuota:
    max_trials: int = 20
    max_seconds: float = 30.0
    max_memory_mb: int = 256
    seed: int = 42
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        if int(self.max_trials) <= 0:
            raise ValueError("max_trials must be positive")
        if float(self.max_seconds) <= 0:
            raise ValueError("max_seconds must be positive")
        if int(self.max_memory_mb) <= 0:
            raise ValueError("max_memory_mb must be positive")
        if int(self.max_concurrency) != 1:
            raise ValueError("only serial max_concurrency=1 is supported in the local bounded adapter")


@dataclass(frozen=True)
class TrialRecord:
    run_id: str
    trial_id: str
    sequence: int
    parameters: Mapping[str, object]
    status: TrialStatus
    score: float | None
    duration_ms: float
    peak_memory_mb: float
    error: str | None
    is_baseline: bool
    selection_scope: str = "development_validation_only"
    final_test_score: None = None
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if self.final_test_score is not None or self.execution_allowed:
            raise ValueError("optimisation evidence cannot contain final-test selection or execution authority")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": OPTIMISATION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "trial_id": self.trial_id,
            "sequence": self.sequence,
            "parameters": dict(self.parameters),
            "status": self.status,
            "score": self.score,
            "duration_ms": self.duration_ms,
            "peak_memory_mb": self.peak_memory_mb,
            "error": self.error,
            "is_baseline": self.is_baseline,
            "selection_scope": self.selection_scope,
            "final_test_score": None,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class OptimisationSummary:
    run_id: str
    status: str
    trial_count: int
    completed_count: int
    pruned_count: int
    failed_count: int
    cancelled_count: int
    best_trial_id: str | None
    best_score: float | None
    baseline_score: float | None
    effective_independent_trial_count: float
    parameter_importance: Mapping[str, float]
    peak_memory_mb: float
    elapsed_seconds: float
    stop_reason: str
    search_fingerprint: str = ""
    seed: int = 42
    selection_scope: str = "development_validation_only"
    promotion_eligible: bool = False
    execution_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": OPTIMISATION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "trial_count": self.trial_count,
            "completed_count": self.completed_count,
            "pruned_count": self.pruned_count,
            "failed_count": self.failed_count,
            "cancelled_count": self.cancelled_count,
            "best_trial_id": self.best_trial_id,
            "best_score": self.best_score,
            "baseline_score": self.baseline_score,
            "effective_independent_trial_count": self.effective_independent_trial_count,
            "parameter_importance": dict(self.parameter_importance),
            "peak_memory_mb": self.peak_memory_mb,
            "elapsed_seconds": self.elapsed_seconds,
            "stop_reason": self.stop_reason,
            "search_fingerprint": self.search_fingerprint,
            "seed": self.seed,
            "selection_scope": self.selection_scope,
            "promotion_eligible": False,
            "execution_allowed": False,
        }


class OptimisationLedger:
    """Durable append-by-identity trial records in the local store."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def record(self, trial: TrialRecord) -> dict[str, object]:
        payload = trial.to_dict()
        with TransactionalStore(self.root) as store:
            existing = store.get(_ENTITY_TRIAL, f"{trial.run_id}:{trial.trial_id}")
            if existing is not None:
                if existing.payload == payload:
                    return existing.payload
                raise OptimisationError(f"trial already exists with different evidence: {trial.trial_id}")
            return store.put(_ENTITY_TRIAL, f"{trial.run_id}:{trial.trial_id}", payload).payload

    def list(self, run_id: str) -> tuple[dict[str, object], ...]:
        with TransactionalStore(self.root) as store:
            records = store.list(_ENTITY_TRIAL)
        return tuple(sorted((item.payload for item in records if item.payload.get("run_id") == run_id), key=lambda item: int(item.get("sequence", 0))))

    def list_all(self) -> tuple[dict[str, object], ...]:
        with TransactionalStore(self.root) as store:
            records = store.list(_ENTITY_TRIAL)
        return tuple(sorted((item.payload for item in records), key=lambda item: (str(item.get("run_id", "")), int(item.get("sequence", 0)))))

    def record_summary(self, summary: OptimisationSummary) -> dict[str, object]:
        payload = summary.to_dict()
        payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with TransactionalStore(self.root) as store:
            return store.put(_ENTITY_SUMMARY, summary.run_id, payload).payload

    def list_summaries(self) -> tuple[dict[str, object], ...]:
        with TransactionalStore(self.root) as store:
            records = store.list(_ENTITY_SUMMARY)
        return tuple(sorted((item.payload for item in records), key=lambda item: str(item.get("run_id", ""))))


def run_bounded_optimisation(
    root: Path,
    run_id: str,
    parameter_space: Mapping[str, Sequence[object]],
    objective: Callable[[Mapping[str, object], DevelopmentOnlyContext], float],
    *,
    quota: OptimisationQuota | None = None,
    prune_below: float | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> OptimisationSummary:
    """Run or resume a deterministic, quota-bounded local search.

    The objective is called only with generated local parameter values and
    must return a finite development/validation score.  It is never serialised
    or imported from user data.  Reusing ``run_id`` resumes from durable trial
    records without duplicating evidence.
    """

    definition = quota or OptimisationQuota()
    run_id = _identifier(run_id, "run_id")
    values = _validate_parameter_space(parameter_space)
    if not callable(objective):
        raise TypeError("objective must be a local callable")
    ledger = OptimisationLedger(root)
    context = DevelopmentOnlyContext(run_id)
    search_fingerprint = _search_fingerprint(values, int(definition.seed))
    prior_summary = next((item for item in ledger.list_summaries() if item.get("run_id") == run_id), None)
    if prior_summary is not None and prior_summary.get("search_fingerprint") != search_fingerprint:
        raise OptimisationError("cannot resume optimisation with a different seed or parameter space")
    existing = {str(item["trial_id"]): item for item in ledger.list(run_id)}
    started = time.monotonic()
    peak_memory = max((float(item.get("peak_memory_mb", 0.0)) for item in existing.values()), default=0.0)
    stop_reason = "quota_reached"
    rng = random.Random(int(definition.seed))
    for sequence in range(int(definition.max_trials)):
        trial_id = "baseline" if sequence == 0 else f"trial-{sequence:04d}"
        parameters = _parameters_for_sequence(values, rng, sequence)
        if trial_id in existing:
            continue
        if cancel_check is not None and cancel_check():
            stop_reason = "cancel_requested"
            break
        if time.monotonic() - started >= definition.max_seconds:
            stop_reason = "time_quota_exceeded"
            break
        trial = _evaluate_trial(
            ledger,
            run_id,
            trial_id,
            sequence,
            parameters,
            objective,
            context,
            definition,
            prune_below,
            cancel_check,
        )
        existing[trial_id] = trial
        peak_memory = max(peak_memory, float(trial.get("peak_memory_mb", 0.0)))
        if trial["status"] == "cancelled":
            stop_reason = "cancel_requested"
            break
        if time.monotonic() - started >= definition.max_seconds:
            stop_reason = "time_quota_exceeded"
            break
    else:
        stop_reason = "quota_reached"

    rows = tuple(existing.values())
    completed = [item for item in rows if item.get("status") == "completed" and item.get("score") is not None]
    best = max(completed, key=lambda item: (float(item["score"]), str(item["trial_id"])), default=None)
    baseline = next((item for item in rows if item.get("trial_id") == "baseline" and item.get("score") is not None), None)
    importance = _parameter_importance(completed)
    status = "cancelled" if stop_reason == "cancel_requested" else "completed"
    summary = OptimisationSummary(
        run_id,
        status,
        len(rows),
        sum(item.get("status") == "completed" for item in rows),
        sum(item.get("status") == "pruned" for item in rows),
        sum(item.get("status") == "failed" for item in rows),
        sum(item.get("status") == "cancelled" for item in rows),
        None if best is None else str(best["trial_id"]),
        None if best is None else float(best["score"]),
        None if baseline is None else float(baseline["score"]),
        float(len(rows)),
        importance,
        peak_memory,
        max(0.0, time.monotonic() - started),
        stop_reason,
        search_fingerprint,
        int(definition.seed),
    )
    ledger.record_summary(summary)
    return summary


def _evaluate_trial(
    ledger: OptimisationLedger,
    run_id: str,
    trial_id: str,
    sequence: int,
    parameters: Mapping[str, object],
    objective: Callable[[Mapping[str, object], DevelopmentOnlyContext], float],
    context: DevelopmentOnlyContext,
    quota: OptimisationQuota,
    prune_below: float | None,
    cancel_check: Callable[[], bool] | None,
) -> dict[str, object]:
    started = time.monotonic()
    tracemalloc.start()
    status: TrialStatus = "completed"
    score: float | None = None
    error: str | None = None
    try:
        value = float(objective(parameters, context))
        if not math.isfinite(value):
            raise ValueError("objective must return a finite score")
        score = value
        if prune_below is not None and value < float(prune_below):
            status = "pruned"
        if cancel_check is not None and cancel_check():
            status = "cancelled"
            error = "cancel requested after objective evaluation"
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_memory_mb = peak_bytes / (1024 * 1024)
    duration_ms = (time.monotonic() - started) * 1000.0
    if duration_ms / 1000.0 > quota.max_seconds:
        status = "failed"
        error = f"time quota exceeded: {duration_ms / 1000.0:.3f} seconds > {quota.max_seconds:.3f} seconds"
    if peak_memory_mb > quota.max_memory_mb:
        status = "failed"
        error = f"memory quota exceeded: {peak_memory_mb:.3f} MB > {quota.max_memory_mb} MB"
    record = TrialRecord(
        run_id,
        trial_id,
        sequence,
        _redacted_mapping(parameters),
        status,
        score,
        duration_ms,
        peak_memory_mb,
        error,
        trial_id == "baseline",
    )
    return ledger.record(record)


def _validate_parameter_space(parameter_space: Mapping[str, Sequence[object]]) -> dict[str, tuple[object, ...]]:
    if not isinstance(parameter_space, Mapping) or not parameter_space:
        raise ValueError("parameter_space must contain at least one parameter")
    clean: dict[str, tuple[object, ...]] = {}
    for key, options in sorted(parameter_space.items(), key=lambda item: str(item[0])):
        name = _identifier(str(key), "parameter_name")
        if isinstance(options, (str, bytes)) or not isinstance(options, Sequence) or not options:
            raise ValueError(f"parameter {name} must provide a non-empty sequence")
        for value in options:
            try:
                json.dumps(value, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"parameter {name} contains a non-JSON value") from exc
        clean[name] = tuple(options)
    return clean


def _search_fingerprint(values: Mapping[str, tuple[object, ...]], seed: int) -> str:
    payload = json.dumps({"parameter_space": values, "seed": int(seed)}, sort_keys=True, allow_nan=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parameters_for_sequence(values: Mapping[str, tuple[object, ...]], rng: random.Random, sequence: int) -> dict[str, object]:
    if sequence == 0:
        return {key: options[0] for key, options in values.items()}
    return {key: options[rng.randrange(len(options))] for key, options in values.items()}


def _parameter_importance(rows: Sequence[Mapping[str, object]]) -> dict[str, float]:
    if not rows:
        return {}
    scores = [float(row["score"]) for row in rows if row.get("score") is not None]
    spread = max(scores) - min(scores) if scores else 0.0
    if spread <= 0:
        return {key: 0.0 for key in sorted(rows[0].get("parameters", {}))}
    result: dict[str, float] = {}
    keys = sorted({key for row in rows for key in row.get("parameters", {})})
    for key in keys:
        groups: dict[str, list[float]] = {}
        for row in rows:
            parameters = row.get("parameters", {})
            if key in parameters and row.get("score") is not None:
                groups.setdefault(json.dumps(parameters[key], sort_keys=True, default=str), []).append(float(row["score"]))
        group_spread = max((max(values) - min(values) for values in groups.values()), default=0.0)
        result[key] = round(min(1.0, group_spread / spread), 6)
    return dict(sorted(result.items()))


def _redacted_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _safe_json(item) for key, item in value.items()}


def _safe_json(value: object) -> object:
    if isinstance(value, Mapping):
        return _redacted_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    return value


def _identifier(value: str, label: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 160 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise ValueError(f"{label} must be a bounded identifier")
    return value


__all__ = [
    "OPTIMISATION_SCHEMA_VERSION",
    "DevelopmentOnlyContext",
    "OptimisationError",
    "OptimisationLedger",
    "OptimisationQuota",
    "OptimisationSummary",
    "TrialRecord",
    "run_bounded_optimisation",
]
