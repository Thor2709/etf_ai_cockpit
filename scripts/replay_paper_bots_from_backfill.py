"""Replay the paper bots over the historical score backfill and print the result (conditional historical simulation).

Usage: python scripts/replay_paper_bots_from_backfill.py [--root PATH] [--as-of YYYY-MM-DD]

Reads data/derived/score_history_backfill.parquet (written by backfill_score_history.py), replays the frozen bot rules through the
normal next-session paper execution into the separate replay record (data/paper_bots_replay) and prints decisions, trades, NAV vs
the VWCE benchmark track, costs, drawdown, unfilled orders and the score term coverage over time. Debug only, never forward
evidence; execution_allowed stays false. The configs/paper_bots_v1.yaml of the chosen root decides the virtual cash.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="replay cutoff date (default: the day after the last VWCE price)")
    args = parser.parse_args()
    if args.root:
        os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.application.score_backfill import SURVIVORSHIP_CAVEAT, eligible_counts_by_year, run_label, term_coverage_by_year
    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.data.local_storage import TransactionalStore
    from etf_cockpit.data.score_history_backfill import load_backfill_eligibility, load_backfill_score_history
    from etf_cockpit.portfolio import paper_bots_execution as execution
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview

    history = load_backfill_score_history(ROOT)
    print(f"=== {run_label(history)} ===")
    if history.empty:
        print("No backfill store: run scripts/backfill_score_history.py first.")
        return 1
    book = execution.PriceBook.from_root(ROOT)
    if args.as_of is not None:
        cutoff_day = args.as_of
    else:
        sessions = [day for day in book.sessions]
        cutoff_day = (max(sessions) + timedelta(days=1)) if sessions else date.today()
    as_of = datetime.combine(cutoff_day, time(12, 0), tzinfo=timezone.utc)
    result = run_historical_replay(as_of, root=ROOT, price_book=book, now=datetime.now(timezone.utc), history_source="backfill")
    print(f"replay: status={result.status} label={result.label!r} appended={result.appended}")
    if result.reason:
        print(f"reason: {result.reason}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    overview = build_paper_bots_overview(ROOT, as_of=as_of, price_book=book)
    replay = overview.get("replay")
    track = execution.replay_track(ROOT, execution.load_execution_config()[1])
    with TransactionalStore(track.store_root, read_only=True) as store:
        decisions = [dict(item.payload) for item in store.list(track.decision_type)]
        records = [dict(item.payload) for item in store.list(track.record_type)]
    print(f"period: {history['as_of_date'].min()} .. {history['as_of_date'].max()} ({history['run_id'].nunique()} scored sessions)")
    print(f"decisions: {len(decisions)} ({Counter(item.get('status') for item in decisions)}); by bot: {Counter(item.get('bot_family') for item in decisions)}")
    print(f"paper records: {Counter(item.get('status') for item in records)}")
    print("unfilled orders by reason:")
    for reason, count in Counter(str(item.get("reason") or item.get("status")) for item in records if item.get("status") != "filled").most_common(10):
        print(f"  {count:4d}  {reason}")
    if not replay:
        print("No replay report is available.")
    else:
        print(f"replay report status: {replay['status']}; label: {replay['label']}")
        for bot in replay["bots"]:
            metrics = bot.get("metrics", {})
            print(f"--- {bot['family']} {bot['name']} (status {bot['status']}, decisions {bot['decisions']}, unavailable {bot['unavailable_decisions']})")
            if bot.get("reason"):
                print(f"    reason: {bot['reason']}")
            for key in ("final_value_eur", "net_contributions_eur", "pnl_eur", "twr", "benchmark_twr", "max_drawdown", "turnover",
                        "traded_notional_eur", "fees_eur", "spread_slippage_eur", "costs_eur", "filled_orders", "missed_orders"):
                print(f"    {key}: {metrics.get(key)}")
            if bot.get("benchmark_wealth"):
                print(f"    VWCE benchmark track final: {bot['benchmark_wealth'][-1]}; first/last date: {bot['dates'][0]} / {bot['dates'][-1]}")
            print(f"    trades in log: {len(bot.get('trade_log', []))}")
    print("eligible instruments at the last session of each year, by asset type:")
    print(eligible_counts_by_year(load_backfill_eligibility(ROOT)).to_string())
    print("share of scored instruments with each score term available, by year:")
    print(term_coverage_by_year(history).to_string())
    print(SURVIVORSHIP_CAVEAT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
