"""Read-only comparison of broker evidence with the canonical local projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
import logging
from typing import Any, Callable, Mapping, Sequence

from etf_cockpit.portfolio.ledger_projection import LedgerReplay
from etf_cockpit.security.policy import redact_secrets
from etf_cockpit.trading.broker_contracts import (
    BrokerAccountStatus,
    BrokerCash,
    BrokerOpenOrder,
    BrokerPosition,
    BrokerRead,
    BrokerReadOnlyAdapter,
    LocalOpenOrder,
)
from etf_cockpit.trading.order_lifecycle import OrderState


_LOGGER = logging.getLogger(__name__)
_OPEN_ORDER_STATES = frozenset(
    {
        OrderState.SUBMITTING,
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.UNKNOWN,
        OrderState.RECONCILIATION_REQUIRED,
    }
)


class BrokerSection(StrEnum):
    ACCOUNT = "account"
    POSITIONS = "positions"
    CASH = "cash"
    ORDERS = "orders"


class BrokerSectionStatus(StrEnum):
    RECONCILED = "reconciled"
    BREAK = "break"
    UNKNOWN = "unknown"
    DISCONNECTED = "disconnected"


class BrokerBreakKind(StrEnum):
    DISCONNECTED = "disconnected"
    ACCOUNT_UNKNOWN = "account_unknown"
    POSITIONS_UNKNOWN = "positions_unknown"
    POSITION_MISMATCH = "position_mismatch"
    CASH_UNKNOWN = "cash_unknown"
    CASH_MISMATCH = "cash_mismatch"
    ORDERS_UNKNOWN = "orders_unknown"
    OPEN_ORDER_MISMATCH = "open_order_mismatch"


@dataclass(frozen=True)
class BrokerReconciliationBreak:
    kind: BrokerBreakKind
    section: BrokerSection
    key: str | None
    local_value: str | None
    broker_value: str | None
    detail: str


@dataclass(frozen=True)
class BrokerReconciliation:
    as_of: str
    account_status: BrokerSectionStatus
    positions_status: BrokerSectionStatus
    cash_status: BrokerSectionStatus
    orders_status: BrokerSectionStatus
    connected: bool | None
    breaks: tuple[BrokerReconciliationBreak, ...]
    research_available: bool = True
    paper_available: bool = True
    order_authority_allowed: bool = False
    execution_allowed: bool = False


def reconcile_broker_state(
    adapter: BrokerReadOnlyAdapter,
    local_replay: LedgerReplay,
    local_open_orders: Sequence[LocalOpenOrder],
    *,
    as_of: str,
) -> BrokerReconciliation:
    """Compare broker facts with canonical ledger and order lifecycle projections.

    Freshness uses exact instant equality with ``as_of``. No maximum-age formula
    is specified for this release, so any older (or future) observation is
    conservatively UNKNOWN instead of being accepted as current. Positions are
    summed by instrument across canonical ledger accounts and lots, and cash is
    summed by currency from canonical book balances. Missing keys mean zero only
    in a complete, current section. Values compare exactly as Decimals. Orders
    match by order ID, instrument, side, quantity, remaining quantity and status;
    local nonterminal broker-facing lifecycle states are supplied as a read
    projection. This function never edits broker evidence or grants authority.
    """

    requested_instant = _instant(as_of)
    canonical_as_of = _canonical_instant(requested_instant)
    breaks: list[BrokerReconciliationBreak] = []
    reads = {
        BrokerSection.ACCOUNT: _read(adapter.read_account_status),
        BrokerSection.POSITIONS: _read(adapter.read_positions),
        BrokerSection.CASH: _read(adapter.read_cash),
        BrokerSection.ORDERS: _read(adapter.read_orders),
    }

    account_read = _fresh_value(
        reads[BrokerSection.ACCOUNT], requested_instant, BrokerBreakKind.ACCOUNT_UNKNOWN,
        BrokerSection.ACCOUNT, breaks,
    )
    if account_read is None or not isinstance(account_read, BrokerAccountStatus):
        account_status = BrokerSectionStatus.UNKNOWN
        connected = None
        if account_read is not None:
            breaks.append(_unknown_break(
                BrokerBreakKind.ACCOUNT_UNKNOWN,
                BrokerSection.ACCOUNT,
                "broker account status is invalid",
            ))
    elif not account_read.connected:
        account_status = BrokerSectionStatus.DISCONNECTED
        connected = False
        breaks.append(
            BrokerReconciliationBreak(
                BrokerBreakKind.DISCONNECTED,
                BrokerSection.ACCOUNT,
                None,
                "connected",
                "disconnected",
                "broker account is disconnected",
            )
        )
    else:
        account_status = BrokerSectionStatus.RECONCILED
        connected = True

    if connected is not True:
        fallback = BrokerSectionStatus.DISCONNECTED if connected is False else BrokerSectionStatus.UNKNOWN
        section_statuses = {
            BrokerSection.POSITIONS: _unknown_section(
                BrokerSection.POSITIONS, BrokerBreakKind.POSITIONS_UNKNOWN, fallback, reads, requested_instant, breaks
            ),
            BrokerSection.CASH: _unknown_section(
                BrokerSection.CASH, BrokerBreakKind.CASH_UNKNOWN, fallback, reads, requested_instant, breaks
            ),
            BrokerSection.ORDERS: _unknown_section(
                BrokerSection.ORDERS, BrokerBreakKind.ORDERS_UNKNOWN, fallback, reads, requested_instant, breaks
            ),
        }
    else:
        section_statuses = {
            BrokerSection.POSITIONS: _reconcile_positions(
                reads[BrokerSection.POSITIONS], requested_instant, local_replay, breaks
            ),
            BrokerSection.CASH: _reconcile_cash(
                reads[BrokerSection.CASH], requested_instant, local_replay, breaks
            ),
            BrokerSection.ORDERS: _reconcile_orders(
                reads[BrokerSection.ORDERS], requested_instant, local_open_orders, breaks
            ),
        }

    return BrokerReconciliation(
        as_of=canonical_as_of,
        account_status=account_status,
        positions_status=section_statuses[BrokerSection.POSITIONS],
        cash_status=section_statuses[BrokerSection.CASH],
        orders_status=section_statuses[BrokerSection.ORDERS],
        connected=connected,
        breaks=tuple(breaks),
    )


def audit_document(reconciliation: BrokerReconciliation) -> dict[str, Any]:
    """Return a credential-redacted JSON-compatible audit payload."""

    return redact_secrets(_json_value({"contract": "broker-reconciliation-audit.v1", **asdict(reconciliation)}))


def export_payload(reconciliation: BrokerReconciliation) -> dict[str, Any]:
    """Return a credential-redacted export payload."""

    return redact_secrets(audit_document(reconciliation))


def _read(method: Callable[[], BrokerRead[Any] | None]) -> BrokerRead[Any] | None:
    try:
        return method()
    except Exception:
        # Adapter exception text can contain a credential; do not log or export it.
        _LOGGER.warning("Broker read failed; reconciliation is unknown")
        return None


def _fresh_value(
    read: BrokerRead[Any] | None,
    requested: datetime,
    kind: BrokerBreakKind,
    section: BrokerSection,
    breaks: list[BrokerReconciliationBreak],
) -> Any | None:
    if read is None:
        breaks.append(_unknown_break(kind, section, "broker section is unavailable"))
        return None
    try:
        observed = _instant(read.observed_at)
    except (AttributeError, TypeError, ValueError):
        breaks.append(_unknown_break(kind, section, "broker observation time is invalid"))
        return None
    if observed != requested:
        breaks.append(_unknown_break(kind, section, "broker observation is not current at the requested instant"))
        return None
    if read.value is None:
        breaks.append(_unknown_break(kind, section, "broker section value is unavailable"))
        return None
    return read.value


def _unknown_section(
    section: BrokerSection,
    kind: BrokerBreakKind,
    status: BrokerSectionStatus,
    reads: Mapping[BrokerSection, BrokerRead[Any] | None],
    requested: datetime,
    breaks: list[BrokerReconciliationBreak],
) -> BrokerSectionStatus:
    read = reads[section]
    if _fresh_value(read, requested, kind, section, breaks) is not None:
        breaks.append(_unknown_break(kind, section, "broker account status does not permit reconciliation"))
    return status


def _reconcile_positions(
    read: BrokerRead[Any] | None,
    requested: datetime,
    local_replay: LedgerReplay,
    breaks: list[BrokerReconciliationBreak],
) -> BrokerSectionStatus:
    value = _fresh_value(read, requested, BrokerBreakKind.POSITIONS_UNKNOWN, BrokerSection.POSITIONS, breaks)
    if value is None:
        return BrokerSectionStatus.UNKNOWN
    if _local_replay_is_stale(local_replay, requested):
        breaks.append(_unknown_break(
            BrokerBreakKind.POSITIONS_UNKNOWN,
            BrokerSection.POSITIONS,
            "canonical ledger replay is not current at the requested instant",
        ))
        return BrokerSectionStatus.UNKNOWN
    if local_replay.missing_position_instrument_lines or local_replay.timing_uncertainty_entry_ids:
        breaks.append(_unknown_break(
            BrokerBreakKind.POSITIONS_UNKNOWN,
            BrokerSection.POSITIONS,
            "canonical ledger replay contains unattributed or timing-unknown position evidence",
        ))
        return BrokerSectionStatus.UNKNOWN
    try:
        broker_positions = _unique_positions(value)
        local_position_values: dict[str, list[Decimal]] = {}
        for position in local_replay.positions:
            local_position_values.setdefault(position.instrument_id, []).append(position.quantity)
        local_positions = {key: _sum_exact(values) for key, values in local_position_values.items()}
    except (AttributeError, TypeError, ValueError, InvalidOperation):
        breaks.append(_unknown_break(BrokerBreakKind.POSITIONS_UNKNOWN, BrokerSection.POSITIONS, "position evidence is invalid"))
        return BrokerSectionStatus.UNKNOWN
    mismatch_count = 0
    for key in sorted(local_positions.keys() | broker_positions.keys()):
        local = local_positions.get(key, Decimal(0))
        broker = broker_positions.get(key, Decimal(0))
        if local != broker:
            mismatch_count += 1
            breaks.append(BrokerReconciliationBreak(
                BrokerBreakKind.POSITION_MISMATCH,
                BrokerSection.POSITIONS,
                key,
                str(local),
                str(broker),
                "canonical ledger quantity differs from broker quantity",
            ))
    return BrokerSectionStatus.BREAK if mismatch_count else BrokerSectionStatus.RECONCILED


def _reconcile_cash(
    read: BrokerRead[Any] | None,
    requested: datetime,
    local_replay: LedgerReplay,
    breaks: list[BrokerReconciliationBreak],
) -> BrokerSectionStatus:
    value = _fresh_value(read, requested, BrokerBreakKind.CASH_UNKNOWN, BrokerSection.CASH, breaks)
    if value is None:
        return BrokerSectionStatus.UNKNOWN
    if _local_replay_is_stale(local_replay, requested):
        breaks.append(_unknown_break(
            BrokerBreakKind.CASH_UNKNOWN,
            BrokerSection.CASH,
            "canonical ledger replay is not current at the requested instant",
        ))
        return BrokerSectionStatus.UNKNOWN
    try:
        broker_cash = _unique_cash(value)
        local_cash_values: dict[str, list[Decimal]] = {}
        for balance in local_replay.cash:
            local_cash_values.setdefault(balance.currency, []).append(balance.book_balance)
        local_cash = {key: _sum_exact(values) for key, values in local_cash_values.items()}
    except (AttributeError, TypeError, ValueError, InvalidOperation):
        breaks.append(_unknown_break(BrokerBreakKind.CASH_UNKNOWN, BrokerSection.CASH, "cash evidence is invalid"))
        return BrokerSectionStatus.UNKNOWN
    mismatch_count = 0
    for key in sorted(local_cash.keys() | broker_cash.keys()):
        local = local_cash.get(key, Decimal(0))
        broker = broker_cash.get(key, Decimal(0))
        if local != broker:
            mismatch_count += 1
            breaks.append(BrokerReconciliationBreak(
                BrokerBreakKind.CASH_MISMATCH,
                BrokerSection.CASH,
                key,
                str(local),
                str(broker),
                "canonical ledger book balance differs from broker cash balance",
            ))
    return BrokerSectionStatus.BREAK if mismatch_count else BrokerSectionStatus.RECONCILED


def _reconcile_orders(
    read: BrokerRead[Any] | None,
    requested: datetime,
    local_open_orders: Sequence[LocalOpenOrder],
    breaks: list[BrokerReconciliationBreak],
) -> BrokerSectionStatus:
    value = _fresh_value(read, requested, BrokerBreakKind.ORDERS_UNKNOWN, BrokerSection.ORDERS, breaks)
    if value is None:
        return BrokerSectionStatus.UNKNOWN
    try:
        broker_orders = _unique_orders(value)
        local_orders = {
            order.order_id: order
            for order in local_open_orders
            if _is_open_status(order.status)
        }
        if len(local_orders) != sum(_is_open_status(order.status) for order in local_open_orders):
            raise ValueError("duplicate local order identity")
    except (AttributeError, TypeError, ValueError):
        breaks.append(_unknown_break(BrokerBreakKind.ORDERS_UNKNOWN, BrokerSection.ORDERS, "open order evidence is invalid"))
        return BrokerSectionStatus.UNKNOWN
    mismatch_count = 0
    for key in sorted(local_orders.keys() | broker_orders.keys()):
        local = local_orders.get(key)
        broker = broker_orders.get(key)
        local_value = _local_order_value(local)
        broker_value = _broker_order_value(broker)
        if local_value != broker_value:
            mismatch_count += 1
            breaks.append(BrokerReconciliationBreak(
                BrokerBreakKind.OPEN_ORDER_MISMATCH,
                BrokerSection.ORDERS,
                key,
                local_value,
                broker_value,
                "local order lifecycle differs from broker open order state",
            ))
    return BrokerSectionStatus.BREAK if mismatch_count else BrokerSectionStatus.RECONCILED


def _unique_positions(rows: object) -> dict[str, Decimal]:
    if not isinstance(rows, (tuple, list)):
        raise TypeError("positions must be a sequence")
    result: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, BrokerPosition) or not row.instrument_id.strip():
            raise ValueError("position row is invalid")
        if row.instrument_id in result or not row.quantity.is_finite():
            raise ValueError("position identity or quantity is invalid")
        result[row.instrument_id] = row.quantity
    return result


def _unique_cash(rows: object) -> dict[str, Decimal]:
    if not isinstance(rows, (tuple, list)):
        raise TypeError("cash must be a sequence")
    result: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, BrokerCash) or len(row.currency) != 3 or not row.currency.isupper():
            raise ValueError("cash row is invalid")
        if row.currency in result or not row.balance.is_finite():
            raise ValueError("cash identity or balance is invalid")
        result[row.currency] = row.balance
    return result


def _unique_orders(rows: object) -> dict[str, BrokerOpenOrder]:
    if not isinstance(rows, (tuple, list)):
        raise TypeError("orders must be a sequence")
    result: dict[str, BrokerOpenOrder] = {}
    for row in rows:
        if not isinstance(row, BrokerOpenOrder) or not row.order_id.strip():
            raise ValueError("order row is invalid")
        if row.order_id in result or not row.quantity.is_finite() or not row.remaining_quantity.is_finite():
            raise ValueError("order identity or quantity is invalid")
        result[row.order_id] = row
    return result


def _local_order_value(order: LocalOpenOrder | None) -> str | None:
    if order is None:
        return None
    return "|".join((
        order.instrument_id,
        order.side,
        str(order.quantity),
        str(order.remaining_quantity),
        order.status,
    ))


def _broker_order_value(order: BrokerOpenOrder | None) -> str | None:
    if order is None:
        return None
    return "|".join((
        order.instrument_id,
        order.side,
        str(order.quantity),
        str(order.remaining_quantity),
        order.status,
    ))


def _unknown_break(kind: BrokerBreakKind, section: BrokerSection, detail: str) -> BrokerReconciliationBreak:
    return BrokerReconciliationBreak(kind, section, None, None, None, detail)


def _instant(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _local_replay_is_stale(local_replay: LedgerReplay, requested: datetime) -> bool:
    try:
        return _instant(local_replay.as_of) != requested
    except (AttributeError, TypeError, ValueError):
        return True


def _sum_exact(values: Sequence[Decimal]) -> Decimal:
    nonzero = tuple(value for value in values if value)
    if not nonzero:
        return Decimal(0)
    min_exponent = min(int(value.as_tuple().exponent) for value in nonzero)
    max_adjusted = max(value.adjusted() for value in nonzero)
    with localcontext() as context:
        context.prec = max(28, max_adjusted - min_exponent + len(str(len(values))) + 2)
        return sum(values, Decimal(0))


def _is_open_status(status: str) -> bool:
    try:
        return OrderState(status) in _OPEN_ORDER_STATES
    except (TypeError, ValueError):
        raise ValueError("local order status is invalid")


def _canonical_instant(parsed: datetime) -> str:
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


__all__ = [
    "BrokerBreakKind",
    "BrokerReconciliation",
    "BrokerReconciliationBreak",
    "BrokerSection",
    "BrokerSectionStatus",
    "audit_document",
    "export_payload",
    "reconcile_broker_state",
]
