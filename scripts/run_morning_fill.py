"""CLI for the forward paper session-opens job; the output is one JSON line."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Observe the session opens that forward paper fills can need.")
    parser.add_argument("--root", required=True, type=Path, help="Runtime data root with configs/universe.yaml.")
    args = parser.parse_args(argv)
    runtime_root = args.root.expanduser().resolve()
    os.environ["ETF_COCKPIT_ROOT"] = str(runtime_root)
    from etf_cockpit.application.morning_fill import run_morning_fill

    result = run_morning_fill(runtime_root)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result.get("status") in {"available", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
