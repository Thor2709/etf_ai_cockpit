"""Forward-only iShares holdings collection. Configure funds before live use."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_cockpit.data.holdings_registry import collect_daily


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    results = collect_daily(args.root, workers=args.workers)
    for row in results:
        print(" ".join(f"{key}={value}" for key, value in row.items()))
    if not results:
        print("No configured iShares funds; no collection performed.")
    return int(any(row["status"] == "failed" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
