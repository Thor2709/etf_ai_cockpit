"""ISSUE-0213: ESEF inline-XBRL hardening - transformation, unit and duplicate checks, stored decode status."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from etf_cockpit.data import stock_sources as src
from etf_cockpit.parsers import esef_ixbrl
from etf_cockpit.parsers.esef_ixbrl import XbrlFact, parse_esef_package
from etf_cockpit.parsers.sec_facts import statement_facts_frame, statement_facts_from_esef, write_statement_facts

IXT = "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
HEAD = f"""<?xml version='1.0'?>
<html xmlns='http://www.w3.org/1999/xhtml' xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
  xmlns:xbrli='http://www.xbrl.org/2003/instance' xmlns:iso4217='http://www.xbrl.org/2003/iso4217'
  xmlns:ifrs-full='https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full'
  xmlns:ixt='{IXT}' xmlns:custom='https://example.test/custom' xmlns:xbrldi='http://xbrl.org/2006/xbrldi'
  xmlns:alias='https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full'>
  <body><xbrli:context id='c'><xbrli:entity><xbrli:identifier>549300TESTLEI00000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:context id='d1'><xbrli:entity><xbrli:identifier>549300TESTLEI00000001</xbrli:identifier><xbrli:segment>
      <xbrldi:explicitMember dimension='ifrs-full:ComponentsOfEquityAxis'>ifrs-full:RetainedEarningsMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension='custom:SegmentAxis'>custom:AMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
      <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:context id='d2'><xbrli:entity><xbrli:identifier>549300TESTLEI00000001</xbrli:identifier><xbrli:segment>
      <xbrldi:explicitMember dimension='custom:SegmentAxis'>custom:AMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension='ifrs-full:ComponentsOfEquityAxis'>ifrs-full:RetainedEarningsMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
      <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:unit id='EUR'><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
    <xbrli:unit id='shares'><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
    <xbrli:unit id='bare'><xbrli:measure>shares</xbrli:measure></xbrli:unit>
    <xbrli:unit id='foreign'><xbrli:measure>ifrs-full:EUR</xbrli:measure></xbrli:unit>
    <xbrli:unit id='cased'><xbrli:measure>xbrli:Shares</xbrli:measure></xbrli:unit>
    <xbrli:unit id='rebound'><xbrli:measure xmlns:iso4217='https://foreign.example/iso'>iso4217:EUR</xbrli:measure></xbrli:unit>
"""


def _parse(tmp_path: Path, monkeypatch, facts: str):
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: False)
    package = tmp_path / "hardening.xbri"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("META-INF/reportPackage.json", "{}")
        archive.writestr("reports/report.xhtml", HEAD + facts + "</body></html>")
    return {fact.concept: fact for fact in parse_esef_package(package).records}


def _fact(concept: str, value: str, unit: str = "EUR", extra: str = "", context: str = "c", prefix: str = "ifrs-full") -> str:
    return f"<ix:nonFraction name='{prefix}:{concept}' contextRef='{context}' unitRef='{unit}' decimals='0' {extra}>{value}</ix:nonFraction>"


def test_unsupported_transformation_is_unavailable_and_valid_facts_keep_their_values(tmp_path: Path, monkeypatch) -> None:
    facts = _parse(
        tmp_path,
        monkeypatch,
        _fact("Revenue", "1.234,5", extra="format='ixt:num-comma-decimal' scale='3'")  # supported
        + _fact("Assets", "1.234", extra="format='custom:num-comma-decimal'")  # name is supported, namespace is not
        + _fact("Equity", "1.234", extra="format='nope:num-comma-decimal'")  # prefix is not declared
        + _fact("ProfitLoss", "7", extra="format='num-dot-decimal'")  # no prefix, so no namespace
        + _fact("Liabilities", "1.234", extra="format='ixt:num-comma-decimal' xmlns:ixt='https://foreign.example/ixt'"),  # prefix rebound on the element
    )
    assert (facts["Liabilities"].value, facts["Liabilities"].decode_status) == ("1.234", "unavailable")

    assert (facts["Revenue"].value, facts["Revenue"].mapping_status, facts["Revenue"].decode_status) == ("1234500", "mapped", "decoded")
    for concept, raw in (("Assets", "1.234"), ("Equity", "1.234"), ("ProfitLoss", "7")):
        assert (facts[concept].value, facts[concept].mapping_status, facts[concept].decode_status) == (raw, "unsupported_numeric", "unavailable")


def test_undefined_or_foreign_namespace_unit_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    facts = _parse(
        tmp_path,
        monkeypatch,
        _fact("Revenue", "100")
        + _fact("Assets", "5", unit="missing")  # no unit definition
        + _fact("Equity", "5", unit="foreign")  # measure in the IFRS namespace, not ISO 4217
        + _fact("DilutedEarningsLossPerShare", "0.5", unit="bare")  # measure without a QName
        + _fact("OtherReserves", "3", unit="cased")  # QNames are case-sensitive
        + _fact("Liabilities", "4", unit="rebound")  # the measure's prefix is bound to a foreign namespace on the measure itself
        + _fact("AdjustedWeightedAverageShares", "9", unit="shares"),
    )

    assert (facts["Revenue"].mapping_status, facts["Revenue"].decode_status, facts["Revenue"].unit_resolved) == ("mapped", "decoded", True)
    assert facts["AdjustedWeightedAverageShares"].decode_status == "decoded"
    for concept in ("Assets", "Equity", "DilutedEarningsLossPerShare", "OtherReserves", "Liabilities"):
        assert (facts[concept].mapping_status, facts[concept].decode_status, facts[concept].unit_resolved) == ("unsupported_numeric", "unavailable", False)


def test_inconsistent_duplicate_facts_are_unavailable_but_exact_duplicates_are_not(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: False)
    package = tmp_path / "duplicates.xbri"
    body = (
        _fact("Revenue", "100") + _fact("Revenue", "100")  # exact duplicate: ignored
        + _fact("Assets", "5") + _fact("Assets", "6")  # same context and unit, two values: a conflict
        + _fact("Equity", "5") + _fact("Equity", "5", unit="shares")  # different units are not duplicates
        + _fact("Liabilities", "7") + _fact("Liabilities", "8", prefix="alias")  # another prefix for the same expanded concept
        + _fact("Revenue", "1", context="d1") + _fact("Revenue", "2", context="d2")  # the same dimensions listed in another order
        + _fact("OtherReserves", "5", extra="format='custom:num-comma-decimal'") + _fact("OtherReserves", "5")  # same text, different status
    )
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("META-INF/reportPackage.json", "{}")
        archive.writestr("reports/report.xhtml", HEAD + body + "</body></html>")
    records = parse_esef_package(package).records

    by_concept = {name: [fact for fact in records if fact.concept == name] for name in ("Revenue", "Assets", "Equity", "Liabilities", "OtherReserves")}
    assert [(fact.decode_status, fact.mapping_status) for fact in by_concept["Revenue"] if not fact.context_dimensions] == [("decoded", "mapped")]
    assert [(fact.value, fact.decode_status) for fact in by_concept["Revenue"] if fact.context_dimensions] == [("1", "unavailable"), ("2", "unavailable")]
    assert [(fact.value, fact.decode_status) for fact in by_concept["Liabilities"]] == [("7", "unavailable"), ("8", "unavailable")]
    assert sorted(fact.decode_status for fact in by_concept["OtherReserves"]) == ["decoded", "unavailable"]  # neither replaces the other
    assert [(fact.value, fact.decode_status, fact.mapping_status) for fact in by_concept["Assets"]] == [("5", "unavailable", "unsupported_numeric"), ("6", "unavailable", "unsupported_numeric")]
    assert {fact.decode_status for fact in by_concept["Equity"]} == {"decoded"}


def test_non_numeric_fact_carries_a_not_applicable_decode_status(tmp_path: Path, monkeypatch) -> None:
    facts = _parse(tmp_path, monkeypatch, "<ix:nonNumeric name='ifrs-full:NameOfReportingEntity' contextRef='c'>Acme</ix:nonNumeric>")

    assert facts["NameOfReportingEntity"].decode_status == "not_applicable"


def test_every_stored_statement_fact_carries_its_decode_status() -> None:
    ifrs = "https://xbrl.ifrs.org/taxonomy/ifrs-full"
    base = ("L", "DilutedEarningsLossPerShare", "0.5", "EUR/shares", "0", "ctx", "2025-01-01", "2025-12-31", "report.xhtml", "unmapped", (), ifrs, None, True, True)
    good = statement_facts_from_esef((XbrlFact(*base, "decoded"),), instrument_id="X", source_sha256="a" * 64)[0]
    bad = statement_facts_from_esef((XbrlFact(*base, "unavailable"),), instrument_id="X", source_sha256="a" * 64)[0]

    assert (good.decode_status, good.mapping_confidence) == ("decoded", "numeric_decoded_unit_resolved")
    assert (bad.decode_status, bad.canonical_metric, bad.mapping_confidence) == ("unavailable", None, "manual_review")
    assert list(statement_facts_frame((good, bad))["decode_status"]) == ["decoded", "unavailable"]


def test_a_stored_fact_with_unavailable_decode_status_never_reaches_the_period_row() -> None:
    def row(concept: str, **extra: object) -> dict:
        return {"instrument_id": "XX", "taxonomy": "ifrs-full", "concept": concept, "unit": "EUR", "value": 100.0, "start": "2024-01-01",
                "end": "2024-12-31", "instant": None, "known_at": "2025-03-01T00:00:00.000000+00:00", "dimensions": "",
                "consolidation_scope": "consolidated", "mapping_confidence": "high", **extra}

    config = {"esef_concepts": {"revenue": ["Revenue"]}}
    assert src.parse_esef_statement_facts(pd.DataFrame([row("Revenue", decode_status="decoded")]), config, source_ref="t")[0]["revenue"] == 100.0
    assert src.parse_esef_statement_facts(pd.DataFrame([row("Revenue")]), config, source_ref="t")[0]["revenue"] == 100.0  # a store written before the column
    assert src.parse_esef_statement_facts(pd.DataFrame([row("Revenue", decode_status="unavailable")]), config, source_ref="t") == []


def test_a_decoded_and_an_unavailable_fact_of_one_context_keep_distinct_stored_ids(tmp_path: Path) -> None:
    ifrs = "https://xbrl.ifrs.org/taxonomy/ifrs-full"
    base = ("L", "Assets", "5", "EUR", "0", "ctx", "2025-01-01", "2025-12-31", "report.xhtml", "mapped", (), ifrs, None, True, True)
    good, bad = (statement_facts_from_esef((XbrlFact(*base, status),), instrument_id="X", source_sha256="a" * 64)[0] for status in ("decoded", "unavailable"))
    destination = tmp_path / "facts.parquet"
    for _ in range(2):  # a re-import changes nothing
        write_statement_facts((bad, good), destination)
    stored = pd.read_parquet(destination)

    assert good.source_id != bad.source_id and good.source_id.split(":")[:2] == bad.source_id.split(":")[:2]
    assert sorted(stored["decode_status"]) == ["decoded", "unavailable"]
