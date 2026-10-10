from __future__ import annotations

import sys
from pathlib import Path

from run_pipeline_cli import require_cached_inputs, run_cli

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.config import load_config  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.application.backtest_service import BacktestService  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.data.duckdb_store import PRICE_PARQUET  # noqa: E402


def main() -> int:
    require_cached_inputs(PRICE_PARQUET)
    config = load_config()
    report = BacktestService(config).run_backtest()
    if report.quality_label == "not_available":
        print("Backtest unavailable: " + "; ".join(report.quality_notes or ["No usable backtest data."]))
        return 1
    print(report.results.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
