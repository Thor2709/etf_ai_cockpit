"""Bughunt D regressions for portfolio imports (issue 982)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.application.portfolio_imports import PortfolioImportApplication
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow
from etf_cockpit.data.portfolio_imports import PortfolioImportStore, _claim_effective


def _identity(root: Path, instrument_id: str, isin: str) -> None:
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


def _cash(source_id: object, account_id: str = "A1") -> dict[str, object]:
    return {
        "provider_id": "broker-a",
        "source_system": "broker-a",
        "record_type": "cash",
        "source_id": source_id,
        "occurred_at": "2024-01-02T10:00:00Z",
        "account_id": account_id,
        "currency": "USD",
        "cash_amount": 10,
    }


def _trade(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "provider_id": "broker-a",
        "source_system": "broker-a",
        "record_type": "transaction",
        "source_id": "trade-1",
        "occurred_at": "2024-01-02T10:00:00Z",
        "account_id": "A1",
        "instrument_id": "SEC-1",
        "currency": "USD",
        "side": "buy",
        "quantity": 1,
        "price": 100,
        "fee_amount": -1,
        "tax_amount": 0,
        "settlement_cash": -101,
    }
    row.update(overrides)
    return row


def test_missing_source_id_is_rejected_not_stringified(tmp_path: Path) -> None:
    """D112-N001"""
    source = _write(tmp_path / "missing.csv", [_cash(None), _cash("None", "A2")])
    frame = PortfolioImportStore(tmp_path).preview(source).frame
    missing = frame.iloc[0]
    assert missing["source_id"] == ""
    assert missing["staging_status"] == "quarantined"
    assert missing["quarantine_reason"] == "missing_source_id"
    assert "None" not in missing["event_key"]


def test_event_key_delimiter_collision_is_impossible(tmp_path: Path) -> None:
    """D112-N002"""
    rows = [_cash("a,b", "acct|a"), _cash("a|b", "acct")]
    rows[0]["source_id"] = "b"
    rows[1]["source_id"] = "a|b"
    rows[0]["account_id"] = "acct|a"
    rows[1]["account_id"] = "acct"
    frame = PortfolioImportStore(tmp_path).preview(_write(tmp_path / "k.csv", rows)).frame
    assert frame["event_key"].nunique() == 2
    assert frame["staging_status"].tolist() == ["accepted", "accepted"]


def test_event_key_unchanged_for_plain_components(tmp_path: Path) -> None:
    frame = PortfolioImportStore(tmp_path).preview(
        _write(tmp_path / "k.csv", [_cash("c1")])
    ).frame
    assert frame.iloc[0]["event_key"] == "broker-a|broker-a|A1|c1"


def test_price_row_is_not_a_ledger_posting_error(tmp_path: Path) -> None:
    """D112-N003"""
    _identity(tmp_path, "SEC-1", "US0000000001")
    price = {
        "provider_id": "broker-a",
        "source_system": "broker-a",
        "record_type": "price",
        "source_id": "px-1",
        "occurred_at": "2024-01-02T00:00:00Z",
        "instrument_id": "SEC-1",
        "currency": "USD",
        "adjusted_close": 101.5,
    }
    app = PortfolioImportApplication(tmp_path)
    preview = app.preview(_write(tmp_path / "px.csv", [price]))
    assert preview.frame.iloc[0]["staging_status"] == "accepted"
    app.commit(preview)
    cutoff = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = app.reconcile(authority="broker", as_of="2025-01-01T00:00:00Z", known_at=cutoff)
    assert [item.kind for item in result.discrepancies] == []
    assert result.active_source_rows == 1


def test_explicit_instrument_id_conflicting_with_isin_is_rejected(tmp_path: Path) -> None:
    """D012-N001"""
    _identity(tmp_path, "SEC-1", "US0000000001")
    _identity(tmp_path, "SEC-2", "US0000000002")
    rows = [
        _trade(source_id="conflict", isin="US0000000002"),
        _trade(source_id="agree", isin="US0000000001"),
        _trade(source_id="id-only"),
    ]
    frame = PortfolioImportStore(tmp_path).preview(_write(tmp_path / "c.csv", rows)).frame
    assert frame["staging_status"].tolist() == ["quarantined", "accepted", "accepted"]
    assert frame.iloc[0]["quarantine_reason"] == "identity_id_isin_conflict"
    assert frame.iloc[0]["instrument_id"] == ""


def test_claim_effective_handles_naive_and_aware_timestamps() -> None:
    """D.C3.S12.N002"""
    claim = {
        "valid_from": "2020-01-01",
        "valid_to": "2030-01-01",
        "available_at": "2020-01-02",
    }
    assert _claim_effective(claim, "2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00")
    assert not _claim_effective(claim, "2019-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00")
    assert not _claim_effective(claim, "2024-01-01T00:00:00+00:00", "2019-06-01T00:00:00+00:00")


def test_spreadsheet_escape_round_trips_source_identity(tmp_path: Path) -> None:
    """D.C3.S12.N003"""
    _identity(tmp_path, "SEC-1", "US0000000001")
    service = PortfolioImportStore(tmp_path)
    service.commit(service.preview(_write(tmp_path / "s.csv", [_cash("-7"), _cash("=X1", "A2")])))
    exported = service.export_canonical(tmp_path / "export.csv")
    other = tmp_path / "other"
    other.mkdir()
    imported = PortfolioImportStore(other)
    imported.commit(imported.preview(exported))
    assert sorted(imported.source_events()["source_id"]) == sorted(
        service.source_events()["source_id"]
    )
