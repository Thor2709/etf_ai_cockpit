from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from etf_cockpit.app.state import AppState
from etf_cockpit.operations.models import OperationalEvent
from etf_cockpit.operations.event_store import (
    append_operational_event,
    load_events_with_tail_recovery,
)


FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _event(sequence_number: int, *, status: str = "running") -> OperationalEvent:
    return OperationalEvent(
        event_id=f"requested-{sequence_number}",
        session_id="session-1",
        sequence_number=sequence_number,
        timestamp_utc=datetime(2026, 7, 11, 2, sequence_number, tzinfo=timezone.utc),
        event_type="activity_update",
        status=status,
        component="test",
        action_id="action-1",
    )


def test_append_operational_events_builds_an_ordered_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"

    append_operational_event(_event(1), path=path)
    append_operational_event(_event(2, status="completed"), path=path)
    events, recovery = load_events_with_tail_recovery(path)

    assert recovery.quarantined_tail is False
    assert [event.sequence_number for event in events] == [1, 2]
    assert all(event.event_id for event in events)
    assert events[0].prior_event_hash is None
    assert events[0].event_hash
    assert events[1].prior_event_hash == events[0].event_hash
    assert events[1].event_hash != events[0].event_hash


def test_event_store_recovers_only_the_incomplete_jsonl_tail(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    fixture = FIXTURE_DIR / "session_incomplete_tail.jsonl"
    path.write_bytes(fixture.read_bytes() + b'{"event_id":')

    events, recovery = load_events_with_tail_recovery(path)

    assert [event.event_id for event in events] == ["event-1"]
    assert recovery.quarantined_tail is True
    assert recovery.quarantine_path is not None
    assert recovery.quarantine_path.read_text(encoding="utf-8") == '{"event_id":'
    assert path.read_text(encoding="utf-8").endswith('"status":"running"}\n')


def test_event_store_does_not_silently_skip_a_malformed_complete_row(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text('{"event_id":}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="complete JSONL row"):
        load_events_with_tail_recovery(path)


def test_event_store_reports_a_schema_invalid_complete_row_as_an_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text('{"event_id":"incomplete-schema"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed complete JSONL row 1"):
        load_events_with_tail_recovery(path)


def test_app_state_activity_view_is_derived_from_session_events(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "session.jsonl"
    append_operational_event(_event(1, status="queued"), path=path)
    append_operational_event(_event(2, status="completed"), path=path)
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", path)

    state = object.__new__(AppState)

    assert state.current_activity_view().status == "completed"


def test_append_failure_is_best_effort(tmp_path: Path) -> None:
    directory = tmp_path / "not-a-jsonl-file"
    directory.mkdir()

    assert append_operational_event(_event(1), path=directory) is None
