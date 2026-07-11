from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.runtime import configure_runtime_environment

configure_runtime_environment()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Build the service snapshot without opening the UI.")
    args = parser.parse_args()
    if args.smoke:
        from etf_cockpit.services import build_snapshot

        snapshot = build_snapshot()
        print(f"snapshot_ok as_of={snapshot.data_report.as_of_date} signals={len(snapshot.signals)} backtests={len(snapshot.backtest.results)}")
        return
    from etf_cockpit.app.flet_app import run

    run()


if __name__ == "__main__":
    main()
