"""Bughunt D (#983): broker reconciliation must fail closed on uncertain or economically different local state."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from etf_cockpit.portfolio.ledger_projection import CashBalance, LedgerReplay, PositionBalance
from etf_cockpit.trading.broker_contracts import (
    BrokerAccountStatus,
    BrokerCash,
    BrokerOpenOrder,
    BrokerPosition,
    BrokerSnapshot,
    LocalOpenOrder,
)
from etf_cockpit.trading.broker_reconciliation import (
    BrokerBreakKind,
    BrokerSectionStatus,
    reconcile_broker_state,
)
from etf_cockpit.trading.fixture_broker import FixtureBrokerAdapter
from etf_cockpit.trading.order_lifecycle import OrderState

AS_OF = "2026-09-30T12:00:00Z"
ACK = OrderState.ACKNOWLEDGED.value


def _replay(*, positions=(), cash=(), **overrides) -> LedgerReplay:
    base = LedgerReplay(
        authority="paper",
        as_of=AS_OF,
        known_at=AS_OF,
        positions=positions,
        cash=cash,
        trial_balance=(),
        unpriced_instruments=(),
        missing_lot_identity=(),
        missing_position_instrument_lines=(),
        unknown_settlement_lines=(),
        timing_uncertainty_entry_ids=(),
        fx_conversions=(),
        trial_balance_totals=(),
        trial_balance_balanced=True,
    )
    return replace(base, **overrides)


def _adapter(*, positions=(), cash=(), orders=()) -> FixtureBrokerAdapter:
    return FixtureBrokerAdapter(
        BrokerSnapshot(
            observed_at=AS_OF,
            positions=positions,
            cash=cash,
            orders=orders,
            account_status=BrokerAccountStatus(connected=True),
        )
    )


def _cash(account: str, amount: str) -> CashBalance:
    value = Decimal(amount)
    return CashBalance(account, "EUR", value, value, Decimal(0), Decimal(0))


def _order(cls, status=ACK, qty="2", remaining="1", **terms):
    return cls("o-1", "TEST-FUND", "buy", Decimal(qty), Decimal(remaining), status, **terms)


def _run(adapter, replay=None, local_orders=()):
    return reconcile_broker_state(adapter, replay or _replay(), tuple(local_orders), as_of=AS_OF)


def test_timing_uncertain_cash_is_not_reconciled() -> None:  # D016-N001
    replay = _replay(cash=(_cash("A", "100"),), timing_uncertainty_entry_ids=("e-1",))
    result = _run(_adapter(cash=(BrokerCash("EUR", Decimal("100")),)), replay)
    assert result.cash_status is BrokerSectionStatus.UNKNOWN
    assert any(item.kind is BrokerBreakKind.CASH_UNKNOWN for item in result.breaks)


@pytest.mark.parametrize("known_at", ["2026-09-30T13:00:00Z", "2026-09-30T11:00:00Z"])
def test_known_at_mismatch_is_not_reconciled(known_at: str) -> None:  # D016-N002
    replay = _replay(cash=(_cash("A", "100"),), known_at=known_at)
    result = _run(
        _adapter(cash=(BrokerCash("EUR", Decimal("100")),), positions=()), replay
    )
    assert result.cash_status is BrokerSectionStatus.UNKNOWN
    assert result.positions_status is BrokerSectionStatus.UNKNOWN


def test_unbalanced_trial_balance_blocks_reconciliation() -> None:  # D016-N003
    replay = _replay(
        cash=(_cash("A", "100"),),
        positions=(PositionBalance("A", "TEST-FUND", None, Decimal("5"), False),),
        trial_balance_balanced=False,
    )
    result = _run(
        _adapter(
            cash=(BrokerCash("EUR", Decimal("100")),),
            positions=(BrokerPosition("TEST-FUND", Decimal("5")),),
        ),
        replay,
    )
    assert result.cash_status is BrokerSectionStatus.UNKNOWN
    assert result.positions_status is BrokerSectionStatus.UNKNOWN


@pytest.mark.parametrize("state", [OrderState.UNKNOWN, OrderState.RECONCILIATION_REQUIRED])
def test_matching_uncertain_orders_are_not_reconciled(state: OrderState) -> None:  # D116-N001
    result = _run(
        _adapter(orders=(_order(BrokerOpenOrder, state.value),)),
        local_orders=(_order(LocalOpenOrder, state.value),),
    )
    assert result.orders_status is BrokerSectionStatus.UNKNOWN
    assert any(item.kind is BrokerBreakKind.ORDERS_UNKNOWN for item in result.breaks)


@pytest.mark.parametrize(
    ("qty", "remaining"), [("-1", "0"), ("2", "-1"), ("2", "3")]
)
def test_impossible_order_quantities_are_rejected(qty: str, remaining: str) -> None:  # D116-N002
    broker_only = _run(_adapter(orders=(_order(BrokerOpenOrder, qty=qty, remaining=remaining),)))
    both = _run(
        _adapter(orders=(_order(BrokerOpenOrder, qty=qty, remaining=remaining),)),
        local_orders=(_order(LocalOpenOrder, qty=qty, remaining=remaining),),
    )
    assert broker_only.orders_status is BrokerSectionStatus.UNKNOWN
    assert both.orders_status is BrokerSectionStatus.UNKNOWN


def test_account_scoped_broker_cash_does_not_match_aggregate_local() -> None:  # D116-N003
    replay = _replay(cash=(_cash("A", "100"), _cash("B", "200")))
    result = _run(_adapter(cash=(BrokerCash("EUR", Decimal("300"), account_id="A"),)), replay)
    assert result.cash_status is BrokerSectionStatus.BREAK
    matched = _run(
        _adapter(
            cash=(
                BrokerCash("EUR", Decimal("100"), account_id="A"),
                BrokerCash("EUR", Decimal("200"), account_id="B"),
            )
        ),
        replay,
    )
    assert matched.cash_status is BrokerSectionStatus.RECONCILED


def test_account_scoped_broker_positions_do_not_match_aggregate_local() -> None:  # D116-N003
    replay = _replay(
        positions=(
            PositionBalance("A", "TEST-FUND", None, Decimal("1"), False),
            PositionBalance("B", "TEST-FUND", None, Decimal("2"), False),
        )
    )
    result = _run(_adapter(positions=(BrokerPosition("TEST-FUND", Decimal("3"), account_id="A"),)), replay)
    assert result.positions_status is BrokerSectionStatus.BREAK


def test_unscoped_broker_snapshot_against_multi_account_ledger_is_unknown() -> None:  # D116-N003
    replay = _replay(cash=(_cash("A", "100"), _cash("B", "200")))
    result = _run(_adapter(cash=(BrokerCash("EUR", Decimal("300")),)), replay)
    assert result.cash_status is BrokerSectionStatus.UNKNOWN


@pytest.mark.parametrize(
    "broker_terms",
    [
        {"limit_price": Decimal("11")},
        {"account_id": "B"},
        {"currency": "USD"},
    ],
)
def test_order_terms_must_match(broker_terms: dict) -> None:  # D116-N004
    local_terms = {"limit_price": Decimal("10"), "account_id": "A", "currency": "EUR"}
    broker = {**local_terms, **broker_terms}
    result = _run(
        _adapter(orders=(_order(BrokerOpenOrder, **broker),)),
        local_orders=(_order(LocalOpenOrder, **local_terms),),
    )
    assert result.orders_status is BrokerSectionStatus.BREAK
    matching = _run(
        _adapter(orders=(_order(BrokerOpenOrder, **local_terms),)),
        local_orders=(_order(LocalOpenOrder, **local_terms),),
    )
    assert matching.orders_status is BrokerSectionStatus.RECONCILED


def test_omitted_limit_price_on_one_side_is_a_break() -> None:  # D116-N004
    result = _run(
        _adapter(orders=(_order(BrokerOpenOrder),)),
        local_orders=(_order(LocalOpenOrder, limit_price=Decimal("10")),),
    )
    assert result.orders_status is BrokerSectionStatus.BREAK


def test_non_iso_currency_with_symbol_is_rejected() -> None:  # D.C3.S16.N002
    result = _run(_adapter(cash=(BrokerCash("U$D", Decimal("0")),)))
    assert result.cash_status is BrokerSectionStatus.UNKNOWN


def test_read_object_without_value_attribute_is_unknown() -> None:  # D.C3.S16.N003
    class _NoValue:
        observed_at = AS_OF

    class _Adapter(FixtureBrokerAdapter):
        def read_positions(self):
            return _NoValue()

    adapter = _Adapter(
        BrokerSnapshot(AS_OF, (), (), (), BrokerAccountStatus(connected=True))
    )
    result = _run(adapter)
    assert result.positions_status is BrokerSectionStatus.UNKNOWN


def test_duplicate_broker_position_rows_stay_unknown_not_aggregated() -> None:  # D.C3.S16.N001 guard
    result = _run(
        _adapter(
            positions=(
                BrokerPosition("TEST-FUND", Decimal("1")),
                BrokerPosition("TEST-FUND", Decimal("1")),
            )
        ),
        _replay(positions=(PositionBalance("A", "TEST-FUND", None, Decimal("2"), False),)),
    )
    assert result.positions_status is BrokerSectionStatus.UNKNOWN
