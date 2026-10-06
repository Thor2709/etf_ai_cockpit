"""Read-only access to local quality-programme evidence for the UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_REPORT = Path("artifacts/quality/latest/quality-programme.json")


def load_quality_programme_report(root: Path, path: Path | None = None) -> dict[str, Any]:
    """Load the last local quality report without running validation in the UI."""

    report_path = (path or root / DEFAULT_REPORT).resolve()
    try:
        value = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "not_run",
            "failures": [f"quality report unavailable: {type(exc).__name__}"],
            "suites": [],
            "report_path": str(report_path),
        }
    if not isinstance(value, dict):
        return {
            "status": "blocked",
            "failures": ["quality report root is not an object"],
            "suites": [],
            "report_path": str(report_path),
        }
    value.setdefault("status", "blocked")
    value.setdefault("failures", [])
    value.setdefault("suites", [])
    value["report_path"] = str(report_path)
    return value


__all__ = ["DEFAULT_REPORT", "load_quality_programme_report"]
