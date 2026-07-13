from __future__ import annotations

from pathlib import Path

import pytest
import pandas as pd

from etf_cockpit.data.fund_documents import (
    DOCUMENT_TYPES,
    build_document_inventory,
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


def test_trust_artifact_inventory_emits_missing_rows_for_each_configured_instrument() -> None:
    inventory = trust_artifacts._etf_disclosure_inventory(pd.DataFrame({"instrument_id": ["VWCE", "LYP6"]}))
    assert len(inventory) == 2 * len(DOCUMENT_TYPES)
    assert inventory["coverage_status"].eq("missing").all()
    assert inventory["executable_authority"].eq(False).all()


def test_trust_inventory_uses_configured_etf_ids_even_when_identity_is_incomplete() -> None:
    inventory = trust_artifacts._etf_disclosure_inventory(pd.DataFrame({"instrument_id": ["not-configured"]}), configured_etf_ids=["VWCE", "LYP6"])
    assert set(inventory["instrument_id"]) == {"VWCE", "LYP6"}
    assert len(inventory) == 2 * len(DOCUMENT_TYPES)
