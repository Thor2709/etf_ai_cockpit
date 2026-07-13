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


def test_run_comparison_exposes_all_required_dimensions_and_summary() -> None:
    frame = pd.DataFrame(
        [
            {
                "run_id": "old",
                "instrument_id": "A",
                "final_combined_score_10": 5.0,
                "rank": 4,
                "final_action": "watchlist",
                "warnings": "stale_prices",
                "freshness_status": "stale",
                "model_available": False,
                "forecast_status": "unavailable",
                "news_inventory": 1,
                "backtest_trust": "weak",
                "portfolio_risk": "low",
            },
            {
                "run_id": "new",
                "instrument_id": "A",
                "final_combined_score_10": 7.0,
                "rank": 2,
                "final_action": "add_candidate",
                "warnings": "",
                "freshness_status": "ok",
                "model_available": True,
                "forecast_status": "available",
                "news_inventory": 3,
                "backtest_trust": "usable",
                "portfolio_risk": "review",
            },
        ]
    )

    change = compare_runs(frame, "new", "old").changes[0]

    assert change.score_rank_delta == -2
    assert change.warnings_changed is True
    assert change.freshness_changed is True
    assert change.model_availability_changed is True
    assert change.forecast_changed is True
    assert change.news_inventory_changed is True
    assert change.backtest_trust_changed is True
    assert change.portfolio_risk_changed is True
    assert "score" in change.summary.lower()


def test_run_comparison_can_load_history_by_run_ids(tmp_path) -> None:
    from etf_cockpit.data.score_history import append_score_run

    append_score_run(pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [5.0]}), "old", "2026-07-09", root=tmp_path)
    append_score_run(pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [6.0]}), "new", "2026-07-10", root=tmp_path)

    report = compare_runs("new", "old", root=tmp_path)

    assert report.changes[0].score_delta == 1.0
