"""Optional LightGBM cross-sectional ranker on the PIT panel (ISSUE-0190, INT-08).

Research and shadow only: nothing here registers a model, writes a file,
promotes a ranker or grants execution authority.  ``lightgbm`` is imported
lazily; without it ``fit`` reports ``unavailable``.  A panel that misses the
evidence minima reports ``insufficient_evidence`` and returns no artefact.
Training rows are only the rows of one ``date_grouped_folds`` fold, indexed on
``canonical_panel_rows``.  Folds are built on the full panel; rows with a
non-finite feature (or, for training, a non-finite label) are dropped from each
fold afterwards, never imputed, and ``score`` never returns a number for them.
A training label must be available at the selected horizon's own
``label_available_at_<h>`` by the fold's validation start.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from importlib.util import find_spec
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from etf_cockpit.analysis.decision.rank_validation import RankerSpec, RankValidationPolicy
from etf_cockpit.features.feature_store import labels_available_by
from etf_cockpit.features.panel import (
    DateGroupedFold,
    PanelContractError,
    canonical_panel_rows,
    date_grouped_folds,
    panel_evidence_inventory,
)
from etf_cockpit.validation.protocol import ValidationSpec


# Preflight minima (D9: module constants, not settings, so the settings revision is unchanged).
MIN_DECISION_DATES = 120
MIN_INSTRUMENTS_PER_DATE = 20
MIN_TRAIN_LABELS_PER_FOLD = 400
MIN_VALIDATION_LABELS_PER_FOLD = 100
MIN_NON_OVERLAPPING_PERIODS = 8
SEED = 42
QUINTILES = 5
RANKER_ID = "gbdt_rank_63"

RankerStatus = Literal["fitted", "unavailable", "insufficient_evidence"]


@dataclass(frozen=True)
class RankerArtefact:
    """LightGBM text model plus the facts needed to audit what it saw."""

    model_text: str
    horizon: int
    feature_ids: tuple[str, ...]
    seed: int
    fold: int
    train_dates: tuple[str, ...]
    validation_dates: tuple[str, ...]
    training_cutoff: str  # latest label_available_at among the training rows
    validation_start: str
    train_rows: int
    execution_allowed: bool = False


@dataclass(frozen=True)
class RankerOutcome:
    status: RankerStatus
    reason: str
    artefact: RankerArtefact | None = None


def is_available() -> bool:
    return find_spec("lightgbm") is not None


def _unusable(status: RankerStatus, reason: str) -> RankerOutcome:
    return RankerOutcome(status, reason, None)


def _leaking_ids(feature_ids: Sequence[str]) -> list[str]:
    return sorted(name for name in feature_ids if name.startswith(("fwd_", "label_")))


def _check_panel(panel: pd.DataFrame, horizon: int, feature_ids: Sequence[str]) -> None:
    """Fail closed on missing columns and on label or forward-return feature ids."""

    leaking = _leaking_ids(feature_ids)
    if leaking:
        raise PanelContractError(f"feature ids may not be labels: {', '.join(leaking)}")
    needed = {
        "decision_time", "instrument_id", "label_available_at", f"label_available_at_{horizon}",
        f"fwd_total_{horizon}", *feature_ids,
    }
    missing = sorted(needed.difference(panel))
    if missing:
        raise PanelContractError(f"panel lacks columns: {', '.join(missing)}")


def _finite_masks(panel: pd.DataFrame, horizon: int, feature_ids: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    """(finite features, finite features and finite numeric label): the one mask for preflight and training."""

    values = panel[list(feature_ids)].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(values).all(axis=1)
    label = pd.to_numeric(panel[f"fwd_total_{horizon}"], errors="coerce").to_numpy(dtype=float)
    return finite, finite & np.isfinite(label)


def _fold_rows(
    canonical: pd.DataFrame, fold: DateGroupedFold, horizon: int, feature_ids: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Training rows, validation rows and the validation start of one fold.

    The start comes from every validation row; rows with a non-finite feature
    (or label, for training) are dropped only afterwards.  A training label also
    needs its own horizon's availability at or before that start.
    """

    finite, trainable = _finite_masks(canonical, horizon, feature_ids)
    train = np.asarray(fold.train_rows, dtype=int)
    valid = np.asarray(fold.validation_rows, dtype=int)
    start = pd.to_datetime(
        canonical["decision_time"].iloc[valid], format="mixed", errors="coerce", utc=True
    ).min()
    available = labels_available_by(canonical[f"label_available_at_{horizon}"].iloc[train], start).to_numpy(dtype=bool)
    return (
        canonical.iloc[train[trainable[train] & available]], canonical.iloc[valid[finite[valid]]], start,
    )


def _preflight(
    inventory: dict[str, object], folds: Sequence[DateGroupedFold], horizon: int,
    train_labels: dict[int, int],
) -> list[str]:
    key = str(horizon)
    failures: list[str] = []
    if int(inventory["decision_dates"]) < MIN_DECISION_DATES:
        failures.append(f"decision_dates {inventory['decision_dates']} < {MIN_DECISION_DATES}")
    per_date = inventory["instruments_per_date"]
    if not per_date or min(per_date.values()) < MIN_INSTRUMENTS_PER_DATE:
        failures.append(f"instruments_per_date minimum < {MIN_INSTRUMENTS_PER_DATE}")
    for fold in folds:
        counts = inventory["matured_labels_by_fold"].get(fold.fold, {}).get(key, {})
        if train_labels[fold.fold] < MIN_TRAIN_LABELS_PER_FOLD:
            failures.append(f"fold {fold.fold} train labels < {MIN_TRAIN_LABELS_PER_FOLD}")
        if counts.get("validation", 0) < MIN_VALIDATION_LABELS_PER_FOLD:
            failures.append(f"fold {fold.fold} validation labels < {MIN_VALIDATION_LABELS_PER_FOLD}")
    if inventory["non_overlapping_periods"].get(key, 0) < MIN_NON_OVERLAPPING_PERIODS:
        failures.append(f"non_overlapping_periods < {MIN_NON_OVERLAPPING_PERIODS}")
    if inventory["membership_pit_grade"] != "observed":
        failures.append("membership_pit_grade is not observed")
    return failures


def _prepare(
    panel: pd.DataFrame, spec: ValidationSpec, horizon: int, feature_ids: Sequence[str],
) -> tuple[pd.DataFrame, tuple[DateGroupedFold, ...]] | str:
    """Canonical panel and folds built on the full panel, or the preflight failure text."""

    try:
        _check_panel(panel, horizon, feature_ids)
        folds = date_grouped_folds(panel, spec)
        canonical = canonical_panel_rows(panel)
        canonical.attrs.update(panel.attrs)
        _, trainable = _finite_masks(canonical, horizon, feature_ids)
        label = f"fwd_total_{horizon}"
        counted = canonical.assign(**{label: canonical[label].where(trainable)})
        counted.attrs.update(panel.attrs)
        train_labels = {fold.fold: len(_fold_rows(canonical, fold, horizon, feature_ids)[0]) for fold in folds}
        failures = _preflight(panel_evidence_inventory(counted, folds=folds), folds, horizon, train_labels)
    except (PanelContractError, ValueError) as error:
        return str(error)
    if failures:
        return "; ".join(failures)
    return canonical, folds


def _quintile_target(rows: pd.DataFrame, horizon: int) -> pd.Series:
    """Per-date quintile 0-4 of fwd_total_<h>; rows must be in canonical order."""

    label = pd.to_numeric(rows[f"fwd_total_{horizon}"], errors="coerce")
    date = pd.to_datetime(rows["decision_time"], format="mixed", errors="coerce", utc=True).dt.date
    rank = label.groupby(date).rank(method="first")
    count = label.groupby(date).transform("count")
    return ((rank - 1) * QUINTILES // count).astype("Int64")


def _train(
    rows: pd.DataFrame, validation_start: pd.Timestamp, fold: DateGroupedFold, horizon: int,
    feature_ids: Sequence[str], seed: int,
) -> RankerArtefact:
    import lightgbm as lgb  # lazy: the base install has no lightgbm

    target = _quintile_target(rows, horizon).astype(int)
    day = pd.to_datetime(rows["decision_time"], format="mixed", errors="coerce", utc=True).dt.date
    group = day.groupby(day, sort=False).size().tolist()  # rows are sorted by decision date
    model = lgb.LGBMRanker(
        objective="lambdarank", n_estimators=50, learning_rate=0.05, num_leaves=15,
        min_child_samples=20, subsample=1.0, colsample_bytree=1.0, random_state=seed,
        deterministic=True, force_row_wise=True, n_jobs=1, device_type="cpu", verbose=-1,
    )
    model.fit(rows[list(feature_ids)].to_numpy(dtype=float), target.to_numpy(), group=group)
    cutoff = pd.to_datetime(rows[f"label_available_at_{horizon}"], format="mixed", errors="coerce", utc=True).max()
    return RankerArtefact(
        model_text=model.booster_.model_to_string(), horizon=horizon,
        feature_ids=tuple(feature_ids), seed=seed, fold=fold.fold,
        train_dates=tuple(sorted(set(day.map(str)))), validation_dates=fold.validation_dates,
        training_cutoff=cutoff.isoformat(), validation_start=validation_start.isoformat(),
        train_rows=len(rows),
    )


def fit(
    panel: pd.DataFrame, spec: ValidationSpec, *, horizon: int = 63,
    feature_ids: Sequence[str], seed: int = SEED,
) -> RankerOutcome:
    """Fit on the training rows of the last date-grouped fold; no side effects."""

    if not is_available():
        return _unusable("unavailable", "lightgbm is not installed")
    prepared = _prepare(panel, spec, horizon, feature_ids)
    if isinstance(prepared, str):
        return _unusable("insufficient_evidence", prepared)
    canonical, folds = prepared
    rows, _, start = _fold_rows(canonical, folds[-1], horizon, feature_ids)
    artefact = _train(rows, start, folds[-1], horizon, feature_ids, seed)
    return RankerOutcome("fitted", f"trained on fold {artefact.fold}", artefact)


def score(artefact: RankerArtefact, rows: pd.DataFrame) -> pd.Series:
    """Ordinal scores for rows; NaN, never a number, where a feature is not finite."""

    result = pd.Series(np.nan, index=rows.index, dtype=float)
    if not is_available() or _leaking_ids(artefact.feature_ids):
        return result
    features = rows[list(artefact.feature_ids)].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(features.to_numpy(dtype=float)).all(axis=1)
    if finite.any():
        import lightgbm as lgb

        booster = lgb.Booster(model_str=artefact.model_text)
        result.loc[finite] = booster.predict(features.loc[finite].to_numpy(dtype=float), num_threads=1)
    return result


def walk_forward_scores(
    panel: pd.DataFrame, spec: ValidationSpec, *, horizon: int = 63,
    feature_ids: Sequence[str], seed: int = SEED,
) -> pd.DataFrame:
    """Out-of-sample scores: each fold's validation rows scored by that fold's model.

    Empty when the ranker is unavailable or the preflight fails.
    """

    columns = ["decision_time", "instrument_id", "score", "fold"]
    prepared = _prepare(panel, spec, horizon, feature_ids) if is_available() else None
    if prepared is None or isinstance(prepared, str):
        return pd.DataFrame(columns=columns)
    canonical, folds = prepared
    parts = []
    for fold in folds:
        train, validation, start = _fold_rows(canonical, fold, horizon, feature_ids)
        scores = score(_train(train, start, fold, horizon, feature_ids, seed), validation)
        parts.append(pd.DataFrame({
            "decision_time": validation["decision_time"], "instrument_id": validation["instrument_id"],
            "score": scores, "fold": fold.fold,
        }))
    return pd.concat(parts, ignore_index=True)


def challenger_policy(policy: RankValidationPolicy, version: str = "gbdt-rank-63-v1") -> RankValidationPolicy:
    """Policy copy holding only this ranker, for the existing rank-IC replay.

    The shared policy file is untouched; evidence needs a ``gbdt_rank_63`` column
    built from ``walk_forward_scores``.
    """

    return replace(policy, rankers={RANKER_ID: RankerSpec(version, score_column=RANKER_ID)})
