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
from pathlib import Path
from typing import Literal

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.models.model_promotion import PRETRAINING_CUTOFFS
from etf_cockpit.validation.protocol import ValidationSpec, build_walk_forward_splits
from etf_cockpit.validation.tuning_registry import TuningDefaults, TuningRegistry, registry_fingerprint


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
    pruning: PruningRule | None = None,
    refine_after: int | None = None,
    patience: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    identity: Mapping[str, object] | None = None,
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
    deadline = started + float(definition.max_seconds)
    peak_memory = max((float(item.get("peak_memory_mb", 0.0)) for item in existing.values()), default=0.0)
    stop_reason = "quota_reached"
    rng = random.Random(int(definition.seed))
    best_seen: float | None = None
    stale = 0
    for sequence in range(int(definition.max_trials)):
        trial_id = "baseline" if sequence == 0 else f"trial-{sequence:04d}"
        if refine_after is not None and sequence >= int(refine_after):
            parameters = _refined_parameters(values, existing, int(definition.seed), sequence)
        else:
            parameters = _parameters_for_sequence(values, rng, sequence)
        if trial_id not in existing:
            if cancel_check is not None and cancel_check():
                stop_reason = "cancel_requested"
                break
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
) -> dict[str, object]:
    started = clock()
    intermediate: dict[str, float] = {}

    def reporter(step: int, value: float) -> None:
        if not math.isfinite(value):
            raise ValueError("intermediate value must be finite")
        intermediate[str(step)] = value
        if clock() >= deadline:
            raise TrialInterrupted(f"run time quota reached at step {step}")
        if pruning is not None and pruning.should_prune(step, value, history):
            raise TrialPruned(f"pruned at step {step}")

    trial_context = DevelopmentOnlyContext(context.run_id, context.split, context.final_test_available, reporter)
    tracemalloc.start()
    status: TrialStatus = "completed"
    score: float | None = None
    error: str | None = None
    try:
        value = float(objective(parameters, trial_context))
        if not math.isfinite(value):
            raise ValueError("objective must return a finite score")
        score = value
        if prune_below is not None and value < float(prune_below):
            status = "pruned"
        if cancel_check is not None and cancel_check():
            status = "cancelled"
            error = "cancel requested after objective evaluation"
    except TrialPruned as exc:
        status = "pruned"
        error = str(exc)
    except TrialInterrupted as exc:
        status = "failed"
        error = f"time quota exceeded (cooperative): {exc}"
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_memory_mb = peak_bytes / (1024 * 1024)
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
    tuning window; the purged gap, the evaluation window and the reserved final
    tail are never passed to the search.  The candidate is proposed only if it
    beats the current settings out of sample by the configured margin, after a
    change penalty, in enough evaluation blocks; otherwise the decision is
    ``keep_current``.  Missing or unverifiable evidence gives ``unavailable``.
    Settings files are never written.

    The whole run (search plus out-of-sample judging) shares ``max_seconds``: the
    search may use ``_SEARCH_TIME_FRACTION`` of it, and out-of-sample evaluation
    is checked against the full deadline and cancellation between and inside
    calls.  ``evaluator_identity`` (or an ``identity`` attribute on ``evaluate``)
    names the data/objective the scores come from; it is mandatory for market and
    private data.  Retained trials are reused only under an identical identity.
    """

    run_id = _identifier(run_id, "run_id")
    config = defaults or registry.defaults
    guards, split = config.guards, config.split
    current = registry.current_values()
    run_started = clock()
    deadline = run_started + float(config.search.max_seconds)
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
    try:
        spec = ValidationSpec(1, split.eval_size, split.horizon, split.embargo, split.final_test_size, seed=config.search.seed)
        fold = build_walk_forward_splits(len(dates), spec)[0]
    except ValueError as exc:
        return unavailable(f"insufficient_samples: {exc}")
    tune, evaluation = fold.train_indices, fold.validation_indices
    windows: dict[str, object] = {
        "tune": _window(dates, tune),
        "purged_gap": len(fold.purged_indices),
        "evaluation": _window(dates, evaluation),
        "reserved_final_tail": split.final_test_size,
    }
    if len(tune) < guards.min_tune_samples:
        return unavailable(f"insufficient_tuning_samples: {len(tune)} < {guards.min_tune_samples}", windows)
    if len(evaluation) < max(guards.min_eval_samples, guards.eval_blocks):
        return unavailable(f"insufficient_evaluation_samples: {len(evaluation)} < {max(guards.min_eval_samples, guards.eval_blocks)}", windows)
    evidence = _cutoff_evidence(registry, dates[tune[0]], data_provenance, model_cutoffs)
    objective_identity = evaluator_identity if evaluator_identity is not None else getattr(evaluate, "identity", None)
    if not isinstance(objective_identity, str) or not objective_identity.strip():
        # a module/qualname fallback cannot distinguish closures over different data or targets, so no run (synthetic included) may reuse evidence without it
        return unavailable("evaluator_identity_unverified", windows, evidence)
    penalty = float(guards.change_penalty)
    bound_identity = {
        "evaluator": str(objective_identity),
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

    def objective(raw: Mapping[str, object], context: DevelopmentOnlyContext) -> float:
        parameters = registry.materialise(raw)
        return float(evaluate(parameters, tune, context)) - penalty * registry.distance_from_current(parameters)

    quota = OptimisationQuota(config.search.max_trials, config.search.max_seconds * _SEARCH_TIME_FRACTION, config.search.max_memory_mb, config.search.seed)
    try:
        summary = run_bounded_optimisation(
            root,
            run_id,
            registry.search_space(),
            objective,
            quota=quota,
            cancel_check=cancel_check,
            pruning=PruningRule(config.search.prune_warmup_trials),
            refine_after=config.search.refine_after,
            patience=config.search.patience,
            clock=clock,
            identity=bound_identity,
        )
    except OptimisationError:
        return unavailable("retained_evidence_identity_mismatch", windows, evidence)
    search = {
        "stop_reason": summary.stop_reason,
        "trial_count": summary.trial_count,
        "completed_count": summary.completed_count,
        "pruned_count": summary.pruned_count,
        "failed_count": summary.failed_count,
        "best_trial_id": summary.best_trial_id,
        "search_fingerprint": summary.search_fingerprint,
        "seed": summary.seed,
        "time_limit": "cooperative",
    }
    in_sample = {"baseline_score": summary.baseline_score, "best_score": summary.best_score, "scores_include_change_penalty": True}
    if summary.status == "cancelled":
        return unavailable("search_cancelled", windows, evidence, search)
    if summary.baseline_score is None or summary.best_score is None or summary.best_trial_id is None:
        return unavailable("baseline_trial_did_not_complete", windows, evidence, search)
    if next((item for item in OptimisationLedger(root).list(run_id) if item["trial_id"] == "baseline"), {}).get("status") != "completed":
        return unavailable("baseline_trial_did_not_complete", windows, evidence, search)

    def keep(reason: str, candidate: Mapping[str, float] | None = None, oos: Mapping[str, object] | None = None) -> TuningProposal:
        return TuningProposal(run_id, "keep_current", (reason,), current, candidate, windows, in_sample, oos, guard_view, evidence, search, base_inputs)

    if summary.best_trial_id == "baseline" or summary.best_score <= summary.baseline_score:
        return keep("no_in_sample_improvement_over_current")
    best_row = next(item for item in OptimisationLedger(root).list(run_id) if item["trial_id"] == summary.best_trial_id)
    try:
        candidate = registry.materialise(best_row["parameters"])  # type: ignore[arg-type]
    except Exception as exc:
        return unavailable(f"candidate_not_reconstructable: {type(exc).__name__}", windows, evidence, search)
    if all(abs(candidate[key] - current[key]) <= 1e-12 for key in current):
        return keep("candidate_equals_current")

    blocks = _blocks(evaluation, guards.eval_blocks)
    cost = penalty * registry.distance_from_current(candidate)

    def oos_report(step: int, value: float) -> None:
        if not math.isfinite(value):
            raise ValueError("intermediate value must be finite")
        if clock() >= deadline:
            raise TrialInterrupted(f"run time quota reached at step {step}")
        if cancel_check is not None and cancel_check():
            raise TrialInterrupted("cancel requested")

    oos_context = DevelopmentOnlyContext(run_id, reporter=oos_report)

    def oos_score(parameters: Mapping[str, float], block: Sequence[int]) -> float:
        if clock() >= deadline or (cancel_check is not None and cancel_check()):
            raise TrialInterrupted("run budget or cancellation reached before evaluation")
        value = _finite(evaluate(parameters, block, oos_context))
        if clock() >= deadline:
            raise TrialInterrupted("run time quota reached during evaluation")
        if cancel_check is not None and cancel_check():
            raise TrialInterrupted("cancel requested during evaluation")
        return value

    try:
        current_scores = [oos_score(current, block) for block in blocks]
        candidate_scores = [oos_score(candidate, block) for block in blocks]
    except TrialInterrupted:
        return unavailable("out_of_sample_interrupted", windows, evidence, search)
    except Exception as exc:  # category only: raw messages may carry secrets and are never exported
        return unavailable(f"out_of_sample_evaluation_failed: {type(exc).__name__}", windows, evidence, search)
    if cancel_check is not None and cancel_check():  # final gate before any decision is published
        return unavailable("out_of_sample_interrupted", windows, evidence, search)
    margins = [cand - cur - cost for cand, cur in zip(candidate_scores, current_scores)]
    wins = sum(margin > guards.min_improvement for margin in margins)
    mean_margin = sum(margins) / len(margins)
    win_fraction = wins / len(margins)
    oos = {
        "blocks": len(blocks),
        "current_scores": current_scores,
        "candidate_scores": candidate_scores,
        "change_cost": cost,
        "margins_after_cost": margins,
        "mean_margin_after_cost": mean_margin,
        "block_wins": wins,
        "win_fraction": win_fraction,
        "required_win_fraction": guards.min_block_win_fraction,
        "required_margin": guards.min_improvement,
    }
    if mean_margin > guards.min_improvement and win_fraction >= guards.min_block_win_fraction:
        return TuningProposal(run_id, "propose_change", ("beat_current_out_of_sample",), current, candidate, windows, in_sample, oos, guard_view, evidence, search, base_inputs)
    return keep("did_not_beat_current_out_of_sample", candidate, oos)


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


def _finite(value: object) -> float:
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number):
        raise ValueError("evaluation returned a non-finite score")
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
