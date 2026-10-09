"""SB2 data wiring: equity members, extension mappings, derived owner figures, Pillar 3 extraction."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.application.sparebank_evidence import with_derived_owner_earnings
from etf_cockpit.data import pillar3_queue
from etf_cockpit.data.esef_extensions import equity_member_facts, issuer_extension
from etf_cockpit.data.pillar3_extract import detect_period, extract_figures, ingest_pdf
from scripts.import_official_filing import _write_ec_facts

PERIOD = "2024-12-31"


def _record(member: str, value: int, *, concept: str = "Equity", start: str | None = None, extra: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(
        concept=concept, value=str(value), is_numeric=True, period_end=PERIOD, period_start=start, consolidation_scope="consolidated",
        context_dimensions=(("ifrs-full:ComponentsOfEquityAxis", member), *extra), context_id=f"c-{member}", unit="NOK",
        source_location="report.xhtml", namespace="http://issuer.example",
    )


def test_equity_component_members_feed_the_ownerless_and_equalisation_pools() -> None:
    records = [
        _record("spar:Dividendequalisationreservemember", 1831),
        _record("spar:Primarycapitalreservemember", 876),
        _record("spar:Giftfoundationmember", 28),
        _record("ifrs-full:SharePremiumMember", 1505),  # not a rule: share premium comes from the IFRS concept
        _record("spar:" + "AdditionalTier1CapitalReserveOfFairValueGainsLossesPrimaryCapitalReserveGiftReserve" * 2 + "Member", 3459),
        _record("spar:Primarycapitalreservemember", 52, concept="ProfitLoss", start="2024-01-01"),  # a flow, not a balance
    ]
    facts = equity_member_facts(records, PERIOD)
    assert {name: item["value"] for name, item in facts.items()} == {"utjevningsfond": "1831", "sparebankens_fond": "876", "gavefond": "28"}
    assert "member=Primarycapitalreservemember" in facts["sparebankens_fond"]["source_locator"]
    # Two balances matching the same pool are ambiguous and are not guessed.
    ambiguous = equity_member_facts([*records, _record("spar:OtherEqualisationMember", 5)], PERIOD)
    assert "utjevningsfond" not in ambiguous


def test_issuer_extension_mapping_is_per_issuer_and_uses_the_namespace_the_filing_uses() -> None:
    ring = [SimpleNamespace(namespace="http://sparebank1ringerikehadeland.com"), SimpleNamespace(namespace="http://other.example")]
    namespace, rules = issuer_extension("RING", ring)
    assert namespace == "http://sparebank1ringerikehadeland.com"
    assert rules["SumOperatingExpenses"] == {"metric": "operating_expenses", "magnitude": True}
    assert issuer_extension("NONG", ring) == (None, {})  # no reviewed mapping for another issuer
    assert issuer_extension("RING", [SimpleNamespace(namespace="http://other.example")]) == (None, {})


def _facts(**overrides: object) -> dict[str, object]:
    base = {
        name: {"available": True, "value": value, "unit": "NOK", "known_at": "2025-03-01T00:00:00Z", "source_url": "https://example.test/f"}
        for name, value in {"ec_capital": 258e6, "overkursfond": 1505e6, "utjevningsfond": 1831e6, "sparebankens_fond": 876e6, "gavefond": 28e6}.items()
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def test_owner_result_uses_the_tagged_primary_capital_split_and_count_comes_from_eps() -> None:
    statements = {
        "period_end": PERIOD,
        "current": {"profit_attributable_to_owners": 439e6, "ownerless_result": 110e6, "net_profit": 571e6, "basic_eps": 16.2},
    }
    derived = with_derived_owner_earnings(_facts(), statements)
    # Owners / (owners + ownerless) = 0.7996 matches the ownership fraction 0.7990: the owners' profit IS the EC share.
    assert derived["ec_attributable_result"]["value"] == pytest.approx(439e6)
    assert "tags the ownerless share" in derived["ec_attributable_result"]["source_locator"]
    # EC count = result / EPS (27.1 m); implied nominal 258 m / 27.1 m = 9.5 NOK is within the plausible NOK 1 to 60 range.
    assert derived["weighted_average_ec_count"]["value"] == pytest.approx(439e6 / 16.2)
    assert derived["outstanding_ec_count"]["derived"] is True
    # A split that disagrees with the ownership fraction is not trusted; the book's eierbrok allocation is used.
    off = with_derived_owner_earnings(_facts(), {**statements, "current": {**statements["current"], "ownerless_result": 300e6}})
    assert off["ec_attributable_result"]["value"] == pytest.approx(439e6 * 0.79905, rel=1e-3)
    # An EPS tag with the wrong scale (163 instead of 16.3) implies a NOK 96 nominal: no count is invented.
    scale = with_derived_owner_earnings(_facts(), {**statements, "current": {**statements["current"], "basic_eps": 163.0}})
    assert "weighted_average_ec_count" not in scale


def test_reimport_of_the_same_package_fills_only_previously_unavailable_facts(tmp_path: Path) -> None:
    archive = SimpleNamespace(sha256="b" * 64)
    destination = tmp_path / "ec_facts.json"
    first = {"ec_capital": {"value": 100, "source_locator": "a", "unit": "NOK", "period": PERIOD}}
    _write_ec_facts(first, destination, archive, "TEST", PERIOD, "2025-03-01T00:00:00Z", "https://example.test/f")
    second = {
        "ec_capital": {"value": 999, "source_locator": "b", "unit": "NOK", "period": PERIOD},  # must not overwrite
        "utjevningsfond": {"value": 50, "source_locator": "c", "unit": "NOK", "period": PERIOD},
    }
    _write_ec_facts(second, destination, archive, "TEST", PERIOD, "2025-03-01T00:00:00Z", "https://example.test/f")
    stored = json.loads(destination.read_text(encoding="utf-8"))
    facts = stored["revisions"][0]["facts"]
    assert len(stored["revisions"]) == 1
    assert facts["ec_capital"]["value"] == 100 and facts["utjevningsfond"]["value"] == 50


def test_pillar3_extraction_reads_column_order_ignores_thresholds_and_proposes_only_pending() -> None:
    pages = [
        "Pilar 3 2024\n31.12.2024 31.12.2024 31.12.2024",
        "Nøkkeltall   2023   2024\nRen kjernekapitaldekning 17,10 % 16,80 %\nLCR konsern (>100 %) 363,9 % 250,1 %\n"
        "Uvektet kjernekapitalandel 7,90 % 7,83 %\nOver the year the CET1 ratio stands at 18.3%.",
        "Annual\nAt the end of 2023 the leverage ratio stands at 7.0% and 2024 follows.",
    ]
    figures = {(f["metric"], f["value"]): f for f in extract_figures(pages)}
    assert detect_period(pages) == "2024-12-31"
    # Header 2023 | 2024 is ascending, so the 2024 value is the LAST column.
    assert figures[("cet1_ratio_pct", 16.8)]["period"] == "2024-12-31" and figures[("cet1_ratio_pct", 16.8)]["page"] == 2
    assert figures[("leverage_ratio_pct", 7.83)]["flags"] == []
    # The threshold "(>100 %)" is not read as the LCR value.
    assert ("lcr_pct", 100.0) not in figures and figures[("lcr_pct", 250.1)]["printed_text"].startswith("LCR konsern")
    # A prose line naming two years is ambiguous: it falls back to the document period and says so.
    assert "several_years_in_line" in figures[("leverage_ratio_pct", 7.0)]["flags"]


def test_ingest_requires_https_and_a_pdf_and_queues_everything_as_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "p3.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    monkeypatch.setattr("etf_cockpit.data.pillar3_extract.read_pdf_pages", lambda path: ["31.12.2024 31.12.2024 31.12.2024\nCET1 ratio 17,1 %"])
    with pytest.raises(ValueError):
        ingest_pdf(tmp_path, "TEST", str(pdf), source_url="http://example.test/p3.pdf")
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
    with pytest.raises(ValueError):
        ingest_pdf(tmp_path, "TEST", str(tmp_path / "bad.pdf"), source_url="https://example.test/p3.pdf")
    result = ingest_pdf(tmp_path, "TEST", str(pdf), source_url="https://example.test/p3.pdf", title="Synthetic")
    queue = pillar3_queue.load_queue(tmp_path, "TEST")
    assert result["proposed"] == 1 and {item["status"] for item in queue["figures"]} == {"pending"}
    assert queue["documents"][0]["source_url"] == "https://example.test/p3.pdf" and len(queue["documents"][0]["sha256"]) == 64


def test_dividend_history_is_point_in_time_per_certificate_and_unavailable_when_empty() -> None:
    import pandas as pd

    from etf_cockpit.analysis.sparebank.dividends import dividend_history

    dates = pd.to_datetime(["2023-04-20", "2024-04-18", "2024-10-10", "2025-04-17", "2025-06-30"], utc=True)
    frame = pd.DataFrame({"_price_date": dates, "dividends": [5.0, 6.0, None, 8.0, 0.0]})
    result = dividend_history(frame, 160.0)
    assert [(item["year"], item["amount"], item["complete"]) for item in result["by_year"]] == [(2023, 5.0, True), (2024, 6.0, True), (2025, 8.0, False)]
    assert result["ttm_amount"] == pytest.approx(8.0)  # only 2025-04-17 lies within a year of the last row
    assert result["ttm_yield"] == pytest.approx(8.0 / 160.0)
    assert result["last_ex_date"] == "2025-04-17"
    for empty in (pd.DataFrame({"_price_date": dates, "dividends": [0.0] * 5}), pd.DataFrame({"_price_date": dates}), None):
        outcome = dividend_history(empty, 160.0)
        assert outcome["status"] == "unavailable" and outcome["reason_code"] and outcome["by_year"] == []


def test_listing_sync_adds_only_pattern_matched_unknown_banks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pandas as pd

    from etf_cockpit.data import savings_bank_universe as module
    from etf_cockpit.data.universe_store import UniverseRecord

    assert module.display_name("SPBK 1 NORDMØRE") == "Sparebank 1 Nordmøre"
    listing = pd.DataFrame(
        [
            {"isin": "NO0010691660", "symbol": "SNOR", "yfinance_ticker": "SNOR.OL", "market": "Oslo Børs"},
            {"isin": "NO0003025009", "symbol": "VVL", "yfinance_ticker": "VVL.OL", "market": "Oslo Børs"},  # include-name only, not a pattern
            {"isin": "NO0006000801", "symbol": "NONG", "yfinance_ticker": "NONG.OL", "market": "Oslo Børs"},  # already known
            {"isin": "NO0006001601", "symbol": "AURG", "yfinance_ticker": "AURG.OL", "market": "Oslo Børs"},  # known without a valid ISIN
        ]
    )
    monkeypatch.setattr(module, "savings_bank_view", lambda root: listing)
    monkeypatch.setattr(module, "_listing_names", lambda root: {"NO0010691660": "SPBK 1 NORDMØRE", "NO0003025009": "VOSS VEKSEL OGLAND", "NO0006000801": "SPAREBANK 1 NORD-NORGE", "NO0006001601": "AURSKOG SPAREBANK"})
    existing = (
        UniverseRecord(instrument_id="NONG", name="SpareBank 1 Nord-Norge", isin="NO0006000801", ticker="NONG.OL", asset_type="equity_certificate", tier="sparebanken", currency="NOK"),
        UniverseRecord(instrument_id="AURG", name="Aurskog Sparebank", isin="NEEDS_VERIFICATION", isin_status="needs_verification", ticker="AURG.OL", asset_type="equity_certificate", tier="sparebanken", currency="NOK"),
    )
    monkeypatch.setattr(module, "_all_records", lambda root: existing)
    monkeypatch.setattr(module, "load_sparebank_records", lambda root, enabled_only=False: existing)
    assert [row["symbol"] for row in module.missing_savings_banks(tmp_path)] == ["SNOR"]
    assert module.isin_corrections(tmp_path) == {"AURG": "NO0006001601"}
    created = module.sync(tmp_path)
    assert [(record.instrument_id, record.asset_type, record.isin, record.currency) for record in created] == [("SNOR", "equity_certificate", "NO0010691660", "NOK")]
