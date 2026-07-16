"""Generate deterministic programme status JSON and progress Markdown."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from scripts.issue_registry_core import (
        PROGRESS_PATH,
        REGISTRY_PATH,
        STATUS_PATH,
        deterministic_json,
        ready_records,
    )
except ModuleNotFoundError:
    from issue_registry_core import (
        PROGRESS_PATH,
        REGISTRY_PATH,
        STATUS_PATH,
        deterministic_json,
        ready_records,
    )


def status_payload(registry: dict) -> dict:
    records = list(registry.get("records", []))
    statuses = Counter(str(record.get("programme_status", "")) for record in records)
    phases = Counter(str(record.get("phase", "")) for record in records)
    return {
        "schema_version": "1.0",
        "source_registry_sha256": __import__("hashlib").sha256(
            deterministic_json(registry)
        ).hexdigest(),
        "counts": dict(sorted(statuses.items())),
        "phase_counts": dict(sorted(phases.items())),
        "ready_issue_ids": [record["canonical_id"] for record in ready_records(registry)],
        "blocked_issue_ids": [
            record["canonical_id"]
            for record in records
            if record.get("programme_status") == "blocked"
        ],
        "policy": registry.get("policy", {}),
    }


def progress_markdown(payload: dict, registry: dict) -> str:
    lines = [
        "# Completion programme progress",
        "",
        "This file is generated from `issues/issue_registry.json`; it contains no wall-clock state.",
        "",
        "## Status summary",
        "",
        "| Programme status | Records |",
        "|---|---:|",
    ]
    for status, count in payload["counts"].items():
        lines.append(f"| `{status}` | {count} |")
    lines.extend(["", "## Ready issues", ""])
    ready_ids = payload["ready_issue_ids"]
    lines.append(", ".join(f"`{issue_id}`" for issue_id in ready_ids) if ready_ids else "None.")
    lines.extend(["", "## Phase coverage", "", "| Phase | Records |", "|---|---:|"])
    for phase, count in payload["phase_counts"].items():
        lines.append(f"| `{phase}` | {count} |")
    lines.extend(
        [
            "",
            "## Safety boundaries",
            "",
            "- `execution_allowed=false` remains the controlling product boundary.",
            "- Optional providers and model integrations remain non-blocking.",
            "- GitHub synchronisation remains dry-run by default and requires a reviewed plan checksum.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="verify both files are fresh without writing")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
    payload = status_payload(registry)
    status_bytes = deterministic_json(payload)
    progress_bytes = progress_markdown(payload, registry).encode("utf-8")
    status_path = root / STATUS_PATH
    progress_path = root / PROGRESS_PATH
    if args.check:
        fresh = status_path.exists() and progress_path.exists()
        fresh = fresh and status_path.read_bytes() == status_bytes
        fresh = fresh and progress_path.read_bytes() == progress_bytes
        print("FRESH" if fresh else "STALE")
        return 0 if fresh else 1
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_bytes(status_bytes)
    progress_path.write_bytes(progress_bytes)
    print(f"WROTE: {status_path}")
    print(f"WROTE: {progress_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
