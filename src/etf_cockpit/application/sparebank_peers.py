"""Peer summary for the Sparebank instrument page (SB2).

Every rescore of a bank (``scripts/sparebank_refresh.py``) stores one summary row in
``data/derived/sparebank_peers.json``. The page lists the other certificates from that file, so building one page
never rescores the whole universe, and a row dated after the decision time is never shown (point in time).
Owner-picked peers are kept in the display preferences and only change the order, not the data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import ROOT
from etf_cockpit.core.ui_preferences import SPAREBANK_PEERS, load_preferences, save_preference

SCHEMA_VERSION = "sparebank_peers.v1"
# scorecard input ids copied into the peer row (the scorecard stays the one place that computes them)
_INPUT_FIELDS = {
    "cost_income_pct": "cost_income_pct",
    "cost_of_risk_bps": "cost_of_risk_bps",
    "cet1_headroom_pp": "cet1_headroom_pp",
    "deposit_to_loan_ratio_pct": "deposit_to_loan_ratio_pct",
    "normalised_roe_minus_cost_of_equity_pp": "roe_minus_coe_pp",
    "owner_value_vs_decision_price_pct": "owner_value_vs_price_pct",
    "expectations_gap_pp": "expectations_gap_pp",
}


def _path(root: Path | None) -> Path:
    return (Path(root) if root is not None else ROOT) / "data" / "derived" / "sparebank_peers.json"


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def axis_evidence_groups(scorecard: Mapping[str, object]) -> tuple[list[str], list[str]]:
    """(axes with no rating at all, axes rated on partial evidence), from the scorecard's own axis results.

    The scorecard's ``missing_axes`` lists every axis below full coverage, so it also names axes that show a
    rating; pages must describe those separately instead of claiming they have no evidence.
    """

    without: list[str] = []
    partial: list[str] = []
    axes = scorecard.get("axes")
    for axis_id, axis in (axes.items() if isinstance(axes, Mapping) else ()):
        if not isinstance(axis, Mapping):
            continue
        coverage = _number(axis.get("coverage"))
        if _number(axis.get("rating_10")) is None:
            without.append(str(axis_id))
        elif coverage is not None and coverage < 1.0:
            partial.append(str(axis_id))
    return without, partial


def axis_evidence_notes(without: Sequence[object] | None, partial: Sequence[object] | None, incomplete: Sequence[object] = ()) -> list[str]:
    """Plain-language header lines about axis evidence; ``incomplete`` is the legacy undifferentiated list."""

    def names(items: Sequence[object]) -> str:
        return ", ".join(str(item).replace("_", " ") for item in items)

    notes: list[str] = []
    if without:
        notes.append(f"Axes without a rating (no evidence): {names(without)}.")
    if partial:
        notes.append(f"Axes rated on partial evidence: {names(partial)}.")
    if not notes and incomplete:
        notes.append(f"Axes with incomplete evidence: {names(incomplete)}.")
    return notes


def peer_row(instrument_id: str, name: str, analysis: Mapping[str, object], as_of: str) -> dict[str, object]:
    """One summary row from a Sparebank analysis payload."""

    scorecard = analysis.get("scorecard") if isinstance(analysis.get("scorecard"), Mapping) else {}
    inputs: dict[str, object] = {}
    for axis in (scorecard.get("axes") or {}).values():  # type: ignore[union-attr]
        for item in axis.get("inputs", ()) if isinstance(axis, Mapping) else ():
            if isinstance(item, Mapping):
                inputs[str(item.get("id"))] = item.get("value")
    valuation = analysis.get("valuation") if isinstance(analysis.get("valuation"), Mapping) else {}
    standalone = valuation.get("standalone") if isinstance(valuation.get("standalone"), Mapping) else {}
    central = valuation.get("central_owner_value_per_ec") if isinstance(valuation.get("central_owner_value_per_ec"), Mapping) else {}
    claim = analysis.get("claim_state") if isinstance(analysis.get("claim_state"), Mapping) else {}
    dividends = analysis.get("dividends") if isinstance(analysis.get("dividends"), Mapping) else {}
    row: dict[str, object] = {
        "instrument_id": instrument_id,
        "name": name,
        "as_of": as_of,
        "composite": _number(scorecard.get("composite_10")),
        "coverage": _number(scorecard.get("composite_coverage")),
        "owner_pb": _number(standalone.get("owner_pb")),
        "justified_pb": _number(central.get("justified_pb")),
        "roe": _number(standalone.get("roe")),
        "eierbrok": _number(claim.get("reconstructed_eierbrok")),
        "ttm_yield": _number(dividends.get("ttm_yield")),
        "gate_reasons": [str(item) for item in (scorecard.get("gate_reasons") or ())],
        "missing_axes": [str(item) for item in (scorecard.get("missing_axes") or ())],
        "axes_without_rating": axis_evidence_groups(scorecard)[0],
        "axes_partial_evidence": axis_evidence_groups(scorecard)[1],
        "formula_version": scorecard.get("formula_version"),
    }
    for source, target in _INPUT_FIELDS.items():
        row[target] = _number(inputs.get(source))
    return row


def record_peer_row(root: Path | None, row: Mapping[str, object]) -> None:
    """Upsert one bank's row (atomic file replace)."""

    path = _path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    rows = payload.get("rows") if isinstance(payload, dict) and isinstance(payload.get("rows"), dict) else {}
    rows[str(row["instrument_id"])] = dict(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "rows": rows, "execution_allowed": False})


def load_peer_rows(root: Path | None, instrument_id: str, decision_time: object = None) -> list[dict[str, object]]:
    """Other certificates, owner-picked first, then by composite; rows after the decision time are dropped."""

    try:
        payload = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = payload.get("rows") if isinstance(payload, dict) and isinstance(payload.get("rows"), dict) else {}
    cutoff = pd.to_datetime(decision_time, errors="coerce", utc=True) if decision_time else None
    picked = set(picked_peers(root, instrument_id))
    result: list[dict[str, object]] = []
    for key, row in rows.items():
        if key == instrument_id or not isinstance(row, Mapping):
            continue
        stamp = pd.to_datetime(row.get("as_of"), errors="coerce", utc=True)
        if cutoff is not None and not pd.isna(cutoff) and (pd.isna(stamp) or stamp > cutoff):
            continue
        result.append({**row, "picked": key in picked})
    return sorted(result, key=lambda row: (not row["picked"], -(_number(row.get("composite")) or -1.0), str(row.get("instrument_id"))))


def load_peer_row(root: Path | None, instrument_id: str) -> dict[str, object] | None:
    """The latest stored summary row of one certificate (used to explain a missing score)."""

    try:
        payload = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = payload.get("rows") if isinstance(payload, dict) and isinstance(payload.get("rows"), dict) else {}
    row = rows.get(str(instrument_id))
    return dict(row) if isinstance(row, Mapping) else None


def picked_peers(root: Path | None, instrument_id: str) -> list[str]:
    stored = load_preferences(root).get(SPAREBANK_PEERS)
    chosen = stored.get(instrument_id) if isinstance(stored, Mapping) else None
    return [str(item) for item in chosen] if isinstance(chosen, list) else []


def set_picked_peers(root: Path | None, instrument_id: str, peer_ids: list[str]) -> None:
    stored = load_preferences(root).get(SPAREBANK_PEERS)
    updated = dict(stored) if isinstance(stored, Mapping) else {}
    updated[instrument_id] = sorted({str(item).upper() for item in peer_ids if str(item).strip() and str(item).upper() != instrument_id})
    save_preference(SPAREBANK_PEERS, updated, root=root)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def quarterly_score_history(
    frame: pd.DataFrame | None,
    instrument_id: str,
    decision_time: str | None = None,
) -> list[dict[str, object]]:
    """Last native run per reporting quarter at the decision time, oldest first.

    The change is shown only between rows of the same formula version (a formula change is not a trend).
    """

    if frame is None or frame.empty or not {"instrument_id", "run_id", "final_combined_score_10"}.issubset(frame.columns):
        return []
    rows = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id)) & frame["run_id"].astype(str).str.startswith("sparebank:")].copy()
    if rows.empty:
        return []
    if "effective_at" not in rows.columns:
        return []
    started = rows["run_started_at"] if "run_started_at" in rows.columns else pd.Series(pd.NaT, index=rows.index)
    completed = rows["run_completed_at"] if "run_completed_at" in rows.columns else pd.Series(pd.NaT, index=rows.index)
    rows["_started_at"] = pd.to_datetime(started, errors="coerce", utc=True)
    rows["_completed_at"] = pd.to_datetime(completed, errors="coerce", utc=True)
    rows["_at"] = rows["_completed_at"].fillna(rows["_started_at"])
    rows["_period"] = pd.to_datetime(rows["effective_at"], errors="coerce", utc=True)
    rows = rows.loc[rows["_at"].notna() & rows["_period"].notna()]
    if decision_time:
        cutoff = pd.to_datetime(decision_time, errors="coerce", utc=True)
        if pd.isna(cutoff):
            return []
        rows = rows.loc[rows["_at"].le(cutoff)]
    rows = rows.sort_values("_at", kind="stable")
    rows["_quarter"] = rows["_period"].dt.tz_localize(None).dt.to_period("Q")
    latest = rows.groupby("_quarter", sort=True).tail(1).sort_values("_quarter", kind="stable")
    result: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    for row in latest.to_dict("records"):
        composite = _number(row.get("final_combined_score_10"))
        entry: dict[str, object] = {
            "quarter": f"{row['_quarter'].year} Q{row['_quarter'].quarter}",
            "run_started_at": row["_started_at"].isoformat() if pd.notna(row["_started_at"]) else None,
            "run_completed_at": row["_completed_at"].isoformat() if pd.notna(row["_completed_at"]) else None,
            "run_timestamp": row["_at"].isoformat(),
            "effective_at": row["_period"].date().isoformat(),
            "data_as_of": str(row.get("data_as_of_date") or "") or None,
            "composite": composite,
            "coverage": _number(row.get("coverage")),
            "formula_version": str(row.get("formula_version") or "") or None,
            "change": None,
        }
        if previous is not None and composite is not None and previous["composite"] is not None and previous["formula_version"] == entry["formula_version"]:
            entry["change"] = composite - float(previous["composite"])  # type: ignore[arg-type]
        result.append(entry)
        previous = entry
    return result
