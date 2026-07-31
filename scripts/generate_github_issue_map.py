"""Create a reviewed map for duplicate legacy GitHub Issue records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from scripts.issue_registry_core import deterministic_json
    from scripts.sync_github_issues import DEFAULT_MAP_PATH, gh_list_issues, marker_ids
except ModuleNotFoundError:
    from issue_registry_core import deterministic_json
    from sync_github_issues import DEFAULT_MAP_PATH, gh_list_issues, marker_ids


def _body_marker_inventory_sha256(remote: list[dict]) -> str:
    rows = sorted(
        (
            {
                "number": int(issue.get("number", 0)),
                "title": str(issue.get("title") or ""),
                "body": str(issue.get("body") or ""),
                "state": str(issue.get("state") or "").lower(),
                "url": str(issue.get("url") or issue.get("html_url") or ""),
            }
            for issue in remote
        ),
        key=lambda row: (len(str(row["number"])), str(row["number"])),
    )
    return hashlib.sha256(deterministic_json(rows)).hexdigest()


def build_map(remote: list[dict]) -> dict:
    mappings: dict[str, dict] = {}
    for stable_id, issues in sorted(marker_ids(remote).items()):
        if len(issues) < 2:
            continue
        ordered = sorted(issues, key=lambda issue: int(issue["number"]))
        selected = ordered[-1]
        retained = ordered[:-1]
        if any(str(issue.get("state", "")).lower() != "closed" for issue in retained):
            raise ValueError(f"cannot map duplicate {stable_id}: an older duplicate is not closed")
        mappings[stable_id] = {
            "selected_remote_number": int(selected["number"]),
            "remote_numbers": [int(issue["number"]) for issue in ordered],
            "retained_closed_remote_numbers": [int(issue["number"]) for issue in retained],
            "selection_basis": (
                "newest remote legacy-marker record; older duplicate records are already closed "
                "and are retained as historical records"
            ),
        }
    payload = {
        "schema_version": "1.0",
        "repository": "Thor2709/etf_ai_cockpit",
        "remote_inventory_sha256": _body_marker_inventory_sha256(remote),
        "duplicate_group_count": len(mappings),
        "mappings": mappings,
    }
    payload["map_sha256"] = hashlib.sha256(deterministic_json(payload)).hexdigest()
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    remote = json.loads(args.remote_snapshot.read_text(encoding="utf-8")) if args.remote_snapshot else gh_list_issues()
    if not isinstance(remote, list):
        raise SystemExit("remote snapshot must be a JSON list")
    output = args.output or Path.cwd() / DEFAULT_MAP_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_map(remote)
    output.write_bytes(deterministic_json(payload))
    print(f"MAP: {output}")
    print(f"DUPLICATE_GROUPS: {payload['duplicate_group_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
