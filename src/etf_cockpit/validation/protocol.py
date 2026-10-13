"""Deterministic walk-forward, purge/embargo and trial evidence.

This module is a validation protocol, not a model trainer.  Callers provide
per-observation scores for each trial; the protocol owns the split boundary,
selection, uncertainty and promotion evidence.  The final-test indices are
never consulted while selecting a trial.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
from itertools import combinations
import json
import math
from statistics import NormalDist
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
    periods_per_year: float | None = None

    def __post_init__(self) -> None:
        positive = ("n_splits", "test_size", "horizon", "final_test_size", "bootstrap_repetitions", "block_size")
        for field in positive:
            if int(getattr(self, field)) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.embargo < 0:
            raise ValueError("embargo must be non-negative")
        if self.train_size is not None and int(self.train_size) <= 0:
            raise ValueError("train_size must be positive when supplied")
        if self.periods_per_year is not None and (
            not math.isfinite(float(self.periods_per_year)) or float(self.periods_per_year) <= 0
        ):
            raise ValueError("periods_per_year must be positive and finite when supplied")

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
    total_trial_count: int = 0
    holdout_status: str = "unavailable"

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
            "total_trial_count": self.total_trial_count,
            "holdout_status": self.holdout_status,
            "report_fingerprint": report_fingerprint(self),
        }


def build_walk_forward_splits(
    n_samples: int,
    spec: ValidationSpec | None = None,
    *,
    reserve_final_test: bool = True,
    strict_label_purge: bool = True,
) -> tuple[ValidationFold, ...]:
    """Return non-overlapping temporal folds with label purge and embargo.

    Labels are assumed to span t+1..t+horizon. ``strict_label_purge`` (default,
    used by inference) purges ``horizon`` rows before validation, keeps a
    ``horizon`` gap before the final test and requires two training rows per
    fold. ``strict_label_purge=False`` keeps the original ``horizon - 1`` purge
    and unpadded final tail for non-inference callers (the tuning optimiser).
    """

    definition = spec or ValidationSpec()
    n_samples = int(n_samples)
    final_gap = 0
    if reserve_final_test:
        final_gap = definition.final_test_size + (definition.horizon if strict_label_purge else 0)
    purge_width = definition.horizon if strict_label_purge else definition.horizon - 1
    min_train = 2 if strict_label_purge else 0
    development_end = n_samples - final_gap
    required = (
        final_gap
        + definition.n_splits * definition.test_size
        + definition.horizon
        + definition.embargo
        + min_train
    )
    if n_samples < required:
        raise ValueError(
            f"at least {required} observations are required for this validation spec"
            + (", " if strict_label_purge else "")
            + ("including two post-purge training observations" if strict_label_purge else "")
        )
    folds: list[ValidationFold] = []
    for fold in range(definition.n_splits):
        validation_start = development_end - (definition.n_splits - fold) * definition.test_size
        validation_end = validation_start + definition.test_size
        purge_end = max(0, validation_start - purge_width)
        embargo_start = validation_end
        embargo_end = min(development_end, validation_end + definition.embargo)
        train_start = 0 if definition.expanding or definition.train_size is None else max(0, purge_end - definition.train_size)
        train_indices = tuple(range(train_start, purge_end))
        if len(train_indices) < min_train:
            raise ValueError("each fold requires at least two training observations after label purge")
        purged = tuple(range(purge_end, validation_start))
        embargoed = tuple(range(embargo_start, embargo_end))
        folds.append(ValidationFold(fold, train_indices, tuple(range(validation_start, validation_end)), purged, embargoed))
    return tuple(folds)


def evaluate_trials(
    scores: Mapping[str, Sequence[float]],
    *,
    registry=None,
    run_id: str | None = None,
    **options,
) -> ValidationReport:
    """Evaluate development evidence; durable registry evidence authorizes inference.

    Legacy caller-supplied history and holdout booleans are not authority. Use
    the application facade with a registered run to retain the complete family
    and atomically consume a holdout before scoring it.
    """
    for name in ("holdout_use_recorded", "holdout_reused", "prior_trial_scores", "external_trial_count"):
        options.pop(name, None)
    if any(name.startswith("_") for name in options):
        raise TypeError("internal evaluation evidence cannot be supplied by callers")
    if registry is not None:
        if not run_id:
            raise ValueError("registered validation requires run_id")
        return registry.evaluate_validation_trials(run_id, scores, **options)
    return _evaluate_trials(scores, **options)


def _evaluate_trials(
    scores: Mapping[str, Sequence[float]],
    *,
    spec: ValidationSpec | None = None,
    parameters: Mapping[str, Mapping[str, object]] | None = None,
    regime_labels: Sequence[str] | None = None,
    subgroup_labels: Sequence[str] | None = None,
    baseline_trial_id: str = "baseline",
    frozen_candidate_id: str | None = None,
    predeclared_comparator_ids: Sequence[str] = (),
    holdout_id: str | None = None,
    holdout_use_recorded: bool = False,
    holdout_reused: bool = False,
    date_labels: Sequence[object] | None = None,
    prior_trial_scores: Mapping[str, Sequence[float]] | None = None,
    external_trial_count: int = 0,
    _family_verified: bool = False,
    _family_reason: str = "durable_trial_family_missing",
    _evaluation_id: str | None = None,
) -> ValidationReport:
    """Select on development folds and score only an audited frozen holdout family.

    ``date_labels`` groups cross-sectional rows into chronological date-level
    observations before splitting or inference. Prior trial series may only be
    supplied when their date alignment and data identity have been verified by
    the caller. ``external_trial_count`` conservatively counts additional
    ledger entries whose paired series are unavailable; such entries make the
    FDR metric unavailable rather than silently shrinking its family.
    """

    definition = spec or ValidationSpec()
    if not scores:
        raise ValueError("at least one trial score series is required")
    if isinstance(external_trial_count, bool) or int(external_trial_count) < 0:
        raise ValueError("external_trial_count must be a non-negative integer")
    raw_arrays = {str(key): np.asarray(value, dtype=float) for key, value in scores.items()}
    for trial_id, values in raw_arrays.items():
        if values.ndim != 1:
            raise ValueError(f"trial scores for {trial_id} must be one-dimensional")
    lengths = {len(value) for value in raw_arrays.values()}
    if len(lengths) != 1 or not np.isfinite(np.concatenate(list(raw_arrays.values()))).all():
        raise ValueError("trial scores must have equal finite lengths")
    raw_n_samples = lengths.pop()
    groups = _date_groups(date_labels, raw_n_samples)
    arrays = _aggregate_by_groups(raw_arrays, groups)
    prior_arrays: dict[str, np.ndarray] = {}
    for trial_id, series in (prior_trial_scores or {}).items():
        values = np.asarray(series, dtype=float)
        if values.ndim != 1 or len(values) != raw_n_samples or not np.isfinite(values).all():
            raise ValueError(f"prior trial scores for {trial_id} are not aligned finite one-dimensional series")
        prior_arrays[f"prior:{trial_id}"] = _aggregate_by_groups({"series": values}, groups)["series"]
    if set(arrays).intersection(prior_arrays):
        raise ValueError("current and prior trial identifiers must be distinct")
    reserve_final = not holdout_reused
    n_samples = len(next(iter(arrays.values())))
    folds = build_walk_forward_splits(n_samples, definition, reserve_final_test=reserve_final)
    validation_indices = np.concatenate([np.asarray(fold.validation_indices, dtype=int) for fold in folds])
    if reserve_final:
        final_start = n_samples - definition.final_test_size
        final_indices = np.arange(final_start, n_samples)
    else:
        final_indices = np.asarray([], dtype=int)
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
    comparator_ids = tuple(dict.fromkeys(str(item) for item in predeclared_comparator_ids))
    requested_holdout_ids = set(comparator_ids)
    if frozen_candidate_id is not None:
        requested_holdout_ids.add(str(frozen_candidate_id))
    missing_holdout_ids = sorted(requested_holdout_ids.difference(arrays))
    holdout_ready = bool(
        reserve_final
        and holdout_id
        and holdout_use_recorded
        and not holdout_reused
        and frozen_candidate_id in arrays
        and bool(comparator_ids)
        and not missing_holdout_ids
        and str(frozen_candidate_id) not in comparator_ids
    )
    final_scores: dict[str, float | None] = {trial_id: None for trial_id in arrays}
    if holdout_ready:
        for trial_id in requested_holdout_ids:
            final_scores[trial_id] = float(math.fsum(arrays[trial_id][final_indices]) / len(final_indices))
        holdout_status = "scored"
    elif holdout_reused:
        holdout_status = "development_reuse"
        warnings.append("holdout_reused_as_development")
    elif requested_holdout_ids and missing_holdout_ids:
        holdout_status = "unavailable"
        warnings.append("holdout_predeclaration_missing_trial")
    elif requested_holdout_ids and not holdout_id:
        holdout_status = "unavailable"
        warnings.append("holdout_identity_missing")
    elif requested_holdout_ids and not holdout_use_recorded:
        holdout_status = "unavailable"
        warnings.append("holdout_audit_missing")
    elif requested_holdout_ids and (not comparator_ids or str(frozen_candidate_id) in comparator_ids):
        holdout_status = "unavailable"
        warnings.append("holdout_candidate_or_comparator_declaration_invalid")
    else:
        holdout_status = "sealed_not_accessed"
        if reserve_final:
            warnings.append("holdout_not_authorized")
    if holdout_reused:
        final_scores = {trial_id: None for trial_id in arrays}
    final_score = final_scores.get(str(frozen_candidate_id))
    baseline_final_score = final_scores.get(baseline_trial_id)
    if baseline_final_score is None:
        warnings.append("baseline_final_score_unavailable")
    trial_rows = [
        ValidationTrial(
            row.trial_id,
            row.parameters,
            row.validation_scores,
            row.validation_mean,
            final_scores[row.trial_id],
            row.trial_id == selected_id,
            (
                None
                if row.trial_id == selected_id
                else "not_selected_on_development_folds"
                if final_scores[row.trial_id] is not None
                else "not_predeclared_for_holdout"
            ),
        )
        for row in trial_rows
    ]
    selected_validation = arrays[selected_id][validation_indices]
    baseline_validation = arrays.get(baseline_trial_id)
    if baseline_validation is None:
        uncertainty = {"status": "unavailable", "reason": "baseline_trial_missing", "observations": 0}
    else:
        uncertainty = _paired_block_bootstrap(
            selected_validation - baseline_validation[validation_indices],
            definition,
            paired_with=baseline_trial_id,
        )
    regime_results = _group_results(arrays[selected_id], _group_labels(regime_labels, groups), folds)
    subgroup_results = _group_results(arrays[selected_id], _group_labels(subgroup_labels, groups), folds)
    family_arrays = {**arrays, **prior_arrays}
    development_family = {trial_id: values[validation_indices] for trial_id, values in family_arrays.items()}
    total_trial_count = len(arrays) + len(prior_arrays) + int(external_trial_count)
    # No correlation discount without independently verified trial-dependence evidence.
    independent_count = float(total_trial_count)
    trial_sharpes = [_periodic_sharpe(values) for values in development_family.values()]
    deflated = (
        _deflated_sharpe(selected_validation, independent_count, definition.periods_per_year, trial_sharpes)
        if _family_verified else None
    )
    if deflated is None:
        warnings.append("dsr_unavailable_requires_frequency_sample_and_multiple_trials")
    pbo, pbo_reason = _pbo_probability(development_family) if _family_verified else (None, _family_reason)
    if pbo is None:
        warnings.append(f"pbo_unavailable:{pbo_reason or 'insufficient_evidence'}")
    p_values: list[float] = []
    if _family_verified and baseline_validation is not None and total_trial_count >= 2 and external_trial_count == 0:
        for trial_id, values in family_arrays.items():
            if trial_id == baseline_trial_id or trial_id == f"prior:{baseline_trial_id}":
                continue
            paired = _paired_block_bootstrap(
                values[validation_indices] - baseline_validation[validation_indices],
                definition,
                paired_with=baseline_trial_id,
            )
            p_value = paired.get("p_value")
            if paired.get("status") != "available" or not isinstance(p_value, (int, float)):
                p_values = []
                break
            p_values.append(float(p_value))
    else:
        p_values = []
    false_discovery = _false_discovery_rate(p_values) if p_values else None
    if false_discovery is None:
        reason = "prior_trial_p_values_unavailable" if external_trial_count else "insufficient_paired_trials_or_dates"
        warnings.append(f"fdr_unavailable:{reason}")
    if not _family_verified:
        warnings.append(f"trial_family_unavailable:{_family_reason}")
    uncertainty["trial_family_status"] = "available" if _family_verified else "unavailable"
    uncertainty["trial_family_reason"] = None if _family_verified else _family_reason
    uncertainty["evaluation_id"] = _evaluation_id
    uncertainty["effective_dates"] = int(len(validation_indices))
    uncertainty["total_trial_count"] = total_trial_count
    uncertainty["effective_independent_trial_count"] = independent_count
    uncertainty["false_discovery_rate_method"] = "Benjamini-Yekutieli minimum adjusted q-value" if false_discovery is not None else None
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
    promotion = bool(
        stable
        and _family_verified
        and holdout_status == "scored"
        and frozen_candidate_id == selected_id
        and baseline_final_score is not None
        and final_score is not None
        and final_score >= baseline_final_score
    )
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
        total_trial_count,
        holdout_status,
    )


def report_fingerprint(report: ValidationReport) -> str:
    """Hash split definition and evidence for immutable audit references."""

    payload = asdict(report)
    if isinstance(payload, dict):
        payload.pop("report_fingerprint", None)
    return _sha256(_canonical(payload))


def _date_groups(labels: Sequence[object] | None, n_samples: int) -> tuple[tuple[int, ...], ...]:
    """Chronological whole-date clusters; reject ambiguous/missing date identities."""
    if labels is None:
        return tuple((index,) for index in range(n_samples))
    if len(labels) != n_samples:
        raise ValueError("date labels must align with score observations")
    grouped: dict[object, list[int]] = {}
    for index, label in enumerate(labels):
        if label is None or str(label) in {"NaT", "nan", ""}:
            raise ValueError("date labels must be non-missing chronological identities")
        if isinstance(label, (str, date, np.datetime64)):
            try:
                label = datetime.fromisoformat(str(label).replace("Z", "+00:00")).date()
            except ValueError as exc:
                raise ValueError("date labels must use unambiguous ISO dates") from exc
        elif isinstance(label, (int, float, np.integer, np.floating)):
            if not math.isfinite(float(label)) or isinstance(label, bool):
                raise ValueError("date labels must be finite chronological identities")
        else:
            raise ValueError("date labels must be ISO dates or numeric chronological identities")
        try:
            grouped.setdefault(label, []).append(index)
        except TypeError as exc:
            raise ValueError("date labels must be hashable chronological identities") from exc
    try:
        ordered = sorted(grouped)
    except TypeError as exc:
        raise ValueError("date labels must have a consistent chronological ordering") from exc
    return tuple(tuple(grouped[label]) for label in ordered)


def _aggregate_by_groups(scores: Mapping[str, np.ndarray], groups: Sequence[Sequence[int]]) -> dict[str, np.ndarray]:
    return {trial: np.asarray([values[list(group)].mean() for group in groups]) for trial, values in scores.items()}


def _group_labels(labels: Sequence[str] | None, groups: Sequence[Sequence[int]]) -> list[str] | None:
    if labels is None or len(labels) != sum(map(len, groups)):
        return None
    # Mixed cross-sectional membership cannot be attributed to a date-level score.
    if any(len({str(labels[index]) for index in group}) != 1 for group in groups):
        return None
    return [str(labels[group[0]]) for group in groups]


def _paired_block_bootstrap(values: np.ndarray, spec: ValidationSpec, *, paired_with: str) -> dict[str, object]:
    """Moving-block paired mean interval and centered-null one-sided bootstrap test."""
    n = len(values)
    if n < 2 or not np.isfinite(values).all():
        return {"status": "unavailable", "reason": "at_least_two_finite_paired_dates_required", "observations": n}
    rng = np.random.default_rng(spec.seed)
    # At least two blocks must fit, including in a short inference window.
    block = min(spec.block_size, max(1, n // 2))
    draws = np.empty(spec.bootstrap_repetitions)
    for repetition in range(spec.bootstrap_repetitions):
        starts = rng.integers(0, n - block + 1, size=math.ceil(n / block))
        indices = (starts[:, None] + np.arange(block)).ravel()[:n]
        draws[repetition] = values[indices].mean()
    observed = float(values.mean())
    null_draws = draws - observed
    return {
        "status": "available", "observations": n, "paired_with": paired_with,
        "repetitions": spec.bootstrap_repetitions, "block_size": block, "seed": spec.seed,
        "mean": observed, "lower_5": float(np.quantile(draws, 0.05)),
        "upper_95": float(np.quantile(draws, 0.95)),
        "p_value": float((1 + np.count_nonzero(null_draws >= observed)) / (len(draws) + 1)),
        "method": "paired moving-block bootstrap, centered null, one-sided improvement",
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


def _periodic_sharpe(values: np.ndarray) -> float | None:
    if len(values) < 3 or not np.isfinite(values).all():
        return None
    deviation = float(values.std(ddof=1))
    return float(values.mean() / deviation) if deviation > 0 else None


def _deflated_sharpe(
    values: np.ndarray,
    independent_trials: float,
    periods_per_year: float | None = None,
    trial_sharpes: Sequence[float | None] | None = None,
) -> float | None:
    """Bailey & Lopez de Prado (2014), DSR equations (1), (3) and (4).

    Expected maximum uses empirical variance across trial Sharpe estimates.
    PSR's estimator variance uses selected-return skew and Pearson kurtosis.
    Every estimate remains in periodic units (annualization cancels).
    """
    sharpe = _periodic_sharpe(values)
    if (sharpe is None or independent_trials <= 1 or periods_per_year is None
            or not math.isfinite(periods_per_year) or periods_per_year <= 0
            or trial_sharpes is None or len(trial_sharpes) < 2
            or any(value is None or not math.isfinite(value) for value in trial_sharpes)):
        return None
    centered = values - values.mean()
    population_std = float(np.sqrt(np.mean(centered**2)))
    skew = float(np.mean((centered / population_std)**3))
    kurtosis = float(np.mean((centered / population_std)**4))
    estimator_variance = (1 - skew * sharpe + (kurtosis - 1) * sharpe**2 / 4) / (len(values) - 1)
    if estimator_variance <= 0 or not math.isfinite(estimator_variance):
        return None
    across_trial_variance = float(np.var(trial_sharpes, ddof=1))
    gamma = 0.5772156649015329
    normal = NormalDist()
    expected_maximum = math.sqrt(across_trial_variance) * (
        (1 - gamma) * normal.inv_cdf(1 - 1 / independent_trials)
        + gamma * normal.inv_cdf(1 - 1 / (independent_trials * math.e))
    )
    return normal.cdf((sharpe - expected_maximum) / math.sqrt(estimator_variance))


def _pbo_probability(scores: Mapping[str, np.ndarray]) -> tuple[float | None, str | None]:
    """CSCV (Bailey et al., 2017): complementary contiguous splits, OOS rank logit.

    The supplied observations are scores, so the selection statistic is their
    mean, as in the walk-forward selector. Equal OOS scores receive midranks.
    """
    if len(scores) < 2:
        return None, "multiple_trials_required"
    rows = [np.asarray(values, dtype=float) for _, values in sorted(scores.items())]
    if any(values.ndim != 1 or len(values) < 4 or not np.isfinite(values).all() for values in rows):
        return None, "at_least_four_finite_dates_required"
    if len({len(values) for values in rows}) != 1:
        return None, "trial_dates_not_aligned"
    matrix = np.vstack(rows)
    n_dates = matrix.shape[1]
    partitions = min(10, n_dates - n_dates % 2)
    blocks = np.array_split(np.arange(n_dates), partitions)
    losses = []
    for chosen in combinations(range(partitions), partitions // 2):
        train = np.concatenate([blocks[index] for index in chosen])
        test = np.concatenate([blocks[index] for index in range(partitions) if index not in chosen])
        in_sample = matrix[:, train].mean(axis=1)
        # Match the deterministic ID tie break of development selection.
        winner = len(rows) - 1 - int(np.argmax(in_sample[::-1]))
        out_sample = matrix[:, test].mean(axis=1)
        performance = out_sample[winner]
        rank = np.count_nonzero(out_sample < performance) + (np.count_nonzero(out_sample == performance) + 1) / 2
        relative_rank = rank / (len(rows) + 1)
        losses.append(relative_rank <= 0.5)
    return float(np.mean(losses)), None


def _false_discovery_rate(p_values: Sequence[float]) -> float | None:
    """Benjamini-Yekutieli (2001) step-up minimum adjusted q-value."""
    values = np.asarray(p_values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
        return None
    count = len(values)
    harmonic = sum(1 / index for index in range(1, count + 1))
    return float(min(1.0, np.min(np.sort(values) * count * harmonic / np.arange(1, count + 1))))


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
