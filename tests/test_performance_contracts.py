from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.core.timing import read_timing_records, record_cache_event, timed_step, timing_summary


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


def test_timing_summary_reads_latest_valid_records_across_invalid_tail(tmp_path: Path) -> None:
    path = tmp_path / "timings.jsonl"
    lines = [
        '{"duration_ms": 1, "step": "old"}',
        '{"duration_ms": 2, "step": "newer"}',
        '{"event_type": "cache", "cache_status": "hit"}',
        "[]",
        "",
        "{corrupt",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    summary = timing_summary(path, limit=2)

    assert summary["records"] == read_timing_records(path)[-2:]
    assert summary["durations_ms"] == [2.0]
    assert summary["cache_counts"] == {"hit": 1, "miss": 0, "invalidation": 0}


def test_timing_summary_handles_oversized_line_across_chunks(tmp_path: Path) -> None:
    path = tmp_path / "timings.jsonl"
    oversized = {
        "duration_ms": 1,
        "detail": "x" * (128 * 1024),
        "step": "oversized",
    }
    lines = [
        '{"duration_ms": 0, "step": "old"}',
        json.dumps(oversized),
        '{"duration_ms": 2, "step": "latest"}',
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    assert timing_summary(path, limit=2)["records"] == read_timing_records(path)[-2:]


def test_timing_summary_preserves_unicode_crlf_and_mixed_record_parity(tmp_path: Path) -> None:
    path = tmp_path / "timings.jsonl"
    path.write_bytes(
        b'{"duration_ms": 1, "step": "caf\xc3\xa9"}\r\n'
        b'{"ignored": true}\r\n'
        b'{"event_type": "cache", "cache_status": "miss", "detail": "na\xffve"}\r\n'
        b"{bad\r\n"
        b'{"duration_ms": 3, "step": "\xe6\x9d\xb1\xe4\xba\xac"}\r\n'
    )

    assert timing_summary(path, limit=2)["records"] == read_timing_records(path)[-2:]


def test_timing_summary_missing_file_and_minimum_limit(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    assert timing_summary(missing)["records"] == []

    path = tmp_path / "timings.jsonl"
    path.write_text('{"duration_ms": 1}\n{"duration_ms": 2}\n', encoding="utf-8")
    assert timing_summary(path, limit=0)["records"] == [{"duration_ms": 2}]
