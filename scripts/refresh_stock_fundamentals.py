"""Refresh normal-stock fundamentals from free sources (SEC EDGAR when configured, then yfinance).

Usage: python scripts/refresh_stock_fundamentals.py [--root PATH] [--ids A,B]
Read-only fetches; writes data/clean/stock_*.parquet under the chosen root, then the SEC evidence
(bitemporal store, raw SEC cache, document chunk store); an SEC evidence error never changes the exit code.
A full run (no --ids, no --sources) then refreshes the ETF reference data; its errors never change the exit code.
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
    parser.add_argument(
        "--sources",
        default="",
        help="comma separated subset of the configured source chain, e.g. sec_edgar (default: the whole chain). "
        "A point-in-time history backfill uses sec_edgar only: yfinance statements are restated and dated at fetch time.",
    )
    args = parser.parse_args()
    if args.root:
        os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.application.stock_service import refresh_universe_stock_fundamentals
    from etf_cockpit.core.config import load_config

    config = load_config()
    only = {item.strip() for item in args.ids.split(",") if item.strip()} or None
    chain = [item.strip() for item in args.sources.split(",") if item.strip()] or None
    report = refresh_universe_stock_fundamentals(config, only_ids=only, progress=print, chain=chain)
    print(f"rows added: {report.rows_added}; instruments without data: {len(report.failures)}")
    for key, reason in report.failures.items():
        print(f"  {key}: {reason}")
    try:
        from etf_cockpit.application.sec_evidence_refresh import refresh_sec_evidence

        sec = refresh_sec_evidence(config, only_ids=only, progress=print)
        print(
            f"SEC evidence added: earnings rows {sec['earnings_rows']}; Form 4 filings {sec['insider_rows']}; "
            f"10-K chunks indexed {sec['ten_k_chunks']}; targets with a gap: {len(sec['reasons'])}"
        )
    except Exception as exc:  # the stock refresh above already ran: keep its exit code
        print(f"SEC evidence refresh unavailable: {type(exc).__name__}: {exc}")
    if only is None and chain is None:
        try:
            from etf_cockpit.application.data_service import DataService

            for message in DataService(config).refresh_reference_data():
                print(message)
        except Exception as exc:  # the stock refresh above already ran: keep its exit code
            print(f"ETF reference data refresh unavailable: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
