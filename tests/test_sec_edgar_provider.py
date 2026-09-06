from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider


@pytest.mark.parametrize("document_type", ["companyfacts", "submissions"])
def test_sec_retrieval_timestamp_matches_persisted_and_revalidated_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document_type: str
) -> None:
    import etf_cockpit.data.sec_edgar_provider as sec_provider

    class AdvancingClock(datetime):
        ticks = 0

        @classmethod
        def now(cls, tz=None):
            cls.ticks += 1
            return datetime(2026, 9, 3, tzinfo=timezone.utc) + timedelta(seconds=cls.ticks)

    monkeypatch.setattr(sec_provider, "datetime", AdvancingClock)
    payload = json.dumps({"cik": "0000789019", "facts": {}}).encode()
    responses = [(payload, 200, {"ETag": '"v1"'}), (b"", 304, {})]
    provider = SecEdgarProvider(
        "ETF AI Cockpit tests research@company.org",
        cache_dir=tmp_path,
        transport=lambda _url, _headers: responses.pop(0),
        rate_limit_seconds=0,
    )
    fetch = getattr(provider, f"fetch_{document_type}")
    first = fetch("789019")
    metadata = json.loads(
        (tmp_path / f"{document_type}_0000789019.json.meta.json").read_text(encoding="utf-8")
    )
    revalidated = fetch("789019")

    assert first.retrieved_at.isoformat() == metadata["retrieved_at"]
    assert revalidated.retrieved_at == first.retrieved_at
    assert first.retrieved_at.utcoffset() == timedelta(0)
    assert revalidated.path == first.path
    assert revalidated.sha256 == first.sha256
    assert revalidated.http_status == 304


@pytest.mark.parametrize(
    "user_agent",
    [
        "ETF AI contact@example.invalid",
        "ETF AI contact@example.com",
        "ETF AI contact@example.net",
        "ETF AI contact@example.org",
        "1234@567",
        "a@b.cdef",
        "ETF AI contact@-example.com",
        "ETF AI contact@example..com",
        "ETF AI contact@.example.com",
        "ETF AI contact@example.com.",
        "ETF AI a..b@example.com",
    ],
)
def test_sec_provider_rejects_placeholder_or_non_descriptive_user_agent(tmp_path: Path, user_agent: str) -> None:
    with pytest.raises(ValueError, match="organisation|contact"):
        SecEdgarProvider(user_agent, cache_dir=tmp_path, transport=lambda _url, _headers: b"{}")


def test_sec_provider_uses_compliant_user_agent_and_raw_document(tmp_path: Path) -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str]) -> bytes:
        requests.append((url, headers))
        return json.dumps({"cik": "0000789019", "facts": {}}).encode()

    provider = SecEdgarProvider("ETF AI Cockpit tests research@company.org", cache_dir=tmp_path, transport=transport)
    document = provider.fetch_companyfacts("789019")
    assert document.path.exists()
    assert document.http_status == 200
    assert requests[0][0].endswith("CIK0000789019.json")
    assert "ETF AI Cockpit" in requests[0][1]["User-Agent"]


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
        "ETF AI Cockpit tests research@company.org",
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


def test_sec_provider_cold_304_retries_unconditionally(tmp_path: Path) -> None:
    payload = json.dumps({"cik": "0000789019", "facts": {}}).encode()
    responses = [(payload, 200, {"ETag": '"facts-v1"'}), (b"", 304, {}), (payload, 200, {})]
    requests: list[dict[str, str]] = []

    def transport(_url: str, headers: dict[str, str]) -> tuple[bytes, int, dict[str, str]]:
        requests.append(dict(headers))
        return responses.pop(0)

    first_provider = SecEdgarProvider(
        "ETF AI Cockpit tests research@company.org",
        cache_dir=tmp_path,
        transport=transport,
        rate_limit_seconds=0,
    )
    first = first_provider.fetch_companyfacts("789019")
    first_provider._authority_ledger.clear()
    second = first_provider.fetch_companyfacts("789019")
    assert first.sha256 == second.sha256
    assert second.http_status == 200
    assert "If-None-Match" not in requests[1]
    assert "If-Modified-Since" not in requests[1]
    assert "Range" not in requests[1]


@pytest.mark.parametrize("retrieved_at", [None, "2026-09-03T12:00:00", "not-a-timestamp"])
def test_sec_provider_rejects_invalid_persisted_304_timestamp_without_replacing_cache(
    tmp_path: Path, retrieved_at: str | None
) -> None:
    payload = json.dumps({"cik": "0000789019", "facts": {}}).encode()
    provider = SecEdgarProvider(
        "ETF AI Cockpit tests research@company.org",
        cache_dir=tmp_path,
        transport=lambda _url, _headers: (payload, 200, {"ETag": '"facts-v1"'}),
        rate_limit_seconds=0,
    )
    first = provider.fetch_companyfacts("789019")
    metadata_path = tmp_path / "companyfacts_0000789019.json.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if retrieved_at is None:
        metadata.pop("retrieved_at")
    else:
        metadata["retrieved_at"] = retrieved_at
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    cache_bytes = first.path.read_bytes()
    provider.transport = lambda _url, _headers: (b"", 304, {"ETag": '"facts-v1"'})

    with pytest.raises(ValueError, match="provider-owned session proof"):
        provider.fetch_companyfacts("789019")

    assert first.path.read_bytes() == cache_bytes
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == metadata


def test_sec_provider_preserves_existing_cache_on_invalid_response(tmp_path: Path) -> None:
    payload = json.dumps({"cik": "0000789019", "facts": {}}).encode()
    calls = 0

    def transport(_url: str, _headers: dict[str, str]) -> bytes:
        nonlocal calls
        calls += 1
        return payload if calls == 1 else b"not-json"

    provider = SecEdgarProvider("ETF AI Cockpit tests research@company.org", cache_dir=tmp_path, transport=transport)
    first = provider.fetch_companyfacts("789019")
    with pytest.raises(ValueError, match="JSON"):
        provider.fetch_companyfacts("789019")
    assert first.path.read_bytes() == payload


def test_sec_provider_rejects_wrong_identity_payload(tmp_path: Path) -> None:
    def transport(_url: str, _headers: dict[str, str]) -> bytes:
        return json.dumps({"cik": "0000000001", "facts": {}}).encode()

    provider = SecEdgarProvider("ETF AI Cockpit tests research@company.org", cache_dir=tmp_path, transport=transport)
    with pytest.raises(ValueError, match="CIK"):
        provider.fetch_companyfacts("789019")


def test_sec_provider_rejects_corrupt_cached_304_payload(tmp_path: Path) -> None:
    payload = json.dumps({"cik": "0000789019", "facts": {}}).encode()

    def transport(_url: str, _headers: dict[str, str]):
        return payload, 200, {"ETag": '"facts-v1"'}

    provider = SecEdgarProvider("ETF AI Cockpit tests research@company.org", cache_dir=tmp_path, transport=transport)
    provider.fetch_companyfacts("789019")
    cached = tmp_path / "companyfacts_0000789019.json"
    cached.write_text(json.dumps({"cik": "0000000001", "facts": {}}), encoding="utf-8")

    def not_modified(_url: str, _headers: dict[str, str]):
        return b"", 304, {"ETag": '"facts-v1"'}

    provider.transport = not_modified
    with pytest.raises(ValueError, match="cache|CIK|checksum"):
        provider.fetch_companyfacts("789019")


def test_sec_provider_retains_immutable_raw_generations(tmp_path: Path) -> None:
    first_payload = json.dumps({"cik": "0000789019", "facts": {"us-gaap": {"Assets": {}}}}).encode()
    second_payload = json.dumps({"cik": "0000789019", "facts": {"us-gaap": {"Assets": {"changed": True}}}}).encode()
    responses = [first_payload, second_payload]

    def transport(_url: str, _headers: dict[str, str]) -> bytes:
        return responses.pop(0)

    provider = SecEdgarProvider("ETF AI Cockpit tests research@company.org", cache_dir=tmp_path, transport=transport)
    first = provider.fetch_companyfacts("789019")
    second = provider.fetch_companyfacts("789019")

    assert first.path != second.path
    assert first.path.read_bytes() == first_payload
    assert second.path.read_bytes() == second_payload
    assert first.sha256 != second.sha256
