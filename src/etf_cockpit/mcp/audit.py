"""One-record-per-call MCP audit trail backed by the local session log.

Open defaults: client_id is "local" and the in-memory inspection buffer retains the latest
1,000 records; the persistent session log receives the complete begin/end event pair.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from etf_cockpit.core.session_log import log_event, new_action_id
from etf_cockpit.mcp.serialise import canonical_json


@dataclass(frozen=True)
class AuditRecord:
    tool: str
    tier: str
    args_hash: str
    outcome: str
    output_hash: str | None = None
    duration_ms: float = 0.0
    client_id: str = "local"
    reason_code: str | None = None
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AuditRecorder:
    """Append one scrubbed summary record for each dispatched or refused tool call."""

    def __init__(self, sink: Callable[[AuditRecord], None] | None = None) -> None:
        self.records: deque[AuditRecord] = deque(maxlen=1000)
        self._sink = sink if sink is not None else _session_log_sink

    def record(self, record: AuditRecord) -> None:
        self.records.append(record)
        self._sink(record)


def hash_arguments(arguments: object) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(arguments).encode("utf-8")).hexdigest()


def _session_log_sink(record: AuditRecord) -> None:
    action_id = new_action_id("mcp")
    log_event(
        event_type="mcp_tool_begin",
        action_id=action_id,
        component="mcp",
        operation=record.tool,
        status="started",
        input_summary={"args_sha256": record.args_hash},
        extra={"tier": record.tier, "client_id": record.client_id, "reason_code": record.reason_code, "occurred_at": record.occurred_at},
    )
    log_event(
        event_type="mcp_tool_end",
        action_id=action_id,
        component="mcp",
        operation=record.tool,
        status=record.outcome,
        duration_ms=record.duration_ms,
        input_summary={"args_sha256": record.args_hash},
        output_summary={"sha256": record.output_hash} if record.output_hash else {},
        extra={"tier": record.tier, "client_id": record.client_id, "reason_code": record.reason_code, "occurred_at": record.occurred_at},
    )
