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
        if event_logger is not None:
            try:
                event_logger(payload)
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
