from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider


def test_sec_provider_uses_compliant_user_agent_and_raw_document(tmp_path: Path) -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str]) -> bytes:
        requests.append((url, headers))
        return json.dumps({"cik": "0000789019", "facts": {}}).encode()

    provider = SecEdgarProvider("ETF Cockpit test contact@example.invalid", cache_dir=tmp_path, transport=transport)
    document = provider.fetch_companyfacts("789019")
    assert document.path.exists()
    assert document.http_status == 200
    assert requests[0][0].endswith("CIK0000789019.json")
    assert "ETF Cockpit" in requests[0][1]["User-Agent"]
