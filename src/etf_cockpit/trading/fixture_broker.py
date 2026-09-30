"""In-memory read-only broker fixture for deterministic reconciliation."""

from __future__ import annotations

from etf_cockpit.trading.broker_contracts import (
    BrokerAccountStatus,
    BrokerCash,
    BrokerOpenOrder,
    BrokerPosition,
    BrokerRead,
    BrokerSnapshot,
)


class FixtureBrokerAdapter:
    """Expose immutable fixture state through the production read-only contract."""

    def __init__(self, snapshot: BrokerSnapshot) -> None:
        self._snapshot = snapshot

    def read_positions(self) -> BrokerRead[tuple[BrokerPosition, ...]] | None:
        return self._read(self._snapshot.positions)

    def read_cash(self) -> BrokerRead[tuple[BrokerCash, ...]] | None:
        return self._read(self._snapshot.cash)

    def read_orders(self) -> BrokerRead[tuple[BrokerOpenOrder, ...]] | None:
        return self._read(self._snapshot.orders)

    def read_account_status(self) -> BrokerRead[BrokerAccountStatus] | None:
        return self._read(self._snapshot.account_status)

    def _read(self, value: object) -> BrokerRead[object] | None:
        if value is None:
            return None
        return BrokerRead(observed_at=self._snapshot.observed_at, value=value)


__all__ = ["FixtureBrokerAdapter"]
