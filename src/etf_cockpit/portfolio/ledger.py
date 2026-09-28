from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re
import sqlite3
from collections.abc import Iterable, Iterator


ACCOUNT_TYPES = frozenset({"asset", "liability", "equity", "income", "expense"})
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
    parent_account_id: str | None
    created_at: str


@dataclass(frozen=True)
class LedgerPosting:
    account_id: str
    currency: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    authority: str
    effective_at: str
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
    ) -> LedgerAccount:
        _required_text(account_id, "account_id")
        _required_text(name, "name")
        _validate_authority(authority)
        if account_type not in ACCOUNT_TYPES:
            raise LedgerInvariantError(f"unsupported account type: {account_type!r}")
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
                    account_id, parent_account_id, name, account_type, authority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (account_id, parent_account_id, name, account_type, authority, created_at),
            )
        result = self.get_account(account_id, authority=authority)
        if result is None:
            raise RuntimeError("created ledger account could not be read back")
        return result

    def get_account(self, account_id: str, *, authority: str) -> LedgerAccount | None:
        row = self.connection.execute(
            """
            SELECT account_id, name, account_type, authority, parent_account_id, created_at
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
            parent_account_id=row[4],
            created_at=row[5],
        )

    def post(
        self,
        entry_id: str,
        *,
        authority: str,
        effective_at: str,
        postings: Iterable[LedgerPosting],
        description: str = "",
    ) -> LedgerEntry:
        return self._post(
            entry_id,
            authority=authority,
            effective_at=effective_at,
            postings=postings,
            description=description,
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
        reversal_of_entry_id: str | None,
    ) -> LedgerEntry:
        _required_text(entry_id, "entry_id")
        _required_text(effective_at, "effective_at")
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
                        entry_id, authority, effective_at, recorded_at, description,
                        reversal_of_entry_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'posting')
                    """,
                    (entry_id, authority, effective_at, recorded_at, description, reversal_of_entry_id),
                )
                self.connection.executemany(
                    """
                    INSERT INTO ledger_postings(
                        entry_id, line_number, account_id, authority, currency, debit_amount, credit_amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
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
            )
            for line in original.postings
        )
        return self._post(
            entry_id,
            authority=original.authority,
            effective_at=effective_at,
            postings=reversal_postings,
            description=description if description is not None else f"Reversal of {original_entry_id}",
            reversal_of_entry_id=original_entry_id,
        )

    def get_entry(self, entry_id: str, *, authority: str | None = None) -> LedgerEntry | None:
        if authority is not None:
            _validate_authority(authority)
            rows = self.connection.execute(
                """
                SELECT entry_id, authority, effective_at, recorded_at, description, reversal_of_entry_id
                FROM ledger_entries
                WHERE entry_id = ? AND authority = ? AND status = 'posted'
                """,
                (entry_id, authority),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT entry_id, authority, effective_at, recorded_at, description, reversal_of_entry_id
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
            SELECT account_id, currency, debit_amount, credit_amount
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
                )
                for line in posting_rows
            )
        except InvalidOperation as exc:
            raise RuntimeError(f"stored ledger entry has an invalid decimal amount: {entry_id}") from exc
        return LedgerEntry(
            entry_id=row[0],
            authority=row[1],
            effective_at=row[2],
            recorded_at=row[3],
            description=row[4],
            reversal_of_entry_id=row[5],
            postings=lines,
        )


def _validate_postings(postings: tuple[LedgerPosting, ...]) -> None:
    if len(postings) < 2:
        raise LedgerInvariantError("a ledger entry requires at least two postings")
    for line in postings:
        if not isinstance(line, LedgerPosting):
            raise LedgerInvariantError("postings must be LedgerPosting values")
        _required_text(line.account_id, "posting account_id")
        if not isinstance(line.currency, str) or _CURRENCY_PATTERN.fullmatch(line.currency) is None:
            raise LedgerInvariantError("posting currency must be a three-letter uppercase code")
        if not isinstance(line.debit, Decimal) or not isinstance(line.credit, Decimal):
            raise LedgerInvariantError("posting amounts must be Decimal values")
        if not line.debit.is_finite() or not line.credit.is_finite():
            raise LedgerInvariantError("posting amounts must be finite")
        try:
            if line.debit < 0 or line.credit < 0:
                raise LedgerInvariantError("posting amounts cannot be negative")
            if (line.debit > 0) == (line.credit > 0):
                raise LedgerInvariantError("each posting must have exactly one positive side")
        except InvalidOperation as exc:
            raise LedgerInvariantError("posting amounts must be finite decimals") from exc


def _validate_balances(postings: tuple[LedgerPosting, ...]) -> None:
    by_currency: dict[str, list[LedgerPosting]] = {}
    for line in postings:
        by_currency.setdefault(line.currency, []).append(line)
    for currency, lines in by_currency.items():
        amounts = [amount for line in lines for amount in (line.debit, line.credit) if amount]
        min_exponent = min(amount.as_tuple().exponent for amount in amounts)
        max_adjusted = max(amount.adjusted() for amount in amounts)
        precision = max(28, max_adjusted - min_exponent + len(str(len(amounts))) + 2)
        with localcontext() as context:
            context.prec = precision
            debit_total = sum((line.debit for line in lines), Decimal("0"))
            credit_total = sum((line.credit for line in lines), Decimal("0"))
        if debit_total != credit_total:
            raise LedgerInvariantError(f"debits and credits do not balance for {currency}")


def _amount_text(amount: Decimal) -> str:
    return "0" if amount == 0 else format(amount, "f")


def _validate_authority(authority: str) -> None:
    if authority not in AUTHORITIES:
        raise LedgerInvariantError("authority must be 'paper' or 'broker'")


def _required_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LedgerInvariantError(f"{field} must be non-empty text")


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
