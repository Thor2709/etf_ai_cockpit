from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.oam_adapters import (
    CompaniesHouseFilingAdapter,
    DenmarkFinanstilsynetOamAdapter,
    FinlandFsaOamAdapter,
    FranceDilaOamAdapter,
    NetherlandsAfmOamAdapter,
    NorwayFinanstilsynetOamAdapter,
    OAMDiscoveryRequest,
    SwedenFiOamAdapter,
    archive_manual_official_filing,
    download_oam_document,
    write_filing_coverage,
    write_oam_discovery_registry,
)


def _transport(payload: bytes, *, media_type: str, status: int = 200):
    def fetch(_url: str, _headers: object):
        return payload, status, {"content-type": media_type}

    return fetch


def test_france_adapter_parses_json_retries_and_retains_immutable_snapshot(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "data": [
                {
                    "issuer_name": "Example SA",
                    "isin": "FR0000000001",
                    "title": "Annual financial report",
                    "document_type": "annual_report",
                    "publication_date": "2026-07-15",
                    "document_url": "https://data.gouv.fr/files/report.pdf",
                }
            ]
        }
    ).encode()
    attempts = 0

    def fetch(url: str, headers: object):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return b"busy", 503, {"content-type": "application/json"}
        return _transport(payload, media_type="application/json")(url, headers)

    result = FranceDilaOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://www.data.gouv.fr/api/financial-information",
        transport=fetch,
        enabled=True,
        retries=1,
        sleep=lambda _seconds: None,
    ).discover(OAMDiscoveryRequest(issuer="Example", isin="FR0000000001"))

    assert result.status == "ok"
    assert result.retry_count == 1
    assert result.records[0].source_authority == "official_oam"
    assert result.records[0].terms_url.startswith("https://www.data.gouv.fr/")
    assert result.snapshot is not None
    assert Path(result.snapshot.path).read_bytes() == payload
    assert result.snapshot.sha256


def test_afm_adapter_parses_csv_and_writes_registry(tmp_path: Path) -> None:
    payload = (
        "issuer,isin,title,document_type,published_at,source_url\n"
        "Dutch NV,NL0000000002,Annual report,annual_report,2026-06-01,https://www.afm.nl/export/report.pdf\n"
    ).encode()
    adapter = NetherlandsAfmOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://export.afm.nl/oam.csv",
        transport=_transport(payload, media_type="text/csv"),
        enabled=True,
    )
    result = adapter.discover(OAMDiscoveryRequest(isin="NL0000000002"))
    destination = write_oam_discovery_registry(result, destination=tmp_path / "oam.parquet")

    assert result.status == "ok"
    assert destination.exists()
    stored = __import__("pandas").read_parquet(destination)
    assert stored.loc[0, "snapshot_sha256"] == result.snapshot.sha256
    assert stored.loc[0, "source_authority"] == "official_oam"


def test_afm_adapter_parses_structured_xml_export(tmp_path: Path) -> None:
    payload = b"""<?xml version='1.0'?><records><record><issuer>XML BV</issuer><isin>NL0000000003</isin><title>Report</title><document_type>annual_report</document_type><date>2026-05-01</date><url>https://afm.nl/report.pdf</url></record></records>"""
    result = NetherlandsAfmOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://afm.nl/oam.xml",
        transport=_transport(payload, media_type="application/xml"),
        enabled=True,
    ).discover(OAMDiscoveryRequest(isin="NL0000000003"))

    assert result.status == "ok"
    assert result.records[0].issuer == "XML BV"
    assert result.records[0].published_at == "2026-05-01"


def test_discovered_document_download_is_checksum_backed_and_official_only(tmp_path: Path) -> None:
    payload = b"%PDF-raw-official-document"
    discovery = NetherlandsAfmOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://afm.nl/oam.json",
        transport=_transport(
            json.dumps({"results": [{"issuer": "Dutch BV", "isin": "NL0000000004", "document_url": "https://afm.nl/report.pdf"}]}).encode(),
            media_type="application/json",
        ),
        enabled=True,
    ).discover(OAMDiscoveryRequest(isin="NL0000000004"))
    snapshot = download_oam_document(
        discovery.records[0],
        cache_dir=tmp_path / "documents",
        transport=_transport(payload, media_type="application/pdf"),
    )

    assert Path(snapshot.path).read_bytes() == payload
    assert snapshot.sha256


def test_missing_or_ambiguous_results_fail_closed_with_manual_fallback(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "results": [
                {"issuer": "Ambiguous BV", "isin": "NL0000000010", "title": "One"},
                {"issuer": "Ambiguous BV", "isin": "NL0000000011", "title": "Two"},
            ]
        }
    ).encode()
    result = NetherlandsAfmOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://afm.nl/oam.json",
        transport=_transport(payload, media_type="application/json"),
        enabled=True,
    ).discover(OAMDiscoveryRequest(issuer="Ambiguous BV"))

    assert result.status == "manual_review"
    assert result.records == ()
    assert result.manual_fallback is True
    assert "ambiguous_issuer" in result.warnings

    disabled = FranceDilaOamAdapter(cache_dir=tmp_path).discover()
    assert disabled.status == "unavailable"
    assert disabled.manual_fallback is True


def test_html_and_untrusted_hosts_are_rejected_without_scraping(tmp_path: Path) -> None:
    html = b"<!doctype html><html><body>not an export</body></html>"
    result = FranceDilaOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://www.data.gouv.fr/oam",
        transport=_transport(html, media_type="text/html"),
        enabled=True,
    ).discover()
    untrusted = FranceDilaOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://example.com/oam.json",
        transport=_transport(b"{}", media_type="application/json"),
        enabled=True,
    ).discover()

    assert result.status == "error"
    assert result.manual_fallback is True
    assert untrusted.status == "error"
    # The trusted-host response is retained for audit even though HTML is
    # rejected as an input format; the untrusted host is rejected before fetch.
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 1


def test_payload_links_cannot_expand_the_official_host_boundary(tmp_path: Path) -> None:
    payload = json.dumps({"results": [{"issuer": "Safe SA", "isin": "FR0000000005", "url": "https://evil.example/document.pdf"}]}).encode()
    result = FranceDilaOamAdapter(
        cache_dir=tmp_path,
        endpoint="https://data.gouv.fr/oam.json",
        transport=_transport(payload, media_type="application/json"),
        enabled=True,
    ).discover(OAMDiscoveryRequest(isin="FR0000000005"))

    assert result.status == "ok"
    assert result.records[0].document_url == ""
    assert "untrusted_document_url" in result.records[0].warnings


@pytest.mark.parametrize(
    ("adapter_type", "endpoint", "country"),
    [
        (DenmarkFinanstilsynetOamAdapter, "https://oam.finanstilsynet.dk/export.json", "DK"),
        (SwedenFiOamAdapter, "https://www.fi.se/export.json", "SE"),
        (FinlandFsaOamAdapter, "https://www.finanssivalvonta.fi/export.json", "FI"),
        (NorwayFinanstilsynetOamAdapter, "https://www.finanstilsynet.no/export.json", "NO"),
    ],
)
def test_nordic_adapters_share_the_official_structured_export_contract(
    tmp_path: Path,
    adapter_type,
    endpoint: str,
    country: str,
) -> None:
    payload = json.dumps(
        {
            "records": [
                {
                    "issuer": "Nordic Issuer",
                    "isin": f"{country}0000000001",
                    "title": "Annual report",
                    "document_type": "annual_report",
                    "published_at": "2026-07-01T06:00:00Z",
                    "available_at": "2026-07-01T06:05:00Z",
                    "document_url": endpoint.rsplit("/", 1)[0] + "/annual-report.pdf",
                }
            ]
        }
    ).encode()

    result = adapter_type(
        cache_dir=tmp_path / country,
        endpoint=endpoint,
        transport=_transport(payload, media_type="application/json"),
        enabled=True,
    ).discover(OAMDiscoveryRequest(isin=f"{country}0000000001"))

    assert result.status == "ok"
    assert result.records[0].country == country
    assert result.records[0].available_at == "2026-07-01T06:05:00Z"
    assert result.records[0].availability_precision == "timestamp"
    assert result.records[0].identity_status == "matched_isin"


@pytest.mark.parametrize(
    "adapter_type",
    [
        DenmarkFinanstilsynetOamAdapter,
        FinlandFsaOamAdapter,
        FranceDilaOamAdapter,
        NetherlandsAfmOamAdapter,
        NorwayFinanstilsynetOamAdapter,
        SwedenFiOamAdapter,
    ],
)
def test_jurisdiction_adapters_fail_closed_when_no_structured_endpoint_is_enabled(
    tmp_path: Path,
    adapter_type,
) -> None:
    result = adapter_type(cache_dir=tmp_path).discover(OAMDiscoveryRequest())

    assert result.status == "unavailable"
    assert result.manual_fallback is True
    assert result.snapshot is None
    assert "manual_fallback_available" in result.warnings


def test_oam_discovery_retains_amendment_and_date_precision(tmp_path: Path) -> None:
    endpoint = "https://www.fi.se/export.json"
    payload = json.dumps(
        {
            "records": [
                {
                    "issuer": "Issuer",
                    "isin": "SE0000000001",
                    "title": "Corrected annual report",
                    "document_type": "annual_report",
                    "published_at": "2026-07-01",
                    "amendment_of": "original-filing-1",
                    "document_url": "https://www.fi.se/report.pdf",
                }
            ]
        }
    ).encode()

    result = SwedenFiOamAdapter(
        cache_dir=tmp_path,
        endpoint=endpoint,
        transport=_transport(payload, media_type="application/json"),
        enabled=True,
    ).discover(OAMDiscoveryRequest(isin="SE0000000001"))

    assert result.status == "ok"
    assert result.records[0].amendment_of == "original-filing-1"
    assert result.records[0].availability_precision == "date"
    assert "availability_precision_date" in result.records[0].warnings


def test_companies_house_discovery_requires_company_identity_and_keeps_credentials_out_of_records(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    payload = json.dumps(
        {
            "items": [
                {
                    "transaction_id": "MzAwOTQxNTg5N2FkaXF6a2N4",
                    "date": "2026-07-01",
                    "category": "accounts",
                    "description": "accounts-with-accounts-type-full",
                    "links": {"document_metadata": "/document/abc123"},
                }
            ]
        }
    ).encode()

    def fetch(url: str, headers: object):
        captured.update({"url": url, "headers": headers})
        return payload, 200, {"content-type": "application/json"}

    result = CompaniesHouseFilingAdapter(
        cache_dir=tmp_path,
        api_key="secret-key",
        transport=fetch,
        enabled=True,
    ).discover(OAMDiscoveryRequest(company_number="03842976", document_type="accounts"))

    assert result.status == "ok"
    assert "/company/03842976/filing-history" in str(captured["url"])
    assert str(captured["headers"]).find("secret-key") == -1
    assert result.records[0].identity_status == "matched_company_number"
    assert result.records[0].document_url.endswith("/document/abc123/content")
    assert "secret-key" not in json.dumps(result.records[0].__dict__)

    downloaded = download_oam_document(
        result.records[0],
        cache_dir=tmp_path / "documents",
        transport=_transport(b"official filing", media_type="application/pdf"),
    )
    assert Path(downloaded.path).read_bytes() == b"official filing"


def test_companies_house_discovery_rejects_non_api_official_hosts(tmp_path: Path) -> None:
    result = CompaniesHouseFilingAdapter(
        cache_dir=tmp_path,
        endpoint="https://download.companieshouse.gov.uk",
        api_key="test-key",
        enabled=True,
    ).discover(OAMDiscoveryRequest(company_number="03842976"))

    assert result.status == "error"
    assert "official HTTPS API host" in result.message


def test_filing_coverage_persists_unavailable_and_success_states(tmp_path: Path) -> None:
    request = OAMDiscoveryRequest(isin="FR0000000001")
    disabled = FranceDilaOamAdapter(cache_dir=tmp_path).discover(request)
    destination = write_filing_coverage(
        disabled,
        country="FR",
        request=request,
        destination=tmp_path / "coverage.parquet",
    )

    stored = pd.read_parquet(destination)
    assert stored.loc[0, "status"] == "unavailable"
    assert bool(stored.loc[0, "manual_fallback"]) is True
    assert bool(stored.loc[0, "execution_allowed"]) is False


def test_manual_official_filing_archive_is_immutable_and_timing_explicit(tmp_path: Path) -> None:
    source = tmp_path / "accounts.xbrl"
    source.write_bytes(b"<xbrl>official accounts</xbrl>")
    queue = tmp_path / "manual-queue.parquet"

    first = archive_manual_official_filing(
        source,
        jurisdiction="GB",
        instrument_id="GB:03842976",
        source_url="https://find-and-update.company-information.service.gov.uk/company/03842976/filing-history",
        published_at="2026-07-01",
        raw_dir=tmp_path / "raw",
        queue_path=queue,
    )
    second = archive_manual_official_filing(
        source,
        jurisdiction="GB",
        instrument_id="GB:03842976",
        source_url="https://find-and-update.company-information.service.gov.uk/company/03842976/filing-history",
        published_at="2026-07-01",
        raw_dir=tmp_path / "raw",
        queue_path=queue,
    )

    assert first == second
    assert Path(first.raw_path).read_bytes() == source.read_bytes()
    assert first.availability_precision == "date"
    assert first.manual_review is True
    assert first.execution_allowed is False
    assert len(pd.read_parquet(queue)) == 1


def test_manual_companies_house_bulk_file_is_an_allowed_no_quota_source(tmp_path: Path) -> None:
    source = tmp_path / "Accounts_Bulk_Data.zip"
    source.write_bytes(b"PK-official-bulk")

    record = archive_manual_official_filing(
        source,
        jurisdiction="GB",
        instrument_id="GB:BULK-ACCOUNTS",
        source_url="https://download.companieshouse.gov.uk/en_accountsdata.html",
        document_type="accounts_bulk_archive",
        raw_dir=tmp_path / "raw",
        queue_path=tmp_path / "queue.parquet",
    )

    assert record.source_authority == "official_manual_import"
    assert record.coverage_status == "archived_timing_unavailable"
    assert record.execution_allowed is False


def test_manual_official_filing_rejects_untrusted_source_url(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-test")

    with pytest.raises(ValueError, match="official HTTPS host"):
        archive_manual_official_filing(
            source,
            jurisdiction="SE",
            instrument_id="SE:TEST",
            source_url="https://example.com/report.pdf",
            raw_dir=tmp_path / "raw",
            queue_path=tmp_path / "queue.parquet",
        )


def test_manual_official_filing_rejects_invalid_timing(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-test")

    with pytest.raises(ValueError, match="timestamps must be valid"):
        archive_manual_official_filing(
            source,
            jurisdiction="GB",
            instrument_id="GB:TEST",
            source_url="https://find-and-update.company-information.service.gov.uk/company/TEST/filing-history",
            published_at="not-a-date",
            raw_dir=tmp_path / "raw",
            queue_path=tmp_path / "queue.parquet",
        )
