from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from etf_cockpit.data.bulk_cache import (
    ArchiveValidationError,
    BulkCacheError,
    ContentAddressedCache,
    DownloadRequest,
    DownloadResponse,
    safe_extract_archive,
)


def test_local_source_is_content_addressed_deduplicated_and_invalidates_changed_versions(tmp_path: Path) -> None:
    source = tmp_path / "official.csv"
    source.write_bytes(b"version-one\n")
    cache = ContentAddressedCache(tmp_path)

    first = cache.store_local_file("official-bulk", source, licence="official")
    second = cache.store_local_file("official-bulk", source, licence="official")
    assert first.manifest.content_sha256 == second.manifest.content_sha256
    assert second.deduplicated is True
    assert second.manifest.version == 2

    source.write_bytes(b"version-two\n")
    changed = cache.store_local_file("official-bulk", source, licence="official")
    assert changed.manifest.version == 3
    assert changed.manifest.previous_sha256 == first.manifest.content_sha256
    invalidations = (cache.manifests / "invalidations.jsonl").read_text(encoding="utf-8")
    assert first.manifest.content_sha256 in invalidations
    assert changed.manifest.content_sha256 in invalidations


def test_interrupted_download_resumes_from_part_without_promoting_partial_bytes(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    request = DownloadRequest("resumable", "https://example.test/file", expected_size=6, allowlisted_hosts=("example.test",))
    calls: list[int] = []

    class InterruptedBody:
        def __iter__(self):
            yield b"abc"
            raise OSError("fixture interruption")

    def fetcher(_request: DownloadRequest, offset: int) -> DownloadResponse:
        calls.append(offset)
        if offset == 0:
            return DownloadResponse(200, InterruptedBody())
        return DownloadResponse(206, [b"def"], total_size=3)

    with pytest.raises(OSError, match="fixture interruption"):
        cache.download(request, fetcher=fetcher)
    assert cache._part_path("resumable").read_bytes() == b"abc"

    result = cache.download(request, fetcher=fetcher)
    assert result.resumed is True
    assert calls == [0, 3]
    assert Path(tmp_path / result.manifest.object_path).read_bytes() == b"abcdef"
    assert not cache._part_path("resumable").exists()


def test_checksum_mismatch_keeps_part_and_never_publishes_object(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    request = DownloadRequest("bad-checksum", "https://example.test/file", expected_sha256="0" * 64, allowlisted_hosts=("example.test",))

    with pytest.raises(BulkCacheError, match="checksum mismatch"):
        cache.download(request, fetcher=lambda _request, _offset: DownloadResponse(200, [b"unsafe"]))
    assert cache._part_path("bad-checksum").is_file()
    assert not list(cache.objects.rglob("*"))
    assert not (cache.manifests / "bad-checksum.json").exists()


def test_generation_validation_and_promotion_are_atomic(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    with pytest.raises(BulkCacheError, match="generation validation failed"):
        cache.stage_generation("prices", b"broken", source_sha256="1" * 64, validator=lambda _payload: (_ for _ in ()).throw(ValueError("bad rows")))
    assert not list((cache.staging / "generations").rglob("*.bin"))

    staged = cache.stage_generation("prices", b"valid", source_sha256="1" * 64, validator=lambda payload: None)
    assert staged.status == "staged"
    assert list((cache.generations / "prices").glob("*.bin")) == []
    promoted = cache.promote_generation(staged)
    assert promoted.status == "promoted"
    assert (tmp_path / promoted.relative_path).read_bytes() == b"valid"
    with pytest.raises(BulkCacheError, match="existing staged"):
        cache.promote_generation(staged)


def test_archive_extraction_rejects_traversal_and_compression_bombs(tmp_path: Path) -> None:
    safe_archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(safe_archive, "w") as package:
        package.writestr("nested/value.txt", "ok")
    extracted = safe_extract_archive(safe_archive, tmp_path / "safe")
    assert (tmp_path / "safe/nested/value.txt").read_text(encoding="utf-8") == "ok"
    assert len(extracted) == 1

    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as package:
        package.writestr("../outside.txt", "blocked")
    with pytest.raises(ArchiveValidationError, match="escapes destination"):
        safe_extract_archive(traversal, tmp_path / "unsafe")
    assert not (tmp_path / "outside.txt").exists()

    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("large.txt", "A" * 20_000)
    with pytest.raises(ArchiveValidationError, match="safety limits"):
        safe_extract_archive(bomb, tmp_path / "bomb", max_compression_ratio=2)


def test_health_report_is_local_only_and_reports_staged_state(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    report = cache.health()
    assert report["schema_version"] == "bulk-cache.v1"
    assert report["status"] == "passed"
    assert report["network_calls"] is False
    cache.stage_generation("prices", b"valid", source_sha256="1" * 64)
    assert cache.health()["staged_file_count"] == 1


def test_network_download_requires_explicit_https_allowlist(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    request = DownloadRequest("not-allowed", "http://example.test/file", allowlisted_hosts=("example.test",))
    with pytest.raises(BulkCacheError, match="HTTPS URL and an explicit allow-listed host"):
        cache.download(request)
