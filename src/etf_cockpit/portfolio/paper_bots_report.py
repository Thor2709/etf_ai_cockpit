"""Read-only performance report of the paper bots (forward record or labelled historical replay).

Every number comes from the paper ledgers and the canonical valuation, TWR, XIRR and relative-wealth functions; this
module only assembles them. The comparison for every bot is its own cash-flow-matched VWCE shadow account, so an
unmatched or unverifiable pair gives ``unavailable`` with a reason, never an approximation. B0 is the shadow account.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping

import pandas as pd

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.fx_data import EurRateBook, load_fx_rates
from etf_cockpit.data.local_storage import StorageSchemaError, TransactionalStore
from etf_cockpit.portfolio import paper_bots as bots
from etf_cockpit.portfolio import paper_bots_execution as execution
from etf_cockpit.portfolio.benchmark_relative_diagnostics import build_relative_performance
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError
from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series
from etf_cockpit.portfolio.valuation import PortfolioValuationError, build_daily_portfolio_snapshots, expected_session_dates

UNCONFIRMED_LABEL = "Unconfirmed advantage"
REPLAY_LABEL = "conditional historical simulation"
EXPECTATIONS = (
    "3-6 months of forward paper trading shows whether the bots behave sensibly (orders, costs, missed fills).",
    "Separating skill from luck takes years: Part 4 R15 puts a 2% edge with 8% tracking error at about 60 years.",
    "A relative result is shown as an advantage only when its date-clustered interval excludes 0.",
)
_T_95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
    2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def build_paper_bots_overview(
    root: Path | None = None,
    *,
    as_of: datetime | None = None,
    price_book: execution.PriceBook | None = None,
    config_path: Path | None = None,
    execution_config_path: Path | None = None,
) -> dict[str, Any]:
    """Forward record and (when present) the separately stored replay, each built from its own records."""

    project_root = Path(root or ROOT).resolve()
    clock = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reports: dict[str, dict[str, Any]] = {}
    try:
        config_file = Path(config_path or execution._config_file(project_root, "paper_bots_execution_v1.yaml", execution.EXECUTION_CONFIG_PATH))
        _exec_bytes, config = execution.load_execution_config(execution_config_path or config_file)
    except (OSError, TypeError, ValueError) as exc:
        unavailable = _unavailable("forward", None, f"Execution specification unavailable: {type(exc).__name__}.")
        return {"forward": unavailable, "replay": None, "expectations": list(EXPECTATIONS), "execution_allowed": False}
    for track in (execution.forward_track(project_root), execution.replay_track(project_root, config)):
        reports[track.name] = build_track_report(
            project_root, track, config, clock, price_book=price_book, config_path=config_path,
        )
    replay = reports["replay"]
    return {
        "forward": reports["forward"],
        "replay": None if replay["status"] == "unavailable" and not replay["bots"] else replay,
        "expectations": list(EXPECTATIONS),
        "execution_allowed": False,
    }


def _unavailable(track: str, label: str | None, reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "track": track, "label": label, "caveat": None, "as_of": None, "reason": reason,
            "bots": [], "execution_allowed": False}


class _CutoffLedger(PaperLedger):
    """Reuse ledger projections over verified events visible to this report only."""

    def __init__(self, root: Path, *, account_id: str, cutoff: datetime) -> None:
        super().__init__(root, account_id=account_id)
        self._report_cutoff = cutoff

    def _read_events(self) -> list[dict[str, Any]]:
        return [event for event in super()._read_events()
                if (stamp := bots._parse_timestamp(event.get("occurred_at"))) is not None and stamp <= self._report_cutoff]


def build_track_report(
    root: Path,
    track: execution.Track,
    config: Mapping[str, Any],
    cutoff: datetime,
    *,
    price_book: execution.PriceBook | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    base = _unavailable(track.name, track.label, "No paper bot decision is recorded yet.")
    base["caveat"] = track.caveat
    base["survivorship_unverified"] = False
    base["as_of"] = bots._time_text(cutoff)
    book = price_book if price_book is not None else execution.PriceBook.from_root(root)
    try:
        with TransactionalStore(track.store_root, read_only=True) as store:
            decisions = [dict(item.payload) for item in store.list(track.decision_type)]
            records = [dict(item.payload) for item in store.list(track.record_type)]
    except (OSError, ValueError, StorageSchemaError):
        return base
    decisions = [item for item in decisions
                 if (known := bots._parse_timestamp(item.get("known_at"))) is not None and known <= cutoff
                 and (decided := bots._parse_timestamp(item.get("as_of"))) is not None and decided <= cutoff]
    decision_ids = {item.get("decision_id") for item in decisions}
    records = [item for item in records if item.get("decision_id") in decision_ids
               and (stamp := bots._parse_timestamp(item.get("occurred_at") or item.get("recorded_at"))) is not None
               and stamp <= cutoff
               and ((recorded := bots._parse_timestamp(item.get("recorded_at"))) is None or recorded <= cutoff)]
    if not decisions:
        return base
    if not book.usable:
        base["reason"] = book.error or "No benchmark sessions are available."
        return base
    frame, check = book.benchmark_check(cutoff)
    through = max((day for day in book.sessions if day < cutoff.date()), default=None)
    by_bot: dict[str, list[dict[str, Any]]] = {}
    for item in decisions:
        by_bot.setdefault(str(item.get("bot_id")), []).append(item)
    reports = [
        _bot_report(root, track, config, cutoff, book, frame, check, through, bot_id, items, [r for r in records if r.get("bot_id") == bot_id])
        for bot_id, items in sorted(by_bot.items(), key=lambda pair: (_family_order(pair[1][0]), pair[0]))
    ]
    statuses = {item["status"] for item in reports}
    flagged = [item for item in decisions if item.get("survivorship_unverified") is True]
    if flagged:  # replay admitted instruments whose delisting history is unverified: carry the label to every consumer
        base.update(
            survivorship_unverified=True,
            survivorship_unverified_ids=sorted({str(key) for item in flagged for key in item.get("survivorship_unverified_ids") or ()}),
            survivorship_banner=str(flagged[0].get("survivorship_banner") or "SURVIVORSHIP UNVERIFIED"),
        )
    base.update(
        status="available" if statuses == {"available"} else "partial" if "available" in statuses or "partial" in statuses else "unavailable",
        reason=None, bots=reports,
    )
    if base["status"] == "unavailable":
        base["reason"] = "No bot has a verified performance series yet."
    return base


def _family_order(decision: Mapping[str, Any]) -> tuple[int, str]:
    family = str(decision.get("bot_family"))
    return ({"B0": 0, "B1": 1, "B2": 2, "B3": 3}.get(family, 4), family)


def _bot_report(
    root: Path, track: execution.Track, config: Mapping[str, Any], cutoff: datetime, book: execution.PriceBook,
    frame: pd.DataFrame, check: Any, through: date | None, bot_id: str, decisions: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    available = sorted((item for item in decisions if item.get("status") == "available"), key=lambda item: str(item.get("as_of")))
    head = available[-1] if available else sorted(decisions, key=lambda item: str(item.get("as_of")))[-1]
    report: dict[str, Any] = {
        "bot_id": bot_id, "family": head.get("bot_family"), "name": head.get("bot_name"),
        "score_lineage_version": head.get("score_lineage_version"), "spec_hash": head.get("spec_hash"),
        "decisions": len(available), "unavailable_decisions": len(decisions) - len(available),
        "latest_targets": dict(head.get("targets") or {}) if head.get("status") == "available" else {},
        "latest_decision_reason": head.get("reason"), "status": "unavailable", "reason": None,
        "wealth": [], "benchmark_wealth": [], "dates": [], "relative_wealth": [], "drawdown": [],
        "metrics": {}, "uncertainty": _uncertainty(None, None, config), "trade_log": [], "missed_fills": 0,
        "execution_allowed": False,
    }
    ledger = _CutoffLedger(track.ledger_root, account_id=execution.account_id_for(bot_id), cutoff=cutoff)
    shadow = _CutoffLedger(track.ledger_root, account_id=execution.shadow_id_for(bot_id), cutoff=cutoff)
    report["trade_log"] = _trade_log(records, shadow, head)
    report["missed_fills"] = sum(1 for item in records if item.get("status") == "missed")
    failures = [item for item in records if item.get("status") == "failed"]
    report["execution_failures"] = len(failures)
    report["execution_failure_reasons"] = [item.get("reason") for item in failures]
    if through is None or check.status != "available":
        report["reason"] = "VWCE reference series unavailable: " + ", ".join(getattr(check, "reasons", ()) or ("no completed session",))
        return report
    through = _matched_through(ledger, shadow, book, through)
    if through is None:
        report["reason"] = "Awaiting the first VWCE shadow execution close after the first funding flow."
        return report
    report["valued_through"] = through.isoformat()
    try:
        benchmark = shadow.shadow_daily_snapshots(
            frame, series_check=check, through=through, decision_time=cutoff,
            max_stale_sessions=int(config["max_stale_mark_sessions"]),
        )
    except PaperLedgerError as exc:
        report["reason"] = f"Benchmark shadow account unavailable: {str(exc)[:160]}"
        return report
    if head.get("strategy") == "benchmark":
        strategy = benchmark
    else:
        try:
            strategy = _ledger_snapshots(ledger, book, config, cutoff, [day for day in book.sessions if day <= through], check, root=root)
        except (PortfolioValuationError, PaperLedgerError, ValueError, KeyError) as exc:
            report["reason"] = f"Bot valuation unavailable: {str(exc)[:160]}"
            return report
    relative = build_relative_performance(strategy, benchmark)
    report.update(_series_fields(strategy, benchmark))
    carried = list(benchmark.attrs.get("carried_forward_sessions") or ())
    if carried:  # label the bounded carry-forward marks used for VWCE data gaps
        report["benchmark_carried_forward_sessions"] = carried
        report["benchmark_carry_label"] = f"VWCE mark carried forward on {len(carried)} session(s) without a bar: {', '.join(carried)}"
    report["metrics"] = _metrics(strategy, benchmark, relative, records, shadow, config, ledger=ledger)
    report["uncertainty"] = _uncertainty(strategy, benchmark, config)
    report["status"] = "available" if relative.status == "available" and not relative.reasons and not failures else "partial"
    report["reason"] = "; ".join(str(item.get("reason")) for item in failures) if failures else (
        None if report["status"] == "available" else "; ".join(relative.reasons) or "Relative measures are partly unavailable."
    )
    return report


def _matched_through(ledger: PaperLedger, shadow: PaperLedger, book: execution.PriceBook, through: date) -> date | None:
    """Last session through which the shadow account mirrors every funding flow, so both series carry the same flows."""

    flows = ledger.external_flows()
    mirrored = {str(flow["flow_id"]) for flow in _shadow_flows(shadow)}
    pending = [flow for flow in flows if str(flow["flow_id"]) not in mirrored]
    if not pending:
        return through
    entries = [book.first_session_on_or_after(datetime.fromisoformat(str(flow["flow_at"])).date()) for flow in pending]
    if any(entry is None for entry in entries):
        return None
    first_pending = min(entry for entry in entries if entry is not None)
    earlier = [day for day in book.sessions if day < first_pending and day <= through]
    return earlier[-1] if earlier else None


def _ledger_snapshots(
    ledger: PaperLedger, book: execution.PriceBook, config: Mapping[str, Any], cutoff: datetime, sessions: list[date], check: Any,
    *, root: Path = ROOT,
) -> pd.DataFrame:
    """Daily canonical snapshots of a bot account: ledger cash and fills valued with the point-in-time price book."""

    events = [event for event in ledger._read_events() if pd.Timestamp(event["occurred_at"]) <= pd.Timestamp(cutoff)]
    flows = [event for event in events if event["event_type"] == "external_flow_recorded"]
    fills = [event for event in events if event["event_type"] == "fill_recorded"]
    if not flows:
        raise PaperLedgerError("The bot account has no funding flow yet.")
    start = min(pd.Timestamp(event["payload"]["effective_at"]).date() for event in flows)
    days = [day for day in sessions if day >= start]
    if not days:
        raise PaperLedgerError("No completed session exists since the first funding flow.")
    # An exchange session without a price bar (a data gap) still needs its daily snapshot: it is valued with the bounded
    # carried-forward mark below, or stays unavailable when the stale limit is exceeded.
    known_days = set(days)
    days = sorted(known_days | {day.date() for day in expected_session_dates(days[0], days[-1], "XETR")})
    traded = sorted({str(event["payload"]["instrument_id"]) for event in fills})
    fills.sort(key=lambda event: pd.Timestamp(event["occurred_at"]))
    lots: dict[str, list[list[float | None]]] = {}
    realised = 0.0
    fill_index = 0
    stale_limit = int(config["max_stale_mark_sessions"])
    known_text = (cutoff if book.known_at is None else min(book.known_at, cutoff)).isoformat()
    holdings, prices, cash_rows, movements = [], [], [], []
    try:
        fx_rates = load_fx_rates(root / "data" / "clean" / "fx.parquet")
    except (OSError, ValueError, KeyError):
        fx_rates = pd.DataFrame()
    for day in days:
        daily_events = [event for event in events if pd.Timestamp(event["occurred_at"]).date() <= day
                        and (event["event_type"] != "external_flow_recorded"
                             or pd.Timestamp(event["payload"]["effective_at"]).date() <= day)]
        state = ledger._replay(daily_events)
        day_end = (pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)).to_pydatetime()
        rates = EurRateBook(fx_rates, known_by=min(day_end, cutoff))
        # Each buy starts on its own raw basis. FIFO sales realise that lot's
        # accumulated total return, rather than silently discarding it from wealth.
        while fill_index < len(fills) and pd.Timestamp(fills[fill_index]["occurred_at"]).date() <= day:
            event = fills[fill_index]
            fill = event["payload"]
            instrument = str(fill["instrument_id"])
            fill_day = pd.Timestamp(event["occurred_at"]).date()
            bar = book.bar(instrument, fill_day)
            close = bots._finite_number(bar.get("close")) if bar else None
            adjusted = bots._finite_number(bar.get("adjusted_close")) if bar else None
            if close is None or close <= 0:
                raise PaperLedgerError(f"No reference bar for a fill of {instrument}.")
            quantity = float(fill["quantity"])
            instrument_lots = lots.setdefault(instrument, [])
            if fill["side"] == "buy":
                instrument_lots.append([quantity, close / adjusted if adjusted and adjusted > 0 else None])
            else:
                for lot in instrument_lots:
                    sold = min(quantity, float(lot[0]))
                    if sold > 0 and adjusted and adjusted > 0 and lot[1] is not None:
                        realised += sold * (adjusted * float(lot[1]) - close) * float(fill["fx_rate"])
                    lot[0] = float(lot[0]) - sold
                    quantity -= sold
                    if quantity <= 1e-9:
                        break
                if quantity > 1e-9:
                    raise PaperLedgerError(f"Sale has no matching valuation lot for {instrument}.")
            fill_index += 1
        cash_rows.append({"date": day, "cash_value": float(state["cash"]) + realised})
        for instrument in traded:
            position = state["positions"].get(instrument, {})
            quantity = float(position.get("quantity", 0))
            holdings.append({"date": day, "instrument_id": instrument, "quantity": quantity})
            if quantity == 0:
                prices.append({"date": day, "instrument_id": instrument, "price": 0.0})
                continue
            active_lots = [lot for lot in lots.get(instrument, []) if float(lot[0]) > 0]
            marks = [(float(lot[0]), _mark(book, instrument, day, lot[1], stale_limit)) for lot in active_lots]
            if not math.isclose(sum(q for q, _ in marks), quantity, abs_tol=1e-7):
                raise PaperLedgerError(f"Ledger quantity differs from valuation lots for {instrument}.")
            mark = sum(q * value for q, value in marks if value is not None) / quantity if all(value is not None for _, value in marks) else None
            fx = rates.series(str(position.get("currency", "")), [day]).rates.iloc[0]
            if mark is not None and pd.notna(fx):
                prices.append({"date": day, "instrument_id": instrument, "price": mark * float(fx)})
    for event in flows:
        payload = event["payload"]
        movements.append({"date": pd.Timestamp(payload["effective_at"]).date(), "event_type": payload["flow_kind"], "amount": float(payload["amount"])})
    for event in fills:
        if Decimal(event["payload"]["fee"]) > 0:
            movements.append({"date": pd.Timestamp(event["occurred_at"]).date(), "event_type": "fee", "amount": float(event["payload"]["fee"])})
    frames = [
        pd.DataFrame(holdings, columns=["date", "instrument_id", "quantity"]),
        pd.DataFrame(prices, columns=["date", "instrument_id", "price"]),
        pd.DataFrame(cash_rows, columns=["date", "cash_value"]),
        pd.DataFrame(movements, columns=["date", "event_type", "amount"]),
    ]
    for item in frames:
        item["available_at"] = known_text
    result = build_daily_portfolio_snapshots(*frames, decision_time=cutoff, calendar="XETR")
    result.attrs.update(account_id=ledger.account_id, calendar="XETR")
    return result


def _mark(book: execution.PriceBook, instrument: str, day: date, scale: float | None, stale_limit: int) -> float | None:
    """Total-return mark on a lot's raw basis; raw fallback prices are never scaled."""

    bar = book.bar(instrument, day)
    if bar is None:
        last = book.last_bar(instrument, day)
        if last is None:
            return None
        gap = max(
            len([session for session in book.sessions if last["date"].date() < session <= day]),
            len(expected_session_dates(last["date"], day, "XETR")) - 1,  # exchange sessions absent from the book count as stale too
        )
        if gap > stale_limit:
            return None
        bar = last
    adjusted = bots._finite_number(bar.get("adjusted_close"))
    if scale is not None and adjusted is not None and adjusted > 0:
        return adjusted * scale
    value = bots._finite_number(bar.get("close"))
    return value if value is not None and value > 0 else None


def _series_fields(strategy: pd.DataFrame, benchmark: pd.DataFrame) -> dict[str, Any]:
    left = strategy.copy()
    right = benchmark.copy()
    for frame in (left, right):
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    dates = [item.date().isoformat() for item in left["date"]]
    aligned = (
        len(left) == len(right) and bool((left["date"].values == right["date"].values).all())
        and bool((pd.to_numeric(left["external_flow"], errors="coerce").fillna(0.0).values
                  == pd.to_numeric(right["external_flow"], errors="coerce").fillna(0.0).values).all())
    )
    wealth = [_number(value) for value in left["total_value"]]
    bench = [_number(value) for value in right["total_value"]] if len(right) == len(left) else []
    relative = (
        [None if b is None or w is None or b <= 0 else w / b - 1.0 for w, b in zip(wealth, bench, strict=True)]
        if aligned else []
    )
    drawdown: list[float | None] = []
    series = build_portfolio_performance_series(strategy, metric="drawdown", aggregation="day")
    if series.status != "unavailable":
        by_end = {point.period_end.isoformat(): point.value for point in series.points}
        drawdown = [by_end.get(day) for day in dates]
    return {"dates": dates, "wealth": wealth, "benchmark_wealth": bench, "relative_wealth": relative, "drawdown": drawdown}


def _number(value: object) -> float | None:
    number = bots._finite_number(value)
    return number


def _metrics(
    strategy: pd.DataFrame, benchmark: pd.DataFrame, relative: Any, records: list[dict[str, Any]], shadow: PaperLedger,
    config: Mapping[str, Any],
    *, ledger: PaperLedger | None = None,
) -> dict[str, Any]:
    flows = pd.to_numeric(strategy["external_flow"], errors="coerce").fillna(0.0)
    final = _number(strategy["total_value"].iloc[-1])
    filled = [item for item in records if item.get("status") == "filled"]
    evidence = filled
    if ledger is not None and filled:
        state = ledger._replay(ledger._read_events())
        fills_by_id = {item["fill_id"]: item for item in state["fills"]}
        evidence = [execution._fill_evidence_fields(fills_by_id[item["fill_id"]], state["cost_policy"])
                    if item.get("fill_id") in fills_by_id else {} for item in filled]
    notionals = [_number(item.get("traded_notional_eur")) for item in evidence]
    traded = sum(notionals) if all(value is not None for value in notionals) else None
    fees = sum(float(item["fee"]) for item in filled)
    spread_costs = [_number(item.get("spread_slippage_cost")) for item in evidence]
    spread = sum(spread_costs) if all(value is not None for value in spread_costs) else None
    shadow_trades = [flow for flow in _shadow_flows(shadow) if flow["side"] != "none"]
    if not filled and shadow_trades and strategy is benchmark:
        traded = sum(float(Decimal(flow["quantity"]) * Decimal(flow["price"])) for flow in shadow_trades)
        fees = sum(float(flow["fee"]) for flow in shadow_trades)
        spread = sum(float(Decimal(flow["quantity"]) * abs(Decimal(flow["price"]) - Decimal(flow["executed_close"]))) for flow in shadow_trades)
    average = float(pd.to_numeric(strategy["total_value"], errors="coerce").mean())
    drawdowns = [value for value in _series_fields(strategy, benchmark)["drawdown"] if value is not None]
    return {
        "final_value_eur": final, "net_contributions_eur": float(flows.sum()),
        "pnl_eur": None if final is None else final - float(flows.sum()),
        "twr": relative.strategy_twr, "benchmark_twr": relative.benchmark_twr,
        "money_weighted_return": relative.strategy_mwr,
        "period_excess_return": relative.period_excess_return, "period_excess_label": relative.period_excess_return_label,
        "compounded_relative_wealth": relative.compounded_relative_wealth,
        "compounded_relative_wealth_label": relative.compounded_relative_wealth_label,
        "max_drawdown": min(drawdowns) if drawdowns else None,
        "turnover": None if traded is None or not average or average <= 0 else traded / average,
        "traded_notional_eur": traded, "fees_eur": fees, "spread_slippage_eur": spread, "costs_eur": None if spread is None else fees + spread,
        "filled_orders": len(filled), "missed_orders": sum(1 for item in records if item.get("status") == "missed"),
        "relative_status": relative.status, "relative_reasons": list(relative.reasons),
    }


def _shadow_flows(shadow: PaperLedger) -> list[dict[str, Any]]:
    try:
        state = shadow._replay(shadow._read_events())
    except PaperLedgerError:
        return []
    return [dict(item) for item in state["shadow_flows"].values()]


def _trade_log(records: list[dict[str, Any]], shadow: PaperLedger, head: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "session": item.get("session"), "instrument_id": item.get("instrument_id"), "side": item.get("side"),
            "status": item.get("status"), "quantity": item.get("quantity"), "planned_quantity": item.get("planned_quantity"),
            "reference_open": item.get("reference_open"), "fill_price": item.get("fill_price"), "fee": item.get("fee"),
            "reason": item.get("trade_reason"), "outcome_reason": item.get("reason"), "decision_month": item.get("decision_month"),
        }
        for item in records
    ]
    if head.get("strategy") == "benchmark":
        for flow in _shadow_flows(shadow):
            rows.append({
                "session": flow["executed_session"], "instrument_id": flow["instrument_id"], "side": flow["side"],
                "status": "filled" if flow["side"] != "none" else "no_trade", "quantity": flow["quantity"],
                "planned_quantity": flow["quantity"], "reference_open": flow["executed_close"], "fill_price": flow["price"],
                "fee": flow["fee"], "reason": f"benchmark {flow['flow_kind']} {flow['amount']} EUR (flow {flow['flow_id'].rsplit(':', 1)[-1]})",
                "outcome_reason": "shadow account fills at the close of the first session after the flow date",
                "decision_month": None,
            })
    return sorted(rows, key=lambda row: (str(row["session"]), str(row["instrument_id"]), str(row["side"])))


def _t_value(degrees: int, confidence: float) -> float:
    if math.isclose(confidence, 0.95) and degrees <= len(_T_95):
        return _T_95[degrees - 1]
    return NormalDist().inv_cdf(0.5 + confidence / 2.0)


def _monthly_returns(snapshots: pd.DataFrame) -> pd.Series:
    frame = snapshots.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    returns = pd.to_numeric(frame["period_return"], errors="coerce")
    monthly = (1.0 + returns).groupby(frame["date"].dt.to_period("M")).prod(min_count=1) - 1.0
    # A month with any missing daily return is not a complete observation.
    complete = returns.notna().groupby(frame["date"].dt.to_period("M")).all()
    return monthly[complete]


def _uncertainty(strategy: pd.DataFrame | None, benchmark: pd.DataFrame | None, config: Mapping[str, Any]) -> dict[str, Any]:
    """Calendar-month (date-clustered) interval of the paired relative return; an unconfirmed advantage unless it excludes 0."""

    settings = config["uncertainty"]
    minimum = int(settings["minimum_months"])
    confidence = float(settings["confidence"])
    result: dict[str, Any] = {
        "status": "unavailable", "verdict": UNCONFIRMED_LABEL, "months": 0, "minimum_months": minimum, "confidence": confidence,
        "mean_monthly_relative_return": None, "standard_error": None, "lower": None, "upper": None, "bands": [],
        "method": "calendar-month clusters of the paired relative return (bot / VWCE shadow - 1); partial first and current months excluded",
        "reason": "No paired monthly returns yet.",
    }
    if strategy is None or benchmark is None:
        return result
    left, right = _monthly_returns(strategy), _monthly_returns(benchmark)
    months = sorted(set(left.index) & set(right.index))
    if len(strategy) and len(months) >= 1:
        first = pd.to_datetime(strategy["date"]).min().to_period("M")
        last = pd.to_datetime(strategy["date"]).max().to_period("M")
        months = [month for month in months if first < month < last]
    paired = pd.Series([(1.0 + left[m]) / (1.0 + right[m]) - 1.0 for m in months], index=months, dtype=float)
    result["months"] = len(paired)
    if len(paired) < max(2, minimum):
        result["reason"] = f"Only {len(paired)} complete calendar months; at least {max(2, minimum)} are needed."
        return result
    logs = paired.map(lambda value: math.log1p(value))
    mean = float(paired.mean())
    deviation = float(paired.std(ddof=1))
    error = deviation / math.sqrt(len(paired))
    critical = _t_value(len(paired) - 1, confidence)
    lower, upper = mean - critical * error, mean + critical * error
    log_deviation = float(logs.std(ddof=1))
    cumulative = 0.0
    bands = []
    for index, month in enumerate(paired.index, start=1):
        cumulative += float(logs.iloc[index - 1])
        half = critical * log_deviation * math.sqrt(index)
        bands.append({"month": str(month), "relative_wealth": math.expm1(cumulative),
                      "lower": math.expm1(cumulative - half), "upper": math.expm1(cumulative + half)})
    verdict = (
        "Advantage confirmed at the interval level (not proof of skill)" if lower > 0
        else "Underperformance confirmed at the interval level" if upper < 0
        else UNCONFIRMED_LABEL
    )
    result.update(
        status="available", verdict=verdict, mean_monthly_relative_return=mean, standard_error=error, lower=lower, upper=upper,
        bands=bands, reason=None,
    )
    return result


__all__ = ["EXPECTATIONS", "UNCONFIRMED_LABEL", "build_paper_bots_overview", "build_track_report"]
