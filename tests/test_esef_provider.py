from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.esef_provider import FilingsXbrlOrgProvider


def test_esef_provider_discovers_and_downloads_with_injected_transport(tmp_path: Path) -> None:
    package = b"PK-fake"

    def transport(url: str, headers: dict[str, str]) -> bytes:
        if url.endswith(".xbri"):
            return package
        return json.dumps({"data": []}).encode()

    provider = FilingsXbrlOrgProvider(cache_dir=tmp_path, transport=transport)
    listings = provider.list_filings("NL", 10)
    document = provider.download_report_package("id-1", "https://filings.xbrl.org/id-1.xbri")
    assert listings.status == "ok"
    assert isinstance(listings.data, pd.DataFrame)
    assert listings.data.empty
    assert document.path.exists()
    assert document.provider_id == "filings_xbrl_org"


def test_provider_flattens_api_rows_and_downloads_by_filing_id(tmp_path: Path) -> None:
    package = b"PK-official-package"
    payload = {
        "data": [{
            "id": "25092",
            "attributes": {
                "fxo_id": "LEI-2026-ESEF-NL-0",
                "country": "NL",
                "package_url": "/lei/2026/ESEF/NL/0/report.xbri",
                "sha256": "",
            },
        }]
    }

    def transport(url: str, headers: dict[str, str]):
        if url.endswith(".xbri"):
            return package, 200, {"Content-Type": "application/octet-stream"}
        return json.dumps(payload).encode(), 200, {"Content-Type": "application/json"}

    provider = FilingsXbrlOrgProvider(cache_dir=tmp_path, transport=transport)
    listings = provider.list_filings("NL", 10)
    assert listings.status == "ok"
    assert listings.data is not None
    assert listings.data.loc[0, "fxo_id"] == "LEI-2026-ESEF-NL-0"
    document = provider.download_report_package("LEI-2026-ESEF-NL-0")
    assert document.path.name.endswith(".xbri")
    assert document.path.read_bytes() == package
    assert document.sha256
    assert not (tmp_path / "LEI-2026-ESEF-NL-0.xbri").exists()


def test_provider_rejects_unsafe_filing_ids_and_reports_bounded_unavailability(tmp_path: Path) -> None:
    provider = FilingsXbrlOrgProvider(cache_dir=tmp_path, transport=lambda _url, _headers: (_ for _ in ()).throw(TimeoutError()))
    result = provider.list_filings("NL", 10)
    assert result.status == "unavailable"
    with pytest.raises(ValueError, match="filing_id"):
        provider.download_report_package("../escape", "https://filings.xbrl.org/escape.xbri")


def test_provider_selects_retained_official_fixture_by_fxo_id(tmp_path: Path) -> None:
    manifest = Path("tests/fixtures/official/manifest.json")
    provider = FilingsXbrlOrgProvider(cache_dir=tmp_path, fixture_manifest=manifest)
    listings = provider.list_filings("NL", 10)
    assert listings.status == "ok"
    assert listings.data is not None and not listings.data.empty
    document = provider.download_report_package("7245003GZ2696Y0W1X57-2026-03-31-ESEF-NL-0")
    assert document.source_url.endswith("7245003GZ2696Y0W1X57-2026-03-31.xbri")
    assert document.sha256 == "ba41916fc4457e5e49b2de7543fd140fa9cb2a9f67b3fdc333d9ed485ea7af6f"
