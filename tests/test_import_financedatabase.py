from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket

import pytest

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow
from scripts import import_financedatabase as importer

HEADER = "symbol,name,currency,summary,category_group,category,family,exchange,mic,isin,delisted"
REVISION = "91c2264299d4742db2775ed029bec055f0c780ff"
IMPORTED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
OFFICIAL_ISIN = "IE00B3RBWM25"


def _fixture(tmp_path: Path) -> tuple[Path, str]:
    folder = tmp_path / "financedatabase"
    (folder / "database" / "etfs").mkdir(parents=True)
    (folder / "database" / "equities").mkdir()
    etf_csv = folder / "database" / "etfs" / "AMS.csv"
    etf_csv.write_text(
        "\n".join(
            [
                HEADER,
                f"VWRL.AS,Hint Name,EUR,,Equities,Large Blend,Hint Family,AMS,XAMS,{OFFICIAL_ISIN},False",
                "NOISIN.AS,No Isin Fund,EUR,,Equities,,Fam,AMS,XAMS,,False",
                "GONE.AS,Delisted Fund,EUR,,Equities,,Fam,AMS,XAMS,IE0000000002,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (folder / "database" / "equities" / "AMS.csv").write_text(
        "symbol,name,summary,currency,sector,industry_group,industry,exchange,mic,market,country,state,city,"
        "zipcode,website,market_cap,isin,cusip,figi,composite_figi,shareclass_figi,delisted\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(etf_csv.read_bytes()).hexdigest()
    empty = hashlib.sha256((folder / "database" / "equities" / "AMS.csv").read_bytes()).hexdigest()
    (folder / "SOURCE.json").write_text(
        json.dumps(
            {
                "repo": "JerBouma/FinanceDatabase",
                "version": "2.5.1",
                "revision": REVISION,
                "license": "MIT",
                "files": [
                    {"file": "data/imports/financedatabase/2.5.1-91c22642/database/etfs/AMS.csv", "sha256": digest},
                    {"file": "data/imports/financedatabase/2.5.1-91c22642/database/equities/AMS.csv", "sha256": empty},
                ],
            }
        ),
        encoding="utf-8",
    )
    return folder, digest


def _official(isin: str = OFFICIAL_ISIN) -> IdentitySourceRow:
    return IdentitySourceRow(
        row_id="official:1",
        instrument_id="SEC-VWRL",
        object_type="instrument",
        object_id="SEC-VWRL",
        parent_object_id=None,
        relationship=None,
        identifiers={"isin": isin},
        attributes={"name": "Official Name", "currency": "EUR", "provider_symbol": "VWRL.L"},
        source="issuer_register",
        authority=SourceAuthority.OFFICIAL,
        source_id="official:1",
        valid_from="2024-01-01T00:00:00Z",
        available_at="2024-01-02T00:00:00Z",
    )


def test_hint_never_overrides_an_official_identity(tmp_path: Path) -> None:
    folder, _ = _fixture(tmp_path)
    store_root = tmp_path / "store"
    with IdentityMasterStore(store_root) as store:
        store.import_rows([_official()])
        importer.import_financedatabase(folder, store, imported_at=IMPORTED_AT)
        resolution = store.resolve("SEC-VWRL")
    assert resolution.identity.name == "Official Name"
    hints = [c for c in resolution.claims if c.source == "financedatabase"]
    assert hints and {c.authority for c in hints} == {SourceAuthority.COMMUNITY}
    assert {c.field for c in hints} >= {"name", "provider_symbol"}
    assert all(c.valid_from is None and c.valid_to is None for c in hints)
    assert resolution.execution_allowed is False


def test_offline_import_records_file_hash_and_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder, digest = _fixture(tmp_path)

    def _no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    with IdentityMasterStore(tmp_path / "store") as store:
        summary = importer.import_financedatabase(folder, store, imported_at=IMPORTED_AT)
        rows = [r.payload["row"] for r in store._store.list("identity_source_row_v1")]
    assert summary["rows_imported"] == 2 and summary["rows_skipped_delisted"] == 1
    assert {r["source"] for r in rows} == {"financedatabase"}
    assert {r["authority"] for r in rows} == {"community"}
    assert {r["source_checksum"] for r in rows} == {digest}
    assert {datetime.fromisoformat(r["retrieved_at"].replace("Z", "+00:00")) for r in rows} == {IMPORTED_AT}
    assert all("2.5.1" in r["source_id"] and REVISION[:8] in r["source_id"] for r in rows)
    assert all(r["valid_from"] is None and r["valid_to"] is None for r in rows)


def test_tampered_file_is_refused(tmp_path: Path) -> None:
    folder, _ = _fixture(tmp_path)
    with (folder / "database" / "etfs" / "AMS.csv").open("a", encoding="utf-8") as handle:
        handle.write("EVIL.AS,Evil,EUR,,,,,AMS,XAMS,IE0000000003,False\n")
    with IdentityMasterStore(tmp_path / "store") as store:
        with pytest.raises(ValueError, match="sha256"):
            importer.import_financedatabase(folder, store, imported_at=IMPORTED_AT)
