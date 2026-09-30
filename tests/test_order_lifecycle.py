from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from etf_cockpit.core.config import SettlementConfig, load_settlement_config
from etf_cockpit.portfolio.ledger import Ledger
from etf_cockpit.portfolio.paper_trading import PaperLedger
from etf_cockpit.trading.cash_reservation import InsufficientBuyingPower
from etf_cockpit.trading.order_lifecycle import (
    ALLOWED_TRANSITIONS,
    OrderLifecycle,
    OrderLifecycleError,
    OrderState,
    OrderTransitionError,
)


class FixedCashSource:
    cash_includes_unsettled_trades = False

    def __init__(self, amount: Decimal) -> None:
        self.amount = amount

    def cash_balance(self, *, account_id: str, currency: str, as_of: datetime) -> Decimal:
        assert account_id == "account-1"
        assert currency == "EUR"
        return self.amount


def _lifecycle(path: Path, cash: Decimal = Decimal("1000")) -> OrderLifecycle:
    return OrderLifecycle(
        path,
        FixedCashSource(cash),
        settlement=SettlementConfig(settlement_lags={"XETRA": {"etf": 2}}),
    )


def _reserve(
    lifecycle: OrderLifecycle,
    *,
    order_id: str = "order-1",
    idempotency_key: str = "request-1",
    quantity: Decimal = Decimal("10"),
    price: Decimal = Decimal("10"),
    fee: Decimal = Decimal("0"),
) -> object:
    return lifecycle.reserve_order(
        account_id="account-1",
        order_id=order_id,
        idempotency_key=idempotency_key,
        currency="EUR",
        side="buy",
        quantity=quantity,
        limit_price=price,
        fee_estimate=fee,
        venue="XETRA",
        instrument_type="etf",
        occurred_at=datetime(2026, 9, 30, 10, tzinfo=timezone.utc),
    )


def test_two_concurrent_reservations_cannot_double_spend_cash(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.sqlite3"
    first = _lifecycle(db_path, Decimal("100"))
    second = _lifecycle(db_path, Decimal("100"))
    barrier = Barrier(2)

    def reserve(lifecycle: OrderLifecycle, suffix: str) -> str:
        barrier.wait()
        try:
            _reserve(
                lifecycle,
                order_id=f"order-{suffix}",
                idempotency_key=f"request-{suffix}",
                quantity=Decimal("8"),
            )
            return "reserved"
        except (InsufficientBuyingPower, OrderLifecycleError):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda item: reserve(*item), [(first, "a"), (second, "b")]))

    assert sorted(outcomes) == ["rejected", "reserved"]
    assert first.available_buying_power(account_id="account-1", currency="EUR") == Decimal("20")


def test_duplicate_idempotency_key_creates_one_order_intent(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path / "orders.sqlite3")

    first = _reserve(lifecycle)
    duplicate = _reserve(lifecycle)

    assert first.order_id == duplicate.order_id
    assert lifecycle.event_count() == 2
    with sqlite3.connect(lifecycle.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 1


def test_partial_fill_keeps_exact_decimal_residual_reservation(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path / "orders.sqlite3")
    _reserve(lifecycle, fee=Decimal("0.25"))
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="paper-ack")

    _, reservation = lifecycle.record_fill(
        "order-1",
        fill_id="fill-1",
        quantity=Decimal("4"),
        price=Decimal("9.95"),
        fee=Decimal("0.10"),
        occurred_at=datetime(2026, 9, 30, 10, tzinfo=timezone.utc),
    )

    assert reservation.remaining_quantity == Decimal("6")
    assert reservation.reserved_amount == Decimal("60.25")
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR") == Decimal("899.85")


def test_fill_cannot_consume_cash_reserved_for_another_order(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path / "orders.sqlite3", Decimal("100"))
    _reserve(lifecycle, order_id="order-a", idempotency_key="request-a", quantity=Decimal("8"))
    _reserve(lifecycle, order_id="order-b", idempotency_key="request-b", quantity=Decimal("2"))
    lifecycle.transition("order-a", OrderState.ACKNOWLEDGED, event_key="ack-a")

    with pytest.raises(OrderLifecycleError, match="reserved for another"):
        lifecycle.record_fill(
            "order-a",
            fill_id="fill-a",
            quantity=Decimal("8"),
            price=Decimal("11"),
            occurred_at=datetime(2026, 9, 30, 10, tzinfo=timezone.utc),
        )

    assert lifecycle.get_state("order-a") is OrderState.ACKNOWLEDGED
    assert lifecycle.get_reservation("order-a").reserved_amount == Decimal("80")


def test_unknown_state_requires_reconciliation_and_blocks_transitions(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path / "orders.sqlite3")
    _reserve(lifecycle)
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="paper-ack")

    event = lifecycle.transition(
        "order-1",
        OrderState.UNKNOWN,
        event_key="callback-unknown",
        payload={"reason": "connection state unavailable"},
    )

    assert event.state is OrderState.RECONCILIATION_REQUIRED
    assert lifecycle.get_state("order-1") is OrderState.RECONCILIATION_REQUIRED
    with pytest.raises(OrderTransitionError):
        lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="retry")


def test_illegal_transition_is_rejected_and_paper_shares_the_transition_table(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path / "orders.sqlite3")
    _reserve(lifecycle)

    with pytest.raises(OrderTransitionError):
        lifecycle.transition("order-1", OrderState.FILLED, event_key="illegal-fill")

    assert PaperLedger.ORDER_TRANSITIONS is ALLOWED_TRANSITIONS


def test_settlement_uses_configured_business_day_lag_and_unknown_fails_closed() -> None:
    settlement = SettlementConfig(settlement_lags={"XETRA": {"etf": 2}, "US": {"stock": 1}})

    assert settlement.settlement_date("XETRA", "etf", date(2026, 10, 2)) == date(2026, 10, 6)
    assert settlement.settlement_date("unknown", "etf", date(2026, 10, 2)) is None
    assert load_settlement_config(Path("configs")).settlement_date("XETRA", "etf", date(2026, 10, 2)) == date(2026, 10, 6)


def test_ledger_cash_source_returns_settled_decimal_balance() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE ledger_accounts(account_id TEXT, authority TEXT, account_role TEXT);
        CREATE TABLE ledger_entries(
            entry_id TEXT, authority TEXT, effective_at TEXT, settlement_at TEXT, status TEXT
        );
        CREATE TABLE ledger_postings(
            entry_id TEXT, authority TEXT, account_id TEXT, currency TEXT,
            debit_amount TEXT, credit_amount TEXT
        );
        INSERT INTO ledger_accounts VALUES ('cash-eur', 'broker', 'cash');
        INSERT INTO ledger_entries VALUES (
            'settled', 'broker', '2026-09-29T10:00:00Z', '2026-09-29T10:00:00Z', 'posted'
        );
        INSERT INTO ledger_entries VALUES (
            'unsettled', 'broker', '2026-09-30T10:00:00Z', '2026-10-01T10:00:00Z', 'posted'
        );
        INSERT INTO ledger_postings VALUES ('settled', 'broker', 'cash-eur', 'EUR', '100.25', '0');
        INSERT INTO ledger_postings VALUES ('unsettled', 'broker', 'cash-eur', 'EUR', '50', '0');
        """
    )

    balance = Ledger(connection).cash_balance(
        account_id="cash-eur",
        currency="EUR",
        as_of=datetime(2026, 9, 30, 10, tzinfo=timezone.utc),
    )

    assert balance == Decimal("100.25")
    connection.close()
