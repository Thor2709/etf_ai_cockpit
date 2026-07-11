from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.core.session_log import append_event
from etf_cockpit.operations.event_store import load_events_with_tail_recovery


def test_operational_append_redacts_nested_secrets_before_hashing(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"

    append_event(
        {
            "session_id": "session-1",
            "sequence_number": 1,
            "timestamp_utc": "2026-07-11T00:00:00+00:00",
            "event_type": "activity_update",
            "status": "running",
            "input_summary": {
                "nested": {"api_key": "SHOULD_NOT_APPEAR"},
                "message": "authorization: Bearer SHOULD_NOT_APPEAR",
            },
        },
        path=path,
    )

    text = path.read_text(encoding="utf-8")
    row = json.loads(text)
    events, _ = load_events_with_tail_recovery(path)

    assert "SHOULD_NOT_APPEAR" not in text
    assert row["input_summary"]["nested"]["api_key"] == "***redacted***"
    assert "Bearer ***redacted***" in row["input_summary"]["message"]
    assert events[0].event_hash
