from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.types import ComponentScores, DataQualityIssue, DataQualityReport, SignalResult
from etf_cockpit.portfolio.proposals import create_manual_trade_proposal_report


def _scores() -> ComponentScores:
    return ComponentScores(
        momentum=0.0,
        trend=0.0,
        risk=0.0,
        rebalance=0.0,
        relative_strength=0.0,
        toto=0.0,
        timesfm=0.0,
        baseline_ml=0.0,
        chatgpt_thesis=0.0,
        cost_penalty=0.0,
        turnover_penalty=0.0,
        concentration_penalty=0.0,
    )


def _signal(action: str, blocked_by: list[str] | None = None, trade_value: float | None = 250.0) -> SignalResult:
    return SignalResult(
        run_id="test_run",
        signal_date=pd.Timestamp("2026-06-26").date(),
        etf_id="WORLD_CORE",
        action=action,  # type: ignore[arg-type]
        confidence=0.7,
        total_score=0.6,
        components=_scores(),
        blocked_by=blocked_by or [],
        warnings=[],
        reason_short="test",
        reason_long="test reason",
        horizon_primary="1-3 months",
        supporting_metrics={"reason_full": "test reason"},
        suggested_trade_value_eur=trade_value,
        suggested_new_weight=0.12,
    )


def test_trade_proposal_report_blocks_when_data_quality_blocks(tmp_path) -> None:
    report = create_manual_trade_proposal_report(
        [_signal("add_candidate")],
        DataQualityReport(
            as_of_date=pd.Timestamp("2026-06-26").date(),
            issues=[DataQualityIssue("WORLD_CORE", "block", "target_policy_violation", "blocked")],
        ),
        run_id="test_run",
        report_dir=tmp_path,
    )

    saved = json.loads(Path(str(report["path"])).read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["proposals"] == []
    assert saved["executable_authority"] is False
    assert saved["broker_execution"] == "not_supported"


def test_trade_proposal_report_includes_only_surviving_candidate_signals(tmp_path) -> None:
    report = create_manual_trade_proposal_report(
        [
            _signal("add_candidate", trade_value=500.0),
            _signal("trim_candidate", blocked_by=["risk_limit"], trade_value=400.0),
            _signal("manual_review", blocked_by=["portfolio_validation_block"], trade_value=None),
            _signal("no_trade", trade_value=None),
        ],
        DataQualityReport(as_of_date=pd.Timestamp("2026-06-26").date(), issues=[]),
        run_id="test_run",
        report_dir=tmp_path,
    )

    assert report["status"] == "draft"
    proposals = report["proposals"]
    assert isinstance(proposals, list)
    assert len(proposals) == 1
    assert proposals[0]["final_action"] == "add_candidate"
    assert proposals[0]["executable_authority"] is False
    assert len(report["blocked_or_no_trade_summary"]) == 3
