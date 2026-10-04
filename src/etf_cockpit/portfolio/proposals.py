from __future__ import annotations

from pathlib import Path
import warnings

from etf_cockpit.core.logging import append_jsonl
from etf_cockpit.core.paths import REPORTS_DIR
from etf_cockpit.core.types import DataQualityReport, SignalResult
from etf_cockpit.portfolio.review_reports import create_portfolio_review_report


def create_manual_trade_proposal_report(
    signals: list[SignalResult],
    data_report: DataQualityReport,
    *,
    run_id: str,
    report_dir: Path = REPORTS_DIR,
) -> dict[str, object]:
    """Deprecated compatibility adapter for the non-executable review report."""

    warnings.warn(
        "create_manual_trade_proposal_report is deprecated; use create_portfolio_review_report",
        DeprecationWarning,
        stacklevel=2,
    )
    report = create_portfolio_review_report(signals, data_report, run_id=run_id, report_dir=report_dir)
    legacy_rows = [
        _proposal_row(signal)
        for signal in signals
        if _is_eligible_proposal_signal(signal) and data_report.analysis_allowed
    ]
    append_jsonl(
        "portfolio_review_adapter.jsonl",
        "deprecated_portfolio_proposal_adapter",
        {
            "report_path": report.get("path"),
            "legacy_row_count": len(legacy_rows),
            "execution_allowed": False,
            "executable_authority": False,
        },
        run_id=run_id,
    )
    return report | {"proposals": legacy_rows}


def _is_eligible_proposal_signal(signal: SignalResult) -> bool:
    return (
        signal.action in {"add_candidate", "trim_candidate"}
        and not signal.blocked_by
        and signal.suggested_trade_value_eur is not None
        and abs(signal.suggested_trade_value_eur) > 0
    )


def _proposal_row(signal: SignalResult) -> dict[str, object]:
    return {
        "etf_id": signal.etf_id,
        "final_action": signal.action,
        "suggested_trade_value_eur": signal.suggested_trade_value_eur,
        "suggested_new_weight": signal.suggested_new_weight,
        "confidence": signal.confidence,
        "reason": signal.supporting_metrics.get("reason_full", signal.reason_long),
        "blocked_by": signal.blocked_by,
        "executable_authority": False,
        "canonical_score": signal.canonical_score.as_dict() if signal.canonical_score else None,
    }
