"""Generate the deterministic canonical issue registry."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.issue_registry_core import REGISTRY_PATH, build_registry, deterministic_json
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from issue_registry_core import REGISTRY_PATH, build_registry, deterministic_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="verify byte-for-byte freshness without writing")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    target = root / REGISTRY_PATH
    payload = deterministic_json(build_registry(root))
    if args.check:
        if not target.exists() or target.read_bytes() != payload:
            print(f"STALE: {target}")
            return 1
        print(f"FRESH: {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    print(f"WROTE: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
