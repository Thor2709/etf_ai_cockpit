from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit
from etf_cockpit.chatgpt_bridge.validation import validate_audit_file
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.logging import append_jsonl
from etf_cockpit.core.paths import CHATGPT_IMPORTS_DIR


def import_audit_json(path: Path, config: AppConfig) -> ChatGPTAudit:
    audit = validate_audit_file(path, set(config.universe.enabled_ids))
    CHATGPT_IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = CHATGPT_IMPORTS_DIR / f"chatgpt_audit_{audit.review_date}.json"
    convictions = [action.conviction for action in audit.portfolio_actions]
    note = {
        "source": str(path),
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": audit.review_date,
        "confidence": sum(convictions) / len(convictions) if convictions else 0.0,
        "executable_authority": False,
        "audit": audit.model_dump(),
    }
    out.write_text(json.dumps(note, indent=2), encoding="utf-8")
    append_jsonl(
        "chatgpt_audits.jsonl",
        "chatgpt_audit_imported",
        {key: value for key, value in note.items() if key != "audit"} | {"schema_version": audit.schema_version},
    )
    return audit
