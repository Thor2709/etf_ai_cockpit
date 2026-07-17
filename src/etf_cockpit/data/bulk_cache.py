"""Local-first bulk source cache and safe staged-generation primitives.

The cache is deliberately transport-agnostic.  Callers may inject a bounded
HTTP response reader for opt-in network use, while local files and replay
fixtures use the same content-addressed and promotion path without network
access.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import tarfile
from typing import Any
from urllib.parse import urlparse
import urllib.error
import urllib.request
import zipfile

from etf_cockpit.core.atomic_io import atomic_write_bytes


BULK_CACHE_SCHEMA_VERSION = "bulk-cache.v1"
DEFAULT_CACHE_RELATIVE_PATH = Path("data/raw/bulk_cache")
DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_MEMBERS = 50_000
DEFAULT_MAX_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 200.0
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class BulkCacheError(RuntimeError):
    """Base class for cache, transport and promotion failures."""


class ArchiveValidationError(BulkCacheError):
    """Raised when an archive is unsafe or exceeds configured limits."""


@dataclass(frozen=True)
class DownloadRequest:
    source_id: str
    url: str
    expected_sha256: str | None = None
    expected_size: int | None = None
    expected_content_type: str | None = None
    allowlisted_hosts: tuple[str, ...] = ()
    licence: str = "unspecified"
    fair_use_note: str = ""
    update_schedule: str = ""
    max_bytes: int = DEFAULT_MAX_BYTES
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class DownloadResponse:
    status_code: int
    body: Iterable[bytes]
    total_size: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class CacheManifest:
    schema_version: str
    source_id: str
    source_url: str
    content_sha256: str
    size_bytes: int
    object_path: str
    retrieved_at: str
    version: int
    etag: str | None
    last_modified: str | None
    licence: str
    fair_use_note: str
    update_schedule: str
    previous_sha256: str | None = None


@dataclass(frozen=True)
class DownloadResult:
    manifest: CacheManifest
    resumed: bool
    deduplicated: bool


@dataclass(frozen=True)
class GenerationRecord:
    dataset_id: str
    generation_id: str
    source_sha256: str
    relative_path: str
    status: str
    validated_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_name(value: str, label: str) -> str:
    cleaned = _SAFE_NAME.sub("_", str(value).strip()).strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise BulkCacheError(f"{label} must contain a safe name")
    return cleaned[:160]


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = str(value).strip().lower()
    if len(normalised) != 64 or any(char not in "0123456789abcdef" for char in normalised):
        raise BulkCacheError("expected_sha256 must be a 64-character hexadecimal digest")
    return normalised


def _validate_url(url: str, allowlisted_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {str(item).strip().lower().rstrip(".") for item in allowlisted_hosts if str(item).strip()}
    if parsed.scheme != "https" or not host or not allowed or host not in allowed:
        raise BulkCacheError("network downloads require an HTTPS URL and an explicit allow-listed host")


def _http_fetch(request: DownloadRequest, offset: int) -> DownloadResponse:
    _validate_url(request.url, request.allowlisted_hosts)
    headers = {"Accept": "application/octet-stream"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    try:
        response = urllib.request.urlopen(urllib.request.Request(request.url, headers=headers), timeout=request.timeout_seconds)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise BulkCacheError(f"bulk download failed for {request.source_id}: {type(exc).__name__}") from exc

    def body() -> Iterator[bytes]:
        try:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    return
                yield chunk
        finally:
            response.close()

    content_type = response.headers.get("Content-Type")
    return DownloadResponse(
        status_code=int(getattr(response, "status", 200)),
        body=body(),
        total_size=int(response.headers["Content-Length"]) if response.headers.get("Content-Length", "").isdigit() else None,
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
        content_type=content_type.split(";", 1)[0].strip().lower() if content_type else None,
    )


class ContentAddressedCache:
    """Store immutable raw objects and atomically promote validated generations."""

    def __init__(self, root: Path, *, relative_path: Path = DEFAULT_CACHE_RELATIVE_PATH) -> None:
        self.root = Path(root).resolve()
        self.base = (self.root / relative_path).resolve()
        if not self.base.is_relative_to(self.root):
            raise BulkCacheError("cache path must remain inside the application root")
        self.objects = self.base / "objects" / "sha256"
        self.manifests = self.base / "manifests"
        self.staging = self.base / "staging"
        self.generations = self.base / "generations"

    def _prepare(self) -> None:
        for path in (self.objects, self.manifests, self.staging, self.generations):
            path.mkdir(parents=True, exist_ok=True)

    def _part_path(self, source_id: str) -> Path:
        return self.staging / "downloads" / f"{_safe_name(source_id, 'source_id')}.part"

    def _manifest_path(self, source_id: str) -> Path:
        return self.manifests / f"{_safe_name(source_id, 'source_id')}.json"

    def _object_path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest

    def _read_manifest(self, source_id: str) -> dict[str, Any] | None:
        path = self._manifest_path(source_id)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BulkCacheError(f"cache manifest is unreadable: {path}") from exc
        return value if isinstance(value, dict) else None

    def store_local_file(
        self,
        source_id: str,
        path: Path,
        *,
        licence: str = "unspecified",
        fair_use_note: str = "",
        update_schedule: str = "",
        expected_sha256: str | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> DownloadResult:
        source = Path(path).resolve()
        if not source.is_file():
            raise BulkCacheError(f"local bulk source does not exist: {source}")
        expected = _validate_sha256(expected_sha256)
        size = source.stat().st_size
        if size > max_bytes:
            raise BulkCacheError(f"bulk source exceeds max_bytes={max_bytes}")
        with source.open("rb") as handle:
            response = DownloadResponse(200, iter(lambda: handle.read(1024 * 1024), b""), total_size=size)
            return self._consume(
                DownloadRequest(
                    source_id=source_id,
                    url=f"file://{source}",
                    expected_sha256=expected,
                    expected_size=size,
                    licence=licence,
                    fair_use_note=fair_use_note,
                    update_schedule=update_schedule,
                    max_bytes=max_bytes,
                ),
                response,
                offset=0,
                resumed=False,
            )

    def download(
        self,
        request: DownloadRequest,
        *,
        fetcher: Callable[[DownloadRequest, int], DownloadResponse] | None = None,
    ) -> DownloadResult:
        """Download into a resumable part file and publish only verified bytes."""

        if request.max_bytes <= 0 or (request.expected_size is not None and request.expected_size < 0):
            raise BulkCacheError("download size limits must be positive")
        expected = _validate_sha256(request.expected_sha256)
        if expected != request.expected_sha256:
            request = DownloadRequest(**{**request.__dict__, "expected_sha256": expected})
        self._prepare()
        part = self._part_path(request.source_id)
        part.parent.mkdir(parents=True, exist_ok=True)
        offset = part.stat().st_size if part.is_file() else 0
        response = (fetcher or _http_fetch)(request, offset)
        resumed = offset > 0 and response.status_code == 206
        if offset and not resumed:
            part.unlink(missing_ok=True)
            offset = 0
        if response.status_code not in {200, 206}:
            raise BulkCacheError(f"bulk source returned unsupported status {response.status_code}")
        if request.expected_content_type and response.content_type:
            expected_type = request.expected_content_type.split(";", 1)[0].strip().lower()
            if response.content_type.lower() != expected_type:
                raise BulkCacheError(f"unexpected content type for {request.source_id}: {response.content_type}")
        return self._consume(request, response, offset=offset, resumed=resumed)

    def _consume(
        self,
        request: DownloadRequest,
        response: DownloadResponse,
        *,
        offset: int,
        resumed: bool,
    ) -> DownloadResult:
        part = self._part_path(request.source_id)
        part.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if offset else "wb"
        written = offset
        try:
            with part.open(mode) as handle:
                for chunk in response.body:
                    if not isinstance(chunk, bytes):
                        raise BulkCacheError("bulk transport yielded a non-bytes chunk")
                    written += len(chunk)
                    if written > request.max_bytes:
                        raise BulkCacheError(f"bulk source exceeds max_bytes={request.max_bytes}")
                    handle.write(chunk)
                handle.flush()
        except Exception:
            # The part is intentionally retained for a caller-controlled retry.
            raise
        if request.expected_size is not None and written != request.expected_size:
            raise BulkCacheError(f"bulk source size mismatch: expected {request.expected_size}, got {written}")
        digest = _sha256_file(part)
        if request.expected_sha256 and digest != request.expected_sha256:
            raise BulkCacheError(f"bulk source checksum mismatch: expected {request.expected_sha256}, got {digest}")
        return self._publish(request, part, digest, written, response, resumed)

    def _publish(
        self,
        request: DownloadRequest,
        part: Path,
        digest: str,
        size: int,
        response: DownloadResponse,
        resumed: bool,
    ) -> DownloadResult:
        self._prepare()
        object_path = self._object_path(digest)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        deduplicated = object_path.is_file()
        if deduplicated:
            part.unlink(missing_ok=True)
        else:
            part.replace(object_path)
        previous = self._read_manifest(request.source_id)
        previous_digest = str(previous.get("content_sha256")) if previous else None
        version = int(previous.get("version", 0)) + 1 if previous else 1
        manifest = CacheManifest(
            schema_version=BULK_CACHE_SCHEMA_VERSION,
            source_id=_safe_name(request.source_id, "source_id"),
            source_url=request.url,
            content_sha256=digest,
            size_bytes=size,
            object_path=str(object_path.relative_to(self.root)).replace("\\", "/"),
            retrieved_at=_utc_now(),
            version=version,
            etag=response.etag,
            last_modified=response.last_modified,
            licence=request.licence,
            fair_use_note=request.fair_use_note,
            update_schedule=request.update_schedule,
            previous_sha256=previous_digest if previous_digest and previous_digest != digest else None,
        )
        atomic_write_bytes(self._manifest_path(request.source_id), _json_bytes(manifest.__dict__), lambda _path: None)
        if previous_digest and previous_digest != digest:
            self._append_invalidation(request.source_id, previous_digest, digest)
        return DownloadResult(manifest, resumed, deduplicated)

    def _append_invalidation(self, source_id: str, previous: str, current: str) -> None:
        path = self.manifests / "invalidations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"schema_version": BULK_CACHE_SCHEMA_VERSION, "source_id": source_id, "previous_sha256": previous, "current_sha256": current, "occurred_at": _utc_now()}, sort_keys=True) + "\n")

    def stage_generation(
        self,
        dataset_id: str,
        payload: bytes,
        *,
        source_sha256: str,
        validator: Callable[[bytes], None] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> GenerationRecord:
        if not isinstance(payload, bytes) or not payload:
            raise BulkCacheError("a non-empty bytes payload is required for staging")
        source_digest = _validate_sha256(source_sha256)
        assert source_digest is not None
        if validator is not None:
            try:
                validator(payload)
            except Exception as exc:
                raise BulkCacheError(f"generation validation failed: {type(exc).__name__}: {exc}") from exc
        dataset = _safe_name(dataset_id, "dataset_id")
        generation_id = f"gen_{hashlib.sha256(payload).hexdigest()[:24]}"
        path = self.staging / "generations" / dataset / f"{generation_id}.bin"
        atomic_write_bytes(path, payload, lambda _path: None)
        if metadata:
            atomic_write_bytes(path.with_suffix(".json"), _json_bytes(dict(metadata)), lambda _path: None)
        return GenerationRecord(dataset, generation_id, source_digest, str(path.relative_to(self.root)).replace("\\", "/"), "staged", _utc_now())

    def promote_generation(self, record: GenerationRecord) -> GenerationRecord:
        staged = (self.root / record.relative_path).resolve()
        if not staged.is_file() or not staged.is_relative_to(self.staging):
            raise BulkCacheError("only an existing staged generation may be promoted")
        dataset = _safe_name(record.dataset_id, "dataset_id")
        destination = self.generations / dataset / f"{record.generation_id}.bin"
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged.replace(destination)
        promoted = GenerationRecord(dataset, record.generation_id, record.source_sha256, str(destination.relative_to(self.root)).replace("\\", "/"), "promoted", _utc_now())
        atomic_write_bytes(destination.with_suffix(".json"), _json_bytes(promoted.__dict__), lambda _path: None)
        return promoted

    def health(self) -> dict[str, object]:
        manifests = sorted(self.manifests.glob("*.json")) if self.manifests.is_dir() else []
        rows: list[dict[str, object]] = []
        failures: list[str] = []
        for path in manifests:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and payload.get("schema_version") == BULK_CACHE_SCHEMA_VERSION:
                    rows.append(payload)
            except (OSError, json.JSONDecodeError):
                failures.append(path.name)
        staged = sum(1 for path in self.staging.rglob("*") if path.is_file()) if self.staging.is_dir() else 0
        promoted = sum(1 for path in self.generations.rglob("*.bin")) if self.generations.is_dir() else 0
        return {"schema_version": BULK_CACHE_SCHEMA_VERSION, "status": "failed" if failures else "passed", "network_calls": False, "object_count": sum(1 for path in self.objects.rglob("*") if path.is_file()) if self.objects.is_dir() else 0, "manifest_count": len(rows), "staged_file_count": staged, "promoted_generation_count": promoted, "latest": rows[-10:], "failures": failures, "cache_path": str(self.base.relative_to(self.root)).replace("\\", "/")}


def bulk_cache_health(root: Path) -> dict[str, object]:
    return ContentAddressedCache(root).health()


def safe_extract_archive(
    archive: Path,
    destination: Path,
    *,
    max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
    max_total_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
) -> tuple[Path, ...]:
    """Extract ZIP/TAR archives after complete traversal and size validation."""

    source = Path(archive).resolve()
    target = Path(destination).resolve()
    if not source.is_file():
        raise ArchiveValidationError(f"archive does not exist: {source}")
    target.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as package:
            members = package.infolist()
            _validate_archive_members(members, target, max_members, max_total_bytes, max_compression_ratio, zip_mode=True)
            return _extract_zip(package, members, target)
    try:
        is_tar = tarfile.is_tarfile(source)
    except (OSError, tarfile.TarError):
        is_tar = False
    if is_tar:
        with tarfile.open(source, mode="r:*") as package:
            members = package.getmembers()
            _validate_archive_members(members, target, max_members, max_total_bytes, max_compression_ratio, zip_mode=False)
            return _extract_tar(package, members, target)
    raise ArchiveValidationError("only ZIP and TAR archives are supported")


def _safe_member_path(name: str, target: Path) -> Path:
    candidate = (target / name).resolve()
    if not candidate.is_relative_to(target) or Path(name).is_absolute():
        raise ArchiveValidationError(f"archive member escapes destination: {name}")
    return candidate


def _validate_archive_members(members: Iterable[object], target: Path, max_members: int, max_total_bytes: int, max_ratio: float, *, zip_mode: bool) -> None:
    values = tuple(members)
    if len(values) > max_members:
        raise ArchiveValidationError(f"archive contains too many members: {len(values)}")
    total = 0
    for member in values:
        name = str(getattr(member, "filename", getattr(member, "name", "")))
        _safe_member_path(name, target)
        is_dir = bool(getattr(member, "is_dir", lambda: False)())
        if not zip_mode and (getattr(member, "issym", lambda: False)() or getattr(member, "islnk", lambda: False)()):
            raise ArchiveValidationError(f"archive links are not allowed: {name}")
        if zip_mode and stat.S_ISLNK((int(getattr(member, "external_attr", 0)) >> 16) & 0xFFFF):
            raise ArchiveValidationError(f"archive links are not allowed: {name}")
        size = 0 if is_dir else int(getattr(member, "file_size", getattr(member, "size", 0)))
        compressed = int(getattr(member, "compress_size", 0))
        if size < 0 or size > max_total_bytes or (compressed > 0 and size / compressed > max_ratio):
            raise ArchiveValidationError(f"archive member exceeds safety limits: {name}")
        total += size
        if total > max_total_bytes:
            raise ArchiveValidationError("archive expands beyond the configured byte limit")


def _extract_zip(package: zipfile.ZipFile, members: Iterable[zipfile.ZipInfo], target: Path) -> tuple[Path, ...]:
    extracted: list[Path] = []
    for member in members:
        destination = _safe_member_path(member.filename, target)
        if member.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with package.open(member) as source, destination.open("wb") as handle:
            shutil.copyfileobj(source, handle, length=1024 * 1024)
        extracted.append(destination)
    return tuple(extracted)


def _extract_tar(package: tarfile.TarFile, members: Iterable[tarfile.TarInfo], target: Path) -> tuple[Path, ...]:
    extracted: list[Path] = []
    for member in members:
        destination = _safe_member_path(member.name, target)
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        source = package.extractfile(member)
        if source is None:
            raise ArchiveValidationError(f"archive member cannot be read: {member.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source, destination.open("wb") as handle:
            shutil.copyfileobj(source, handle, length=1024 * 1024)
        extracted.append(destination)
    return tuple(extracted)


__all__ = [
    "ArchiveValidationError",
    "BULK_CACHE_SCHEMA_VERSION",
    "BulkCacheError",
    "CacheManifest",
    "ContentAddressedCache",
    "DEFAULT_CACHE_RELATIVE_PATH",
    "DownloadRequest",
    "DownloadResponse",
    "DownloadResult",
    "GenerationRecord",
    "bulk_cache_health",
    "safe_extract_archive",
]
