"""Issue #968 (train OL1): ledger cash cutoffs, order lifecycle and cash reservation regression tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest

from etf_cockpit.core.config import SettlementConfig
from etf_cockpit.data.local_storage import _apply_migrations, _register_ledger_sql_functions
from etf_cockpit.portfolio.ledger import Ledger, LedgerInvariantError, LedgerPosting
from etf_cockpit.trading.cash_reservation import CashReservationError
from etf_cockpit.trading.order_lifecycle import (
    IdempotencyConflict,
    OrderLifecycle,
    OrderLifecycleError,
    OrderState,
    OrderTransitionError,
)

UTC = timezone.utc
AT = datetime(2026, 9, 30, 10, tzinfo=UTC)


# --- ledger.cash_balance (D106-N001/N002, D06-C2-N001/N002/N003) -------------------------------


def _ledger() -> tuple[sqlite3.Connection, Ledger]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _register_ledger_sql_functions(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    _apply_migrations(connection)
    ledger = Ledger(connection)
    ledger.create_account("cash", name="Cash", account_type="asset", authority="broker", account_role="cash")
    ledger.create_account("equity", name="Equity", account_type="equity", authority="broker")
    return connection, ledger


def _deposit(
    ledger: Ledger, entry_id: str, amount: str, effective_at: str, settlement_at: str | None
) -> None:
    ledger.post(
        entry_id,
        authority="broker",
        effective_at=effective_at,
        settlement_at=settlement_at,
        postings=(
            LedgerPosting("cash", "EUR", debit=Decimal(amount)),
            LedgerPosting("equity", "EUR", credit=Decimal(amount)),
        ),
    )


def _cash(ledger: Ledger, as_of: datetime, **kwargs: object) -> Decimal:
    return ledger.cash_balance(account_id="cash", currency="EUR", as_of=as_of, authority="broker", **kwargs)


@pytest.mark.parametrize(
    ("settlement_at", "included"),
    [
        ("2026-10-01T10:00:00Z", True),  # exactly the cutoff
        ("2026-10-01T00:00:00-11:00", False),  # 11:00Z, after the cutoff though lexically smaller
        ("2026-10-01T20:00:00+11:00", True),  # 09:00Z, before the cutoff though lexically larger
    ],
)
def test_cash_balance_compares_instants_not_text(settlement_at: str, included: bool) -> None:
    connection, ledger = _ledger()
    _deposit(ledger, "e1", "100", "2026-09-01T00:00:00Z", settlement_at)
    cutoff = datetime(2026, 10, 1, 10, tzinfo=UTC)
    future_known = datetime.now(UTC) + timedelta(days=1)

    assert _cash(ledger, cutoff, known_at=future_known) == (Decimal("100") if included else Decimal("0"))
    connection.close()


def test_backdated_entry_recorded_after_the_cutoff_is_excluded_from_historical_cash() -> None:
    connection, ledger = _ledger()
    _deposit(ledger, "known", "100", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z")
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    stamp = (cutoff - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    _deposit(ledger, "backdated", "500", stamp, stamp)  # recorded now, i.e. after the cutoff

    assert _cash(ledger, cutoff, known_at=datetime(2026, 9, 2, tzinfo=UTC)) == Decimal("0")
    assert _cash(ledger, cutoff) == Decimal("0")
    assert _cash(ledger, cutoff, known_at=datetime.now(UTC) + timedelta(minutes=1)) == Decimal("600")
    connection.close()


def test_missing_settlement_is_unknown_and_future_effective_cash_is_excluded() -> None:
    connection, ledger = _ledger()
    _deposit(ledger, "no-settlement", "100", "2026-09-01T00:00:00Z", None)
    _deposit(ledger, "future-effective", "40", "2026-12-01T00:00:00Z", "2026-09-01T00:00:00Z")
    _deposit(ledger, "settled", "7", "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")

    assert _cash(ledger, datetime(2026, 10, 1, tzinfo=UTC), known_at=datetime.now(UTC) + timedelta(days=1)) == Decimal("7")
    connection.close()


def test_duplicate_external_cash_event_cannot_be_posted_twice() -> None:
    connection, ledger = _ledger()
    _deposit(ledger, "dup", "100", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z")

    with pytest.raises((LedgerInvariantError, sqlite3.IntegrityError)):
        _deposit(ledger, "dup", "100", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z")
    connection.close()


def test_naive_cutoff_is_rejected() -> None:
    connection, ledger = _ledger()
    with pytest.raises(LedgerInvariantError):
        _cash(ledger, datetime(2026, 10, 1))
    with pytest.raises(LedgerInvariantError):
        _cash(ledger, AT, known_at=datetime(2026, 10, 1))
    connection.close()


# --- order lifecycle ------------------------------------------------------------------------


class FixedCashSource:
    cash_includes_unsettled_trades = False

    def __init__(self, amount: Decimal) -> None:
        self.amount = amount

    def cash_balance(self, *, account_id: str, currency: str, as_of: datetime) -> Decimal:
        return self.amount


class SettledOnlySource(FixedCashSource):
    """A settled-cash source that reports which fills it has posted."""

    def __init__(self, amount: Decimal, confirmed: frozenset[str] = frozenset()) -> None:
        super().__init__(amount)
        self.confirmed = confirmed

    def confirmed_fill_ids(self, *, account_id: str, as_of: datetime) -> frozenset[str]:
        return self.confirmed


def _lifecycle(path: Path, cash: Decimal = Decimal("1000"), *, lag: int = 2, source: object | None = None) -> OrderLifecycle:
    path.mkdir(parents=True, exist_ok=True)
    return OrderLifecycle(
        path / "orders.sqlite3",
        source if source is not None else FixedCashSource(cash),
        settlement=SettlementConfig(settlement_lags={"XETRA": {"etf": lag}}),
    )


def _reserve(
    lifecycle: OrderLifecycle,
    *,
    order_id: str = "order-1",
    quantity: str = "10",
    price: str = "10",
    occurred_at: datetime = AT,
    venue: str = "XETRA",
) -> None:
    lifecycle.reserve_order(
        account_id="account-1",
        order_id=order_id,
        idempotency_key=f"request-{order_id}",
        currency="EUR",
        side="buy",
        quantity=Decimal(quantity),
        limit_price=Decimal(price),
        fee_estimate=Decimal("0"),
        venue=venue,
        instrument_type="etf",
        occurred_at=occurred_at,
    )


def _unknown(lifecycle: OrderLifecycle, order_id: str = "order-1") -> None:
    lifecycle.mark_unknown(order_id, event_key=f"unknown-{order_id}", reason="Submission result was lost", occurred_at=AT)


def _reconcile(lifecycle: OrderLifecycle, target: OrderState, *, key: str = "rec", **overrides: object):
    kwargs: dict[str, object] = {
        "event_key": key,
        "reason": "Broker evidence matched",
        "occurred_at": AT,
    }
    if target in {OrderState.PARTIALLY_FILLED, OrderState.FILLED}:
        kwargs.update(
            fill_id="fill-1",
            fill_quantity=Decimal("4"),
            fill_price=Decimal("10"),
            fill_fee=Decimal("0"),
            fill_fx_rate=Decimal("1"),
            fill_cash_change=Decimal("-40"),
            remaining_quantity=Decimal("6"),
        )
    kwargs.update(overrides)
    return lifecycle.reconcile("order-1", target, **kwargs)


@pytest.mark.parametrize("target", [OrderState.FILLED, OrderState.PARTIALLY_FILLED])
def test_fill_states_are_unreachable_through_transition(tmp_path: Path, target: OrderState) -> None:
    lifecycle = _lifecycle(tmp_path)
    _reserve(lifecycle)
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT)

    with pytest.raises(OrderTransitionError):
        lifecycle.transition("order-1", target, event_key="fake-fill", occurred_at=AT)
    with pytest.raises(OrderTransitionError):
        lifecycle.transition(
            "order-1",
            OrderState.ACKNOWLEDGED,
            event_key="fake-fill-event",
            event_type="fill",
            payload={"fill_id": "x", "quantity": "10", "price": "10"},
            occurred_at=AT,
        )

    assert lifecycle.get_state("order-1") is OrderState.ACKNOWLEDGED
    assert lifecycle.get_reservation("order-1").reserved_amount == Decimal("100")


def test_exact_reconcile_retry_is_idempotent_and_a_changed_retry_conflicts(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _reserve(lifecycle)
    _unknown(lifecycle)
    first = _reconcile(lifecycle, OrderState.PARTIALLY_FILLED)
    events = lifecycle.event_count()

    again = _reconcile(lifecycle, OrderState.PARTIALLY_FILLED)

    assert again.event_id == first.event_id
    assert lifecycle.event_count() == events
    assert lifecycle.get_reservation("order-1").reserved_amount == Decimal("60")
    with pytest.raises(IdempotencyConflict):
        _reconcile(
            lifecycle,
            OrderState.PARTIALLY_FILLED,
            fill_quantity=Decimal("5"),
            fill_cash_change=Decimal("-50"),
            remaining_quantity=Decimal("5"),
        )


def test_exact_reconcile_retry_after_cancel_is_idempotent(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _reserve(lifecycle)
    _unknown(lifecycle)
    first = _reconcile(lifecycle, OrderState.CANCELLED)

    assert _reconcile(lifecycle, OrderState.CANCELLED).event_id == first.event_id
    with pytest.raises(IdempotencyConflict):
        _reconcile(lifecycle, OrderState.CANCELLED, reason="different reason")


def test_post_fill_buying_power_is_enforced(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path, Decimal("100"))
    _reserve(lifecycle)
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT)

    with pytest.raises(OrderLifecycleError):
        lifecycle.record_fill("order-1", fill_id="f1", quantity=Decimal("10"), price=Decimal("20"), occurred_at=AT)

    assert lifecycle.get_state("order-1") is OrderState.ACKNOWLEDGED


def test_reconciled_fill_exceeding_cash_is_rejected(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path, Decimal("100"))
    _reserve(lifecycle)
    _unknown(lifecycle)

    with pytest.raises(OrderLifecycleError):
        _reconcile(
            lifecycle,
            OrderState.FILLED,
            fill_quantity=Decimal("10"),
            fill_price=Decimal("20"),
            fill_cash_change=Decimal("-200"),
            remaining_quantity=None,
        )

    assert lifecycle.get_state("order-1") is OrderState.RECONCILIATION_REQUIRED


def test_t_plus_zero_buy_of_200_from_100_cannot_pass(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path, lag=0, source=SettledOnlySource(Decimal("100")))
    _reserve(lifecycle)
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT)

    with pytest.raises(OrderLifecycleError):
        lifecycle.record_fill("order-1", fill_id="f1", quantity=Decimal("10"), price=Decimal("20"), occurred_at=AT)

    assert lifecycle.get_state("order-1") is OrderState.ACKNOWLEDGED


@pytest.mark.parametrize("source_kind", ["fixed", "projected", "settled", "ledger"])
def test_settled_commitment_is_released_only_after_the_cash_source_posts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_kind: str,
) -> None:
    class ProjectedSource(FixedCashSource):
        def projected_fill_ids(self, *, account_id: str, as_of: datetime) -> frozenset[str]:
            return frozenset()

    connection = None
    if source_kind == "ledger":
        monkeypatch.setattr("etf_cockpit.portfolio.ledger._utc_now", lambda: AT.isoformat())
        connection, _ = _ledger()
        source = Ledger(connection, fill_entry_ids={"f1": "cash-f1"})
        source.create_account("account-1", name="Order cash", account_type="asset", authority="broker", account_role="cash")
        source.post("opening", authority="broker", effective_at=AT.isoformat(), settlement_at=AT.isoformat(), postings=(
            LedgerPosting("account-1", "EUR", debit=Decimal("1000")),
            LedgerPosting("equity", "EUR", credit=Decimal("1000")),
        ))
    else:
        source = {"fixed": FixedCashSource, "projected": ProjectedSource, "settled": SettledOnlySource}[source_kind](Decimal("1000"))
    unposted = _lifecycle(tmp_path / "a", lag=0, source=source)
    _reserve(unposted)
    unposted.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT)
    unposted.record_fill("order-1", fill_id="f1", quantity=Decimal("10"), price=Decimal("10"), occurred_at=AT)
    later = AT + timedelta(days=3)
    assert unposted.available_buying_power(account_id="account-1", currency="EUR", as_of=later) == Decimal("900")

    if connection is not None:
        source.post("cash-f1", authority="broker", effective_at=AT.isoformat(), settlement_at=later.isoformat(), postings=(
            LedgerPosting("account-1", "EUR", credit=Decimal("100")),
            LedgerPosting("equity", "EUR", debit=Decimal("100")),
        ))
        assert source.confirmed_fill_ids(account_id="account-1", as_of=AT) == frozenset()
        assert source.confirmed_fill_ids(account_id="account-1", as_of=later) == frozenset({"f1"})
        assert Ledger(connection).confirmed_fill_ids(account_id="account-1", as_of=later) == frozenset()
        assert unposted.available_buying_power(account_id="account-1", currency="EUR", as_of=later) == Decimal("900")
        connection.close()

    posted = _lifecycle(tmp_path / "b", lag=0, source=SettledOnlySource(Decimal("900"), frozenset({"f1"})))
    _reserve(posted)
    posted.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT)
    posted.record_fill("order-1", fill_id="f1", quantity=Decimal("10"), price=Decimal("10"), occurred_at=AT)
    assert posted.available_buying_power(account_id="account-1", currency="EUR", as_of=later) == Decimal("900")


def test_reconcile_with_zero_remaining_becomes_filled(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _reserve(lifecycle)
    _unknown(lifecycle)

    event = _reconcile(
        lifecycle,
        OrderState.PARTIALLY_FILLED,
        fill_quantity=Decimal("10"),
        fill_cash_change=Decimal("-100"),
        remaining_quantity=Decimal("0"),
    )

    assert event.state is OrderState.FILLED
    assert lifecycle.get_state("order-1") is OrderState.FILLED


def test_rejected_after_a_committed_partial_fill_restores_the_partial_state(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _reserve(lifecycle)
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT)
    lifecycle.record_fill("order-1", fill_id="f1", quantity=Decimal("4"), price=Decimal("10"), occurred_at=AT)
    _unknown(lifecycle)

    event = _reconcile(lifecycle, OrderState.REJECTED, key="rej")
    assert event.state is OrderState.PARTIALLY_FILLED
    assert lifecycle.get_state("order-1") is OrderState.PARTIALLY_FILLED
    assert lifecycle.get_intent("order-1").remaining_quantity == Decimal("6")
    assert lifecycle.get_reservation("order-1").reserved_amount == Decimal("60")
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=AT) == Decimal("900")
    assert event.payload["partial_fill_committed"] is True
    assert event.payload["filled_quantity"] == "4"
    assert event.payload["remaining_quantity"] == "6"
    assert event.payload["requested_state"] == "REJECTED"
    count = lifecycle.event_count()
    assert _reconcile(lifecycle, OrderState.REJECTED, key="rej").event_id == event.event_id
    assert lifecycle.event_count() == count
    assert len(lifecycle.fill_events()) == 1
    with pytest.raises(IdempotencyConflict):
        _reconcile(lifecycle, OrderState.CANCELLED, key="rej")


def test_event_timestamps_are_monotonic_and_not_before_order_creation(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _reserve(lifecycle)

    with pytest.raises(OrderLifecycleError):
        lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="early", occurred_at=AT - timedelta(hours=1))
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT + timedelta(minutes=5))
    with pytest.raises(OrderLifecycleError):
        lifecycle.record_fill(
            "order-1", fill_id="f1", quantity=Decimal("1"), price=Decimal("10"), occurred_at=AT + timedelta(minutes=1)
        )


@pytest.mark.parametrize("venue,zones,fill_at,expected", [
    ("XETRA", None, datetime(2026, 10, 1, 23, 30, tzinfo=UTC), date(2026, 10, 5)),
    ("NYSE", None, datetime(2026, 12, 2, 1, 30, tzinfo=UTC), date(2026, 12, 2)),
    ("NYSE", {}, datetime(2026, 12, 2, 1, 30, tzinfo=UTC), None),
    ("NYSE", {"NYSE": "invalid/zone"}, datetime(2026, 12, 2, 1, 30, tzinfo=UTC), None),
])
def test_settlement_date_is_refreshed_on_fill_using_the_exchange_local_trade_date(
    tmp_path: Path, venue: str, zones: dict[str, str] | None, fill_at: datetime, expected: date | None,
) -> None:
    lifecycle = OrderLifecycle(
        tmp_path / "orders.sqlite3", FixedCashSource(Decimal("1000")),
        settlement=SettlementConfig(settlement_lags={venue: {"etf": 1}}), venue_timezones=zones,
    )
    _reserve(lifecycle, venue=venue)
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=AT)
    # Thu 2026-10-01 23:30 UTC is already Fri 2026-10-02 in Berlin: T+1 is Monday 2026-10-05.

    lifecycle.record_fill("order-1", fill_id="f1", quantity=Decimal("1"), price=Decimal("10"), occurred_at=fill_at)

    with sqlite3.connect(lifecycle.db_path) as connection:
        stored = connection.execute("SELECT settlement_date FROM order_intents WHERE order_id = 'order-1'").fetchone()[0]
        commitment = connection.execute("SELECT settlement_date FROM unsettled_cash_commitments").fetchone()[0]
    assert stored == commitment == (None if expected is None else expected.isoformat())
    if expected is None:
        assert "time zone" in lifecycle.get_intent("order-1").settlement_warning
        assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=fill_at) == Decimal("900")


@pytest.mark.parametrize("finish", ["fill", "cancel"])
def test_reservations_created_after_the_as_of_do_not_reduce_historical_buying_power(tmp_path: Path, finish: str) -> None:
    lifecycle = _lifecycle(tmp_path, Decimal("1000"))
    _reserve(lifecycle, occurred_at=AT + timedelta(days=1))

    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=AT) == Decimal("1000")
    assert lifecycle.available_buying_power(
        account_id="account-1", currency="EUR", as_of=AT + timedelta(days=2)
    ) == Decimal("900")
    partial_at = AT + timedelta(days=2)
    final_at = AT + timedelta(days=3)
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="ack", occurred_at=partial_at)
    lifecycle.record_fill("order-1", fill_id="f1", quantity=Decimal("4"), price=Decimal("8"), occurred_at=partial_at)
    if finish == "fill":
        lifecycle.record_fill("order-1", fill_id="f2", quantity=Decimal("6"), price=Decimal("8"), occurred_at=final_at)
    else:
        lifecycle.transition("order-1", OrderState.CANCELLED, event_key="cancel", occurred_at=final_at)
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=AT) == Decimal("1000")
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=AT + timedelta(days=1)) == Decimal("900")
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=partial_at) == Decimal("908")
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=final_at) == Decimal("920" if finish == "fill" else "968")
    with sqlite3.connect(lifecycle.db_path) as connection:
        connection.execute("DROP TRIGGER order_events_no_delete")
        connection.execute("DELETE FROM order_lifecycle_events WHERE event_type = 'cash_reserved'")
    with pytest.raises(CashReservationError, match="Reservation history unavailable"):
        lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=AT + timedelta(days=1))
