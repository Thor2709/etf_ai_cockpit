"""SB2 application views behind the bank workspace: quarter history, peers, Scores context, Pillar 3 review."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import flet as ft

from etf_cockpit.app.pages import _sparebank_view as sparebank_view
from etf_cockpit.app.pages._sparebank_view import render_sparebank_workspace
from etf_cockpit.application import sparebank_peers
from etf_cockpit.application.score_views import sparebank_score_context
from etf_cockpit.application.sparebank_evidence import review_pillar3_figure
from etf_cockpit.data import pillar3_queue
from etf_cockpit.data.pillar3_queue import confirmed_figures


def _run(run_id: str, at: str, score: float, formula: str = "v1.2.0", instrument: str = "NONG", effective: str | None = None) -> dict[str, object]:
    return {"instrument_id": instrument, "run_id": run_id, "run_started_at": at, "run_completed_at": at, "effective_at": effective or at[:10], "final_combined_score_10": score, "coverage": 0.77, "formula_version": formula}


def test_quarter_history_keeps_the_last_native_run_per_quarter_and_trends_only_within_a_formula() -> None:
    frame = pd.DataFrame(
        [
            _run("sparebank:a", "2026-01-10T09:00:00Z", 6.0, effective="2024-12-31"),
            _run("sparebank:b", "2026-02-20T09:00:00Z", 7.0, effective="2024-12-31"),  # same reporting period, later run
            _run("sparebank:c", "2026-04-02T09:00:00Z", 8.0, effective="2025-03-31"),
            _run("sparebank:d", "2026-07-02T09:00:00Z", 5.0, formula="v2.0.0", effective="2025-06-30"),  # formula change: no trend
            _run("score-engine:x", "2026-07-03T09:00:00Z", 1.0, effective="2025-06-30"),  # generic engine rows are not bank scorecards
            _run("sparebank:e", "2026-07-04T09:00:00Z", 9.0, instrument="HELG", effective="2025-06-30"),
        ]
    )
    history = sparebank_peers.quarterly_score_history(frame, "NONG")
    assert [(row["quarter"], row["composite"]) for row in history] == [("2024 Q4", 7.0), ("2025 Q1", 8.0), ("2025 Q2", 5.0)]
    assert history[0]["change"] is None and history[1]["change"] == 1.0 and history[2]["change"] is None
    assert history[0]["run_started_at"] == "2026-02-20T09:00:00+00:00"
    assert history[0]["run_completed_at"] == "2026-02-20T09:00:00+00:00"
    earlier = sparebank_peers.quarterly_score_history(frame, "NONG", "2026-06-01T00:00:00Z")
    assert [(row["quarter"], row["composite"]) for row in earlier] == [("2024 Q4", 7.0), ("2025 Q1", 8.0)]
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
    first = next(item["figure_id"] for item in queue["figures"] if item["value"] == 16.8)
    second = next(item["figure_id"] for item in queue["figures"] if item["value"] == 17.1)
    t1, t2 = "2025-04-01T00:00:00Z", "2025-06-01T00:00:00Z"
    pillar3_queue.decide(tmp_path, "TEST", first, "confirmed", decided_at=t1)
    result = pillar3_queue.decide(tmp_path, "TEST", second, "confirmed", decided_at=t2)
    by_id = {item["figure_id"]: item for item in result["figures"]}
    assert by_id[second]["status"] == "confirmed" and by_id[first]["status"] == "confirmed"
    assert by_id[first]["decided_at"] == t1 and by_id[first]["superseded_at"] == t2
    assert [item["figure_id"] for item in confirmed_figures(result, "2025-05-01T00:00:00Z")] == [first]
    assert [item["figure_id"] for item in confirmed_figures(result, "2025-07-01T00:00:00Z")] == [second]
    with pytest.raises(ValueError):
        review_pillar3_figure(tmp_path, "TEST", second, "maybe")
    with pytest.raises(KeyError):
        review_pillar3_figure(tmp_path, "TEST", "missing", "confirmed")


def test_workspace_renders_for_a_sparse_available_record_and_is_empty_when_unavailable(tmp_path: Path) -> None:
    sparse = {"status": "available", "instrument_id": "T1", "scorecard": {"formula_version": "sparebank-scorecard-v1.2.0"}}
    tile = render_sparebank_workspace(sparse, root=tmp_path, page=None)
    assert tile.key == "instrument-detail.sparebank-workspace"
    assert render_sparebank_workspace({"status": "unavailable"}).__class__.__name__ == "Container"


def test_economics_table_displays_the_producer_net_interest_margin() -> None:
    captured: dict[str, object] = {}

    def table(_columns: object, rows: object, **_kwargs: object) -> ft.Control:
        captured["rows"] = rows
        return ft.Container()

    original = sparebank_view.DataTable
    sparebank_view.DataTable = table  # type: ignore[assignment]
    try:
        sparebank_view._bank_economics({"bank_economics": {"lending": {"net_interest_margin": 0.023}}})
    finally:
        sparebank_view.DataTable = original
    rows = captured["rows"]
    assert rows[0]["metric"] == "Net interest margin"  # type: ignore[index]
    assert rows[0]["value"] == "2.30 %"  # type: ignore[index]


def test_input_rows_show_the_evidence_source_next_to_the_calculation_id() -> None:
    rows = sparebank_view._input_rows(
        [
            {
                "id": "cet1_headroom_pp",
                "label": "CET1 headroom",
                "calculation_id": "sparebank.bank_economics.capital_resilience",
                "source_locator": "https://example.test/p3.pdf | Pillar 3 | page 4",
                "value": 1.5,
                "rating_10": 5.0,
                "scored": True,
            }
        ]
    )
    assert "sparebank.bank_economics.capital_resilience" in rows[0]["input"][1]
    assert "page 4" in rows[0]["input"][1]


def test_history_table_shows_run_timestamps_as_separate_columns() -> None:
    captured: dict[str, object] = {}

    def table(columns: object, rows: object, **_kwargs: object) -> ft.Control:
        captured["columns"] = columns
        captured["rows"] = rows
        return ft.Container()

    original = sparebank_view.DataTable
    sparebank_view.DataTable = table  # type: ignore[assignment]
    try:
        sparebank_view._history(
            {
                "history": [
                    {
                        "quarter": "2024 Q4",
                        "run_started_at": "2026-02-20T09:00:00+00:00",
                        "run_completed_at": "2026-02-20T09:05:00+00:00",
                        "composite": 7.0,
                        "coverage": 0.77,
                        "formula_version": "v1.2.0",
                    }
                ]
            }
        )
    finally:
        sparebank_view.DataTable = original
    columns = captured["columns"]
    assert {column.key for column in columns} >= {"run_started_at", "run_completed_at"}  # type: ignore[union-attr]
    assert captured["rows"][0]["run_started_at"] == "2026-02-20T09:00:00+00:00"  # type: ignore[index]
