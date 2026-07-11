from __future__ import annotations

from datetime import datetime, timezone

from etf_cockpit.operations import OperationalEvent
from etf_cockpit.operations.event_store import current_activity_view


def _event(sequence_number: int, status: str) -> OperationalEvent:
    return OperationalEvent(
        event_id=f"event-{sequence_number}",
        session_id="session-1",
        sequence_number=sequence_number,
        timestamp_utc=datetime(2026, 7, 11, tzinfo=timezone.utc),
        event_type="activity_update",
        status=status,
        action_id="action-1",
    )


def test_operational_event_public_model_accepts_legacy_hash_fields() -> None:
    event = OperationalEvent(
        session_id="legacy-session",
        sequence_number=1,
        timestamp_utc=datetime(2026, 7, 11, tzinfo=timezone.utc),
        event_type="session_start",
    )

    assert event.event_id == ""
    assert event.prior_event_hash is None
    assert event.event_hash is None


def test_current_activity_view_uses_the_latest_sequence() -> None:
    view = current_activity_view([_event(2, "completed"), _event(1, "queued")])

    assert view.status == "completed"
    assert view.sequence_number == 2
    assert view.action_id == "action-1"


def test_current_activity_view_is_idle_without_events() -> None:
    assert current_activity_view([]).status == "idle"
