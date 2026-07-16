from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning
from etf_cockpit.parsers.index_methodology import IndexMethodologyRecord
from etf_cockpit.parsers.priips_kid import PriipsKidRecord


def _kid_result() -> ParseResult[PriipsKidRecord]:
    record = PriipsKidRecord(
        product="Example ETF",
        isin="IE000Q4J3CW6",
        manufacturer="Vanguard",
        sri=4,
        cost_fields={"entry_costs": "EUR 0"},
        holding_period_years=5,
        scenarios=("moderate",),
        document_date="2026-04-14",
        extraction_confidence="high",
        warnings=(),
        source_sha256="a" * 64,
        source_pages=(1, 2),
        score_eligible=True,
    )
    return ParseResult((record,), (), "priips_kid", "2.0", "a" * 64, True)


def _methodology_result() -> ParseResult[IndexMethodologyRecord]:
    record = IndexMethodologyRecord(
        provider="FTSE Russell",
        index_series="FTSE Global Equity Index Series",
        version="14.2",
        document_date="July 2026",
        eligibility_rules=("Eligible securities",),
        weighting_rules=("Capitalisation weighting",),
        review_frequency="Quarterly review",
        caps=("5% cap",),
        source_pages=(1, 3),
        confidence="high",
        warnings=(),
        source_sha256="b" * 64,
        score_eligible=True,
    )
    return ParseResult((record,), (), "index_methodology", "2.0", "b" * 64, True)


def test_parsed_kid_persistence_is_versioned_checksum_keyed_and_idempotent(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_priips_kid_result, read_priips_kid_records

    destination = tmp_path / "priips_kid_records.parquet"
    persist_priips_kid_result(_kid_result(), "VWCE", destination=destination)
    persist_priips_kid_result(_kid_result(), "VWCE", destination=destination)

    frame = read_priips_kid_records(destination)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["schema_version"] == 2
    assert row["source_id"].startswith("parsed:kid:")
    assert row["source_sha256"] == "a" * 64
    assert row["source_pages"] == "[1, 2]"


def test_parsed_methodology_persistence_retains_warning_pages_and_manual_state(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_index_methodology_result, read_index_methodology_records

    warning = ParseWarning("methodology_holdings_conflict", "conflict", "warning", "page 3")
    result = ParseResult(
        (_methodology_result().records[0],),
        (warning,),
        "index_methodology",
        "2.0",
        "b" * 64,
        False,
    )
    destination = tmp_path / "index_methodology_records.parquet"
    persist_index_methodology_result(result, "VWCE", destination=destination)

    row = read_index_methodology_records(destination).iloc[0]
    assert row["provider"] == "FTSE Russell"
    assert row["source_pages"] == "[1, 3]"
    assert "methodology_holdings_conflict" in row["warnings"]
    assert bool(row["manual_review"]) is True


def test_methodology_persistence_attaches_real_holdings_conflict(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_index_methodology_result, read_index_methodology_records

    destination = tmp_path / "index_methodology_records.parquet"
    holdings = pd.DataFrame({"security": ["Large"], "weight": [0.08], "region": ["Developed Markets"]})
    persist_index_methodology_result(_methodology_result(), "VWCE", destination=destination, holdings=holdings)

    row = read_index_methodology_records(destination).iloc[0]
    assert "methodology_holdings_conflict" in row["warnings"]
    assert bool(row["manual_review"]) is True
    assert bool(row["score_eligible"]) is False


def test_methodology_holdings_unavailable_retains_source_document_provenance(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.data.fund_documents import read_document_registry

    source = tmp_path / "methodology.pdf"
    source.write_bytes(b"methodology source")
    registry = tmp_path / "fund_documents.parquet"
    parsed.persist_index_methodology_with_document(
        _methodology_result(),
        "VWCE",
        source,
        destination=tmp_path / "index_methodology_records.parquet",
        registry_destination=registry,
        holdings=pd.DataFrame(),
    )

    methodology = read_document_registry(path=registry).loc[lambda frame: frame["document_type"].eq("methodology")].iloc[0]
    assert methodology["coverage_status"] == "available"
    assert methodology["path"] == str(source)
    assert methodology["sha256"]


def test_combined_kid_import_publishes_parsed_store_and_registry_atomically(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed

    source = tmp_path / "kid.pdf"
    source.write_bytes(b"kid source")
    destination = tmp_path / "priips_kid_records.parquet"
    registry = tmp_path / "fund_documents.parquet"

    assert hasattr(parsed, "persist_priips_kid_with_document")
    parsed.persist_priips_kid_with_document(
        _kid_result(),
        "VWCE",
        source,
        destination=destination,
        registry_destination=registry,
    )

    assert len(pd.read_parquet(destination)) == 1
    registry_frame = pd.read_parquet(registry)
    assert set(registry_frame["document_type"]) >= {"kid"}


def test_failed_kid_import_is_unavailable_and_does_not_retain_ephemeral_path(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.data.fund_documents import read_document_registry

    source = tmp_path / "mismatched-kid.pdf"
    source.write_bytes(b"mismatched kid source")
    result = ParseResult(
        (),
        (ParseWarning("identity_mismatch", "KID identity does not match the configured instrument", "error", "page 1"),),
        "priips_kid",
        "2.0",
        "c" * 64,
        False,
    )
    destination = tmp_path / "priips_kid_records.parquet"
    registry = tmp_path / "fund_documents.parquet"

    parsed.persist_priips_kid_with_document(
        result,
        "VWCE",
        source,
        destination=destination,
        registry_destination=registry,
    )

    row = pd.read_parquet(destination).iloc[0]
    assert bool(row["manual_review"]) is True
    assert bool(row["success"]) is False
    registered = read_document_registry(path=registry)
    kid = registered.loc[registered["document_type"].eq("kid")].iloc[0]
    assert kid["coverage_status"] == "unavailable"
    assert kid["path"] == ""
    assert "identity_mismatch" in kid["warnings"]


def test_failed_kid_import_supersedes_preexisting_missing_inventory_row(tmp_path: Path) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.data.fund_documents import build_document_inventory, read_document_registry, write_document_registry

    source = tmp_path / "mismatched-kid.pdf"
    source.write_bytes(b"mismatched kid source")
    registry = tmp_path / "fund_documents.parquet"
    write_document_registry(build_document_inventory(["VWCE"]), destination=registry)
    result = ParseResult(
        (),
        (ParseWarning("identity_mismatch", "KID identity does not match the configured instrument", "error", "page 1"),),
        "priips_kid",
        "2.0",
        "d" * 64,
        False,
    )

    parsed.persist_priips_kid_with_document(
        result,
        "VWCE",
        source,
        destination=tmp_path / "priips_kid_records.parquet",
        registry_destination=registry,
    )

    kid = read_document_registry(path=registry).loc[lambda frame: frame["document_type"].eq("kid")].iloc[0]
    assert kid["coverage_status"] == "unavailable"
    assert "identity_mismatch" in kid["warnings"]
    assert kid["path"] == ""


def test_combined_kid_import_rolls_back_when_registry_stage_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.parsed_disclosures as parsed
    from etf_cockpit.core import atomic_io

    source = tmp_path / "kid.pdf"
    source.write_bytes(b"kid source")
    destination = tmp_path / "priips_kid_records.parquet"
    registry = tmp_path / "fund_documents.parquet"
    parsed.persist_priips_kid_with_document(_kid_result(), "VWCE", source, destination=destination, registry_destination=registry)
    prior = {
        path: path.read_bytes()
        for path in (destination, destination.with_suffix(".csv"), registry, registry.with_suffix(".csv"))
    }

    real_atomic_write_group = atomic_io.atomic_write_group

    def fail_registry_stage(requests, **kwargs):
        staged = []
        for request in tuple(requests):
            if request.destination.resolve() == registry.resolve():
                staged.append(atomic_io.AtomicWriteRequest(request.destination, request.payload, lambda _path: (_ for _ in ()).throw(OSError("registry validation failed"))))
            else:
                staged.append(request)
        return real_atomic_write_group(tuple(staged), **kwargs)

    monkeypatch.setattr(parsed, "atomic_write_group", fail_registry_stage)
    with pytest.raises(OSError, match="registry validation failed"):
        parsed.persist_priips_kid_with_document(_kid_result(), "LYP6", source, destination=destination, registry_destination=registry)

    assert {path: path.read_bytes() for path in prior} == prior


def test_corrupt_parsed_store_fails_closed_without_overwriting_prior_bytes(tmp_path: Path) -> None:
    from etf_cockpit.data.parsed_disclosures import persist_priips_kid_result

    destination = tmp_path / "corrupt.parquet"
    destination.write_bytes(b"corrupt parquet bytes")
    prior = destination.read_bytes()

    with pytest.raises(ValueError, match="corrupt"):
        persist_priips_kid_result(_kid_result(), "VWCE", destination=destination)

    assert destination.read_bytes() == prior
