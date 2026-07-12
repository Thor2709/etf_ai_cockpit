from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.esef_ixbrl import XbrlFact
from etf_cockpit.parsers.sec_facts import StatementFact, parse_companyfacts, select_authoritative_facts, write_statement_facts, write_statement_inventory


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
    assert frame["schema_version"].eq("statement_facts.v1").all()
    assert frame["source_id"].astype(str).str.startswith("sec_edgar:").all()


def test_statement_inventory_persists_official_source_and_mapping_ids(tmp_path: Path) -> None:
    result = parse_companyfacts(FIXTURE, _identity())
    document = RawDocument(FIXTURE, "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json", datetime.now(timezone.utc), result.source_sha256, "sec_edgar", "sec_companyfacts", "application/json", 200)
    destination = tmp_path / "filings_statements.parquet"
    write_statement_inventory(document, result.records, destination)
    import pandas as pd

    row = pd.read_parquet(destination).iloc[0]
    assert row["schema_version"] == "filings_statements.v1"
    assert row["source_authority"] == "official_regulator"
    assert row["coverage_status"] == "imported"
    assert int(row["fact_count"]) == len(result.records)
    assert "sec_edgar:" in str(row["source_ids"])


def test_unmapped_standard_ifrs_fact_is_not_misclassified_as_custom() -> None:
    from etf_cockpit.parsers.sec_facts import statement_facts_from_esef

    fact = XbrlFact(
        "7245003GZ2696Y0W1X57",
        "SomeStandardConcept",
        "1",
        "EUR",
        "0",
        "ctx",
        None,
        "2025-12-31",
        "report.xhtml",
        "unmapped",
        (),
        "https://xbrl.ifrs.org/taxonomy/ifrs-full",
    )
    result = statement_facts_from_esef((fact,), instrument_id="NL_ENTITY", source_sha256="a" * 64)

    assert result[0].taxonomy == "ifrs-full"
    assert result[0].mapping_status == "unmapped"
    assert result[0].is_custom is False


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


def test_sec_import_resolves_known_cik_from_identity_store(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    import pandas as pd

    payload_path = tmp_path / "facts.json"
    payload_path.write_text(json.dumps({"cik": 789019, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 3, "end": "2024-12-31"}]}}}}}), encoding="utf-8")
    identity_path = tmp_path / "instrument_identity.parquet"
    pd.DataFrame([{"instrument_id": "MSFT", "cik": "789019"}]).to_parquet(identity_path, index=False)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", identity_path)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "statement_facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "filings_statements.parquet")
    state = state_module.AppState.__new__(state_module.AppState)
    state.selected_etf = "SELECTED_ETF"
    state.last_message = "Ready"

    assert "manual identity review" not in state.import_sec_companyfacts(payload_path)
    assert pd.read_parquet(tmp_path / "statement_facts.parquet")["instrument_id"].iat[0] == "MSFT"


def test_sec_import_rejects_mismatched_supplied_instrument_id(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    import pandas as pd

    payload_path = tmp_path / "facts.json"
    payload_path.write_text(json.dumps({"cik": 789019, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 3, "end": "2024-12-31"}]}}}}}), encoding="utf-8")
    identity_path = tmp_path / "instrument_identity.parquet"
    pd.DataFrame([{"instrument_id": "MSFT", "cik": "789019"}]).to_parquet(identity_path, index=False)
    facts_path = tmp_path / "statement_facts.parquet"
    inventory_path = tmp_path / "filings_statements.parquet"
    monkeypatch.setattr(state_module, "IDENTITY_PATH", identity_path)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", facts_path)
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", inventory_path)
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"

    message = state.import_sec_companyfacts(payload_path, instrument_id="WRONG")

    assert "No data changed" in message
    assert not facts_path.exists()
    assert not inventory_path.exists()


def test_sec_claim_selection_prefers_only_matching_official_fact() -> None:
    result = parse_companyfacts(FIXTURE, _identity())
    official = next(record for record in result.records if record.canonical_metric == "revenue")
    matching_vendor = {"instrument_id": "MSFT", "concept": "revenue", "unit": official.unit, "start": official.start, "end": official.end, "fiscal_period": official.fiscal_period, "value": 1}
    other_period_vendor = {"instrument_id": "MSFT", "concept": "revenue", "unit": official.unit, "start": "1999-01-01", "end": "1999-12-31", "fiscal_period": official.fiscal_period, "value": 2}

    selected = select_authoritative_facts((official,), (matching_vendor, other_period_vendor))

    assert selected[0] is official
    assert selected[1] == other_period_vendor


def test_sec_claim_selection_is_deterministic_for_amended_duplicate_filings() -> None:
    common = dict(instrument_id="MSFT", cik="789019", taxonomy="us-gaap", concept="Revenues", unit="USD", value=1, start="2024-01-01", end="2024-12-31", instant=None, form="10-K", fiscal_year=2024, fiscal_period="FY", canonical_metric="revenue", mapping_status="mapped", is_custom=False)
    older = StatementFact(**common, filed="2025-01-20", accession="0001", source_id="sec_edgar:older")
    amended = StatementFact(**common, filed="2025-02-20", accession="0002", source_id="sec_edgar:amended")
    vendor = {"instrument_id": "MSFT", "concept": "revenue", "unit": "USD", "start": "2024-01-01", "end": "2024-12-31", "fiscal_period": "FY", "value": 99}

    selected = select_authoritative_facts((older, amended), (vendor,))

    assert selected == (amended,)


def test_statement_store_persists_authority_selection_for_matching_vendor_claim(tmp_path: Path) -> None:
    common = dict(instrument_id="MSFT", cik="789019", taxonomy="us-gaap", concept="Revenues", unit="USD", value=1, start="2024-01-01", end="2024-12-31", instant=None, form="10-K", fiscal_year=2024, fiscal_period="FY", canonical_metric="revenue", mapping_status="mapped", is_custom=False)
    older = StatementFact(**common, filed="2025-01-20", accession="0001", source_id="sec_edgar:older")
    amended = StatementFact(**common, filed="2025-02-20", accession="0002", source_id="sec_edgar:amended")
    vendor = {"instrument_id": "MSFT", "concept": "revenue", "unit": "USD", "start": "2024-01-01", "end": "2024-12-31", "fiscal_period": "FY", "value": 99}
    destination = tmp_path / "statement_facts.parquet"

    write_statement_facts((older, amended), destination, vendor_records=(vendor,))

    import pandas as pd

    frame = pd.read_parquet(destination).set_index("source_id")
    assert frame.loc["sec_edgar:amended", "authority_selection"] == "canonical_sec"
    assert frame.loc["sec_edgar:older", "authority_selection"] == "retained_sec"


def test_statement_store_recomputes_authority_across_sequential_imports(tmp_path: Path) -> None:
    common = dict(instrument_id="MSFT", cik="789019", taxonomy="us-gaap", concept="Revenues", unit="USD", value=1, start="2024-01-01", end="2024-12-31", instant=None, form="10-K", fiscal_year=2024, fiscal_period="FY", canonical_metric="revenue", mapping_status="mapped", is_custom=False)
    older = StatementFact(**common, filed="2025-01-20", accession="0001", source_id="sec_edgar:older")
    amended = StatementFact(**common, filed="2025-02-20", accession="0002", source_id="sec_edgar:amended")
    vendor = {"instrument_id": "MSFT", "concept": "revenue", "unit": "USD", "start": "2024-01-01", "end": "2024-12-31", "fiscal_period": "FY", "value": 99}
    destination = tmp_path / "statement_facts.parquet"

    write_statement_facts((older,), destination, vendor_records=(vendor,))
    write_statement_facts((amended,), destination, vendor_records=(vendor,))

    import pandas as pd

    frame = pd.read_parquet(destination).set_index("source_id")
    assert frame.loc["sec_edgar:amended", "authority_selection"] == "canonical_sec"
    assert frame.loc["sec_edgar:older", "authority_selection"] == "retained_sec"


def test_sec_claim_selection_does_not_collapse_annual_and_quarterly_same_end() -> None:
    common = dict(instrument_id="MSFT", cik="789019", taxonomy="us-gaap", concept="Revenues", unit="USD", value=1, instant=None, form="10-K", fiscal_year=2024, canonical_metric="revenue", mapping_status="mapped", is_custom=False)
    annual = StatementFact(**common, start="2024-01-01", end="2024-12-31", filed="2025-01-20", accession="annual", fiscal_period="FY", source_id="sec_edgar:annual")
    quarter = StatementFact(**common, start="2024-10-01", end="2024-12-31", filed="2025-01-20", accession="quarter", fiscal_period="Q4", source_id="sec_edgar:quarter")
    vendor = {"instrument_id": "MSFT", "concept": "revenue", "unit": "USD", "start": "2024-01-01", "end": "2024-12-31", "fiscal_period": "FY", "value": 9}

    selected = select_authoritative_facts((annual, quarter), (vendor,))

    assert selected == (annual, quarter)


def test_end_only_sec_fact_is_normalised_as_instant_for_exact_precedence(tmp_path: Path) -> None:
    path = tmp_path / "instant.json"
    path.write_text(json.dumps({"cik": 1, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 1, "end": "2024-12-31", "form": "10-K", "filed": "2025-01-20"}]}}}}}), encoding="utf-8")
    result = parse_companyfacts(path, _identity("1"))
    fact = result.records[0]
    vendor = {"instrument_id": "MSFT", "concept": "assets", "unit": "USD", "end": "2024-12-31", "value": 9}

    selected = select_authoritative_facts((fact,), (vendor,))

    assert fact.instant == "2024-12-31"
    assert selected == (fact,)


def test_statement_store_migrates_legacy_rows_to_schema_version(tmp_path: Path) -> None:
    import pandas as pd

    destination = tmp_path / "statement_facts.parquet"
    pd.DataFrame([{"instrument_id": "MSFT", "source_id": "legacy"}]).to_parquet(destination, index=False)
    write_statement_facts((), destination)
    frame = pd.read_parquet(destination)
    assert frame["schema_version"].eq("statement_facts.v1").all()


def test_sec_import_rolls_back_when_atomic_evidence_publish_fails(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_text(json.dumps({"cik": 4, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 4}]}}}}}), encoding="utf-8")
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "statement_facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "filings_statements.parquet")
    monkeypatch.setattr(state_module, "write_statement_evidence", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("injected atomic evidence failure")))
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"

    message = state.import_sec_companyfacts(payload_path)

    assert "No data changed" in message
    assert "scoring and execution were not started" in message
    assert not (tmp_path / "statement_facts.parquet").exists()
    assert not (tmp_path / "filings_statements.parquet").exists()


def test_statement_evidence_atomic_failure_rolls_back_after_first_destination_replaced(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.parsers import sec_facts as sec_module

    facts_destination = tmp_path / "statement_facts.parquet"
    inventory_destination = tmp_path / "filings_statements.parquet"
    write_statement_facts((), facts_destination)
    write_statement_inventory(FIXTURE, (), inventory_destination)
    facts_before = facts_destination.read_bytes()
    inventory_before = inventory_destination.read_bytes()
    record = parse_companyfacts(FIXTURE, _identity()).records[0]
    source = RawDocument(FIXTURE, "https://data.sec.gov/fixture", datetime.now(timezone.utc), _identity().cik or "", "sec_edgar", "sec_companyfacts", "application/json", 200)
    original_replace = Path.replace
    replaced_destinations: list[Path] = []
    injected = False

    def replace_with_failure(path: Path, target: Path, *args, **kwargs):
        nonlocal injected
        resolved_target = Path(target).resolve()
        if resolved_target == facts_destination.resolve() and not replaced_destinations:
            result = original_replace(path, target, *args, **kwargs)
            replaced_destinations.append(resolved_target)
            return result
        if resolved_target == inventory_destination.resolve() and not injected:
            assert facts_destination.read_bytes() != facts_before
            injected = True
            raise OSError("injected after first destination replacement")
        return original_replace(path, target, *args, **kwargs)

    monkeypatch.setattr(Path, "replace", replace_with_failure)

    import pytest

    with pytest.raises(OSError, match="injected after first destination replacement"):
        sec_module.write_statement_evidence(source, (record,), facts_destination, inventory_destination)
    assert replaced_destinations == [facts_destination.resolve()]
    assert facts_destination.read_bytes() == facts_before
    assert inventory_destination.read_bytes() == inventory_before


def test_sec_network_fetch_requires_configured_contact_user_agent(monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    monkeypatch.delenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT", raising=False)
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"

    message = state.fetch_sec_companyfacts("789019")

    assert "configure ETF_COCKPIT_SEC_EDGAR_USER_AGENT" in message
    assert "contact@example.invalid" not in message
