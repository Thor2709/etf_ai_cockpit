from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.sec_facts import parse_companyfacts, write_statement_facts, write_statement_inventory


FIXTURE = Path("tests/fixtures/official/sec_companyfacts/microsoft-companyfacts.json")


def _identity(cik: str | None = "789019") -> CanonicalIdentity:
    return CanonicalIdentity("MSFT", "Microsoft Corporation", None, "needs_verification", "MSFT", "NASDAQ", "USD", "stock", {"yahoo": "MSFT"}, "high", (), cik)


def test_real_sec_fixture_retains_official_fact_provenance() -> None:
    result = parse_companyfacts(FIXTURE, _identity())
    assert result.success is True
    assert result.records
    assert any(record.concept in {"Revenue", "Assets", "NetIncomeLoss"} for record in result.records)
    fact = result.records[0]
    assert fact.cik == "789019"
    assert fact.unit
    assert fact.filed
    assert fact.source_id


def test_wrong_cik_fails_without_inventing_values() -> None:
    result = parse_companyfacts(FIXTURE, _identity("1"))
    assert result.success is False
    assert result.records == ()
    assert any(warning.code == "identity_mismatch" for warning in result.warnings)


def test_ambiguous_units_are_warned_and_skipped(tmp_path: Path) -> None:
    payload = {"entityName": "X", "cik": 1, "facts": {"us-gaap": {"Revenue": {"label": "Revenue", "units": {"USD": [{"val": 1}], "shares": [{"val": 2}]}}}}}
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = parse_companyfacts(path, _identity("1"))
    assert result.records == ()
    assert any(warning.code == "ambiguous_unit" for warning in result.warnings)


def test_custom_concepts_are_retained_but_not_auto_mapped_and_duplicates_are_deduplicated(tmp_path: Path) -> None:
    entry = {"val": 10, "start": "2024-01-01", "end": "2024-12-31", "accn": "0001-24-000001", "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-01-20"}
    payload = {
        "cik": 1,
        "facts": {
            "us-gaap": {"Revenues": {"units": {"USD": [entry, dict(entry)]}}},
            "microsoft": {"AdjustedRevenue": {"units": {"USD": [{**entry, "val": 11}]}}},
        },
    }
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = parse_companyfacts(path, _identity("1"))

    assert result.success is True
    assert len(result.records) == 2
    revenue = next(record for record in result.records if record.concept == "Revenues")
    custom = next(record for record in result.records if record.concept == "AdjustedRevenue")
    assert revenue.canonical_metric == "revenue"
    assert custom.canonical_metric is None
    assert custom.is_custom is True
    assert any(warning.code == "duplicate_fact" for warning in result.warnings)
    assert any(warning.code == "custom_concept" for warning in result.warnings)


def test_statement_facts_persist_with_source_ids(tmp_path: Path) -> None:
    result = parse_companyfacts(FIXTURE, _identity())
    destination = tmp_path / "statement_facts.parquet"
    write_statement_facts(result.records, destination)
    import pandas as pd

    frame = pd.read_parquet(destination)
    assert {"source_id", "taxonomy", "concept", "unit", "value"} <= set(frame.columns)
    assert frame["source_id"].astype(str).str.startswith("sec_edgar:").all()


def test_statement_inventory_persists_official_source_and_mapping_ids(tmp_path: Path) -> None:
    result = parse_companyfacts(FIXTURE, _identity())
    document = RawDocument(FIXTURE, "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json", datetime.now(timezone.utc), result.source_sha256, "sec_edgar", "sec_companyfacts", "application/json", 200)
    destination = tmp_path / "filings_statements.parquet"
    write_statement_inventory(document, result.records, destination)
    import pandas as pd

    row = pd.read_parquet(destination).iloc[0]
    assert row["source_authority"] == "official_regulator"
    assert row["coverage_status"] == "imported"
    assert int(row["fact_count"]) == len(result.records)
    assert "sec_edgar:" in str(row["source_ids"])
