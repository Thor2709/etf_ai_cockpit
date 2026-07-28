from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from etf_cockpit.core.paths import LOG_DIR


@contextmanager
def timed_step(
    action_id: str,
    step_name: str,
    event_logger: Callable[[dict[str, object]], None] | None = None,
    *,
    store_path: Path | None = None,
    slow_ms: float = 1000,
) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "action_id": action_id,
            "step": step_name,
            "duration_ms": round(duration_ms, 3),
            "slow": duration_ms >= slow_ms,
        }
        logger = event_logger
        if logger is None and store_path is None:
            logger = _session_timing_logger
        if logger is not None:
            try:
                logger(payload)
            except Exception:
                pass
        destination = store_path or (LOG_DIR / "timings.jsonl")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
                handle.flush()
        except Exception:
            pass


def record_cache_event(
    cache_name: str,
    cache_status: str,
    *,
    action_id: str = "",
    store_path: Path | None = None,
    detail: str = "",
) -> dict[str, object]:
    """Persist a normalised cache hit/miss/invalidation diagnostic event."""
    status = str(cache_status).strip().lower()
    if status not in {"hit", "miss", "invalidation"}:
        raise ValueError(f"unsupported cache status: {cache_status}")
    payload: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event_type": "cache",
        "action_id": str(action_id),
        "cache_name": str(cache_name),
        "cache_status": status,
        "detail": str(detail),
    }
    destination = store_path or (LOG_DIR / "timings.jsonl")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
    except Exception:
        pass
    return payload


def _session_timing_logger(payload: dict[str, object]) -> None:
    from etf_cockpit.core.session_log import log_event

    log_event(
        event_type="timed_step",
        severity="warning" if payload.get("slow") else "info",
        action_id=str(payload.get("action_id") or ""),
        component="timing",
        operation=str(payload.get("step") or ""),
        status="slow" if payload.get("slow") else "complete",
        duration_ms=payload.get("duration_ms"),
        output_summary={"step": payload.get("step"), "slow": payload.get("slow")},
    )


def _timing_record_from_line(line: str) -> dict[str, object] | None:
    try:
        item = json.loads(line)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(item, dict):
        return None
    if "duration_ms" in item or item.get("event_type") == "cache":
        return item
    return None


def read_timing_records(path: Path | None = None) -> list[dict[str, object]]:
    """Read valid timing/cache events while ignoring corrupt tail lines."""
    source = path or (LOG_DIR / "timings.jsonl")
    try:
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    records: list[dict[str, object]] = []
    for line in lines:
        item = _timing_record_from_line(line)
        if item is not None:
            records.append(item)
    return records


def _read_timing_tail(
    source: Path,
    *,
    limit: int,
    chunk_size: int = 64 * 1024,
) -> list[dict[str, object]]:
    """Read the newest valid timing/cache records without scanning full history."""
    records: list[dict[str, object]] = []
    try:
        with source.open("rb") as handle:
            handle.seek(0, 2)
            position = handle.tell()
            carry = b""
            while position > 0 and len(records) < limit:
                start = max(0, position - chunk_size)
                handle.seek(start)
                block = handle.read(position - start)
                parts = (block + carry).split(b"\n")
                if start:
                    carry = parts.pop(0)
                for raw_line in reversed(parts):
                    item = _timing_record_from_line(raw_line.decode("utf-8", errors="replace"))
                    if item is not None:
                        records.append(item)
                        if len(records) >= limit:
                            break
                position = start
    except Exception:
        return []
    records.reverse()
    return records


def timing_summary(path: Path | None = None, *, limit: int = 50) -> dict[str, object]:
    source = path or (LOG_DIR / "timings.jsonl")
    records = _read_timing_tail(source, limit=max(1, int(limit)))
    durations = [float(record["duration_ms"]) for record in records if "duration_ms" in record]
    slow_steps = [record for record in records if bool(record.get("slow"))]
    cache_events = [record for record in records if record.get("event_type") == "cache"]
    return {
        "records": records,
        "durations_ms": durations,
        "slow_steps": slow_steps,
        "cache_events": cache_events,
        "cache_counts": {
            status: sum(1 for record in cache_events if record.get("cache_status") == status)
            for status in ("hit", "miss", "invalidation")
        },
    }
