from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data import portfolio_imports as portfolio_import_module
from etf_cockpit.data.portfolio_imports import (
    PortfolioImportError,
    PortfolioImportStore,
)


def _identity(
    root: Path,
    instrument_id: str = "SEC-1",
    *,
    ticker: str = "AAA",
    isin: str = "US0000000001",
    currency: str = "USD",
) -> None:
    row = IdentitySourceRow(
        row_id=f"identity-{instrument_id}",
        instrument_id=instrument_id,
        object_type="listing",
        object_id=f"{instrument_id}:XNAS",
        parent_object_id=instrument_id,
        relationship="quotation_of",
        identifiers={"isin": isin},
        attributes={
            "ticker": ticker,
            "exchange": "XNAS",
            "mic": "XNAS",
            "currency": currency,
            "listing": f"{ticker}:XNAS",
        },
        source="fixture",
        authority=SourceAuthority.OFFICIAL,
        source_id=f"fixture:{instrument_id}",
        valid_from="2020-01-01T00:00:00Z",
        available_at="2020-01-01T00:00:00Z",
    )
    with IdentityMasterStore(root) as store:
        store.import_rows((row,))


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _trade(
    source_id: str,
    *,
    settlement: float = -101,
    price: float = 100,
    side: str = "buy",
    predecessor: str = "",
    predecessor_revision: int | None = None,
    source_revision: int = 1,
) -> dict[str, object]:
    return {
        "source_system": "broker-a",
        "provider_id": "broker-a",
        "record_type": "transaction",
        "source_id": source_id,
        "predecessor_content_hash": predecessor,
        "predecessor_revision": predecessor_revision,
        "source_revision": source_revision,
        "occurred_at": "2024-01-02T10:00:00Z",
        "account_id": "A1",
        "ticker": "AAA",
        "mic": "XNAS",
        "currency": "USD",
        "side": side,
        "quantity": 1,
        "price": price,
        "fee_amount": -1,
        "tax_amount": 0,
        "settlement_cash": settlement,
    }


@pytest.mark.parametrize(
    "entity_type",
    [
        "portfolio_import_event_v1",
        "portfolio_import_batch_v1",
        "portfolio_import_stage_v1",
    ],
)
def test_valid_sqlite_payload_tampering_is_detected_before_rebuild(
    tmp_path: Path, entity_type: str
) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    service.commit(
        service.preview(
            _write(tmp_path / "trade.csv", [_trade("t1")]), source_format="broker_csv"
        )
    )
    with TransactionalStore(tmp_path) as store:
        record = store.list(entity_type)[0]
        tampered = dict(record.payload)
        if entity_type == "portfolio_import_event_v1":
            tampered["quantity"] = 999
        elif entity_type == "portfolio_import_batch_v1":
            tampered["event_ids"] = []
        else:
            tampered["raw_source_base64"] = "AA=="
        store.put(entity_type, record.entity_id, tampered)
    with pytest.raises(PortfolioImportError, match="integrity"):
        service.rebuild()


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"side": "buy", "settlement_cash": 101}, "trade_settlement_sign"),
        ({"side": "sell", "settlement_cash": 101}, "trade_settlement_mismatch"),
        ({"price": -1}, "invalid_price"),
        ({"quantity": float("inf")}, "invalid_quantity"),
    ],
)
def test_trade_accounting_invariants_quarantine_invalid_rows(
    tmp_path: Path, patch: dict[str, object], reason: str
) -> None:
    _identity(tmp_path)
    row = _trade("bad") | patch
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "bad.csv", [row]), source_format="broker_csv"
    )
    assert preview.frame.iloc[0]["staging_status"] == "quarantined"
    assert preview.frame.iloc[0]["quarantine_reason"] == reason


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (
            {
                "source_system": "market",
                "provider_id": "market",
                "record_type": "price",
                "source_id": "price",
                "occurred_at": "2024-01-02T00:00:00Z",
                "ticker": "AAA",
                "mic": "XNAS",
                "adjusted_close": 0,
            },
            "invalid_adjusted_price",
        ),
        (
            {
                **_trade("notional", settlement=-996),
                "face_value": 0,
                "clean_price": 99,
                "accrued_interest": 5,
            },
            "invalid_bond_notional",
        ),
        (
            {
                **_trade("clean", settlement=-996),
                "face_value": 1000,
                "clean_price": -1,
                "accrued_interest": 5,
            },
            "invalid_clean_price",
        ),
    ],
)
def test_financial_domains_are_positive_and_finite(
    tmp_path: Path, row: dict[str, object], reason: str
) -> None:
    _identity(tmp_path)
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "domain.csv", [row]), source_format="broker_csv"
    )
    assert preview.frame.iloc[0]["quarantine_reason"] == reason


def test_fx_rate_and_transfer_pair_are_reconciled(tmp_path: Path) -> None:
    rows = [
        {
            "source_system": "broker-a",
            "provider_id": "broker-a",
            "record_type": "fx",
            "source_id": "fx",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "from_currency": "USD",
            "from_amount": -100,
            "to_currency": "EUR",
            "to_amount": 80,
            "fx_rate": 0.9,
        },
        {
            "source_system": "broker-a",
            "provider_id": "broker-a",
            "record_type": "transfer",
            "source_id": "xfer-out",
            "transfer_id": "xfer-1",
            "transfer_leg": "debit",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "currency": "USD",
            "cash_amount": -10,
        },
    ]
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "bad-ledger.csv", rows), source_format="broker_csv"
    )
    assert set(preview.frame["quarantine_reason"]) == {
        "fx_rate_mismatch",
        "unpaired_transfer",
    }


def test_ticker_listing_maps_to_canonical_identity_and_exposes_candidates(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "mapped.csv", [_trade("mapped")]), source_format="broker_csv"
    )
    row = preview.frame.iloc[0]
    assert row["raw_instrument_id"] == "AAA"
    assert row["instrument_id"] == "SEC-1"
    assert row["identity_candidates"] == "SEC-1"
    assert row["identity_mapping_method"] == "ticker+mic"
    assert row["staging_status"] == "accepted"


def test_manual_mapping_creates_checksum_bound_immutable_revision(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    source_row = _trade("manual") | {"ticker": "BROKER-ALT"}
    preview = service.preview(
        _write(tmp_path / "manual.csv", [source_row]), source_format="broker_csv"
    )
    assert preview.frame.iloc[0]["quarantine_reason"] == "identity_unresolved"
    mapped = service.apply_mapping(
        preview.preview_id,
        source_identity="BROKER-ALT",
        canonical_instrument_id="SEC-1",
        reviewer="operator",
        reason="broker contract confirmed against official ISIN",
    )
    assert mapped.preview_id != preview.preview_id
    assert mapped.frame.iloc[0]["instrument_id"] == "SEC-1"
    assert mapped.frame.iloc[0]["identity_mapping_method"] == "manual_reviewed"
    stage = next(
        item for item in service.stages() if item["stage_id"] == mapped.preview_id
    )
    assert stage["parent_stage_id"] == preview.preview_id
    assert stage["mapping_version"] == 2
    assert stage["mapping_decisions"][0]["reviewer"] == "operator"


def test_source_namespace_prevents_cross_provider_collision(tmp_path: Path) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    first = _trade("shared")
    second = _trade("shared") | {"source_system": "broker-b", "provider_id": "broker-b"}
    service.commit(
        service.preview(_write(tmp_path / "a.csv", [first]), source_format="broker_csv")
    )
    preview = service.preview(
        _write(tmp_path / "b.csv", [second]), source_format="broker_csv"
    )
    assert preview.frame.iloc[0]["staging_status"] == "accepted"


def test_stale_correction_preview_fails_compare_and_swap(tmp_path: Path) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    service.commit(
        service.preview(
            _write(tmp_path / "first.csv", [_trade("t1")]), source_format="broker_csv"
        )
    )
    predecessor = service.rebuild().active_events.iloc[0]["content_hash"]
    missing_predecessor = service.preview(
        _write(
            tmp_path / "missing-predecessor.csv",
            [_trade("t1", settlement=-102, price=101)],
        ),
        source_format="broker_csv",
    )
    assert (
        missing_predecessor.frame.iloc[0]["quarantine_reason"]
        == "missing_correction_predecessor"
    )
    correction_a = _trade(
        "t1",
        settlement=-102,
        price=101,
        predecessor=predecessor,
        predecessor_revision=1,
        source_revision=2,
    )
    correction_b = _trade(
        "t1",
        settlement=-103,
        price=102,
        predecessor=predecessor,
        predecessor_revision=1,
        source_revision=2,
    )
    preview_a = service.preview(
        _write(tmp_path / "a.csv", [correction_a]), source_format="broker_csv"
    )
    preview_b = service.preview(
        _write(tmp_path / "b.csv", [correction_b]), source_format="broker_csv"
    )
    service.commit(preview_a)
    with pytest.raises(PortfolioImportError, match="stale correction"):
        service.commit(preview_b)


def test_stage_and_raw_source_survive_process_restart(tmp_path: Path) -> None:
    _identity(tmp_path)
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "restart.csv", [_trade("t1")]), source_format="broker_csv"
    )
    portfolio_import_module._PREVIEWS.clear()
    result = PortfolioImportStore(tmp_path).commit(preview.preview_id)
    assert result.status == "committed"
    stages = PortfolioImportStore(tmp_path).stages()
    assert stages[0]["source_sha256"]
    assert stages[0]["raw_source_base64"]
    assert stages[0]["mapping_version"] == 1


def test_locale_is_explicit_and_ambiguous_numbers_are_quarantined(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    row = _trade("locale") | {"quantity": "1,23"}
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "locale.csv", [row]),
        source_format="broker_csv",
        numeric_locale="en_US",
    )
    assert preview.frame.iloc[0]["quarantine_reason"] == "ambiguous_number:quantity"
    assert "numeric_locale:en_US" in preview.warnings


def test_lots_do_not_double_count_and_split_uses_ratio(tmp_path: Path) -> None:
    _identity(tmp_path)
    rows = [
        _trade("trade"),
        {
            "source_system": "broker-a",
            "provider_id": "broker-a",
            "record_type": "lot",
            "source_id": "lot",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "ticker": "AAA",
            "mic": "XNAS",
            "quantity": 1,
        },
        {
            "source_system": "broker-a",
            "provider_id": "broker-a",
            "record_type": "corporate_action",
            "source_id": "split",
            "occurred_at": "2024-01-03T00:00:00Z",
            "account_id": "A1",
            "ticker": "AAA",
            "mic": "XNAS",
            "corporate_action_type": "split",
            "ratio_numerator": 2,
            "ratio_denominator": 1,
        },
    ]
    service = PortfolioImportStore(tmp_path)
    service.commit(
        service.preview(
            _write(tmp_path / "typed.csv", rows), source_format="broker_csv"
        )
    )
    assert service.rebuild().holdings.iloc[0]["quantity"] == 2


def test_balanced_is_derived_from_reconciliation_not_quarantine_count(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    split_without_position = {
        "source_system": "broker-a",
        "provider_id": "broker-a",
        "record_type": "corporate_action",
        "source_id": "orphan-split",
        "occurred_at": "2024-01-03T00:00:00Z",
        "account_id": "A1",
        "ticker": "AAA",
        "mic": "XNAS",
        "corporate_action_type": "split",
        "ratio_numerator": 2,
        "ratio_denominator": 1,
    }
    service = PortfolioImportStore(tmp_path)
    preview = service.preview(
        _write(tmp_path / "orphan.csv", [split_without_position]),
        source_format="broker_csv",
    )
    assert preview.frame.iloc[0]["staging_status"] == "accepted"
    service.commit(preview)
    rebuilt = service.rebuild()
    assert rebuilt.quarantined.empty
    assert rebuilt.balanced is False
    assert rebuilt.reconciliation_errors == (
        "broker-a|broker-a|A1|orphan-split:corporate_action_without_position",
    )


def test_unchanged_fresh_preview_is_a_true_commit_no_op(tmp_path: Path) -> None:
    _identity(tmp_path)
    source = _write(tmp_path / "same.csv", [_trade("same")])
    service = PortfolioImportStore(tmp_path)
    service.commit(service.preview(source, source_format="broker_csv"))
    before = len(service.batches())
    preview = service.preview(source, source_format="broker_csv")
    result = service.commit(preview)
    assert result.status == "no_op"
    assert len(service.batches()) == before
