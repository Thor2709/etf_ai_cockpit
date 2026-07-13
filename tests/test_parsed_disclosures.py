from __future__ import annotations

from pathlib import Path

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
