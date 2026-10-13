"""Sparebank scores are computed by the refresh, stored once, and read (not recomputed) by score lists."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_cockpit.data import score_history
from etf_cockpit.signals import simple_scores


def _history(monkeypatch, rows: dict[str, dict[str, object]]) -> None:
    monkeypatch.setattr(simple_scores, "latest_sparebank_scores", lambda **_: rows)


def _status(display_id: str):
    return simple_scores._sparebank_scorecard_status(
        instrument_key=f"configured:{display_id}", display_id=display_id, name=display_id, yahoo_symbol=f"{display_id}.OL",
        asset_type="Equity certificate", instrument_currency="NOK", isin=None, data_policy="yfinance_only",
    )


def test_stored_native_composite_is_shown_with_coverage(monkeypatch) -> None:
    _history(monkeypatch, {"NONG": {"final_combined_score_10": 4.951899, "coverage": 0.319444, "data_as_of_date": "2026-10-09"}})
    score = _status("NONG")
    assert score.final_score_10 == 4.95
    assert score.decision == "Sparebank scorecard"
    assert "32% of axis evidence" in score.one_line_reason


def test_missing_native_composite_stays_unscored_with_reason(monkeypatch) -> None:
    _history(monkeypatch, {})
    score = _status("HELG")
    assert score.final_score_10 is None
    assert "pending" in score.one_line_reason


def test_latest_sparebank_scores_takes_latest_native_run(tmp_path: Path) -> None:
    current = score_history._current_sparebank_formula_version()
    rows = pd.DataFrame(
        [
            {"instrument_id": "MING", "run_id": "sparebank:MING:2026-10-08T00:00:00Z", "final_combined_score_10": 5.0, "formula_version": current},
            {"instrument_id": "MING", "run_id": "sparebank:MING:2026-10-09T00:00:00Z", "final_combined_score_10": 5.5, "formula_version": current},
            # A later row from a superseded scorecard formula is never shown as current.
            {"instrument_id": "MING", "run_id": "sparebank:MING:2026-10-10T00:00:00Z", "final_combined_score_10": 9.9, "formula_version": "sparebank-scorecard-v0"},
            {"instrument_id": "VWCE", "run_id": "generic:2026-10-09", "final_combined_score_10": 7.9},
        ]
    )
    for run_id, part in rows.groupby("run_id"):
        score_history.append_score_run(part.reset_index(drop=True), run_id, run_id.split(":")[-1] if run_id.startswith("sparebank") else "2026-10-09", root=tmp_path)
    latest = score_history.latest_sparebank_scores(root=tmp_path)
    assert set(latest) == {"MING"}
    assert float(latest["MING"]["final_combined_score_10"]) == 5.5


def test_below_floor_bank_keeps_generic_score_labelled_pending(monkeypatch) -> None:
    _history(monkeypatch, {})
    generic = simple_scores.replace(_status("HELG"), final_score_10=6.1, source_group="Primary", one_line_reason="Momentum strong.")
    pending = simple_scores._as_sparebank_pending(generic)
    assert pending.final_score_10 == 6.1
    assert pending.source_group == simple_scores.SPAREBANKEN_TIER_LABEL
    assert pending.decision == "Sparebank scorecard pending"
    assert pending.one_line_reason.startswith("Generic stock score shown") and "Momentum strong." in pending.one_line_reason
