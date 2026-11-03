"""Fetch real historical universe evidence; canonical writes require --promote."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_cockpit.application.universe_fetch import FetchOptions, fetch_full_universe
from etf_cockpit.core.session_log import redact_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--warmup-days", type=int, default=400, help="calendar-day history padding")
    parser.add_argument("--fill-days", type=int, default=10, help="calendar-day end padding, capped at today; never fills missing rows")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rate-per-host", type=float, default=1.0, help="shared requests/second/host")
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = fetch_full_universe(FetchOptions(**vars(args)))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Fetch failed ({type(exc).__name__}): {redact_text(str(exc))}\n")
    print(json.dumps(report, indent=2))
    return 1 if report["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
