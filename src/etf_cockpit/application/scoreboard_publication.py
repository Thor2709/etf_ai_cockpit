"""Scoreboard publication: classification currency, scoreboard writing and score-history failure records (application; ADR-0002)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Protocol

import numpy as np
import pandas as pd

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.classification import classification_score_state
from contextlib import contextmanager
from etf_cockpit.data.trust_artifacts import refresh_static_trust_artifacts as refresh_static_trust_artifacts, write_trust_artifacts_for_scores
from etf_cockpit.features.regime import build_market_regime, write_market_regime
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.models.calibration import (
    evaluate_forecast_calibration,
    load_forecast_history,
    write_forecast_calibration,
)
from etf_cockpit.application.snapshot_builder import CockpitSnapshot
from etf_cockpit.signals.simple_scores import (
    build_simple_instrument_scores as build_simple_instrument_scores,
    load_latest_candidate_report,
    simple_scoreboard_frame,
    write_simple_scoreboard,
)


SCOREBOARD_PUBLICATION_BINDING_ENTITY_TYPE = "scoreboard_publication_binding"


class ScoreboardPublicationBindingError(RuntimeError):
    """The scoreboard was published but its exact score-history binding was not recorded."""


def _signal_classification_is_current(signal: object, *, root: Path) -> bool:
    instrument_id = str(getattr(signal, "etf_id", "") or "").strip()
    if not instrument_id:
        return False
    metrics = getattr(signal, "supporting_metrics", {})
    stored_token = (
        str(metrics.get("classification_invalidation_hash") or "unavailable")
        if isinstance(metrics, dict)
        else "unavailable"
    )
    state = classification_score_state(root, instrument_id)
    if str(state.get("status")) == "unavailable":
        return False
    current_token = str(state.get("invalidation_token") or "unavailable")
    token_is_bound = stored_token not in {"", "none", "nan", "unavailable"}
    return not (
        (token_is_bound and stored_token != current_token)
        or (bool(state.get("invalidated_score_keys")) and stored_token != current_token)
    )


class ScoreboardSession(Protocol):
    def _record_score_history_failure(self, exc: Exception, scoreboard_path: Path) -> None:
        ...
    @contextmanager
    def activity_publication(self, expected_action_id: str | None = None):
        ...
    score_history_warning: str | None
    snapshot: CockpitSnapshot


def _write_current_scoreboard(session: ScoreboardSession) -> Path:
    candidate_report, _ = load_latest_candidate_report()
    reference_context = context_from_snapshot(
        session.snapshot,
        purpose="comparison",
        analysis_id=f"scoreboard:{getattr(session.snapshot, 'universe_revision', 'unknown')}",
    )
    regime = build_market_regime(
        session.snapshot.prices,
        candidate_report,
        benchmark_id=reference_context.benchmark_data_id,
        benchmark_reference=reference_context.projection,
        benchmark_registry=reference_context.registry,
    )
    with session.activity_publication():
        write_market_regime(regime)
    calibration = evaluate_forecast_calibration(load_forecast_history(), session.snapshot.prices)
    with session.activity_publication():
        write_forecast_calibration(calibration)
    from etf_cockpit.application.score_views import snapshot_scores

    scores = snapshot_scores(session.snapshot)
    scoreboard_frame = simple_scoreboard_frame(scores)
    with session.activity_publication():
        path = write_simple_scoreboard(scores)
    try:
        with session.activity_publication():
            paths = write_trust_artifacts_for_scores(
                session.snapshot.config,
                scores,
                scoreboard_frame,
                prices=session.snapshot.prices,
            )
            history_path = paths.get("score_history") if isinstance(paths, dict) else None
            try:
                if not isinstance(history_path, Path) or not history_path.is_file():
                    raise RuntimeError("Score history publication path is unavailable.")
                _record_scoreboard_publication_binding(path, history_path, scoreboard_frame)
            except Exception as binding_exc:
                raise ScoreboardPublicationBindingError(str(binding_exc)) from binding_exc
    except Exception as exc:
        # The scoreboard itself is published; trust artifacts or their exact
        # publication binding are missing. Keep that absence explicit.
        session._record_score_history_failure(exc, path)
    else:
        session.score_history_warning = None
    return path


def _record_scoreboard_publication_binding(
    scoreboard_path: Path,
    history_path: Path,
    expected_scoreboard: pd.DataFrame,
) -> dict[str, Any]:
    """Bind exact scoreboard bytes to the score-history run that published them."""

    scoreboard_bytes = scoreboard_path.read_bytes()
    actual_scoreboard = pd.read_parquet(BytesIO(scoreboard_bytes))
    try:
        pd.testing.assert_frame_equal(
            _normalise_scoreboard_values(expected_scoreboard),
            _normalise_scoreboard_values(actual_scoreboard),
            check_dtype=False,
            check_exact=True,
        )
    except AssertionError as exc:
        raise RuntimeError("Scoreboard changed while its score-history publication was being recorded.") from exc
    history = pd.read_parquet(history_path)
    required = {"run_id", "run_completed_at", "snapshot_hash"}
    if history.empty or not required.issubset(history.columns):
        raise ValueError("Score history has no verifiable publication identity.")
    completed = pd.to_datetime(history["run_completed_at"], utc=True, errors="coerce")
    if completed.isna().any():
        raise ValueError("Score history contains an unverifiable completion time.")
    newest = completed.max()
    latest = history.loc[completed.eq(newest)]
    run_ids = {str(value).strip() for value in latest["run_id"] if pd.notna(value)}
    hashes = {str(value).strip().lower() for value in latest["snapshot_hash"] if pd.notna(value)}
    if len(run_ids) != 1 or len(hashes) != 1:
        raise ValueError("Latest score history publication identity is ambiguous.")
    run_id = next(iter(run_ids))
    score_snapshot_hash = next(iter(hashes))
    if not run_id or len(score_snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in score_snapshot_hash):
        raise ValueError("Latest score history snapshot hash is invalid.")

    root = scoreboard_path.resolve().parents[2]
    score_completed_at = newest.to_pydatetime().astimezone(timezone.utc)
    published_at = max(datetime.now(timezone.utc), score_completed_at)
    scoreboard_digest = hashlib.sha256(scoreboard_bytes).hexdigest()
    payload = {
        "schema_version": "scoreboard_publication_binding.v1",
        "run_id": run_id,
        "score_snapshot_hash": score_snapshot_hash,
        "score_completed_at": score_completed_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "known_at": published_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "scoreboard_sha256": scoreboard_digest,
        "execution_allowed": False,
    }
    identity = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if hashlib.sha256(scoreboard_path.read_bytes()).hexdigest() != scoreboard_digest:
        raise RuntimeError("Scoreboard changed while its publication binding was being recorded.")
    with TransactionalStore(root) as store:
        store.put_many(
            [(SCOREBOARD_PUBLICATION_BINDING_ENTITY_TYPE, identity, payload)],
            immutable=True,
        )
    return payload


def _normalise_scoreboard_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert Arrow-backed nested arrays and NumPy scalars to comparable Python values."""

    normalised = frame.reset_index(drop=True).copy()
    for column in normalised.columns:
        normalised[column] = normalised[column].map(_normalise_nested_value)
    return normalised


def _normalise_nested_value(value: object) -> object:
    if isinstance(value, np.ndarray):
        return _normalise_nested_value(value.item() if value.ndim == 0 else value.tolist())
    if isinstance(value, np.generic):
        return _normalise_nested_value(value.item())
    if isinstance(value, Mapping):
        return {key: _normalise_nested_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_nested_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalise_nested_value(item) for item in value)
    return value
