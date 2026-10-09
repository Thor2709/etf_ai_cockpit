"""One canonical score list per snapshot, shared by every page and the scoreboard publication."""

from __future__ import annotations

import threading

import pandas as pd

from dataclasses import replace
from math import isfinite

from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.core.ui_preferences import missing_data_penalty
from etf_cockpit.data.score_history import latest_sparebank_scores
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores

NEUTRAL_SCORE_10 = 5.0

_LOCK = threading.Lock()
_CACHE: dict[str, object] = {}


def snapshot_scores(snapshot: object, universe_revision: str = "", *, penalise_missing: bool | None = None) -> list[object]:
    """Build the score rows once per snapshot (and universe revision); later callers reuse them.

    With the missing-data penalty on (user preference), every score is pulled toward neutral in
    proportion to its missing evidence; stored scores and history are never changed.
    """

    if snapshot is None:
        return []
    penalise = missing_data_penalty() if penalise_missing is None else bool(penalise_missing)
    revision = str(getattr(snapshot, "universe_revision", "") or universe_revision or "")
    key = f"{revision}:{len(getattr(snapshot, 'signals', ()) or ())}"
    with _LOCK:
        if _CACHE.get("snapshot") is snapshot and _CACHE.get("key") == key:
            return _presented(_CACHE["scores"], penalise)  # type: ignore[arg-type]
        try:
            reference = context_from_snapshot(snapshot, purpose="comparison", analysis_id=f"scores:{revision or 'unknown'}")
        except (AttributeError, TypeError, ValueError):
            reference = None  # scores still build; benchmark-relative fields show as unavailable
        scores = build_simple_instrument_scores(
            getattr(snapshot, "config", None),
            getattr(snapshot, "signals", ()),
            getattr(snapshot, "forecasts", pd.DataFrame()),
            getattr(snapshot, "prices", pd.DataFrame()),
            universe_revision=revision,
            benchmark_data_id=getattr(reference, "benchmark_data_id", None),
            benchmark_reference=getattr(reference, "projection", None),
            benchmark_registry=getattr(reference, "registry", None),
            reference_identity=getattr(reference, "identity", None),
            peer_member_ids=getattr(reference, "peer_member_ids", ()),
            cash_observation_time=getattr(snapshot, "benchmark_reference_decision_time", None),
        )
        _CACHE.update(snapshot=snapshot, key=key, scores=scores)
        return _presented(scores, penalise)


def _presented(scores: list[object], penalise: bool) -> list[object]:
    return [apply_missing_data_penalty(score) for score in scores] if penalise else list(scores)


def score_coverage(score: object) -> float | None:
    """Share of the score's configured evidence that is present (0-1); ``None`` when unknown."""

    if str(getattr(score, "final_label", "") or "").casefold() == "scorecard_owned":
        row = latest_sparebank_scores().get(str(getattr(score, "display_id", "")))
        value = None if row is None else row.get("coverage")
    else:
        value = getattr(score, "score_coverage", None)
    try:
        coverage = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return min(max(coverage, 0.0), 1.0) if isfinite(coverage) else None


def apply_missing_data_penalty(score: object) -> object:
    """Pull a score toward neutral 5 by its missing evidence: 5 + (score - 5) x coverage."""

    raw = getattr(score, "final_score_10", None)
    coverage = score_coverage(score)
    if raw is None or coverage is None:
        return score
    adjusted = round(NEUTRAL_SCORE_10 + (float(raw) - NEUTRAL_SCORE_10) * coverage, 2)
    note = f"Missing-data penalty on: {float(raw):.1f} -> {adjusted:.1f} at {coverage:.0%} evidence coverage."
    reason = f"{getattr(score, 'one_line_reason', '') or ''} {note}".strip()
    return replace(score, final_score_10=adjusted, one_line_reason=reason)
