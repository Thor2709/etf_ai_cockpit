"""Deterministic point-in-time projections over the canonical double-entry ledger.

PortfolioImportStore remains a legacy ingestion/reconciliation path until the
separately scoped slice-3 adapter wiring; it is not a second ledger projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re
import sqlite3

from etf_cockpit.data.market_adjustments import FXObservationStore, derive_fx_cross


_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


class LedgerReplayError(ValueError):
    """Raised when replay cutoffs are invalid or journal facts are malformed."""


@dataclass(frozen=True)
class PositionBalance:
    account_id: str
    instrument_id: str
    lot_id: str | None
    quantity: Decimal
    missing_lot_identity: bool


@dataclass(frozen=True)
class CashBalance:
    account_id: str
    currency: str
    book_balance: Decimal
    settled_balance: Decimal
    pending_settlement_balance: Decimal
    unknown_settlement_balance: Decimal


@dataclass(frozen=True)
class TrialBalanceRow:
    account_id: str
    currency: str
    debit_balance: Decimal
    credit_balance: Decimal


@dataclass(frozen=True)
class FXCashConversion:
    account_id: str
    currency: str
    base_currency: str
    local_book_balance: Decimal
    base_book_balance: Decimal | None
    status: str
    rate: Decimal | None
    observation_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    valid_at: str | None
    known_at: str | None
    execution_allowed: bool = False


@dataclass(frozen=True)
class LedgerReplay:
    authority: str
    as_of: str
    known_at: str
    positions: tuple[PositionBalance, ...]
    cash: tuple[CashBalance, ...]
    trial_balance: tuple[TrialBalanceRow, ...]
    unpriced_instruments: tuple[str, ...]
    missing_lot_identity: tuple[tuple[str, str], ...]
    missing_position_instrument_lines: tuple[tuple[str, int], ...]
    unknown_settlement_lines: tuple[tuple[str, int], ...]
    timing_uncertainty_entry_ids: tuple[str, ...]
    fx_conversions: tuple[FXCashConversion, ...]
    trial_balance_totals: tuple[tuple[str, Decimal, Decimal], ...]
    trial_balance_balanced: bool
    execution_allowed: bool = False


def replay_ledger(
    connection: sqlite3.Connection,
    *,
    authority: str,
    as_of: str,
    known_at: str | None = None,
    fx_store: FXObservationStore | None = None,
    base_currency: str | None = None,
) -> LedgerReplay:
    """Replay posted facts visible by both effective and knowledge cutoffs.

    Missing lot identity, effective/recorded timing, settlement timing, prices,
    and FX are retained as explicit unknowns. FX uses only the requested direct
    dated pair; this function never inverts or crosses rates.
    """

    if authority not in {"paper", "broker"}:
        raise LedgerReplayError("authority must be 'paper' or 'broker'")
    as_of_instant = _instant(as_of, "as_of")
    knowledge_text = as_of if known_at is None else known_at
    known_instant = _instant(knowledge_text, "known_at")
    if base_currency is not None and _CURRENCY_PATTERN.fullmatch(base_currency) is None:
        raise LedgerReplayError("base_currency must be a three-letter uppercase code")
    rows = connection.execute(
        """
        SELECT entry.entry_id, entry.effective_at, entry.recorded_at, entry.settlement_at,
               posting.line_number, posting.account_id, account.account_role,
               posting.currency, posting.debit_amount, posting.credit_amount,
               posting.instrument_id, posting.quantity_delta, posting.lot_id
        FROM ledger_entries AS entry
        JOIN ledger_postings AS posting
          ON posting.entry_id = entry.entry_id AND posting.authority = entry.authority
        JOIN ledger_accounts AS account
          ON account.account_id = posting.account_id AND account.authority = posting.authority
        WHERE entry.authority = ? AND entry.status = 'posted'
        """,
        (authority,),
    ).fetchall()

    included: list[tuple[datetime, str, int, sqlite3.Row]] = []
    timing_unknown: set[str] = set()
    for row in rows:
        try:
            effective = _instant(row[1], "effective_at")
            recorded = _instant(row[2], "recorded_at")
        except LedgerReplayError:
            timing_unknown.add(row[0])
            continue
        if effective <= as_of_instant and recorded <= known_instant:
            included.append((effective, row[0], int(row[4]), row))
    included.sort(key=lambda item: (item[0], item[1], item[2]))

    position_totals: dict[tuple[str, str, str | None], Decimal] = {}
    missing_position_instrument_lines: set[tuple[str, int]] = set()
    cash_totals: dict[tuple[str, str], dict[str, Decimal]] = {}
    trial_totals: dict[tuple[str, str], list[Decimal]] = {}
    settlement_unknown_lines: set[tuple[str, int]] = set()
    for _effective, entry_id, line_number, row in included:
        account_id = row[5]
        role = row[6]
        currency = row[7]
        debit = _decimal(row[8], "debit_amount")
        credit = _decimal(row[9], "credit_amount")
        instrument_id = row[10]
        quantity = None if row[11] is None else _signed_decimal(row[11], "quantity_delta")
        lot_id = row[12]

        if currency is not None:
            trial = trial_totals.setdefault((account_id, currency), [Decimal("0"), Decimal("0")])
            trial[0] = _add_exact(trial[0], debit)
            trial[1] = _add_exact(trial[1], credit)
        if role == "position":
            if instrument_id is not None and quantity is not None:
                position_key = (account_id, instrument_id, lot_id)
                position_totals[position_key] = _add_exact(
                    position_totals.get(position_key, Decimal("0")), quantity
                )
            elif currency is not None:
                missing_position_instrument_lines.add((entry_id, line_number))
        if role == "cash" and currency is not None:
            cash_key = (account_id, currency)
            cash_values = cash_totals.setdefault(
                cash_key,
                {
                    "book": Decimal("0"),
                    "settled": Decimal("0"),
                    "pending": Decimal("0"),
                    "unknown": Decimal("0"),
                },
            )
            movement = debit - credit
            cash_values["book"] = _add_exact(cash_values["book"], movement)
            settlement_at = row[3]
            if settlement_at is None:
                cash_values["unknown"] = _add_exact(cash_values["unknown"], movement)
                settlement_unknown_lines.add((entry_id, line_number))
            else:
                try:
                    settlement = _instant(settlement_at, "settlement_at")
                except LedgerReplayError:
                    cash_values["unknown"] = _add_exact(cash_values["unknown"], movement)
                    settlement_unknown_lines.add((entry_id, line_number))
                    timing_unknown.add(entry_id)
                else:
                    bucket = "settled" if settlement <= as_of_instant else "pending"
                    cash_values[bucket] = _add_exact(cash_values[bucket], movement)

    positions = tuple(
        PositionBalance(account_id, instrument_id, lot_id, quantity, lot_id is None)
        for (account_id, instrument_id, lot_id), quantity in sorted(position_totals.items())
        if quantity != 0
    )
    cash = tuple(
        CashBalance(account_id, currency, values["book"], values["settled"], values["pending"], values["unknown"])
        for (account_id, currency), values in sorted(cash_totals.items())
    )
    trial_rows = tuple(
        _trial_balance_row(account_id, currency, debits, credits)
        for (account_id, currency), (debits, credits) in sorted(trial_totals.items())
    )
    totals_by_currency: dict[str, list[Decimal]] = {}
    for (_account_id, currency), (debits, credits) in trial_totals.items():
        currency_totals = totals_by_currency.setdefault(currency, [Decimal("0"), Decimal("0")])
        currency_totals[0] = _add_exact(currency_totals[0], debits)
        currency_totals[1] = _add_exact(currency_totals[1], credits)
    trial_totals_rows = tuple(
        (currency, values[0], values[1]) for currency, values in sorted(totals_by_currency.items())
    )
    balanced = all(debits == credits for _currency, debits, credits in trial_totals_rows)
    missing_lots = tuple(
        sorted((position.account_id, position.instrument_id) for position in positions if position.lot_id is None)
    )
    conversions = _convert_cash(
        cash,
        fx_store=fx_store,
        base_currency=base_currency,
        as_of=as_of,
        known_at=knowledge_text,
    )
    return LedgerReplay(
        authority=authority,
        as_of=as_of,
        known_at=knowledge_text,
        positions=positions,
        cash=cash,
        trial_balance=trial_rows,
        unpriced_instruments=tuple(sorted({position.instrument_id for position in positions})),
        missing_lot_identity=missing_lots,
        missing_position_instrument_lines=tuple(sorted(missing_position_instrument_lines)),
        unknown_settlement_lines=tuple(sorted(settlement_unknown_lines)),
        timing_uncertainty_entry_ids=tuple(sorted(timing_unknown)),
        fx_conversions=conversions,
        trial_balance_totals=trial_totals_rows,
        trial_balance_balanced=balanced,
        execution_allowed=False,
    )


def _convert_cash(
    balances: tuple[CashBalance, ...],
    *,
    fx_store: FXObservationStore | None,
    base_currency: str | None,
    as_of: str,
    known_at: str,
) -> tuple[FXCashConversion, ...]:
    if base_currency is None:
        return ()
    converted: list[FXCashConversion] = []
    for balance in balances:
        if balance.currency == base_currency:
            converted.append(
                FXCashConversion(
                    balance.account_id,
                    balance.currency,
                    base_currency,
                    balance.book_balance,
                    balance.book_balance,
                    "identity",
                    Decimal("1"),
                    (),
                    (),
                    as_of,
                    known_at,
                )
            )
            continue
        observations = () if fx_store is None else fx_store.as_of(
            balance.currency,
            base_currency,
            valid_at=as_of,
            known_at=known_at,
        )
        if not observations:
            converted.append(
                FXCashConversion(
                    balance.account_id, balance.currency, base_currency, balance.book_balance,
                    None, "missing", None, (), (), None, None,
                )
            )
            continue
        resolution = derive_fx_cross(
            observations,
            balance.currency,
            base_currency,
            as_of=as_of,
            decision_time=known_at,
        )
        if not resolution.available or resolution.rate is None:
            status = "conflicted" if resolution.status == "quarantined" else "missing"
            converted.append(
                FXCashConversion(
                    balance.account_id,
                    balance.currency,
                    base_currency,
                    balance.book_balance,
                    None,
                    status,
                    None,
                    (),
                    (),
                    None,
                    None,
                )
            )
            continue
        rate = _signed_decimal(str(resolution.rate), "FX rate")
        selected_sources = set(resolution.source_ids)
        selected = tuple(item for item in observations if item.source_id in selected_sources)
        converted.append(
            FXCashConversion(
                balance.account_id,
                balance.currency,
                base_currency,
                balance.book_balance,
                _multiply_exact(balance.book_balance, rate),
                "available",
                rate,
                tuple(sorted({item.observation_id for item in selected})),
                tuple(sorted(selected_sources)),
                max((item.valid_at for item in selected), default=None),
                max((item.known_at for item in selected), default=None),
            )
        )
    return tuple(converted)


def _trial_balance_row(account_id: str, currency: str, debits: Decimal, credits: Decimal) -> TrialBalanceRow:
    net = _add_exact(debits, -credits)
    return TrialBalanceRow(account_id, currency, max(net, Decimal("0")), max(-net, Decimal("0")))


def _add_exact(left: Decimal, right: Decimal) -> Decimal:
    nonzero = tuple(value for value in (left, right) if value)
    if not nonzero:
        return Decimal("0")
    min_exponent = min(int(value.as_tuple().exponent) for value in nonzero)
    max_adjusted = max(value.adjusted() for value in nonzero)
    precision = max(28, max_adjusted - min_exponent + 4)
    with localcontext() as context:
        context.prec = precision
        return left + right


def _multiply_exact(left: Decimal, right: Decimal) -> Decimal:
    precision = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
    with localcontext() as context:
        context.prec = precision
        return left * right


def _instant(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LedgerReplayError(f"{field} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LedgerReplayError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decimal(value: object, field: str) -> Decimal:
    amount = _signed_decimal(value, field)
    if amount < 0:
        raise LedgerReplayError(f"stored {field} cannot be negative")
    return amount


def _signed_decimal(value: object, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LedgerReplayError(f"stored {field} is not a decimal") from exc
    if not amount.is_finite():
        raise LedgerReplayError(f"stored {field} must be finite")
    return amount


__all__ = [
    "CashBalance",
    "FXCashConversion",
    "LedgerReplay",
    "LedgerReplayError",
    "PositionBalance",
    "TrialBalanceRow",
    "replay_ledger",
]
