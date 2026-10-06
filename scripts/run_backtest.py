from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.config import load_config  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.application.backtest_service import BacktestService  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.application.data_service import DataService  # noqa: E402 - imports follow the sys.path bootstrap above


def main() -> None:
    config = load_config()
    DataService(config).update_prices()
    report = BacktestService(config).run_backtest()
    print(report.results.to_string(index=False))


if __name__ == "__main__":
    main()
