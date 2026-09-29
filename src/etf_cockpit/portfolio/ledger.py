from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re
import sqlite3
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etf_cockpit.data.market_adjustments import CorporateAction


ACCOUNT_TYPES = frozenset({"asset", "liability", "equity", "income", "expense"})
ACCOUNT_ROLES = frozenset({"general", "cash", "position"})
AUTHORITIES = frozenset({"paper", "broker"})
_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


class LedgerInvariantError(ValueError):
    """Raised when a ledger account or entry violates journal rules."""


@dataclass(frozen=True)
class LedgerAccount:
    account_id: str
    name: str
    account_type: str
    authority: str
    account_role: str
    parent_account_id: str | None
    created_at: str


@dataclass(frozen=True)
class LedgerPosting:
    account_id: str
    currency: str | None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    instrument_id: str | None = None
    quantity_delta: Decimal | None = None
    lot_id: str | None = None


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    authority: str
    effective_at: str
    settlement_at: str | None
    recorded_at: str
    description: str
    reversal_of_entry_id: str | None
    postings: tuple[LedgerPosting, ...]


class Ledger:
    """Journal operations backed by the connection from ``TransactionalStore``."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create_account(
        self,
        account_id: str,
        *,
        name: str,
        account_type: str,
        authority: str,
        parent_account_id: str | None = None,
        account_role: str = "general",
    ) -> LedgerAccount:
        _required_text(account_id, "account_id")
        _required_text(name, "name")
        _validate_authority(authority)
        if account_type not in ACCOUNT_TYPES:
            raise LedgerInvariantError(f"unsupported account type: {account_type!r}")
        if account_role not in ACCOUNT_ROLES:
            raise LedgerInvariantError(f"unsupported account role: {account_role!r}")
        if parent_account_id is not None:
            _required_text(parent_account_id, "parent_account_id")
            parent = self.connection.execute(
                "SELECT 1 FROM ledger_accounts WHERE account_id = ? AND authority = ?",
                (parent_account_id, authority),
            ).fetchone()
            if parent is None:
                raise LedgerInvariantError("parent account must exist in the same authority domain")

        created_at = _utc_now()
        with _write_transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO ledger_accounts(
                    account_id, parent_account_id, name, account_type, account_role, authority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, parent_account_id, name, account_type, account_role, authority, created_at),
            )
        result = self.get_account(account_id, authority=authority)
        if result is None:
            raise RuntimeError("created ledger account could not be read back")
        return result

    def get_account(self, account_id: str, *, authority: str) -> LedgerAccount | None:
        row = self.connection.execute(
            """
            SELECT account_id, name, account_type, authority, account_role, parent_account_id, created_at
            FROM ledger_accounts WHERE account_id = ? AND authority = ?
            """,
            (account_id, authority),
        ).fetchone()
        if row is None:
            return None
        return LedgerAccount(
            account_id=row[0],
            name=row[1],
            account_type=row[2],
            authority=row[3],
            account_role=row[4],
            parent_account_id=row[5],
            created_at=row[6],
        )

    def post(
        self,
        entry_id: str,
        *,
        authority: str,
        effective_at: str,
        postings: Iterable[LedgerPosting],
        description: str = "",
        settlement_at: str | None = None,
    ) -> LedgerEntry:
        return self._post(
            entry_id,
            authority=authority,
            effective_at=effective_at,
            postings=postings,
            description=description,
            settlement_at=settlement_at,
            reversal_of_entry_id=None,
        )

    def _post(
        self,
        entry_id: str,
        *,
        authority: str,
        effective_at: str,
        postings: Iterable[LedgerPosting],
        description: str,
        settlement_at: str | None,
        reversal_of_entry_id: str | None,
    ) -> LedgerEntry:
        _required_text(entry_id, "entry_id")
        _required_text(effective_at, "effective_at")
        if settlement_at is not None:
            _required_text(settlement_at, "settlement_at")
        _validate_authority(authority)
        if not isinstance(description, str):
            raise LedgerInvariantError("description must be text")
        if reversal_of_entry_id is not None:
            _required_text(reversal_of_entry_id, "reversal_of_entry_id")
            if reversal_of_entry_id == entry_id:
                raise LedgerInvariantError("an entry cannot reverse itself")
        lines = tuple(postings)
        _validate_postings(lines)
        _validate_balances(lines)
        _validate_quantity_balances(lines)
        account_ids = tuple(dict.fromkeys(line.account_id for line in lines))
        placeholders = ", ".join("?" for _ in account_ids)
        accounts = {
            row[0]
            for row in self.connection.execute(
                f"SELECT account_id FROM ledger_accounts WHERE authority = ? AND account_id IN ({placeholders})",
                (authority, *account_ids),
            )
        }
        missing_accounts = set(account_ids) - accounts
        if missing_accounts:
            raise LedgerInvariantError(
                f"accounts must exist in the entry authority domain: {', '.join(sorted(missing_accounts))}"
            )

        recorded_at = _utc_now()
        try:
            with _write_transaction(self.connection):
                if reversal_of_entry_id is not None:
                    original = self.get_entry(reversal_of_entry_id, authority=authority)
                    if original is None:
                        raise LedgerInvariantError(
                            f"unknown posted ledger entry: {reversal_of_entry_id}"
                        )
                    expected_inverse = tuple(
                        LedgerPosting(
                            account_id=line.account_id,
                            currency=line.currency,
                            debit=line.credit,
                            credit=line.debit,
                            instrument_id=line.instrument_id,
                            quantity_delta=-line.quantity_delta if line.quantity_delta is not None else None,
                            lot_id=line.lot_id,
                        )
                        for line in original.postings
                    )
                    if lines != expected_inverse:
                        raise LedgerInvariantError(
                            "reversal postings must exactly invert the referenced entry"
                        )
                self.connection.execute(
                    """
                    INSERT INTO ledger_entries(
                        entry_id, authority, effective_at, settlement_at, recorded_at, description,
                        reversal_of_entry_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'posting')
                    """,
                    (entry_id, authority, effective_at, settlement_at, recorded_at, description, reversal_of_entry_id),
                )
                self.connection.executemany(
                    """
                    INSERT INTO ledger_postings(
                        entry_id, line_number, account_id, authority, currency, debit_amount,
                        credit_amount, instrument_id, quantity_delta, lot_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            entry_id,
                            line_number,
                            line.account_id,
                            authority,
                            line.currency,
                            _amount_text(line.debit),
                            _amount_text(line.credit),
                            line.instrument_id,
                            None if line.quantity_delta is None else _amount_text(line.quantity_delta),
                            line.lot_id,
                        )
                        for line_number, line in enumerate(lines, 1)
                    ),
                )
                cursor = self.connection.execute(
                    """
                    UPDATE ledger_entries SET status = 'posted'
                    WHERE entry_id = ? AND authority = ? AND status = 'posting'
                    """,
                    (entry_id, authority),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("ledger entry did not complete its posting transition")
        except sqlite3.IntegrityError as exc:
            raise LedgerInvariantError(f"ledger entry could not be posted: {exc}") from exc

        result = self.get_entry(entry_id, authority=authority)
        if result is None:
            raise RuntimeError("posted ledger entry could not be read back")
        return result

    def reverse(
        self,
        original_entry_id: str,
        *,
        entry_id: str,
        effective_at: str,
        description: str | None = None,
        authority: str | None = None,
        settlement_at: str | None = None,
    ) -> LedgerEntry:
        original = self.get_entry(original_entry_id, authority=authority)
        if original is None:
            raise LedgerInvariantError(f"unknown posted ledger entry: {original_entry_id}")
        reversal_postings = tuple(
            LedgerPosting(
                account_id=line.account_id,
                currency=line.currency,
                debit=line.credit,
                credit=line.debit,
                instrument_id=line.instrument_id,
                quantity_delta=-line.quantity_delta if line.quantity_delta is not None else None,
                lot_id=line.lot_id,
            )
            for line in original.postings
        )
        return self._post(
            entry_id,
            authority=original.authority,
            effective_at=effective_at,
            postings=reversal_postings,
            description=description if description is not None else f"Reversal of {original_entry_id}",
            settlement_at=original.settlement_at if settlement_at is None else settlement_at,
            reversal_of_entry_id=original_entry_id,
        )

    def post_corporate_action(
        self,
        action: CorporateAction,
        *,
        entry_id: str,
        authority: str,
        known_at: str,
        quantity_before: Decimal,
        lot_id: str | None,
        position_account_id: str,
        counter_account_id: str,
        cash_account_id: str | None = None,
        withholding_account_id: str | None = None,
    ) -> LedgerEntry:
        """Journal one point-in-time action for a replayed position lot.

        ``quantity_before`` must come from this ledger's replay immediately before
        the action. The corporate-action domain object supplies the action factor,
        cash-flow classification and withholding-adjusted amount; no price or
        settlement date is inferred here.
        """

        from etf_cockpit.data.market_adjustments import CorporateAction, CorporateActionType

        _validate_authority(authority)
        _required_text(known_at, "known_at")
        if not isinstance(action, CorporateAction):
            raise LedgerInvariantError("action must be a CorporateAction")
        action.validate()
        if _parse_instant(action.known_at) > _parse_instant(known_at):
            raise LedgerInvariantError("corporate action was not known at the requested cutoff")
        if not isinstance(quantity_before, Decimal) or not quantity_before.is_finite():
            raise LedgerInvariantError("quantity_before must be a finite Decimal")
        if quantity_before == 0:
            raise LedgerInvariantError("corporate action requires a non-zero projected lot quantity")
        if lot_id is not None:
            _required_text(lot_id, "lot_id")
        position = self.get_account(position_account_id, authority=authority)
        if position is None or position.account_role != "position":
            raise LedgerInvariantError("corporate action position account must have the position role")

        description = (
            f"Corporate action {action.action_id} source={action.source_id} "
            f"revision={action.revision} class={action.cash_flow_classification}"
        )
        kind = CorporateActionType(action.action_type)
        postings: tuple[LedgerPosting, ...]
        if kind is CorporateActionType.SPLIT:
            counter = self.get_account(counter_account_id, authority=authority)
            if counter is None or counter.account_role == "position":
                raise LedgerInvariantError("split quantity offset account must not have the position role")
            factor_delta = _decimal_add(Decimal(str(action.quantity_factor)), Decimal("-1"))
            delta = _decimal_product(quantity_before, factor_delta)
            if delta == 0:
                raise LedgerInvariantError("split produced no quantity change")
            postings = (
                LedgerPosting(
                    position_account_id,
                    None,
                    instrument_id=action.instrument_id,
                    quantity_delta=delta,
                    lot_id=lot_id,
                ),
                LedgerPosting(
                    counter_account_id,
                    None,
                    instrument_id=action.instrument_id,
                    quantity_delta=-delta,
                    lot_id=lot_id,
                ),
            )
        elif action.cash_flow_classification in {"investment_income", "security_principal"}:
            if cash_account_id is None:
                raise LedgerInvariantError("cash corporate action requires an explicit cash account")
            if action.currency is None or action.cash_amount <= 0:
                raise LedgerInvariantError("cash corporate action requires amount and currency")
            cash_account = self.get_account(cash_account_id, authority=authority)
            if cash_account is None or cash_account.account_role != "cash":
                raise LedgerInvariantError("corporate-action cash account must have the cash role")
            gross = _decimal_product(Decimal(str(action.cash_amount)), quantity_before)
            net = _decimal_product(Decimal(str(action.net_cash_amount)), quantity_before)
            withheld = _decimal_add(gross, -net)
            if withheld != 0 and withholding_account_id is None:
                raise LedgerInvariantError("withholding requires an explicit tax account")
            postings_list = []
            if net != 0:
                postings_list.append(_signed_money_posting(
                    cash_account_id,
                    action.currency,
                    net,
                    instrument_id=action.instrument_id,
                    lot_id=lot_id,
                ))
            postings_list.append(_signed_money_posting(counter_account_id, action.currency, -gross))
            if withheld != 0:
                postings_list.append(
                    _signed_money_posting(withholding_account_id, action.currency, withheld)
                )
            postings = tuple(postings_list)
        else:
            raise LedgerInvariantError(
                "corporate action requires an explicit instrument/account mapping not supported by this API"
            )

        return self.post(
            entry_id,
            authority=authority,
            effective_at=action.event_at,
            settlement_at=action.payable_at,
            postings=postings,
            description=description,
        )

    def get_entry(self, entry_id: str, *, authority: str | None = None) -> LedgerEntry | None:
        if authority is not None:
            _validate_authority(authority)
            rows = self.connection.execute(
                """
                SELECT entry_id, authority, effective_at, settlement_at, recorded_at, description, reversal_of_entry_id
                FROM ledger_entries
                WHERE entry_id = ? AND authority = ? AND status = 'posted'
                """,
                (entry_id, authority),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT entry_id, authority, effective_at, settlement_at, recorded_at, description, reversal_of_entry_id
                FROM ledger_entries
                WHERE entry_id = ? AND status = 'posted'
                """,
                (entry_id,),
            ).fetchall()
        if len(rows) > 1:
            raise LedgerInvariantError("entry_id is ambiguous; specify its authority")
        row = rows[0] if rows else None
        if row is None:
            return None
        posting_rows = self.connection.execute(
            """
            SELECT account_id, currency, debit_amount, credit_amount, instrument_id, quantity_delta, lot_id
            FROM ledger_postings
            WHERE entry_id = ? AND authority = ?
            ORDER BY line_number
            """,
            (entry_id, row[1]),
        ).fetchall()
        try:
            lines = tuple(
                LedgerPosting(
                    account_id=line[0],
                    currency=line[1],
                    debit=Decimal(line[2]),
                    credit=Decimal(line[3]),
                    instrument_id=line[4],
                    quantity_delta=None if line[5] is None else Decimal(line[5]),
                    lot_id=line[6],
                )
                for line in posting_rows
            )
        except InvalidOperation as exc:
            raise RuntimeError(f"stored ledger entry has an invalid decimal amount: {entry_id}") from exc
        return LedgerEntry(
            entry_id=row[0],
            authority=row[1],
            effective_at=row[2],
            settlement_at=row[3],
            recorded_at=row[4],
            description=row[5],
            reversal_of_entry_id=row[6],
            postings=lines,
        )


def _validate_postings(postings: tuple[LedgerPosting, ...]) -> None:
    if len(postings) < 2:
        raise LedgerInvariantError("a ledger entry requires at least two postings")
    for line in postings:
        if not isinstance(line, LedgerPosting):
            raise LedgerInvariantError("postings must be LedgerPosting values")
        _required_text(line.account_id, "posting account_id")
        if line.currency is not None and (
            not isinstance(line.currency, str) or _CURRENCY_PATTERN.fullmatch(line.currency) is None
        ):
            raise LedgerInvariantError("posting currency must be a three-letter uppercase code")
        if not isinstance(line.debit, Decimal) or not isinstance(line.credit, Decimal):
            raise LedgerInvariantError("posting amounts must be Decimal values")
        if not line.debit.is_finite() or not line.credit.is_finite():
            raise LedgerInvariantError("posting amounts must be finite")
        try:
            if line.debit < 0 or line.credit < 0:
                raise LedgerInvariantError("posting amounts cannot be negative")
            if line.currency is not None and (line.debit > 0) == (line.credit > 0):
                raise LedgerInvariantError("each posting must have exactly one positive side")
            if line.currency is None and (
                line.debit != 0 or line.credit != 0 or line.instrument_id is None
                or line.quantity_delta is None or line.quantity_delta == 0
            ):
                raise LedgerInvariantError("quantity-only postings require instrument and non-zero quantity")
        except InvalidOperation as exc:
            raise LedgerInvariantError("posting amounts must be finite decimals") from exc
        has_quantity_metadata = (
            line.instrument_id is not None or line.quantity_delta is not None or line.lot_id is not None
        )
        if has_quantity_metadata:
            if not isinstance(line.instrument_id, str) or not line.instrument_id.strip():
                raise LedgerInvariantError("quantity metadata requires a non-empty instrument_id")
            if not isinstance(line.quantity_delta, Decimal) or not line.quantity_delta.is_finite():
                raise LedgerInvariantError("quantity_delta must be a finite Decimal")
            if line.currency is None and line.quantity_delta == 0:
                raise LedgerInvariantError("quantity-only postings require a non-zero quantity_delta")
            if line.lot_id is not None and (not isinstance(line.lot_id, str) or not line.lot_id.strip()):
                raise LedgerInvariantError("lot_id must be non-empty when supplied")


def _validate_balances(postings: tuple[LedgerPosting, ...]) -> None:
    by_currency: dict[str, list[LedgerPosting]] = {}
    for line in postings:
        if line.currency is not None:
            by_currency.setdefault(line.currency, []).append(line)
    for currency, lines in by_currency.items():
        amounts = [amount for line in lines for amount in (line.debit, line.credit) if amount]
        min_exponent = min(int(amount.as_tuple().exponent) for amount in amounts)
        max_adjusted = max(amount.adjusted() for amount in amounts)
        precision = max(28, max_adjusted - min_exponent + len(str(len(amounts))) + 2)
        with localcontext() as context:
            context.prec = precision
            debit_total = sum((line.debit for line in lines), Decimal("0"))
            credit_total = sum((line.credit for line in lines), Decimal("0"))
        if debit_total != credit_total:
            raise LedgerInvariantError(f"debits and credits do not balance for {currency}")


def _validate_quantity_balances(postings: tuple[LedgerPosting, ...]) -> None:
    """Balance each entry by instrument/lot; ``lot_id=None`` stays its own bucket."""

    by_position: dict[tuple[str, str | None], list[Decimal]] = {}
    for line in postings:
        if line.instrument_id is not None and line.quantity_delta is not None:
            by_position.setdefault((line.instrument_id, line.lot_id), []).append(line.quantity_delta)
    for (instrument_id, lot_id), quantities in by_position.items():
        nonzero = tuple(quantity for quantity in quantities if quantity)
        if not nonzero:
            continue
        min_exponent = min(int(quantity.as_tuple().exponent) for quantity in nonzero)
        max_adjusted = max(quantity.adjusted() for quantity in nonzero)
        precision = max(28, max_adjusted - min_exponent + len(str(len(nonzero))) + 2)
        with localcontext() as context:
            context.prec = precision
            total = sum(quantities, Decimal("0"))
        if total != 0:
            raise LedgerInvariantError(
                f"quantity deltas do not balance for instrument {instrument_id!r} lot {lot_id!r}"
            )


def _amount_text(amount: Decimal) -> str:
    return "0" if amount == 0 else format(amount, "f")


def _decimal_add(left: Decimal, right: Decimal) -> Decimal:
    nonzero = tuple(value for value in (left, right) if value)
    if not nonzero:
        return Decimal("0")
    min_exponent = min(int(value.as_tuple().exponent) for value in nonzero)
    max_adjusted = max(value.adjusted() for value in nonzero)
    precision = max(28, max_adjusted - min_exponent + 4)
    with localcontext() as context:
        context.prec = precision
        return left + right


def _decimal_product(left: Decimal, right: Decimal) -> Decimal:
    precision = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
    with localcontext() as context:
        context.prec = precision
        return left * right


def _validate_authority(authority: str) -> None:
    if authority not in AUTHORITIES:
        raise LedgerInvariantError("authority must be 'paper' or 'broker'")


def _required_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LedgerInvariantError(f"{field} must be non-empty text")


def _parse_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise LedgerInvariantError("timestamps must be ISO-8601 values") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _signed_money_posting(
    account_id: str | None,
    currency: str,
    debit_balance: Decimal,
    *,
    instrument_id: str | None = None,
    lot_id: str | None = None,
) -> LedgerPosting:
    if account_id is None:
        raise LedgerInvariantError("money posting requires an explicit account")
    _required_text(account_id, "posting account_id")
    if debit_balance == 0:
        raise LedgerInvariantError("zero-valued money postings are not journal lines")
    if debit_balance > 0:
        return LedgerPosting(
            account_id,
            currency,
            debit=debit_balance,
            instrument_id=instrument_id,
            quantity_delta=Decimal("0") if instrument_id is not None else None,
            lot_id=lot_id,
        )
    return LedgerPosting(
        account_id,
        currency,
        credit=-debit_balance,
        instrument_id=instrument_id,
        quantity_delta=Decimal("0") if instrument_id is not None else None,
        lot_id=lot_id,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@contextmanager
def _write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    nested = connection.in_transaction
    if nested:
        connection.execute("SAVEPOINT ledger_write")
    else:
        connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if nested:
            connection.execute("ROLLBACK TO ledger_write")
            connection.execute("RELEASE ledger_write")
        else:
            connection.rollback()
        raise
    else:
        if nested:
            connection.execute("RELEASE ledger_write")
        else:
            connection.commit()
