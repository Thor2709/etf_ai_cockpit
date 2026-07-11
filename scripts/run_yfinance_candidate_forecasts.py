from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etf_cockpit.core.config import ProviderSection, load_config
from etf_cockpit.core.paths import FORECASTS_DIR
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.services import ForecastService


DEFAULT_CANDIDATES = ROOT / "data" / "raw" / "trade_candidates" / "yahoo_trade_candidates_2026-06-30.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline, TimesFM and Toto forecasts for the yfinance candidate list.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--as-of", type=str, default="")
    args = parser.parse_args()

    candidates = pd.read_csv(args.candidates)
    as_of_date = pd.to_datetime(args.as_of).date() if args.as_of else date.today()
    start_date = as_of_date.replace(year=as_of_date.year - args.years)
    section = ProviderSection(
        active_provider="yfinance",
        symbols_map={row.instrument_id: row.yahoo_symbol for row in candidates.itertuples(index=False)},
    )
    result = YFinanceProvider(section, default_currency="EUR").fetch_prices([], start_date, as_of_date)
    if not result.ok or result.data is None:
        print(result.message)
        return 1

    prices = result.data.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    effective_as_of = prices["date"].max().date()
    candidate_ids = list(candidates["instrument_id"].astype(str))
    output = FORECASTS_DIR / f"yfinance_candidate_forecasts_{effective_as_of:%Y%m%d}.csv"
    forecasts = ForecastService(load_config()).run_forecasts(effective_as_of, candidate_ids, prices, output_path=output)
    counts = Counter((forecast.model_name, forecast.status) for forecast in forecasts)

    print(result.message)
    print(f"Forecast date: {effective_as_of}")
    print(f"Instrument count: {len(candidate_ids)}")
    print(f"Rows: {len(forecasts)}")
    for (model_name, status), count in sorted(counts.items()):
        print(f"{model_name:10s} {status:12s} {count}")
    print(f"Wrote {output}")
    return 1 if any(forecast.status == "failed" for forecast in forecasts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
