"""List issues that have no unresolved blocking prerequisite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.issue_registry_core import REGISTRY_PATH, ready_records
except ModuleNotFoundError:
    from issue_registry_core import REGISTRY_PATH, ready_records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
    records = ready_records(registry)
    if args.as_json:
        print(json.dumps({"count": len(records), "issues": records}, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for record in records:
            print(
                f"{record['canonical_id']} [{record['priority']}] {record['owner']} "
                f"- {record['title']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
