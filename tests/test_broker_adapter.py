from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import inspect
import json

import pytest

from etf_cockpit.portfolio.ledger_projection import CashBalance, LedgerReplay, PositionBalance
from etf_cockpit.trading.broker_contracts import (
    BrokerAccountStatus,
    BrokerCash,
    BrokerOpenOrder,
    BrokerPosition,
    BrokerRead,
    BrokerReadOnlyAdapter,
    BrokerSnapshot,
    LocalOpenOrder,
)
from etf_cockpit.trading.broker_reconciliation import (
    BrokerBreakKind,
    BrokerReconciliationBreak,
    BrokerSection,
    BrokerSectionStatus,
    audit_document,
    export_payload,
    reconcile_broker_state,
)
from etf_cockpit.trading.fixture_broker import FixtureBrokerAdapter
from etf_cockpit.trading.order_lifecycle import OrderState


AS_OF = "2026-09-30T12:00:00Z"


def _local_replay(
    *,
    positions: tuple[PositionBalance, ...] = (),
    cash: tuple[CashBalance, ...] = (),
    as_of: str = AS_OF,
) -> LedgerReplay:
    return LedgerReplay(
        authority="paper",
        as_of=as_of,
        known_at=as_of,
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


def _adapter(
    *,
    positions: tuple[BrokerPosition, ...] | None = (),
    cash: tuple[BrokerCash, ...] | None = (),
    orders: tuple[BrokerOpenOrder, ...] | None = (),
    connected: bool = True,
    observed_at: str = AS_OF,
) -> FixtureBrokerAdapter:
    return FixtureBrokerAdapter(
        BrokerSnapshot(
            observed_at=observed_at,
            positions=positions,
            cash=cash,
            orders=orders,
            account_status=BrokerAccountStatus(connected=connected),
        )
    )


def test_position_mismatch_emits_classified_break() -> None:
    local = _local_replay(
        positions=(PositionBalance("paper", "TEST-FUND", None, Decimal("5"), False),)
    )

    result = reconcile_broker_state(
        _adapter(positions=(BrokerPosition("TEST-FUND", Decimal("4")),)),
        local,
        (),
        as_of=AS_OF,
    )

    assert result.positions_status is BrokerSectionStatus.BREAK
    assert [item.kind for item in result.breaks] == [BrokerBreakKind.POSITION_MISMATCH]
    assert result.breaks[0].local_value == "5"
    assert result.breaks[0].broker_value == "4"


def test_cash_and_open_order_mismatches_have_distinct_break_types() -> None:
    local = _local_replay(cash=(CashBalance("paper", "EUR", Decimal("100"), Decimal("100"), Decimal(0), Decimal(0)),))
    local_order = LocalOpenOrder(
        "local-order-1", "TEST-FUND", "buy", Decimal("2"), Decimal("1"), OrderState.ACKNOWLEDGED.value
    )
    broker_order = BrokerOpenOrder(
        "local-order-1", "TEST-FUND", "buy", Decimal("2"), Decimal("0.5"), OrderState.ACKNOWLEDGED.value
    )

    result = reconcile_broker_state(
        _adapter(cash=(BrokerCash("EUR", Decimal("99")),), orders=(broker_order,)),
        local,
        (local_order,),
        as_of=AS_OF,
    )

    assert {item.kind for item in result.breaks} == {
        BrokerBreakKind.CASH_MISMATCH,
        BrokerBreakKind.OPEN_ORDER_MISMATCH,
    }
    assert result.cash_status is BrokerSectionStatus.BREAK
    assert result.orders_status is BrokerSectionStatus.BREAK


def test_disconnect_keeps_paper_usable_and_blocks_order_authority() -> None:
    result = reconcile_broker_state(_adapter(connected=False), _local_replay(), (), as_of=AS_OF)

    assert result.paper_available is True
    assert result.research_available is True
    assert result.order_authority_allowed is False
    assert result.execution_allowed is False
    assert result.connected is False
    assert any(item.kind is BrokerBreakKind.DISCONNECTED for item in result.breaks)
    assert result.positions_status is BrokerSectionStatus.DISCONNECTED
    assert result.cash_status is BrokerSectionStatus.DISCONNECTED
    assert result.orders_status is BrokerSectionStatus.DISCONNECTED


def test_credentials_are_redacted_from_logs_audit_and_export_payloads(caplog: pytest.LogCaptureFixture) -> None:
    class FailingAdapter:
        def read_positions(self) -> BrokerRead[tuple[BrokerPosition, ...]]:
            raise RuntimeError("password=credential-secret")

        def read_cash(self) -> BrokerRead[tuple[BrokerCash, ...]]:
            raise RuntimeError("password=credential-secret")

        def read_orders(self) -> BrokerRead[tuple[BrokerOpenOrder, ...]]:
            raise RuntimeError("password=credential-secret")

        def read_account_status(self) -> BrokerRead[BrokerAccountStatus]:
            raise RuntimeError("password=credential-secret")

    result = reconcile_broker_state(FailingAdapter(), _local_replay(), (), as_of=AS_OF)
    assert "credential-secret" not in caplog.text

    with_secret = replace(
        result,
        breaks=(BrokerReconciliationBreak(
            BrokerBreakKind.ACCOUNT_UNKNOWN,
            BrokerSection.ACCOUNT,
            None,
            None,
            None,
            "password=credential-secret",
        ),),
    )
    audit = json.dumps(audit_document(with_secret), sort_keys=True)
    exported = json.dumps(export_payload(with_secret), sort_keys=True)
    assert "credential-secret" not in audit
    assert "credential-secret" not in exported


def test_adapter_protocol_has_only_read_methods() -> None:
    methods = {
        name
        for name, member in inspect.getmembers(BrokerReadOnlyAdapter)
        if inspect.isfunction(member) and not name.startswith("__")
    }

    assert methods == {"read_positions", "read_cash", "read_orders", "read_account_status"}
    assert not any(name.startswith(("submit", "cancel", "write")) for name in methods)


def test_missing_or_stale_broker_data_is_unknown_not_zero() -> None:
    missing = reconcile_broker_state(
        _adapter(positions=None),
        _local_replay(positions=(PositionBalance("paper", "TEST-FUND", None, Decimal("5"), False),)),
        (),
        as_of=AS_OF,
    )
    stale = reconcile_broker_state(
        _adapter(observed_at="2026-09-30T11:59:59Z"),
        _local_replay(),
        (),
        as_of=AS_OF,
    )

    assert missing.positions_status is BrokerSectionStatus.UNKNOWN
    assert any(item.kind is BrokerBreakKind.POSITIONS_UNKNOWN for item in missing.breaks)
    assert stale.positions_status is BrokerSectionStatus.UNKNOWN
    assert any(item.kind is BrokerBreakKind.POSITIONS_UNKNOWN for item in stale.breaks)
