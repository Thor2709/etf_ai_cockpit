from __future__ import annotations

import pandas as pd

from etf_cockpit.data.score_history import append_score_run, score_history_frame


def test_score_history_append_is_idempotent_by_run_and_snapshot(tmp_path) -> None:
    scores = pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [7.0], "final_action": ["watchlist"], "component": ["momentum"]})
    first = append_score_run(scores, "run-1", "2026-07-10", root=tmp_path)
    second = append_score_run(scores, "run-1", "2026-07-10", root=tmp_path)
    history = score_history_frame(root=tmp_path)
    assert first.rows_written == 1
    assert second.rows_written == 0
    assert len(history) == 1


def test_invalid_history_rows_are_dropped_without_crashing(tmp_path) -> None:
    scores = pd.DataFrame({"instrument_id": ["A", "B"], "final_combined_score_10": [7.0, "bad"], "final_action": ["watchlist", "manual_review"]})
    append_score_run(scores, "run-1", "2026-07-10", root=tmp_path)
    assert len(score_history_frame(root=tmp_path)) == 1
