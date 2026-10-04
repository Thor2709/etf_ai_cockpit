"""Terminal activity must be published before the activity slot is released.

Readers poll ``current_activity is None`` without the lock and then read
``recent_activity``/``last_message``; releasing the slot first lets them observe
an empty history.
"""

from __future__ import annotations

import pytest

from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


@pytest.fixture
def snapshot():
    """Build the snapshot per test: a snapshot cached across tests can point at a deleted project root."""

    return build_snapshot()


class _ObservedState(AppState):
    """AppState that records what a lock-free reader would see on slot release."""

    def __setattr__(self, name: str, value: object) -> None:
        if name == "current_activity" and value is None and getattr(self, "current_activity", None) is not None:
            observed = self.__dict__.setdefault("_released_with", [])
            observed.append(([item.action_id for item in self.recent_activity], self.last_message))
        super().__setattr__(name, value)


def _state(snapshot) -> _ObservedState:
    return _ObservedState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_finish_activity_publishes_entry_before_releasing_slot(snapshot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", tmp_path / "activity.jsonl")
    state = _state(snapshot)
    entry = state.begin_activity("Publish order success")

    state.finish_activity("Done message", expected_action_id=entry.action_id)

    assert state.current_activity is None
    assert state.__dict__["_released_with"] == [([entry.action_id], "Done message")]


def test_fail_activity_publishes_entry_before_releasing_slot(snapshot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", tmp_path / "activity.jsonl")
    state = _state(snapshot)
    entry = state.begin_activity("Publish order failure")

    failed = state.fail_activity("Publish order failure", TimeoutError("provider timeout"), expected_action_id=entry.action_id)

    assert state.current_activity is None
    assert state.__dict__["_released_with"] == [([entry.action_id], failed.message)]
