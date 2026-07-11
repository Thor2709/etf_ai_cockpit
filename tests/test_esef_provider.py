from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

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
