from __future__ import annotations

from pathlib import Path

from etf_cockpit.core.timing import read_timing_records, record_cache_event, timed_step


def test_timed_step_records_duration_and_slow_warning(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    with timed_step("action-1", "read-store", events.append, store_path=tmp_path / "timings.jsonl", slow_ms=0):
        pass
    assert events[0]["action_id"] == "action-1"
    assert events[0]["step"] == "read-store"
    assert events[0]["duration_ms"] >= 0
    assert events[0]["slow"] is True
    assert (tmp_path / "timings.jsonl").exists()


def test_timing_diagnostics_parse_duration_slow_and_cache_events(tmp_path: Path) -> None:
    path = tmp_path / "timings.jsonl"
    with timed_step("startup-1", "snapshot", store_path=path, slow_ms=0):
        pass
    record_cache_event("forecast", "hit", action_id="forecast-1", store_path=path)
    record_cache_event("forecast", "invalidation", action_id="forecast-1", store_path=path)
    records = read_timing_records(path)
    assert records[0]["duration_ms"] >= 0
    assert records[0]["slow"] is True
    assert {record["cache_status"] for record in records[1:]} == {"hit", "invalidation"}
