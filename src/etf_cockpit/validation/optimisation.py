"""Bounded, local-only hyperparameter search evidence.

This module is an optimisation adapter, not a model trainer.  A developer
supplies a local objective that returns a development/validation score; final
test metrics are intentionally not accepted.  Every attempted trial is
durably recorded before a summary is returned, and no result grants model or
execution authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
import math
import random
import re
import time
import tracemalloc
import uuid
from pathlib import Path
from typing import Literal

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.models.model_promotion import PRETRAINING_CUTOFFS
from etf_cockpit.validation.protocol import ValidationSpec, build_walk_forward_splits
from etf_cockpit.validation.tuning_registry import TuningDefaults, TuningRegistry, registry_fingerprint


OPTIMISATION_SCHEMA_VERSION = "optimisation.v1"
_ENTITY_TRIAL = "optimisation.trial"
_ENTITY_SUMMARY = "optimisation.summary"
_ENTITY_JUDGEMENT = "optimisation.judgement"
# OD-4 validation gate of a tuning proposal (module constants: the tuning registry has no keys for them).
_GATE_MIN_DEFLATED_SHARPE = 0.95
_GATE_MAX_PBO = 0.2
_GATE_MAX_FDR = 0.10  # Benjamini-Yekutieli q
_GATE_BOOTSTRAP_REPETITIONS = 1000
_USEFUL_EDGE_PER_YEAR = 0.01  # owner "useful edge" X: +1%/yr net vs VWCE
_USEFUL_EDGE_UNITS = "net_return_vs_vwce"  # an evaluator declares its units with an ``edge_units`` attribute
_SECRET_KEY = re.compile(r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd|authorization|bearer|secret|token)", re.I)
TrialStatus = Literal["completed", "pruned", "failed", "cancelled"]


@dataclass(frozen=True)
class DevelopmentOnlyContext:
    """The only evaluation context exposed to an optimisation objective."""

    run_id: str
    split: str = "nested_development_validation"
    final_test_available: bool = False
    reporter: Callable[[int, float], None] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.split != "nested_development_validation" or self.final_test_available:
            raise ValueError("optimisation objectives require nested development validation only")

    def report(self, step: int, value: float) -> None:
        """Report an intermediate score; may raise TrialPruned/TrialInterrupted to stop the trial early."""

        if self.reporter is not None:
            self.reporter(int(step), float(value))


class OptimisationError(RuntimeError):
    """Raised when a search request violates the local optimisation contract."""


class TrialPruned(Exception):
    """Raised inside an objective by ``context.report`` when the pruner stops the trial."""


class TrialInterrupted(Exception):
    """Raised inside an objective by ``context.report`` when a cooperative time limit is reached."""


class _EvaluationCancelled(TrialInterrupted):
    pass


class _MemoryQuotaExceeded(TrialInterrupted):
    pass


@dataclass
class _EvaluationGuard:
    """One cooperative guard for search calls, unseen-window calls and decisions.

    Memory is the Python-tracked allocation peak for each call, including
    allocations freed before return. Native memory and hung calls need isolation.
    """

    deadline: float
    max_memory_mb: int
    clock: Callable[[], float]
    cancel_check: Callable[[], bool] | None = None
    peak_memory_mb: float = 0.0
    _tracking: bool = False
    _initial_bytes: int = 0

    def _check_memory(self) -> None:
        if self._tracking:
            _, peak_bytes = tracemalloc.get_traced_memory()
            self.peak_memory_mb = max(self.peak_memory_mb, (peak_bytes - self._initial_bytes) / (1024 * 1024))
            if self.peak_memory_mb > self.max_memory_mb:
                raise _MemoryQuotaExceeded(f"memory quota exceeded: {self.peak_memory_mb:.3f} MB > {self.max_memory_mb} MB")

    def check(self) -> None:
        self._check_memory()
        if self.cancel_check is not None and self.cancel_check():
            raise _EvaluationCancelled("cancel requested")
        if self.clock() >= self.deadline:
            raise TrialInterrupted("run time quota reached")

    def call(self, evaluate: Callable[[DevelopmentOnlyContext], float], context: DevelopmentOnlyContext) -> float:
        owns_trace = not tracemalloc.is_tracing()
        if owns_trace:
            tracemalloc.start()
        self._initial_bytes = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        self.peak_memory_mb = 0.0
        self._tracking = True

        def report(step: int, value: float) -> None:
            self.check()
            if not math.isfinite(value):
                raise ValueError("intermediate value must be finite")
            if context.reporter is not None:
                context.reporter(step, value)

        guarded_context = DevelopmentOnlyContext(context.run_id, context.split, context.final_test_available, report)
        try:
            self.check()
            return _finite(evaluate(guarded_context))
        finally:
            try:
                self.check()  # errors/pruning also cannot bypass quotas or cancellation
            finally:
                self._tracking = False
                if owns_trace:
                    tracemalloc.stop()


@dataclass(frozen=True)
class PruningRule:
    """Median pruner: stop a trial whose intermediate value trails the median of completed trials at that step."""

    warmup_trials: int = 5
    min_step: int = 0

    def __post_init__(self) -> None:
        if int(self.warmup_trials) < 1 or int(self.min_step) < 0:
            raise ValueError("warmup_trials must be >= 1 and min_step >= 0")

    def should_prune(self, step: int, value: float, history: Sequence[Mapping[str, float]]) -> bool:
        if step < self.min_step:
            return False
        peers = sorted(float(item[str(step)]) for item in history if str(step) in item)
        if len(peers) < int(self.warmup_trials):
            return False
        middle = len(peers) // 2
        median = peers[middle] if len(peers) % 2 else (peers[middle - 1] + peers[middle]) / 2.0
        return value < median


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
    intermediate: Mapping[str, float] = field(default_factory=dict)
    search_fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.final_test_score is not None or self.execution_allowed:
            raise ValueError("optimisation evidence cannot contain final-test selection or execution authority")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
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
        if self.intermediate:  # additive key: records without intermediate reports stay byte-identical
            payload["intermediate"] = dict(self.intermediate)
        if self.search_fingerprint:  # additive key: binds the score to the search/evidence identity it was produced under
            payload["search_fingerprint"] = self.search_fingerprint
        return payload


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

    def record(self, trial: TrialRecord, store: TransactionalStore | None = None) -> dict[str, object]:
        """Write one trial in its own transaction; ``store`` is an already open store of this root (one open per run)."""

        if store is None:
            with TransactionalStore(self.root) as opened:
                return self.record(trial, opened)
        payload = trial.to_dict()
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
    pruning: PruningRule | None = None,
    refine_after: int | None = None,
    patience: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    identity: Mapping[str, object] | None = None,
    deadline: float | None = None,
) -> OptimisationSummary:
    """Run or resume a deterministic, quota-bounded local search.

    The objective is called only with generated local parameter values and
    must return a finite development/validation score.  It is never serialised
    or imported from user data.  Reusing ``run_id`` resumes from durable trial
    records without duplicating evidence.  The first option of every parameter
    is the baseline (current setting).

    ``pruning`` stops a trial mid-objective when it calls ``context.report``;
    ``refine_after`` switches to seeded one-step moves around the best trial so
    far; ``patience`` stops after that many consecutive non-improving trials.
    Time limits are cooperative: they are checked between trials and at every
    ``context.report`` call, but cannot interrupt an objective that never reports.
    ``identity`` (JSON-able) binds retained trials to the data/objective/window
    identity they were scored under: a resume with a different identity, or with
    retained trials that carry no matching fingerprint, is refused.
    ``deadline`` may cap the search at an enclosing run's earlier deadline.
    """

    definition = quota or OptimisationQuota()
    run_id = _identifier(run_id, "run_id")
    values = _validate_parameter_space(parameter_space)
    if not callable(objective):
        raise TypeError("objective must be a local callable")
    if refine_after is not None and int(refine_after) < 1:
        raise ValueError("refine_after must be at least 1 (the baseline is trial 0)")
    if patience is not None and int(patience) < 1:
        raise ValueError("patience must be positive")
    ledger = OptimisationLedger(root)
    context = DevelopmentOnlyContext(run_id)
    search_fingerprint = _search_fingerprint(values, int(definition.seed), refine_after, identity)
    prior_summary = next((item for item in ledger.list_summaries() if item.get("run_id") == run_id), None)
    if prior_summary is not None and prior_summary.get("search_fingerprint") != search_fingerprint:
        raise OptimisationError("cannot resume optimisation with a different seed or parameter space")
    existing = {str(item["trial_id"]): item for item in ledger.list(run_id)}
    if identity is not None and any(item.get("search_fingerprint") != search_fingerprint for item in existing.values()):
        raise OptimisationError("cannot resume optimisation: retained trials were scored under a different evidence identity")
    started = clock()
    deadline = min(started + float(definition.max_seconds), deadline) if deadline is not None else started + float(definition.max_seconds)
    peak_memory = max((float(item.get("peak_memory_mb", 0.0)) for item in existing.values()), default=0.0)
    stop_reason = "quota_reached"
    rng = random.Random(int(definition.seed))
    best_seen: float | None = None
    stale = 0
    with TransactionalStore(ledger.root) as store:  # one open per run; each trial is still its own transaction
        for sequence in range(int(definition.max_trials)):
            trial_id = "baseline" if sequence == 0 else f"trial-{sequence:04d}"
            if refine_after is not None and sequence >= int(refine_after):
                parameters = _refined_parameters(values, existing, int(definition.seed), sequence)
            else:
                parameters = _parameters_for_sequence(values, rng, sequence)
            if trial_id in existing:
                if cancel_check is not None and cancel_check():
                    stop_reason = "cancel_requested"
                    break
            else:
                if existing and clock() >= deadline:  # the baseline always runs, so a run is never empty
                    stop_reason = "time_quota_exceeded"
                    break
                history = [item["intermediate"] for item in existing.values() if item.get("status") == "completed" and item.get("intermediate")]
                existing[trial_id] = _evaluate_trial(
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
                    pruning,
                    history,
                    clock,
                    deadline,
                    search_fingerprint,
                    store,
                )
                peak_memory = max(peak_memory, float(existing[trial_id].get("peak_memory_mb", 0.0)))
            trial = existing[trial_id]
            if trial["status"] == "cancelled":
                stop_reason = "cancel_requested"
                break
            if trial["status"] == "completed" and trial.get("score") is not None and (best_seen is None or float(trial["score"]) > best_seen):
                best_seen, stale = float(trial["score"]), 0
            else:
                stale += 1
            if patience is not None and stale >= int(patience):
                stop_reason = "no_improvement"
                break
            if clock() >= deadline:
                stop_reason = "time_quota_exceeded"
                break
        else:
            stop_reason = "quota_reached"

    rows = tuple(existing.values())
    completed = [item for item in rows if item.get("status") == "completed" and item.get("score") is not None]
    best = max(completed, key=lambda item: (float(item["score"]), str(item["trial_id"])), default=None)
    baseline = next((item for item in rows if item.get("trial_id") == "baseline" and item.get("status") == "completed" and item.get("score") is not None), None)
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
        max(0.0, clock() - started),
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
    pruning: PruningRule | None,
    history: Sequence[Mapping[str, float]],
    clock: Callable[[], float],
    deadline: float,
    search_fingerprint: str = "",
    store: TransactionalStore | None = None,
) -> dict[str, object]:
    started = clock()
    intermediate: dict[str, float] = {}

    def reporter(step: int, value: float) -> None:
        intermediate[str(step)] = value
        if pruning is not None and pruning.should_prune(step, value, history):
            raise TrialPruned(f"pruned at step {step}")

    trial_context = DevelopmentOnlyContext(context.run_id, context.split, context.final_test_available, reporter)
    guard = _EvaluationGuard(deadline, quota.max_memory_mb, clock, cancel_check)
    status: TrialStatus = "completed"
    score: float | None = None
    error: str | None = None
    try:
        value = guard.call(lambda guarded_context: objective(parameters, guarded_context), trial_context)
        score = value
        if prune_below is not None and value < float(prune_below):
            status = "pruned"
    except _EvaluationCancelled as exc:
        status = "cancelled"
        error = str(exc)
    except _MemoryQuotaExceeded as exc:
        status = "failed"
        error = str(exc)
    except TrialPruned as exc:
        status = "pruned"
        error = str(exc)
    except TrialInterrupted as exc:
        status = "failed"
        error = f"time quota exceeded (cooperative): {exc}"
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
    peak_memory_mb = guard.peak_memory_mb
    duration_ms = (clock() - started) * 1000.0
    if duration_ms / 1000.0 > quota.max_seconds:
        status = "failed"
        score = None
        error = f"time quota exceeded: {duration_ms / 1000.0:.3f} seconds > {quota.max_seconds:.3f} seconds"
    if peak_memory_mb > quota.max_memory_mb:
        status = "failed"
        score = None  # a quota-violating trial never supplies evidence
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
        intermediate=intermediate,
        search_fingerprint=search_fingerprint,
    )
    return ledger.record(record, store)


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


def _search_fingerprint(
    values: Mapping[str, tuple[object, ...]], seed: int, refine_after: int | None = None, bound_identity: Mapping[str, object] | None = None
) -> str:
    identity: dict[str, object] = {"parameter_space": values, "seed": int(seed)}
    if refine_after is not None:  # keyed only when used, so earlier fingerprints stay valid
        identity["refine_after"] = int(refine_after)
    if bound_identity is not None:
        identity["evidence_identity"] = dict(bound_identity)
    payload = json.dumps(identity, sort_keys=True, allow_nan=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parameters_for_sequence(values: Mapping[str, tuple[object, ...]], rng: random.Random, sequence: int) -> dict[str, object]:
    if sequence == 0:
        return {key: options[0] for key, options in values.items()}
    return {key: options[rng.randrange(len(options))] for key, options in values.items()}


def _refined_parameters(
    values: Mapping[str, tuple[object, ...]],
    existing: Mapping[str, Mapping[str, object]],
    seed: int,
    sequence: int,
) -> dict[str, object]:
    """One seeded grid step away from the best completed trial so far (independent of earlier draws)."""

    completed = [item for item in existing.values() if item.get("status") == "completed" and item.get("score") is not None]
    best = max(completed, key=lambda item: (float(item["score"]), str(item["trial_id"])), default=None)
    if best is None:
        return {key: options[0] for key, options in values.items()}
    parameters = {key: best["parameters"].get(key, options[0]) for key, options in values.items()}  # type: ignore[union-attr]
    movable = [key for key, options in values.items() if len(options) > 1 and parameters[key] in options]
    if not movable:
        return parameters
    rng = random.Random(f"{seed}:{sequence}")
    key = movable[rng.randrange(len(movable))]
    options = values[key]
    index = options.index(parameters[key]) + rng.choice((-1, 1))
    parameters[key] = options[min(len(options) - 1, max(0, index))]
    return parameters


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


TUNING_PROPOSAL_SCHEMA_VERSION = "tuning-proposal.v1"
TuningDecision = Literal["keep_current", "propose_change", "unavailable"]
DataProvenance = Literal["market", "synthetic", "private"]
TuningEvaluator = Callable[[Mapping[str, float], Sequence[int], DevelopmentOnlyContext], float]
_SEARCH_TIME_FRACTION = 0.8  # share of the run budget the search may use; the rest is reserved for out-of-sample judging


@dataclass(frozen=True)
class TuningProposal:
    """Proposal artefact: a recommendation only.  Nothing here is ever applied to settings."""

    run_id: str
    decision: TuningDecision
    reasons: tuple[str, ...]
    current: Mapping[str, float]
    candidate: Mapping[str, float] | None
    windows: Mapping[str, object]
    in_sample: Mapping[str, object]
    out_of_sample: Mapping[str, object] | None
    guards: Mapping[str, object]
    evidence: Mapping[str, object]
    search: Mapping[str, object]
    inputs: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        changes = (
            {}
            if self.candidate is None
            else {key: round(float(self.candidate[key]) - float(self.current[key]), 10) for key in self.current if abs(float(self.candidate[key]) - float(self.current[key])) > 1e-12}
        )
        body: dict[str, object] = {
            "schema_version": TUNING_PROPOSAL_SCHEMA_VERSION,
            "run_id": self.run_id,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "current": dict(self.current),
            "candidate": None if self.candidate is None else dict(self.candidate),
            "changes": changes,
            "windows": dict(self.windows),
            "in_sample": dict(self.in_sample),
            "out_of_sample": None if self.out_of_sample is None else dict(self.out_of_sample),
            "guards": dict(self.guards),
            "evidence": dict(self.evidence),
            "search": dict(self.search),
            "inputs": dict(self.inputs),
            "applied": False,
            "settings_modified": False,
            "owner_review_required": True,
            "execution_allowed": False,
        }
        body["proposal_fingerprint"] = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False, default=str).encode("utf-8")).hexdigest()
        return body


def run_walk_forward_tuning(
    root: Path,
    run_id: str,
    registry: TuningRegistry,
    evaluate: TuningEvaluator,
    sample_dates: Sequence[date],
    *,
    data_provenance: DataProvenance = "market",
    model_cutoffs: Mapping[str, date] | None = None,
    defaults: TuningDefaults | None = None,
    cancel_check: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
    evaluator_identity: str | None = None,
) -> TuningProposal:
    """Tune on one window, then judge the winner on a LATER unseen window.

    ``evaluate(parameters, indices, context)`` returns a higher-is-better score
    for the given sample indices and must be point-in-time (an index may only
    use information available at that sample's date).  Tuning sees only the
    tuning window; the purged gap, the evaluation folds and the final test are
    never passed to the search.  Every completed or pruned trial is then scored
    per date (after the change penalty) and judged by one registered
    ``validation.protocol`` evaluation: the fold-selected trial is proposed only
    if it is promotion-eligible there and passes the OD-4 gate (bootstrap
    lower_5 above the margin, DSR, PBO, Benjamini-Yekutieli q, a positive final
    test margin and the useful edge in net return vs VWCE per year); otherwise
    the decision is ``keep_current``.  The final test is consumed once; an
    identical resume reuses the stored judgement.  Missing or unverifiable
    evidence gives ``unavailable``.  Settings files are never written.

    The whole run (search plus out-of-sample judging) shares ``max_seconds``: the
    search may use ``_SEARCH_TIME_FRACTION`` of it. Every evaluator call checks
    the deadline, cancellation and Python-tracked memory before/after the call
    and at intermediate reports; every decision also checks the run guards.
    ``evaluator_identity`` (or an ``identity`` attribute on ``evaluate``) names
    the data/objective the scores come from. Retained trials are reused only
    under an identical verified identity. An unverifiable identity starts a
    fresh evidence namespace and cannot supply promotion evidence.
    """

    run_id = _identifier(run_id, "run_id")
    config = defaults or registry.defaults
    guards, split = config.guards, config.split
    current = registry.current_values()
    run_started = clock()
    deadline = run_started + float(config.search.max_seconds)
    run_guard = _EvaluationGuard(deadline, config.search.max_memory_mb, clock, cancel_check)
    base_inputs = {
        "registry_version": registry.version,
        "registry_checksum": registry.registry_checksum,
        "registry_fingerprint": registry_fingerprint(registry),
        "source_checksums": dict(registry.source_checksums),
        "sample_count": len(sample_dates),
    }
    guard_view = {
        "min_tune_samples": guards.min_tune_samples,
        "min_eval_samples": guards.min_eval_samples,
        "eval_blocks": guards.eval_blocks,
        "min_block_win_fraction": guards.min_block_win_fraction,
        "change_penalty": guards.change_penalty,
        "min_improvement": guards.min_improvement,
        "split": {"eval_size": split.eval_size, "horizon": split.horizon, "embargo": split.embargo, "final_test_size": split.final_test_size},
        "search": {"max_trials": config.search.max_trials, "max_seconds": config.search.max_seconds, "seed": config.search.seed},
    }

    def unavailable(reason: str, windows: Mapping[str, object] | None = None, evidence: Mapping[str, object] | None = None, search: Mapping[str, object] | None = None) -> TuningProposal:
        return TuningProposal(run_id, "unavailable", (reason,), current, None, windows or {}, {}, None, guard_view, evidence or _evidence_stub(data_provenance), search or {}, base_inputs)

    dates = list(sample_dates)
    if any(not isinstance(item, date) or isinstance(item, datetime) for item in dates):
        return unavailable("sample_dates_must_be_dates")
    if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
        return unavailable("sample_dates_not_strictly_increasing")
    # The protocol's strict split: tune | purge | eval_blocks folds | horizon gap | final test (scored once).
    try:
        spec = ValidationSpec(
            guards.eval_blocks, split.eval_size // max(1, guards.eval_blocks), split.horizon, split.embargo, split.final_test_size,
            bootstrap_repetitions=_GATE_BOOTSTRAP_REPETITIONS, seed=config.search.seed,
            periods_per_year=(len(dates) - 1) * 365.25 / (dates[-1] - dates[0]).days if len(dates) > 1 else None,
        )
        folds = build_walk_forward_splits(len(dates), spec, strict_label_purge=True)
    except ValueError as exc:
        return unavailable(f"insufficient_samples: {exc}")
    tune = folds[0].train_indices
    evaluation = tuple(index for fold in folds for index in fold.validation_indices)
    windows: dict[str, object] = {
        "tune": _window(dates, tune),
        "purged_gap": len(folds[0].purged_indices),
        "evaluation": _window(dates, evaluation),
        "final_test": _window(dates, range(len(dates) - split.final_test_size, len(dates))),
    }
    if len(tune) < guards.min_tune_samples:
        return unavailable(f"insufficient_tuning_samples: {len(tune)} < {guards.min_tune_samples}", windows)
    if len(evaluation) < max(guards.min_eval_samples, guards.eval_blocks):
        return unavailable(f"insufficient_evaluation_samples: {len(evaluation)} < {max(guards.min_eval_samples, guards.eval_blocks)}", windows)
    evidence = _cutoff_evidence(registry, dates[tune[0]], data_provenance, model_cutoffs)
    objective_identity = evaluator_identity if evaluator_identity is not None else getattr(evaluate, "identity", None)
    identity_verified = isinstance(objective_identity, str) and bool(objective_identity.strip())
    # Never overwrite or resume an earlier namespace when closures cannot be distinguished.
    search_run_id = run_id if identity_verified else f"fresh-{uuid.uuid4().hex}"
    if not identity_verified:
        evidence["flags"].append("evaluator_identity_unverified")
        evidence["promotion_evidence_eligible"] = False
    penalty = float(guards.change_penalty)
    bound_identity = {
        "evaluator": objective_identity if identity_verified else None,
        "data_provenance": data_provenance,
        "dates_sha256": hashlib.sha256(",".join(item.isoformat() for item in dates).encode("utf-8")).hexdigest(),
        "tune_indices": [tune[0], tune[-1]],
        "registry_fingerprint": base_inputs["registry_fingerprint"],
        "guards": guard_view,
        "search_config": {  # every effective search setting, so a changed quota/stop rule never reuses earlier evidence
            "max_trials": config.search.max_trials,
            "max_seconds": config.search.max_seconds,
            "max_memory_mb": config.search.max_memory_mb,
            "seed": config.search.seed,
            "refine_after": config.search.refine_after,
            "patience": config.search.patience,
            "prune_warmup_trials": config.search.prune_warmup_trials,
        },
        "change_penalty": penalty,
        "model_cutoffs": {key: value.isoformat() for key, value in sorted((model_cutoffs or {}).items())},
    }
    if not identity_verified:
        bound_identity["fresh_run_id"] = search_run_id

    def objective(raw: Mapping[str, object], context: DevelopmentOnlyContext) -> float:
        parameters = registry.materialise(raw)
        return float(evaluate(parameters, tune, context)) - penalty * registry.distance_from_current(parameters)

    quota = OptimisationQuota(config.search.max_trials, config.search.max_seconds * _SEARCH_TIME_FRACTION, config.search.max_memory_mb, config.search.seed)
    try:
        summary = run_bounded_optimisation(
            root,
            search_run_id,
            registry.search_space(),
            objective,
            quota=quota,
            cancel_check=cancel_check,
            pruning=PruningRule(config.search.prune_warmup_trials),
            refine_after=config.search.refine_after,
            patience=config.search.patience,
            clock=clock,
            identity=bound_identity,
            deadline=deadline,
        )
    except OptimisationError:
        return unavailable("retained_evidence_identity_mismatch", windows, evidence)
    search = {
        "run_id": summary.run_id,
        "resume_allowed": identity_verified,
        "stop_reason": summary.stop_reason,
        "trial_count": summary.trial_count,
        "completed_count": summary.completed_count,
        "pruned_count": summary.pruned_count,
        "failed_count": summary.failed_count,
        "best_trial_id": summary.best_trial_id,
        "search_fingerprint": summary.search_fingerprint,
        "seed": summary.seed,
        "peak_memory_mb": summary.peak_memory_mb,
        "time_limit": "cooperative",
    }
    in_sample = {"baseline_score": summary.baseline_score, "best_score": summary.best_score, "scores_include_change_penalty": True}
    if summary.status == "cancelled":
        return unavailable("search_cancelled", windows, evidence, search)
    if summary.baseline_score is None or summary.best_score is None or summary.best_trial_id is None:
        return unavailable("baseline_trial_did_not_complete", windows, evidence, search)
    rows = OptimisationLedger(root).list(search_run_id)
    if next((item for item in rows if item["trial_id"] == "baseline"), {}).get("status") != "completed":
        return unavailable("baseline_trial_did_not_complete", windows, evidence, search)

    def decide(decision: TuningDecision, reason: str, candidate: Mapping[str, float] | None = None, oos: Mapping[str, object] | None = None) -> TuningProposal:
        try:
            run_guard.check()
        except TrialInterrupted:
            return unavailable("decision_interrupted", windows, evidence, search)
        return TuningProposal(run_id, decision, (reason,), current, candidate, windows, in_sample, oos, guard_view, evidence, search, base_inputs)

    if summary.best_trial_id == "baseline" or summary.best_score <= summary.baseline_score:
        return decide("keep_current", "no_in_sample_improvement_over_current")
    best_row = next(item for item in rows if item["trial_id"] == summary.best_trial_id)
    try:
        candidate = registry.materialise(best_row["parameters"])  # type: ignore[arg-type]
    except Exception as exc:
        return unavailable(f"candidate_not_reconstructable: {type(exc).__name__}", windows, evidence, search)
    if all(abs(candidate[key] - current[key]) <= 1e-12 for key in current):
        return decide("keep_current", "candidate_equals_current")

    judgement_key = f"{search_run_id}:" + hashlib.sha256(
        json.dumps([bound_identity, summary.search_fingerprint], sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    with TransactionalStore(root) as store:
        stored = store.get(_ENTITY_JUDGEMENT, judgement_key)
    if stored is not None:  # identical resume: the final test is consumed once, its judgement is reused
        judged = stored.payload
        search["peak_memory_mb"] = max(float(search["peak_memory_mb"]), float(judged["peak_memory_mb"]))  # incl. the judging calls
        chosen =registry.materialise(judged["candidate"]) if judged["candidate"] is not None else None
        return decide(judged["decision"], judged["reason"], chosen, judged["oos"])

    # Every completed or pruned search trial is one member of the family the statistics correct for.
    family: dict[str, Mapping[str, float]] = {}
    for row in rows:
        if row.get("status") in {"completed", "pruned"}:
            try:
                family[str(row["trial_id"])] = registry.materialise(row["parameters"])  # type: ignore[arg-type]
            except Exception as exc:
                return unavailable(f"candidate_not_reconstructable: {type(exc).__name__}", windows, evidence, search)
    # The judged series keeps two (plus embargo) tuning dates as its unscored training rows, so its own strict split
    # puts the folds and the final test on the same dates as above.
    judged_indices = tuple(range(max(0, tune[-1] - 1 - split.embargo), len(dates)))
    per_session = getattr(evaluate, "per_session", None)  # optional: one score per sample date in one call
    oos_context = DevelopmentOnlyContext(search_run_id)

    def judged_series(parameters: Mapping[str, float]) -> list[float]:
        values: list[float] = []

        def score_all(context: DevelopmentOnlyContext) -> float:
            if per_session is not None:
                every = per_session(parameters)
                values.extend(_finite(every[index]) for index in judged_indices)
            else:
                values.extend(_finite(evaluate(parameters, (index,), context)) for index in judged_indices)
            return 0.0

        try:
            run_guard.call(score_all, oos_context)
        finally:
            search["peak_memory_mb"] = max(float(search["peak_memory_mb"]), run_guard.peak_memory_mb)
        cost = penalty * registry.distance_from_current(parameters)
        return [value - cost for value in values]

    try:
        scores = {trial_id: judged_series(parameters) for trial_id, parameters in family.items()}
    except _MemoryQuotaExceeded:
        return unavailable("out_of_sample_memory_quota_exceeded", windows, evidence, search)
    except TrialInterrupted:
        return unavailable("out_of_sample_interrupted", windows, evidence, search)
    except Exception as exc:  # category only: raw messages may carry secrets and are never exported
        return unavailable(f"out_of_sample_evaluation_failed: {type(exc).__name__}", windows, evidence, search)
    judged_folds = build_walk_forward_splits(len(judged_indices), spec, strict_label_purge=True)
    fold_means = {
        trial_id: [sum(values[i] for i in fold.validation_indices) / len(fold.validation_indices) for fold in judged_folds]
        for trial_id, values in scores.items()
    }
    # The protocol's selection rule (best mean of fold means, ties by id), frozen before the final test is read.
    selected = max(fold_means, key=lambda key: (sum(fold_means[key]) / len(fold_means[key]), key))
    judged_dates = [dates[index] for index in judged_indices]
    report = _registered_judgement(
        root, search_run_id, scores, spec, judged_dates, selected,
        identity=[objective_identity if identity_verified else search_run_id, bound_identity["dates_sha256"], base_inputs["registry_fingerprint"]],
        parameters={trial_id: dict(item) for trial_id, item in family.items()},
    )
    bootstrap = report.uncertainty
    final = {row.trial_id: row.final_test_score for row in report.trials}
    final_margin = None if final.get(selected) is None or final.get("baseline") is None else final[selected] - final["baseline"]
    edge_units = getattr(evaluate, "edge_units", None)
    mean_margin = bootstrap.get("mean")
    annual_edge = (
        float(mean_margin) * float(spec.periods_per_year) / split.horizon
        if isinstance(mean_margin, (int, float)) and spec.periods_per_year else None
    )
    margins = [cand - cur for cand, cur in zip(fold_means[selected], fold_means["baseline"])]
    checks = {
        "promotion_eligible": report.promotion_eligible,
        "bootstrap_lower_5_above_margin": float(bootstrap.get("lower_5", -math.inf)) > guards.min_improvement,
        "deflated_sharpe": report.deflated_sharpe is not None and report.deflated_sharpe >= _GATE_MIN_DEFLATED_SHARPE,
        "probability_of_backtest_overfitting": (
            report.probability_of_backtest_overfitting is not None and report.probability_of_backtest_overfitting <= _GATE_MAX_PBO
        ),
        "false_discovery_rate": report.false_discovery_rate is not None and report.false_discovery_rate <= _GATE_MAX_FDR,
        "final_test_same_sign": final_margin is not None and final_margin > 0,
        # The useful-edge threshold is in net return vs VWCE per year; other objective units cannot show it.
        "useful_edge": edge_units == _USEFUL_EDGE_UNITS and annual_edge is not None and annual_edge >= _USEFUL_EDGE_PER_YEAR,
    }
    oos = {
        "method": "validation.protocol registered evaluation: DSR, PBO, Benjamini-Yekutieli q, paired block bootstrap",
        "family_trials": len(scores),
        "selected_trial_id": selected,
        "evaluation_id": bootstrap.get("evaluation_id"),
        "holdout_status": report.holdout_status,
        "bootstrap": {key: bootstrap.get(key) for key in ("mean", "lower_5", "upper_95", "p_value", "block_size", "repetitions")},
        "deflated_sharpe": report.deflated_sharpe,
        "probability_of_backtest_overfitting": report.probability_of_backtest_overfitting,
        "false_discovery_rate": report.false_discovery_rate,
        "final_test_margin": final_margin,
        "edge_units": edge_units,
        "annualised_edge": annual_edge,
        "checks": checks,
        "thresholds": {
            "min_deflated_sharpe": _GATE_MIN_DEFLATED_SHARPE, "max_pbo": _GATE_MAX_PBO, "max_fdr": _GATE_MAX_FDR,
            "useful_edge_per_year": _USEFUL_EDGE_PER_YEAR, "useful_edge_units": _USEFUL_EDGE_UNITS,
            "required_margin": guards.min_improvement,
        },
        # Descriptive only (not a gate): fold means after the change penalty.
        "current_scores": fold_means["baseline"],
        "candidate_scores": fold_means[selected],
        "margins_after_cost": margins,
        "block_wins": sum(margin > guards.min_improvement for margin in margins),
        "win_fraction": sum(margin > guards.min_improvement for margin in margins) / len(margins),
    }
    if selected == "baseline":
        decision, reason, chosen = "keep_current", "current_selected_on_evaluation_folds", None
    elif all(checks.values()):
        decision, reason, chosen = "propose_change", "passed_validation_gate", family[selected]
    else:
        decision, reason, chosen = "keep_current", "failed_validation_gate:" + ",".join(key for key, ok in checks.items() if not ok), family[selected]
    stored_payload = json.loads(json.dumps(
        {"decision": decision, "reason": reason, "candidate": None if chosen is None else dict(chosen), "oos": oos,
         "peak_memory_mb": search["peak_memory_mb"]}, default=str
    ))
    with TransactionalStore(root) as store:
        store.put(_ENTITY_JUDGEMENT, judgement_key, stored_payload)
    return decide(decision, reason, chosen, stored_payload["oos"])


def _registered_judgement(
    root: Path, search_run_id: str, scores: Mapping[str, Sequence[float]], spec: ValidationSpec, dates: Sequence[date],
    selected: str, *, identity: Sequence[object], parameters: Mapping[str, Mapping[str, float]],
):
    """One registered protocol evaluation: the family is verified, the final test is consumed once per window."""

    from etf_cockpit.features.training_centre import LocalTrainingRegistry  # lazy: training_centre imports this module
    from etf_cockpit.validation.protocol import evaluate_trials

    def digest(value: object) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    data_hash = digest([list(identity), spec.fingerprint])
    registry = LocalTrainingRegistry(root)
    experiment = registry.create_experiment("tuner-validation-gate", experiment_id=f"tuner-gate-{data_hash[:24]}")
    run_id = f"{search_run_id}.judge"[-160:]
    registry.create_run(
        str(experiment["experiment_id"]), run_id=run_id, dataset_hash=data_hash, feature_hash=digest(sorted(scores)),
        code_hash=digest(TUNING_PROPOSAL_SCHEMA_VERSION), environment_hash=digest("local"),
    )
    comparators = ("baseline",) if selected != "baseline" else ()
    return evaluate_trials(
        scores, registry=registry, run_id=run_id, spec=spec, date_labels=list(dates), parameters=parameters,
        frozen_candidate_id=selected if comparators else None, predeclared_comparator_ids=comparators,
        holdout_id=f"tuner-final-{data_hash[:24]}" if comparators else None,
    )


def render_tuning_report(proposal: TuningProposal) -> str:
    """Plain-text (Markdown) report of a proposal; descriptive only."""

    data = proposal.to_dict()
    lines = [
        f"# Parameter tuning proposal: {proposal.run_id}",
        "",
        f"- Decision: **{proposal.decision}** ({', '.join(proposal.reasons)})",
        "- Applied to settings: no. Settings modified: no. Execution allowed: no. Owner review required.",
        f"- Evidence class: {proposal.evidence.get('evidence_class')}; promotion evidence eligible: {proposal.evidence.get('promotion_evidence_eligible')}",
    ]
    for flag in proposal.evidence.get("flags", ()):  # type: ignore[union-attr]
        lines.append(f"- Evidence flag: {flag}")
    lines += ["", "## Windows", ""]
    for name, window in proposal.windows.items():
        lines.append(f"- {name}: {window}")
    if proposal.search:
        lines += ["", "## Search", "", "- " + ", ".join(f"{key}={value}" for key, value in proposal.search.items())]
    if proposal.out_of_sample:
        lines += ["", "## Out of sample", ""] + [f"- {key}: {value}" for key, value in proposal.out_of_sample.items()]
    changes = data["changes"]
    if proposal.candidate is not None:
        lines += ["", "## Parameters", "", "| knob | current | candidate | change |", "|---|---|---|---|"]
        for key, value in proposal.current.items():
            lines.append(f"| {key} | {value} | {proposal.candidate[key]} | {changes.get(key, 0.0)} |")  # type: ignore[union-attr]
    lines += ["", f"Proposal fingerprint: `{data['proposal_fingerprint']}`", ""]
    return "\n".join(lines)


def synthetic_tuning_fixture(
    registry: TuningRegistry,
    planted: Mapping[str, float],
    *,
    n_samples: int = 800,
    seed: int = 7,
    noise: float = 0.05,
    start: date = date(2020, 1, 1),
) -> tuple[list[date], TuningEvaluator]:
    """Synthetic dates and an objective whose true optimum is ``planted`` (machinery tests only)."""

    rng = random.Random(seed)
    noise_values = [rng.uniform(-1.0, 1.0) for _ in range(int(n_samples))]
    dates: list[date] = []
    day = start
    while len(dates) < int(n_samples):
        if day.weekday() < 5:
            dates.append(day)
        day = day.fromordinal(day.toordinal() + 1)
    spans = {item.key: item.upper - item.lower for item in registry.parameters}

    def evaluate(parameters: Mapping[str, float], indices: Sequence[int], context: DevelopmentOnlyContext) -> float:
        loss = sum(((float(parameters[key]) - float(target)) / spans[key]) ** 2 for key, target in planted.items()) / len(planted)
        chunks = _blocks(indices, 4)
        seen = 0.0
        count = 0
        for step, chunk in enumerate(chunks):
            seen += sum(noise_values[index] for index in chunk)
            count += len(chunk)
            context.report(step, -loss + noise * seen / count)
        return -loss + noise * seen / count

    evaluate.identity = "synthetic:" + hashlib.sha256(  # type: ignore[attr-defined]
        json.dumps({"planted": dict(planted), "n": int(n_samples), "seed": seed, "noise": noise, "start": start.isoformat()}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return dates, evaluate


def _blocks(indices: Sequence[int], count: int) -> list[tuple[int, ...]]:
    size, extra = divmod(len(indices), count)
    blocks: list[tuple[int, ...]] = []
    cursor = 0
    for position in range(count):
        end = cursor + size + (1 if position < extra else 0)
        blocks.append(tuple(indices[cursor:end]))
        cursor = end
    return [block for block in blocks if block]


def _window(dates: Sequence[date], indices: Sequence[int]) -> dict[str, object]:
    return {"start": dates[indices[0]].isoformat(), "end": dates[indices[-1]].isoformat(), "samples": len(indices)}


_MAX_ABS_SCORE = 1e12


def _finite(value: object) -> float:
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number):
        raise ValueError("evaluation returned a non-finite score")
    # Bounded magnitude keeps every derived difference, mean and penalty finite.
    if abs(number) > _MAX_ABS_SCORE:
        raise ValueError("evaluation returned an out-of-range score")
    return number


def _evidence_stub(provenance: str) -> dict[str, object]:
    return {"data_provenance": provenance, "evidence_class": "not_assessed", "promotion_evidence_eligible": False, "flags": [], "cutoffs": {}}


def _cutoff_evidence(
    registry: TuningRegistry,
    first_used: date,
    provenance: str,
    model_cutoffs: Mapping[str, date] | None,
) -> dict[str, object]:
    """Flag windows that touch a model's pretraining period; synthetic data is never promotion evidence."""

    cutoffs = dict(PRETRAINING_CUTOFFS)
    cutoffs.update(model_cutoffs or {})
    models = registry.models_in_scope()
    flags: list[str] = []
    if provenance == "synthetic":
        evidence_class = "synthetic_machinery_only"
        flags.append("synthetic_data_not_promotion_evidence")
    elif provenance == "private":
        evidence_class = "private_data_outside_pretraining"
    else:
        evidence_class = "market_data_post_cutoff"
        for model in models:
            cutoff = cutoffs.get(model)
            if cutoff is None:
                flags.append(f"{model}:pretraining_cutoff_unknown")
            elif first_used <= cutoff:
                flags.append(f"{model}:pre_cutoff_window")
        if flags:
            evidence_class = "market_data_cutoff_flagged"
    return {
        "data_provenance": provenance,
        "evidence_class": evidence_class,
        "promotion_evidence_eligible": not flags,
        "flags": flags,
        "models_in_scope": list(models),
        "first_used_date": first_used.isoformat(),
        "cutoffs": {model: (cutoffs[model].isoformat() if model in cutoffs else "unknown") for model in models},
    }


__all__ = [
    "OPTIMISATION_SCHEMA_VERSION",
    "TUNING_PROPOSAL_SCHEMA_VERSION",
    "DevelopmentOnlyContext",
    "OptimisationError",
    "OptimisationLedger",
    "OptimisationQuota",
    "OptimisationSummary",
    "PruningRule",
    "TrialInterrupted",
    "TrialPruned",
    "TrialRecord",
    "TuningProposal",
    "render_tuning_report",
    "run_bounded_optimisation",
    "run_walk_forward_tuning",
    "synthetic_tuning_fixture",
]
