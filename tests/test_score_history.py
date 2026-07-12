from __future__ import annotations

import pandas as pd

from etf_cockpit.data.score_history import append_score_run, score_history_frame, score_history_v2_payload


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


def test_legacy_review_states_never_infer_portfolio_authority_without_snapshot() -> None:
    for state in (
        "maintain_review",
        "increase_exposure_review",
        "reduce_exposure_review",
        "exit_thesis_review",
        "constraints_blocked",
    ):
        payload = score_history_v2_payload(
            {
                "instrument_id": "A",
                "final_combined_score_10": 7.0,
                "final_action": "hold",
                "portfolio_review_state": state,
            }
        )
        assert payload["portfolio_review_allowed"] is False
        assert payload["portfolio_snapshot_validated"] is False


def test_score_history_accepts_portfolio_review_only_with_validated_snapshot() -> None:
    payload = score_history_v2_payload(
        {
            "instrument_id": "A",
            "final_combined_score_10": 7.0,
            "final_action": "hold",
            "portfolio_snapshot": {
                "as_of_date": "2026-07-10",
                "portfolio_review_state": "reduce_exposure_review",
                "holdings": [{"instrument_id": "A", "weight": 0.5}],
            },
        }
    )
    assert payload["portfolio_review_state"] == "reduce_exposure_review"
    assert payload["portfolio_review_allowed"] is True
    assert payload["portfolio_snapshot_validated"] is True


def test_score_history_rejects_forged_snapshot_marker_without_source_evidence() -> None:
    payload = score_history_v2_payload(
        {
            "instrument_id": "A",
            "research_state": "hold_review",
            "portfolio_review_state": "reduce_exposure_review",
            "portfolio_snapshot_validated": True,
            "portfolio_snapshot_provenance": "validated_snapshot",
            "portfolio_snapshot_checksum": "0" * 64,
            "portfolio_review_allowed": True,
        }
    )

    assert payload["portfolio_review_allowed"] is False
    assert payload["portfolio_snapshot_validated"] is False
    assert payload["portfolio_snapshot_provenance"] == "unavailable"
