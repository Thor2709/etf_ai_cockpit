"""Deterministic walk-forward, purge/embargo and trial evidence.

This module is a validation protocol, not a model trainer.  Callers provide
per-observation scores for each trial; the protocol owns the split boundary,
selection, uncertainty and promotion evidence.  The final-test indices are
never consulted while selecting a trial.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Mapping, Sequence

import numpy as np


VALIDATION_PROTOCOL_VERSION = "validation-protocol.v1"


@dataclass(frozen=True)
class ValidationSpec:
    """Immutable temporal split definition."""

    n_splits: int = 5
    test_size: int = 20
    horizon: int = 1
    embargo: int = 0
    final_test_size: int = 20
    expanding: bool = True
    train_size: int | None = None
    bootstrap_repetitions: int = 200
    block_size: int = 5
    seed: int = 42

    def __post_init__(self) -> None:
        positive = ("n_splits", "test_size", "horizon", "final_test_size", "bootstrap_repetitions", "block_size")
        for field in positive:
            if int(getattr(self, field)) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.embargo < 0:
            raise ValueError("embargo must be non-negative")
        if self.train_size is not None and int(self.train_size) <= 0:
            raise ValueError("train_size must be positive when supplied")

    @property
    def fingerprint(self) -> str:
        return _sha256(_canonical(asdict(self)))


@dataclass(frozen=True)
class ValidationFold:
    fold: int
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    purged_indices: tuple[int, ...]
    embargoed_indices: tuple[int, ...]


@dataclass(frozen=True)
class ValidationTrial:
    trial_id: str
    parameters: Mapping[str, object]
    validation_scores: tuple[float, ...]
    validation_mean: float
    final_test_score: float | None
    selected: bool
    discarded_reason: str | None


@dataclass(frozen=True)
class ValidationReport:
    protocol_version: str
    spec: ValidationSpec
    folds: tuple[ValidationFold, ...]
    trials: tuple[ValidationTrial, ...]
    selected_trial_id: str | None
    final_test_score: float | None
    final_test_used_for_selection: bool
    uncertainty: Mapping[str, object]
    regime_results: Mapping[str, Mapping[str, object]]
    subgroup_results: Mapping[str, Mapping[str, object]]
    effective_independent_trial_count: float
    deflated_sharpe: float | None
    probability_of_backtest_overfitting: float | None
    false_discovery_rate: float | None
    promotion_eligible: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "spec": asdict(self.spec),
            "spec_fingerprint": self.spec.fingerprint,
            "folds": [asdict(fold) for fold in self.folds],
            "trials": [asdict(trial) for trial in self.trials],
            "selected_trial_id": self.selected_trial_id,
            "final_test_score": self.final_test_score,
            "final_test_used_for_selection": self.final_test_used_for_selection,
            "uncertainty": dict(self.uncertainty),
            "regime_results": {key: dict(value) for key, value in self.regime_results.items()},
            "subgroup_results": {key: dict(value) for key, value in self.subgroup_results.items()},
            "effective_independent_trial_count": self.effective_independent_trial_count,
            "deflated_sharpe": self.deflated_sharpe,
            "probability_of_backtest_overfitting": self.probability_of_backtest_overfitting,
            "false_discovery_rate": self.false_discovery_rate,
            "promotion_eligible": self.promotion_eligible,
            "warnings": list(self.warnings),
            "report_fingerprint": report_fingerprint(self),
        }


def build_walk_forward_splits(n_samples: int, spec: ValidationSpec | None = None) -> tuple[ValidationFold, ...]:
    """Return non-overlapping temporal folds with label purge and embargo."""

    definition = spec or ValidationSpec()
    n_samples = int(n_samples)
    development_end = n_samples - definition.final_test_size
    required = definition.final_test_size + definition.n_splits * definition.test_size + definition.horizon + definition.embargo
    if n_samples < required:
        raise ValueError(f"at least {required} observations are required for this validation spec")
    folds: list[ValidationFold] = []
    for fold in range(definition.n_splits):
        validation_start = development_end - (definition.n_splits - fold) * definition.test_size
        validation_end = validation_start + definition.test_size
        purge_end = max(0, validation_start - definition.horizon + 1)
        embargo_start = validation_end
        embargo_end = min(development_end, validation_end + definition.embargo)
        train_start = 0 if definition.expanding or definition.train_size is None else max(0, purge_end - definition.train_size)
        train_indices = tuple(range(train_start, purge_end))
        purged = tuple(range(purge_end, validation_start))
        embargoed = tuple(range(embargo_start, embargo_end))
        folds.append(ValidationFold(fold, train_indices, tuple(range(validation_start, validation_end)), purged, embargoed))
    return tuple(folds)


def evaluate_trials(
    scores: Mapping[str, Sequence[float]],
    *,
    spec: ValidationSpec | None = None,
    parameters: Mapping[str, Mapping[str, object]] | None = None,
    regime_labels: Sequence[str] | None = None,
    subgroup_labels: Sequence[str] | None = None,
    baseline_trial_id: str = "baseline",
) -> ValidationReport:
    """Select on development folds and score the untouched final test once."""

    definition = spec or ValidationSpec()
    if not scores:
        raise ValueError("at least one trial score series is required")
    arrays = {str(key): np.asarray(value, dtype=float) for key, value in scores.items()}
    lengths = {len(value) for value in arrays.values()}
    if len(lengths) != 1 or not np.isfinite(np.concatenate(list(arrays.values()))).all():
        raise ValueError("trial scores must have equal finite lengths")
    n_samples = lengths.pop()
    folds = build_walk_forward_splits(n_samples, definition)
    final_indices = np.arange(n_samples - definition.final_test_size, n_samples)
    trial_rows: list[ValidationTrial] = []
    validation_means: dict[str, float] = {}
    warnings: list[str] = []
    for trial_id in sorted(arrays):
        values = arrays[trial_id]
        fold_scores = tuple(float(values[list(fold.validation_indices)].mean()) for fold in folds)
        validation_mean = float(np.mean(fold_scores))
        validation_means[trial_id] = validation_mean
        trial_rows.append(ValidationTrial(trial_id, dict((parameters or {}).get(trial_id, {})), fold_scores, validation_mean, None, False, None))
    if baseline_trial_id not in arrays:
        warnings.append("baseline_trial_missing")
    selected_id = max(validation_means, key=lambda key: (validation_means[key], key))
    selected_mean = validation_means[selected_id]
    baseline_mean = validation_means.get(baseline_trial_id)
    final_score = float(arrays[selected_id][final_indices].mean())
    final_scores = {trial_id: float(values[final_indices].mean()) for trial_id, values in arrays.items()}
    trial_rows = [
        ValidationTrial(
            row.trial_id,
            row.parameters,
            row.validation_scores,
            row.validation_mean,
            final_scores[row.trial_id],
            row.trial_id == selected_id,
            None if row.trial_id == selected_id else "not_selected_on_development_folds",
        )
        for row in trial_rows
    ]
    selected_validation = arrays[selected_id][np.concatenate([np.asarray(fold.validation_indices) for fold in folds])]
    uncertainty = _block_bootstrap(selected_validation, definition)
    regime_results = _group_results(arrays[selected_id], regime_labels, folds)
    subgroup_results = _group_results(arrays[selected_id], subgroup_labels, folds)
    independent_count = _effective_trial_count(arrays)
    deflated = _deflated_sharpe(selected_validation, independent_count)
    pbo = _pbo_probability(validation_means, final_scores)
    false_discovery = _false_discovery_rate(validation_means, baseline_mean)
    stable = bool(
        baseline_mean is not None
        and selected_mean > baseline_mean
        and float(uncertainty.get("lower_5", float("-inf"))) > 0
        and len(folds) >= 2
    )
    if baseline_mean is None:
        stable = False
    if not stable:
        warnings.append("promotion_evidence_insufficient_or_unstable")
    promotion = bool(stable and final_score >= baseline_mean)
    return ValidationReport(
        VALIDATION_PROTOCOL_VERSION,
        definition,
        folds,
        tuple(trial_rows),
        selected_id,
        final_score,
        False,
        uncertainty,
        regime_results,
        subgroup_results,
        independent_count,
        deflated,
        pbo,
        false_discovery,
        promotion,
        tuple(dict.fromkeys(warnings)),
    )


def report_fingerprint(report: ValidationReport) -> str:
    """Hash split definition and evidence for immutable audit references."""

    payload = asdict(report)
    if isinstance(payload, dict):
        payload.pop("report_fingerprint", None)
    return _sha256(_canonical(payload))


def _block_bootstrap(values: np.ndarray, spec: ValidationSpec) -> dict[str, object]:
    if len(values) < 2:
        return {"status": "unavailable", "observations": int(len(values))}
    rng = np.random.default_rng(spec.seed)
    block = min(spec.block_size, len(values))
    samples: list[float] = []
    for _ in range(spec.bootstrap_repetitions):
        indices: list[int] = []
        while len(indices) < len(values):
            start = int(rng.integers(0, len(values) - block + 1))
            indices.extend(range(start, start + block))
        samples.append(float(values[indices[: len(values)]].mean()))
    distribution = np.asarray(samples, dtype=float)
    return {
        "status": "available",
        "observations": int(len(values)),
        "repetitions": int(spec.bootstrap_repetitions),
        "block_size": int(block),
        "seed": int(spec.seed),
        "mean": float(distribution.mean()),
        "lower_5": float(np.quantile(distribution, 0.05)),
        "upper_95": float(np.quantile(distribution, 0.95)),
    }


def _group_results(values: np.ndarray, labels: Sequence[str] | None, folds: tuple[ValidationFold, ...]) -> dict[str, dict[str, object]]:
    if labels is None or len(labels) != len(values):
        return {}
    indices = np.concatenate([np.asarray(fold.validation_indices) for fold in folds])
    result: dict[str, dict[str, object]] = {}
    for label in sorted({str(labels[index]) for index in indices}):
        selected = [index for index in indices if str(labels[index]) == label]
        result[label] = {"observations": len(selected), "mean_score": float(values[selected].mean()) if selected else None}
    return result


def _effective_trial_count(scores: Mapping[str, np.ndarray]) -> float:
    if len(scores) <= 1:
        return 1.0
    matrix = np.vstack([values for values in scores.values()])
    correlations = np.corrcoef(matrix)
    upper = correlations[np.triu_indices_from(correlations, 1)]
    mean_abs = float(np.nanmean(np.abs(upper))) if len(upper) else 0.0
    return float(max(1.0, len(scores) / max(1.0, 1.0 + (len(scores) - 1) * mean_abs)))


def _deflated_sharpe(values: np.ndarray, independent_trials: float) -> float | None:
    if len(values) < 2 or float(values.std(ddof=1)) <= 0:
        return None
    sharpe = float(values.mean() / values.std(ddof=1) * math.sqrt(252.0))
    penalty = math.sqrt(max(0.0, 2.0 * math.log(max(1.0, independent_trials))))
    return sharpe - penalty


def _pbo_probability(validation: Mapping[str, float], final: Mapping[str, float]) -> float:
    if len(validation) < 2:
        return 0.0
    validation_order = sorted(validation, key=validation.get, reverse=True)
    final_order = sorted(final, key=final.get, reverse=True)
    discordant = sum(left != right for left, right in zip(validation_order, final_order))
    return float(discordant / len(validation_order))


def _false_discovery_rate(validation: Mapping[str, float], baseline: float | None) -> float | None:
    if baseline is None or not validation:
        return None
    positives = sum(value > baseline for value in validation.values())
    return float(max(0, positives - 1) / max(1, positives))


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "VALIDATION_PROTOCOL_VERSION",
    "ValidationFold",
    "ValidationReport",
    "ValidationSpec",
    "ValidationTrial",
    "build_walk_forward_splits",
    "evaluate_trials",
    "report_fingerprint",
]
