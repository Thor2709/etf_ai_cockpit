from __future__ import annotations

from datetime import datetime

import pytest

from etf_cockpit.backtest.event_engine import (
    CancelEvent,
    EventDrivenBacktest,
    EventReplayError,
    ExpiryEvent,
    FillEvent,
    MarketEvent,
    OrderRequest,
    ProposalEvent,
    SessionCalendar,
    SignalEvent,
    TargetEvent,
    UnsupportedExecutionDataError,
    proposal_to_order,
)


def _market(minutes: int, *, available_quantity: float | None = None, listed: bool = True) -> MarketEvent:
    return MarketEvent(
        datetime(2026, 7, 17, 10, minutes),
        "ETF-A",
        open_price=100.0,
        high_price=102.0,
        low_price=98.0,
        close_price=101.0,
        available_quantity=available_quantity,
        listed=listed,
    )


def _order(*, timestamp: datetime | None = None, quantity: float = 10.0, order_type: str = "market", limit_price: float | None = None, expires_at: datetime | None = None) -> OrderRequest:
    return OrderRequest(
        timestamp=timestamp or datetime(2026, 7, 17, 10, 0),
        order_id="order-1",
        instrument_id="ETF-A",
        side="buy",
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        expires_at=expires_at,
    )


def test_replay_is_order_level_and_hash_is_independent_of_input_order() -> None:
    events = [
        _market(1),
        _order(),
        SignalEvent(datetime(2026, 7, 17, 9, 59), "signal-1", "ETF-A", "buy"),
        TargetEvent(datetime(2026, 7, 17, 9, 59), "target-1", "ETF-A", 10.0),
        ProposalEvent(datetime(2026, 7, 17, 9, 59), "proposal-1", "ETF-A", "buy", 10.0),
        _market(0),
    ]

    first = EventDrivenBacktest().replay(events)
    second = EventDrivenBacktest().replay(list(reversed(events)))

    assert first.ledger_hash == second.ledger_hash
    assert len(first.fills) == 1
    assert first.fills[0].timestamp == datetime(2026, 7, 17, 10, 1)
    assert first.fills[0].quantity == 10.0
    assert first.execution_allowed is False
    assert first.orders[0].status == "filled"


def test_partial_fills_then_cancel_preserve_remaining_quantity() -> None:
    result = EventDrivenBacktest().replay(
        [_order(quantity=10.0), _market(1, available_quantity=4.0), _market(2, available_quantity=3.0), CancelEvent(datetime(2026, 7, 17, 10, 3), "order-1", "user_cancel")]
    )

    fills = [event for event in result.events if isinstance(event, FillEvent)]
    assert [fill.quantity for fill in fills] == [4.0, 3.0]
    assert result.orders[0].status == "cancelled"
    assert result.orders[0].remaining_quantity == 3.0
    assert result.events[-1].kind == "cancel"


def test_limit_order_and_expiry_do_not_fill_after_expiry() -> None:
    result = EventDrivenBacktest().replay(
        [
            _order(order_type="limit", limit_price=97.0, expires_at=datetime(2026, 7, 17, 10, 2)),
            _market(1),
            _market(2),
            ExpiryEvent(datetime(2026, 7, 17, 10, 2), "order-1"),
            _market(3),
        ]
    )

    assert result.fills == ()
    assert result.orders[0].status == "expired"


def test_invalid_session_and_unsupported_listing_fail_closed() -> None:
    with pytest.raises(EventReplayError, match="outside a valid market session"):
        EventDrivenBacktest().replay([_order(timestamp=datetime(2026, 7, 18, 10, 0))])
    with pytest.raises(UnsupportedExecutionDataError, match="not listed"):
        EventDrivenBacktest().replay([_market(0, listed=False)])


def test_proposal_conversion_preserves_shared_order_contract() -> None:
    proposal = ProposalEvent(datetime(2026, 7, 17, 10, 0), "proposal-1", "ETF-A", "sell", 2.0, "limit", 103.0)
    order = proposal_to_order(proposal, expires_at=datetime(2026, 7, 17, 11, 0))

    assert order.source_id == "proposal-1"
    assert order.order_id == "order:proposal-1"
    assert order.order_type == "limit"
    assert order.limit_price == 103.0


def test_custom_calendar_rejects_holidays() -> None:
    calendar = SessionCalendar(holidays=frozenset({datetime(2026, 7, 17).date()}))
    with pytest.raises(EventReplayError, match="outside a valid market session"):
        EventDrivenBacktest(calendar=calendar).replay([_market(0)])
