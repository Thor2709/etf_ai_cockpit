"""Fetch the ECB overnight cash rates, or write the rank-validation cash table (train E1).

Usage:
  python scripts/ecb_cash_rates.py fetch --root PATH          (network: writes data/reference/ecb_overnight_rates.*)
  python scripts/ecb_cash_rates.py table --root PATH --out FILE.csv

``table`` reads the stored rates and the session dates of data/validated/prices/prices_daily.parquet (the price file
rank validation reads by default) and writes ``decision_date, net_return, source`` for ``run_rank_validation.py --cash``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def write_cash_table(root: Path, out: Path) -> int:
    """Write the cash table of ``root`` to ``out``; return its row count."""

    import pandas as pd

    from etf_cockpit.analysis.decision.rank_validation import load_rank_validation_policy
    from etf_cockpit.data.ecb_cash import CASH_RATES_FILE, forward_cash_returns

    rates = pd.read_parquet(root / "data" / "reference" / f"{CASH_RATES_FILE}.parquet")
    dates = pd.read_parquet(root / "data" / "validated" / "prices" / "prices_daily.parquet", columns=["date"])["date"]
    sessions = pd.to_datetime(dates.drop_duplicates(), errors="coerce").dropna().dt.date
    table = forward_cash_returns(rates, sessions.tolist(), load_rank_validation_policy().holding_period_sessions)
    table.to_csv(out, index=False)
    return len(table)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("fetch", "table"))
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--out", type=Path, help="cash table path (.csv), for table")
    args = parser.parse_args(argv)
    if not args.root or (args.command == "table" and args.out is None):
        parser.error("--root (or ETF_COCKPIT_ROOT) is required, and --out for table")
    root = Path(args.root).resolve()
    try:
        if args.command == "fetch":
            from etf_cockpit.data.ecb_cash import fetch_overnight_rates

            print(f"ECB overnight rates written: {fetch_overnight_rates(root)}")
        else:
            print(f"cash table rows: {write_cash_table(root, args.out)} -> {args.out}")
    except (ValueError, OSError) as exc:
        print(f"ECB cash {args.command} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
