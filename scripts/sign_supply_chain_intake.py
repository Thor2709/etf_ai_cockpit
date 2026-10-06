"""Create a detached HMAC signature for the local supply-chain intake registry."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.governance.supply_chain_intake import (  # noqa: E402
    load_supply_chain_intake,
    sign_supply_chain_registry,
    supply_chain_intake_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--key-env", default="ETF_COCKPIT_RELEASE_SIGNING_KEY")
    parser.add_argument("--key-id", default="local-release-key")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    key_text = os.getenv(args.key_env, "")
    if not key_text:
        print(f"ERROR: {args.key_env} is not set", file=sys.stderr)
        return 2
    registry = load_supply_chain_intake(root / "configs" / "supply_chain_intake.yaml")
    report = supply_chain_intake_report(root)
    signature = sign_supply_chain_registry(str(report["registry_sha256"]), key_text.encode("utf-8"), key_id=args.key_id)
    destination = root / str(registry["signature"]["path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(signature, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"signed_supply_chain_intake={destination} key_id={args.key_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
