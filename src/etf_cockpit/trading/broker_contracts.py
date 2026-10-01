"""Read-only broker evidence contracts; they contain no credential fields."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, Protocol, TypeVar


@dataclass(frozen=True)
class BrokerPosition:
    instrument_id: str
    quantity: Decimal


@dataclass(frozen=True)
class BrokerCash:
    currency: str
    balance: Decimal


@dataclass(frozen=True)
class BrokerOpenOrder:
    order_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    remaining_quantity: Decimal
    status: str


@dataclass(frozen=True)
class LocalOpenOrder:
    """Read projection of a live local order lifecycle plus its instrument identity."""

    order_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    remaining_quantity: Decimal
    status: str


@dataclass(frozen=True)
class BrokerAccountStatus:
    connected: bool


ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class BrokerRead(Generic[ValueT]):
    """One read result, tied to the broker's point-in-time observation."""

    observed_at: str
    value: ValueT


@dataclass(frozen=True)
class BrokerSnapshot:
    """Immutable fixture data; ``None`` means unavailable, while ``()`` means empty."""

    observed_at: str
    positions: tuple[BrokerPosition, ...] | None
    cash: tuple[BrokerCash, ...] | None
    orders: tuple[BrokerOpenOrder, ...] | None
    account_status: BrokerAccountStatus | None


class BrokerReadOnlyAdapter(Protocol):
    """Minimal read-only adapter contract. No submit or cancel operation exists."""

    def read_positions(self) -> BrokerRead[tuple[BrokerPosition, ...]] | None: ...

    def read_cash(self) -> BrokerRead[tuple[BrokerCash, ...]] | None: ...

    def read_orders(self) -> BrokerRead[tuple[BrokerOpenOrder, ...]] | None: ...

    def read_account_status(self) -> BrokerRead[BrokerAccountStatus] | None: ...


__all__ = [
    "BrokerAccountStatus",
    "BrokerCash",
    "BrokerOpenOrder",
    "BrokerPosition",
    "BrokerRead",
    "BrokerReadOnlyAdapter",
    "BrokerSnapshot",
    "LocalOpenOrder",
]
