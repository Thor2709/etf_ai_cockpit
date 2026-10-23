"""PLAN-FIX-20261023 lane LEDGER: regression tests for the verified A07 audit items and decision D5."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from etf_cockpit.data.local_storage import _apply_migrations, _register_ledger_sql_functions
from etf_cockpit.portfolio.ledger import Ledger, LedgerPosting
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, ShadowCostPolicy
from tests.test_paper_trading import _proposal
from tests.test_vwce_benchmark import _at, _check, _ledger, _record, _series

UTC = timezone.utc


def _day(days: int) -> datetime:
    return datetime(2026, 5, 1, tzinfo=UTC) + timedelta(days=days)


def _policy_account(tmp_path, commission: str = "0") -> PaperLedger:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=0, cost_policy=ShadowCostPolicy(commission=Decimal(commission), lot_size=Decimal("1")),
                        occurred_at=_day(0))
    return ledger


def _position(ledger: PaperLedger):
    return next(item for item in ledger.snapshot().positions if item.instrument_id == "VWCE")


def _fund(ledger: PaperLedger, amount: int = 10_000) -> None:
    ledger.record_external_flow(flow_id="c1", kind="contribution", amount=amount, flow_at=_day(0),
                                source_authority="fixture", source_checksum="a" * 64)


def test_a07_f1_external_flows_are_not_pnl_or_drawdown(tmp_path) -> None:
    ledger = _policy_account(tmp_path)
    _fund(ledger)
    ledger.record_external_flow(flow_id="w1", kind="withdrawal", amount=2_000, flow_at=_day(1),
                                source_authority="fixture", source_checksum="a" * 64)
    snapshot = ledger.snapshot()
    assert snapshot.cash == pytest.approx(8_000)
    assert snapshot.pnl == pytest.approx(0.0)
    assert snapshot.drawdown == pytest.approx(0.0)


def test_a07_f2_weekend_contribution_mirrors_into_the_shadow_account(tmp_path) -> None:
    frame = _series()
    policy = ShadowCostPolicy(commission=Decimal("1"), adverse_bps=Decimal("0"), lot_size=Decimal("1"))
    shadow = _ledger(tmp_path, "shadow-weekend", policy)
    saturday = _at("2025-03-08")  # the active flow keeps its default effective time (a non-session day)
    flow = _record(shadow, flow_id="sat", kind="contribution", amount=1000, flow_at=saturday,
                   prices=frame, series_check=_check(frame), cost_policy=policy)
    assert flow["entry_session"] == "2025-03-10" and flow["executed_session"] == "2025-03-10"


def test_d5_shadow_flow_fills_at_the_next_session_open_and_refuses_a_series_without_open(tmp_path) -> None:
    closes = [100.0, 100.0, 104.0, 107.0, 110.0, 110.0, 106.0, 103.0, 101.0, 100.0]
    frame = _series(closes, open=[c - 3.0 for c in closes])
    policy = ShadowCostPolicy(commission=Decimal("1"), adverse_bps=Decimal("10"), lot_size=Decimal("1"))
    shadow = _ledger(tmp_path, "shadow-open", policy)
    buy = _record(shadow, flow_id="f1", kind="contribution", amount=1000, flow_at=_at("2025-03-07"),
                  prices=frame, series_check=_check(frame), cost_policy=policy)
    # Friday flow -> executed Monday 10 Mar; Monday close is 110 and the open 107.
    assert buy["executed_session"] == "2025-03-10"
    assert Decimal(buy["executed_open"]) == Decimal("107.0")
    assert Decimal(buy["price"]) == Decimal("107.0") * Decimal("1.001")
    no_open = _series(closes).drop(columns=["open"])
    other = _ledger(tmp_path, "shadow-no-open", policy)
    with pytest.raises(PaperLedgerError, match="open"):
        _record(other, flow_id="f1", kind="contribution", amount=1000, flow_at=_at("2025-03-07"),
                prices=no_open, series_check=_check(no_open), cost_policy=policy)


def test_a07_f4_split_applies_only_to_units_held_at_the_ex_date(tmp_path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000, occurred_at=_day(0))
    before = ledger.accept_proposal(_proposal(source="pre"), execution_price=10, occurred_at=_day(1))
    ledger.record_fill(str(before["order_id"]), quantity=10, price=10, occurred_at=_day(1))
    after = ledger.accept_proposal(_proposal(source="post"), execution_price=5, occurred_at=_day(3))
    ledger.record_fill(str(after["order_id"]), quantity=10, price=5, occurred_at=_day(3))
    ledger.apply_corporate_action("VWCE", split_ratio=2, source_authority="fixture", source_checksum="b" * 64,
                                  occurred_at=_day(2))  # recorded late, effective between the two fills
    position = _position(ledger)
    assert position.quantity == pytest.approx(30)
    assert position.average_cost == pytest.approx(150 / 30)


def test_a07_f5_outcome_ignores_future_splits_and_includes_entitled_dividends(tmp_path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000, occurred_at=_day(0))
    order = ledger.accept_proposal(_proposal(source="mature"), execution_price=10, occurred_at=_day(1))
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10, occurred_at=_day(1))
    ledger.apply_corporate_action("VWCE", split_ratio=1, cash_dividend_per_unit=0.5, source_authority="fixture",
                                  source_checksum="c" * 64, occurred_at=_day(10))
    ledger.apply_corporate_action("VWCE", split_ratio=2, source_authority="fixture",
                                  source_checksum="d" * 64, occurred_at=_day(30))
    outcome = ledger.mature_outcome(str(order["order_id"]), adjusted_close=10.5, benchmark_return=0, cash_return=0,
                                    source_authority="fixture", source_checksum="e" * 64, occurred_at=_day(21))
    assert outcome["quantity"] == pytest.approx(10)  # the day-30 split is after maturity
    assert outcome["cash_dividends"] == pytest.approx(5)
    assert outcome["gross_return"] == pytest.approx((10.5 * 10 + 5 - 100) / 100)


def test_a07_f6_fill_sets_quote_currency_and_clears_a_pre_fill_mark(tmp_path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000, occurred_at=_day(0))
    ledger.mark("VWCE", adjusted_close=11, source_checksum="a" * 64, occurred_at=_day(1))
    order = ledger.accept_proposal(_proposal(source="usd"), execution_price=10, quote_currency="USD", fx_rate=0.9,
                                   occurred_at=_day(2))
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10, fx_rate=0.9, occurred_at=_day(2))
    position = _position(ledger)
    assert position.currency == "USD"
    assert position.mark_price is None  # the EUR pre-fill mark is not carried into the USD position
    with pytest.raises(PaperLedgerError, match="fx_rate"):
        ledger.mark("VWCE", adjusted_close=12, source_checksum="b" * 64, occurred_at=_day(3))


def test_a07_f7_unsettled_reversal_does_not_suppress_fill_confirmation() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _register_ledger_sql_functions(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    _apply_migrations(connection)
    setup = Ledger(connection)
    setup.create_account("cash", name="Cash", account_type="asset", authority="broker", account_role="cash")
    setup.create_account("equity", name="Equity", account_type="equity", authority="broker")
    setup.post("buy-cash", authority="broker", effective_at="2027-01-01T00:00:00+00:00",
               settlement_at="2027-01-02T00:00:00+00:00", postings=(
                   LedgerPosting("cash", "EUR", credit=Decimal("100")), LedgerPosting("equity", "EUR", debit=Decimal("100"))))
    setup.reverse("buy-cash", entry_id="buy-cash-rev", effective_at="2027-01-03T00:00:00+00:00", authority="broker",
                  settlement_at="2027-01-10T00:00:00+00:00")
    ledger = Ledger(connection, fill_entry_ids={"fill-1": "buy-cash"})
    # The reversal has not settled by 5 Jan: the settled cash balance still deducts the fill, so it stays confirmed.
    assert ledger.confirmed_fill_ids(account_id="cash", as_of=datetime(2027, 1, 5, tzinfo=UTC)) == frozenset({"fill-1"})
    assert ledger.confirmed_fill_ids(account_id="cash", as_of=datetime(2027, 1, 11, tzinfo=UTC)) == frozenset()
    connection.close()


def test_a07_f8_partial_fills_share_one_commission(tmp_path) -> None:
    ledger = _policy_account(tmp_path, commission="2")
    _fund(ledger)
    order = ledger.accept_proposal(_proposal(source="partial"), execution_price=10, fee=2, occurred_at=_day(1))
    ledger.record_fill(str(order["order_id"]), fill_id="half-1", quantity=5, price=10, reference_price=10, occurred_at=_day(2))
    ledger.record_fill(str(order["order_id"]), fill_id="half-2", quantity=5, price=10, reference_price=10, occurred_at=_day(2))
    assert ledger.snapshot().cash == pytest.approx(10_000 - 100 - 2)  # one commission in total, not one per fill
    other = ledger.accept_proposal(_proposal(source="partial-b"), execution_price=10, fee=2, occurred_at=_day(3))
    with pytest.raises(PaperLedgerError):  # a full commission on a half fill is a double charge
        ledger.record_fill(str(other["order_id"]), quantity=5, price=10, fee=2, reference_price=10, occurred_at=_day(4))
