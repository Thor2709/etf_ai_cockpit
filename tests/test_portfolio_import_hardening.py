from __future__ import annotations

from pathlib import Path
from dataclasses import replace

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


def test_commit_rejects_forged_preview_and_uses_durable_stage_authority(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    preview = service.preview(
        _write(tmp_path / "forged.csv", [_trade("forged")]),
        source_format="broker_csv",
    )
    forged_frame = preview.frame.copy(deep=True)
    forged_frame.loc[0, "quantity"] = 99
    forged_frame.loc[0, "content_hash"] = portfolio_import_module._content_hash(
        forged_frame.iloc[0].to_dict()
    )
    forged = replace(
        preview,
        frame=forged_frame,
        checksum=portfolio_import_module._frame_checksum(forged_frame),
    )
    forged_mapping_metadata = replace(
        preview,
        warnings=tuple(
            "mapping_version:99" if item.startswith("mapping_version:") else item
            for item in preview.warnings
        ),
    )
    alternate_source = _write(tmp_path / "alternate.csv", [_trade("forged")])
    forged_source_metadata = replace(preview, path=alternate_source)
    for supplied in (forged, forged_mapping_metadata, forged_source_metadata):
        with pytest.raises(PortfolioImportError, match="durable stage"):
            service.commit(supplied)
    with TransactionalStore(tmp_path) as store:
        assert store.list("portfolio_import_batch_v1") == ()
        assert store.list("portfolio_import_event_v1") == ()


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
    assert stage["mapping_decisions"][0]["decision_time"] == stage["decision_time"]
    assert set(mapped.frame["decision_time"]) == {stage["decision_time"]}


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
    decision_time = stages[0]["decision_time"]
    rebuilt = PortfolioImportStore(tmp_path).rebuild()
    assert set(rebuilt.active_events["decision_time"]) == {decision_time}


def test_one_decision_time_is_reused_and_future_identity_is_unavailable(
    tmp_path: Path,
) -> None:
    future = IdentitySourceRow(
        row_id="future",
        instrument_id="SEC-FUTURE",
        object_type="listing",
        object_id="SEC-FUTURE:XNAS",
        parent_object_id="SEC-FUTURE",
        relationship="quotation_of",
        identifiers={"isin": "US9999999999"},
        attributes={"ticker": "FUT", "mic": "XNAS", "currency": "USD"},
        source="fixture",
        authority=SourceAuthority.OFFICIAL,
        source_id="fixture:future",
        valid_from="2020-01-01T00:00:00Z",
        available_at="2099-01-01T00:00:00Z",
    )
    with IdentityMasterStore(tmp_path) as store:
        store.import_rows((future,))
    rows = [
        _trade("future-1") | {"ticker": "FUT"},
        _trade("future-2") | {"ticker": "FUT"},
    ]
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "future.csv", rows), source_format="broker_csv"
    )
    assert preview.frame["decision_time"].nunique() == 1
    assert set(preview.frame["quarantine_reason"]) == {"identity_unresolved"}
    stage = PortfolioImportStore(tmp_path).stages()[0]
    assert stage["decision_time"] == preview.frame.iloc[0]["decision_time"]


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
            "lot_role": "trade_detail",
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


def test_lot_only_opening_position_is_rebuilt_once(tmp_path: Path) -> None:
    _identity(tmp_path)
    lot = {
        "source_system": "broker-a",
        "provider_id": "broker-a",
        "record_type": "lot",
        "source_id": "opening-lot",
        "occurred_at": "2024-01-01T00:00:00Z",
        "account_id": "A1",
        "ticker": "AAA",
        "mic": "XNAS",
        "quantity": 7,
        "lot_role": "opening_position",
    }
    service = PortfolioImportStore(tmp_path)
    service.commit(
        service.preview(
            _write(tmp_path / "lot-only.csv", [lot]), source_format="broker_csv"
        )
    )
    assert service.rebuild().holdings.iloc[0]["quantity"] == 7


def test_lot_without_explicit_semantics_is_quarantined(tmp_path: Path) -> None:
    _identity(tmp_path)
    lot = {
        "source_system": "broker-a",
        "provider_id": "broker-a",
        "record_type": "lot",
        "source_id": "ambiguous-lot",
        "occurred_at": "2024-01-01T00:00:00Z",
        "account_id": "A1",
        "ticker": "AAA",
        "mic": "XNAS",
        "quantity": 7,
    }
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "ambiguous-lot.csv", [lot]), source_format="broker_csv"
    )
    assert preview.frame.iloc[0]["quarantine_reason"] == "unsupported_lot_semantics"


@pytest.mark.parametrize(
    ("currency", "reason"),
    [
        ("ZZZ", "unknown_currency:currency"),
        ("DEM", "withdrawn_currency:currency"),
        ("$", "ambiguous_currency:currency"),
    ],
)
def test_currency_registry_is_canonical_and_point_in_time(
    tmp_path: Path, currency: str, reason: str
) -> None:
    row = {
        "source_system": "broker-a",
        "provider_id": "broker-a",
        "record_type": "cash",
        "source_id": "cash",
        "occurred_at": "2024-01-01T00:00:00Z",
        "account_id": "A1",
        "currency": currency,
        "cash_amount": 10,
    }
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "currency.csv", [row]), source_format="broker_csv"
    )
    assert preview.frame.iloc[0]["quarantine_reason"] == reason


def test_cash_and_fx_persist_canonical_currency_identities(tmp_path: Path) -> None:
    rows = [
        {
            "source_system": "broker-a",
            "provider_id": "broker-a",
            "record_type": "cash",
            "source_id": "cash",
            "occurred_at": "2024-01-01T00:00:00Z",
            "account_id": "A1",
            "currency": "usd",
            "cash_amount": 10,
        },
        {
            "source_system": "broker-a",
            "provider_id": "broker-a",
            "record_type": "fx",
            "source_id": "fx",
            "occurred_at": "2024-01-01T00:00:00Z",
            "account_id": "A1",
            "from_currency": "USD",
            "from_amount": -10,
            "to_currency": "EUR",
            "to_amount": 9,
            "fx_rate": 0.9,
        },
    ]
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "canonical-currency.csv", rows),
        source_format="broker_csv",
    )
    cash, fx = preview.frame.to_dict(orient="records")
    assert cash["currency_identity"] == "ISO4217:USD"
    assert fx["from_currency_identity"] == "ISO4217:USD"
    assert fx["to_currency_identity"] == "ISO4217:EUR"
    assert set(preview.frame["staging_status"]) == {"accepted"}


def test_withdrawn_currency_is_valid_only_before_its_pit_cutoff(tmp_path: Path) -> None:
    row = {
        "source_system": "broker-a",
        "provider_id": "broker-a",
        "record_type": "cash",
        "source_id": "historical-dem",
        "occurred_at": "2000-01-01T00:00:00Z",
        "account_id": "A1",
        "currency": "DEM",
        "cash_amount": 10,
    }
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "historical-dem.csv", [row]), source_format="broker_csv"
    )
    assert preview.frame.iloc[0]["staging_status"] == "accepted"
    assert preview.frame.iloc[0]["currency_identity"] == "ISO4217:DEM"


def test_transfer_pairing_is_namespaced_by_provider_and_source(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for provider, amount in (("broker-a", 10), ("broker-b", 20)):
        common = {
            "source_system": provider,
            "provider_id": provider,
            "record_type": "transfer",
            "transfer_id": "shared-transfer",
            "occurred_at": "2024-01-01T00:00:00Z",
            "account_id": "A1",
            "currency": "USD",
        }
        rows.extend(
            [
                common
                | {
                    "source_id": f"{provider}-out",
                    "transfer_leg": "debit",
                    "cash_amount": -amount,
                },
                common
                | {
                    "source_id": f"{provider}-in",
                    "transfer_leg": "credit",
                    "cash_amount": amount,
                },
            ]
        )
    preview = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "transfers.csv", rows), source_format="broker_csv"
    )
    assert set(preview.frame["staging_status"]) == {"accepted"}


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
