from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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


def test_statement_fact_and_inventory_writes_merge_prior_ciks_without_duplicates(tmp_path: Path) -> None:
    first_path = tmp_path / "first.json"
    first_path.write_text(json.dumps({"cik": 1, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 1, "end": "2024-12-31", "accn": "a"}]}}}}}), encoding="utf-8")
    second_path = tmp_path / "second.json"
    second_path.write_text(json.dumps({"cik": 2, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 2, "end": "2024-12-31", "accn": "b"}]}}}}}), encoding="utf-8")
    first = parse_companyfacts(first_path, _identity("1"))
    second = parse_companyfacts(second_path, _identity("2"))
    facts_destination = tmp_path / "statement_facts.parquet"
    inventory_destination = tmp_path / "filings_statements.parquet"
    write_statement_facts(first.records, facts_destination)
    write_statement_facts(second.records, facts_destination)
    write_statement_inventory(RawDocument(first_path, "https://data.sec.gov/first", datetime.now(timezone.utc), first.source_sha256, "sec_edgar", "sec_companyfacts", "application/json", 200), first.records, inventory_destination)
    write_statement_inventory(RawDocument(second_path, "https://data.sec.gov/second", datetime.now(timezone.utc), second.source_sha256, "sec_edgar", "sec_companyfacts", "application/json", 200), second.records, inventory_destination)
    import pandas as pd

    facts = pd.read_parquet(facts_destination)
    inventory = pd.read_parquet(inventory_destination)
    assert set(facts["cik"].astype(str)) == {"1", "2"}
    assert len(facts) == 2
    assert set(inventory["checksum"].astype(str)) == {first.source_sha256, second.source_sha256}
    assert len(inventory) == 2


def test_sec_import_does_not_attribute_unresolved_cik_to_selected_etf(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_text(
        json.dumps({"cik": 3, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 3, "end": "2024-12-31"}]}}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "statement_facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "filings_statements.parquet")
    state = state_module.AppState.__new__(state_module.AppState)
    state.selected_etf = "SELECTED_ETF"
    state.snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=[])))
    state.last_message = "Ready"

    message = state.import_sec_companyfacts(payload_path)

    assert "complete" in message
    import pandas as pd

    facts = pd.read_parquet(tmp_path / "statement_facts.parquet")
    assert facts["instrument_id"].iat[0] != "SELECTED_ETF"
    assert str(facts["instrument_id"].iat[0]).startswith("sec_unresolved_")
    assert str(facts["cik"].iat[0]) == "3"
