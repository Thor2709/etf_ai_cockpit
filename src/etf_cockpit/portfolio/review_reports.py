"""Non-executable portfolio review reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from etf_cockpit.core.paths import REPORTS_DIR
from etf_cockpit.core.types import DataQualityReport, SignalResult


def create_portfolio_review_report(
    signals: list[SignalResult],
    data_report: DataQualityReport,
    *,
    run_id: str,
    report_dir: Path = REPORTS_DIR,
) -> dict[str, object]:
    """Persist an advisory review report without creating transaction authority."""

    report_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc)
    rows: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    for signal in signals:
        payload = signal.to_v2_dict()
        row = {
            "etf_id": signal.etf_id,
            "research_state": payload["research_state"],
            "portfolio_review_state": payload["portfolio_review_state"],
            "analysis_status": payload["analysis_status"],
            "gate_policy_version": payload["gate_policy_version"],
            "gate_policy_checksum": payload["gate_policy_checksum"],
            "execution_allowed": False,
            "executable_authority": False,
            "final_action": signal.action,
            "reason": signal.reason_short,
            "reason_full": signal.reason_long,
            "blocked_by": list(signal.blocked_by),
            "warnings": list(signal.warnings),
            "suggested_trade_value_eur": signal.suggested_trade_value_eur,
        }
        if signal.blocked_by or signal.action in {"manual_review", "no_trade"}:
            blocked.append(row)
        elif signal.action in {"buy", "add", "trim", "sell", "add_candidate", "trim_candidate"}:
            rows.append(row)
    status = "blocked" if not data_report.analysis_allowed else ("draft" if rows else "no_action")
    if not data_report.analysis_allowed:
        rows = []
    first = signals[0].to_v2_dict() if signals else {}
    report: dict[str, object] = {
        "created_at": created_at.isoformat(),
        "run_id": run_id,
        "as_of_date": data_report.as_of_date.isoformat(),
        "status": status,
        "message": "Advisory review only; no broker or execution authority is created.",
        "research_state": first.get("research_state", "manual_review"),
        "portfolio_review_state": first.get("portfolio_review_state", "not_applicable"),
        "analysis_status": first.get("analysis_status", "unavailable"),
        "gates": first.get("gates", []),
        "executable_authority": False,
        "execution_allowed": False,
        "broker_execution": "not_supported",
        "required_user_action": "manual_review_before_any_external_broker_action",
        "proposals": rows,
        "blocked_or_no_trade_summary": blocked,
    }
    path = report_dir / f"portfolio_review_{created_at:%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report | {"path": str(path)}


__all__ = ["create_portfolio_review_report"]
