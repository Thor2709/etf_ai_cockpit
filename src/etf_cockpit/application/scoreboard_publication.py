"""Scoreboard publication: classification currency, scoreboard writing and score-history failure records (application; ADR-0002)."""

from __future__ import annotations

from pathlib import Path

from etf_cockpit.data.classification import classification_score_state
from contextlib import contextmanager
from typing import Protocol
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
    build_simple_instrument_scores,
    load_latest_candidate_report,
    simple_scoreboard_frame,
    write_simple_scoreboard,
)


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
    with session.activity_publication():
        path = write_simple_scoreboard(scores)
    try:
        with session.activity_publication():
            write_trust_artifacts_for_scores(
                session.snapshot.config,
                scores,
                simple_scoreboard_frame(scores),
                prices=session.snapshot.prices,
            )
    except Exception as exc:
        # The scoreboard itself is published; only the trust artifacts
        # (score history, components, evidence ledger, drivers) are missing.
        # Keep that absence explicit instead of looking like a first run.
        session._record_score_history_failure(exc, path)
    else:
        session.score_history_warning = None
    return path
