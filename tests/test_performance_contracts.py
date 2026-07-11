from __future__ import annotations

from pathlib import Path

from etf_cockpit.core.timing import timed_step


def test_timed_step_records_duration_and_slow_warning(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    with timed_step("action-1", "read-store", events.append, store_path=tmp_path / "timings.jsonl", slow_ms=0):
        pass
    assert events[0]["action_id"] == "action-1"
    assert events[0]["step"] == "read-store"
    assert events[0]["duration_ms"] >= 0
    assert events[0]["slow"] is True
    assert (tmp_path / "timings.jsonl").exists()
