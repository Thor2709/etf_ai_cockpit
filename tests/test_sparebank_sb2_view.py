"""SB2 application views behind the bank workspace: quarter history, peers, Scores context, Pillar 3 review."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.app.pages._sparebank_view import render_sparebank_workspace
from etf_cockpit.application import sparebank_peers
from etf_cockpit.application.score_views import sparebank_score_context
from etf_cockpit.application.sparebank_evidence import review_pillar3_figure
from etf_cockpit.data import pillar3_queue


def _run(run_id: str, at: str, score: float, formula: str = "v1.2.0", instrument: str = "NONG") -> dict[str, object]:
    return {"instrument_id": instrument, "run_id": run_id, "run_started_at": at, "final_combined_score_10": score, "coverage": 0.77, "formula_version": formula}


def test_quarter_history_keeps_the_last_native_run_per_quarter_and_trends_only_within_a_formula() -> None:
    frame = pd.DataFrame(
        [
            _run("sparebank:a", "2026-01-10T09:00:00Z", 6.0),
            _run("sparebank:b", "2026-02-20T09:00:00Z", 7.0),  # supersedes a within the quarter
            _run("sparebank:c", "2026-04-02T09:00:00Z", 8.0),
            _run("sparebank:d", "2026-07-02T09:00:00Z", 5.0, formula="v2.0.0"),  # formula change: no trend
            _run("score-engine:x", "2026-07-03T09:00:00Z", 1.0),  # generic engine rows are not bank scorecards
            _run("sparebank:e", "2026-07-04T09:00:00Z", 9.0, instrument="HELG"),
        ]
    )
    history = sparebank_peers.quarterly_score_history(frame, "NONG")
    assert [(row["quarter"], row["composite"]) for row in history] == [("2026 Q1", 7.0), ("2026 Q2", 8.0), ("2026 Q3", 5.0)]
    assert history[0]["change"] is None and history[1]["change"] == 1.0 and history[2]["change"] is None
    assert sparebank_peers.quarterly_score_history(None, "NONG") == [] and sparebank_peers.quarterly_score_history(frame, "NOPE") == []


def test_peer_rows_respect_the_decision_time_and_list_picked_peers_first(tmp_path: Path) -> None:
    for identifier, composite, as_of in (("AAA", 5.0, "2026-10-01T00:00:00Z"), ("BBB", 9.0, "2026-10-01T00:00:00Z"), ("CCC", 7.0, "2026-10-20T00:00:00Z"), ("SELF", 8.0, "2026-10-01T00:00:00Z")):
        sparebank_peers.record_peer_row(tmp_path, {"instrument_id": identifier, "name": identifier, "as_of": as_of, "composite": composite})
    # CCC was scored after the decision time (look-ahead) and the certificate itself is never its own peer.
    rows = sparebank_peers.load_peer_rows(tmp_path, "SELF", "2026-10-09T00:00:00Z")
    assert [row["instrument_id"] for row in rows] == ["BBB", "AAA"]
    sparebank_peers.set_picked_peers(tmp_path, "SELF", ["aaa", "self", " "])
    picked = sparebank_peers.load_peer_rows(tmp_path, "SELF", "2026-10-09T00:00:00Z")
    assert [(row["instrument_id"], row["picked"]) for row in picked] == [("AAA", True), ("BBB", False)]
    assert sparebank_peers.picked_peers(tmp_path, "SELF") == ["AAA"]


def test_scores_context_explains_a_bank_row_from_the_stored_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sparebank_peers, "ROOT", tmp_path)
    sparebank_peers.record_peer_row(tmp_path, {"instrument_id": "NONG", "name": "N", "as_of": "2026-10-09T00:00:00Z", "composite": 8.6, "coverage": 0.77, "missing_axes": ["capital_allocation"], "gate_reasons": []})
    context = sparebank_score_context(type("Score", (), {"display_id": "NONG"})())
    assert context is not None and context["composite"] == 8.6 and context["missing_axes"] == ["capital_allocation"]
    assert sparebank_score_context(type("Score", (), {"display_id": "XAIX"})()) is None


def test_pillar3_review_confirms_supersedes_and_rejects_bad_requests(tmp_path: Path) -> None:
    document = {"document_id": "doc1", "source_url": "https://example.test/p3.pdf"}
    figures = [{"metric": "cet1_ratio_pct", "value": value, "period": "2024-12-31", "page": page, "status": "pending"} for value, page in ((16.8, 2), (17.1, 3))]
    queue = pillar3_queue.merge_extraction(tmp_path, "TEST", document, figures)
    first, second = (item["figure_id"] for item in queue["figures"])
    review_pillar3_figure(tmp_path, "TEST", first, "confirmed")
    result = review_pillar3_figure(tmp_path, "TEST", second, "confirmed")
    status = {item["figure_id"]: item["status"] for item in result["figures"]}
    assert status[second] == "confirmed" and status[first] == "rejected"  # one confirmed figure per metric and period
    with pytest.raises(ValueError):
        review_pillar3_figure(tmp_path, "TEST", second, "maybe")
    with pytest.raises(KeyError):
        review_pillar3_figure(tmp_path, "TEST", "missing", "confirmed")


def test_workspace_renders_for_a_sparse_available_record_and_is_empty_when_unavailable(tmp_path: Path) -> None:
    sparse = {"status": "available", "instrument_id": "T1", "scorecard": {"formula_version": "sparebank-scorecard-v1.2.0"}}
    tile = render_sparebank_workspace(sparse, root=tmp_path, page=None)
    assert tile.key == "instrument-detail.sparebank-workspace"
    assert render_sparebank_workspace({"status": "unavailable"}).__class__.__name__ == "Container"
