from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.data.oam_adapters import (
    FranceDilaOamAdapter,
    NetherlandsAfmOamAdapter,
    OAMDiscoveryRequest,
    download_oam_document,
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
