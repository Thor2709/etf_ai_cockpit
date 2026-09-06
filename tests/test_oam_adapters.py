from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import json
import os
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
    import_local_oam_export,
    write_filing_coverage,
    write_oam_discovery_registry,
)


def _local_oam_payload(issuer: str, isin: str) -> dict[str, object]:
    return {
        "records": [
            {
                "issuer": issuer,
                "isin": isin,
                "title": "Annual report",
                "document_type": "annual_report",
                "published_at": "2026-07-01",
                "available_at": "2026-07-01T12:00:00Z",
                "source_url": "https://afm.nl/export/oam.json",
                "document_url": "https://afm.nl/export/report.pdf",
            }
        ]
    }


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


@pytest.mark.parametrize(
    ("suffix", "payload", "isin"),
    [
        (".json", json.dumps(_local_oam_payload("Local BV", "NL0000000101")).encode(), "NL0000000101"),
        (
            ".csv",
            b"issuer,isin,title,document_type,published_at,available_at\nLocal BV,NL0000000102,Report,annual_report,2026-07-01,2026-07-01T12:00:00Z\n",
            "NL0000000102",
        ),
        (
            ".xml",
            b"<?xml version='1.0'?><records><record><issuer>Local BV</issuer><isin>NL0000000103</isin><title>Report</title><document_type>annual_report</document_type><published_at>2026-07-01</published_at></record></records>",
            "NL0000000103",
        ),
    ],
)
def test_local_structured_oam_import_is_offline_content_addressed_and_manual_review(
    tmp_path: Path,
    suffix: str,
    payload: bytes,
    isin: str,
) -> None:
    source = tmp_path / f"oam-export{suffix}"
    source.write_bytes(payload)
    network_calls: list[str] = []

    def forbidden_transport(*_args: object) -> object:
        network_calls.append("called")
        raise AssertionError("local OAM import must not invoke transport")

    adapter = NetherlandsAfmOamAdapter(
        cache_dir=tmp_path / "cache",
        endpoint="https://afm.nl/remote.json",
        transport=forbidden_transport,
        enabled=False,
    )
    result = adapter.discover_local(source, OAMDiscoveryRequest(isin=isin))

    assert result.status == "manual_review"
    assert len(result.records) == 1
    record = result.records[0]
    assert record.source_authority == "local_user_import"
    assert record.coverage_status == "manual_review"
    assert record.manual_review is True
    assert record.execution_allowed is False
    assert record.identity_status == "matched_isin_manual_review"
    assert "manual_review_required" in record.warnings
    assert result.coverage == {
        "status": "manual_review",
        "matched_records": 1,
        "query": {"isin": record.isin},
        "source_authority": "local_user_import",
        "manual_review": True,
        "execution_allowed": False,
    }
    assert result.snapshot is not None
    assert Path(result.snapshot.path).read_bytes() == payload
    assert result.snapshot.sha256 == hashlib.sha256(payload).hexdigest()
    assert network_calls == []


def test_local_import_rejects_html_untrusted_links_and_oversize_without_registry_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_local_oam_payload("Local BV", "NL0000000110")), encoding="utf-8")
    adapter = NetherlandsAfmOamAdapter(cache_dir=tmp_path / "cache", enabled=False)
    accepted = adapter.discover_local(valid, OAMDiscoveryRequest(isin="NL0000000110"))
    registry = tmp_path / "oam.parquet"
    write_oam_discovery_registry(accepted, destination=registry)
    before = registry.read_bytes()

    html = tmp_path / "bad.html"
    html.write_text("<!doctype html><html>not an export</html>", encoding="utf-8")
    rejected_html = adapter.discover_local(html)
    assert rejected_html.status == "error"
    assert rejected_html.snapshot is None
    assert registry.read_bytes() == before

    linked = tmp_path / "linked.json"
    payload = _local_oam_payload("Local BV", "NL0000000111")
    payload["records"][0]["document_url"] = "https://evil.example/report.pdf"  # type: ignore[index]
    linked.write_text(json.dumps(payload), encoding="utf-8")
    rejected_link = adapter.discover_local(linked, OAMDiscoveryRequest(isin="NL0000000111"))
    assert rejected_link.status == "error"
    assert rejected_link.snapshot is not None
    assert "local_import_rejected" in rejected_link.warnings
    assert registry.read_bytes() == before

    monkeypatch.setattr("etf_cockpit.data.oam_adapters.MAX_RESPONSE_BYTES", 8)
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b'{"records": []}')
    rejected_size = adapter.discover_local(oversized)
    assert rejected_size.status == "error"
    assert rejected_size.snapshot is None
    assert registry.read_bytes() == before


def test_local_snapshot_breaks_hardlink_alias_and_survives_selected_source_mutation(tmp_path: Path) -> None:
    payload = json.dumps(_local_oam_payload("Local BV", "NL0000000113")).encode()
    source = tmp_path / "selected.json"
    source.write_bytes(payload)
    cache = tmp_path / "cache"
    snapshot_dir = cache / "snapshots"
    snapshot_dir.mkdir(parents=True)
    digest = hashlib.sha256(payload).hexdigest()
    expected_snapshot = snapshot_dir / f"nl_afm_oam-{digest[:16]}.json"
    os.link(source, expected_snapshot)

    result = NetherlandsAfmOamAdapter(cache_dir=cache, enabled=False).discover_local(
        source,
        OAMDiscoveryRequest(isin="NL0000000113"),
    )
    assert result.snapshot is not None
    assert not os.path.samefile(source, result.snapshot.path)
    source.write_bytes(b"mutated after import")
    assert Path(result.snapshot.path).read_bytes() == payload


def test_local_identity_requires_explicit_query_identifier_match(tmp_path: Path) -> None:
    source = tmp_path / "identity.json"
    source.write_text(
        json.dumps({"records": [{"issuer": "Issuer", "isin": "NL0000000114", "title": "Report"}]}),
        encoding="utf-8",
    )
    adapter = NetherlandsAfmOamAdapter(cache_dir=tmp_path / "cache", enabled=False)

    issuer_query = adapter.discover_local(source, OAMDiscoveryRequest(issuer="Issuer"))
    isin_query = adapter.discover_local(source, OAMDiscoveryRequest(isin="NL0000000114"))

    assert issuer_query.records[0].identity_status == "issuer_only_manual_review"
    assert isin_query.records[0].identity_status == "matched_isin_manual_review"


def test_local_availability_is_observed_snapshot_time_and_claim_is_retained(tmp_path: Path) -> None:
    source = tmp_path / "availability.json"
    source.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "issuer": "Issuer",
                        "isin": "NL0000000115",
                        "published_at": "2026-07-01",
                        "available_at": "2026-07-02",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = NetherlandsAfmOamAdapter(cache_dir=tmp_path / "cache", enabled=False).discover_local(
        source,
        OAMDiscoveryRequest(isin="NL0000000115"),
    )

    assert result.snapshot is not None
    record = result.records[0]
    assert record.available_at == result.snapshot.retrieved_at
    assert record.claimed_available_at == "2026-07-02"
    assert record.published_at == "2026-07-01"
    assert "availability_observed_at_snapshot" in record.warnings
    assert "claimed_availability_unverified" in record.warnings

def test_oam_registry_upsert_preserves_other_jurisdictions_for_local_import(tmp_path: Path) -> None:
    fr_source = tmp_path / "fr.json"
    fr_source.write_text(json.dumps({"records": [{"issuer": "France SA", "isin": "FR0000000110"}]}), encoding="utf-8")
    fr = FranceDilaOamAdapter(cache_dir=tmp_path / "fr", enabled=False).discover_local(fr_source, OAMDiscoveryRequest(isin="FR0000000110"))
    registry = tmp_path / "oam.parquet"
    write_oam_discovery_registry(fr, destination=registry)
    before = pd.read_parquet(registry)

    nl_source = tmp_path / "nl.json"
    nl_source.write_text(json.dumps(_local_oam_payload("Dutch BV", "NL0000000111")), encoding="utf-8")
    nl = NetherlandsAfmOamAdapter(cache_dir=tmp_path / "nl", enabled=False).discover_local(nl_source, OAMDiscoveryRequest(isin="NL0000000111"))
    write_oam_discovery_registry(nl, destination=registry)
    stored = pd.read_parquet(registry)

    assert set(stored["country"]) == {"FR", "NL"}
    assert set(stored.loc[stored["country"] == "FR", "source_id"]) == set(before["source_id"])
    assert set(stored.loc[stored["country"] == "NL", "source_authority"]) == {"local_user_import"}

    coverage_path = write_filing_coverage(
        nl,
        country="NL",
        request=OAMDiscoveryRequest(isin="NL0000000111"),
        destination=tmp_path / "coverage.parquet",
    )
    coverage = pd.read_parquet(coverage_path)
    assert coverage.loc[0, "official_records"] == 0
    assert coverage.loc[0, "manual_review_records"] == 1
    assert bool(coverage.loc[0, "execution_allowed"]) is False


def test_oam_registry_serializes_concurrent_jurisdiction_upserts(tmp_path: Path) -> None:
    registry = tmp_path / "oam.parquet"
    results = []
    for country, adapter_type, isin in (
        ("FR", FranceDilaOamAdapter, "FR0000000210"),
        ("NL", NetherlandsAfmOamAdapter, "NL0000000211"),
    ):
        source = tmp_path / f"{country.casefold()}.json"
        source.write_text(
            json.dumps({"records": [{"issuer": f"{country} issuer", "isin": isin, "title": "Annual report"}]}),
            encoding="utf-8",
        )
        results.append(
            adapter_type(cache_dir=tmp_path / f"cache-{country}", enabled=False).discover_local(
                source,
                OAMDiscoveryRequest(isin=isin),
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write_oam_discovery_registry, result, destination=registry)
            for result in results
        ]
        for future in futures:
            assert future.result() == registry

    assert set(pd.read_parquet(registry)["country"]) == {"FR", "NL"}


def test_filing_coverage_serializes_concurrent_jurisdiction_upserts(tmp_path: Path) -> None:
    destination = tmp_path / "coverage.parquet"
    results = []
    for country, adapter_type, isin in (
        ("FR", FranceDilaOamAdapter, "FR0000000212"),
        ("NL", NetherlandsAfmOamAdapter, "NL0000000213"),
    ):
        source = tmp_path / f"coverage-{country.casefold()}.json"
        source.write_text(
            json.dumps({"records": [{"issuer": f"{country} issuer", "isin": isin}]}),
            encoding="utf-8",
        )
        results.append(
            (
                country,
                OAMDiscoveryRequest(isin=isin),
                adapter_type(cache_dir=tmp_path / f"coverage-cache-{country}", enabled=False).discover_local(
                    source,
                    OAMDiscoveryRequest(isin=isin),
                ),
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                write_filing_coverage,
                result,
                country=country,
                request=request,
                destination=destination,
            )
            for country, request, result in results
        ]
        for future in futures:
            assert future.result() == destination

    stored = pd.read_parquet(destination)
    assert set(stored["country"]) == {"FR", "NL"}


def test_local_import_convenience_function_bypasses_disabled_adapter_transport(tmp_path: Path) -> None:
    source = tmp_path / "local.json"
    source.write_text(json.dumps(_local_oam_payload("Local BV", "NL0000000112")), encoding="utf-8")
    result = import_local_oam_export(source, country="NL", request=OAMDiscoveryRequest(isin="NL0000000112"), cache_dir=tmp_path / "cache")

    assert result.status == "manual_review"
    assert result.records[0].source_authority == "local_user_import"


def test_companies_house_local_import_accepts_local_keyword_contract_without_network(tmp_path: Path) -> None:
    source = tmp_path / "companies-house.json"
    source.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "company_number": "03842976",
                        "transaction_id": "local-accounts-1",
                        "date": "2026-07-01",
                        "category": "accounts",
                        "description": "Annual accounts",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = CompaniesHouseFilingAdapter(cache_dir=tmp_path / "cache", enabled=False).discover_local(
        source,
        OAMDiscoveryRequest(company_number="03842976", document_type="accounts"),
    )

    assert result.status == "manual_review"
    record = result.records[0]
    assert record.country == "GB"
    assert record.source_authority == "local_user_import"
    assert record.identity_status == "matched_company_number_manual_review"
    assert record.available_at == result.snapshot.retrieved_at


def test_companies_house_local_import_keeps_each_row_company_identity(tmp_path: Path) -> None:
    source = tmp_path / "companies-house-multi.json"
    source.write_text(
        json.dumps(
            {
                "items": [
                    {"company_number": "03842976", "transaction_id": "a", "category": "accounts"},
                    {"company_number": "01234567", "transaction_id": "b", "category": "accounts"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = CompaniesHouseFilingAdapter(cache_dir=tmp_path / "cache", enabled=False).discover_local(source)

    assert result.status == "manual_review"
    assert {record.issuer for record in result.records} == {"03842976", "01234567"}
    assert {record.identity_status for record in result.records} == {"issuer_only_manual_review"}


def test_local_import_keeps_identity_and_timing_gaps_explicit(tmp_path: Path) -> None:
    source = tmp_path / "timing.json"
    source.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "issuer": "Issuer without ISIN",
                        "published_at": "not-a-timestamp",
                        "title": "Report",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = NetherlandsAfmOamAdapter(cache_dir=tmp_path / "cache", enabled=False).discover_local(source)

    assert result.status == "manual_review"
    record = result.records[0]
    assert record.identity_status == "issuer_only_manual_review"
    assert record.availability_precision == "timestamp"
    assert "availability_observed_at_snapshot" in record.warnings
    assert "publication_timestamp_unavailable" in record.warnings
    assert record.coverage_status == "manual_review"


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


def test_companies_house_applies_requested_date_range_to_returned_records(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "items": [
                {
                    "transaction_id": "old-filing",
                    "date": "2025-12-31",
                    "category": "accounts",
                    "description": "accounts",
                }
            ]
        }
    ).encode()
    result = CompaniesHouseFilingAdapter(
        cache_dir=tmp_path,
        api_key="test-key",
        transport=_transport(payload, media_type="application/json"),
        enabled=True,
    ).discover(
        OAMDiscoveryRequest(
            company_number="03842976",
            document_type="accounts",
            date_from=date(2026, 1, 1),
        )
    )

    assert result.status == "manual_review"
    assert result.records == ()
    assert result.snapshot is not None


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
