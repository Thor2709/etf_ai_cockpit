from __future__ import annotations

import json
from pathlib import Path
import warnings

import pandas as pd

from etf_cockpit.core.types import ComponentScores, DataQualityReport, SignalResult
from etf_cockpit.portfolio.proposals import create_manual_trade_proposal_report
from etf_cockpit.portfolio.review_reports import create_portfolio_review_report


def _signal(action: str = "add_candidate", *, blocked_by: list[str] | None = None) -> SignalResult:
    return SignalResult(
        run_id="run-1",
        signal_date=pd.Timestamp("2026-06-26").date(),
        etf_id="WORLD_CORE",
        action=action,
        confidence=0.7,
        total_score=0.6,
        components=ComponentScores(*(0.0 for _ in range(12))),
        blocked_by=blocked_by or [],
        warnings=[],
        reason_short="test",
        reason_long="private thesis must remain in the report only",
        horizon_primary="1-3 months",
        supporting_metrics={"reason_full": "detailed reason"},
        suggested_trade_value_eur=250.0,
        suggested_new_weight=0.12,
    )


def _data_report() -> DataQualityReport:
    return DataQualityReport(as_of_date=pd.Timestamp("2026-06-26").date(), issues=[])


def test_portfolio_review_report_is_never_executable_and_persists_typed_states(tmp_path: Path) -> None:
    report = create_portfolio_review_report([_signal()], _data_report(), run_id="run-1", report_dir=tmp_path)

    assert report["execution_allowed"] is False
    assert report["executable_authority"] is False
    assert report["broker_execution"] == "not_supported"
    assert report["required_user_action"] == "manual_review_before_any_external_broker_action"
    assert report["research_state"] == "research_candidate"
    assert report["portfolio_review_state"] == "not_applicable"
    assert "gates" in report
    assert report["blocked_or_no_trade_summary"] == []
    saved = json.loads(Path(str(report["path"])).read_text(encoding="utf-8"))
    assert saved["execution_allowed"] is False
    assert "private thesis" in json.dumps(saved)


def test_legacy_manual_trade_adapter_warns_and_never_creates_authority(tmp_path: Path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        report = create_manual_trade_proposal_report([_signal()], _data_report(), run_id="run-1", report_dir=tmp_path)

    assert any(item.category is DeprecationWarning for item in caught)
    assert report["execution_allowed"] is False
    assert report["executable_authority"] is False
    assert report["broker_execution"] == "not_supported"
    assert report["proposals"]

