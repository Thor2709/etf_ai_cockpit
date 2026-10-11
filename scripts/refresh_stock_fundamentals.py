"""Refresh normal-stock fundamentals from free sources (SEC EDGAR when configured, then yfinance).

Usage: python scripts/refresh_stock_fundamentals.py [--root PATH] [--ids A,B]
Read-only fetches; writes only data/clean/stock_*.parquet under the chosen root.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--ids", default="", help="comma separated instrument ids (default: all normal stocks)")
    args = parser.parse_args()
    if args.root:
        os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.application.stock_service import refresh_universe_stock_fundamentals
    from etf_cockpit.core.config import load_config

    config = load_config()
    only = {item.strip() for item in args.ids.split(",") if item.strip()} or None
    report = refresh_universe_stock_fundamentals(config, only_ids=only, progress=print)
    print(f"rows added: {report.rows_added}; instruments without data: {len(report.failures)}")
    for key, reason in report.failures.items():
        print(f"  {key}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
