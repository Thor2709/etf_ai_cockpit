from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.services import ChatGPTBridge, build_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="latest")
    args = parser.parse_args()
    snapshot = build_snapshot()
    path = ChatGPTBridge(snapshot.config).export_review_pack(
        snapshot.data_report.as_of_date,
        snapshot.holdings,
        snapshot.features,
        snapshot.signals,
        snapshot.backtest,
    )
    print(path)


if __name__ == "__main__":
    main()
