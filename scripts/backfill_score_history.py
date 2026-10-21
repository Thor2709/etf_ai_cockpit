"""Backfill the canonical score as of past sessions into the separate historical-backfill score store.

Usage: python scripts/backfill_score_history.py --start 2022-10-17 --end 2026-10-09 [--every 5] [--root PATH] [--force]
       [--exclusions-csv FILE]

Each selected session (default every 5th benchmark session, i.e. weekly; ``--every 1`` is daily) is scored with the real score
engine using only data known at that session. Output (never the live score history): data/derived/score_history_backfill.parquet,
its eligibility log and manifest under the chosen root. Nothing is traded and execution_allowed stays false.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="first date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="last date (YYYY-MM-DD)")
    parser.add_argument("--every", type=int, default=5, help="score every N benchmark sessions (default 5 = weekly)")
    parser.add_argument("--force", action="store_true", help="recompute sessions that are already stored")
    parser.add_argument(
        "--exclusions-csv", type=Path, default=None,
        help="CSV with columns id and reason (and optionally replay_set: only EXCLUDED rows count) of instruments removed from the replay universe",
    )
    args = parser.parse_args()
    if args.root:
        os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.application.score_backfill import (
        SURVIVORSHIP_CAVEAT,
        backfill_score_history,
        eligible_counts_by_year,
        never_eligible,
    )
    from etf_cockpit.core.paths import ROOT

    excluded: dict[str, str] = {}
    if args.exclusions_csv is not None:
        import pandas as pd

        table = pd.read_csv(args.exclusions_csv, dtype=str).fillna("")
        if "replay_set" in table.columns:
            table = table[table["replay_set"].str.upper().eq("EXCLUDED")]
        excluded = {str(row["id"]): str(row["reason"]) or "excluded" for _, row in table.iterrows()}
    result = backfill_score_history(
        ROOT, args.start, args.end, every=args.every, force=args.force, excluded=excluded, progress=print
    )
    print(f"status: {result.status}; sessions requested: {result.sessions_requested}; written: {result.runs_written}; kept: {result.runs_kept}")
    if result.reason:
        print(f"reason: {result.reason}")
    for day, reason in sorted(result.unavailable_dates.items()):
        print(f"  unavailable {day}: {reason}")
    if result.path:
        print(f"store: {result.path}")
        print("eligible instruments at the last session of each year, by asset type:")
        print(eligible_counts_by_year(result.eligibility).to_string())
        print("never eligible:")
        print(never_eligible(result.eligibility).to_string(index=False))
    print(SURVIVORSHIP_CAVEAT)
    return 0 if result.status == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
