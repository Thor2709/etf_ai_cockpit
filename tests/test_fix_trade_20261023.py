from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import RLock

import pytest

from etf_cockpit.trading.order_lifecycle import OrderLifecycle, OrderLifecycleError, OrderState
from etf_cockpit.trading.pre_trade_controls import (
    PreTradeControlError,
    PreTradeControls,
    _current_exposure,
    _daily_turnover,
)
from etf_cockpit.trading.tca import TCACalculator


class _CashSource:
    cash_includes_unsettled_trades = False

    def __init__(self, balance: Decimal) -> None:
        self.balance = balance

    def cash_balance(self, *, account_id: str, currency: str, as_of: datetime) -> Decimal:
        assert account_id == "account-1"
        assert currency == "EUR"
        return self.balance


class _PaperLedger:
    def __init__(self) -> None:
        self._lock = RLock()
        self.orders: dict[str, dict[str, object]] = {
            "paper-order": {"order_id": "paper-order", "status": "accepted"}
        }
        self.cancelled: list[str] = []

    def _file_lock(self):
        return nullcontext()

    def _read_events(self) -> tuple[object, ...]:
        return ()

    def _replay(self, events: object) -> dict[str, object]:
        return {"orders": self.orders}

    def _cancel_order_locked(self, order_id: str, *, reason: str, occurred_at: datetime) -> None:
        self.cancelled.append(order_id)
        self.orders[order_id]["status"] = "cancelled"


def test_kill_switch_activates_and_cancels_when_limits_are_invalid(tmp_path: Path) -> None:
    limits_path = tmp_path / "invalid-limits.yaml"
    limits_path.write_text("schema_version: unsupported\n", encoding="utf-8")
    controls = PreTradeControls(tmp_path, limits_path=limits_path)
    ledger = _PaperLedger()

    activated = controls.activate_kill_switch(
        who="operator-a",
        reason="Operational halt",
        paper_ledger=ledger,
        occurred_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )

    assert activated["event_type"] == "kill_switch_activated"
    assert activated["details"]["cancel_open_paper_orders"] is True
    assert activated["details"]["limits_config_error"]
    assert controls.kill_switch_active() is True
    assert ledger.cancelled == ["paper-order"]
    assert ledger.orders["paper-order"]["status"] == "cancelled"


def test_partial_fill_reduces_remaining_fee_buffer(tmp_path: Path) -> None:
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3", _CashSource(Decimal("1005")))
    at = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)
    lifecycle.reserve_order(
        account_id="account-1",
        order_id="order-fee-buffer",
        idempotency_key="request-fee-buffer",
        currency="EUR",
        side="buy",
        quantity=Decimal("100"),
        limit_price=Decimal("10"),
        fee_estimate=Decimal("5"),
        venue="XETRA",
        instrument_type="etf",
        occurred_at=at,
    )
    lifecycle.transition("order-fee-buffer", OrderState.ACKNOWLEDGED, event_key="ack-fee-buffer", occurred_at=at)

    _, reservation = lifecycle.record_fill(
        "order-fee-buffer",
        fill_id="fill-fee-buffer",
        quantity=Decimal("50"),
        price=Decimal("10"),
        fee=Decimal("2.5"),
        occurred_at=at,
    )

    assert reservation.remaining_quantity == Decimal("50")
    assert reservation.reserved_amount == Decimal("502.5")
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=at) == Decimal("0")


def test_missing_position_order_or_event_fx_fails_closed() -> None:
    at = datetime(2026, 9, 30, tzinfo=timezone.utc)
    accepted_at = at.isoformat()
    missing_fx_cases = (
        lambda: _current_exposure(
            "VWCE", {"VWCE": {"quantity": 1, "mark_price": 10}}, {}
        ),
        lambda: _current_exposure(
            "VWCE",
            {},
            {
                "order-1": {
                    "instrument_id": "VWCE",
                    "status": "accepted",
                    "side": "buy",
                    "remaining_quantity": 1,
                    "monetary_terms": {"execution_price": 10},
                }
            },
        ),
        lambda: _daily_turnover(
            at,
            [{
                "event_type": "order_accepted",
                "occurred_at": accepted_at,
                "payload": {"monetary_terms": {"quantity_delta": 1, "execution_price": 10}},
            }],
            None,
            "paper",
        ),
        lambda: _daily_turnover(
            at,
            [{
                "event_type": "order_accepted",
                "occurred_at": accepted_at,
                "payload": {"quantity": 1, "execution_price": 10},
            }],
            None,
            "paper",
        ),
    )

    for calculate in missing_fx_cases:
        with pytest.raises(PreTradeControlError):
            calculate()


def test_risk_reducing_sell_is_not_rejected_by_position_exposure_limit(tmp_path: Path) -> None:
    limits_path = tmp_path / "limits.yaml"
    limits_path.write_text(
        """schema_version: pre_trade_limits.v1
allowed_instruments: [VWCE]
max_order_value: 5000
max_position_exposure: 10000
max_daily_turnover: 5000
cancel_open_paper_orders_on_kill_switch: true
max_override_ttl_seconds: 300
""",
        encoding="utf-8",
    )
    controls = PreTradeControls(tmp_path, limits_path=limits_path)

    decision = controls.evaluate_order(
        {"proposal_id": "sell-proposal", "instrument_id": "VWCE"},
        execution_price=10,
        quantity_delta=-300,
        fx_rate=1,
        positions={"VWCE": {"quantity": 1500, "mark_price": 10, "mark_fx_rate": 1}},
        open_orders={},
        paper_events=[],
        path="paper",
        occurred_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )

    assert decision.allowed is True


def test_partial_reconciliation_without_new_fill_restores_partial_state(tmp_path: Path) -> None:
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3", _CashSource(Decimal("1000")))
    at = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)
    lifecycle.reserve_order(
        account_id="account-1",
        order_id="order-reconcile-partial",
        idempotency_key="request-reconcile-partial",
        currency="EUR",
        side="buy",
        quantity=Decimal("10"),
        limit_price=Decimal("10"),
        venue="XETRA",
        instrument_type="etf",
        occurred_at=at,
    )
    lifecycle.transition("order-reconcile-partial", OrderState.ACKNOWLEDGED, event_key="ack-partial", occurred_at=at)
    lifecycle.record_fill(
        "order-reconcile-partial",
        fill_id="fill-before-reconcile",
        quantity=Decimal("4"),
        price=Decimal("10"),
        occurred_at=at,
    )
    lifecycle.transition("order-reconcile-partial", OrderState.UNKNOWN, event_key="unknown-partial", occurred_at=at)
    lifecycle.transition(
        "order-reconcile-partial", OrderState.RECONCILIATION_REQUIRED, event_key="needs-reconcile-partial", occurred_at=at
    )

    event = lifecycle.reconcile(
        "order-reconcile-partial",
        OrderState.PARTIALLY_FILLED,
        event_key="restore-partial",
        reason="Broker confirms the existing partial fill.",
        remaining_quantity=Decimal("6"),
        occurred_at=at,
    )
    retried = lifecycle.reconcile(
        "order-reconcile-partial",
        OrderState.PARTIALLY_FILLED,
        event_key="restore-partial",
        reason="Broker confirms the existing partial fill.",
        remaining_quantity=Decimal("6"),
        occurred_at=at,
    )

    assert event.state is OrderState.PARTIALLY_FILLED
    assert retried.event_id == event.event_id
    assert event.payload["no_new_fill"] is True
    assert lifecycle.get_state("order-reconcile-partial") is OrderState.PARTIALLY_FILLED
    assert len(lifecycle.fill_events()) == 1


def test_reconciliation_cannot_regress_committed_partial_fill_to_acknowledged(tmp_path: Path) -> None:
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3", _CashSource(Decimal("1000")))
    at = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)
    lifecycle.reserve_order(
        account_id="account-1",
        order_id="order-no-ack-regression",
        idempotency_key="request-no-ack-regression",
        currency="EUR",
        side="buy",
        quantity=Decimal("10"),
        limit_price=Decimal("10"),
        venue="XETRA",
        instrument_type="etf",
        occurred_at=at,
    )
    lifecycle.transition("order-no-ack-regression", OrderState.ACKNOWLEDGED, event_key="ack-no-regression", occurred_at=at)
    lifecycle.record_fill(
        "order-no-ack-regression",
        fill_id="fill-before-ack-reconcile",
        quantity=Decimal("4"),
        price=Decimal("10"),
        occurred_at=at,
    )
    lifecycle.transition("order-no-ack-regression", OrderState.UNKNOWN, event_key="unknown-no-regression", occurred_at=at)
    lifecycle.transition(
        "order-no-ack-regression", OrderState.RECONCILIATION_REQUIRED, event_key="needs-reconcile-no-regression", occurred_at=at
    )

    with pytest.raises(OrderLifecycleError, match="committed fill"):
        lifecycle.reconcile(
            "order-no-ack-regression",
            OrderState.ACKNOWLEDGED,
            event_key="reject-ack-regression",
            reason="The order already has a committed partial fill.",
            occurred_at=at,
        )


def test_eur_cost_forecast_is_not_subtracted_from_usd_realised_cost() -> None:
    fill = {
        "fill_id": "fill-usd",
        "order_id": "order-usd",
        "side": "buy",
        "quantity": 1,
        "price": 100,
        "fee": 0,
        "currency": "USD",
    }
    order = {"order_id": "order-usd", "side": "buy", "quantity": 1, "filled_quantity": 1, "status": "filled"}

    for forecast in (
        {"currency": "USD", "total_cost_eur": 10},
        {"currency": "USD", "total_cost_bps": 10, "order_value_eur": 1000},
    ):
        record = TCACalculator().calculate(fill, order, cost_forecast=forecast)
        assert record.estimated_total_cost is None


def test_rmn_no_fill_reconciliation_requires_an_existing_committed_partial_fill(tmp_path: Path) -> None:
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3", _CashSource(Decimal("1000")))
    at = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)
    lifecycle.reserve_order(
        account_id="account-1", order_id="order-unfilled", idempotency_key="request-unfilled", currency="EUR",
        side="buy", quantity=Decimal("10"), limit_price=Decimal("10"), venue="XETRA", instrument_type="etf", occurred_at=at,
    )
    lifecycle.transition("order-unfilled", OrderState.ACKNOWLEDGED, event_key="ack-unfilled", occurred_at=at)
    lifecycle.transition("order-unfilled", OrderState.UNKNOWN, event_key="unknown-unfilled", occurred_at=at)
    lifecycle.transition("order-unfilled", OrderState.RECONCILIATION_REQUIRED, event_key="needs-unfilled", occurred_at=at)

    with pytest.raises(OrderLifecycleError, match="committed partial fill"):
        lifecycle.reconcile(
            "order-unfilled", OrderState.PARTIALLY_FILLED, event_key="invent-partial",
            reason="No fill evidence exists.", remaining_quantity=Decimal("10"), occurred_at=at,
        )
    assert lifecycle.get_state("order-unfilled") is OrderState.RECONCILIATION_REQUIRED
    assert len(lifecycle.fill_events()) == 0
