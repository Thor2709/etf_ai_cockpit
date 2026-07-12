from __future__ import annotations

import json
from pathlib import Path
import pytest

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


def test_sec_provider_uses_conditional_cache_and_bounded_rate(tmp_path: Path) -> None:
    requests: list[tuple[str, dict[str, str]]] = []
    responses = [
        (json.dumps({"cik": "0000789019", "facts": {}}).encode(), 200, {"ETag": '"facts-v1"'}),
        (b"", 304, {"ETag": '"facts-v1"'}),
    ]
    clock = [0.0]

    def transport(url: str, headers: dict[str, str]):
        requests.append((url, headers))
        return responses.pop(0)

    provider = SecEdgarProvider(
        "ETF Cockpit test contact@example.invalid",
        cache_dir=tmp_path,
        transport=transport,
        rate_limit_seconds=1.0,
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    first = provider.fetch_companyfacts("789019")
    second = provider.fetch_companyfacts("789019")

    assert first.sha256 == second.sha256
    assert second.http_status == 304
    assert requests[1][1]["If-None-Match"] == '"facts-v1"'
    assert clock[0] >= 1.0
    assert (tmp_path / "companyfacts_0000789019.json.meta.json").exists()


def test_sec_provider_preserves_existing_cache_on_invalid_response(tmp_path: Path) -> None:
    payload = json.dumps({"cik": "0000789019", "facts": {}}).encode()
    calls = 0

    def transport(_url: str, _headers: dict[str, str]) -> bytes:
        nonlocal calls
        calls += 1
        return payload if calls == 1 else b"not-json"

    provider = SecEdgarProvider("ETF Cockpit test contact@example.invalid", cache_dir=tmp_path, transport=transport)
    first = provider.fetch_companyfacts("789019")
    with pytest.raises(ValueError, match="JSON"):
        provider.fetch_companyfacts("789019")
    assert first.path.read_bytes() == payload


def test_sec_provider_rejects_wrong_identity_payload(tmp_path: Path) -> None:
    def transport(_url: str, _headers: dict[str, str]) -> bytes:
        return json.dumps({"cik": "0000000001", "facts": {}}).encode()

    provider = SecEdgarProvider("ETF Cockpit test contact@example.invalid", cache_dir=tmp_path, transport=transport)
    with pytest.raises(ValueError, match="CIK"):
        provider.fetch_companyfacts("789019")
