from __future__ import annotations

import json

import pytest

from etf_cockpit.chatgpt_bridge.validation import validate_audit_text
from etf_cockpit.core.exceptions import AuditImportError


def _valid_payload() -> dict:
    return {
        "schema_version": "1.0",
        "review_date": "2026-06-26",
        "overall_view": "neutral",
        "portfolio_actions": [
            {
                "etf_id": "WORLD_CORE",
                "action": "hold",
                "conviction": 0.6,
                "reason_short": "Evidence is balanced.",
                "main_supporting_metrics": ["trend_200"],
                "main_risks": ["cost"],
                "blocked_by": [],
                "manual_checks": ["review data freshness"],
            }
        ],
        "ignored_signals": [],
        "risk_flags": [],
        "model_audit": {
            "toto_usefulness": "unavailable",
            "timesfm_usefulness": "unavailable",
            "baseline_comparison": "baseline first",
            "overfitting_concerns": [],
        },
        "dashboard_notes": ["ChatGPT is audit commentary only."],
    }


def test_chatgpt_json_validation_accepts_known_ids() -> None:
    audit = validate_audit_text(json.dumps(_valid_payload()), {"WORLD_CORE"})
    assert audit.overall_view == "neutral"


def test_chatgpt_json_validation_rejects_unknown_ids() -> None:
    payload = _valid_payload()
    payload["portfolio_actions"][0]["etf_id"] = "UNKNOWN"
    with pytest.raises(AuditImportError):
        validate_audit_text(json.dumps(payload), {"WORLD_CORE"})


def test_chatgpt_json_validation_rejects_automatic_trading() -> None:
    payload = _valid_payload()
    payload["dashboard_notes"] = ["Please place the order automatically."]
    with pytest.raises(AuditImportError):
        validate_audit_text(json.dumps(payload), {"WORLD_CORE"})
