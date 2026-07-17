from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import warnings

import pandas as pd

from etf_cockpit.core.types import ComponentScores, DataQualityReport, SignalResult
from etf_cockpit.portfolio.proposals import create_manual_trade_proposal_report
from etf_cockpit.portfolio import review_reports
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
    assert "review_rows" in report
    assert "proposals" not in report
    assert "final_action" not in json.dumps(report)
    assert "suggested_trade_value_eur" not in json.dumps(report)
    assert report["policy_version"]
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


def test_release_review_report_uses_neutral_recommendations(tmp_path: Path) -> None:
    signals = [_signal(action) for action in ("buy", "sell", "add_candidate", "trim_candidate")]
    report = create_portfolio_review_report(signals, _data_report(), run_id="run-1", report_dir=tmp_path)
    encoded = json.dumps(report)
    assert all(token not in encoded for token in ("buy", "sell", "add_candidate", "trim_candidate"))
    assert {row["review_recommendation"] for row in report["review_rows"]} == {
        "consider_increase",
        "consider_decrease",
    }


def test_release_review_report_preserves_signal_policy_evidence(tmp_path: Path, monkeypatch) -> None:
    signal = replace(_signal(), gate_policy_version="historic", gate_policy_checksum="h" * 64)
    monkeypatch.setattr(
        review_reports,
        "load_gate_policy",
        lambda: SimpleNamespace(
            policy=SimpleNamespace(policy_version="current"),
            diagnostic_mode=False,
            checksum="c" * 64,
        ),
    )
    report = create_portfolio_review_report([signal], _data_report(), run_id="run-1", report_dir=tmp_path)
    assert report["policy_version"] == "historic"
    assert report["policy_checksum"] == "h" * 64


def test_review_rows_keep_the_canonical_score_when_present(tmp_path: Path) -> None:
    from dataclasses import replace

    from etf_cockpit.signals.canonical_scoring import canonical_score_from_signal_row
    from etf_cockpit.core.config import load_config

    canonical = canonical_score_from_signal_row(
        {"etf_id": "WORLD_CORE", "score_momentum": 0.2, "score_trend": 0.3, "score_risk": 0.4},
        load_config(),
        "2026-06-26",
    )
    report = create_portfolio_review_report([replace(_signal(), canonical_score=canonical)], _data_report(), run_id="run-1", report_dir=tmp_path)

    row = report["review_rows"][0]
    assert row["canonical_score"]["formula_version"] == "score-engine-v3.0.0"
