from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from etf_cockpit.core.logging import append_jsonl
from etf_cockpit.core.paths import REPORTS_DIR
from etf_cockpit.core.types import DataQualityReport, SignalResult


def log_trade_proposals(signals: list[SignalResult], run_id: str) -> list[dict[str, object]]:
    proposals = []
    for signal in signals:
        if signal.action in {"buy", "add", "trim", "sell", "add_candidate", "trim_candidate"} and signal.suggested_trade_value_eur:
            proposals.append(
                {
                    "etf_id": signal.etf_id,
                    "action": signal.action,
                    "suggested_trade_value_eur": signal.suggested_trade_value_eur,
                    "suggested_new_weight": signal.suggested_new_weight,
                    "confidence": signal.confidence,
                    "reason": signal.reason_short,
                }
            )
    append_jsonl("trade_proposals.jsonl", "manual_trade_proposals", {"proposals": proposals}, run_id=run_id)
    return proposals


def create_manual_trade_proposal_report(
    signals: list[SignalResult],
    data_report: DataQualityReport,
    *,
    run_id: str,
    report_dir: Path = REPORTS_DIR,
) -> dict[str, object]:
    """Create an advisory-only proposal report from already-gated signals."""

    timestamp = datetime.now(timezone.utc)
    report_dir.mkdir(parents=True, exist_ok=True)
    eligible = [_proposal_row(signal) for signal in signals if _is_eligible_proposal_signal(signal)]
    if not data_report.trading_allowed:
        status = "blocked"
        message = "No manual trade proposal created because current data or risk gates require manual review."
        eligible = []
    elif not eligible:
        status = "no_action"
        message = "No manual trade proposal created because no signal survived gates with a useful trade size."
    else:
        status = "draft"
        message = f"Created {len(eligible)} advisory manual trade proposal(s). Review before any broker action."

    blocked_summary = [
        {
            "etf_id": signal.etf_id,
            "final_action": signal.action,
            "blocked_by": signal.blocked_by,
            "reason_full": signal.supporting_metrics.get("reason_full", signal.reason_long),
        }
        for signal in signals
        if signal.blocked_by or signal.action in {"manual_review", "no_trade"}
    ]
    payload: dict[str, object] = {
        "created_at": timestamp.isoformat(),
        "run_id": run_id,
        "as_of_date": data_report.as_of_date.isoformat(),
        "status": status,
        "message": message,
        "executable_authority": False,
        "broker_execution": "not_supported",
        "required_user_action": "manual_review_before_any_external_broker_action",
        "proposals": eligible,
        "blocked_or_no_trade_summary": blocked_summary,
    }
    path = report_dir / f"trade_proposal_{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    append_jsonl(
        "trade_proposals.jsonl",
        "manual_trade_proposal_report",
        {
            "status": status,
            "message": message,
            "proposal_count": len(eligible),
            "report_path": str(path),
            "executable_authority": False,
        },
        run_id=run_id,
    )
    return payload | {"path": str(path)}


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
    }
