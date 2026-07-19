from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.application.validation import _validation_code_hash, build_validation_preview, record_validation_preview
from etf_cockpit.features.training_centre import LocalTrainingRegistry


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


def test_validation_preview_can_be_retained_with_explicit_hashes_and_pending_decision(tmp_path) -> None:
    dates = pd.date_range("2025-01-01", periods=80)
    prices = pd.DataFrame({"date": dates, "etf_id": "AAA", "adjusted_close": [100 + index * 0.2 for index in range(80)]})

    result = record_validation_preview(tmp_path, prices)

    assert result is not None
    assert len(result["report"]["trial_ids"]) == 2
    assert result["report"]["code_hash"] == _validation_code_hash()
    assert result["promotion"]["eligible"] is False
    assert "researcher_approval_missing" in result["promotion"]["reasons"]


def test_validation_preview_marks_run_failed_when_evidence_persistence_fails(tmp_path, monkeypatch) -> None:
    dates = pd.date_range("2025-01-01", periods=80)
    prices = pd.DataFrame({"date": dates, "etf_id": "AAA", "adjusted_close": [100 + index * 0.2 for index in range(80)]})

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated evidence failure")

    monkeypatch.setattr(LocalTrainingRegistry, "record_validation_report", fail)
    with pytest.raises(RuntimeError, match="simulated evidence failure"):
        record_validation_preview(tmp_path, prices)

    runs = LocalTrainingRegistry(tmp_path).snapshot()["training.run"]
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["completion_report"]["status"] == "validation_evidence_failed"
