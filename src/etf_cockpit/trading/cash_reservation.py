"""Decimal cash reservations shared by paper and future broker lifecycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import sqlite3
from typing import Protocol


class CashReservationError(ValueError):
    """A cash reservation cannot be created or updated safely."""


class InsufficientBuyingPower(CashReservationError):
    """The account does not have enough available cash for a reservation."""


class CashSource(Protocol):
    """Read-only authority for an account's currency cash projection."""

    def cash_balance(self, *, account_id: str, currency: str, as_of: datetime) -> Decimal:
        """Return the source balance without converting it to float."""


def projected_fill_ids(cash_source: object, *, account_id: str, as_of: datetime) -> frozenset[str] | None:
    """Return the fills the cash source's balance already contains, or None when it cannot say."""

    reader = getattr(cash_source, "projected_fill_ids", None)
    if not callable(reader):
        return None
    return frozenset(str(item) for item in reader(account_id=account_id, as_of=as_of))


def confirmed_fill_ids(cash_source: object, *, account_id: str, as_of: datetime) -> frozenset[str] | None:
    """Return the fills the cash source has posted to its settled balance, or None when it cannot say.

    A source that reports this set confirms the cash-source posting of a settled
    commitment; a due commitment stays unavailable until its fill appears here.
    """

    reader = getattr(cash_source, "confirmed_fill_ids", None)
    if not callable(reader):
        return None
    return frozenset(str(item) for item in reader(account_id=account_id, as_of=as_of))


def _instant(value: object) -> datetime | None:
    """Parse a stored ISO instant; unreadable values return None so callers keep the conservative side."""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class CashReservation:
    order_id: str
    account_id: str
    currency: str
    original_quantity: Decimal
    remaining_quantity: Decimal
    limit_price: Decimal
    fee_estimate: Decimal
    reserved_amount: Decimal
    status: str


def decimal_value(value: object, field: str, *, positive: bool = False, non_negative: bool = False) -> Decimal:
    """Parse finite Decimal money/quantity, retaining legacy float text exactly."""

    if isinstance(value, bool):
        raise CashReservationError(f"{field} must be a finite Decimal value.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CashReservationError(f"{field} must be a finite Decimal value.") from exc
    if not result.is_finite():
        raise CashReservationError(f"{field} must be a finite Decimal value.")
    if positive and result <= 0:
        raise CashReservationError(f"{field} must be greater than zero.")
    if non_negative and result < 0:
        raise CashReservationError(f"{field} cannot be negative.")
    return result


def _as_of_date(as_of: datetime) -> date:
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise CashReservationError("as_of must be a timezone-aware datetime.")
    return as_of.astimezone(timezone.utc).date()


class CashReservationService:
    """SQLite-backed reservations; callers perform each mutation in one write transaction."""

    @staticmethod
    def create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS order_reservations (
                order_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                original_quantity TEXT NOT NULL,
                remaining_quantity TEXT NOT NULL,
                limit_price TEXT NOT NULL,
                fee_estimate TEXT NOT NULL,
                reserved_amount TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'released')),
                FOREIGN KEY(order_id) REFERENCES order_intents(order_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS order_reservations_account_currency
            ON order_reservations(account_id, currency, status)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS unsettled_cash_commitments (
                order_id TEXT NOT NULL,
                fill_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                buy_commitment TEXT NOT NULL,
                sale_credit TEXT NOT NULL,
                settlement_date TEXT,
                PRIMARY KEY(order_id, fill_id),
                FOREIGN KEY(order_id) REFERENCES order_intents(order_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS unsettled_cash_account_currency
            ON unsettled_cash_commitments(account_id, currency, settlement_date)
            """
        )

    def reserve(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        order_id: str,
        currency: str,
        side: str,
        quantity: Decimal,
        limit_price: Decimal,
        fee_estimate: Decimal,
        cash_source: CashSource,
        as_of: datetime,
    ) -> CashReservation:
        amount = self._reservation_amount(quantity, limit_price, fee_estimate) if side == "buy" else Decimal("0")
        if side == "buy":
            available = self.available_buying_power(
                connection,
                account_id=account_id,
                currency=currency,
                cash_source=cash_source,
                as_of=as_of,
            )
            if amount > available:
                raise InsufficientBuyingPower(
                    f"Reservation requires {amount} {currency}; available buying power is {available} {currency}."
                )
        connection.execute(
            """
            INSERT INTO order_reservations(
                order_id, account_id, currency, original_quantity, remaining_quantity,
                limit_price, fee_estimate, reserved_amount, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                order_id,
                account_id,
                currency,
                str(quantity),
                str(quantity),
                str(limit_price),
                str(fee_estimate),
                str(amount),
            ),
        )
        return CashReservation(
            order_id, account_id, currency, quantity, quantity, limit_price, fee_estimate, amount, "active"
        )

    def available_buying_power(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        currency: str,
        cash_source: CashSource,
        as_of: datetime,
        in_flight_fill_ids: frozenset[str] = frozenset(),
    ) -> Decimal:
        """Return cash available at ``as_of``.

        Reservations and fill commitments created after ``as_of`` are excluded
        (an unknown creation time stays included). A commitment past its
        settlement date is released only once the cash source confirms the
        posting when it can report that; ``in_flight_fill_ids`` names fills
        being recorded now, which no source can have posted yet, so their buy
        debit is always held.
        """

        balance = decimal_value(
            cash_source.cash_balance(account_id=account_id, currency=currency, as_of=as_of),
            "cash balance",
        )
        cutoff_instant = as_of.astimezone(timezone.utc)
        date_cutoff = _as_of_date(as_of).isoformat()
        reservation_rows = connection.execute(
            """
            SELECT reservation.reserved_amount, intent.created_at
            FROM order_reservations AS reservation
            LEFT JOIN order_intents AS intent ON intent.order_id = reservation.order_id
            WHERE reservation.account_id = ? AND reservation.currency = ? AND reservation.status = 'active'
            """,
            (account_id, currency),
        ).fetchall()
        commitment_rows = connection.execute(
            """
            SELECT buy_commitment, sale_credit, fill_id, settlement_date, order_id
            FROM unsettled_cash_commitments
            WHERE account_id = ? AND currency = ?
            """,
            (account_id, currency),
        ).fetchall()
        reservations = [row for row in reservation_rows if self._created_by(row[1], cutoff_instant)]
        fill_times = self._fill_times(connection, {str(row[4]) for row in commitment_rows})
        projected = projected_fill_ids(cash_source, account_id=account_id, as_of=as_of)
        confirmed = confirmed_fill_ids(cash_source, account_id=account_id, as_of=as_of)
        commitments = []
        for row in commitment_rows:
            if not self._created_by(fill_times.get((str(row[4]), str(row[2]))), cutoff_instant):
                continue
            pending = row[3] is None or str(row[3]) > date_cutoff
            held = str(row[2]) in in_flight_fill_ids or (
                confirmed is not None and str(row[2]) not in confirmed and projected is None
            )
            if pending or held:
                commitments.append(row)
        reserved = sum((decimal_value(row[0], "reserved amount", non_negative=True) for row in reservations), Decimal("0"))
        # A paper projection books fills immediately, while a canonical ledger
        # balance is filtered to settled entries. Apply the unsettled side that
        # the selected source does not already reflect, fill by fill when the
        # source reports which fills its balance contains: a projected sale
        # credit and an unprojected buy debit can coexist after an interrupted
        # projection, and one global flag would unlock the projected credit.
        if projected is not None:
            unavailable_unsettled = Decimal("0")
            for row in commitments:
                if str(row[2]) in projected:
                    if row[3] is None or str(row[3]) > date_cutoff:
                        unavailable_unsettled += decimal_value(row[1], "unsettled sale", non_negative=True)
                else:
                    unavailable_unsettled += decimal_value(row[0], "unsettled buy", non_negative=True)
        else:
            unsettled_buys = sum((decimal_value(row[0], "unsettled buy", non_negative=True) for row in commitments), Decimal("0"))
            unsettled_sales = sum(
                (
                    decimal_value(row[1], "unsettled sale", non_negative=True)
                    for row in commitments
                    if row[3] is None or str(row[3]) > date_cutoff
                ),
                Decimal("0"),
            )
            includes_unsettled = bool(getattr(cash_source, "cash_includes_unsettled_trades", False))
            unavailable_unsettled = unsettled_sales if includes_unsettled else unsettled_buys
        return balance - reserved - unavailable_unsettled

    @staticmethod
    def _created_by(created_at: object, cutoff: datetime) -> bool:
        created = _instant(created_at)
        return created is None or created <= cutoff

    @staticmethod
    def _fill_times(connection: sqlite3.Connection, order_ids: set[str]) -> dict[tuple[str, str], object]:
        """Map (order, fill) to the lifecycle event time that committed it, when that journal is present."""

        if not order_ids:
            return {}
        try:
            rows = connection.execute(
                """
                SELECT order_id, occurred_at, payload_json FROM order_lifecycle_events
                WHERE event_type IN ('fill', 'reconciled')
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        times: dict[tuple[str, str], object] = {}
        for order_id, occurred_at, payload_json in rows:
            if str(order_id) not in order_ids:
                continue
            try:
                payload = json.loads(payload_json)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("fill_id") is not None:
                times[(str(order_id), str(payload["fill_id"]))] = occurred_at
        return times

    def record_fill(
        self,
        connection: sqlite3.Connection,
        *,
        order_id: str,
        fill_id: str,
        remaining_quantity: Decimal,
        fill_cash_change: Decimal,
        side: str,
        account_id: str,
        currency: str,
        settlement_date: date | None,
    ) -> CashReservation:
        row = connection.execute(
            """
            SELECT original_quantity, limit_price, fee_estimate, currency, account_id
            FROM order_reservations WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise CashReservationError("The order has no cash reservation record.")
        original_quantity = decimal_value(row[0], "original quantity", positive=True)
        limit_price = decimal_value(row[1], "limit price", non_negative=True)
        fee_estimate = decimal_value(row[2], "fee estimate", non_negative=True)
        if row[3] != currency or row[4] != account_id:
            raise CashReservationError("The fill account or currency does not match its reservation.")
        if remaining_quantity < 0 or remaining_quantity > original_quantity:
            raise CashReservationError("The remaining fill quantity is outside the original order quantity.")
        amount = (
            self._reservation_amount(remaining_quantity, limit_price, fee_estimate)
            if remaining_quantity > 0 and side == "buy"
            else Decimal("0")
        )
        connection.execute(
            """
            UPDATE order_reservations
            SET remaining_quantity = ?, reserved_amount = ?, status = ?
            WHERE order_id = ?
            """,
            (str(remaining_quantity), str(amount), "active" if remaining_quantity > 0 else "released", order_id),
        )
        buy_commitment = max(Decimal("0"), -fill_cash_change)
        sale_credit = max(Decimal("0"), fill_cash_change)
        connection.execute(
            """
            INSERT INTO unsettled_cash_commitments(
                order_id, fill_id, account_id, currency, buy_commitment, sale_credit, settlement_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                fill_id,
                account_id,
                currency,
                str(buy_commitment),
                str(sale_credit),
                None if settlement_date is None else settlement_date.isoformat(),
            ),
        )
        return CashReservation(
            order_id,
            account_id,
            currency,
            original_quantity,
            remaining_quantity,
            limit_price,
            fee_estimate,
            amount,
            "active" if remaining_quantity > 0 else "released",
        )

    def release(self, connection: sqlite3.Connection, order_id: str) -> None:
        connection.execute(
            "UPDATE order_reservations SET reserved_amount = '0', status = 'released' WHERE order_id = ?",
            (order_id,),
        )

    @staticmethod
    def get(connection: sqlite3.Connection, order_id: str) -> CashReservation | None:
        row = connection.execute(
            """
            SELECT order_id, account_id, currency, original_quantity, remaining_quantity,
                   limit_price, fee_estimate, reserved_amount, status
            FROM order_reservations WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return CashReservation(
            row[0], row[1], row[2], Decimal(row[3]), Decimal(row[4]), Decimal(row[5]),
            Decimal(row[6]), Decimal(row[7]), row[8]
        )

    @staticmethod
    def _reservation_amount(quantity: Decimal, limit_price: Decimal, fee_estimate: Decimal) -> Decimal:
        # Keep the complete fee estimate until the order finishes or is cancelled.
        return quantity * limit_price + fee_estimate
