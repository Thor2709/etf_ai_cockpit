from __future__ import annotations

import hashlib
from contextlib import contextmanager
import http.client
from io import BytesIO
import json
from pathlib import Path
import struct
import threading
from urllib.error import HTTPError
import zipfile

import pytest

from etf_cockpit.core.workflow import WorkflowTransitionError
from etf_cockpit.data.sec_edgar_bulk import (
    COMPANYFACTS_BULK_URL,
    SUBMISSIONS_BULK_URL,
    SecEdgarBulkUnavailable,
)
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider


class Response:
    def __init__(self, payload: bytes, status: int = 200, headers: dict[str, str] | None = None, chunk: int = 7, effective_url: str | None = None) -> None:
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.chunk = chunk
        self.offset = 0
        self.closed = False
        self.requested_sizes: list[int] = []
        self.effective_url = effective_url

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        if size < 0:
            size = len(self.payload)
        size = min(size, self.chunk)
        result = self.payload[self.offset : self.offset + size]
        self.offset += len(result)
        return result

    def close(self) -> None:
        self.closed = True

    def geturl(self) -> str | None:
        return self.effective_url


def _zip_bytes() -> bytes:
    from io import BytesIO

    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("CIK0000000001.json", b"{\"cik\": 1}")
    return output.getvalue()


def _zip_bytes_with(value: bytes) -> bytes:
    from io import BytesIO

    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("CIK0000000001.json", value)
    return output.getvalue()


def _provider(tmp_path: Path, responses: list[Response], **kwargs) -> tuple[SecEdgarProvider, list[tuple[str, dict[str, str]]]]:
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str]) -> Response:
        calls.append((url, headers.copy()))
        return responses.pop(0)

    return SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path, transport=transport, rate_limit_seconds=0, **kwargs), calls


def test_both_bulk_endpoints_stream_ua_and_retain_provenance(tmp_path: Path) -> None:
    payload = _zip_bytes()
    company_response = Response(payload)
    submission_response = Response(payload)
    provider, calls = _provider(tmp_path, [company_response, submission_response])

    companyfacts = provider.fetch_companyfacts_bulk()
    submissions = provider.fetch_submissions_bulk()

    assert companyfacts.source_url == COMPANYFACTS_BULK_URL
    assert submissions.source_url == SUBMISSIONS_BULK_URL
    assert companyfacts.http_status == submissions.http_status == 200
    assert companyfacts.media_type == submissions.media_type == "application/zip"
    assert companyfacts.retrieved_at.tzinfo is not None
    assert companyfacts.sha256 == hashlib.sha256(payload).hexdigest()
    assert [url for url, _ in calls] == [COMPANYFACTS_BULK_URL, SUBMISSIONS_BULK_URL]
    assert all(headers["User-Agent"].startswith("ETF Research") for _, headers in calls)
    assert all(headers["Accept"] == "application/zip" for _, headers in calls)
    assert all(size > 0 and size <= 1024 * 1024 for size in company_response.requested_sizes)
    assert all(size > 0 and size <= 1024 * 1024 for size in submission_response.requested_sizes)


def test_304_preserves_original_acquisition_time_and_bytes(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload, headers={"ETag": '"stable"'}), Response(b"", 304)])
    first = provider.fetch_companyfacts_bulk()
    second = provider.fetch_companyfacts_bulk()

    assert second.http_status == 304
    assert second.sha256 == first.sha256
    assert second.retrieved_at == first.retrieved_at


def test_interrupted_response_keeps_partial_and_resumes_exact_range(tmp_path: Path) -> None:
    payload = _zip_bytes()

    class Broken(Response):
        def read(self, size: int = -1) -> bytes:
            if self.offset >= len(self.payload) // 2:
                raise OSError("interrupted")
            return super().read(size)

    first_response = Broken(payload, headers={"ETag": '"stable"', "Content-Length": str(len(payload))})
    provider, calls = _provider(tmp_path, [first_response], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    # The partial offset is the bytes actually delivered, not an assumed range.
    partial = tmp_path / "sec_edgar_bulk" / "partials" / "companyfacts.part"
    offset = partial.stat().st_size
    resume_headers: dict[str, str] = {}

    def resume_transport(_url: str, headers: dict[str, str]) -> Response:
        resume_headers.update(headers)
        start = int(headers["Range"].split("=", 1)[1].rstrip("-"))
        return Response(payload[start:], 206, {"ETag": '"stable"', "Content-Range": f"bytes {start}-{len(payload)-1}/{len(payload)}"})

    provider.transport = resume_transport
    second = provider.fetch_companyfacts_bulk()

    assert second.http_status == 206
    assert resume_headers["Range"] == f"bytes={offset}-"
    assert resume_headers["If-Range"] == '"stable"'


def test_mismatched_206_validator_or_range_fails_without_splicing(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload[:5], headers={"ETag": '"stable"', "Content-Length": str(len(payload))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    partial = tmp_path / "sec_edgar_bulk" / "partials" / "companyfacts.part"
    old = partial.read_bytes()
    provider.transport = lambda _url, _headers: Response(payload[5:], 206, {"ETag": '"changed"', "Content-Range": f"bytes 5-{len(payload)-1}/{len(payload)}"})
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    assert partial.read_bytes() == old


def test_mismatched_206_range_fails_without_splicing(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload[:5], headers={"ETag": '"stable"', "Content-Length": str(len(payload))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    partial = tmp_path / "sec_edgar_bulk" / "partials" / "companyfacts.part"
    old = partial.read_bytes()
    provider.transport = lambda _url, _headers: Response(payload[5:], 206, {"ETag": '"stable"', "Content-Range": f"bytes 6-{len(payload)-1}/{len(payload)}"})

    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    assert partial.read_bytes() == old


def test_mismatched_206_content_length_fails_before_append(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload[:5], headers={"ETag": '"stable"', "Content-Length": str(len(payload))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    partial = tmp_path / "sec_edgar_bulk" / "partials" / "companyfacts.part"
    old = partial.read_bytes()
    provider.transport = lambda _url, _headers: Response(
        payload[5:], 206,
        {"ETag": '"stable"', "Content-Range": f"bytes 5-{len(payload)-1}/{len(payload)}", "Content-Length": "2"},
    )

    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    assert partial.read_bytes() == old


def test_same_size_prefix_mutation_invalidates_stale_generation(tmp_path: Path) -> None:
    payload_a = _zip_bytes_with(b"generation-a")
    payload_b = _zip_bytes_with(b"generation-b")
    provider, _ = _provider(tmp_path, [Response(payload_a[:7], headers={"ETag": '"a"', "Content-Length": str(len(payload_a))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    partial = tmp_path / "sec_edgar_bulk" / "partials" / "companyfacts.part"
    mutated_prefix = bytearray(payload_b[:7])
    mutated_prefix[-1] ^= 1
    partial.write_bytes(mutated_prefix)
    observed: dict[str, str] = {}

    def response(_url: str, headers: dict[str, str]) -> Response:
        observed.update(headers)
        return Response(payload_a[7:], 206, {"ETag": '"a"', "Content-Range": f"bytes 7-{len(payload_a)-1}/{len(payload_a)}"})

    provider.transport = response
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    assert "Range" not in observed
    assert not list((tmp_path / "sec_edgar_bulk" / "objects" / "companyfacts").glob("*.zip"))


def test_200_restarts_when_partial_validator_is_unavailable(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, calls = _provider(tmp_path, [Response(payload[:5], headers={"ETag": '"stable"', "Content-Length": str(len(payload))}), Response(payload, 200, {})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    result = provider.fetch_companyfacts_bulk()

    assert result.http_status == 200
    assert result.path.read_bytes() == payload


def test_partial_source_url_binding_disables_resume(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload[:5], headers={"ETag": '"stable"', "Content-Length": str(len(payload))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    partial_meta = tmp_path / "sec_edgar_bulk" / "partials" / "companyfacts.json"
    metadata = json.loads(partial_meta.read_text(encoding="utf-8"))
    metadata["source_url"] = "https://sec.invalid/other.zip"
    partial_meta.write_text(json.dumps(metadata), encoding="utf-8")
    observed: dict[str, str] = {}

    def response(_url: str, headers: dict[str, str]) -> Response:
        observed.update(headers)
        return Response(payload, 200, {})

    provider.transport = response
    result = provider.fetch_companyfacts_bulk()

    assert result.http_status == 200
    assert "Range" not in observed
    assert result.path.read_bytes() == payload


def test_partial_resume_requires_the_same_provider_session(tmp_path: Path) -> None:
    payload = _zip_bytes()
    first, _ = _provider(tmp_path, [Response(payload[:7], headers={"ETag": '"stable"', "Content-Length": str(len(payload))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        first.fetch_companyfacts_bulk()
    observed: dict[str, str] = {}

    def response(_url: str, headers: dict[str, str]) -> Response:
        observed.update(headers)
        return Response(payload, 200, {})

    second, _ = _provider(tmp_path, [Response(payload)], max_retries=0)
    second.transport = response
    result = second.fetch_companyfacts_bulk()
    assert "Range" not in observed
    assert "If-Range" not in observed
    assert result.path.read_bytes() == payload


def test_bad_zip_or_truncation_preserves_last_good_artifact(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload, headers={"ETag": '"good"'})])
    good = provider.fetch_companyfacts_bulk()
    good_bytes = good.path.read_bytes()
    provider.transport = lambda _url, _headers: Response(b"not-a-zip", 200, {})

    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    assert good.path.read_bytes() == good_bytes


def test_declared_truncation_preserves_last_good_artifact(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload, headers={"ETag": '"good"'})])
    good = provider.fetch_companyfacts_bulk()
    good_bytes = good.path.read_bytes()
    provider.transport = lambda _url, _headers: Response(b"short", 200, {"Content-Length": str(len(payload) + 10)})

    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    assert good.path.read_bytes() == good_bytes


def test_quota_response_retries_with_bounded_delay(tmp_path: Path) -> None:
    payload = _zip_bytes()
    delays: list[float] = []
    provider, calls = _provider(
        tmp_path,
        [Response(b"", 429), Response(payload)],
        max_retries=1,
        sleep=delays.append,
    )

    result = provider.fetch_companyfacts_bulk()

    assert result.http_status == 200
    assert len(calls) == 2
    assert delays == [0.25]


def test_cache_only_is_explicit_and_does_not_invoke_transport(tmp_path: Path) -> None:
    def unexpected(_url: str, _headers: dict[str, str]) -> Response:
        raise AssertionError("cache-only acquisition must not call transport")

    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path, transport=unexpected, rate_limit_seconds=0)
    with pytest.raises(SecEdgarBulkUnavailable, match="no cached"):
        provider.fetch_companyfacts_bulk(cache_only=True)


def test_cache_only_replay_reuses_process_bound_admission(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload)], max_retries=0)
    first = provider.fetch_companyfacts_bulk()
    replay = provider.fetch_companyfacts_bulk(cache_only=True)
    forged = type(first)(
        first.path,
        first.source_url,
        first.retrieved_at,
        first.sha256,
        first.provider_id,
        first.document_type,
        first.media_type,
        first.http_status,
    )

    assert replay is not first
    assert provider._session_generation_matches(first)
    assert provider._session_generation_matches(replay)
    assert forged == first


def test_bulk_cold_304_retries_unconditionally(tmp_path: Path) -> None:
    payload = _zip_bytes()
    responses = [Response(payload), Response(b"", status=304), Response(payload)]
    provider, _ = _provider(tmp_path, responses, max_retries=0)
    first = provider.fetch_companyfacts_bulk()
    provider._authority_ledger.clear()
    second = provider.fetch_companyfacts_bulk()
    assert second.http_status == 200
    assert second.sha256 == first.sha256


def test_cache_only_after_session_ledger_eviction_fails_closed(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path, [Response(_zip_bytes())], max_retries=0)
    provider.fetch_companyfacts_bulk()
    provider._authority_ledger.clear()

    with pytest.raises(SecEdgarBulkUnavailable, match="provider-owned (?:acquisition proof|session proof)"):
        provider.fetch_companyfacts_bulk(cache_only=True)


@pytest.mark.parametrize(
    ("field", "value"),
    (("schema_version", 99), ("dataset", "submissions"), ("bytes", 1), ("status", None), ("raw_path", "outside.zip")),
)
def test_invalid_complete_metadata_fails_closed_in_cache_only_mode(tmp_path: Path, field: str, value: object) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload)])
    provider.fetch_companyfacts_bulk()
    metadata_path = tmp_path / "sec_edgar_bulk" / "companyfacts.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata[field] = value
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    provider.transport = lambda _url, _headers: (_ for _ in ()).throw(AssertionError("invalid cache must not fabricate a result"))

    with pytest.raises(SecEdgarBulkUnavailable, match="no cached"):
        provider.fetch_companyfacts_bulk(cache_only=True)


def test_redirected_effective_url_is_rejected(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path, [Response(_zip_bytes(), effective_url="https://mirror.invalid/companyfacts.zip")], max_retries=0)

    with pytest.raises(SecEdgarBulkUnavailable, match="redirect"):
        provider.fetch_companyfacts_bulk()


def test_preexisting_cache_namespace_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable in this environment")
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=alias, transport=lambda _url, _headers: Response(_zip_bytes()), rate_limit_seconds=0)

    with pytest.raises(SecEdgarBulkUnavailable, match="link"):
        provider.fetch_companyfacts_bulk()


def test_incomplete_read_partial_bytes_are_checkpointed(tmp_path: Path) -> None:
    payload = _zip_bytes()

    class Incomplete(Response):
        def read(self, size: int = -1) -> bytes:
            if self.offset:
                raise http.client.IncompleteRead(payload[7:14], len(payload))
            return super().read(size)

    provider, _ = _provider(tmp_path, [Incomplete(payload)], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    partial = tmp_path / "sec_edgar_bulk" / "partials" / "companyfacts.part"
    assert partial.read_bytes() == payload[:14]
    state = json.loads((partial.parent / "companyfacts.json").read_text(encoding="utf-8"))
    assert state["bytes"] == 14
    assert state["prefix_sha256"] == hashlib.sha256(payload[:14]).hexdigest()


def test_slow_network_read_is_outside_publication_scope_and_cancel_stops_publish(tmp_path: Path) -> None:
    payload = _zip_bytes()
    started = threading.Event()
    release = threading.Event()
    publication_active = threading.Event()
    cancelled = threading.Event()

    class Slow(Response):
        def read(self, size: int = -1) -> bytes:
            started.set()
            release.wait(2)
            return super().read(size)

    @contextmanager
    def guard():
        if cancelled.is_set():
            raise WorkflowTransitionError("cancelled")
        publication_active.set()
        try:
            yield
        finally:
            publication_active.clear()

    provider, _ = _provider(tmp_path, [Slow(payload)], max_retries=0)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            provider.fetch_companyfacts_bulk(publish_guard=guard)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(2)
    assert not publication_active.is_set()
    cancelled.set()
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert any(isinstance(error, WorkflowTransitionError) for error in errors)
    assert not list((tmp_path / "sec_edgar_bulk" / "objects" / "companyfacts").glob("*.zip"))


def test_zip_member_capacity_is_checked_before_member_table_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _zip_bytes()
    monkeypatch.setattr("etf_cockpit.data.sec_edgar_bulk.MAX_BULK_MEMBERS", 0)
    provider, _ = _provider(tmp_path, [Response(payload)], max_retries=0)

    with pytest.raises(SecEdgarBulkUnavailable, match="central directory"):
        provider.fetch_companyfacts_bulk()


def test_cancellation_at_durable_boundary_propagates(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload)])

    with pytest.raises(WorkflowTransitionError):
        provider.fetch_companyfacts_bulk(publish_guard=lambda: (_ for _ in ()).throw(WorkflowTransitionError("cancelled")))


def test_concurrent_same_dataset_calls_are_guarded(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload), Response(payload)])
    results: list[object] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(provider.fetch_companyfacts_bulk())
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert errors == []
    assert len(results) == 2


def test_short_206_retains_prefix_until_whole_resource_arrives(tmp_path: Path) -> None:
    prefix = _zip_bytes()
    payload = prefix + prefix
    offset = 7
    provider, calls = _provider(tmp_path, [
        Response(payload[:offset], headers={"ETag": '"stable"', "Content-Length": str(len(payload))}),
        Response(payload[offset:len(prefix)], 206, {"ETag": '"stable"', "Content-Range": f"bytes {offset}-{len(prefix)-1}/{len(payload)}"}),
        Response(payload[len(prefix):], 206, {"ETag": '"stable"', "Content-Range": f"bytes {len(prefix)}-{len(payload)-1}/{len(payload)}"}),
    ], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    with pytest.raises(SecEdgarBulkUnavailable, match="truncated"):
        provider.fetch_companyfacts_bulk()
    root = tmp_path / "sec_edgar_bulk"
    assert not (root / "companyfacts.meta.json").exists()
    assert not list((root / "objects/companyfacts").glob("*.zip"))
    assert (root / "partials/companyfacts.part").read_bytes() == prefix
    complete = provider.fetch_companyfacts_bulk()
    assert calls[-1][1]["Range"] == f"bytes={len(prefix)}-"
    assert complete.path.read_bytes() == payload
    assert json.loads((root / "companyfacts.meta.json").read_text())["bytes"] == len(payload)


def test_incomplete_read_retries_with_verified_exception_prefix(tmp_path: Path) -> None:
    payload = _zip_bytes()

    class Interrupted(Response):
        def read(self, size: int = -1) -> bytes:
            if self.offset:
                raise http.client.IncompleteRead(payload[7:14], len(payload) - 14)
            return super().read(size)

    provider, calls = _provider(tmp_path, [
        Interrupted(payload, headers={"ETag": '"stable"', "Content-Length": str(len(payload))}),
        Response(payload[14:], 206, {"ETag": '"stable"', "Content-Range": f"bytes 14-{len(payload)-1}/{len(payload)}"}),
    ], max_retries=1, sleep=lambda _delay: None)
    result = provider.fetch_companyfacts_bulk()
    assert len(calls) == 2
    assert calls[1][1]["Range"] == "bytes=14-"
    assert result.http_status == 206
    assert result.path.read_bytes() == payload


def test_incomplete_read_exception_cannot_overrun_206_span(tmp_path: Path) -> None:
    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload[:7], headers={"ETag": '"stable"', "Content-Length": str(len(payload))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()

    class Interrupted(Response):
        def read(self, size: int = -1) -> bytes:
            raise http.client.IncompleteRead(payload[7:14], 0)

    provider.transport = lambda _url, _headers: Interrupted(b"", 206, {"ETag": '"stable"', "Content-Range": f"bytes 7-8/{len(payload)}"})
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    assert (tmp_path / "sec_edgar_bulk/partials/companyfacts.part").read_bytes() == payload[:7]


@pytest.mark.parametrize("final_url", [COMPANYFACTS_BULK_URL, "https://mirror.invalid/companyfacts.zip"])
def test_real_http_error_304_preserves_endpoint_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_url: str) -> None:
    provider, _ = _provider(tmp_path, [Response(_zip_bytes(), headers={"ETag": '"stable"'})], max_retries=0)
    original = provider.fetch_companyfacts_bulk()
    provider.transport = None

    def revalidation(_request, **_kwargs):
        raise HTTPError(final_url, 304, "not modified", {}, BytesIO(b""))

    monkeypatch.setattr("etf_cockpit.data.sec_edgar_provider.urlopen", revalidation)
    if final_url != COMPANYFACTS_BULK_URL:
        with pytest.raises(SecEdgarBulkUnavailable, match="redirect"):
            provider.fetch_companyfacts_bulk()
    else:
        cached = provider.fetch_companyfacts_bulk()
        assert cached.http_status == 304
        assert cached.retrieved_at == original.retrieved_at


@pytest.mark.parametrize("payload", [b"x" * (64 * 1024 + 1), b"[" * 2000 + b"0" + b"]" * 2000], ids=["oversized", "deeply-nested"])
def test_metadata_size_and_recursion_fail_closed(tmp_path: Path, payload: bytes) -> None:
    from etf_cockpit.data import sec_edgar_bulk as bulk

    path = tmp_path / "metadata.json"
    path.write_bytes(payload)
    assert bulk._read_json(path) == {}


def test_oversized_partial_rejects_before_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.data import sec_edgar_bulk as bulk

    payload = _zip_bytes()
    provider, _ = _provider(tmp_path, [Response(payload[:7], headers={"ETag": '"stable"', "Content-Length": str(len(payload))})], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    monkeypatch.setattr(bulk, "MAX_BULK_BYTES", 6)
    monkeypatch.setattr(bulk, "_sha256_file", lambda _path: pytest.fail("oversized partial was hashed"))
    assert bulk._partial_state(bulk._paths(tmp_path / "sec_edgar_bulk", "companyfacts"), COMPANYFACTS_BULK_URL, "companyfacts") == {}


def _zip64_bytes(*, misleading_eocd: bool = False, extensible: bytes = b"") -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("CIK0000000001.json", b"{}")
        archive.writestr("CIK0000000002.json", b"{}")
    payload = output.getvalue()
    eocd = bytearray(payload[-22:])
    size, offset = struct.unpack_from("<II", eocd, 12)
    record = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44 + len(extensible), 45, 45, 0, 0, 2, 2, size, offset) + extensible
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, len(payload) - 22, 1)
    if misleading_eocd:
        struct.pack_into("<HHII", eocd, 8, 1, 1, 0, offset)
    return payload[:-22] + record + locator + eocd


def test_valid_adjacent_zip64_without_sentinels_is_supported(tmp_path: Path) -> None:
    payload = _zip64_bytes()
    provider, _ = _provider(tmp_path, [Response(payload)], max_retries=0)
    assert provider.fetch_companyfacts_bulk().path.read_bytes() == payload


def test_variable_length_zip64_extensible_sector_is_supported(tmp_path: Path) -> None:
    payload = _zip64_bytes(extensible=b"PK\x99\x00" + b"x" * 60)
    provider, _ = _provider(tmp_path, [Response(payload)], max_retries=0)
    assert provider.fetch_companyfacts_bulk().path.read_bytes() == payload


@pytest.mark.parametrize("limit", ["MAX_BULK_MEMBERS", "MAX_CENTRAL_DIRECTORY_BYTES"])
def test_actual_adjacent_zip64_is_bounded_before_zipfile_allocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    from etf_cockpit.data import sec_edgar_bulk as bulk

    payload = _zip64_bytes(misleading_eocd=True)
    monkeypatch.setattr(bulk, limit, 1)
    monkeypatch.setattr(bulk.zipfile, "ZipFile", lambda *_args, **_kwargs: pytest.fail("member table allocated before preflight"))
    provider, _ = _provider(tmp_path, [Response(payload)], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable, match="central directory"):
        provider.fetch_companyfacts_bulk()


def test_actual_central_record_count_is_checked_before_allocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.data import sec_edgar_bulk as bulk

    payload = bytearray(_zip64_bytes())
    # The selected ZIP64 declaration lies about the count, but not its size.
    struct.pack_into("<QQ", payload, len(payload) - 98 + 24, 1, 1)
    monkeypatch.setattr(bulk.zipfile, "ZipFile", lambda *_args, **_kwargs: pytest.fail("member table allocated before count validation"))
    provider, _ = _provider(tmp_path, [Response(bytes(payload))], max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable, match="central directory"):
        provider.fetch_companyfacts_bulk()


def test_dataset_policy_has_bounded_historical_submissions_headroom() -> None:
    from etf_cockpit.data import sec_edgar_bulk as bulk

    facts = bulk._dataset_limits("companyfacts")
    submissions = bulk._dataset_limits("submissions")
    assert facts == (8 * 1024**3, 50_000, 32 * 1024**2)
    assert submissions == (8 * 1024**3, 1_000_000, 256 * 1024**2)
    assert submissions[1] > 781_211
