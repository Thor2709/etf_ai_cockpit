"""One canonical score list per snapshot, shared by every page and the scoreboard publication."""

from __future__ import annotations

import threading

import pandas as pd

from dataclasses import fields, is_dataclass, replace
from math import isfinite

from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.core.ui_preferences import missing_data_penalty
from etf_cockpit.data.score_history import latest_sparebank_scores
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores

NEUTRAL_SCORE_10 = 5.0
INSUFFICIENT_LABEL = "insufficient_evidence"  # equals analysis.decision.gates.INSUFFICIENT_LABEL (kept import-light)

_LOCK = threading.Lock()
_CACHE: dict[str, object] = {}


def snapshot_scores(snapshot: object, universe_revision: str = "", *, penalise_missing: bool | None = None) -> list[object]:
    """Build the score rows once per snapshot (and universe revision); later callers reuse them.

    With the missing-data penalty on (user preference), every score is pulled toward neutral in
    proportion to its missing evidence and the visible rank follows the displayed value; the research
    score is never changed here. Persisting callers use ``published_scores`` (never penalised).
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
        scores = _without_superseded_candidates(scores)
        _CACHE.update(snapshot=snapshot, key=key, scores=scores)
        return _presented(scores, penalise)


def published_scores(snapshot: object, universe_revision: str = "") -> list[object]:
    """The research scores that are stored (scoreboard, history, exports): the penalty is a display annotation only."""

    return snapshot_scores(snapshot, universe_revision, penalise_missing=False)


def _without_superseded_candidates(scores: list[object]) -> list[object]:
    """A stale candidate-report row never duplicates an instrument that is configured and scored."""

    def is_candidate(score: object) -> bool:
        return str(getattr(score, "instrument_key", "")).startswith("candidate:")

    configured = {
        value.upper()
        for score in scores
        if not is_candidate(score)
        for value in (str(getattr(score, "display_id", "") or ""), str(getattr(score, "yahoo_symbol", "") or ""))
        if value
    }
    return [
        score for score in scores
        if not (
            is_candidate(score)
            and (
                str(getattr(score, "display_id", "") or "").upper() in configured
                or str(getattr(score, "yahoo_symbol", "") or "").upper() in configured
            )
        )
    ]


def _presented(scores: list[object], penalise: bool) -> list[object]:
    if not penalise:
        return list(scores)
    return _ranked_by_displayed_score([apply_missing_data_penalty(score) for score in scores])


def _rank_sort_key(score: object) -> tuple[bool, float, str]:
    value = getattr(score, "final_score_10", None)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return (True, 0.0, str(getattr(score, "display_id", "")))
    return (not isfinite(number), -number if isfinite(number) else 0.0, str(getattr(score, "display_id", "")))


def _ranked_by_displayed_score(scores: list[object]) -> list[object]:
    """Visible rank and rank-delta follow the displayed score: the ranked score is the shown score.

    Only rows that already carry a rank (ordinary instruments; native bank rows have none) are re-ranked,
    in the same order the research ranking uses (unavailable last, ties by identifier).
    """

    ranked_rows = [
        score
        for score in scores
        if is_dataclass(score)
        and {"rank", "score_rank"} <= {field.name for field in fields(score)}
        and getattr(score, "rank", None) is not None
    ]
    if not ranked_rows:
        return scores
    new_ranks = {id(score): position for position, score in enumerate(sorted(ranked_rows, key=_rank_sort_key), start=1)}
    result: list[object] = []
    for score in scores:
        position = new_ranks.get(id(score))
        if position is None:
            result.append(score)
            continue
        presented = replace(score, rank=position, score_rank=position)  # type: ignore[type-var]
        basis = getattr(score, "_display_basis", None)
        if basis is not None:
            object.__setattr__(presented, "_display_basis", basis)
        result.append(presented)
    return result


def displayed_rank_info(
    rank_info: dict[str, tuple[float | None, float | None]],
    scores: list[object],
    history: pd.DataFrame | None,
    previous_run_id: object,
) -> dict[str, tuple[float | None, float | None]]:
    """(previous, current) rank per instrument on ONE basis: the displayed (possibly penalised) score.

    Stored history ranks are the unpenalised research ranks. While the missing-data penalty is on, the current
    rank is the visible one and the previous rank is recomputed from the previous run's stored scores and
    coverage with the same penalty, so a delta never compares two different bases. With the penalty off the
    stored pair is returned unchanged; an instrument with no recomputable previous rank gets ``None`` (no delta).
    """

    if not any(getattr(score, "_display_basis", None) is not None for score in scores):
        return dict(rank_info)
    current = {str(score.display_id): score.rank for score in scores if getattr(score, "rank", None) is not None}  # type: ignore[attr-defined]
    previous: dict[str, int] = {}
    if isinstance(history, pd.DataFrame) and not history.empty and {"run_id", "instrument_id", "final_combined_score_10"} <= set(history.columns):
        frame = history.loc[history["run_id"].astype(str) == str(previous_run_id)]
        if "rank" in frame.columns:
            frame = frame.loc[frame["rank"].notna()]  # rows without a rank (native bank rows) stay unranked
        entries: list[tuple[bool, float, str]] = []
        for record in frame.to_dict(orient="records"):
            raw = pd.to_numeric(record.get("final_combined_score_10"), errors="coerce")
            coverage = pd.to_numeric(record.get("coverage"), errors="coerce") if "coverage" in frame.columns else float("nan")
            value = float(raw) if isfinite(raw) else None
            if value is not None and isfinite(coverage):
                value = round(NEUTRAL_SCORE_10 + (value - NEUTRAL_SCORE_10) * min(max(float(coverage), 0.0), 1.0), 2)
            entries.append((value is None, -(value or 0.0), str(record.get("instrument_id", ""))))
        previous = {key[2]: position for position, key in enumerate(sorted(entries), start=1)}
    return {
        instrument_id: (
            None if instrument_id not in previous or instrument_id not in current else previous[instrument_id],
            current.get(instrument_id),
        )
        for instrument_id in rank_info
    }


def latest_signal_per_instrument(signals: object) -> dict[str, tuple[object, bool]]:
    """Latest signal per instrument; ``(signal, conflict)`` where same-date signals that disagree set ``conflict``.

    The choice never depends on row order: the latest ``signal_date`` wins, and when several rows share it they
    must agree on score and state, otherwise the instrument is reported as conflicting (callers show unavailable).
    """

    grouped: dict[str, list[object]] = {}
    for signal in signals or ():  # type: ignore[attr-defined]
        grouped.setdefault(str(getattr(signal, "etf_id", "")), []).append(signal)
    result: dict[str, tuple[object, bool]] = {}
    for instrument_id, rows in grouped.items():
        newest = max(str(getattr(row, "signal_date", "")) for row in rows)
        same_day = [row for row in rows if str(getattr(row, "signal_date", "")) == newest]
        fingerprints = {
            (repr(getattr(row, "total_score", None)), str(getattr(row, "research_state", "")), str(getattr(row, "status", "")))
            for row in same_day
        }
        ordered = sorted(
            same_day,
            key=lambda row: (repr(getattr(row, "total_score", None)), str(getattr(row, "research_state", ""))),
        )
        result[instrument_id] = (ordered[0], len(fingerprints) > 1)
    return result


def evidence_ordered_history(history: pd.DataFrame) -> pd.DataFrame:
    """Score history ordered by evidence date, then run completion: a late backfill never becomes "Latest"."""

    if not isinstance(history, pd.DataFrame) or history.empty:
        return history
    keys: list[pd.Series] = []
    for column in ("data_as_of_date", "run_completed_at"):
        if column in history.columns:
            keys.append(pd.to_datetime(history[column], errors="coerce", utc=True))
    if not keys:
        return history
    frame = history.copy()
    names = []
    for index, key in enumerate(keys):
        name = f"__order_{index}"
        frame[name] = key
        names.append(name)
    frame = frame.sort_values(names, kind="stable", na_position="first")
    return frame.drop(columns=names)


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


def sparebank_score_context(score: object) -> dict[str, object] | None:
    """What the stored scorecard says about one bank: composite, coverage, gate reasons, axes without evidence."""

    from etf_cockpit.application.sparebank_peers import load_peer_row

    return load_peer_row(None, str(getattr(score, "display_id", "")))


def score_gate_failed(score: object) -> bool:
    """True when a critical-evidence gate failed: the score is descriptive only and carries no Buy-type label."""

    canonical = getattr(score, "canonical_score", None)
    if canonical is not None and bool(getattr(canonical, "gate_failed", False)):
        return True
    return str(getattr(score, "final_label", "") or "") == INSUFFICIENT_LABEL


def score_buy_eligible(score: object) -> bool:
    """A Buy-type label counts only while no critical gate has failed; the display shrink never changes this."""

    from etf_cockpit.analysis.decision.gates import is_buy_label

    return not score_gate_failed(score) and is_buy_label(getattr(score, "final_label", ""))


def apply_missing_data_penalty(score: object) -> object:
    """Pull a score toward neutral 5 by its missing evidence: 5 + (score - 5) x coverage.

    The result is a display adjustment, never a confidence or probability, and it never touches the label or
    action: a gate-failed instrument stays "Insufficient evidence" whatever the shrunk value is.
    """

    raw = getattr(score, "final_score_10", None)
    coverage = score_coverage(score)
    if raw is None or coverage is None:
        return score
    adjusted = round(NEUTRAL_SCORE_10 + (float(raw) - NEUTRAL_SCORE_10) * coverage, 2)
    note = (
        f"Missing-data penalty on: {float(raw):.1f} -> {adjusted:.1f} at {coverage:.0%} evidence coverage "
        "(research score -> display-adjusted value; not a confidence or probability)."
    )
    if score_gate_failed(score):
        note += " Critical evidence is missing, so this adjustment cannot make the instrument eligible."
    reason = f"{getattr(score, 'one_line_reason', '') or ''} {note}".strip()
    presented = replace(score, final_score_10=adjusted, one_line_reason=reason)
    # Not a dataclass field (the score contract and goldens stay unchanged): the three display numbers.
    object.__setattr__(presented, "_display_basis", {"research": float(raw), "coverage": coverage, "adjusted": adjusted})
    return presented


def score_display_values(score: object) -> dict[str, object]:
    """Research score, evidence coverage and display-adjusted value as three separate fields."""

    basis = getattr(score, "_display_basis", None)
    if isinstance(basis, dict):
        research, coverage, adjusted = basis["research"], basis["coverage"], basis["adjusted"]
    else:
        research = getattr(score, "final_score_10", None)
        coverage = score_coverage(score)
        adjusted = research
    return {
        "research_score_10": research,
        "evidence_coverage": coverage,
        "display_adjusted_score_10": adjusted,
        "gate_failed": score_gate_failed(score),
        "buy_eligible": score_buy_eligible(score),
    }


def score_card_values(score: object) -> dict[str, object]:
    """Every number shown beside a score, read from the one canonical score row.

    Pages must not recompute these (the stored scoreboard and the signal pipeline apply different caps and
    eligibility rules), otherwise the same instrument shows different Quality, confidence or component counts.
    """

    canonical = getattr(score, "canonical_score", None)

    def number(value: object) -> float | None:
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return result if isfinite(result) else None

    return {
        "canonical_attractiveness_10": number(getattr(canonical, "attractiveness_10", None)),
        "canonical_expected_return_10": number(getattr(canonical, "expected_return_10", None)),
        "canonical_risk_implementation_10": number(getattr(canonical, "risk_implementation_10", None)),
        "canonical_evidence_confidence_10": number(getattr(canonical, "evidence_confidence_10", None)),
        "canonical_coverage": number(getattr(canonical, "coverage", None)),
        "evidence_quality_10": number(getattr(score, "evidence_quality_10", None)),
        "valid_components": tuple(getattr(score, "evidence_component_counts", (0, 0)))[0],
        "total_components": tuple(getattr(score, "evidence_component_counts", (0, 0)))[1],
        "confidence_cap": _confidence_cap(canonical),
        "critical_gates_failed": tuple(
            str(getattr(gate, "gate_id", "")) for gate in getattr(canonical, "critical_gates", ()) or () if not getattr(gate, "passed", True)
        ),
        "research_decision_status": getattr(getattr(canonical, "authority", None), "research_decision_status", None),
    }


def _confidence_cap(canonical: object) -> float | None:
    """The structure cap that limited evidence confidence (0-1), or ``None`` when no cap was applied."""

    for warning in getattr(canonical, "warnings", ()) or ():
        text = str(warning)
        if text.startswith("structure_confidence_cap:"):
            try:
                return float(text.split(":", 1)[1])
            except ValueError:
                return None
    return None


def confidence_cap_note(values: dict[str, object]) -> str | None:
    """Plain-language reason evidence confidence is low although the score itself is valid."""

    cap = values.get("confidence_cap")
    confidence = values.get("canonical_evidence_confidence_10")
    if not isinstance(cap, float) or not isinstance(confidence, float) or cap >= 1.0:
        return None
    return (
        f"Evidence confidence is held at {confidence:.1f} of 10 because fund-structure evidence "
        "(holdings, methodology, fees) is incomplete; the score itself is unchanged."
    )
