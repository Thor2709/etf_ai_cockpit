from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from run_pipeline_cli import require_cached_inputs, run_cli  # noqa: E402 - follows the scripts-dir bootstrap

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etf_cockpit.application.forecast_run import run_forecast_recipe  # noqa: E402
from etf_cockpit.application.forecast_service import ForecastService  # noqa: E402,F401 - retained script test seam
from etf_cockpit.core.config import load_config  # noqa: E402
from etf_cockpit.data.duckdb_store import PRICE_PARQUET, load_prices  # noqa: E402


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="Run baseline and configured optional forecasts for the local ETF universe.")
    parser.add_argument("--date", default="latest")
    parser.add_argument("--etf", action="append", default=[], help="ETF id; all enabled ids must be supplied to avoid partial cache replacement.")
    args = parser.parse_args()

    require_cached_inputs(PRICE_PARQUET)
    config = load_config()
    result = run_forecast_recipe(
        config,
        as_of_date=args.date,
        instrument_ids=args.etf or None,
        live_optional_models=None,
        prices=load_prices(),
    )
    print(f"Forecast date: {result['as_of_date']}")
    print(f"ETF count: {result['instrument_count']}")
    print(f"Rows: {result['forecast_row_count']}")
    print(
        "Optional models run: "
        f"{result['live_optional_models']}; automatic promotion: {config.models.promotion.enabled}; execution_allowed=false"
    )
    for item in result["model_status_counts"]:
        print(f"{item['model']:10s} {item['status']:12s} {item['count']}")
    for name, promotion in result["promotions"].items():
        print(f"promotion {name:10s} {promotion['state']:11s} {promotion['reason']}")
    print(f"Wrote {result['output_path']}")
    print(f"Runtime seconds: {time.perf_counter() - started:.3f}")
    return 1 if any(item["status"] == "failed" for item in result["model_status_counts"]) else 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
