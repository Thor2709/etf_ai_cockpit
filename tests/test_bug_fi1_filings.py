"""Bughunt #962 (FI1): SEC/ESEF filing ingestion fails closed (native regression tests)."""

from __future__ import annotations

import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import etf_cockpit.parsers.esef_ixbrl as esef_ixbrl
from etf_cockpit.data import stock_sources as sources
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.data.oam_adapters import FinlandFsaOamAdapter, OAMDiscoveryRequest
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider, _validate_identity
from etf_cockpit.data.stock_fundamentals import load_stock_config
from etf_cockpit.parsers.esef_ixbrl import is_ifrs_full_namespace, map_ifrs_fact, parse_esef_package
from etf_cockpit.parsers.sec_facts import (
    StatementFact,
    authority_selection_as_of,
    parse_companyfacts,
    select_authoritative_facts,
    statement_facts_from_esef,
    write_statement_facts,
    write_statement_inventory,
)

CONFIG = load_stock_config()


def _identity(cik: str | None = "789019") -> CanonicalIdentity:
    return CanonicalIdentity("MSFT", "Microsoft Corporation", None, "needs_verification", "MSFT", "NASDAQ", "USD", "stock", {}, "high", (), cik)


def _facts(entries: list[dict], *, concept: str = "Assets", extra: dict | None = None) -> dict:
    payload = {"cik": "0000789019", "facts": {"us-gaap": {concept: {"units": {"USD": entries}}}}}
    payload.update(extra or {})
    return payload


def _entry(value: object = 10, **kwargs: object) -> dict:
    return {"val": value, "end": "2024-12-31", "form": "10-K", "filed": "2025-02-01", **kwargs}


def _write(tmp_path: Path, payload: dict | str, name: str = "facts.json") -> Path:
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def _state():
    from etf_cockpit.app import state as state_module

    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"
    state.selected_etf = "SELECTED_ETF"
    state.snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=[])))
    return state


def _patch_stores(monkeypatch, tmp_path: Path) -> None:
    import etf_cockpit.application.filing_ingestion as filing_ingestion
    import etf_cockpit.application.filing_ingestion_workflows as workflows

    monkeypatch.setattr(workflows, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(workflows, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(filing_ingestion, "IDENTITY_PATH", tmp_path / "identity.parquet")


_COMMON = dict(
    instrument_id="MSFT", cik="789019", taxonomy="us-gaap", concept="Revenues", unit="USD", value=1,
    start="2024-01-01", end="2024-12-31", instant=None, form="10-K", fiscal_year=2024, fiscal_period="FY",
    canonical_metric="revenue", mapping_status="mapped", is_custom=False,
)


def _fact(source_id: str, filed: str, **kwargs: object) -> StatementFact:
    return StatementFact(**{**_COMMON, "filed": filed, "accession": source_id, "source_id": source_id, **kwargs})


_VENDOR = {"instrument_id": "MSFT", "concept": "revenue", "unit": "USD", "start": "2024-01-01", "end": "2024-12-31", "fiscal_period": "FY", "value": 99}


# --- A005-N001 / A01-C2-N002: a local path-only import is never official or canonical -------------------


def test_local_unverified_companyfacts_is_not_official_or_canonical(tmp_path, monkeypatch) -> None:
    path = _write(tmp_path, _facts([_entry()]))
    _patch_stores(monkeypatch, tmp_path)

    message = _state().import_sec_companyfacts(path)

    inventory = pd.read_parquet(tmp_path / "inventory.parquet").iloc[0]
    facts = pd.read_parquet(tmp_path / "facts.parquet")
    assert "complete" in message
    assert inventory["source_authority"] == "local_unverified"
    assert inventory["source_authority"] not in {"official_regulator", "official_filing"}
    assert inventory["document_id"].startswith("sec_local_import:")
    assert set(facts["authority_selection"]) == {"manual_review"}
    assert all(str(item).startswith("sec_local_import:") for item in facts["source_id"])
    assert bool(facts["manual_review_required"].all())


def test_local_source_labels_never_resolve_to_official_authority() -> None:
    from etf_cockpit.data.contracts import SourceAuthority
    from etf_cockpit.data.fundamentals import _canonical_source_authority

    for label in ("sec_local_import", "local_unverified", "manual_local", "community_probe"):
        assert _canonical_source_authority(label) is not SourceAuthority.OFFICIAL


# --- A005-N002 / A005-N006 ------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", '"n/a"', '"10"', "true"])
def test_non_finite_and_non_numeric_facts_are_rejected(tmp_path, raw) -> None:
    text = '{"cik": "0000789019", "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": %s, "end": "2024-12-31", "form": "10-K", "filed": "2025-02-01"}]}}}}}' % raw
    result = parse_companyfacts(_write(tmp_path, text), _identity())

    assert result.records == ()
    assert result.success is False
    assert any(warning.code in {"non_numeric_fact", "malformed_fact"} for warning in result.warnings)


def test_one_bad_value_does_not_poison_valid_facts(tmp_path) -> None:
    text = '{"cik": "0000789019", "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": NaN, "end": "2023-12-31", "filed": "2024-02-01"}, {"val": 7, "end": "2024-12-31", "filed": "2025-02-01"}]}}}}}'
    result = parse_companyfacts(_write(tmp_path, text), _identity())

    assert [record.value for record in result.records] == [7]
    assert any(warning.code == "non_numeric_fact" for warning in result.warnings)


def test_empty_facts_object_is_not_complete(tmp_path, monkeypatch) -> None:
    path = _write(tmp_path, {"cik": "0000789019", "facts": {}})
    _patch_stores(monkeypatch, tmp_path)

    result = parse_companyfacts(path, _identity())
    message = _state().import_sec_companyfacts(path)

    assert result.success is False
    assert any(warning.code == "no_facts" for warning in result.warnings)
    assert "complete" not in message and "unavailable" in message
    assert not (tmp_path / "facts.parquet").exists()


# --- A005-N003 / B101 / B01-C2-N001 / A05-C2-N002: point-in-time authority ------------------------------


def test_amendment_does_not_change_canonical_before_its_filed_date(tmp_path) -> None:
    older = _fact("sec_edgar:older", "2025-01-20")
    amended = _fact("sec_edgar:amended", "2025-02-20", form="10-K/A", value=2)
    destination = tmp_path / "statement_facts.parquet"

    write_statement_facts((older, amended), destination, vendor_records=(_VENDOR,))

    frame = pd.read_parquet(destination).set_index("source_id")
    assert frame.loc["sec_edgar:amended", "authority_selection"] == "canonical_sec"
    assert frame.loc["sec_edgar:older", "authority_selection"] == "retained_sec"  # current view
    old_row, new_row = frame.loc["sec_edgar:older"].to_dict(), frame.loc["sec_edgar:amended"].to_dict()
    assert old_row["superseded_at"] == "2025-02-20"
    assert authority_selection_as_of(old_row, "2025-02-10") == "canonical_sec"
    assert authority_selection_as_of(new_row, "2025-02-10") == "unavailable"
    assert authority_selection_as_of(old_row, "2025-03-01") == "retained_sec"
    assert authority_selection_as_of(new_row, "2025-03-01") == "canonical_sec"
    # the selection itself is point in time: a later-published fact never masks the earlier one
    assert select_authoritative_facts((older, amended), (_VENDOR,), as_of="2025-02-10") == (older,)
    assert select_authoritative_facts((older, amended), (_VENDOR,), as_of="2025-03-01") == (amended,)
    assert select_authoritative_facts((older, amended), (_VENDOR,), as_of="2025-01-01") == (_VENDOR,)


def test_statement_view_as_known_at_uses_point_in_time_authority(tmp_path) -> None:
    from etf_cockpit.data.statement_normalisation import statement_view

    older = _fact("sec_edgar:older", "2025-01-20")
    amended = _fact("sec_edgar:amended", "2025-02-20", form="10-K/A", value=2)
    destination = tmp_path / "statement_facts.parquet"
    write_statement_facts((older, amended), destination, vendor_records=(_VENDOR,))
    stored = pd.read_parquet(destination)
    stored["known_at"] = stored["filed"]  # the knowledge-time ledger stamps first observation
    assert stored.set_index("source_id").loc["sec_edgar:older", "authority_selection"] == "retained_sec"

    before = statement_view(stored, "as_known_at", as_known_at="2025-02-10").set_index("source_id")
    after = statement_view(stored, "as_known_at", as_known_at="2025-03-01").set_index("source_id")

    assert before.loc["sec_edgar:older", "authority_selection"] == "canonical_sec"
    assert after.loc["sec_edgar:amended", "authority_selection"] == "canonical_sec"


def test_date_only_filing_is_not_available_at_exact_midnight() -> None:
    fact = _fact("sec_edgar:a", "2025-02-20")

    assert select_authoritative_facts((fact,), (), as_of="2025-02-20") == ()
    assert select_authoritative_facts((fact,), (), as_of="2025-02-20T23:59:59+00:00") == ()
    assert select_authoritative_facts((fact,), (), as_of="2025-02-21") == (fact,)
    with pytest.raises(ValueError):
        select_authoritative_facts((fact,), (), as_of="not-a-date")


def test_malformed_filed_date_never_wins_latest_filing_choice() -> None:
    good = _fact("sec_edgar:good", "2025-02-20")
    bad = _fact("sec_edgar:bad", "zzzz-not-a-date")
    unfiled = _fact("sec_edgar:none", "")

    assert select_authoritative_facts((good, bad, unfiled), (_VENDOR,)) == (good,)
    assert select_authoritative_facts((bad, good), (_VENDOR,)) == (good,)


def test_identical_sec_value_replaces_vendor_even_with_stored_nan_fields() -> None:
    sec = _fact("sec_edgar:a", "2025-02-20", value=99)
    vendor = {**_VENDOR, "canonical_metric": float("nan"), "instant": float("nan"), "consolidation_scope": None}

    assert select_authoritative_facts((sec,), (vendor,)) == (sec,)


# --- A005-N004 / A05-C2-N003 / B01-C2-N002: exact-key matching --------------------------------------------


@pytest.mark.parametrize("label", ["Q4", "", None, "FY2024"])
def test_duration_facts_match_by_dates_not_fiscal_period_label(label) -> None:
    sec = _fact("sec_edgar:a", "2025-02-20", fiscal_period="FY")
    vendor = {**_VENDOR, "fiscal_period": label}

    assert select_authoritative_facts((sec,), (vendor,)) == (sec,)
    other_dates = {**_VENDOR, "start": "2024-10-01"}
    assert select_authoritative_facts((sec,), (other_dates,)) == (other_dates, sec)


def test_one_official_fact_is_selected_once_for_several_same_key_vendor_rows() -> None:
    sec = _fact("sec_edgar:a", "2025-02-20")

    selected = select_authoritative_facts((sec,), ({**_VENDOR, "value": 1}, {**_VENDOR, "value": 2}, {**_VENDOR, "value": 3}))

    assert selected == (sec,)


def test_consolidated_and_separate_scope_do_not_collide() -> None:
    consolidated = _fact("filings_xbrl_org:c", "2025-03-01", consolidation_scope="consolidated", value=10)
    separate = _fact("filings_xbrl_org:s", "2025-03-01", consolidation_scope="separate", value=5)
    vendor = {**_VENDOR, "start": "2024-01-01"}

    selected = select_authoritative_facts((consolidated, separate), (vendor,))

    assert consolidated in selected and separate in selected and vendor not in selected
    assert len(selected) == 2
    assert select_authoritative_facts((separate,), (vendor,)) == (vendor, separate)  # separate never replaces an unscoped vendor


def test_unmapped_only_import_is_not_evidence_coverage(tmp_path) -> None:
    unmapped = _fact("sec_edgar:u", "2025-02-20", canonical_metric=None, mapping_status="unmapped")
    mapped = _fact("sec_edgar:m", "2025-02-20")
    source = tmp_path / "facts.json"
    source.write_text("{}", encoding="utf-8")

    only = pd.read_parquet(write_statement_inventory(source, (unmapped,), tmp_path / "a.parquet", instrument_id="MSFT")).iloc[0]
    both = pd.read_parquet(write_statement_inventory(source, (unmapped, mapped), tmp_path / "b.parquet", instrument_id="MSFT")).iloc[0]

    assert only["coverage_status"] == "unmapped_only" and only["mapped_fact_count"] == 0
    assert both["coverage_status"] == "imported" and both["mapped_fact_count"] == 1 and both["fact_count"] == 2


# --- A005-N005: cik / cik_str must agree -----------------------------------------------------------------


def test_conflicting_cik_and_cik_str_are_rejected(tmp_path, monkeypatch) -> None:
    payload = _facts([_entry()], extra={"cik_str": "0000000001"})
    path = _write(tmp_path, payload)
    _patch_stores(monkeypatch, tmp_path)

    result = parse_companyfacts(path, _identity())
    message = _state().import_sec_companyfacts(path)

    assert result.success is False and any(w.code == "identity_mismatch" for w in result.warnings)
    with pytest.raises(ValueError, match="disagree"):
        _validate_identity(payload, "0000789019")
    assert "unavailable" in message and not (tmp_path / "facts.parquet").exists()
    # agreeing aliases (any zero padding) stay accepted
    _validate_identity({"cik": 789019, "cik_str": "0000789019"}, "0000789019")
    assert parse_companyfacts(_write(tmp_path, _facts([_entry()], extra={"cik_str": 789019}), "ok.json"), _identity()).success is True


# --- A106-N001 / A106-N002 -----------------------------------------------------------------------------------


def test_ifrs_substring_extension_is_not_promoted_and_non_numeric_is_not_numeric() -> None:
    fake = "https://example.test/ifrs-extension/2025"
    assert is_ifrs_full_namespace("https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full")
    assert not is_ifrs_full_namespace(fake)
    assert map_ifrs_fact("Assets", fake) is None
    assert map_ifrs_fact("Revenue", "https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full") == "revenue"

    def record(namespace: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(concept="Assets", unit="EUR", period_start=None, period_end="2025-12-31", namespace=namespace, value="5", context_dimensions=(), context_id="c1", mapping_status="unmapped", **kwargs)

    extension, real, text = (
        record(fake),
        record("https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full"),
        record("https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full", is_numeric=False),
    )
    facts = statement_facts_from_esef((extension, real, text), instrument_id="X", source_sha256="a" * 64, known_at="2026-01-01T00:00:00+00:00")

    assert facts[0].canonical_metric is None and facts[0].taxonomy == "esef-extension" and facts[0].is_custom
    assert facts[1].canonical_metric == "total_assets" and facts[1].taxonomy == "ifrs-full"
    assert facts[2].canonical_metric is None and facts[2].manual_review_required


def test_non_numeric_inline_fact_is_never_mapped_numeric(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: False)
    xhtml = """<?xml version='1.0'?>
    <html xmlns='http://www.w3.org/1999/xhtml' xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
      xmlns:xbrli='http://www.xbrl.org/2003/instance' xmlns:ifrs-full='https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full'
      xmlns:ifrs='https://example.test/not-the-ifrs-taxonomy'>
      <body><xbrli:context id='c1'><xbrli:entity><xbrli:identifier scheme='http://standards.iso.org/iso/17442'>549300TESTLEI00000001</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
      <ix:nonNumeric name='ifrs-full:Assets' contextRef='c1'>Total assets, see note</ix:nonNumeric>
      <ix:nonFraction name='ifrs-full:Assets' contextRef='c1' unitRef='EUR' decimals='0'>5</ix:nonFraction>
      <ix:nonFraction name='ifrs:ProfitLoss' contextRef='c1' unitRef='EUR' decimals='0'>3</ix:nonFraction></body></html>"""
    package = tmp_path / "p.xbri"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("META-INF/reportPackage.json", '{"documentInfo":{"documentType":"https://xbrl.org/report-package/2023/xbri"}}')
        archive.writestr("reports/report.xhtml", xhtml)

    result = parse_esef_package(package)
    by_kind = {(fact.is_numeric, fact.concept, fact.namespace): fact for fact in result.records}

    assert by_kind[(False, "Assets", "https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full")].mapping_status == "non_numeric"
    assert by_kind[(True, "Assets", "https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full")].mapping_status == "mapped"
    assert by_kind[(True, "ProfitLoss", "https://example.test/not-the-ifrs-taxonomy")].mapping_status == "unmapped_extension"
    statement = statement_facts_from_esef(result.records, instrument_id="X", source_sha256="b" * 64, known_at="2026-01-01T00:00:00+00:00")
    mapped = {(fact.concept, fact.canonical_metric) for fact in statement if fact.canonical_metric}
    assert mapped == {("Assets", "total_assets")}  # exactly the numeric IFRS-namespace fact


# --- A106-N003: issuer-only OAM query ---------------------------------------------------------------------


def test_issuer_only_oam_query_is_not_labelled_matched_isin(tmp_path) -> None:
    payload = json.dumps({"records": [{"issuer": "Nordic Issuer", "isin": "FI0000000001", "title": "Annual report", "document_type": "annual_report", "published_at": "2026-07-01T06:00:00Z", "available_at": "2026-07-01T06:05:00Z", "document_url": "https://www.finanssivalvonta.fi/annual-report.pdf"}]}).encode()

    def adapter(name: str) -> FinlandFsaOamAdapter:
        return FinlandFsaOamAdapter(cache_dir=tmp_path / name, endpoint="https://www.finanssivalvonta.fi/export.json", transport=lambda _u, _h: (payload, 200, {"content-type": "application/json"}), enabled=True)

    issuer_only = adapter("a").discover(OAMDiscoveryRequest(issuer="Nordic Issuer"))
    by_isin = adapter("b").discover(OAMDiscoveryRequest(isin="FI0000000001"))

    assert issuer_only.records[0].identity_status == "issuer_only_manual_review"
    assert by_isin.records[0].identity_status == "matched_isin"


# --- A05-C2-N001: shared SEC rate limit ---------------------------------------------------------------------


def test_sec_rate_limit_is_shared_across_provider_instances(tmp_path) -> None:
    now = [100.0]
    sleeps: list[float] = []
    clock = lambda: now[0]  # noqa: E731 - one shared clock = one client

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    agent = "ETF AI Cockpit tests research@company.org"
    first = SecEdgarProvider(agent, cache_dir=tmp_path / "a", rate_limit_seconds=1.0, monotonic=clock, sleep=fake_sleep)
    second = SecEdgarProvider(agent, cache_dir=tmp_path / "b", rate_limit_seconds=1.0, monotonic=clock, sleep=fake_sleep)

    first._respect_rate_limit()
    second._respect_rate_limit()

    assert sleeps == [1.0]
    results: list[int] = []
    threads = [threading.Thread(target=lambda p=p: (p._respect_rate_limit(), results.append(1))) for p in (first, second, first)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 3 and len(sleeps) == 4


# --- B02-C2-N001 / N003: stock_sources companyfacts --------------------------------------------------------


def _fy(concept_entries: dict[str, list[dict]], dei: list[dict] | None = None) -> dict:
    facts: dict[str, object] = {"us-gaap": {name: {"units": {"USD": entries}} for name, entries in concept_entries.items()}, "dei": {}}
    if dei is not None:
        facts["dei"] = {"EntityCommonStockSharesOutstanding": {"units": {"shares": dei}}}  # type: ignore[assignment]
    return {"facts": facts}


def _fy_row(payload: dict) -> dict:
    return next(row for row in sources.parse_edgar_companyfacts(payload, CONFIG, source_ref="t") if row["period_type"] == "FY")


@pytest.mark.parametrize("flip", [False, True])
def test_tied_cover_page_share_counts_are_not_chosen_by_insertion_order(flip) -> None:
    revenue = {"Revenues": [{"start": "2025-01-01", "end": "2025-12-31", "val": 500.0, "filed": "2026-02-10"}]}
    cover = [{"end": "2026-02-05", "val": 100.0, "filed": "2026-02-10"}, {"end": "2026-02-05", "val": 900.0, "filed": "2026-02-10"}]

    row = _fy_row(_fy(revenue, cover[::-1] if flip else cover))

    assert "shares_outstanding" not in row  # ambiguous tie is unavailable, never an arbitrary pick


def test_agreeing_cover_page_share_counts_are_still_used() -> None:
    revenue = {"Revenues": [{"start": "2025-01-01", "end": "2025-12-31", "val": 500.0, "filed": "2026-02-10"}]}
    cover = [{"end": "2026-02-05", "val": 100.0, "filed": "2026-02-10"}, {"end": "2026-02-05", "val": 100.0, "filed": "2026-02-10"}]

    assert _fy_row(_fy(revenue, cover))["shares_outstanding"] == 100.0


def test_lower_priority_revenue_concept_filed_earlier_is_not_suppressed() -> None:
    period = {"start": "2025-01-01", "end": "2025-12-31"}
    payload = _fy({
        "Revenues": [{**period, "val": 520.0, "filed": "2026-03-01"}],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [{**period, "val": 480.0, "filed": "2026-02-10"}],
    })

    assert _fy_row(payload)["revenue"] == 480.0  # as originally reported (earliest filing)
    tie = _fy({
        "Revenues": [{**period, "val": 500.0, "filed": "2026-02-10"}],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [{**period, "val": 480.0, "filed": "2026-02-10"}],
    })
    assert _fy_row(tie)["revenue"] == 500.0  # same filing: configured concept priority decides


@pytest.mark.parametrize("bad_filed", ["0000-00-00", "1999-bad", 19990101, None])
def test_malformed_filed_in_companyfacts_never_wins_earliest_filed_choice(bad_filed) -> None:
    period = {"start": "2025-01-01", "end": "2025-12-31"}
    payload = _fy(
        {"Revenues": [{**period, "val": 1.0, "filed": bad_filed}, {**period, "val": 480.0, "filed": "2026-02-10"}]},
        [{"end": "2026-02-05", "val": 900.0, "filed": bad_filed}, {"end": "2026-02-05", "val": 100.0, "filed": "2026-02-10"}],
    )

    row = _fy_row(payload)

    assert row["revenue"] == 480.0
    assert row["shares_outstanding"] == 100.0
