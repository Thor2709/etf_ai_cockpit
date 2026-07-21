"""Generate the deterministic canonical issue registry."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.issue_registry_core import (
        OPEN_LEDGER,
        REGISTRY_PATH,
        build_registry,
        deterministic_json,
        render_open_ledger_with_final_release,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from issue_registry_core import (
        OPEN_LEDGER,
        REGISTRY_PATH,
        build_registry,
        deterministic_json,
        render_open_ledger_with_final_release,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="verify byte-for-byte freshness without writing")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    target = root / REGISTRY_PATH
    ledger_target = root / OPEN_LEDGER
    ledger_payload = render_open_ledger_with_final_release(root)
    if args.check:
        if not ledger_target.exists() or ledger_target.read_bytes() != ledger_payload:
            print(f"STALE: {ledger_target}")
            return 1
        payload = deterministic_json(build_registry(root))
        if not target.exists() or target.read_bytes() != payload:
            print(f"STALE: {target}")
            return 1
        print(f"FRESH: {target}")
        return 0
    ledger_target.write_bytes(ledger_payload)
    payload = deterministic_json(build_registry(root))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    print(f"WROTE: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
