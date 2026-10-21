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
)


_NEGATIONS = frozenset({"no", "not", "never", "without", "cannot", "cant", "dont", "doesnt", "isnt", "wont", "nor", "non"})
_WORD_RE = re.compile(r"[a-z']+")
_CLAUSE_BREAK_RE = re.compile(r"[.;:!?\n\"{}\[\],]")
_PROHIBITIVE_SUFFIX_RE = re.compile(
    r"^(?:(?:is|are|was|were)\s+(?:(?:not|never)\s+"
    r"(?:allowed|permitted|recommended|authori[sz]ed|enabled)|prohibited|forbidden|disallowed|banned)"
    r"|(?:must|shall|should)\s+(?:not|never)\s+be\s+"
    r"(?:allowed|permitted|recommended|authori[sz]ed|enabled))\b"
)


def _is_negated(lowered: str, start: int, end: int) -> bool:
    """True when a phrase is plainly negated ("no automatic execution", "broker should not ..."), so
    anti-execution commentary is not mistaken for an instruction to trade."""

    before = lowered[max(0, start - 40) : start]
    clause = _CLAUSE_BREAK_RE.split(before)[-1]
    words = [word.replace("'", "") for word in _WORD_RE.findall(clause)]
    # Only adjacent negation, or negation of an explicit recommendation verb,
    # scopes over the action. "not hesitate to" is an affirmative instruction.
    if words and words[-1] in _NEGATIONS:
        return True
    if len(words) >= 2 and words[-2] in _NEGATIONS and words[-1] in {"recommend", "allow", "permit"}:
        return True
    phrase = lowered[start:end]
    after_clause = _CLAUSE_BREAK_RE.split(lowered[end : end + 40])[0]
    after = [word.replace("'", "") for word in _WORD_RE.findall(after_clause)]
    # Other phrases may be the subject of an explicit prohibition. Do not treat
    # arbitrary following negation ("not only", "not prohibited") as a denial.
    if phrase != "broker should" and _PROHIBITIVE_SUFFIX_RE.match(" ".join(after)):
        return True
    # Following negation must directly govern an action verb. Intervening words
    # such as "hesitate to" or "only" do not establish anti-execution commentary.
    return (
        phrase == "broker should"
        and len(after) >= 2
        and after[0] in {"not", "never"}
        and after[1] in {"act", "buy", "sell", "trade", "execute", "place", "submit"}
    )


def _recommends_execution(lowered: str) -> str | None:
    for phrase in BANNED_EXECUTION_PHRASES:
        index = lowered.find(phrase)
        while index != -1:
            if not _is_negated(lowered, index, index + len(phrase)):
                return phrase
            index = lowered.find(phrase, index + 1)
    return None


def validate_audit_text(raw_text: str, known_etf_ids: set[str]) -> ChatGPTAudit | ChatGPTAuditV2:
    phrase = _recommends_execution(raw_text.lower())
    if phrase is not None:
        raise AuditImportError(f"Audit rejected because it recommends automatic trading: {phrase}")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AuditImportError(f"Audit JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuditImportError("Audit JSON must contain an object")
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
