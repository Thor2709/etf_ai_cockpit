from decimal import Decimal
import sqlite3

import pytest

from etf_cockpit.data.local_storage import (
    STORAGE_SCHEMA_VERSION,
    TransactionalStore,
    _migration_v1,
    _migration_v2,
    _migration_v3,
    _migration_v4,
    _migration_v5,
    _migration_v6,
    connect_storage,
)
from etf_cockpit.data.market_adjustments import (
    CorporateAction,
    CorporateActionStore,
    FXObservation,
    FXObservationStore,
)
from etf_cockpit.portfolio.ledger import Ledger, LedgerInvariantError, LedgerPosting
from etf_cockpit.portfolio.ledger_projection import replay_ledger


def _accounts(ledger: Ledger, *, authority: str = "paper") -> tuple[str, str]:
    ledger.create_account("cash", name="Cash", account_type="asset", authority=authority, account_role="cash")
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
        with pytest.raises(LedgerInvariantError, match="quantity deltas do not balance"):
            ledger.post(
                "unbalanced-lot-quantities",
                authority="paper",
                effective_at="2026-09-28T12:02:00Z",
                postings=(
                    LedgerPosting(
                        cash,
                        "EUR",
                        debit=Decimal("1"),
                        instrument_id="AAA",
                        quantity_delta=Decimal("1"),
                        lot_id="lot-a",
                    ),
                    LedgerPosting(
                        equity,
                        "EUR",
                        credit=Decimal("1"),
                        instrument_id="AAA",
                        quantity_delta=Decimal("-1"),
                        lot_id="lot-b",
                    ),
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
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.connection.execute(
                "UPDATE ledger_entries SET settlement_at = '2026-09-29' WHERE entry_id = ?",
                (original.entry_id,),
            )


def test_ledger_v5_persists_account_hierarchy_and_authority(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        assert store.integrity().schema_version == STORAGE_SCHEMA_VERSION == 7
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


def test_direct_sql_cannot_persist_posted_unbalanced_or_invalid_amounts(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        cash, equity = _accounts(ledger)
        connection = store.connection

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO ledger_entries(
                    entry_id, authority, effective_at, recorded_at, description,
                    reversal_of_entry_id, status
                ) VALUES ('empty-posted', 'paper', '2026-09-28', '2026-09-28', '', NULL, 'posted')
                """
            )

        connection.execute(
            """
            INSERT INTO ledger_entries(
                entry_id, authority, effective_at, recorded_at, description,
                reversal_of_entry_id, status
            ) VALUES ('unbalanced-quantity', 'paper', '2026-09-28', '2026-09-28', '', NULL, 'posting')
            """
        )
        connection.executemany(
            """
            INSERT INTO ledger_postings(
                entry_id, line_number, account_id, authority, currency, debit_amount,
                credit_amount, instrument_id, quantity_delta, lot_id
            ) VALUES ('unbalanced-quantity', ?, ?, 'paper', 'EUR', ?, ?, 'AAA', ?, ?)
            """,
            (
                (1, cash, "1", "0", "1", "lot-a"),
                (2, equity, "0", "1", "-1", "lot-b"),
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="balance by currency and quantity"):
            connection.execute(
                "UPDATE ledger_entries SET status = 'posted' WHERE entry_id = 'unbalanced-quantity'"
            )

        for entry_id, invalid_amount in (
            ("invalid-text", "not-a-decimal"),
            ("negative-amount", "-0.01"),
            ("nan-amount", "NaN"),
            ("infinite-amount", "Infinity"),
        ):
            connection.execute(
                """
                INSERT INTO ledger_entries(
                    entry_id, authority, effective_at, recorded_at, description,
                    reversal_of_entry_id, status
                ) VALUES (?, 'paper', '2026-09-28', '2026-09-28', '', NULL, 'posting')
                """,
                (entry_id,),
            )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO ledger_postings(
                        entry_id, line_number, account_id, authority, currency, debit_amount, credit_amount
                    ) VALUES (?, 1, 'cash', 'paper', 'EUR', ?, '0')
                    """,
                    (entry_id, invalid_amount),
                )

        connection.execute(
            """
            INSERT INTO ledger_entries(
                entry_id, authority, effective_at, recorded_at, description,
                reversal_of_entry_id, status
            ) VALUES ('unbalanced-posting', 'paper', '2026-09-28', '2026-09-28', '', NULL, 'posting')
            """
        )
        connection.executemany(
            """
            INSERT INTO ledger_postings(
                entry_id, line_number, account_id, authority, currency, debit_amount, credit_amount
            ) VALUES ('unbalanced-posting', ?, ?, 'paper', 'EUR', ?, ?)
            """,
            ((1, cash, "1.00", "0"), (2, equity, "0", "0.99")),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE ledger_entries SET status = 'posted'
                WHERE entry_id = 'unbalanced-posting' AND authority = 'paper'
                """
            )


def test_post_cannot_claim_arbitrary_reversal_linkage(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        cash, equity = _accounts(ledger)
        original = ledger.post(
            "original",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting(cash, "EUR", debit=Decimal("10")),
                LedgerPosting(equity, "EUR", credit=Decimal("10")),
            ),
        )

        with pytest.raises(TypeError):
            ledger.post(
                "false-reversal",
                authority="paper",
                effective_at="2026-09-28T12:01:00Z",
                postings=(
                    LedgerPosting(cash, "EUR", debit=Decimal("10")),
                    LedgerPosting(equity, "EUR", credit=Decimal("10")),
                ),
                reversal_of_entry_id=original.entry_id,
            )
        assert ledger.get_entry("false-reversal", authority="paper") is None


def test_account_and_entry_identifiers_are_scoped_by_authority(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        cash, equity = _accounts(ledger, authority="paper")
        ledger.create_account("cash", name="Broker cash", account_type="asset", authority="broker")
        ledger.create_account("equity", name="Broker equity", account_type="equity", authority="broker")

        paper_entry = ledger.post(
            "shared-entry",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting(cash, "EUR", debit=Decimal("5")),
                LedgerPosting(equity, "EUR", credit=Decimal("5")),
            ),
        )
        broker_entry = ledger.post(
            "shared-entry",
            authority="broker",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting("cash", "EUR", debit=Decimal("7")),
                LedgerPosting("equity", "EUR", credit=Decimal("7")),
            ),
        )

        assert ledger.get_account("cash", authority="paper").name == "Cash"
        assert ledger.get_account("cash", authority="broker").name == "Broker cash"
        assert ledger.get_entry("shared-entry", authority="paper") == paper_entry
        assert ledger.get_entry("shared-entry", authority="broker") == broker_entry
        with pytest.raises(LedgerInvariantError, match="ambiguous"):
            ledger.get_entry("shared-entry")


def test_v7_migrates_v6_ledger_facts_without_rewriting_them(tmp_path):
    connection = connect_storage(tmp_path)
    connection.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    migrations = (_migration_v1, _migration_v2, _migration_v3, _migration_v4, _migration_v5, _migration_v6)
    connection.execute("BEGIN IMMEDIATE")
    for version, migration in enumerate(migrations, 1):
        migration(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
            (version, f"v{version}", "2026-09-28T12:00:00Z"),
        )
    connection.execute(
        "INSERT INTO ledger_accounts(account_id, name, account_type, authority, created_at) "
        "VALUES ('cash', 'Cash', 'asset', 'paper', '2026-09-28T12:00:00Z')"
    )
    connection.execute(
        "INSERT INTO ledger_accounts(account_id, name, account_type, authority, created_at) "
        "VALUES ('equity', 'Equity', 'equity', 'paper', '2026-09-28T12:00:00Z')"
    )
    connection.execute(
        "INSERT INTO ledger_entries(entry_id, authority, effective_at, recorded_at, description, status) "
        "VALUES ('legacy-entry', 'paper', '2026-09-28T12:00:00Z', '2026-09-28T12:00:00Z', 'legacy', 'posting')"
    )
    connection.executemany(
        "INSERT INTO ledger_postings(entry_id, line_number, account_id, authority, currency, debit_amount, credit_amount) "
        "VALUES ('legacy-entry', ?, ?, 'paper', 'EUR', ?, ?)",
        ((1, "cash", "25.50", "0"), (2, "equity", "0", "25.50")),
    )
    connection.execute("UPDATE ledger_entries SET status = 'posted' WHERE entry_id = 'legacy-entry'")
    connection.commit()
    connection.close()

    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        assert store.integrity().schema_version == 7
        # V6 has no role evidence: preserve it as general instead of inferring cash from its name.
        assert ledger.get_account("cash", authority="paper").account_role == "general"
        entry = ledger.get_entry("legacy-entry", authority="paper")
        assert entry is not None
        assert entry.settlement_at is None
        assert entry.postings[0] == LedgerPosting("cash", "EUR", debit=Decimal("25.50"))


def test_replay_positions_settlement_trial_balance_and_fx_are_point_in_time(tmp_path):
    with TransactionalStore(tmp_path / "ledger") as store:
        ledger = Ledger(store.connection)
        ledger.create_account(
            "positions", name="Positions", account_type="asset", authority="paper", account_role="position"
        )
        ledger.create_account("offset", name="Position offset", account_type="equity", authority="paper")
        ledger.create_account(
            "cash-eur", name="EUR Cash", account_type="asset", authority="paper", account_role="cash"
        )
        ledger.create_account("income", name="Income", account_type="income", authority="paper")
        ledger.create_account("tax", name="Withholding", account_type="expense", authority="paper")
        ledger.post(
            "opening-lot",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting("positions", None, instrument_id="AAA", quantity_delta=Decimal("10"), lot_id="lot-1"),
                LedgerPosting("offset", None, instrument_id="AAA", quantity_delta=Decimal("-10"), lot_id="lot-1"),
            ),
        )
        ledger.create_account("equity", name="Equity", account_type="equity", authority="paper")
        ledger.post(
            "opening-cash",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            settlement_at="2026-10-02T12:00:00Z",
            postings=(
                LedgerPosting("cash-eur", "EUR", debit=Decimal("100")),
                LedgerPosting("equity", "EUR", credit=Decimal("100")),
            ),
        )
        with pytest.raises(LedgerInvariantError, match="quantity-only postings"):
            ledger.post(
                "invalid-empty-line",
                authority="paper",
                effective_at="2026-09-28T12:01:00Z",
                postings=(
                    LedgerPosting("positions", None),
                    LedgerPosting("offset", "EUR", debit=Decimal("1")),
                ),
            )

        with FXObservationStore(tmp_path / "fx") as fx_store:
            fx_store.append(
                FXObservation(
                    observation_id="eur-usd-1",
                    base_currency="EUR",
                    quote_currency="USD",
                    rate=Decimal("1.10"),
                    valid_at="2026-10-01T00:00:00Z",
                    published_at="2026-10-01T08:00:00Z",
                    retrieved_at="2026-10-01T08:01:00Z",
                    known_at="2026-10-01T08:01:00Z",
                    revision=1,
                    source="official",
                    source_id="central-bank",
                    source_checksum="a" * 64,
                )
            )
            replay = replay_ledger(
                store.connection,
                authority="paper",
                as_of="2026-10-01T23:59:59Z",
                known_at="2026-10-02T00:00:00Z",
                fx_store=fx_store,
                base_currency="USD",
            )
        assert replay.execution_allowed is False
        assert (replay.positions[0].instrument_id, replay.positions[0].quantity, replay.positions[0].lot_id) == (
            "AAA", Decimal("10"), "lot-1"
        )
        assert replay.unpriced_instruments == ("AAA",)
        assert replay.cash[0].book_balance == Decimal("100")
        assert replay.cash[0].settled_balance == 0
        assert replay.cash[0].pending_settlement_balance == Decimal("100")
        assert replay.cash[0].unknown_settlement_balance == 0
        assert replay.trial_balance_balanced is True
        assert replay.trial_balance_totals == (("EUR", Decimal("100"), Decimal("100")),)
        assert replay.fx_conversions[0].status == "available"
        assert replay.fx_conversions[0].base_book_balance == Decimal("110.0")
        assert replay.fx_conversions[0].execution_allowed is False

        missing_fx = replay_ledger(
            store.connection,
            authority="paper",
            as_of="2026-10-01T23:59:59Z",
            known_at="2026-10-02T00:00:00Z",
            base_currency="USD",
        )
        assert missing_fx.fx_conversions[0].status == "missing"
        assert missing_fx.fx_conversions[0].base_book_balance is None

        not_yet_known = replay_ledger(
            store.connection,
            authority="paper",
            as_of="2026-10-01T23:59:59Z",
            known_at="2020-01-01T00:00:00Z",
        )
        assert not_yet_known.positions == ()
        assert not_yet_known.cash == ()


def test_corporate_action_store_replay_posts_split_and_net_dividend(tmp_path):
    with TransactionalStore(tmp_path / "ledger") as store:
        ledger = Ledger(store.connection)
        ledger.create_account(
            "positions", name="Positions", account_type="asset", authority="paper", account_role="position"
        )
        ledger.create_account("offset", name="Position offset", account_type="equity", authority="paper")
        ledger.create_account(
            "cash-eur", name="EUR Cash", account_type="asset", authority="paper", account_role="cash"
        )
        ledger.create_account("income", name="Income", account_type="income", authority="paper")
        ledger.create_account("tax", name="Withholding", account_type="expense", authority="paper")
        ledger.post(
            "opening-lot",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting("positions", None, instrument_id="AAA", quantity_delta=Decimal("10"), lot_id="lot-1"),
                LedgerPosting("offset", None, instrument_id="AAA", quantity_delta=Decimal("-10"), lot_id="lot-1"),
            ),
        )

        split = CorporateAction(
            action_id="split-1",
            instrument_id="AAA",
            action_type="split",
            announced_at="2026-09-28T09:00:00Z",
            effective_at="2026-09-29T00:00:00Z",
            ex_date="2026-09-29",
            payable_at=None,
            known_at="2026-09-28T09:00:00Z",
            revision=1,
            source="issuer",
            source_id="issuer-feed",
            source_checksum="b" * 64,
            ratio=2,
        )
        dividend = CorporateAction(
            action_id="dividend-1",
            instrument_id="AAA",
            action_type="dividend",
            announced_at="2026-09-29T09:00:00Z",
            effective_at="2026-09-30T00:00:00Z",
            ex_date="2026-09-30",
            payable_at="2026-10-02T12:00:00Z",
            known_at="2026-09-29T09:00:00Z",
            revision=1,
            source="issuer",
            source_id="issuer-feed",
            source_checksum="c" * 64,
            amount=0.5,
            currency="EUR",
            withholding_rate=0.1,
        )
        with CorporateActionStore(tmp_path / "actions") as action_store:
            action_store.append(split)
            action_store.append(dividend)
            assert action_store.replay(
                "AAA", effective_at="2026-09-29T23:59:59Z", known_at="2026-09-28T12:00:00Z"
            ) == (split,)
            split_entry = ledger.post_corporate_action(
                split,
                entry_id="action-split-1",
                authority="paper",
                known_at="2026-09-28T12:00:00Z",
                quantity_before=Decimal("10"),
                lot_id="lot-1",
                position_account_id="positions",
                counter_account_id="offset",
            )
            before_dividend = replay_ledger(
                store.connection,
                authority="paper",
                as_of="2026-09-29T23:59:59Z",
                known_at="9999-12-31T00:00:00Z",
            )
            quantity_before_dividend = before_dividend.positions[0].quantity
            assert quantity_before_dividend == Decimal("20")
            assert action_store.replay(
                "AAA", effective_at="2026-09-30T23:59:59Z", known_at="2026-09-29T12:00:00Z"
            ) == (split, dividend)
            dividend_entry = ledger.post_corporate_action(
                dividend,
                entry_id="action-dividend-1",
                authority="paper",
                known_at="2026-09-29T12:00:00Z",
                quantity_before=quantity_before_dividend,
                lot_id="lot-1",
                position_account_id="positions",
                counter_account_id="income",
                cash_account_id="cash-eur",
                withholding_account_id="tax",
            )

        assert split_entry.settlement_at is None
        assert dividend_entry.settlement_at == "2026-10-02T12:00:00Z"
        replay = replay_ledger(
            store.connection,
            authority="paper",
            as_of="2026-10-01T23:59:59Z",
            known_at="9999-12-31T00:00:00Z",
        )
        assert replay.positions[0].quantity == Decimal("20")
        assert replay.cash[0].book_balance == Decimal("9.00")
        assert replay.cash[0].pending_settlement_balance == Decimal("9.00")
        assert replay.cash[0].settled_balance == 0
        assert replay.trial_balance_balanced is True
        assert replay.trial_balance_totals == (("EUR", Decimal("10.00"), Decimal("10.00")),)

        ledger.reverse(
            split_entry.entry_id,
            entry_id="action-split-reversal",
            authority="paper",
            effective_at="2026-10-03T12:00:00Z",
        )
        ledger.reverse(
            dividend_entry.entry_id,
            entry_id="action-dividend-reversal",
            authority="paper",
            effective_at="2026-10-03T12:00:00Z",
        )
        corrected = replay_ledger(
            store.connection,
            authority="paper",
            as_of="2026-10-04T00:00:00Z",
            known_at="9999-12-31T00:00:00Z",
        )
        assert corrected.positions[0].quantity == Decimal("10")
        assert corrected.cash[0].book_balance == 0
        assert corrected.trial_balance_balanced is True


def test_replay_keeps_missing_lot_and_settlement_explicit(tmp_path):
    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        ledger.create_account(
            "positions", name="Positions", account_type="asset", authority="paper", account_role="position"
        )
        ledger.create_account("offset", name="Offset", account_type="equity", authority="paper")
        ledger.create_account(
            "cash", name="Cash", account_type="asset", authority="paper", account_role="cash"
        )
        ledger.create_account("equity", name="Equity", account_type="equity", authority="paper")
        ledger.post(
            "unidentified-lot",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting("positions", None, instrument_id="AAA", quantity_delta=Decimal("3")),
                LedgerPosting("offset", None, instrument_id="AAA", quantity_delta=Decimal("-3")),
            ),
        )
        ledger.post(
            "unknown-settlement",
            authority="paper",
            effective_at="2026-09-28T12:00:00Z",
            postings=(
                LedgerPosting("cash", "EUR", debit=Decimal("12")),
                LedgerPosting("equity", "EUR", credit=Decimal("12")),
            ),
        )
        replay = replay_ledger(
            store.connection,
            authority="paper",
            as_of="2026-09-29T12:00:00Z",
            known_at="9999-12-31T00:00:00Z",
        )
        assert replay.positions[0].missing_lot_identity is True
        assert replay.missing_lot_identity == (("positions", "AAA"),)
        assert replay.cash[0].book_balance == Decimal("12")
        assert replay.cash[0].unknown_settlement_balance == Decimal("12")
        assert replay.unknown_settlement_lines == (("unknown-settlement", 1),)
