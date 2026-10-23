"""FIX-BOT: bounded regressions for the verified A06 and RA-BOTS paths."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio import paper_bots as bots, paper_bots_execution as execution
from etf_cockpit.portfolio import paper_bots_report as reports
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)
from tests.test_paper_bots import _NOW, _rows, _scoreboard
from tests.test_paper_bots_execution import (
    RUN_AT, _book, _by, _decisions, _execute, _plans, _ready, _record_month, _records,
)


def test_pinned_baseline_and_unavailable_slots_survive_live_policy_bump(monkeypatch, tmp_path):
    first = _decisions(monkeypatch, tmp_path)
    original = {r["bot_family"]: r for r in first.records}
    _, config = bots._load_config(bots.PAPER_BOTS_CONFIG_PATH)
    config_hash = original["B1"]["config_hash"]
    # A subsequent live score-policy version must leave the immutable pin untouched.
    with TransactionalStore(tmp_path) as store:
        pin = store.list(bots.BASELINE_ENTITY_TYPE)[0]
        pinned_payload = dict(pin.payload)
    monkeypatch.setattr(bots, "load_score_policy", lambda: SimpleNamespace(formula_version="score-engine-v4.0.0"))
    later = _NOW - timedelta(minutes=1)
    changed = _rows(later, run_id="score-run-v4", version="score-engine-v4.0.0", snapshot="b")
    old = _rows(_NOW - timedelta(minutes=5), version=pinned_payload["baseline_score_version"])
    result = _record_month(monkeypatch, tmp_path, old + changed, _scoreboard(changed, later), _NOW)
    for family in ("B1", "B2", "B3"):
        assert next(r for r in result.records if r["bot_family"] == family)["bot_id"] == original[family]["bot_id"]
    assert any(str(r["bot_family"]).startswith("B3-b1") for r in result.records)
    with TransactionalStore(tmp_path) as store:
        assert len(store.list(bots.BASELINE_ENTITY_TYPE)) == 1
        assert dict(store.list(bots.BASELINE_ENTITY_TYPE)[0].payload) == pinned_payload
    unavailable = bots._persist_unavailable(tmp_path, _NOW, "2026-10", config, config_hash, "publication outage")
    assert unavailable.records == ()  # existing slots win even during a publication outage
    november = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    unavailable = bots._persist_unavailable(tmp_path, november, "2026-11", config, config_hash, "publication outage")
    assert [r["bot_family"] for r in unavailable.records] == ["B1"]
    assert unavailable.records[0]["bot_id"] == original["B1"]["bot_id"]
    assert unavailable.records[0]["known_at"] == bots._time_text(november)
    legacy = SimpleNamespace(entity_id=bots._baseline_id(config_hash, pinned_payload["baseline_score_version"]), payload=pinned_payload)
    assert bots._stored_baseline(SimpleNamespace(list=lambda _: [legacy]), config, config_hash) is legacy


def test_empty_selections_use_vwce_without_reallocating_unavailable_evidence(monkeypatch, tmp_path):
    empty = _decisions(monkeypatch, tmp_path / "empty", mutate=lambda board: board.__setitem__("research_promotion_allowed", False))
    for family in ("B1", "B2", "B3"):
        record = next(r for r in empty.records if r["bot_family"] == family)
        assert record["status"] == "available" and record["targets"] == {"VWCE": 1.0}
        assert "VWCE" in record["prices_used"] and record["execution_allowed"] is False
    known = _NOW - timedelta(minutes=5)
    rows = [dict(row, final_action="no_trade") for row in _rows(known)]
    sleeve = _record_month(monkeypatch, tmp_path / "sleeve", rows, _scoreboard(rows, known), _NOW)
    assert next(r for r in sleeve.records if r["bot_family"] == "B2")["targets"] == {"VWCE": 1.0}
    def unknown_gate(board):
        board["research_promotion_allowed"] = board["research_promotion_allowed"].astype(object)
        board.loc[board["instrument_id"] == "AAA", "research_promotion_allowed"] = None
    unknown = _decisions(monkeypatch, tmp_path / "unknown", mutate=unknown_gate)
    assert next(r for r in unknown.records if r["bot_family"] == "B1")["status"] == "unavailable"


def test_captured_price_age_and_per_bar_knowledge_fail_closed(tmp_path):
    cutoff = _NOW
    frame = pd.DataFrame([
        {"instrument_id": "VWCE", "date": "2026-10-12", "close": 100.0, "known_at": "2026-10-12T18:00:00Z"},
        {"instrument_id": "VWCE", "date": "2026-10-13", "close": 999.0, "known_at": "2026-10-20T18:00:00Z"},
    ])
    path = tmp_path / execution.PRICE_FILE_RELATIVE
    path.parent.mkdir(parents=True)
    frame.to_parquet(path)
    book = execution.PriceBook.from_root(tmp_path)
    assert book.known_at is None  # no mtime-derived snapshot knowledge
    context = SimpleNamespace(book=book, config={"sizing_price_max_age_days": 5})
    decision = {"prices_used": {}, "_known_at": cutoff, "_decided_at": cutoff}
    assert execution._sizing_price(context, decision, "VWCE", cutoff.date()) == (Decimal("100.0"), "2026-10-12")
    for day in ("2026-10-01", "2026-10-15", "malformed"):
        decision["prices_used"] = {"VWCE": {"price": 100.0, "price_as_of": day}}
        assert execution._sizing_price(context, decision, "VWCE", cutoff.date()) is None
    decision["prices_used"] = {"VWCE": {"price": 100.0, "price_as_of": "2026-10-09"}}
    assert execution._sizing_price(context, decision, "VWCE", cutoff.date()) == (Decimal("100.0"), "2026-10-09")
    assert book.bar("VWCE", date(2026, 10, 13), known_by=cutoff) is None
    assert book.benchmark_check(cutoff)[0]["close"].tolist() == [100.0]
    frame.drop(columns="known_at").to_parquet(path)
    assert not execution.PriceBook.from_root(tmp_path).usable


def test_valuation_uses_each_buy_lot_and_realises_its_adjusted_basis(tmp_path):
    days = [date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]
    for post_action in (50.0, 90.0):  # split-like and dividend-like adjusted histories
        frame = pd.DataFrame([{"instrument_id": "VWCE", "date": day, "close": raw,
                               "adjusted_close": post_action} for day, raw in zip(days, (100.0, post_action, post_action))])
        book = execution.PriceBook(frame, known_at=RUN_AT)
        events = [{"event_type": "external_flow_recorded", "occurred_at": "2026-10-14T08:00:00Z",
                   "payload": {"effective_at": "2026-10-14T08:00:00Z", "flow_kind": "contribution", "amount": "4000"}}]
        for day, side, quantity in zip(days, ("buy", "buy", "sell"), (10, 10, 5)):
            events.append({"event_type": "fill_recorded", "occurred_at": f"{day}T09:30:00Z",
                           "payload": {"instrument_id": "VWCE", "side": side, "quantity": str(quantity), "fee": "0", "fx_rate": "1"}})
        def replay(selected):
            count = sum(e["event_type"] == "fill_recorded" for e in selected)
            quantity, cash = {1: (10, 3000), 2: (20, 3000 - 10 * post_action),
                              3: (15, 3000 - 5 * post_action)}[count]
            return {"positions": {"VWCE": {"quantity": quantity, "currency": "EUR"}}, "cash": cash}
        ledger = SimpleNamespace(_read_events=lambda: events, _replay=replay, account_id="valuation-fixture")
        snapshots = reports._ledger_snapshots(ledger, book, {"max_stale_mark_sessions": 5}, RUN_AT, days, None, root=tmp_path)
        assert snapshots["total_value"].tolist() == pytest.approx([4000.0] * 3)
        raw = frame.copy()
        raw.loc[2, "adjusted_close"] = float("nan")
        raw_book = execution.PriceBook(raw, known_at=RUN_AT)
        assert reports._mark(raw_book, "VWCE", days[-1], 100 / post_action, 5) == post_action


def test_historical_report_excludes_future_decisions_records_and_ledger_events(monkeypatch, tmp_path):
    book = _ready(monkeypatch, tmp_path)
    cutoff = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    _execute(tmp_path, book, as_of=cutoff)
    before = reports.build_paper_bots_overview(tmp_path, as_of=cutoff, price_book=book)["forward"]
    assert before["bots"] and any(bot["metrics"] for bot in before["bots"])
    _execute(tmp_path, book)  # later split fills and their fees enter the same ledger
    with TransactionalStore(tmp_path) as store:
        decision = dict(store.list(bots.DECISION_ENTITY_TYPE)[0].payload)
        future = {**decision, "decision_id": "future-decision", "bot_id": "future-bot", "status": "unavailable",
                  "known_at": None, "as_of": bots._time_text(RUN_AT)}
        store.put_many([(bots.DECISION_ENTITY_TYPE, future["decision_id"], future)], immutable=True)
        record = {**_records(tmp_path)[0], "record_id": "future-miss", "status": "missed", "fee": "999",
                  "occurred_at": bots._time_text(RUN_AT), "recorded_at": bots._time_text(RUN_AT)}
        store.put_many([(execution.FORWARD_RECORD_TYPE, record["record_id"], record)], immutable=True)
    after = reports.build_paper_bots_overview(tmp_path, as_of=cutoff, price_book=book)["forward"]
    assert after == before


def test_capped_sell_exits_across_sessions_and_waits_only_for_actual_proceeds(monkeypatch, tmp_path):
    book = _ready(monkeypatch, tmp_path)
    _execute(tmp_path, book)
    first = _by(_records(tmp_path), "B2", "VWCE", "filled")[0]
    ledger = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.account_id_for(first["bot_id"]))
    held = next(p.quantity for p in ledger.snapshot().positions if p.instrument_id == "VWCE")
    assert held * 100 > 10000
    assert not execution._awaits_settlement(ledger, RUN_AT)
    with TransactionalStore(tmp_path) as store:
        decision = dict(store.get(bots.DECISION_ENTITY_TYPE, first["decision_id"]).payload)
        exit_time = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
        exit_decision = {**decision, "decision_id": "exit-decision", "as_of": bots._time_text(exit_time),
                         "known_at": bots._time_text(exit_time), "decision_month": "2026-11", "targets": {"cash_weight": 1.0},
                         "prices_used": {"VWCE": {**decision["prices_used"]["VWCE"], "price_as_of": "2026-10-30"}}}
        store.put_many([(bots.DECISION_ENTITY_TYPE, exit_decision["decision_id"], exit_decision)], immutable=True)
    through = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    _execute(tmp_path, book, as_of=through)
    sales = [r for r in _records(tmp_path) if r["decision_id"] == "exit-decision" and r["status"] == "filled"]
    assert len(sales) >= 3 and all(r["side"] == "sell" for r in sales)
    assert sum(Decimal(r["quantity"]) for r in sales) == Decimal(str(held))
    assert all(Decimal(r["quantity"]) * Decimal(r["fill_price"]) <= 10000 for r in sales)
    assert not any(p.instrument_id == "VWCE" and p.quantity > 0 for p in ledger.snapshot().positions)
    assert execution._awaits_settlement(ledger, datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
    assert not execution._awaits_settlement(ledger, through)


def test_failures_persist_funding_is_not_backdated_and_outage_misses_are_terminal(monkeypatch, tmp_path):
    root = tmp_path / "failure"
    book = _ready(monkeypatch, root)
    original = execution._execute_bot
    def fail_one(context, bot_id, decisions):
        if decisions[-1]["bot_family"] == "B1":
            raise PaperLedgerError("injected execution failure")
        return original(context, bot_id, decisions)
    with monkeypatch.context() as patch:
        patch.setattr(execution, "_execute_bot", fail_one)
        result = _execute(root, book)
    assert result.status == "partial"
    overview = reports.build_paper_bots_overview(root, as_of=RUN_AT, price_book=book)["forward"]
    failed = next(bot for bot in overview["bots"] if bot["family"] == "B1")
    assert failed["execution_failures"] == 1
    assert "injected execution failure" in failed["execution_failure_reasons"][0]
    assert any(row["status"] == "failed" for row in failed["trade_log"])
    b2 = _by(_records(root), "B2")[0]
    ledger = PaperLedger(execution.forward_track(root).ledger_root, account_id=execution.account_id_for(b2["bot_id"]))
    assert all(datetime.fromisoformat(flow["flow_at"]) >= _NOW for flow in ledger.external_flows())
    shadow = PaperLedger(execution.forward_track(root).ledger_root, account_id=execution.shadow_id_for(b2["bot_id"]))
    assert all(flow["executed_session"] > _NOW.date().isoformat() for flow in reports._shadow_flows(shadow))
    outage_root = tmp_path / "outage"
    outage_book = _ready(monkeypatch, outage_root, sessions=[date(2026, 10, 13)])
    _execute(outage_root, outage_book)
    missed = _records(outage_root)
    assert missed and all(r["session"] is None and r["status"] == "missed" for r in missed)
    assert all(plan["terminal"] is True for plan in _plans(outage_root))
    _execute(outage_root, _book())
    assert _records(outage_root) == missed


def test_cash_shortfall_cannot_reduce_a_buy_below_five_hundred_euro(monkeypatch, tmp_path):
    decision = next(r for r in _decisions(monkeypatch, tmp_path).records if r["bot_family"] == "B2")
    decision.update(_decided_at=_NOW, _known_at=_NOW)
    config = execution.load_execution_config()[1]
    policy, evidence, _, app_config = execution._cost_policy(tmp_path, config)
    context = SimpleNamespace(config=config, book=_book(), policy=policy, policy_evidence=evidence, app_config=app_config,
                              root=tmp_path, track=execution.forward_track(tmp_path), cutoff=RUN_AT, exec_hash="test", fx_cache={})
    attempts = []
    def refuse(*args, **kwargs):
        attempts.append(kwargs)
        raise PaperLedgerError("available buying power is 450.00")
    ledger = SimpleNamespace(trade_rows=lambda: [], snapshot=lambda: SimpleNamespace(positions=[]), auto_paper_proposal=refuse)
    monkeypatch.setattr(execution, "_limit", lambda *args: None)
    monkeypatch.setattr(execution, "_proposal", lambda *args, **kwargs: {"proposal_allowed": True})
    intent = {"intent_id": "cash-shortfall", "instrument_id": "VWCE", "side": "buy", "planned_quantity": "10",
              "target_weight": "1", "reason": "test target", "sizing_price": "100", "currency": "EUR"}
    record = execution._attempt(context, ledger, decision, intent, date(2026, 10, 15), final_session=True, awaits_settlement=False)
    assert record["status"] == "missed" and record["reason"] == "below_min_trade_value_after_cash_reduction"
    assert record["quantity"] == "0" and len(attempts) == 1
