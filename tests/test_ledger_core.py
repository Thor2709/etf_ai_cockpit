from decimal import Decimal
import sqlite3

import pytest

from etf_cockpit.data.local_storage import STORAGE_SCHEMA_VERSION, TransactionalStore
from etf_cockpit.portfolio.ledger import Ledger, LedgerInvariantError, LedgerPosting


def _accounts(ledger: Ledger, *, authority: str = "paper") -> tuple[str, str]:
    ledger.create_account("cash", name="Cash", account_type="asset", authority=authority)
    ledger.create_account("equity", name="Equity", account_type="equity", authority=authority)
    return "cash", "equity"


def test_ledger_transaction_balances_debits_and_credits(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        cash, equity = _accounts(ledger)

        entry = ledger.post(
            "opening-funds",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting(cash, "EUR", debit=Decimal("12.30")),
                LedgerPosting(equity, "EUR", credit=Decimal("12.30")),
                LedgerPosting(cash, "USD", debit=Decimal("5")),
                LedgerPosting(equity, "USD", credit=Decimal("5.00")),
            ),
        )

        assert entry.entry_id == "opening-funds"
        assert entry.postings[0].debit == Decimal("12.30")
        assert entry.postings[1].credit == Decimal("12.30")
        with pytest.raises(LedgerInvariantError, match="do not balance for EUR"):
            ledger.post(
                "unbalanced-currencies",
                authority="paper",
                effective_at="2026-09-28T12:01:00Z",
                postings=(
                    LedgerPosting(cash, "EUR", debit=Decimal("5")),
                    LedgerPosting(equity, "USD", credit=Decimal("5")),
                ),
            )


def test_ledger_reversing_entry_preserves_immutable_audit(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        cash, equity = _accounts(ledger)
        original = ledger.post(
            "deposit",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting(cash, "EUR", debit=Decimal("40.25")),
                LedgerPosting(equity, "EUR", credit=Decimal("40.25")),
            ),
            description="Initial deposit",
        )

        reversal = ledger.reverse(
            original.entry_id,
            entry_id="deposit-reversal",
            effective_at="2026-09-28T12:05:00Z",
        )

        assert ledger.get_entry(original.entry_id) == original
        assert reversal.reversal_of_entry_id == original.entry_id
        assert tuple((line.debit, line.credit) for line in reversal.postings) == (
            (original.postings[0].credit, original.postings[0].debit),
            (original.postings[1].credit, original.postings[1].debit),
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.connection.execute(
                "UPDATE ledger_postings SET debit_amount = '0' WHERE entry_id = ? AND line_number = 1",
                (original.entry_id,),
            )


def test_ledger_v5_persists_account_hierarchy_and_authority(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        assert store.integrity().schema_version == STORAGE_SCHEMA_VERSION == 5
        assert store.connection.execute(
            "SELECT name FROM schema_migrations WHERE version = 5"
        ).fetchone()[0] == "double_entry_ledger_v1"
        ledger.create_account("paper-assets", name="Assets", account_type="asset", authority="paper")
        ledger.create_account(
            "paper-cash",
            name="Cash",
            account_type="asset",
            authority="paper",
            parent_account_id="paper-assets",
        )
        ledger.create_account("broker-assets", name="Assets", account_type="asset", authority="broker")
        ledger.create_account("broker-equity", name="Equity", account_type="equity", authority="broker")
        entry = ledger.post(
            "broker-entry",
            authority="broker",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting("broker-assets", "EUR", debit=Decimal("7")),
                LedgerPosting("broker-equity", "EUR", credit=Decimal("7")),
            ),
        )
        with pytest.raises(LedgerInvariantError, match="authority domain"):
            ledger.post(
                "cross-authority-entry",
                authority="broker",
                effective_at="2026-09-28T12:01:00Z",
                postings=(
                    LedgerPosting("paper-cash", "EUR", debit=Decimal("1")),
                    LedgerPosting("broker-equity", "EUR", credit=Decimal("1")),
                ),
            )

    with TransactionalStore(tmp_path) as reopened:
        ledger = Ledger(reopened.connection)
        assert ledger.get_account("paper-cash", authority="paper").parent_account_id == "paper-assets"
        assert ledger.get_account("paper-cash", authority="broker") is None
        assert ledger.get_entry("broker-entry").entry_id == entry.entry_id
