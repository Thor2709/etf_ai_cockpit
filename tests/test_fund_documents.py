from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import pandas as pd

from etf_cockpit.data.fund_documents import (
    DOCUMENT_TYPES,
    build_document_inventory,
    import_etf_document,
    register_document,
    write_document_registry,
)
from etf_cockpit.data import trust_artifacts


def test_document_registry_retains_checksum_and_missing_state(tmp_path: Path) -> None:
    path = tmp_path / "kid.pdf"
    path.write_bytes(b"fixture")
    document = register_document(path, "priips_kid", "VWCE", "https://issuer.example/kid.pdf", "issuer")
    assert document.sha256
    assert document.coverage_status == "available"
    with pytest.raises(ValueError):
        register_document(tmp_path / "missing.pdf", "factsheet", "VWCE", "https://issuer.example/factsheet.pdf", "issuer")


def test_document_registry_rejects_unknown_type_and_bad_date(tmp_path: Path) -> None:
    path = tmp_path / "kid.pdf"
    path.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="document_type"):
        register_document(path, "marketing", "VWCE", "https://issuer.example/kid.pdf", "issuer")
    with pytest.raises(ValueError, match="document_date"):
        register_document(path, "kid", "VWCE", "https://issuer.example/kid.pdf", "issuer", document_date="not-a-date")


@pytest.mark.parametrize(
    "future_date",
    [
        datetime.now(timezone.utc) + timedelta(days=1),
        date.today() + timedelta(days=1),
        (date.today() + timedelta(days=1)).isoformat(),
    ],
)
def test_document_registry_rejects_future_dates_fail_closed(tmp_path: Path, future_date: object) -> None:
    path = tmp_path / "factsheet.pdf"
    path.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="future document_date"):
        register_document(path, "factsheet", "VWCE", "", "issuer", document_date=future_date)


def test_document_import_path_registers_and_persists_inventory(tmp_path: Path) -> None:
    source = tmp_path / "factsheet.pdf"
    source.write_bytes(b"fixture")
    destination = tmp_path / "fund_documents.parquet"
    imported = import_etf_document(
        source,
        instrument_id="VWCE",
        document_type="factsheet",
        source_url="",
        authority="issuer",
        destination=destination,
        configured_instrument_ids=["VWCE"],
    )
    assert imported.document_type == "factsheet"
    stored = pd.read_parquet(destination)
    assert stored.loc[stored["document_type"] == "factsheet", "coverage_status"].eq("available").any()


def test_document_import_preserves_registry_instrument_omitted_from_configured_ids(tmp_path: Path) -> None:
    prior_source = tmp_path / "disabled-factsheet.pdf"
    prior_source.write_bytes(b"disabled instrument document")
    prior = register_document(
        prior_source,
        "factsheet",
        "DISABLED",
        "https://issuer.example/disabled/factsheet.pdf",
        "issuer",
        document_date="2026-07-10",
    )
    destination = tmp_path / "fund_documents.parquet"
    write_document_registry([prior], destination=destination)

    imported_source = tmp_path / "vwce-kid.pdf"
    imported_source.write_bytes(b"new instrument document")
    import_etf_document(
        imported_source,
        instrument_id="VWCE",
        document_type="kid",
        destination=destination,
        configured_instrument_ids=["VWCE"],
        document_date="2026-07-11",
    )

    stored = pd.read_parquet(destination)
    assert set(stored["instrument_id"]) == {"DISABLED", "VWCE"}
    retained = stored.loc[stored["source_id"] == prior.source_id].iloc[0]
    assert retained["coverage_status"] == "available"
    disabled_rows = stored[stored["instrument_id"] == "DISABLED"]
    assert disabled_rows["document_type"].nunique() == len(DOCUMENT_TYPES)
    assert disabled_rows.loc[disabled_rows["document_type"] != "factsheet", "coverage_status"].eq("missing").all()


def test_document_inventory_has_every_type_for_every_configured_etf_and_dedupes_exact_versions(tmp_path: Path) -> None:
    path = tmp_path / "factsheet.pdf"
    path.write_bytes(b"same document")
    first = register_document(path, "factsheet", "VWCE", "https://issuer.example/factsheet.pdf", "issuer", document_date="2026-07-10")
    duplicate = register_document(path, "factsheet", "VWCE", "https://issuer.example/factsheet-copy.pdf", "issuer", document_date="2026-07-10")
    inventory = build_document_inventory(["VWCE", "LYP6"], [first, duplicate])
    assert len(inventory) == 2 * len(DOCUMENT_TYPES)
    assert inventory.loc[(inventory["instrument_id"] == "VWCE") & (inventory["document_type"] == "factsheet"), "coverage_status"].tolist() == ["available"]
    assert (inventory["coverage_status"] == "missing").sum() == (2 * len(DOCUMENT_TYPES) - 1)
    assert inventory["source_id"].is_unique


def test_document_registry_is_persisted_atomically_with_version_and_checksum(tmp_path: Path) -> None:
    path = tmp_path / "kid.pdf"
    path.write_bytes(b"fixture")
    document = register_document(path, "kid", "VWCE", "https://issuer.example/kid.pdf", "issuer", document_date="2026-07-10")
    destination = tmp_path / "fund_documents.parquet"
    written = write_document_registry([document], destination=destination)
    assert written == destination
    stored = __import__("pandas").read_parquet(destination)
    assert {"schema_version", "source_id", "checksum", "document_date", "document_type"} <= set(stored.columns)


def test_document_registry_backfills_blank_source_id_from_provenance(tmp_path: Path) -> None:
    destination = tmp_path / "fund_documents.parquet"
    write_document_registry(
        pd.DataFrame(
            {
                "instrument_id": ["VWCE"],
                "document_type": ["factsheet"],
                "path": [""],
                "source_url": ["https://issuer.example/factsheet.pdf"],
                "authority": ["issuer_document"],
                "sha256": ["a" * 64],
                "document_date": ["2026-07-10"],
                "coverage_status": ["missing"],
                "source_id": [""],
            }
        ),
        destination=destination,
    )
    stored = pd.read_parquet(destination)
    assert stored.loc[0, "source_id"].startswith("funddoc:")


def test_trust_artifact_inventory_emits_missing_rows_for_each_configured_instrument() -> None:
    inventory = trust_artifacts._etf_disclosure_inventory(pd.DataFrame({"instrument_id": ["VWCE", "LYP6"]}))
    assert len(inventory) == 2 * len(DOCUMENT_TYPES)
    assert inventory["coverage_status"].eq("missing").all()
    assert inventory["executable_authority"].eq(False).all()


def test_trust_inventory_uses_configured_etf_ids_even_when_identity_is_incomplete() -> None:
    inventory = trust_artifacts._etf_disclosure_inventory(pd.DataFrame({"instrument_id": ["not-configured"]}), configured_etf_ids=["VWCE", "LYP6"])
    assert set(inventory["instrument_id"]) == {"VWCE", "LYP6"}
    assert len(inventory) == 2 * len(DOCUMENT_TYPES)


def test_trust_inventory_reads_canonical_registry_and_preserves_registered_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "factsheet.pdf"
    path.write_bytes(b"registered factsheet")
    registered = register_document(
        path,
        "factsheet",
        "VWCE",
        "https://issuer.example/vwce/factsheet.pdf",
        "issuer_document",
        document_date="2026-07-10",
    )
    registry_path = tmp_path / "fund_documents.parquet"
    write_document_registry([registered], destination=registry_path)
    monkeypatch.setattr(trust_artifacts, "FUND_DOCUMENTS_PATH", registry_path)

    inventory = trust_artifacts._etf_disclosure_inventory(
        pd.DataFrame({"instrument_id": ["ignored"], "instrument_type": ["etf"]}),
        configured_etf_ids=["VWCE", "LYP6"],
    )
    row = inventory[(inventory["instrument_id"] == "VWCE") & (inventory["document_type"] == "factsheet")].iloc[0]
    assert row["source_id"] == registered.source_id
    assert row["document_id"] == registered.source_id
    assert row["source_url"] == registered.source_url
    assert row["as_of_date"] == registered.document_date
    assert row["checksum"] == registered.sha256
    assert len(inventory) == 2 * len(DOCUMENT_TYPES)
    assert inventory.loc[inventory["instrument_id"] == "LYP6", "coverage_status"].eq("missing").all()


def test_trust_inventory_falls_back_to_explicit_missing_rows_when_registry_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trust_artifacts, "FUND_DOCUMENTS_PATH", tmp_path / "absent.parquet")
    inventory = trust_artifacts._etf_disclosure_inventory(
        pd.DataFrame({"instrument_id": ["VWCE"], "instrument_type": ["etf"]}),
        configured_etf_ids=["VWCE"],
    )
    assert len(inventory) == len(DOCUMENT_TYPES)
    assert inventory["coverage_status"].eq("missing").all()
