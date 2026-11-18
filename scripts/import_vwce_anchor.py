"""Import the source-backed VWCE opportunity anchor (INT-09) from the local validated prices.

Usage: python scripts/import_vwce_anchor.py [--root PATH]

Reads the committed prices (duckdb_store.load_prices) under --root (default ETF_COCKPIT_ROOT), sets known_at to now (UTC),
validates the VWCE series with the reference contract and writes data/reference/benchmark_reference_registry.json
atomically. Nothing is written when the series fails. execution_allowed stays false.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    args = parser.parse_args(argv)
    if not args.root:
        parser.error("--root (or ETF_COCKPIT_ROOT) is required")
    os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.application.absolute_merit import import_vwce_anchor
    from etf_cockpit.data.duckdb_store import PRICE_PARQUET, load_prices
    from etf_cockpit.portfolio.benchmark_reference_contract import BenchmarkReferenceError, local_benchmark_registry_path

    if not local_benchmark_registry_path().resolve().is_relative_to(Path(args.root).resolve()):
        print("VWCE anchor not imported: --root is not a project root (no configs/universe.yaml)", file=sys.stderr)
        return 1
    if not PRICE_PARQUET.exists():
        print(f"VWCE anchor not imported: no prices at {PRICE_PARQUET}", file=sys.stderr)
        return 1
    try:
        written = import_vwce_anchor(load_prices())  # the committed rows a decision later reads
    except (BenchmarkReferenceError, OSError, KeyError) as exc:
        print(f"VWCE anchor not imported: {exc}", file=sys.stderr)
        return 1
    print(f"VWCE anchor registry written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
