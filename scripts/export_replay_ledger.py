"""Export the paper-bot replay's orders, fills, weekly holdings and weekly equity to CSV (read-only; nothing is recomputed).

Usage: python scripts/export_replay_ledger.py [--root PATH] [--out DIR] [--as-of YYYY-MM-DD]

Reads the canonical replay record (data/paper_bots_replay store: decisions, plans, execution records) and the per-bot paper
ledgers (fills with their FX rate, funding flows) plus the stored price book for marks, and the score backfill for the score at
each decision. Writes trades.csv (one row per order), holdings_weekly.csv, equity_weekly.csv and order_counts.csv under
<root>/data/paper_bots_replay/exports (or --out). Conditional historical simulation, never forward evidence.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path


def value_positions(cash, held, fx, mark_of):
    """Mark every held position; an unmarked one (stale beyond the limit, no bar) is never valued as zero.

    Returns (value per position or None, invested, total, ids without a mark). When any position is unmarked, invested and
    total are None for that date (and so is every weight): a partial sum would silently understate the portfolio.
    """

    values: dict[str, float | None] = {}
    missing: list[str] = []
    for key, units in held.items():
        if units == 0:
            continue
        mark = mark_of(key)
        if mark is None or mark != mark:
            values[key] = None
            missing.append(key)
        else:
            values[key] = float(units) * float(mark) * float(fx[key])
    if missing:
        return values, None, None, sorted(missing)
    invested = sum(value for value in values.values() if value is not None)
    return values, invested, float(cash) + invested, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--out", type=Path, default=None, help="output directory (default <root>/data/paper_bots_replay/exports)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="report cutoff (default: the day after the last VWCE price)")
    parser.add_argument(
        "--survivorship-mode", choices=("strict", "unverified-delistings"), default="strict",
        help="must match the mode the replay ran with: the export fails closed if the stored replay label disagrees",
    )
    args = parser.parse_args()
    if args.root:
        os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import pandas as pd

    from etf_cockpit.core.config import load_config
    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.data.local_storage import TransactionalStore
    from etf_cockpit.data.score_history_backfill import load_backfill_score_history
    from etf_cockpit.portfolio import paper_bots_execution as execution
    from etf_cockpit.portfolio import paper_bots_report as report
    from etf_cockpit.portfolio.paper_trading import PaperLedger

    out = args.out or ROOT / "data" / "paper_bots_replay" / "exports"
    out.mkdir(parents=True, exist_ok=True)
    exec_config = execution.load_execution_config()[1]
    track = execution.replay_track(ROOT, exec_config)
    names = {key: item.name for key, item in load_config().universe.by_id().items()}
    book = execution.PriceBook.from_root(ROOT)
    cutoff_day = args.as_of or (max(book.sessions) + timedelta(days=1))
    cutoff = datetime.combine(cutoff_day, time(12, 0), tzinfo=timezone.utc)
    stale_limit = int(exec_config["max_stale_mark_sessions"])
    history = load_backfill_score_history(ROOT)
    weekly = sorted({date.fromisoformat(str(value)[:10]) for value in history["as_of_date"]}) if not history.empty else []
    scores = (
        history.set_index(["snapshot_hash", "instrument_id"])[["final_combined_score_10", "rank"]].to_dict("index") if not history.empty else {}
    )

    with TransactionalStore(track.store_root, read_only=True) as store:
        decisions = {item.payload["decision_id"]: dict(item.payload) for item in store.list(track.decision_type)}
        plans = {item.payload["plan_id"]: dict(item.payload) for item in store.list(track.plan_type)}
        records = [dict(item.payload) for item in store.list(track.record_type)]
    bots = {item["bot_id"]: item for item in decisions.values()}
    first_month = {bot_id: min(item["decision_month"] for item in decisions.values() if item["bot_id"] == bot_id) for bot_id in bots}
    overview = report.build_paper_bots_overview(ROOT, as_of=cutoff, price_book=book)
    bot_reports = {item["bot_id"]: item for item in ((overview.get("replay") or {}).get("bots") or [])}

    trades: list[dict[str, object]] = []
    holdings: list[dict[str, object]] = []
    equity: list[dict[str, object]] = []
    for bot_id, head in sorted(bots.items(), key=lambda pair: pair[1]["bot_family"]):
        family = head["bot_family"]
        ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(bot_id))
        events = ledger._read_events()
        flows = [event["payload"] for event in events if event["event_type"] == "external_flow_recorded"]
        fills = [event for event in events if event["event_type"] == "fill_recorded"]
        shadow_rows: list[dict[str, object]] = []
        if head.get("strategy") == "benchmark":
            shadow = PaperLedger(track.ledger_root, account_id=execution.shadow_id_for(bot_id))
            shadow_rows = report._shadow_flows(shadow)
            flows = [
                {"effective_at": f"{flow['executed_session']}T00:00:00+00:00", "amount": flow["amount"], "flow_kind": flow["flow_kind"]}
                for flow in shadow_rows
                if flow["flow_kind"] in {"contribution", "withdrawal"}
            ] or flows
            fills = [
                {
                    "occurred_at": f"{flow['executed_session']}T17:30:00+00:00",
                    "payload": {
                        "instrument_id": flow["instrument_id"], "side": flow["side"], "quantity": flow["quantity"], "price": flow["price"],
                        "fee": flow["fee"], "fx_rate": "1", "currency": "EUR", "order_id": flow["flow_id"], "fill_id": flow["flow_id"],
                    },
                }
                for flow in shadow_rows
                if flow["side"] in {"buy", "sell"}
            ]

        def state_at(moment: str, *, flows=flows, fills=fills) -> tuple[Decimal, dict[str, Decimal], dict[str, Decimal]]:
            cash = Decimal(0)
            quantity: dict[str, Decimal] = {}
            fx: dict[str, Decimal] = {}
            for flow in flows:
                if str(flow["effective_at"]) <= moment:
                    cash += Decimal(str(flow["amount"])) * (1 if flow["flow_kind"] == "contribution" else -1)
            for event in sorted(fills, key=lambda item: str(item["occurred_at"])):
                if str(event["occurred_at"]) <= moment:
                    payload = event["payload"]
                    units = Decimal(str(payload["quantity"])) * (1 if payload["side"] == "buy" else -1)
                    key = str(payload["instrument_id"])
                    quantity[key] = quantity.get(key, Decimal(0)) + units
                    fx[key] = Decimal(str(payload["fx_rate"]))
                    cash -= units * Decimal(str(payload["price"])) * fx[key] + Decimal(str(payload["fee"]))
            return cash, quantity, fx

        fill_by_id = {str(event["payload"]["fill_id"]): event for event in fills}
        bot_records = [item for item in records if item["bot_id"] == bot_id]
        rows_for_bot: list[dict[str, object]] = []
        for item in bot_records:
            plan = plans.get(item["decision_id"], {})
            intent = next((entry for entry in plan.get("intents", []) if entry.get("intent_id") == item.get("intent_id")), {})
            fill_event = fill_by_id.get(str(item.get("fill_id")))
            quantity = Decimal(str(item.get("quantity") or 0))
            planned = Decimal(str(item.get("planned_quantity") or 0))
            status = "no_fill" if item["status"] != "filled" or quantity == 0 else ("partial" if quantity < planned else "filled")
            moment = str(fill_event["occurred_at"]) if fill_event else f"{item['session']}T23:59:59"
            cash_after, held_after, _ = state_at(moment)
            payload = fill_event["payload"] if fill_event else {}
            currency = str(payload.get("currency") or intent.get("currency") or "EUR")
            fx_rate = Decimal(str(payload.get("fx_rate", intent.get("sizing_fx_rate", 1))))
            price = Decimal(str(item["fill_price"])) if item.get("fill_price") not in (None, "") else None
            score = scores.get((item.get("snapshot_hash"), item["instrument_id"]), {})
            rows_for_bot.append(
                {
                    "bot": family, "decision_month": item["decision_month"], "decision_date": plan.get("decision_date"),
                    "execution_date": item["session"], "instrument_id": item["instrument_id"], "name": names.get(item["instrument_id"], ""),
                    "side": item.get("side"), "planned_quantity": item.get("planned_quantity"), "quantity": item.get("quantity"),
                    "price_local": None if price is None else str(price), "currency": currency,
                    "fx_rate_to_eur": str(fx_rate), "fx_rate_as_of": "" if currency == "EUR" else item["session"],
                    "value_eur": None if price is None else float(quantity * price * fx_rate),
                    "fee_eur": item.get("fee"), "spread_slippage_cost_eur": item.get("spread_slippage_cost"),
                    "fill_status": status, "status_reason": item.get("reason"), "rule": item.get("trade_reason"),
                    "target_weight": item.get("target_weight"), "score_at_decision": score.get("final_combined_score_10"),
                    "rank_at_decision": score.get("rank"),
                    "order_kind": "initial_buy_in" if item["decision_month"] == first_month[bot_id] else "rebalance",
                    "cash_after_eur": float(cash_after), "position_after_qty": float(held_after.get(item["instrument_id"], Decimal(0))),
                    "ledger_order_id": item.get("order_id"),
                }
            )
        for flow in shadow_rows:
            if flow["side"] not in {"buy", "sell"}:
                continue
            cash_after, held_after, _ = state_at(f"{flow['executed_session']}T23:59:59")
            rows_for_bot.append(
                {
                    "bot": family, "decision_month": str(flow["executed_session"])[:7], "decision_date": str(flow.get("flow_at", ""))[:10],
                    "execution_date": flow["executed_session"], "instrument_id": flow["instrument_id"],
                    "name": names.get(flow["instrument_id"], ""), "side": flow["side"], "planned_quantity": flow["quantity"],
                    "quantity": flow["quantity"], "price_local": flow["price"], "currency": "EUR", "fx_rate_to_eur": "1", "fx_rate_as_of": "",
                    "value_eur": float(Decimal(str(flow["quantity"])) * Decimal(str(flow["price"]))), "fee_eur": flow["fee"],
                    "spread_slippage_cost_eur": float(
                        Decimal(str(flow["quantity"])) * abs(Decimal(str(flow["price"])) - Decimal(str(flow["executed_close"])))
                    ),
                    "fill_status": "filled", "status_reason": "benchmark shadow account fills at the close of the first session after the flow",
                    "rule": f"benchmark {flow['flow_kind']} {flow['amount']} EUR", "target_weight": "1", "score_at_decision": None,
                    "rank_at_decision": None, "order_kind": "initial_buy_in" if flow["flow_kind"] == "contribution" else "rebalance",
                    "cash_after_eur": float(cash_after), "position_after_qty": float(held_after.get(flow["instrument_id"], Decimal(0))),
                    "ledger_order_id": flow["flow_id"],
                }
            )
        rows_for_bot.sort(key=lambda row: (str(row["execution_date"]), str(row["instrument_id"]), str(row["side"])))
        trades.extend(rows_for_bot)

        # weekly holdings and equity at the scored sessions (marks from the stored price book, as the report values them)
        scale: dict[str, float] = {}
        for event in sorted(fills, key=lambda item: str(item["occurred_at"])):
            key = str(event["payload"]["instrument_id"])
            if key in scale:
                continue
            bar = book.bar(key, pd.Timestamp(str(event["occurred_at"])[:10]).date())
            close = report.bots._finite_number(bar.get("close")) if bar else None
            adjusted = report.bots._finite_number(bar.get("adjusted_close")) if bar else None
            scale[key] = close / adjusted if close and adjusted and adjusted > 0 else 1.0
        wealth = dict(zip(bot_reports.get(bot_id, {}).get("dates", []), bot_reports.get(bot_id, {}).get("wealth", [])))
        bench = dict(zip(bot_reports.get(bot_id, {}).get("dates", []), bot_reports.get(bot_id, {}).get("benchmark_wealth", [])))
        for day in weekly:
            sessions = [candidate for candidate in book.sessions if candidate <= day]
            if not sessions:
                continue
            session = sessions[-1]
            cash, held, fx = state_at(f"{session.isoformat()}T23:59:59")
            if not flows or not any(str(flow["effective_at"])[:10] <= session.isoformat() for flow in flows):
                continue
            values, invested, total, missing = value_positions(
                cash, held, fx, lambda key, session=session: report._mark(book, key, session, scale.get(key, 1.0), stale_limit)
            )
            unmarked = ",".join(missing)
            for key, value in values.items():
                holdings.append(
                    {
                        "date": session.isoformat(), "bot": family, "instrument_id": key, "name": names.get(key, ""),
                        "quantity": float(held[key]), "value_eur": value,
                        "weight": None if total is None or value is None or not total else value / total, "marks_unavailable": unmarked,
                    }
                )
            holdings.append(
                {"date": session.isoformat(), "bot": family, "instrument_id": "CASH", "name": "cash", "quantity": float(cash),
                 "value_eur": float(cash), "weight": None if total is None or not total else float(cash) / total, "marks_unavailable": unmarked}
            )
            equity.append(
                {
                    "date": session.isoformat(), "bot": family, "cash_eur": float(cash), "invested_eur": invested, "total_eur": total,
                    "report_total_eur": wealth.get(session.isoformat()), "vwce_benchmark_total_eur": bench.get(session.isoformat()),
                    "marks_unavailable": unmarked,
                }
            )

    trade_frame = pd.DataFrame(trades)
    holdings_frame = pd.DataFrame(holdings)
    equity_frame = pd.DataFrame(equity)
    replay_report = overview.get("replay") or {}
    flagged_replay = bool(replay_report.get("survivorship_unverified"))
    if args.survivorship_mode == "strict" and flagged_replay:
        print("stored replay is labelled survivorship_unverified: pass --survivorship-mode unverified-delistings", file=sys.stderr)
        return 4
    banner_file = out / "SURVIVORSHIP_UNVERIFIED.txt"
    if replay_report.get("survivorship_unverified"):
        for frame in (trade_frame, holdings_frame, equity_frame):
            frame["survivorship_unverified"] = True
        banner = str(replay_report["survivorship_banner"])
        banner_file.write_text(banner + "\nAdmitted: " + ", ".join(replay_report.get("survivorship_unverified_ids") or []) + "\n", encoding="utf-8")
        print(banner)
    elif banner_file.exists():
        banner_file.unlink()  # a stale label from an earlier flagged export must not outlive its data
    trade_frame.to_csv(out / "trades.csv", index=False)
    holdings_frame.to_csv(out / "holdings_weekly.csv", index=False)
    equity_frame.to_csv(out / "equity_weekly.csv", index=False)
    counts = (
        trade_frame.groupby(["bot", "decision_month"]).agg(
            orders=("instrument_id", "size"), initial=("order_kind", lambda s: int((s == "initial_buy_in").sum())),
            filled=("fill_status", lambda s: int((s == "filled").sum())), partial=("fill_status", lambda s: int((s == "partial").sum())),
            no_fill=("fill_status", lambda s: int((s == "no_fill").sum())),
        ).reset_index()
        if not trade_frame.empty else pd.DataFrame()
    )
    counts.to_csv(out / "order_counts.csv", index=False)
    print(f"wrote {len(trade_frame)} orders, {len(holdings)} holding rows, {len(equity)} equity rows to {out}")
    if not trade_frame.empty:
        by_bot = trade_frame.groupby("bot").agg(
            total=("instrument_id", "size"), initial=("order_kind", lambda s: int((s == "initial_buy_in").sum())),
            later=("order_kind", lambda s: int((s == "rebalance").sum())),
        )
        by_bot["rebalances"] = counts.groupby("bot")["decision_month"].nunique()
        by_bot["orders_per_rebalance"] = (by_bot["later"] / by_bot["rebalances"]).round(2)
        print("orders per bot (total / initial buy-in / later / rebalance months / later orders per rebalance):")
        print(by_bot.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
