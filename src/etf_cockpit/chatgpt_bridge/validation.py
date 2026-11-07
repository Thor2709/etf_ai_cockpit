from __future__ import annotations

import json
from pathlib import Path
import re

from pydantic import ValidationError

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
    "place any orders",
    "execute trades automatically",
)


_CLAUSE_BREAK_RE = re.compile(r"[.;!?]")
_EXECUTION_ACTION = (
    r"(?:automatic execution|execute (?:trades )?automatically|place (?:the order|any orders)"
    r"|submit order|auto trade|autotrade)"
)
_PROHIBITIVE_PREDICATE = (
    r"(?:(?:is|are|was|were)\s+(?:(?:not|never)\s+"
    r"(?:allowed|permitted|recommended|authori[sz]ed|enabled)|prohibited|forbidden|disallowed|banned)"
    r"|(?:must|shall|should)\s+(?:not|never)\s+be\s+"
    r"(?:allowed|permitted|recommended|authori[sz]ed|enabled))"
)
_BROKER_PROHIBITION = r"(?:the )?broker should (?:not|never) act(?: on it)?"
_EXPLICIT_PROHIBITION_RE = re.compile(
    rf"(?:(?:you )?(?:do not|must not|shall not|should not|never|cannot) "
    rf"(?:{_EXECUTION_ACTION}|place the order without review)"
    rf"|(?:this note does not|do not) (?:recommend|allow|permit) {_EXECUTION_ACTION}"
    rf"|(?:there is )?no {_EXECUTION_ACTION}(?:, and {_BROKER_PROHIBITION})?"
    rf"|(?:to |the instruction to )?{_EXECUTION_ACTION} {_PROHIBITIVE_PREDICATE}"
    rf"|{_BROKER_PROHIBITION})"
)


def _recommends_execution(lowered: str) -> str | None:
    # Only complete, explicit prohibition clauses are safe. Unknown qualifiers,
    # indirect negation and mixed instructions fail closed rather than guessing scope.
    # Line breaks are whitespace within phrases and prohibitions, not clause boundaries.
    lowered = " ".join(lowered.split())
    for clause in _CLAUSE_BREAK_RE.split(lowered):
        clause = clause.strip()
        for phrase in BANNED_EXECUTION_PHRASES:
            if phrase in clause and not _EXPLICIT_PROHIBITION_RE.fullmatch(clause):
                return phrase
    return None


def validate_audit_text(raw_text: str, known_etf_ids: set[str]) -> ChatGPTAudit | ChatGPTAuditV2:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AuditImportError(f"Audit JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuditImportError("Audit JSON must contain an object")
    # Inspect decoded strings independently: JSON punctuation and escape sequences
    # must not manufacture clause boundaries or hide execution phrases.
    pending = list(payload.values())
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            phrase = _recommends_execution(value.lower())
            if phrase is not None:
                raise AuditImportError(f"Audit rejected because it recommends automatic trading: {phrase}")
    try:
        audit = ChatGPTAuditV2.model_validate(payload) if str(payload.get("schema_version")) == "2.0" else ChatGPTAudit.model_validate(payload)
    except ValidationError as exc:
        raise AuditImportError(f"Audit JSON does not match the supported schema: {exc}") from exc
    referenced_ids = {item.etf_id for item in audit.portfolio_actions} | {item.etf_id for item in audit.ignored_signals}
    unknown = referenced_ids - known_etf_ids
    if unknown:
        raise AuditImportError(f"Audit references unknown ETF ids: {sorted(unknown)}")
    return audit


def validate_audit_file(path: Path, known_etf_ids: set[str]) -> ChatGPTAudit | ChatGPTAuditV2:
    return validate_audit_text(path.read_text(encoding="utf-8"), known_etf_ids)
