"""Application compositions for score explanation and instrument comparison.

Open defaults: comparison uses stored adjusted prices over one year; missing
score, gate, cost, overlap, or history evidence remains unavailable.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from etf_cockpit.application.score_views import (
    published_scores,
    score_buy_eligible,
    score_card_values,
    score_coverage,
    score_gate_failed,
)


def explain_score(snapshot: object, instrument_id: str) -> dict[str, Any]:
    """Explain an existing canonical row; never derive score or eligibility here."""

    score = next(
        (row for row in published_scores(snapshot) if str(getattr(row, "display_id", "")) == instrument_id),
        None,
    )
    if score is None:
        return {"status": "unavailable", "instrument_id": instrument_id, "reason": "score_unavailable", "score_10": None}
    canonical = getattr(score, "canonical_score", None)
    card = score_card_values(score)
    gates = []
    for gate in getattr(canonical, "critical_gates", ()) or ():
        gates.append({
            "id": getattr(gate, "gate_id", None),
            "status": getattr(gate, "status", "unavailable"),
            "missing": list(getattr(gate, "missing", ()) or ()),
            "reason": getattr(gate, "reason_code", None),
        })
    contributions = list(getattr(canonical, "contributions", ()) or ())
    if not contributions:
        contributions = [
            {"id": getattr(component, "key", None), "label": getattr(component, "label", None),
             "value": getattr(component, "score_10", None), "status": getattr(component, "status", "unavailable")}
            for component in getattr(score, "components", ()) or ()
        ]
    return {
        "status": "available" if getattr(score, "final_score_10", None) is not None else "unavailable",
        "instrument_id": instrument_id,
        "score_10": getattr(score, "final_score_10", None),
        "label": getattr(score, "final_label", "unavailable"),
        "action": getattr(score, "final_action", "unavailable"),
        "buy_eligible": score_buy_eligible(score),
        "gate_failed": score_gate_failed(score),
        "contributions": contributions,
        "critical_gates": gates,
        "confidence_cap": card.get("confidence_cap"),
        "warnings": list(getattr(canonical, "warnings", ()) or getattr(score, "warnings", ()) or ()),
        "coverage": score_coverage(score),
        "evidence_confidence_10": card.get("canonical_evidence_confidence_10"),
        "reason": getattr(canonical, "unavailable_reason", None),
        "execution_allowed": False,
    }


def compare_instruments(
    snapshot: object,
    instrument_ids: Sequence[str],
    *,
    range_key: str = "1y",
    root: Path | None = None,
) -> dict[str, Any]:
    """Compose canonical score, history, economics, overlap, and price views."""

    ids = tuple(dict.fromkeys(str(value).strip() for value in instrument_ids if str(value).strip()))
    if not 2 <= len(ids) <= 5:
        raise ValueError("ids must contain between 2 and 5 distinct instrument ids")
    from etf_cockpit.application.ui_views.stock_research import RANGE_DAYS

    if range_key not in RANGE_DAYS:
        raise ValueError("range must be one of the supported stored-price ranges")

    rows = {str(getattr(row, "display_id", "")): row for row in published_scores(snapshot)}
    scores = {instrument_id: rows.get(instrument_id) for instrument_id in ids}
    prices = getattr(snapshot, "prices", None)
    from etf_cockpit.application.ui_views.comparison import drawdown_index, price_index

    returns = {}
    drawdowns = {}
    for id_a, id_b in combinations(ids, 2):
        pair = f"{id_a}|{id_b}"
        returns[pair] = price_index(prices, id_a, id_b, range_key)
        drawdowns[pair] = drawdown_index(prices, id_a, id_b, range_key)

    overlap: dict[str, Any]
    try:
        from etf_cockpit.application.overlap import build_direct_overlap_view, direct_overlap_payload

        if root is None:
            from etf_cockpit.core.paths import ROOT

            root = ROOT
        overlap = direct_overlap_payload(build_direct_overlap_view(snapshot, ids, root=Path(root)))
    except (OSError, ValueError, TypeError) as exc:
        overlap = {"status": "unavailable", "reason": f"direct_overlap_unavailable:{type(exc).__name__}"}

    costs = {}
    try:
        from etf_cockpit.application.etf_economics_view import build_etf_economics_panel

        for instrument_id in ids:
            try:
                panel = build_etf_economics_panel(snapshot, instrument_id)
                fields = panel.get("e1", {}) if isinstance(panel, Mapping) else {}
                costs[instrument_id] = {
                    name: fields.get(name)
                    for name in ("ter", "ocf", "transaction_cost", "tax_drag")
                    if name in fields
                }
                if not costs[instrument_id]:
                    costs[instrument_id] = {"status": "unavailable", "reason": "canonical_cost_fields_unavailable"}
            except (OSError, ValueError, TypeError) as exc:
                costs[instrument_id] = {"status": "unavailable", "reason": f"canonical_costs_unavailable:{type(exc).__name__}"}
    except ImportError:
        costs = {instrument_id: {"status": "unavailable", "reason": "canonical_cost_service_unavailable"} for instrument_id in ids}

    history: dict[str, list[dict[str, Any]]] = {instrument_id: [] for instrument_id in ids}
    try:
        from etf_cockpit.data.score_history import score_history_frame

        frame = score_history_frame(root=Path(root) if root else None)
        if isinstance(frame, pd.DataFrame) and not frame.empty and "instrument_id" in frame.columns:
            for instrument_id in ids:
                selected = frame.loc[frame["instrument_id"].astype(str) == instrument_id]
                history[instrument_id] = selected.tail(100).to_dict(orient="records")
    except (OSError, ValueError, TypeError):
        history = {instrument_id: [] for instrument_id in ids}

    return {
        "status": "available" if any(scores.values()) else "unavailable",
        "instruments": {instrument_id: explain_score(snapshot, instrument_id) for instrument_id in ids},
        "costs": costs,
        "overlap": overlap,
        "score_history": history,
        "price_return_comparison": returns,
        "drawdown_comparison": drawdowns,
        "range": range_key,
        "execution_allowed": False,
    }


def load_score_history(
    instrument_id: str, *, range_key: str = "1y", root: Path | None = None, limit: int = 500
) -> dict[str, Any]:
    """Read bounded stored score history; do not derive or fill score values."""

    from etf_cockpit.application.score_views import evidence_ordered_history
    from etf_cockpit.application.ui_views.stock_research import RANGE_DAYS
    from etf_cockpit.data.score_history import score_history_frame

    if range_key != "all" and range_key not in RANGE_DAYS:
        raise ValueError("range must be a supported stored-price range or 'all'")
    frame = score_history_frame(root=root)
    if not isinstance(frame, pd.DataFrame) or frame.empty or "instrument_id" not in frame.columns:
        return {"status": "unavailable", "instrument_id": instrument_id, "series": [], "unavailable_reason": "score_history_unavailable"}
    selected = frame.loc[frame["instrument_id"].astype(str) == instrument_id].copy()
    if selected.empty:
        return {"status": "unavailable", "instrument_id": instrument_id, "series": [], "unavailable_reason": "instrument_history_unavailable"}
    date_column = "run_completed_at" if "run_completed_at" in selected.columns else "as_of_date" if "as_of_date" in selected.columns else None
    if date_column is not None:
        dates = pd.to_datetime(selected[date_column], errors="coerce", utc=True)
        valid = dates.notna()
        selected, dates = selected.loc[valid].copy(), dates.loc[valid]
        if range_key != "all" and not dates.empty:
            cutoff = dates.max() - pd.Timedelta(days=RANGE_DAYS[range_key])
            selected = selected.loc[dates >= cutoff]
    selected = evidence_ordered_history(selected)
    truncated = len(selected) > limit
    records = selected.tail(limit).to_dict(orient="records")
    return {
        "status": "available" if records else "unavailable",
        "instrument_id": instrument_id,
        "range": range_key,
        "series": records,
        "truncated": truncated,
        "execution_allowed": False,
        **({"unavailable_reason": "score_history_unavailable_in_range"} if not records else {}),
    }


__all__ = ["compare_instruments", "explain_score", "load_score_history"]
