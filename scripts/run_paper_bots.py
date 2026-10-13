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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record this month's published paper bot decisions.")
    parser.add_argument("--as-of", help="Timezone-aware ISO-8601 date and time (a date alone is rejected); defaults to current UTC time.")
    args = parser.parse_args(argv)
    as_of = args.as_of or datetime.now(timezone.utc)
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
    return 1 if result.status == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
