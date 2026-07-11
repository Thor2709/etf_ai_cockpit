from __future__ import annotations

from pathlib import Path

from etf_cockpit.parsers.priips_kid import parse_priips_kid


FIXTURE = Path("tests/fixtures/official/priips_kid/vanguard-ie000q4j3cw6-priips-kid.pdf")


def test_official_kid_extracts_identity_risk_and_holding_period() -> None:
    result = parse_priips_kid(FIXTURE, expected_isin="IE000Q4J3CW6")
    assert result.success is True
    record = result.records[0]
    assert record.isin == "IE000Q4J3CW6"
    assert record.sri == 4
    assert record.holding_period_years == 5
    assert record.document_date == "2026-04-14"
    assert record.source_sha256


def test_wrong_isin_is_a_controlled_failure(tmp_path: Path) -> None:
    result = parse_priips_kid(FIXTURE, expected_isin="IE0000000000")
    assert result.success is False
    assert result.records == ()
    assert any(item.code == "identity_mismatch" for item in result.warnings)
