from __future__ import annotations

import pandas as pd

from etf_cockpit.data.run_changes import compare_runs


def test_run_comparison_reports_score_action_and_warning_changes() -> None:
    frame = pd.DataFrame(
        [
            {"run_id": "old", "instrument_id": "A", "final_combined_score_10": 5.0, "final_action": "watchlist", "blocked_by": ""},
            {"run_id": "new", "instrument_id": "A", "final_combined_score_10": 7.0, "final_action": "add_candidate", "blocked_by": ""},
        ]
    )
    report = compare_runs(frame, "new", "old")
    assert report.changes[0].score_delta == 2.0
    assert report.changes[0].action_changed is True


def test_history_is_informational_not_action_authority() -> None:
    frame = pd.DataFrame([{ "run_id": "old", "instrument_id": "A", "final_combined_score_10": 9.0, "final_action": "manual_review", "blocked_by": "identity_conflict"}])
    report = compare_runs(frame, "old", None)
    assert report.changes[0].current_action == "manual_review"
