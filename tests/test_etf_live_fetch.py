"""Offline GET, refresh wiring and persistence regressions for ETF1."""

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.data.etf_e1_fetch import (
    _get, _issuer_records, _public_records, _public_url,
    decode_e1_reference_context, fetch_etf_e1_reference_data,
)
from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.reference_data import commit_reference_import, validate_etf_holdings
from etf_cockpit.data.etf_economics import load_etf_e1_fields, load_etf_reference_context


FIXTURES = Path(__file__).parent / "fixtures" / "etf"
NOW = datetime(2026, 1, 3, 12, tzinfo=timezone.utc)


def _config():
    config = load_config()
    config.universe.etfs = [config.universe.by_id()["VWCE"]]
    return config


def _provider(ter=0.003):
    return SimpleNamespace(
        fetch_etf_metadata=lambda _: ProviderResult("yfinance", "etf_metadata", "ok", "offline", pd.DataFrame([dict(etf_id="VWCE", as_of_date=date(2026, 1, 3), ter=ter, total_assets=90_000_000, source="yfinance")])),
        fetch_etf_holdings=lambda _: ProviderResult("yfinance", "etf_holdings", "unavailable", "offline fixture has no holdings"),
    )


def _pdf_parser(monkeypatch, currency="US$"):
    text = """Synthetic offline fund factsheet
Factsheet | 31 December 2025
Ongoing Charges Figure 0.22%
Total assets (million) US$120
IE00BK5BQT80 Accumulated
Weighted exposure
Technology 60.0%
Other 40.0%
Market allocation
United States 60.0%
Other 40.0%
Glossary
"""
    text = text.replace("US$120", currency + "120")
    class Document:
        pages = [SimpleNamespace(extract_text=lambda: text)]
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _: Document()))


def _fields(frame):
    rows = decode_e1_reference_context(frame).to_dict("records")
    return load_etf_e1_fields("VWCE", decision_time=NOW, issuer_records=[r for r in rows if r.get("source_authority") == "issuer_document"], public_records=[r for r in rows if r.get("source_authority") == "public_page"], vendor_records=[r for r in rows if r.get("source_authority") == "yfinance"])


def test_live_source_readers_offline_issuer_first_and_persist_alternates(monkeypatch, tmp_path):
    _pdf_parser(monkeypatch)
    calls = []
    def get(url, *, timeout):
        calls.append((url, timeout))
        return (FIXTURES / "public_profile.html").read_bytes() if "justetf.com" in url else b"%PDF synthetic offline fixture"
    results, messages = fetch_etf_e1_reference_data(_config(), _provider(), http_get=get, now=NOW, registry=pd.DataFrame())
    assert calls[0][0].startswith("https://fund-docs.vanguard.com/")
    assert all(timeout == 10 for _, timeout in calls)
    metadata = dict(results)["etf_metadata"]
    fields = _fields(metadata.data)
    assert fields["ter"]["value"] == pytest.approx(0.0022)
    assert fields["ter"]["source"] == calls[0][0]
    assert fields["ter"]["difference"] and len(fields["ter"]["alternates"]) == 2
    assert fields["aum"]["value"] == 120_000_000
    assert fields["aum"]["currency"] == "USD"
    assert fields["distribution_policy"]["value"] == "accumulating"
    assert fields["sector_split"]["value"]["Technology"] == pytest.approx(0.6)
    # Actual existing importer round trip, including checksum-bound acquisition.
    root = tmp_path / "copy"
    commit_reference_import(metadata, "etf_metadata", known_etfs=["VWCE"], clean_path=root / "data/clean/etf_metadata.parquet", raw_dir=root / "data/raw/etf_factsheets", snapshots_dir=root / "data/snapshots/etf_metadata")
    loaded = load_etf_reference_context("etf_metadata", root=root)
    assert _fields(loaded)["ter"] == fields["ter"]
    assert _fields(loaded)["distribution_policy"]["known_at"] == NOW.isoformat()
    holdings = dict(results)["etf_holdings"]
    assert holdings.ok and len(holdings.data) == 2
    validated = validate_etf_holdings(holdings.data, known_etfs=["VWCE"])
    assert validated.ok and validated.frame["weight"].sum() == pytest.approx(0.6)
    assert set(validated.frame["as_of_date"]) == {date(2025, 12, 31)}
    assert messages == ["etf_holdings: offline fixture has no holdings"]
    from etf_cockpit.application.etf_economics_view import build_etf_economics_panel

    panel = build_etf_economics_panel(SimpleNamespace(data_report=SimpleNamespace(as_of_date=NOW), etf_metadata=loaded, etf_holdings=decode_e1_reference_context(validated.frame)), "VWCE")
    assert panel["holdings_count"] == 2
    assert panel["e1"]["country_split"]["value"] == {"United States": 0.6, "Other/unclassified": 0.4}
    assert panel["e1"]["country_split"]["source"] == calls[0][0]


@pytest.mark.parametrize("public_available", [True, False])
def test_failed_http_sources_fall_through_and_record_reasons(public_available):
    def get(url, *, timeout):
        assert timeout == 10
        if public_available and "justetf.com" in url:
            return (FIXTURES / "public_profile.html").read_bytes()
        raise OSError("offline source fixture")
    results, messages = fetch_etf_e1_reference_data(_config(), _provider(), http_get=get, now=NOW, registry=pd.DataFrame())
    fields = _fields(dict(results)["etf_metadata"].data)
    assert fields["ter"]["value"] == pytest.approx(0.0023 if public_available else 0.003)
    assert fields["ter"]["source"] == (_public_url("IE00BK5BQT80") if public_available else "yfinance")
    assert "OSError" in " ".join(messages) and "offline source fixture" in " ".join(messages)
    if not public_available:
        assert "issuer=" in fields["distribution_policy"]["reason"]
        assert "public_page=" in fields["distribution_policy"]["reason"]


def test_public_splits_are_independent_of_missing_holdings_section():
    instrument = _config().universe.by_id()["VWCE"]
    body = (FIXTURES / "public_profile.html").read_bytes()
    start, finish = body.index(b"<h3>Top 10 Holdings"), body.index(b"<h3>Countries")
    rows = _public_records(body[:start] + body[finish:], instrument, NOW.isoformat(), _public_url(instrument.isin))
    assert "holdings" not in rows[0]
    fields = load_etf_e1_fields("VWCE", decision_time=NOW, public_records=rows)
    assert fields["country_split"]["value"] == {"United States": 0.6, "Other/unclassified": 0.4}
    assert fields["sector_split"]["value"] == {"Technology": 0.6, "Other/unclassified": 0.4}
    assert fields["country_split"]["as_of"].startswith("2025-12-31")
    assert fields["sector_split"]["source"] == _public_url(instrument.isin)


def test_no_fee_from_any_source_is_unavailable():
    def get(_url, *, timeout):
        raise OSError("offline fixture")
    results, _ = fetch_etf_e1_reference_data(_config(), _provider(ter=None), http_get=get, now=NOW, registry=pd.DataFrame())
    field = _fields(dict(results)["etf_metadata"].data)["ter"]
    assert field["value"] is None
    assert field["reason"].startswith("ter_missing_all_sources")
    assert "offline fixture" in field["reason"]


def test_source_identity_and_effective_date_are_not_inferred(monkeypatch):
    instrument = _config().universe.etfs[0]
    body = (FIXTURES / "public_profile.html").read_bytes()
    with pytest.raises(ValueError, match="public_identity_mismatch"):
        _public_records(body.replace(b"IE00BK5BQT80", b"fixture-other-identity"), instrument, NOW.isoformat(), _public_url(instrument.isin))
    companies = _public_records(body.replace(b"Fixture holding A", b"Fixture Holdings A"), instrument, NOW.isoformat(), _public_url(instrument.isin))[0]["holdings"]
    assert len(companies) == 2 and companies[0]["holding_name"] == "Fixture Holdings A"
    _pdf_parser(monkeypatch)
    issuer = _issuer_records(b"%PDF fixture", instrument, NOW.isoformat(), "fixture-source", "factsheet")[0]
    assert issuer["as_of"] == "2025-12-31" and issuer["known_at"] == NOW.isoformat()
    fields = load_etf_e1_fields("VWCE", decision_time="2026-01-02", issuer_records=[issuer])
    assert fields["ter"]["value"] is None and fields["ter"]["reason"] == "ter_no_dated_source"
    _pdf_parser(monkeypatch, currency="$")
    ambiguous = _issuer_records(b"%PDF fixture", instrument, NOW.isoformat(), "fixture-source", "factsheet")[0]
    assert ambiguous["aum"] == 120_000_000 and ambiguous["aum_currency"] is None
    malformed = pd.DataFrame([dict(field_name="etf_e1_context_v1", value="[]", instrument_id="VWCE")])
    assert decode_e1_reference_context(malformed).empty


def test_http_transport_uses_get_and_timeout_and_rejects_other_hosts(monkeypatch):
    calls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self, bound):
            assert bound == 8 * 1024 * 1024 + 1
            return b"offline fixture"
    def open_request(request, *, timeout):
        calls.append((request.get_method(), request.full_url, timeout))
        return Response()
    monkeypatch.setattr("urllib.request.build_opener", lambda _: SimpleNamespace(open=open_request))
    url = _public_url("IE00BK5BQT80")
    assert _get(url, timeout=7) == b"offline fixture"
    assert calls == [("GET", url, 7)]
    with pytest.raises(ValueError, match="source_url_not_supported"):
        _get("https://example.invalid/fixture")


def test_discovery_uses_observed_document_link_and_preserves_classified_holdings():
    config = _config()
    # Remove the fixed VWCE binding to exercise discovered addresses; never
    # invent a production binding for another fund.
    from unittest.mock import patch

    issuer_url = "https://api.fundinfo.com/fixture-factsheet.pdf"
    calls = []
    def get(url, *, timeout):
        calls.append(url)
        if "justetf.com" in url:
            return (FIXTURES / "public_profile.html").read_bytes()
        raise OSError("unsupported offline document fixture")
    with patch("etf_cockpit.data.etf_e1_fetch._ISSUER_DOCUMENTS", {}):
        results, messages = fetch_etf_e1_reference_data(config, _provider(), http_get=get, now=NOW, registry=pd.DataFrame())
    assert calls == [_public_url("IE00BK5BQT80"), issuer_url]
    assert _fields(dict(results)["etf_metadata"].data)["ter"]["source"] == calls[0]
    assert "unsupported offline document fixture" in " ".join(messages)
    instrument = config.universe.etfs[0]
    csv = b"isin,as_of_date,holding_name,weight,country,sector\nIE00BK5BQT80,2025-12-31,Fixture holding A,0.6,US,Technology\n"
    records = _issuer_records(csv, instrument, NOW.isoformat(), "fixture-source", "holdings")
    assert records[0]["holdings"][0]["country"] == "US"
    with pytest.raises(ValueError, match="issuer_csv_date_not_usable"):
        _issuer_records(csv.replace(b"2025-12-31", b"2026-01-04"), instrument, NOW.isoformat(), "fixture-source", "holdings")


def test_all_reader_exceptions_are_contained_and_next_source_runs():
    from etf_cockpit.data.fund_adapters import fetch_etf_economics_sources

    calls = []
    def broken(_):
        calls.append("issuer")
        raise RuntimeError("offline parser fixture")
    def public(_):
        calls.append("public")
        return []
    def vendor(_):
        calls.append("yfinance")
        return [dict(instrument_id="VWCE", as_of="2026-01-01", known_at=NOW.isoformat(), source="yfinance", ter=0.003)]
    result = fetch_etf_economics_sources("VWCE", decision_time=NOW, issuer_reader=broken, public_reader=public, vendor_reader=vendor)
    assert calls == ["issuer", "public", "yfinance"]
    assert result["fields"]["ter"]["value"] == 0.003
    assert result["failure_details"] == {"issuer": "RuntimeError: offline parser fixture"}


def test_refresh_wires_source_chain_and_keeps_price_publication(monkeypatch):
    from etf_cockpit.application import data_service as service
    prices = ProviderResult("fixture", "prices", "ok", "offline prices", pd.DataFrame([dict(etf_id="VWCE")]))
    provider = _provider()
    provider.fetch_prices = lambda *_: prices
    monkeypatch.setattr(service.YFinanceProvider, "from_config", lambda _: provider)
    monkeypatch.setattr(service, "_quarantine_invalid_ohlc", lambda result: (result, None))
    monkeypatch.setattr(service, "validate_prices", lambda *_args, **_kw: SimpleNamespace(issues=[]))
    monkeypatch.setattr(service, "commit_price_import", lambda _: SimpleNamespace(rows=1, clean_path="fixture", previous_snapshot_path=None))
    commits = []
    def commit(result, dataset, **_kwargs):
        commits.append((dataset, result.data))
        return SimpleNamespace(rows=len(result.data), warnings=[], clean_path="fixture")
    monkeypatch.setattr(service, "commit_reference_import", commit)
    def offline(_url, *, timeout):
        raise OSError("offline fixture")
    monkeypatch.setattr("etf_cockpit.data.etf_e1_fetch._get", offline)
    monkeypatch.setattr("etf_cockpit.data.etf_e1_fetch.read_document_registry", pd.DataFrame)
    instance = service.DataService(_config())
    message = instance.refresh_yfinance_data()
    assert instance.last_operation_succeeded
    assert "Validated and committed 1 price rows" in message
    assert [dataset for dataset, _ in commits] == ["etf_metadata"]
    assert "OSError: offline fixture" in message
    assert commits[0][1].iloc[0]["field_name"] == "etf_e1_context_v1"


def test_e1_acquisition_stops_at_the_checkpoint_before_any_network_call():
    from types import SimpleNamespace

    from etf_cockpit.data.etf_e1_fetch import fetch_etf_e1_reference_data

    calls = []

    def cancelled():
        raise RuntimeError("cancelled by user")

    etf = SimpleNamespace(id="VWCE", isin="IE00BK5BQT80", instrument_type="etf", enabled=True)
    config = SimpleNamespace(universe=SimpleNamespace(etfs=[etf]))
    import pandas as pd
    import pytest

    with pytest.raises(RuntimeError, match="cancelled"):
        fetch_etf_e1_reference_data(config, SimpleNamespace(), http_get=lambda *a, **k: calls.append(a), registry=pd.DataFrame(), checkpoint=cancelled)
    assert calls == []
