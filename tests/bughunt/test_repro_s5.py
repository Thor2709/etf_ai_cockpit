"""Bug-hunt S5 reproductions (strict xfail: each asserts the CORRECT behaviour)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd
import pytest

from etf_cockpit.application import filing_ingestion_workflows as w
from etf_cockpit.data import etf_economics as econ
from etf_cockpit.data.capital_efficiency import capital_efficiency_analysis
from etf_cockpit.data.oam_adapters import NetherlandsAfmOamAdapter, OAMDiscoveryRequest
from etf_cockpit.data.statement_normalisation import statement_view
from etf_cockpit.parsers import esef_ixbrl as esef
from etf_cockpit.parsers import priips_kid as kid
from etf_cockpit.parsers.contracts import ParseResult
from etf_cockpit.parsers.esef_ixbrl import XbrlFact
from etf_cockpit.parsers.sec_facts import statement_facts_from_esef

IFRS = "http://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full"


def _fact(value, context="c", dims=()):
    return XbrlFact(
        "X", "Revenue", value, "EUR", "0", context, "2025-01-01", "2025-12-31",
        "report.xhtml", "mapped", dims, IFRS,
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S5-01: Inline XBRL scale and sign are ignored")
def test_s5_01_inline_scale_and_sign(tmp_path, monkeypatch):
    path = tmp_path / "report.xbri"
    xml = (
        "<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL' "
        f"xmlns:ifrs-full='{IFRS}'>"
        "<ix:nonFraction name='ifrs-full:Revenue' unitRef='EUR' scale='6' sign='-'>125</ix:nonFraction></html>"
    )
    with ZipFile(path, "w") as z:
        z.writestr("META-INF/reportPackage.json", "{}")
        z.writestr("report.xhtml", xml)
    monkeypatch.setattr(esef, "_arelle_available", lambda: False)
    result = esef.parse_esef_package(path)
    assert result.success
    assert float(result.records[0].value) == -125000000


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S5-02: Segment facts overwrite consolidated totals")
def test_s5_02_esef_dimensions_survive():
    raw = [_fact("100", "consolidated"), _fact("60", "segment", (("Axis", "Segment"),))]
    facts = statement_facts_from_esef(raw, instrument_id="X", source_sha256="a" * 64)
    # Either keep both dimensional identities or drop the segment: the
    # consolidated total (100) must never be replaced by the segment (60).
    assert "100" in statement_view(facts, "latest_restated")["value"].astype(str).tolist()


def test_s5_03_percent_fee_survives_manifest_enrichment(monkeypatch):
    frame = pd.DataFrame([dict(
        instrument_id="ETF", as_of="2026-09-01", known_at="2026-09-02", ter=0.5, fee_unit="percent",
    )])
    manifest = dict(sha256="a" * 64, source_path="memory.csv", known_at="2026-09-02")
    monkeypatch.setattr(econ, "_read_local_frame", lambda *a, **k: frame)
    monkeypatch.setattr(econ, "load_etf_economics_import_manifest", lambda p: manifest)
    records = econ.load_etf_economics_records(Path("memory.csv"))
    assert records[0].ter == pytest.approx(0.005)


def test_s5_04_distinct_issuer_filings_remain_ambiguous(tmp_path):
    adapter = NetherlandsAfmOamAdapter(endpoint="https://www.afm.nl/export", enabled=True, cache_dir=tmp_path)
    rows = [
        dict(issuer=name, title="Annual Report", published_at="2026-03-01",
             document_url=f"https://www.afm.nl/{i}.pdf")
        for i, name in enumerate(["Acme PLC", "Acme Holdings"])
    ]
    response = SimpleNamespace(payload=json.dumps(rows).encode(), headers={"content-type": "application/json"}, status=200)
    adapter._fetch_with_retries = lambda url: (response, 0)
    result = adapter.discover(OAMDiscoveryRequest(issuer="Acme"))
    assert result.status == "manual_review"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S5-05: Invalid risk indicators become score eligible")
def test_s5_05_invalid_sri_is_not_eligible(monkeypatch):
    text = "\n".join([
        "Key Information Document", "Product: Example ETF", "ISIN: IE00B4L5Y983",
        "Manufacturer: Example Ltd", "Risk indicator: 17 out of 7",
        "Recommended holding period: 5 years",
        "Document date: " + date.today().strftime("%d-%m-%Y"),
        "Composition of Costs", "Entry costs 0%", "Exit costs 0%",
        "Management fees and other 0.2%", "Transaction costs 0.1%", "Performance fees 0%",
    ])
    monkeypatch.setattr(kid, "_read_pages", lambda p: ([text], None))
    result = kid.parse_priips_kid(Path("memory.pdf"))
    assert not result.records[0].score_eligible
    assert result.records[0].sri != 7


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S5-06: Imported ESEF facts lack knowledge timestamps")
def test_s5_06_esef_import_stamps_fact_availability(monkeypatch, tmp_path):
    sha = "a" * 64
    fact = XbrlFact("X", "Revenue", "100", "EUR", "0", "c", "2025-01-01", "2025-12-31", "report.xhtml", "mapped")
    facts_path, inventory_path = tmp_path / "facts.parquet", tmp_path / "inventory.parquet"
    monkeypatch.setattr(w, "STATEMENT_FACTS_PATH", facts_path)
    monkeypatch.setattr(w, "FILINGS_STATEMENTS_PATH", inventory_path)
    monkeypatch.setattr(w, "_preserve_esef_raw", lambda *a, **k: (tmp_path / "raw.xbri", sha))
    monkeypatch.setattr(w, "parse_esef_package", lambda p: ParseResult((fact,), (), "esef_ixbrl", "1.1", sha, True))
    monkeypatch.setattr(w, "_esef_source_provenance", lambda p: ("esef_local_import", ""))
    monkeypatch.setattr(w, "_load_vendor_statement_claims", lambda _: ())
    session = SimpleNamespace(last_message="", _record_activity_output=lambda *a: None)
    w.import_esef_package(session, tmp_path / "report.xbri", instrument_id="X")
    stored = pd.read_parquet(facts_path)
    assert len(stored) == 1
    assert not statement_view(stored, "as_known_at", as_known_at="2100-01-01").empty


def test_s5_07_roic_combines_flow_and_balance_facts():
    values = dict(revenue=200, operating_income=20, equity=100, debt=30, cash=10)
    flow = {"revenue", "operating_income"}
    rows = [
        dict(instrument_id="X", concept=k, canonical_metric=k, value=v, unit="EUR", currency="EUR",
             end="2025-12-31", fiscal_period="FY",
             start="2025-01-01" if k in flow else None,
             instant=None if k in flow else "2025-12-31", source_id=k)
        for k, v in values.items()
    ]
    result = capital_efficiency_analysis(pd.DataFrame(rows), tax_rate=0.25)
    assert result["reported"]["metrics"]["roic"]["value"] == pytest.approx(0.125)


def test_s5_08_uppercase_isin_header_matches():
    adapter = NetherlandsAfmOamAdapter(endpoint="https://www.afm.nl/export")
    query = OAMDiscoveryRequest(isin="IE00B4L5Y983")
    rows = [dict(issuer="Acme", ISIN=query.isin, title="Annual Report")]
    records = adapter._normalise_records(rows, query)
    assert len(records) == 1
    assert records[0].isin == query.isin
