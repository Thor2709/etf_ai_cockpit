from types import SimpleNamespace

import pytest

from etf_cockpit.app.state import AppState
from etf_cockpit.core.workflow import WorkflowTransitionError


def test_repeated_cancel_preserves_worker_reservation_and_terminal_evidence():
    state = AppState(snapshot=SimpleNamespace(), selected_etf="")
    entry = state.begin_activity("Forecast models", "Starting")
    state.cancel_activity(expected_action_id=entry.action_id)
    history = tuple(state.recent_activity)
    finished_at = entry.finished_at
    assert state.cancel_activity(expected_action_id=entry.action_id) is entry
    assert tuple(state.recent_activity) == history
    assert entry.finished_at == finished_at
    assert state.current_activity is entry
    assert state.last_message == "Cancelled by user"
    assert state.workflow_controller.is_cancel_requested(entry.action_id)
    with pytest.raises(WorkflowTransitionError, match="another action"):
        state.cancel_activity(expected_action_id="stale-action")
    state.release_activity(entry.action_id)
    assert state.current_activity is None
