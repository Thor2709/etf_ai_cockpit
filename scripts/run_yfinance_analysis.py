from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# The script adds the local source tree before its application imports.
# ruff: noqa: E402
from etf_cockpit.backtest.engine import run_backtest
from etf_cockpit.core.config import load_config
from etf_cockpit.core.paths import FORECASTS_DIR, REPORTS_DIR
from etf_cockpit.data.import_pipeline import commit_price_import
from etf_cockpit.data.reference_data import commit_reference_import
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.data.etf_structure import structure_confidence_caps
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.models.forecast_scores import forecast_component_maps
from etf_cockpit.models.registry import model_availability
from etf_cockpit.portfolio.risk import target_policy_issues
from etf_cockpit.services import ForecastService
from etf_cockpit.signals.signal_pipeline import generate_signals
from etf_cockpit.data.duckdb_store import load_holdings, write_features


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full cockpit analysis from Yahoo Finance data.")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--as-of", type=str, default="")
    parser.add_argument("--no-commit", action="store_true", help="Fetch and analyse yfinance data without replacing the clean price store.")
    parser.add_argument("--skip-reference", action="store_true", help="Do not fetch Yahoo metadata/top-holdings.")
    parser.add_argument("--skip-models", action="store_true", help="Run algorithms/backtest but skip TimesFM/Toto/baseline forecast generation.")
    args = parser.parse_args()

    config = load_config()
    provider = YFinanceProvider.from_config(config)
    as_of = pd.to_datetime(args.as_of).date() if args.as_of else date.today()
    start = as_of.replace(year=as_of.year - args.years)
    result = provider.fetch_prices([], start, as_of)
    if not result.ok or result.data is None:
        print(result.message)
        return 1

    prices = result.data.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    effective_as_of = max(prices["date"])
    validation = validate_prices(prices, as_of_date=effective_as_of)
    block_messages = [issue.message for issue in validation.issues if issue.severity == "block"]
    if block_messages:
        print("YFinance prices failed validation and were not analysed:")
        for message in block_messages:
            print(f"- {message}")
        return 1

    commit_summary: dict[str, object] = {"committed": False}
    if not args.no_commit:
        commit = commit_price_import(result)
        commit_summary = {
            "committed": True,
            "rows": commit.rows,
            "clean_path": str(commit.clean_path),
            "raw_path": str(commit.raw_path),
            "previous_snapshot_path": str(commit.previous_snapshot_path) if commit.previous_snapshot_path else None,
        }

    reference_summary = _fetch_reference_data(provider, config, skip=args.skip_reference)
    holdings = load_holdings()
    structure_registry, structure_reports, structure_holdings = _load_local_structural_evidence()
    try:
        structure_caps = structure_confidence_caps(
            config.universe.enabled_ids,
            document_registry=structure_registry,
            report_records=structure_reports,
            holdings=structure_holdings,
            decision_time=effective_as_of,
        )
    except (OSError, TypeError, ValueError):
        structure_caps = {str(instrument_id): 0.0 for instrument_id in config.universe.enabled_ids}
    data_report = validate_prices(prices, as_of_date=effective_as_of)
    if target_policy_issues(config):
        data_report = data_report.__class__(
            as_of_date=data_report.as_of_date,
            issues=[*data_report.issues, *target_policy_issues(config)],
            dataset_metadata=data_report.dataset_metadata,
        )
    features = compute_features(prices, benchmark_etf_id=config.universe.enabled_ids[0])
    write_features(features)
    latest = latest_features(features, effective_as_of)

    forecast_rows = []
    forecast_statuses: dict[str, int] = {}
    forecasts_frame = pd.DataFrame()
    if not args.skip_models:
        FORECASTS_DIR.mkdir(parents=True, exist_ok=True)
        output = FORECASTS_DIR / f"forecast_results_yfinance_{effective_as_of:%Y%m%d}.csv"
        forecasts = ForecastService(config).run_forecasts(effective_as_of, config.universe.enabled_ids, prices, output_path=output)
        forecast_rows = [asdict(forecast) for forecast in forecasts]
        forecast_statuses = {f"{model}:{status}": count for (model, status), count in Counter((f.model_name, f.status) for f in forecasts).items()}
        forecasts_frame = pd.DataFrame(forecast_rows)

    status = model_availability(config)
    signals = generate_signals(
        config,
        latest,
        holdings,
        data_report,
        as_of_date=effective_as_of,
        toto_available=status["toto"],
        timesfm_available=status["timesfm"],
        forecast_scores=forecast_component_maps(forecasts_frame),
        structure_confidence_caps=structure_caps,
    )
    backtest = run_backtest(
        config,
        prices,
        structure_document_registry=structure_registry,
        structure_report_records=structure_reports,
        structure_holdings=structure_holdings,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"yfinance_full_analysis_{timestamp}.json"
    summary = {
        "source": "Yahoo Finance via yfinance",
        "as_of_date": effective_as_of.isoformat(),
        "price_rows": len(prices),
        "instrument_count": int(prices["etf_id"].nunique()),
        "price_commit": commit_summary,
        "reference_data": reference_summary,
        "validation_status": validation.status,
        "validation_issues": [asdict(issue) for issue in validation.issues],
        "model_availability": status,
        "forecast_statuses": forecast_statuses,
        "signals": [
            {
                "etf_id": signal.etf_id,
                "score": signal.total_score,
                "action": signal.action,
                "blocked_by": signal.blocked_by,
                "reason": signal.reason_short,
                "toto_score": signal.supporting_metrics.get("toto_score"),
                "timesfm_score": signal.supporting_metrics.get("timesfm_score"),
                "baseline_score": signal.supporting_metrics.get("baseline_score"),
            }
            for signal in signals
        ],
        "backtest": {
            "rows": len(backtest.results),
            "ai_added_value": backtest.ai_added_value,
            "quality": backtest.quality_label,
        },
    }
    report_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print(result.message)
    print(f"YFinance as-of: {effective_as_of}")
    print(f"Validation: {validation.status}")
    print(f"Signals: {len(signals)}")
    print(f"Forecast statuses: {forecast_statuses or 'skipped'}")
    print(f"Backtest quality: {backtest.quality_label}")
    print(f"Wrote {report_path}")
    return 0


def _load_local_structural_evidence() -> tuple[object, object, object]:
    """Load the same optional local structural inputs for signals and backtests."""

    try:
        registry = read_document_registry()
        reports = read_etf_report_records()
        holdings = pd.read_parquet(FUND_HOLDINGS_PATH) if FUND_HOLDINGS_PATH.exists() else pd.DataFrame()
        return registry, reports, holdings
    except (OSError, TypeError, ValueError):
        return None, None, None


def _fetch_reference_data(provider: YFinanceProvider, config, *, skip: bool) -> dict[str, object]:
    if skip:
        return {"skipped": True}
    context = {
        "known_etfs": [etf.id for etf in config.universe.etfs],
        "isin_to_etf_id": {etf.isin: etf.id for etf in config.universe.etfs if etf.isin},
        "ticker_to_etf_id": {etf.ticker: etf.id for etf in config.universe.etfs if etf.ticker},
    }
    output: dict[str, object] = {}
    for dataset_type, result in (
        ("etf_metadata", provider.fetch_etf_metadata([])),
        ("etf_holdings", provider.fetch_etf_holdings([])),
    ):
        if not result.ok or result.data is None:
            output[dataset_type] = {"status": result.status, "message": result.message}
            continue
        try:
            commit = commit_reference_import(
                result,
                dataset_type,
                known_etfs=context["known_etfs"],
                isin_to_etf_id=context["isin_to_etf_id"],
                ticker_to_etf_id=context["ticker_to_etf_id"],
            )
            output[dataset_type] = {
                "status": "ok",
                "rows": commit.rows,
                "clean_path": str(commit.clean_path),
                "warnings": commit.warnings,
            }
        except Exception as exc:
            output[dataset_type] = {"status": "error", "message": str(exc)}
    return output


if __name__ == "__main__":
    raise SystemExit(main())
