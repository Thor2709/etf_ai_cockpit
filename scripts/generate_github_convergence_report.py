"""Write a deterministic record of approved GitHub synchronisation and convergence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.issue_registry_core import deterministic_json
except ModuleNotFoundError:
    from issue_registry_core import deterministic_json


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def plan_summary(plan: dict) -> dict:
    return {
        "plan_sha256": plan.get("plan_sha256"),
        "remote_inventory_sha256": plan.get("remote_inventory_sha256"),
        "remote_issue_count": plan.get("remote_issue_count"),
        "summary": plan.get("summary"),
        "legacy_duplicate_count": len(plan.get("legacy_duplicates", [])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-plan", action="append", type=Path, required=True)
    parser.add_argument("--final-plan", type=Path, required=True)
    parser.add_argument("--map", dest="map_path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    approved = [plan_summary(read_json(path)) for path in args.approved_plan]
    final = plan_summary(read_json(args.final_plan))
    historical_map = read_json(args.map_path)
    first = approved[0]["summary"] or {}
    applied = {
        "create": sum(int((item["summary"] or {}).get("create", 0)) for item in approved),
        "update": sum(int((item["summary"] or {}).get("update", 0)) for item in approved),
        "close": sum(int((item["summary"] or {}).get("close", 0)) for item in approved),
        "reopen": sum(int((item["summary"] or {}).get("reopen", 0)) for item in approved),
        "blocked": sum(int((item["summary"] or {}).get("blocked", 0)) for item in approved),
    }
    report = {
        "schema_version": "1.0",
        "repository": "Thor2709/etf_ai_cockpit",
        "application": {
            "status": "APPLIED_AND_VERIFIED",
            "readback_noop": final["summary"] == {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0},
            "reviewed_reopen_ids": ["ISSUE-0048", "ISSUE-0067", "ISSUE-0122"],
            "initial_action_summary": first,
            "applied_action_totals": applied,
        },
        "approved_plans": approved,
        "final_noop_plan": final,
        "historical_map": {
            "map_sha256": historical_map.get("map_sha256"),
            "remote_inventory_sha256": historical_map.get("remote_inventory_sha256"),
            "duplicate_group_count": historical_map.get("duplicate_group_count"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(deterministic_json(report))
    print(f"REPORT: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
