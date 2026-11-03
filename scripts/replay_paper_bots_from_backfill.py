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


def main(argv: list[str] | None = None) -> int:
    previous_root = os.environ.get("ETF_COCKPIT_ROOT")
    try:
        return _run(argv)
    finally:
        if previous_root is None:
            os.environ.pop("ETF_COCKPIT_ROOT", None)
        else:
            os.environ["ETF_COCKPIT_ROOT"] = previous_root


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="replay cutoff date (default: the day after the last VWCE price)")
    parser.add_argument("--start", type=date.fromisoformat, default=None, help="first included score date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="last included score date (YYYY-MM-DD)")
    parser.add_argument(
        "--decision-dates", type=int, default=None,
        help="select exactly the first N distinct benchmark score dates after filtering by start/end",
    )
    parser.add_argument(
        "--survivorship-mode", choices=("strict", "unverified-delistings"), default="strict",
        help="strict (default): fail closed without verified listing history. unverified-delistings: also admit instruments listed "
        "from their first price date whose delisting is unverified; the report is labelled survivorship_unverified",
    )
    args = parser.parse_args(argv)
    if args.start is not None and args.end is not None and args.end < args.start:
        parser.error("--end must not be before --start")
    if args.decision_dates is not None and args.decision_dates < 1:
        parser.error("--decision-dates must be at least 1")
    if args.root:
        os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.application.score_backfill import SURVIVORSHIP_CAVEAT, eligible_counts_by_year, run_label, term_coverage_by_year
    from etf_cockpit.data.replay_membership import SURVIVORSHIP_UNVERIFIED_BANNER, unverified_instruments
    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.data.local_storage import TransactionalStore
    from etf_cockpit.data.score_history_backfill import load_backfill_eligibility, load_backfill_score_history
    from etf_cockpit.portfolio import paper_bots_execution as execution
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview

    import pandas as pd

    history = load_backfill_score_history(ROOT)
    eligibility = load_backfill_eligibility(ROOT)
    print("survivorship-unverified instruments (no listing history at one or more replay dates):")
    for instrument_id in unverified_instruments(eligibility):
        print(f"  {instrument_id}")
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
    if "as_of_date" not in history.columns:
        print("Replay refused: backfill history has no as_of_date column; no writes were made.")
        return 1
    score_days = pd.to_datetime(history["as_of_date"], errors="coerce").dt.date
    include = score_days.notna() & (score_days <= cutoff_day)
    if args.start is not None:
        include &= score_days >= args.start
    if args.end is not None:
        include &= score_days <= args.end
    filtered_history = history.loc[include].copy()
    if args.decision_dates is not None:
        benchmark_sessions = set(book.sessions)
        available_dates = sorted({day for day in score_days.loc[include] if day in benchmark_sessions})
        if len(available_dates) < args.decision_dates:
            print(
                f"Replay refused: requested {args.decision_dates} distinct benchmark score dates, "
                f"found {len(available_dates)}; no writes were made."
            )
            return 1
        selected_dates = set(available_dates[:args.decision_dates])
        filtered_history = filtered_history.loc[
            pd.to_datetime(filtered_history["as_of_date"], errors="coerce").dt.date.isin(selected_dates)
        ].copy()
    if filtered_history.empty:
        print("Replay refused: no score dates match the requested interval; no writes were made.")
        return 1
    as_of = datetime.combine(cutoff_day, time(12, 0), tzinfo=timezone.utc)
    result = run_historical_replay(
        as_of, root=ROOT, history=filtered_history, price_book=book, now=datetime.now(timezone.utc),
        history_source="backfill", survivorship_mode=args.survivorship_mode,
    )
    if result.survivorship_unverified:
        print("!" * 100)
        print(SURVIVORSHIP_UNVERIFIED_BANNER)
        print("!" * 100)
    print(f"replay: status={result.status} label={result.label!r} appended={result.appended}")
    if result.reason:
        print(f"reason: {result.reason}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    if result.status != "available":
        return 1
    overview = build_paper_bots_overview(ROOT, as_of=as_of, price_book=book)
    replay = overview.get("replay")
    track = execution.replay_track(ROOT, execution.load_execution_config()[1])
    with TransactionalStore(track.store_root, read_only=True) as store:
        decisions = [dict(item.payload) for item in store.list(track.decision_type)]
        records = [dict(item.payload) for item in store.list(track.record_type)]
    print(f"period: {filtered_history['as_of_date'].min()} .. {filtered_history['as_of_date'].max()} ({filtered_history['run_id'].nunique()} scored sessions)")
    print(f"decisions: {len(decisions)} ({Counter(item.get('status') for item in decisions)}); by bot: {Counter(item.get('bot_family') for item in decisions)}")
    print(f"paper records: {Counter(item.get('status') for item in records)}")
    print("unfilled orders by reason:")
    for reason, count in Counter(str(item.get("reason") or item.get("status")) for item in records if item.get("status") != "filled").most_common(10):
        print(f"  {count:4d}  {reason}")
    if not replay:
        print("No replay report is available.")
    else:
        print(f"replay report status: {replay['status']}; label: {replay['label']}")
        if replay.get("survivorship_unverified"):
            print(f"survivorship_unverified: true ({', '.join(replay.get('survivorship_unverified_ids') or [])})")
            print(replay["survivorship_banner"])
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
