from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.application.portfolio_imports import PortfolioImportApplication
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.market_adjustments import FXObservation, FXObservationStore
from etf_cockpit.portfolio.ledger import Ledger, LedgerPosting
from etf_cockpit.portfolio.reconciliation import source_entry_id


def _identity(root: Path) -> None:
    row = IdentitySourceRow(
        row_id="identity-SEC-1",
        instrument_id="SEC-1",
        object_type="instrument",
        object_id="SEC-1",
        parent_object_id=None,
        relationship=None,
        identifiers={"isin": "US0000000001"},
        attributes={"ticker": "SEC-1", "exchange": "XNAS", "currency": "USD"},
        source="fixture",
        authority=SourceAuthority.OFFICIAL,
        source_id="fixture:SEC-1",
        valid_from="2020-01-01T00:00:00Z",
        available_at="2020-01-01T00:00:00Z",
    )
    with IdentityMasterStore(root) as store:
        store.import_rows((row,))


def _accounts(root: Path) -> None:
    with TransactionalStore(root) as store:
        ledger = Ledger(store.connection)
        ledger.create_account(
            "CASH-A1",
            name="A1 cash",
            account_type="asset",
            account_role="cash",
            authority="broker",
        )
        ledger.create_account(
            "POSITION-A1",
            name="A1 positions",
            account_type="asset",
            account_role="position",
            authority="broker",
        )
        ledger.create_account(
            "CLEARING-A1",
            name="A1 clearing",
            account_type="equity",
            authority="broker",
        )


def _trade(*, quantity: int = 1, settlement: int = -101) -> dict[str, object]:
    return {
        "provider_id": "broker-a",
        "source_system": "broker-a",
        "record_type": "transaction",
        "source_id": "trade-1",
        "occurred_at": "2024-01-02T10:00:00Z",
        "account_id": "A1",
        "instrument_id": "SEC-1",
        "currency": "USD",
        "side": "buy",
        "quantity": quantity,
        "price": 100,
        "fee_amount": -quantity,
        "tax_amount": 0,
        "settlement_cash": settlement,
    }


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _cutoff() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _application_with_trade(tmp_path: Path) -> tuple[PortfolioImportApplication, str]:
    _identity(tmp_path)
    _accounts(tmp_path)
    app = PortfolioImportApplication(tmp_path)
    preview = app.preview(_write(tmp_path / "trade.csv", [_trade()]))
    app.commit(preview)
    return app, str(app._store.source_events().iloc[0]["event_id"])


def _map_account(app: PortfolioImportApplication) -> None:
    app.map_source_account(
        authority="broker",
        source_account_id="A1",
        cash_account_id="CASH-A1",
        position_account_id="POSITION-A1",
        clearing_account_id="CLEARING-A1",
        reviewer="operator",
        reason="Broker statement account explicitly matched to the local ledger accounts",
    )


def test_reconciliation_requires_explicit_mapping_then_replays_canonical_ledger(
    tmp_path: Path,
) -> None:
    app, event_id = _application_with_trade(tmp_path)

    before_mapping = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    assert [item.kind for item in before_mapping.discrepancies] == ["missing_account_mapping"]
    assert before_mapping.replay.positions == ()
    _map_account(app)

    unmatched = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    assert unmatched.discrepancies[0].kind == "source_without_ledger_entry"
    assert unmatched.discrepancies[0].adjustment_available is True

    adjustment = app.apply_adjustment(
        event_id,
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=_cutoff(),
        reviewer="operator",
        reason="Post the accepted broker statement fact after verifying explicit account mapping",
    )
    result = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )

    assert adjustment.ledger_entry_id == source_entry_id(event_id)
    assert adjustment.reversed_entry_ids == ()
    assert result.matched_source_rows == 1
    assert result.discrepancies == ()
    assert result.replay.trial_balance_balanced is True
    assert result.replay.positions[0].quantity == 1
    assert result.replay.cash[0].book_balance == -101
    assert result.replay.cash[0].unknown_settlement_balance == -101
    assert result.replay.missing_lot_identity == (("POSITION-A1", "SEC-1"),)
    assert result.execution_allowed is False


def test_correction_is_audited_as_reversal_plus_new_posting(tmp_path: Path) -> None:
    app, original_event_id = _application_with_trade(tmp_path)
    _map_account(app)
    first = app.apply_adjustment(
        original_event_id,
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=_cutoff(),
        reviewer="operator",
        reason="Initial matched statement fact",
    )
    original_entry_id = first.ledger_entry_id

    original = app._store.source_events().iloc[0]
    corrected = _trade(quantity=2, settlement=-202)
    corrected["source_revision"] = 2
    corrected["predecessor_content_hash"] = original["content_hash"]
    corrected["predecessor_revision"] = original["source_revision"]
    preview = app.preview(_write(tmp_path / "correction.csv", [corrected]))
    assert preview.frame.iloc[0]["staging_status"] == "correction"
    app.commit(preview)
    correction_event_id = str(app._store.source_events().iloc[0]["event_id"])

    correction = app.apply_adjustment(
        correction_event_id,
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=_cutoff(),
        reviewer="operator",
        reason="Reverse superseded source posting and post its accepted correction",
    )
    assert correction.reversed_entry_ids == (original_entry_id,)
    result = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    with TransactionalStore(tmp_path) as store:
        original_entry = Ledger(store.connection).get_entry(
            original_entry_id, authority="broker"
        )
        reversal_id = store.connection.execute(
            "SELECT entry_id FROM ledger_entries WHERE authority = 'broker' AND reversal_of_entry_id = ?",
            (original_entry_id,),
        ).fetchone()[0]
        reversal = Ledger(store.connection).get_entry(reversal_id, authority="broker")

    assert correction.reversed_entry_ids == (original_entry_id,)
    assert original_entry is not None and original_entry.reversal_of_entry_id is None
    assert reversal is not None and reversal.reversal_of_entry_id == original_entry_id
    assert result.matched_source_rows == 1
    assert result.replay.positions[0].quantity == 2
    assert result.replay.cash[0].book_balance == -202


def test_reconciliation_uses_source_and_ledger_known_time_cutoffs(
    tmp_path: Path,
) -> None:
    app, original_event_id = _application_with_trade(tmp_path)
    _map_account(app)
    app.apply_adjustment(
        original_event_id,
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=_cutoff(),
        reviewer="operator",
        reason="Post original source event",
    )
    known_before_correction = _cutoff()
    original = app._store.source_events().iloc[0]
    corrected = _trade(quantity=2, settlement=-202)
    corrected["source_revision"] = 2
    corrected["predecessor_content_hash"] = original["content_hash"]
    corrected["predecessor_revision"] = original["source_revision"]
    preview = app.preview(_write(tmp_path / "later-correction.csv", [corrected]))
    app.commit(preview)

    historical = app.reconcile(
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=known_before_correction,
    )
    assert historical.active_source_rows == 1
    assert historical.matched_source_rows == 1
    assert historical.source_events[0]["event_id"] == original_event_id
    assert historical.replay.positions[0].quantity == 1


def test_mismatched_posting_is_reversed_before_audited_replacement(tmp_path: Path) -> None:
    app, event_id = _application_with_trade(tmp_path)
    _map_account(app)
    source_row = app._store.source_events().iloc[0]
    event_key_hash = hashlib.sha256(str(source_row["event_key"]).encode()).hexdigest()
    incorrect_postings = (
        LedgerPosting(
            "POSITION-A1", None, instrument_id="SEC-1", quantity_delta=Decimal("2")
        ),
        LedgerPosting(
            "CLEARING-A1", None, instrument_id="SEC-1", quantity_delta=Decimal("-2")
        ),
        LedgerPosting("CASH-A1", "USD", credit=Decimal("101")),
        LedgerPosting("CLEARING-A1", "USD", debit=Decimal("101")),
    )
    with TransactionalStore(tmp_path) as store:
        Ledger(store.connection).post(
            source_entry_id(event_id),
            authority="broker",
            effective_at="2024-01-02T10:00:00Z",
            postings=incorrect_postings,
            description=f"portfolio-source event={event_id} key={event_key_hash} content=prior",
        )

    mismatch = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    assert mismatch.discrepancies[0].kind == "statement_ledger_mismatch"
    assert mismatch.discrepancies[0].adjustment_available is True
    adjustment = app.apply_adjustment(
        event_id,
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=_cutoff(),
        reviewer="operator",
        reason="Reverse incorrect posted quantity and replace from verified source facts",
    )
    result = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    assert adjustment.reversed_entry_ids == (source_entry_id(event_id),)
    assert adjustment.ledger_entry_id.endswith("-revision-2")
    assert result.matched_source_rows == 1
    assert result.replay.positions[0].quantity == 1


def test_source_rollback_leaves_ledger_facts_and_requires_explicit_reversal(
    tmp_path: Path,
) -> None:
    app, event_id = _application_with_trade(tmp_path)
    _map_account(app)
    adjustment = app.apply_adjustment(
        event_id,
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=_cutoff(),
        reviewer="operator",
        reason="Post source fact before withdrawal",
    )
    batch_id = app.batches()[0]["batch_id"]
    app.rollback(str(batch_id), reason="Statement batch withdrawn by reviewer")

    after_rollback = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    assert any(item.kind == "ledger_without_active_source" for item in after_rollback.discrepancies)
    reversal_id = app.reverse_orphaned_entry(
        adjustment.ledger_entry_id,
        authority="broker",
        reviewer="operator",
        reason="Reverse journal fact after its source batch was withdrawn",
    )
    after_reversal = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    assert after_reversal.replay.positions == ()
    assert not any(item.kind == "ledger_without_active_source" for item in after_reversal.discrepancies)
    with TransactionalStore(tmp_path) as store:
        assert Ledger(store.connection).get_entry(adjustment.ledger_entry_id, authority="broker") is not None
        assert Ledger(store.connection).get_entry(reversal_id, authority="broker") is not None


def test_audit_export_is_deterministic_and_non_executable(
    tmp_path: Path,
) -> None:
    app, _event_id = _application_with_trade(tmp_path)
    _map_account(app)
    one = app.export_reconciliation_audit(
        tmp_path / "audit-one.json",
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at="2030-01-01T00:00:00Z",
    )
    two = app.export_reconciliation_audit(
        tmp_path / "audit-two.json",
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at="2030-01-01T00:00:00Z",
    )
    assert one.read_bytes() == two.read_bytes()
    assert b'"execution_allowed":false' in one.read_bytes()


def test_source_fx_posting_and_dated_fx_replay_use_explicit_observations(
    tmp_path: Path,
) -> None:
    _accounts(tmp_path)
    app = PortfolioImportApplication(tmp_path)
    fx_row = {
        "provider_id": "broker-a",
        "source_system": "broker-a",
        "record_type": "fx",
        "source_id": "fx-1",
        "occurred_at": "2024-01-02T10:00:00Z",
        "account_id": "A1",
        "from_currency": "USD",
        "from_amount": -100,
        "to_currency": "EUR",
        "to_amount": 90,
        "fx_rate": 0.9,
    }
    app.commit(app.preview(_write(tmp_path / "fx.csv", [fx_row])))
    event_id = str(app._store.source_events().iloc[0]["event_id"])
    _map_account(app)
    app.apply_adjustment(
        event_id,
        authority="broker",
        as_of="2025-01-01T00:00:00Z",
        known_at=_cutoff(),
        reviewer="operator",
        reason="Post explicit signed FX source amounts without deriving a rate",
    )
    observation_time = "2024-12-31T00:00:00Z"
    with FXObservationStore(tmp_path) as fx_store:
        fx_store.append(
            FXObservation(
                observation_id="USD-EUR-2024-12-31",
                base_currency="USD",
                quote_currency="EUR",
                rate="0.9",
                valid_at=observation_time,
                published_at=observation_time,
                retrieved_at=observation_time,
                known_at=observation_time,
                revision=1,
                source="official-fixture",
                source_id="fx-source-1",
                source_checksum="a" * 64,
            )
        )
        result = app.reconcile(
            authority="broker",
            as_of="2025-01-01T00:00:00Z",
            known_at="2030-01-01T00:00:00Z",
            fx_store=fx_store,
            base_currency="EUR",
        )

    assert result.replay.trial_balance_balanced is True
    assert {item.currency: item.book_balance for item in result.replay.cash} == {
        "EUR": Decimal("90"),
        "USD": Decimal("-100"),
    }
    conversion = next(item for item in result.replay.fx_conversions if item.currency == "USD")
    assert conversion.status == "available"
    assert conversion.base_book_balance == Decimal("-90.0")


def test_corporate_action_without_canonical_action_mapping_stays_explicit(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    _accounts(tmp_path)
    app = PortfolioImportApplication(tmp_path)
    split = {
        "provider_id": "broker-a",
        "source_system": "broker-a",
        "record_type": "corporate_action",
        "source_id": "split-1",
        "occurred_at": "2024-01-03T00:00:00Z",
        "account_id": "A1",
        "instrument_id": "SEC-1",
        "corporate_action_type": "split",
        "ratio_numerator": 2,
        "ratio_denominator": 1,
    }
    app.commit(app.preview(_write(tmp_path / "split.csv", [split])))
    _map_account(app)

    result = app.reconcile(
        authority="broker", as_of="2025-01-01T00:00:00Z", known_at=_cutoff()
    )
    discrepancy = result.discrepancies[0]
    assert discrepancy.kind == "unsupported_source_mapping"
    assert "CorporateActionStore" in discrepancy.detail
    assert discrepancy.adjustment_available is False


def test_import_store_no_longer_calculates_balances() -> None:
    from etf_cockpit.data.portfolio_imports import PortfolioImportError, PortfolioImportStore

    with pytest.raises(PortfolioImportError, match="ingestion adapter"):
        PortfolioImportStore(Path(".")).rebuild()
