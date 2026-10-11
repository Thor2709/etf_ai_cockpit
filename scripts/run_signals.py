from __future__ import annotations

import argparse
import sys
from math import isfinite
from datetime import date
from pathlib import Path

from run_pipeline_cli import require_cached_inputs, run_cli

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.config import load_config  # noqa: E402 - imports follow the sys.path bootstrap above
from etf_cockpit.data.duckdb_store import HOLDINGS_CSV, PRICE_PARQUET  # noqa: E402
from etf_cockpit.application.signal_service import SignalService  # noqa: E402 - imports follow the sys.path bootstrap above


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="latest")
    args = parser.parse_args()
    as_of_date = None if args.date == "latest" else date.fromisoformat(args.date)
    require_cached_inputs(PRICE_PARQUET, HOLDINGS_CSV)
    config = load_config()
    signals = SignalService(config).generate_signals(as_of_date=as_of_date)
    for signal in signals:
        confidence = f"{signal.confidence:.2f}" if isfinite(signal.confidence) else "unavailable"
        score = f"{signal.total_score:+.2f}" if isfinite(signal.total_score) else "unavailable"
        print(f"{signal.etf_id:16s} {signal.action:13s} confidence={confidence} score={score} blocked={','.join(signal.blocked_by) or '-'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
