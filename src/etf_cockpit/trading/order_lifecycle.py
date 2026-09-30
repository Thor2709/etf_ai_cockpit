"""Shared deterministic order lifecycle and atomic cash reservation contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from etf_cockpit.core.config import SettlementConfig, load_settlement_config
from etf_cockpit.trading.cash_reservation import (
    CashReservation,
    CashReservationError,
    CashReservationService,
    CashSource,
    decimal_value,
)


class OrderLifecycleError(ValueError):
    """An order lifecycle request is invalid or cannot be completed safely."""


class OrderTransitionError(OrderLifecycleError):
    """A state transition is not allowed by the shared contract."""


class IdempotencyConflict(OrderLifecycleError):
    """An idempotency key was reused with different immutable request data."""


class OrderState(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RESERVED = "RESERVED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


# Both the paper simulator and a future broker facade use this exact table.
ALLOWED_TRANSITIONS: Mapping[OrderState, frozenset[OrderState]] = {
    OrderState.DRAFT: frozenset({OrderState.APPROVED, OrderState.REJECTED}),
    OrderState.APPROVED: frozenset({OrderState.RESERVED, OrderState.REJECTED}),
    OrderState.RESERVED: frozenset(
        {OrderState.SUBMITTING, OrderState.ACKNOWLEDGED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.UNKNOWN}
    ),
    OrderState.SUBMITTING: frozenset(
        {
            OrderState.ACKNOWLEDGED,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.ACKNOWLEDGED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.CANCEL_PENDING: frozenset(
        {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.UNKNOWN}
    ),
    OrderState.UNKNOWN: frozenset({OrderState.RECONCILIATION_REQUIRED}),
    OrderState.RECONCILIATION_REQUIRED: frozenset(),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
}

RECONCILIATION_ALLOWED_TARGETS = frozenset(
    {
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
    }
)


@dataclass(frozen=True)
class OrderLifecycleEvent:
    event_id: str
    order_id: str
    prior_state: OrderState
    state: OrderState
    event_type: str
    occurred_at: datetime
    payload: Mapping[str, object]
    execution_allowed: bool = False


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    idempotency_key: str
    account_id: str
    currency: str
    side: str
    quantity: Decimal
    remaining_quantity: Decimal
    limit_price: Decimal
    fee_estimate: Decimal
    state: OrderState
    venue: str | None
    instrument_type: str | None
    settlement_date: date | None
    settlement_warning: str | None
    execution_allowed: bool = False


class OrderLifecycle:
    """Append-only state transitions with cash reservation in one SQLite journal."""

    def __init__(
        self,
        db_path: Path,
        cash_source: CashSource,
        *,
        settlement: SettlementConfig | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cash_source = cash_source
        self.settlement = settlement if settlement is not None else load_settlement_config()
        self.reservations = CashReservationService()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS order_intents (
                    order_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    account_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                    quantity TEXT NOT NULL,
                    remaining_quantity TEXT NOT NULL,
                    limit_price TEXT NOT NULL,
                    fee_estimate TEXT NOT NULL,
                    state TEXT NOT NULL,
                    venue TEXT,
                    instrument_type TEXT,
                    settlement_date TEXT,
                    settlement_warning TEXT,
                    created_at TEXT NOT NULL,
                    execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK(execution_allowed = 0)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS order_lifecycle_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    order_id TEXT NOT NULL,
                    prior_state TEXT NOT NULL,
                    state TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK(execution_allowed = 0),
                    FOREIGN KEY(order_id) REFERENCES order_intents(order_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS order_events_order ON order_lifecycle_events(order_id, sequence)"
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS order_events_no_update
                BEFORE UPDATE ON order_lifecycle_events
                BEGIN SELECT RAISE(ABORT, 'order lifecycle events are append-only'); END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS order_events_no_delete
                BEFORE DELETE ON order_lifecycle_events
                BEGIN SELECT RAISE(ABORT, 'order lifecycle events are append-only'); END
                """
            )
            self.reservations.create_schema(connection)

    @staticmethod
    def _connect_path(db_path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _connect(self) -> sqlite3.Connection:
        return self._connect_path(self.db_path)

    def reserve_order(
        self,
        *,
        account_id: str,
        order_id: str,
        idempotency_key: str,
        currency: str,
        side: str,
        quantity: object,
        limit_price: object,
        fee_estimate: object = Decimal("0"),
        venue: str | None,
        instrument_type: str | None,
        occurred_at: datetime | None = None,
    ) -> OrderIntent:
        account = self._required_text(account_id, "account_id")
        requested_order_id = self._required_text(order_id, "order_id")
        key = self._required_text(idempotency_key, "idempotency_key")
        currency_code = self._currency(currency)
        if side not in {"buy", "sell"}:
            raise OrderLifecycleError("side must be 'buy' or 'sell'.")
        amount_quantity = decimal_value(quantity, "quantity", positive=True)
        price = decimal_value(limit_price, "limit_price", positive=True)
        fees = decimal_value(fee_estimate, "fee_estimate", non_negative=True)
        instant = self._timestamp(occurred_at)
        clean_venue = self._optional_text(venue)
        clean_type = self._optional_text(instrument_type)
        settle_on = self.settlement.settlement_date(clean_venue, clean_type, instant.date())
        warning = None if settle_on is not None else "No settlement rule is available; unsettled sale proceeds remain locked until reconciled."

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM order_intents WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                if not self._intent_matches(
                    existing,
                    account_id=account,
                    currency=currency_code,
                    side=side,
                    quantity=amount_quantity,
                    limit_price=price,
                    fee_estimate=fees,
                    venue=clean_venue,
                    instrument_type=clean_type,
                ):
                    raise IdempotencyConflict("The idempotency key was already used with different order terms.")
                connection.commit()
                return self._intent_from_row(existing)

            collision = connection.execute("SELECT 1 FROM order_intents WHERE order_id = ?", (requested_order_id,)).fetchone()
            if collision is not None:
                raise IdempotencyConflict("The order ID is already assigned to another idempotency key.")
            connection.execute(
                """
                INSERT INTO order_intents(
                    order_id, idempotency_key, account_id, currency, side, quantity,
                    remaining_quantity, limit_price, fee_estimate, state, venue,
                    instrument_type, settlement_date, settlement_warning, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    requested_order_id,
                    key,
                    account,
                    currency_code,
                    side,
                    str(amount_quantity),
                    str(amount_quantity),
                    str(price),
                    str(fees),
                    OrderState.DRAFT.value,
                    clean_venue,
                    clean_type,
                    None if settle_on is None else settle_on.isoformat(),
                    warning,
                    instant.isoformat(),
                ),
            )
            self._append_event(
                connection,
                order_id=requested_order_id,
                prior_state=OrderState.DRAFT,
                state=OrderState.APPROVED,
                event_type="proposal_approved",
                event_key=f"intent:{key}:approved",
                payload={"idempotency_key": key, "execution_allowed": False},
                occurred_at=instant,
            )
            self._ensure_transition(OrderState.DRAFT, OrderState.APPROVED)
            self._ensure_transition(OrderState.APPROVED, OrderState.RESERVED)
            self._append_event(
                connection,
                order_id=requested_order_id,
                prior_state=OrderState.APPROVED,
                state=OrderState.RESERVED,
                event_type="cash_reserved",
                event_key=f"intent:{key}:reserved",
                payload={
                    "currency": currency_code,
                    "fee_estimate": str(fees),
                    "limit_price": str(price),
                    "quantity": str(amount_quantity),
                    "settlement_warning": warning,
                    "execution_allowed": False,
                },
                occurred_at=instant,
            )
            try:
                self.reservations.reserve(
                    connection,
                    account_id=account,
                    order_id=requested_order_id,
                    currency=currency_code,
                    side=side,
                    quantity=amount_quantity,
                    limit_price=price,
                    fee_estimate=fees,
                    cash_source=self.cash_source,
                    as_of=instant,
                )
            except CashReservationError as exc:
                raise OrderLifecycleError(str(exc)) from exc
            connection.execute(
                "UPDATE order_intents SET state = ? WHERE order_id = ?",
                (OrderState.RESERVED.value, requested_order_id),
            )
            connection.commit()
            return self.get_intent(requested_order_id)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def transition(
        self,
        order_id: str,
        state: OrderState | str,
        *,
        event_key: str,
        event_type: str | None = None,
        payload: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> OrderLifecycleEvent:
        target = self._state(state)
        key = self._required_text(event_key, "event_key")
        instant = self._timestamp(occurred_at)
        event_payload = dict(payload or {})
        event_payload.setdefault("execution_allowed", False)
        if target is OrderState.UNKNOWN:
            reason = event_payload.get("reason")
            return self.mark_unknown(
                order_id,
                event_key=key,
                reason=reason if isinstance(reason, str) and reason.strip() else "Order state is unknown.",
                occurred_at=instant,
            )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            event = self._transition_in_transaction(
                connection,
                order_id=self._required_text(order_id, "order_id"),
                target=target,
                event_key=key,
                event_type=event_type or target.value.lower(),
                payload=event_payload,
                occurred_at=instant,
            )
            connection.commit()
            return event
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def mark_unknown(
        self,
        order_id: str,
        *,
        event_key: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> OrderLifecycleEvent:
        detail = self._required_text(reason, "reason")
        instant = self._timestamp(occurred_at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            order = self._order_row(connection, order_id)
            current = OrderState(order[9])
            unknown_key = self._required_text(event_key, "event_key")
            unknown_payload = {"reason": detail, "execution_allowed": False}
            existing_unknown = self._existing_event(connection, order_id, unknown_key)
            reconciliation_key = unknown_key + ":reconciliation-required"
            if existing_unknown is not None:
                self._validate_event_retry(existing_unknown, "unknown", unknown_payload)
                existing_reconciliation = self._existing_event(connection, order_id, reconciliation_key)
                if existing_reconciliation is None:
                    raise OrderLifecycleError("The unknown-state journal is incomplete and requires reconciliation.")
                connection.commit()
                return existing_reconciliation
            if current is OrderState.RECONCILIATION_REQUIRED:
                raise OrderTransitionError("Unknown order state blocks further transitions until reconciled.")
            self._ensure_transition(current, OrderState.UNKNOWN)
            self._ensure_transition(OrderState.UNKNOWN, OrderState.RECONCILIATION_REQUIRED)
            self._append_event(
                connection,
                order_id=order_id,
                prior_state=current,
                state=OrderState.UNKNOWN,
                event_type="unknown",
                event_key=unknown_key,
                payload=unknown_payload,
                occurred_at=instant,
            )
            reconciliation_payload = {
                "reason": "An unknown order state requires operator reconciliation; automatic retries are blocked.",
                "source_event_key": unknown_key,
                "execution_allowed": False,
            }
            self._append_event(
                connection,
                order_id=order_id,
                prior_state=OrderState.UNKNOWN,
                state=OrderState.RECONCILIATION_REQUIRED,
                event_type="reconciliation_required",
                event_key=reconciliation_key,
                payload=reconciliation_payload,
                occurred_at=instant,
            )
            connection.execute(
                "UPDATE order_intents SET state = ? WHERE order_id = ?",
                (OrderState.RECONCILIATION_REQUIRED.value, order_id),
            )
            connection.commit()
            return self._event_by_key(connection, order_id, reconciliation_key)  # connection closed below
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def reconcile(
        self,
        order_id: str,
        state: OrderState | str,
        *,
        event_key: str,
        reason: str,
        remaining_quantity: object | None = None,
        occurred_at: datetime | None = None,
    ) -> OrderLifecycleEvent:
        target = self._state(state)
        key = self._required_text(event_key, "event_key")
        detail = self._required_text(reason, "reason")
        instant = self._timestamp(occurred_at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._order_row(connection, order_id)
            current = OrderState(row[9])
            if current is not OrderState.RECONCILIATION_REQUIRED:
                raise OrderTransitionError("Only a reconciliation-required order can be reconciled.")
            if target not in RECONCILIATION_ALLOWED_TARGETS:
                raise OrderTransitionError(f"Cannot reconcile an order to {target.value}.")
            event_payload: dict[str, object] = {"reason": detail, "execution_allowed": False}
            if target is OrderState.PARTIALLY_FILLED:
                if remaining_quantity is None:
                    raise OrderLifecycleError("A partially filled reconciliation requires remaining_quantity.")
                remaining = decimal_value(remaining_quantity, "remaining_quantity", non_negative=True)
                original = decimal_value(row[5], "quantity", positive=True)
                if remaining >= original:
                    raise OrderLifecycleError("A partially filled reconciliation must leave less than the original quantity.")
                reservation = self.reservations.get(connection, order_id)
                if reservation is not None:
                    amount = remaining * reservation.limit_price + reservation.fee_estimate
                    connection.execute(
                        """
                        UPDATE order_reservations
                        SET remaining_quantity = ?, reserved_amount = ?, status = 'active'
                        WHERE order_id = ?
                        """,
                        (str(remaining), str(amount if row[4] == "buy" else Decimal("0")), order_id),
                    )
                connection.execute(
                    "UPDATE order_intents SET remaining_quantity = ? WHERE order_id = ?",
                    (str(remaining), order_id),
                )
                event_payload["remaining_quantity"] = str(remaining)
            elif target is OrderState.FILLED:
                connection.execute(
                    "UPDATE order_intents SET remaining_quantity = '0' WHERE order_id = ?", (order_id,)
                )
                self.reservations.release(connection, order_id)
            elif target in {OrderState.CANCELLED, OrderState.REJECTED}:
                self.reservations.release(connection, order_id)
            event = self._append_event(
                connection,
                order_id=order_id,
                prior_state=current,
                state=target,
                event_type="reconciled",
                event_key=key,
                payload=event_payload,
                occurred_at=instant,
            )
            connection.execute("UPDATE order_intents SET state = ? WHERE order_id = ?", (target.value, order_id))
            connection.commit()
            return event
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def record_fill(
        self,
        order_id: str,
        *,
        fill_id: str,
        quantity: object,
        price: object,
        fee: object = Decimal("0"),
        fx_rate: object = Decimal("1"),
        occurred_at: datetime | None = None,
    ) -> tuple[OrderIntent, CashReservation]:
        identifier = self._required_text(fill_id, "fill_id")
        filled = decimal_value(quantity, "quantity", positive=True)
        fill_price = decimal_value(price, "price", positive=True)
        fill_fee = decimal_value(fee, "fee", non_negative=True)
        fx = decimal_value(fx_rate, "fx_rate", positive=True)
        instant = self._timestamp(occurred_at)
        event_key = f"fill:{identifier}"
        event_payload = {
            "fill_id": identifier,
            "quantity": str(filled),
            "price": str(fill_price),
            "fee": str(fill_fee),
            "fx_rate": str(fx),
            "execution_allowed": False,
        }
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._order_row(connection, order_id)
            current = OrderState(row[9])
            existing = self._existing_event(connection, order_id, event_key)
            if existing is not None:
                self._validate_event_retry(existing, "fill", event_payload)
                reservation = self.reservations.get(connection, order_id)
                if reservation is None:
                    raise OrderLifecycleError("The order reservation disappeared after its fill was recorded.")
                connection.commit()
                return self._intent_from_row(row), reservation
            if current in {OrderState.UNKNOWN, OrderState.RECONCILIATION_REQUIRED}:
                raise OrderTransitionError("Unknown order state blocks fills until reconciliation completes.")
            remaining = decimal_value(row[6], "remaining_quantity", positive=True)
            if filled > remaining:
                raise OrderLifecycleError("A fill cannot exceed the remaining order quantity.")
            next_remaining = remaining - filled
            target = OrderState.FILLED if next_remaining == 0 else OrderState.PARTIALLY_FILLED
            self._ensure_transition(current, target)
            side = str(row[4])
            multiplier = fx
            cash_delta = filled * fill_price * multiplier + fill_fee
            if side == "buy":
                cash_delta = -cash_delta
            else:
                cash_delta = filled * fill_price * multiplier - fill_fee
            settlement = self.settlement.settlement_date(
                row[10], row[11], instant.date()
            )
            self.reservations.record_fill(
                connection,
                order_id=order_id,
                fill_id=identifier,
                remaining_quantity=next_remaining,
                fill_cash_change=cash_delta,
                side=side,
                account_id=str(row[2]),
                currency=str(row[3]),
                settlement_date=settlement,
            )
            available_after_fill = self.reservations.available_buying_power(
                connection,
                account_id=str(row[2]),
                currency=str(row[3]),
                cash_source=self.cash_source,
                as_of=instant,
            )
            if bool(getattr(self.cash_source, "cash_includes_unsettled_trades", False)):
                available_after_fill -= max(Decimal("0"), -cash_delta)
            if available_after_fill < 0:
                raise OrderLifecycleError(
                    "The fill would consume cash reserved for another open order."
                )
            self._append_event(
                connection,
                order_id=order_id,
                prior_state=current,
                state=target,
                event_type="fill",
                event_key=event_key,
                payload=event_payload,
                occurred_at=instant,
            )
            connection.execute(
                "UPDATE order_intents SET state = ?, remaining_quantity = ? WHERE order_id = ?",
                (target.value, str(next_remaining), order_id),
            )
            reservation = self.reservations.get(connection, order_id)
            if reservation is None:
                raise OrderLifecycleError("The order reservation disappeared after its fill was recorded.")
            connection.commit()
            return self.get_intent(order_id), reservation
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def available_buying_power(self, *, account_id: str, currency: str, as_of: datetime | None = None) -> Decimal:
        instant = self._timestamp(as_of)
        connection = self._connect()
        try:
            return self.reservations.available_buying_power(
                connection,
                account_id=self._required_text(account_id, "account_id"),
                currency=self._currency(currency),
                cash_source=self.cash_source,
                as_of=instant,
            )
        finally:
            connection.close()

    def get_intent(self, order_id: str) -> OrderIntent:
        connection = self._connect()
        try:
            return self._intent_from_row(self._order_row(connection, order_id))
        finally:
            connection.close()

    def get_state(self, order_id: str) -> OrderState:
        return self.get_intent(order_id).state

    def get_reservation(self, order_id: str) -> CashReservation | None:
        connection = self._connect()
        try:
            return self.reservations.get(connection, order_id)
        finally:
            connection.close()

    def event_count(self, order_id: str | None = None) -> int:
        connection = self._connect()
        try:
            if order_id is None:
                row = connection.execute("SELECT COUNT(*) FROM order_lifecycle_events").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM order_lifecycle_events WHERE order_id = ?", (order_id,)
                ).fetchone()
            return int(row[0])
        finally:
            connection.close()

    def _transition_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        order_id: str,
        target: OrderState,
        event_key: str,
        event_type: str,
        payload: Mapping[str, object],
        occurred_at: datetime,
    ) -> OrderLifecycleEvent:
        existing = self._existing_event(connection, order_id, event_key)
        if existing is not None:
            self._validate_event_retry(existing, event_type, payload)
            return existing
        row = self._order_row(connection, order_id)
        current = OrderState(row[9])
        if current in {OrderState.UNKNOWN, OrderState.RECONCILIATION_REQUIRED}:
            raise OrderTransitionError("Unknown order state blocks further transitions until reconciliation completes.")
        self._ensure_transition(current, target)
        event = self._append_event(
            connection,
            order_id=order_id,
            prior_state=current,
            state=target,
            event_type=event_type,
            event_key=event_key,
            payload=payload,
            occurred_at=occurred_at,
        )
        connection.execute("UPDATE order_intents SET state = ? WHERE order_id = ?", (target.value, order_id))
        if target in {OrderState.CANCELLED, OrderState.REJECTED}:
            self.reservations.release(connection, order_id)
        return event

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        order_id: str,
        prior_state: OrderState,
        state: OrderState,
        event_type: str,
        event_key: str,
        payload: Mapping[str, object],
        occurred_at: datetime,
    ) -> OrderLifecycleEvent:
        event_id = hashlib.sha256(f"{order_id}\0{event_key}".encode("utf-8")).hexdigest()
        body = dict(payload)
        body["execution_allowed"] = False
        payload_json = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        connection.execute(
            """
            INSERT INTO order_lifecycle_events(
                event_id, order_id, prior_state, state, event_type, occurred_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, order_id, prior_state.value, state.value, event_type, occurred_at.isoformat(), payload_json),
        )
        return OrderLifecycleEvent(event_id, order_id, prior_state, state, event_type, occurred_at, body)

    def _existing_event(self, connection: sqlite3.Connection, order_id: str, event_key: str) -> OrderLifecycleEvent | None:
        event_id = hashlib.sha256(f"{order_id}\0{event_key}".encode("utf-8")).hexdigest()
        row = connection.execute(
            """
            SELECT event_id, order_id, prior_state, state, event_type, occurred_at, payload_json
            FROM order_lifecycle_events WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return OrderLifecycleEvent(
            row[0], row[1], OrderState(row[2]), OrderState(row[3]), row[4],
            datetime.fromisoformat(row[5]), json.loads(row[6])
        )

    @staticmethod
    def _validate_event_retry(existing: OrderLifecycleEvent, event_type: str, payload: Mapping[str, object]) -> None:
        body = dict(payload)
        body["execution_allowed"] = False
        if existing.event_type != event_type or dict(existing.payload) != body:
            raise IdempotencyConflict("An event idempotency key was reused with different event data.")

    @staticmethod
    def _ensure_transition(current: OrderState, target: OrderState) -> None:
        if target not in ALLOWED_TRANSITIONS[current]:
            raise OrderTransitionError(f"Illegal order transition: {current.value} -> {target.value}.")

    def _order_row(self, connection: sqlite3.Connection, order_id: str) -> tuple[object, ...]:
        row = connection.execute(
            "SELECT * FROM order_intents WHERE order_id = ?", (self._required_text(order_id, "order_id"),)
        ).fetchone()
        if row is None:
            raise OrderLifecycleError("The order intent does not exist.")
        return row

    def _event_by_key(self, connection: sqlite3.Connection, order_id: str, event_key: str) -> OrderLifecycleEvent:
        result = self._existing_event(connection, order_id, event_key)
        if result is None:
            raise OrderLifecycleError("The lifecycle event could not be read back.")
        return result

    @staticmethod
    def _intent_from_row(row: tuple[object, ...]) -> OrderIntent:
        return OrderIntent(
            order_id=str(row[0]),
            idempotency_key=str(row[1]),
            account_id=str(row[2]),
            currency=str(row[3]),
            side=str(row[4]),
            quantity=Decimal(str(row[5])),
            remaining_quantity=Decimal(str(row[6])),
            limit_price=Decimal(str(row[7])),
            fee_estimate=Decimal(str(row[8])),
            state=OrderState(str(row[9])),
            venue=None if row[10] is None else str(row[10]),
            instrument_type=None if row[11] is None else str(row[11]),
            settlement_date=None if row[12] is None else date.fromisoformat(str(row[12])),
            settlement_warning=None if row[13] is None else str(row[13]),
        )

    @staticmethod
    def _intent_matches(
        row: tuple[object, ...],
        *,
        account_id: str,
        currency: str,
        side: str,
        quantity: Decimal,
        limit_price: Decimal,
        fee_estimate: Decimal,
        venue: str | None,
        instrument_type: str | None,
    ) -> bool:
        return (
            str(row[2]) == account_id
            and str(row[3]) == currency
            and str(row[4]) == side
            and Decimal(str(row[5])) == quantity
            and Decimal(str(row[7])) == limit_price
            and Decimal(str(row[8])) == fee_estimate
            and (None if row[10] is None else str(row[10])) == venue
            and (None if row[11] is None else str(row[11])) == instrument_type
        )

    @staticmethod
    def _required_text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OrderLifecycleError(f"{field} must be non-empty text.")
        return value.strip()

    @staticmethod
    def _optional_text(value: object | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    @staticmethod
    def _currency(value: str) -> str:
        normalized = value.strip().upper() if isinstance(value, str) else ""
        if len(normalized) != 3 or any(character < "A" or character > "Z" for character in normalized):
            raise OrderLifecycleError("currency must be a three-letter code.")
        return normalized

    @staticmethod
    def _timestamp(value: datetime | None) -> datetime:
        instant = value or datetime.now(timezone.utc)
        if not isinstance(instant, datetime) or instant.tzinfo is None:
            raise OrderLifecycleError("occurred_at must be a timezone-aware datetime.")
        return instant.astimezone(timezone.utc)

    @staticmethod
    def _state(value: OrderState | str) -> OrderState:
        try:
            return value if isinstance(value, OrderState) else OrderState(value)
        except ValueError as exc:
            raise OrderTransitionError(f"Unsupported order state: {value!r}.") from exc
