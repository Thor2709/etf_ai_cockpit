from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.portfolio_imports import (
    PortfolioImportError,
    PortfolioImportStore,
)


def _identity(
    root: Path, instrument_id: str = "SEC-1", *, isin: str = "US0000000001"
) -> None:
    row = IdentitySourceRow(
        row_id=f"identity-{instrument_id}",
        instrument_id=instrument_id,
        object_type="instrument",
        object_id=instrument_id,
        parent_object_id=None,
        relationship=None,
        identifiers={"isin": isin},
        attributes={"ticker": instrument_id, "exchange": "XNAS", "currency": "USD"},
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
    source_id: str = "trade-1", *, settlement: float = -101, quantity: float = 1
) -> dict[str, object]:
    return {
        "provider_id": "broker-a",
        "source_system": "broker-a",
        "record_type": "transaction",
        "source_id": source_id,
        "occurred_at": "2024-01-02T10:00:00Z",
        "account_id": "A1",
        "instrument_id": "SEC-1",
        "currency": "USD",
        "side": "buy",
        "quantity": quantity,
        "price": abs(settlement) / quantity - 1,
        "fee_amount": -quantity,
        "tax_amount": 0,
        "settlement_cash": settlement,
    }


def test_dry_run_commit_is_idempotent_and_rebuilds_from_zero(tmp_path: Path) -> None:
    _identity(tmp_path)
    source = _write(
        tmp_path / "broker.csv",
        [
            _trade(),
            {
                "record_type": "cash",
                "source_id": "deposit-1",
                "occurred_at": "2024-01-01T00:00:00Z",
                "account_id": "A1",
                "currency": "USD",
                "cash_amount": 200,
            },
        ],
    )
    service = PortfolioImportStore(tmp_path)
    preview = service.preview(source, source_format="broker_csv")
    assert preview.valid
    assert set(preview.frame["staging_status"]) == {"accepted"}

    first = service.commit(preview)
    second = service.commit(preview)
    rebuilt = service.rebuild()

    assert first.status == "committed"
    assert second.status == "idempotent"
    assert rebuilt.holdings.to_dict(orient="records") == [
        {"account_id": "A1", "instrument_id": "SEC-1", "quantity": 1.0}
    ]
    assert rebuilt.cash.to_dict(orient="records") == [
        {"account_id": "A1", "currency": "USD", "cash_balance": 99.0}
    ]
    assert rebuilt.execution_allowed is False


def test_broker_csv_aliases_stage_as_canonical_transaction(tmp_path: Path) -> None:
    _identity(tmp_path)
    source = _write(
        tmp_path / "broker-golden.csv",
        [
            {
                "Transaction Type": "BUY",
                "Trade ID": "broker-100",
                "Trade Date": "2024-01-02T10:00:00Z",
                "Account Number": "BROKER-A",
                "Symbol": "SEC-1",
                "Currency": "USD",
                "Units": 3,
                "Price": 100,
                "Commission Amount": -3,
                "Net Amount": -303,
            }
        ],
    )
    preview = PortfolioImportStore(tmp_path).preview(source, source_format="broker_csv")
    row = preview.frame.iloc[0]
    assert row["record_type"] == "transaction"
    assert row["source_id"] == "broker-100"
    assert row["quantity"] == 3
    assert row["settlement_cash"] == -303
    assert row["staging_status"] == "accepted"


def test_duplicate_correction_and_rollback_reactivate_prior_version(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    original_path = _write(tmp_path / "original.csv", [_trade()])
    original = service.commit(service.preview(original_path))

    duplicate_path = _write(tmp_path / "duplicate.csv", [_trade()])
    duplicate_preview = service.preview(duplicate_path)
    assert duplicate_preview.frame.iloc[0]["staging_status"] == "duplicate"
    service.commit(duplicate_preview)
    assert service.rebuild().holdings.iloc[0]["quantity"] == 1

    corrected = _trade(settlement=-202, quantity=2)
    corrected["predecessor_content_hash"] = service.rebuild().active_events.iloc[0][
        "content_hash"
    ]
    corrected["predecessor_revision"] = service.rebuild().active_events.iloc[0][
        "source_revision"
    ]
    corrected["source_revision"] = int(corrected["predecessor_revision"]) + 1
    correction_path = _write(tmp_path / "correction.csv", [corrected])
    correction_preview = service.preview(correction_path)
    assert correction_preview.frame.iloc[0]["staging_status"] == "correction"
    correction = service.commit(correction_preview)
    assert service.rebuild().holdings.iloc[0]["quantity"] == 2

    assert service.rollback(correction.batch_id, reason="broker correction withdrawn")
    assert service.rebuild().holdings.iloc[0]["quantity"] == 1
    assert original.batch_id != correction.batch_id


def test_ambiguous_unbalanced_and_bad_bond_rows_remain_quarantined(
    tmp_path: Path,
) -> None:
    _identity(tmp_path, "SEC-1", isin="US0000000001")
    _identity(tmp_path, "SEC-2", isin="US0000000001")
    source = _write(
        tmp_path / "quarantine.csv",
        [
            _trade("ambiguous"),
            {
                **_trade("unbalanced"),
                "instrument_id": "MISSING",
                "settlement_cash": None,
            },
            {
                **_trade("bond", settlement=-1001),
                "face_value": 1000,
                "clean_price": 99,
                "accrued_interest": 5,
            },
        ],
    )
    service = PortfolioImportStore(tmp_path)
    preview = service.preview(source)
    assert preview.valid
    assert set(preview.frame["staging_status"]) == {"quarantined"}
    assert set(preview.frame["quarantine_reason"]) == {
        "identity_ambiguous",
        "unbalanced_transaction",
        "unbalanced_bond_settlement",
    }
    service.commit(preview)
    rebuilt = service.rebuild()
    assert rebuilt.holdings.empty
    assert len(rebuilt.quarantined) == 3
    assert rebuilt.balanced is True
    assert rebuilt.quarantined.shape[0] == 3


def test_source_mutation_and_preview_mutation_are_rejected(tmp_path: Path) -> None:
    _identity(tmp_path)
    source = _write(tmp_path / "source.csv", [_trade()])
    service = PortfolioImportStore(tmp_path)
    preview = service.preview(source)
    preview.frame.loc[0, "quantity"] = 99
    with pytest.raises(PortfolioImportError, match="durable stage"):
        service.commit(preview)

    preview = service.preview(source)
    _write(source, [_trade(quantity=2, settlement=-202)])
    with pytest.raises(PortfolioImportError, match="source changed"):
        service.commit(preview)


def test_canonical_export_round_trip_preserves_rebuild(tmp_path: Path) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    source = _write(tmp_path / "source.csv", [_trade()])
    service.commit(service.preview(source))
    exported = service.export_canonical(tmp_path / "export.csv")

    other = tmp_path / "other"
    other.mkdir()
    _identity(other)
    imported = PortfolioImportStore(other)
    preview = imported.preview(exported)
    assert preview.valid
    imported.commit(preview)
    pd.testing.assert_frame_equal(
        service.rebuild().holdings, imported.rebuild().holdings
    )
    pd.testing.assert_frame_equal(service.rebuild().cash, imported.rebuild().cash)


def test_canonical_export_neutralises_spreadsheet_formulas(tmp_path: Path) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    row = _trade()
    row["description"] = '=HYPERLINK("https://invalid")'
    service.commit(service.preview(_write(tmp_path / "formula.csv", [row])))
    destination = service.export_canonical(tmp_path / "safe.csv")
    exported = pd.read_csv(destination, dtype=object)
    assert exported.iloc[0]["description"].startswith("'=")


def test_xlsx_canonical_template_supports_all_portfolio_evidence_types(
    tmp_path: Path,
) -> None:
    _identity(tmp_path)
    rows = [
        {
            "record_type": "account",
            "source_id": "account",
            "occurred_at": "2024-01-01T00:00:00Z",
            "account_id": "A1",
        },
        {
            "record_type": "price",
            "source_id": "price",
            "occurred_at": "2024-01-01T00:00:00Z",
            "instrument_id": "SEC-1",
            "adjusted_close": 100,
        },
        {
            "record_type": "cash",
            "source_id": "cash",
            "occurred_at": "2024-01-01T00:00:00Z",
            "account_id": "A1",
            "currency": "USD",
            "cash_amount": 1000,
        },
        _trade(),
        {
            "record_type": "transfer",
            "source_id": "transfer-out",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "currency": "USD",
            "cash_amount": -25,
            "transfer_id": "transfer-1",
            "transfer_leg": "debit",
        },
        {
            "record_type": "transfer",
            "source_id": "transfer-in",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A2",
            "currency": "USD",
            "cash_amount": 25,
            "transfer_id": "transfer-1",
            "transfer_leg": "credit",
        },
        {
            "record_type": "fee",
            "source_id": "fee",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "currency": "USD",
            "cash_amount": -2,
        },
        {
            "record_type": "tax",
            "source_id": "tax",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "currency": "USD",
            "cash_amount": -3,
        },
        {
            "record_type": "fx",
            "source_id": "fx",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "from_currency": "USD",
            "from_amount": -100,
            "to_currency": "EUR",
            "to_amount": 90,
            "fx_rate": 0.9,
        },
        {
            "record_type": "lot",
            "source_id": "lot",
            "occurred_at": "2024-01-02T00:00:00Z",
            "account_id": "A1",
            "instrument_id": "SEC-1",
            "quantity": 2,
            "lot_role": "trade_detail",
        },
        {
            "record_type": "income",
            "source_id": "income",
            "occurred_at": "2024-01-03T00:00:00Z",
            "account_id": "A1",
            "instrument_id": "SEC-1",
            "currency": "USD",
            "cash_amount": 5,
        },
        {
            "record_type": "corporate_action",
            "source_id": "split",
            "occurred_at": "2024-01-04T00:00:00Z",
            "account_id": "A1",
            "instrument_id": "SEC-1",
            "corporate_action_type": "split",
            "ratio_numerator": 2,
            "ratio_denominator": 1,
        },
    ]
    path = _write(tmp_path / "canonical.csv", rows)
    service = PortfolioImportStore(tmp_path)
    preview = service.preview(path, source_format="canonical_csv")
    assert preview.valid
    assert set(preview.frame["staging_status"]) == {"accepted"}
    service.commit(preview)
    rebuilt = service.rebuild()
    assert rebuilt.holdings.iloc[0].to_dict() == {
        "account_id": "A1",
        "instrument_id": "SEC-1",
        "quantity": 2.0,
    }
    assert rebuilt.cash.to_dict(orient="records") == [
        {"account_id": "A1", "currency": "EUR", "cash_balance": 90.0},
        {"account_id": "A1", "currency": "USD", "cash_balance": 774.0},
        {"account_id": "A2", "currency": "USD", "cash_balance": 25.0},
    ]
    workbook = service.export_canonical(tmp_path / "canonical.xlsx")
    other = tmp_path / "xlsx-roundtrip"
    other.mkdir()
    _identity(other)
    xlsx_service = PortfolioImportStore(other)
    xlsx_preview = xlsx_service.preview(workbook, source_format="canonical_xlsx")
    assert xlsx_preview.valid
    assert set(xlsx_preview.frame["record_type"]) == {
        row["record_type"] for row in rows
    }
    assert set(xlsx_preview.frame["staging_status"]) == {"accepted"}
    xlsx_service.commit(xlsx_preview)
    pd.testing.assert_frame_equal(rebuilt.holdings, xlsx_service.rebuild().holdings)
    pd.testing.assert_frame_equal(rebuilt.cash, xlsx_service.rebuild().cash)


def test_concurrent_disjoint_commits_are_serialized(tmp_path: Path) -> None:
    _identity(tmp_path)
    service = PortfolioImportStore(tmp_path)
    previews = [
        service.preview(_write(tmp_path / f"{index}.csv", [_trade(f"trade-{index}")]))
        for index in range(4)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda preview: PortfolioImportStore(tmp_path).commit(preview), previews
            )
        )
    assert all(result.status == "committed" for result in results)
    assert service.rebuild().holdings.iloc[0]["quantity"] == 4


def test_corrupt_transactional_store_fails_closed(tmp_path: Path) -> None:
    _identity(tmp_path)
    database = storage_layout(tmp_path).transactional_path
    database.write_bytes(b"not sqlite")
    with pytest.raises(PortfolioImportError, match="storage unavailable"):
        PortfolioImportStore(tmp_path).rebuild()
