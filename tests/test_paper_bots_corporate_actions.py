"""Gross cash distributions and nominal-unit split accounting, without providers."""
from datetime import date, datetime, time, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.portfolio import paper_bots_execution as execution
from etf_cockpit.portfolio import paper_bots_report as reports
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, ShadowCostPolicy, _digest
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)
from tests.test_paper_bots import _rows
from tests.test_paper_bots_execution import (
    _allow, _book as _execution_book, _exec_config, _execute, _history_with_columns, _ready, _records, RUN_AT,
)
from tests.test_paper_trading import _proposal

pytestmark = pytest.mark.usefixtures("readiness_pass")

DAYS = [date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]


def _at(day, hour=0):
    return datetime.combine(day, time(hour), tzinfo=timezone.utc)


def _book(*, instrument="VWCE", dividend=2.0, split=0.0, evidenced=True, late=None):
    # Provider prices/dividends already include the split on the last day.
    ratio = split or 1
    rows = []
    for index, day in enumerate(DAYS):
        close = (100 if index == 0 else 100 - dividend) / (ratio if index < 2 else 1)
        if split and index == 2:
            close = (100 - dividend) / ratio
        rows.append({"instrument_id": instrument, "date": day, "open": close, "close": close,
                     "adjusted_close": (100 - dividend) / ratio, "currency": "EUR",
                     "dividends": dividend / ratio if index == 1 else 0.0,
                     "stock_splits": split if index == 2 else 0.0, "actions_evidenced": evidenced,
                     "available_at": late if index == 1 and late else _at(day).isoformat()})
    return execution.PriceBook(pd.DataFrame(rows), known_at=RUN_AT)


def _ledger(tmp_path, instrument="VWCE", *, cash=40000):
    track = execution.forward_track(tmp_path)
    _allow(tmp_path, track=track)
    ledger = PaperLedger(track.ledger_root, account_id="corporate-actions")
    ledger.open_account(initial_cash=0, cost_policy=ShadowCostPolicy(), occurred_at=_at(DAYS[0], 8))
    ledger.record_external_flow(flow_id="fixture", kind="contribution", amount=Decimal(str(cash)),
                               flow_at=_at(DAYS[0], 8), source_authority="fixture", source_checksum="a" * 64)
    _trade(ledger, DAYS[0], 10, 100, instrument)
    return ledger


def _trade(ledger, day, quantity, price, instrument="VWCE"):
    proposal = _proposal(quantity_delta=quantity, source=f"action-{day}-{quantity}")
    proposal["instrument_id"] = instrument
    proposal["input_material"]["instrument_id"] = instrument
    proposal["input_checksum"] = _digest(proposal["input_material"])
    proposal["proposal_id"] = "proposal_" + proposal["input_checksum"][:20]
    proposal.pop("decision_checksum")
    proposal["decision_checksum"] = _digest(proposal)
    order = ledger.accept_proposal(proposal, execution_price=price, quote_currency="EUR", occurred_at=_at(day, 9))
    ledger.record_fill(str(order["order_id"]), quantity=abs(quantity), price=price, reference_price=price, occurred_at=_at(day, 9))


def _sync(tmp_path, ledger, book, through=RUN_AT):
    context = SimpleNamespace(book=book, cutoff=RUN_AT, root=tmp_path, fx_cache={})
    execution._sync_corporate_actions(context, ledger, through)


def _actions(ledger):
    return [event for event in ledger._read_events() if event["event_type"] == "corporate_action"]


@pytest.mark.parametrize("ex_date_trade", [5, -5])
def test_dividend_ex_date_uses_prior_close_quantity(tmp_path, ex_date_trade):
    ledger = _ledger(tmp_path)
    before = ledger.snapshot().cash
    _trade(ledger, DAYS[1], ex_date_trade, 98)
    after_trade = ledger.snapshot().cash
    _sync(tmp_path, ledger, _book())  # late recording must still exclude the ex-date buy/sale
    assert before > 0
    assert ledger.snapshot().cash - after_trade == pytest.approx(20)
    assert datetime.fromisoformat(_actions(ledger)[0]["occurred_at"]) == _at(DAYS[1])


def test_cash_before_ex_date_fill_includes_dividend_appended_after_fill(tmp_path):
    ledger = _ledger(tmp_path)
    before = Decimal(str(ledger.snapshot().cash))
    _trade(ledger, DAYS[1], 5, 98)
    _sync(tmp_path, ledger, _book())

    events = ledger._read_events()
    assert events[-1]["event_type"] == "corporate_action"
    assert datetime.fromisoformat(events[-1]["occurred_at"]) == _at(DAYS[1])
    assert datetime.fromisoformat(events[-1]["payload"]["available_at"]) == _at(DAYS[1])
    assert any(event["event_type"] == "fill_recorded"
               and datetime.fromisoformat(event["occurred_at"]) == _at(DAYS[1], 9)
               for event in events[:-1])
    assert ledger.cash_balance(
        account_id=ledger.account_id, currency="EUR", as_of=_at(DAYS[1], 8),
    ) == before + Decimal("20")


def test_dividend_rerun_and_restart_are_idempotent(tmp_path):
    ledger = _ledger(tmp_path)
    _sync(tmp_path, ledger, _book())
    before = ledger.path.read_bytes()
    reopened = PaperLedger(ledger.root, account_id=ledger.account_id)
    _sync(tmp_path, reopened, _book())
    assert reopened.path.read_bytes() == before
    assert len(_actions(reopened)) == 1


@pytest.mark.parametrize(("closes", "dividends"), [
    ((100, 98, 98), (0, 2, 0)),
    ((100, 98, 110), (0, 2, 0)),
    ((100, 101.75, 110.125), (0, 1.25, 0.375)),
])
def test_cash_dividend_nav_parity_within_one_billionth(tmp_path, closes, dividends):
    ledger = _ledger(tmp_path, cash=1000)
    quantity = Decimal("10")
    rows = []
    adjusted = 100.0
    for index, (day, close, dividend) in enumerate(zip(DAYS, closes, dividends, strict=True)):
        if index:
            adjusted *= (close + dividend) / closes[index - 1]
        rows.append({"instrument_id": "VWCE", "date": day, "open": close, "close": close,
                     "adjusted_close": adjusted, "currency": "EUR", "dividends": dividend,
                     "stock_splits": 0.0, "actions_evidenced": True, "available_at": _at(day).isoformat()})
    book = execution.PriceBook(pd.DataFrame(rows), known_at=RUN_AT)
    credited_cash = Decimal(0)
    expected_values = []
    for day, close, dividend in zip(DAYS, closes, dividends, strict=True):
        _sync(tmp_path, ledger, book, through=_at(day, 12))
        credited_cash += quantity * Decimal(str(dividend))
        expected_nav = quantity * Decimal(str(close)) + credited_cash
        snapshot = ledger.snapshot()
        assert snapshot.positions[0].quantity == quantity
        assert snapshot.cash == pytest.approx(float(credited_cash), rel=1e-9, abs=0)
        nav = snapshot.cash + snapshot.positions[0].quantity * close
        assert nav == pytest.approx(float(expected_nav), rel=1e-9, abs=0)
        expected_values.append(float(expected_nav))
    # The report must not additionally credit adjusted-close synthetic returns.
    snapshots = reports._ledger_snapshots(ledger, book, {"max_stale_mark_sessions": 5}, RUN_AT, DAYS, None, root=tmp_path)
    assert snapshots["total_value"].tolist() == pytest.approx(expected_values, rel=1e-9, abs=0)


@pytest.mark.parametrize("ratio", [10.0, 0.2])
def test_forward_new_split_keeps_nav_and_cost_continuous(tmp_path, ratio):
    ledger = _ledger(tmp_path)
    old = ledger.snapshot()
    book = _book(dividend=0, split=ratio)
    _sync(tmp_path, ledger, book)
    new = ledger.snapshot()
    assert new.positions[0].quantity == pytest.approx(old.positions[0].quantity * ratio)
    assert new.positions[0].average_cost == pytest.approx(old.positions[0].average_cost / ratio)
    assert new.cash + new.positions[0].quantity * book.ledger_bar("VWCE", DAYS[-1])["close"] == pytest.approx(old.cash + 1000)
    values = reports._ledger_snapshots(ledger, book, {"max_stale_mark_sessions": 5}, RUN_AT, DAYS, None, root=tmp_path)
    assert values["total_value"].tolist() == pytest.approx([40000] * 3)
    before = ledger.path.read_bytes()
    _sync(tmp_path, ledger, book)
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("evidence", [False, None, "true", 1])
def test_missing_action_evidence_is_unaccounted_not_zero(tmp_path, evidence):
    ledger = _ledger(tmp_path)
    with pytest.raises(PaperLedgerError, match="corporate_actions_unaccounted: VWCE"):
        _sync(tmp_path, ledger, _book(evidenced=evidence))
    assert not _actions(ledger)


@pytest.mark.parametrize("instrument", ["VWCE", "AAA"])
def test_distributing_etf_and_stock_receive_same_gross_cash(tmp_path, instrument):
    ledger = _ledger(tmp_path, instrument)
    cash = ledger.snapshot().cash
    _sync(tmp_path, ledger, _book(instrument=instrument))
    assert ledger.snapshot().cash == pytest.approx(cash + 20)


def test_dividend_before_later_split_is_not_reduced_or_counted_twice(tmp_path):
    ledger = _ledger(tmp_path)
    cash = ledger.snapshot().cash
    _sync(tmp_path, ledger, _book(split=10))
    assert ledger.snapshot().cash == pytest.approx(cash + 20)
    assert ledger.snapshot().positions[0].quantity == 100


def test_future_availability_never_credits_early(tmp_path):
    ledger = _ledger(tmp_path)
    book = _book(late="2026-10-20T12:00:00Z")
    cash = ledger.snapshot().cash
    _sync(tmp_path, ledger, book, through=_at(DAYS[-1], 12))
    assert ledger.snapshot().cash == cash
    _sync(tmp_path, ledger, book)
    assert ledger.snapshot().cash == cash + 20
    assert ledger.cash_balance(account_id=ledger.account_id, currency="EUR", as_of=_at(DAYS[-1], 12)) == Decimal(str(cash))


def test_forward_pipeline_applies_actions_without_new_decisions(monkeypatch, tmp_path):
    book = _ready(monkeypatch, tmp_path)
    assert _execute(tmp_path, book).status == "available"
    row = next(r for r in _records(tmp_path) if r["instrument_id"] == "AAA" and r["status"] == "filled")
    ledger = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.account_id_for(row["bot_id"]))
    old = ledger.snapshot()
    frame = book._frame.drop(columns=["_instrument"]).copy()
    day = date(2026, 10, 21)
    selected = frame["etf_id"].eq("AAA")
    frame.loc[selected & (frame["date"].dt.date < day), ["open", "close", "high", "low", "dividends"]] /= 10
    frame.loc[selected & (frame["date"].dt.date >= day), ["open", "close", "high", "low"]] /= 10
    frame.loc[selected & (frame["date"].dt.date == day), "stock_splits"] = 10
    refreshed = execution.PriceBook(frame, known_at=RUN_AT)
    result = _execute(tmp_path, refreshed)
    assert result.status == "available", result.warnings
    now = ledger.snapshot()
    def have(snapshot):
        return next(p for p in snapshot.positions if p.instrument_id == "AAA")
    assert have(now).quantity == pytest.approx(have(old).quantity * 10)
    assert have(now).average_cost == pytest.approx(have(old).average_cost / 10)
    assert _execute(tmp_path, refreshed).appended == 0


def test_replay_credits_cash_even_after_order_sessions_finish_and_rerun_is_idempotent(tmp_path):
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

    october = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    history = pd.DataFrame(_history_with_columns(_rows(october)))
    frame = _execution_book()._frame.drop(columns=["_instrument"]).copy()
    frame.loc[frame["etf_id"].eq("AAA") & (frame["date"].dt.date == DAYS[-1]), "dividends"] = 0.5
    book = execution.PriceBook(frame, known_at=RUN_AT)
    track = execution.replay_track(tmp_path, _exec_config())
    _allow(tmp_path, track=track)
    run = run_historical_replay(RUN_AT, root=tmp_path, history=history, price_book=book, now=RUN_AT)
    assert run.status == "available", (run.reason, run.warnings)
    fill = next(r for r in _records(tmp_path, track) if r["instrument_id"] == "AAA" and r["status"] == "filled")
    ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(fill["bot_id"]))
    state = ledger._replay(ledger._read_events())
    quantity = sum(float(r["quantity"]) for r in _records(tmp_path, track)
                   if r["bot_id"] == fill["bot_id"] and r["instrument_id"] == "AAA" and r["status"] == "filled")
    assert state["positions"]["AAA"]["corporate_action_cash"] == Decimal(str(quantity)) * Decimal("0.5")
    before = ledger.path.read_bytes()
    again = run_historical_replay(RUN_AT, root=tmp_path, history=history, price_book=book, now=RUN_AT)
    assert again.appended == 0
    assert ledger.path.read_bytes() == before


def test_report_refuses_an_unrecorded_distribution(tmp_path):
    ledger = _ledger(tmp_path)
    with pytest.raises(PaperLedgerError, match="corporate_actions_unaccounted.*not recorded"):
        reports._ledger_snapshots(ledger, _book(), {"max_stale_mark_sessions": 5}, RUN_AT, DAYS, None, root=tmp_path)


def test_retained_cash_differs_from_reinvested_adjusted_close_after_price_growth(tmp_path):
    ledger = _ledger(tmp_path, cash=1000)
    cash = ledger.snapshot().cash
    _sync(tmp_path, ledger, _book())
    # Ten units at 100, dividend 2, ex-close 98, then price rises to 110.
    cash_nav = ledger.snapshot().cash + 10 * 110
    reinvested_nav = cash + 1000 * (110 / 98)
    assert cash_nav == 1120
    assert reinvested_nav == pytest.approx(1122.448979591837)
    assert reinvested_nav - cash_nav > 1000 * 0.0001
    assert ledger.snapshot().positions[0].quantity == 10  # no authorised automatic reinvestment


def test_pending_order_quantity_changes_with_a_split_before_fill(monkeypatch, tmp_path):
    book = _book(dividend=0, split=10)
    context = SimpleNamespace(book=book, config={"_fill_time": time(9)}, policy=ShadowCostPolicy(),
                              track=SimpleNamespace(ledger_root=tmp_path), warnings=[])
    # A complete bar must be evidenced at the opening fill time.
    for bar in book.action_bars("VWCE"):
        bar["volume"] = 1000
    ledger = SimpleNamespace(trade_rows=lambda: [], snapshot=lambda: SimpleNamespace(positions=[]))
    observed = []

    def proposal(*args, **kwargs):
        observed.append(args[5])  # quantity submitted through the ordinary guarded proposal path
        return {"proposal_allowed": False, "rationale": "test stops before an order"}

    monkeypatch.setattr(execution, "_proposal", proposal)
    monkeypatch.setattr(execution, "_rule_friction_gate", lambda *args: SimpleNamespace(propose=True))
    monkeypatch.setattr(execution, "_record", lambda *args, **kwargs: {"status": args[4], "reason": args[5]})
    intent = {"instrument_id": "VWCE", "intent_id": "split-order", "sizing_price": "100", "side": "buy",
              "planned_quantity": "10", "currency": "EUR", "quantity_basis_date": DAYS[0].isoformat()}
    record = execution._attempt(context, ledger, {}, intent, DAYS[-1], final_session=True, awaits_settlement=False)
    assert observed == [Decimal("100")]
    assert record["status"] == "missed" and "test stops" in record["reason"]


def test_legacy_split_adjusted_fill_is_reported_instead_of_split_twice(tmp_path):
    ledger = _ledger(tmp_path)
    book = _book(dividend=0, split=10)
    # Simulate a legacy replay that already bought the post-split unit basis.
    for bar in book.action_bars("VWCE"):
        if bar["date"].date() < DAYS[-1]:
            bar["open"] = 1.0
    with pytest.raises(PaperLedgerError, match="legacy fill price basis unverified"):
        _sync(tmp_path, ledger, book)
    assert not _actions(ledger)


def test_dividend_and_split_on_same_date_use_prior_close_units(tmp_path):
    ledger = _ledger(tmp_path)
    book = _book(dividend=0, split=2)
    book.action_bars("VWCE")[-1]["dividends"] = 1.0
    cash = ledger.snapshot().cash
    _sync(tmp_path, ledger, book)
    assert ledger.snapshot().cash == cash + 20
    assert ledger.snapshot().positions[0].quantity == 20


def test_sizing_on_split_day_uses_current_units_for_a_previous_close():
    book = _book(dividend=0, split=10)
    context = SimpleNamespace(book=book, config={"sizing_price_max_age_days": 7})
    decision = {"prices_used": {"VWCE": {"price": 10.0, "price_as_of": DAYS[0].isoformat()}},
                "_known_at": _at(DAYS[-1], 12)}
    price, _ = execution._sizing_price(context, decision, "VWCE", DAYS[-1])
    assert price == Decimal("10.0")


def test_future_split_only_converts_quote_units_without_early_ledger_action(tmp_path):
    ledger = _ledger(tmp_path)
    book = _book(dividend=0, split=10)
    cash = ledger.snapshot().cash
    _sync(tmp_path, ledger, book, through=_at(DAYS[1], 12))
    assert not _actions(ledger)
    assert ledger.snapshot().positions[0].quantity == 10
    assert ledger.snapshot().cash == cash
    assert book.ledger_bar("VWCE", DAYS[0])["close"] == 100


def test_vwce_split_is_blocked_by_the_existing_benchmark_contract():
    frame = _execution_book()._frame.drop(columns=["_instrument"]).copy()
    frame.loc[frame["etf_id"].eq("VWCE") & (frame["date"].dt.date == DAYS[-1]), "stock_splits"] = 2.0
    book = execution.PriceBook(frame, known_at=RUN_AT)
    _, check = book.benchmark_check(RUN_AT)
    assert check.status == "unavailable"
    assert "explicit_split_requires_verified_adjustment" in check.reasons
