from __future__ import annotations

import pandas as pd

from etf_cockpit.application.validation import build_validation_preview


def test_validation_preview_is_local_and_promotion_blocked_without_model_trials() -> None:
    dates = pd.date_range("2025-01-01", periods=80)
    prices = pd.DataFrame(
        {
            "date": dates.tolist() * 2,
            "etf_id": ["AAA"] * 80 + ["BBB"] * 80,
            "adjusted_close": [100 + index * 0.2 for index in range(80)] + [90 + index * 0.1 for index in range(80)],
        }
    )

    report = build_validation_preview(prices)

    assert report is not None
    assert report.final_test_used_for_selection is False
    assert report.promotion_eligible is False
    assert len(report.trials) == 2


def test_validation_preview_has_controlled_unavailable_state_without_adjusted_history() -> None:
    assert build_validation_preview(pd.DataFrame({"close": [1, 2, 3]})) is None
