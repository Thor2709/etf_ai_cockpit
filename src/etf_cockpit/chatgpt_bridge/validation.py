from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit, ChatGPTAuditV2
from etf_cockpit.core.exceptions import AuditImportError

BANNED_EXECUTION_PHRASES = (
    "automatic execution",
    "execute automatically",
    "place the order",
    "submit order",
    "broker should",
    "auto trade",
    "autotrade",
)


def validate_audit_text(raw_text: str, known_etf_ids: set[str]) -> ChatGPTAudit | ChatGPTAuditV2:
    lowered = raw_text.lower()
    for phrase in BANNED_EXECUTION_PHRASES:
        if phrase in lowered:
            raise AuditImportError(f"Audit rejected because it recommends automatic trading: {phrase}")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AuditImportError(f"Audit JSON is invalid: {exc}") from exc
    audit = ChatGPTAuditV2.model_validate(payload) if str(payload.get("schema_version")) == "2.0" else ChatGPTAudit.model_validate(payload)
    referenced_ids = {item.etf_id for item in audit.portfolio_actions} | {item.etf_id for item in audit.ignored_signals}
    unknown = referenced_ids - known_etf_ids
    if unknown:
        raise AuditImportError(f"Audit references unknown ETF ids: {sorted(unknown)}")
    return audit


def validate_audit_file(path: Path, known_etf_ids: set[str]) -> ChatGPTAudit:
    return validate_audit_text(path.read_text(encoding="utf-8"), known_etf_ids)
