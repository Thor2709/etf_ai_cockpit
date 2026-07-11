from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.sec_facts import parse_companyfacts


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
