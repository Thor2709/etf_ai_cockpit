from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from run_pipeline_cli import require_cached_inputs, run_cli

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etf_cockpit.core.config import load_config  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.core.paths import FORECASTS_DIR  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.data.duckdb_store import PRICE_PARQUET, load_holdings, load_prices  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.application.forecast_service import ForecastService, _config_with_optional_models_disabled  # noqa: E402
from etf_cockpit.application.reference_context import _benchmark_reference_snapshot_inputs, _reference_context_from_inputs  # noqa: E402
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline, TimesFM and Toto forecasts for the local ETF universe.")
    parser.add_argument("--date", default="latest")
    parser.add_argument("--etf", action="append", default=[], help="ETF id to forecast. Can be supplied more than once.")
    args = parser.parse_args()

    require_cached_inputs(PRICE_PARQUET)
    config = load_config()
    prices = load_prices()
    if prices.empty or "date" not in prices:
        raise ValueError("Cached prices contain no dated observations.")
    prices["date"] = pd.to_datetime(prices["date"])
    if prices["date"].dropna().empty:
        raise ValueError("Cached prices contain no valid dates.")
    as_of_date = prices["date"].max().date() if args.date == "latest" else pd.to_datetime(args.date).date()
    etf_ids = args.etf or config.universe.enabled_ids
    reference_context = _reference_context_from_inputs(
        _benchmark_reference_snapshot_inputs(config, as_of_date, load_holdings()),
        purpose="comparison",
        analysis_id=f"forecast:{as_of_date.isoformat()}",
    )
    request_identity = configured_forecast_request_identity(config)
    live_optional_models = request_identity["live_optional_models"]
    forecast_config = config if live_optional_models else _config_with_optional_models_disabled(config)
    forecasts = ForecastService(forecast_config, reference_context=reference_context).run_forecasts(
        as_of_date, etf_ids, prices,
        horizons=request_identity["requested_horizons"],
        cache_request_identity=request_identity,
        live_optional_models=live_optional_models,
    )
    counts = Counter((forecast.model_name, forecast.status) for forecast in forecasts)

    print(f"Forecast date: {as_of_date}")
    print(f"ETF count: {len(etf_ids)}")
    print(f"Rows: {len(forecasts)}")
    for (model_name, status), count in sorted(counts.items()):
        print(f"{model_name:10s} {status:12s} {count}")
    print(f"Wrote {FORECASTS_DIR / f'forecast_results_{as_of_date:%Y%m%d}.csv'}")
    return 1 if any(forecast.status == "failed" for forecast in forecasts) else 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
