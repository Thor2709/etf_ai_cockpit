"""Run the local forward-only paper bot decision recorder."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from etf_cockpit.portfolio.paper_bots import run_paper_bots  # noqa: E402
from etf_cockpit.portfolio.paper_bots_execution import run_paper_bot_execution  # noqa: E402
from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record this month's published paper bot decisions.")
    parser.add_argument("--as-of", help="Timezone-aware ISO-8601 date and time (a date alone is rejected); defaults to current UTC time.")
    parser.add_argument(
        "--replay", action="store_true",
        help="Instead run the separately stored 'conditional historical simulation' over the stored history.",
    )
    args = parser.parse_args(argv)
    as_of = args.as_of or datetime.now(timezone.utc)
    if args.replay:
        replay = run_historical_replay(as_of)
        print(f"Paper bots {replay.label} {replay.status}: as_of={replay.as_of or 'unavailable'} appended={replay.appended}")
        if replay.reason:
            print(replay.reason)
        for warning in replay.warnings:
            print(f"Warning: {warning}")
        return 1 if replay.status == "unavailable" else 0
    result = run_paper_bots(as_of)
    print(f"Paper bots {result.status}: as_of={result.as_of or 'unavailable'} appended={result.appended}")
    if result.reason:
        print(result.reason)
    for warning in result.warnings:
        print(f"Warning: {warning}")
    for record in result.records:
        print(
            f"{record.get('bot_family', 'unknown')} {record.get('bot_id', 'unavailable')}: "
            f"{record.get('status', 'unavailable')}"
        )
    # Stage B: fill the frozen decisions at the next session open, then mirror the flows into the VWCE shadow accounts.
    execution = run_paper_bot_execution(as_of)
    print(f"Paper bot execution {execution.status}: as_of={execution.as_of or 'unavailable'} appended={execution.appended}")
    if execution.reason:
        print(execution.reason)
    for warning in execution.warnings:
        print(f"Warning: {warning}")
    return 1 if result.status == "unavailable" and execution.status == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
