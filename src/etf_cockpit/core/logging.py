from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etf_cockpit.core.constants import APP_VERSION
from etf_cockpit.core.paths import LOG_DIR, ensure_project_dirs


def configure_logging() -> None:
    ensure_project_dirs()
    logging.basicConfig(
        filename=LOG_DIR / "app.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def append_jsonl(log_name: str, event_type: str, payload: dict[str, Any], run_id: str | None = None) -> None:
    ensure_project_dirs()
    path = LOG_DIR / log_name
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "app_version": APP_VERSION,
        "event_type": event_type,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str, sort_keys=True) + "\n")


def read_tail(path: Path, max_lines: int = 50) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]
