from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etf_cockpit.core.config import load_config
from etf_cockpit.core.paths import FORECASTS_DIR
from etf_cockpit.data.duckdb_store import load_prices
from etf_cockpit.services import ForecastService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline, TimesFM and Toto forecasts for the local ETF universe.")
    parser.add_argument("--date", default="latest")
    parser.add_argument("--etf", action="append", default=[], help="ETF id to forecast. Can be supplied more than once.")
    args = parser.parse_args()

    config = load_config()
    prices = load_prices()
    prices["date"] = pd.to_datetime(prices["date"])
    as_of_date = prices["date"].max().date() if args.date == "latest" else pd.to_datetime(args.date).date()
    etf_ids = args.etf or config.universe.enabled_ids
    forecasts = ForecastService(config).run_forecasts(as_of_date, etf_ids, prices)
    counts = Counter((forecast.model_name, forecast.status) for forecast in forecasts)

    print(f"Forecast date: {as_of_date}")
    print(f"ETF count: {len(etf_ids)}")
    print(f"Rows: {len(forecasts)}")
    for (model_name, status), count in sorted(counts.items()):
        print(f"{model_name:10s} {status:12s} {count}")
    print(f"Wrote {FORECASTS_DIR / f'forecast_results_{as_of_date:%Y%m%d}.csv'}")
    return 1 if any(forecast.status == "failed" for forecast in forecasts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
