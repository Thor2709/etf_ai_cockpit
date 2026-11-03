"""CLI for the local daily paper workflow; all output is one JSON summary line."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh, gate and run the local daily paper accounts.")
    parser.add_argument("--root", required=True, type=Path, help="Runtime data root with configs/universe.yaml.")
    parser.add_argument("--ai-account", default="ai-paper")
    parser.add_argument("--initial-cash-eur", type=float, default=40_000)
    parser.add_argument("--monthly-contribution-eur", type=float, default=0)
    parser.add_argument("--dry-run", action="store_true", help="Refresh, gate and publish but skip paper decisions and account opening.")
    args = parser.parse_args(argv)
    runtime_root = args.root.expanduser().resolve()
    if not (runtime_root / "configs" / "universe.yaml").is_file():
        print('{"error":"runtime root must contain configs/universe.yaml","stage":"configuration","status":"blocked","execution_allowed":false}')
        return 1

    os.environ["ETF_COCKPIT_ROOT"] = str(runtime_root)
    from etf_cockpit.application.daily_paper import run_daily_paper

    result = run_daily_paper(
        runtime_root,
        ai_account=args.ai_account,
        initial_cash_eur=args.initial_cash_eur,
        monthly_contribution_eur=args.monthly_contribution_eur,
        dry_run=args.dry_run,
    )
    print(result.to_json())
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
