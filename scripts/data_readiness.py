"""Data-readiness launch gate: check every decision date of an interval and exit non-zero unless every check passes.

Usage: python scripts/data_readiness.py --root PATH --start 2022-10-17 --end 2026-10-09 [--every N] [--thresholds FILE]

Read-only: reads the score backfill store (history and eligibility log), prices, FX and listing membership under --root through
the existing loaders and never writes. Prints a compact per-date, per-family gap report and a JSON summary (last line).
Exit codes: 0 every check passed; 1 at least one check failed or an input is unavailable; 2 invalid usage or thresholds.
Thresholds: configs/data_readiness_v1.yaml (PLAN-T4-20261023, D10). execution_allowed stays false.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="first date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="last date (YYYY-MM-DD)")
    parser.add_argument("--every", type=int, default=None, help="check every N benchmark sessions (default: the configured cadence)")
    parser.add_argument("--thresholds", type=Path, default=None, help="thresholds file (default configs/data_readiness_v1.yaml)")
    args = parser.parse_args(argv)
    if not args.root:
        parser.error("--root (or ETF_COCKPIT_ROOT) is required")
    if args.every is not None and args.every < 1:
        parser.error("--every must be at least 1")
    os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.application import data_readiness

    try:
        thresholds = data_readiness.load_thresholds(args.thresholds or data_readiness.CONFIG_PATH)
        report = data_readiness.evaluate_readiness(
            data_readiness.load_inputs(Path(args.root)), args.start, args.end, thresholds, every=args.every
        )
    except ValueError as exc:
        print(f"data readiness: invalid input: {exc}")
        return 2
    print(report.format_text())
    print(json.dumps(report.summary(), sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
