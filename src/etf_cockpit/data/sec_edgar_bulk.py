"""Bounded, explicit acquisition of SEC's nightly bulk ZIP archives.

This module deliberately does not parse or publish filing facts.  It owns only
streaming transport, validator-bound resumption, immutable raw bytes, and
honest acquisition provenance.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
from typing import Any, Iterator
import uuid
import zipfile

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.workflow import PublicationScopeFactory, WorkflowTransitionError, publication_scope
from etf_cockpit.parsers.contracts import RawDocument


COMPANYFACTS_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
MAX_BULK_BYTES = 2 * 1024 * 1024 * 1024
# The SEC has historically published more than 780,000 submissions JSON
# members.  Keep a bounded ceiling with headroom for that known shape while
# rejecting pathological central directories before ZipInfo allocation.
MAX_BULK_MEMBERS = 1_000_000
MAX_CENTRAL_DIRECTORY_BYTES = 256 * 1024 * 1024
MAX_BULK_COMPRESSION_RATIO = 200.0
_CHUNK_BYTES = 1024 * 1024
_EOCD_SCAN_BYTES = 8 * 1024 * 1024
_PARTIAL_SCHEMA_VERSION = 2


class SecEdgarBulkError(RuntimeError):
    """Base class for controlled bulk acquisition failures."""


class SecEdgarBulkUnavailable(SecEdgarBulkError):
    """Transport, quota, truncation, or validation failure."""


class SecEdgarBulkResumeError(SecEdgarBulkUnavailable):
    """A resumed response cannot be proven to continue the stored bytes."""


class SecEdgarBulkEndpointError(SecEdgarBulkUnavailable):
    """The response cannot be attributed to the requested SEC endpoint."""


def fetch_bulk(provider: Any, dataset: str, *, publish_guard: PublicationScopeFactory | None = None, cache_only: bool = False) -> RawDocument:
    if dataset not in {"companyfacts", "submissions"}:
        raise ValueError("SEC bulk dataset must be companyfacts or submissions")
    url = COMPANYFACTS_BULK_URL if dataset == "companyfacts" else SUBMISSIONS_BULK_URL
    root = Path(provider.cache_dir) / "sec_edgar_bulk"
    _validate_root(root)
    paths = _paths(root, dataset)
    if cache_only:
        # Cache-only reads use immutable objects and validated metadata; they
        # do not need to wait behind a multi-gigabyte network acquisition or
        # create synchronization files as a side effect.
        if not root.is_dir():
            raise SecEdgarBulkUnavailable(f"no cached SEC {dataset} bulk artifact is available")
        _validate_namespace(root, root.parent)
        return _cached_result(_read_json(paths["metadata"]), paths, url, dataset)
    # Directory and persistent-lock creation are durable namespace changes too;
    # keep them inside the caller's publication authorization boundary.
    with publication_scope(publish_guard):
        _prepare_paths(paths, root)
    with _guard(paths["lock"]):
        metadata = _read_json(paths["metadata"])
        return _acquire(provider, dataset, url, paths, metadata, publish_guard)


def _acquire(provider: Any, dataset: str, url: str, paths: dict[str, Path], metadata: dict[str, object], publish_guard: PublicationScopeFactory | None) -> RawDocument:
    headers = {"User-Agent": provider.user_agent, "Accept": "application/zip"}
    artifact = _metadata_artifact(metadata, paths, url)
    if artifact is not None:
        if metadata.get("etag"):
            headers["If-None-Match"] = str(metadata["etag"])
        if metadata.get("last_modified"):
            headers["If-Modified-Since"] = str(metadata["last_modified"])

    partial = _partial_state(paths, url, dataset)
    resume_offset = _int_value(partial.get("bytes"), 0) if partial else 0
    if partial and partial.get("total") is not None and resume_offset >= _int_value(partial.get("total"), 0):
        # A complete-but-invalid response (for example a bad ZIP) cannot be
        # resumed at EOF.  Let the next 200 response replace it safely.
        resume_offset = 0
    resume_validator = _strong_validator(partial.get("validator")) if partial else None
    if resume_offset and resume_validator and paths["part"].is_file():
        headers["Range"] = f"bytes={resume_offset}-"
        headers["If-Range"] = resume_validator
    else:
        resume_offset = 0
        resume_validator = None

    last_error: Exception | None = None
    for attempt in range(int(provider.max_retries) + 1):
        try:
            provider._respect_rate_limit()
            raw_response = provider._request_bulk_stream(url, headers)
            response = _response(raw_response)
            try:
                if response.effective_url is not None and response.effective_url != url:
                    raise SecEdgarBulkEndpointError("SEC bulk response followed an unexpected redirect")
                if response.status == 304:
                    if artifact is None:
                        raise SecEdgarBulkUnavailable("SEC returned 304 without a cached artifact")
                    return _result(artifact, url, metadata, 304, dataset)
                if response.status in {429} or response.status >= 500:
                    raise SecEdgarBulkUnavailable(f"SEC endpoint returned HTTP {response.status}")
                total: int | None
                if response.status == 206:
                    if not resume_validator or resume_offset <= 0:
                        raise SecEdgarBulkResumeError("SEC returned 206 without a validator-bound partial")
                    expected_total = partial.get("total") if partial else None
                    if isinstance(expected_total, bool) or not isinstance(expected_total, int) or expected_total <= 0:
                        expected_total = None
                    total, response_length = _validate_partial_response(
                        response.headers, resume_offset, resume_validator, expected_total=expected_total
                    )
                    _stream_response(
                        response.stream, paths, publish_guard, resume_offset, total,
                        response.headers, url, dataset, append=True, generation=str(partial["generation"]),
                        expected_length=response_length, prefix_sha256=str(partial["prefix_sha256"]),
                    )
                elif response.status == 200:
                    total = _validated_content_length(response.headers)
                    _stream_response(
                        response.stream, paths, publish_guard, 0, total,
                        response.headers, url, dataset, append=False, generation=None,
                        expected_length=total, prefix_sha256=None,
                    )
                elif response.status < 200 or response.status >= 300:
                    raise SecEdgarBulkUnavailable(f"SEC endpoint returned HTTP {response.status}")
                else:
                    raise SecEdgarBulkUnavailable(f"SEC endpoint returned unsupported HTTP {response.status}")
            finally:
                response.close()
            payload_sha = _sha256_file(paths["part"])
            _validate_zip(paths["part"])
            final = paths["objects"] / f"{payload_sha}.zip"
            _publish_artifact(paths["part"], final, paths["part_meta"], publish_guard, paths["objects"])
            acquired_at = datetime.now(timezone.utc)
            response_etag = _strong_validator(_header(response.headers, "etag")) or ""
            next_metadata = {
                "schema_version": 2,
                "dataset": dataset,
                "source_url": url,
                "retrieved_at": acquired_at.isoformat(),
                "sha256": payload_sha,
                "raw_path": str(final),
                "status": response.status,
                "etag": response_etag,
                "last_modified": _header(response.headers, "last-modified"),
                "complete": True,
                "bytes": final.stat().st_size,
            }
            with publication_scope(publish_guard):
                atomic_write_json(paths["metadata"], next_metadata)
            return RawDocument(final, url, acquired_at, payload_sha, "sec_edgar", f"sec_{dataset}_bulk", "application/zip", response.status)
        except WorkflowTransitionError:
            raise
        except SecEdgarBulkEndpointError:
            raise
        except SecEdgarBulkResumeError:
            # A mismatched continuation must never be retried into a splice.
            raise
        except SecEdgarBulkUnavailable as exc:
            last_error = exc
            if attempt >= int(provider.max_retries):
                raise
            provider._sleep(min(2.0, 0.25 * (2**attempt)))
        except (OSError, IOError, TimeoutError, ValueError, TypeError, zipfile.BadZipFile) as exc:
            last_error = exc
            if attempt >= int(provider.max_retries):
                raise SecEdgarBulkUnavailable(f"SEC bulk acquisition failed after {attempt + 1} attempt(s)") from exc
            provider._sleep(min(2.0, 0.25 * (2**attempt)))
        except Exception as exc:
            raise SecEdgarBulkUnavailable(f"SEC bulk acquisition failed: {type(exc).__name__}") from exc
        if paths["part"].is_file():
            partial = _partial_state(paths, url, dataset)
            resume_offset = _int_value(partial.get("bytes"), 0) if partial else 0
            if partial and partial.get("total") is not None and resume_offset >= _int_value(partial.get("total"), 0):
                resume_offset = 0
            resume_validator = _strong_validator(partial.get("validator")) if partial else None
            headers.pop("If-None-Match", None)
            headers.pop("If-Modified-Since", None)
            if resume_offset and resume_validator:
                headers["Range"] = f"bytes={resume_offset}-"
                headers["If-Range"] = resume_validator
            else:
                headers.pop("Range", None)
                headers.pop("If-Range", None)
    raise SecEdgarBulkUnavailable("SEC bulk acquisition failed") from last_error


def _stream_response(
    stream: Any,
    paths: dict[str, Path],
    publish_guard: PublicationScopeFactory | None,
    offset: int,
    total: int | None,
    headers: dict[str, str],
    source_url: str,
    dataset: str,
    *,
    append: bool,
    generation: str | None,
    expected_length: int | None,
    prefix_sha256: str | None,
) -> None:
    """Read network bytes without the publication lock and checkpoint each write."""

    validator = _strong_validator(_header(headers, "etag"))
    if append and validator is None:
        raise SecEdgarBulkResumeError("resumed response does not repeat a strong ETag")
    if expected_length is not None and expected_length < 0:
        raise SecEdgarBulkUnavailable("SEC bulk response length is invalid")

    if append:
        if generation is None:
            raise SecEdgarBulkResumeError("resumed partial is missing its generation")
        if prefix_sha256 is None or not paths["part"].is_file() or paths["part"].stat().st_size != offset or _sha256_file(paths["part"]) != prefix_sha256:
            raise SecEdgarBulkResumeError("resumed partial prefix changed before append")
        streamed = offset
        digest = hashlib.sha256()
        with paths["part"].open("rb") as existing:
            for existing_chunk in iter(lambda: existing.read(_CHUNK_BYTES), b""):
                digest.update(existing_chunk)
    else:
        generation = uuid.uuid4().hex
        streamed = 0
        # Invalidate the previous generation before truncating its bytes.  If
        # authorization or metadata publication fails, no stale proof can
        # authorize a later append.
        with publication_scope(publish_guard):
            _start_generation(paths, dataset, source_url, total, validator, generation)
        digest = hashlib.sha256()

    received = 0
    while True:
        try:
            # Network I/O intentionally occurs outside publication_scope so a
            # cancellation request is not blocked by a slow SEC response.
            chunk = stream.read(_CHUNK_BYTES)
        except BaseException as exc:
            # http.client.IncompleteRead exposes bytes received before the
            # interruption.  Preserve those bytes only when they fit the
            # same generation and declared bounds.
            exception_partial = getattr(exc, "partial", None)
            if isinstance(exception_partial, (bytes, bytearray)) and exception_partial:
                candidate = bytes(exception_partial)
                if streamed + len(candidate) <= MAX_BULK_BYTES and (total is None or streamed + len(candidate) <= total):
                    with publication_scope(publish_guard):
                        _append_chunk(paths, candidate)
                        streamed += len(candidate)
                        digest.update(candidate)
            _checkpoint_partial(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest(), publish_guard)
            raise
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            _checkpoint_partial(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest(), publish_guard)
            raise TypeError("SEC bulk response returned a non-bytes chunk")
        chunk_bytes = bytes(chunk)
        next_size = streamed + len(chunk_bytes)
        if next_size > MAX_BULK_BYTES or (total is not None and next_size > total):
            _checkpoint_partial(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest(), publish_guard)
            raise SecEdgarBulkUnavailable("SEC bulk response exceeds its bounded byte limit")
        if expected_length is not None and received + len(chunk_bytes) > expected_length:
            _checkpoint_partial(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest(), publish_guard)
            raise SecEdgarBulkResumeError("SEC bulk response body exceeds Content-Length") if append else SecEdgarBulkUnavailable("SEC bulk response body exceeds Content-Length")
        try:
            with publication_scope(publish_guard):
                _append_chunk(paths, chunk_bytes)
                streamed = next_size
                received += len(chunk_bytes)
                digest.update(chunk_bytes)
                _checkpoint_partial_file(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest())
        except BaseException:
            # If the write itself partially succeeded, checkpoint the actual
            # on-disk prefix; a size/hash mismatch makes it non-resumable.
            actual = paths["part"].stat().st_size if paths["part"].is_file() else 0
            actual_sha = _sha256_file(paths["part"]) if actual else _EMPTY_SHA256
            with publication_scope(publish_guard):
                _write_partial_file(paths, dataset, source_url, actual, total, validator, generation, actual_sha)
            raise

    if expected_length is not None and received != expected_length:
        with publication_scope(publish_guard):
            _checkpoint_partial_file(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest())
        raise SecEdgarBulkUnavailable("SEC bulk response was truncated")
    with publication_scope(publish_guard):
        _checkpoint_partial_file(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest())


_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _start_generation(paths: dict[str, Path], dataset: str, source_url: str, total: int | None, validator: str | None, generation: str) -> None:
    _validate_namespace(paths["part"], paths["root"])
    paths["part_meta"].unlink(missing_ok=True)
    descriptor = os.open(
        paths["part"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "wb") as target:
        target.flush()
        os.fsync(target.fileno())
    _write_partial_file(paths, dataset, source_url, 0, total, validator, generation, _EMPTY_SHA256)


def _append_chunk(paths: dict[str, Path], chunk: bytes) -> None:
    _validate_namespace(paths["part"], paths["root"])
    if paths["part"].is_symlink() or _is_reparse(paths["part"]):
        raise SecEdgarBulkUnavailable("SEC bulk partial destination is a link")
    descriptor = os.open(
        paths["part"], os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "wb") as target:
        target.write(chunk)
        target.flush()
        os.fsync(target.fileno())


def _checkpoint_partial(paths: dict[str, Path], dataset: str, source_url: str, streamed: int, total: int | None, validator: str | None, generation: str, prefix_sha256: str, publish_guard: PublicationScopeFactory | None) -> None:
    actual = paths["part"].stat().st_size if paths["part"].is_file() else 0
    with publication_scope(publish_guard):
        _write_partial_file(paths, dataset, source_url, actual, total, validator, generation, prefix_sha256)


def _checkpoint_partial_file(paths: dict[str, Path], dataset: str, source_url: str, streamed: int, total: int | None, validator: str | None, generation: str, prefix_sha256: str) -> None:
    actual = paths["part"].stat().st_size if paths["part"].is_file() else 0
    _write_partial_file(paths, dataset, source_url, actual, total, validator, generation, prefix_sha256)


def _validate_partial_response(headers: dict[str, str], offset: int, validator: str, *, expected_total: int | None = None) -> tuple[int, int]:
    content_range = _header(headers, "content-range")
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range.strip())
    if match is None or int(match.group(1)) != offset or int(match.group(2)) < offset or int(match.group(3)) <= int(match.group(2)):
        raise SecEdgarBulkResumeError("SEC 206 Content-Range does not exactly match the partial offset")
    total = int(match.group(3))
    response_length = int(match.group(2)) - offset + 1
    if expected_total is not None and int(match.group(3)) != expected_total:
        raise SecEdgarBulkResumeError("SEC 206 Content-Range total does not match the partial artifact")
    content_length = _header(headers, "content-length")
    if content_length and (not content_length.isdigit() or int(content_length) != response_length):
        raise SecEdgarBulkResumeError("SEC 206 Content-Length does not match Content-Range")
    response_validator = _strong_validator(_header(headers, "etag"))
    if response_validator != validator:
        raise SecEdgarBulkResumeError("SEC 206 validator does not match the partial artifact")
    return total, response_length


def _publish_artifact(part: Path, final: Path, part_meta: Path, publish_guard: PublicationScopeFactory | None, objects: Path) -> None:
    with publication_scope(publish_guard):
        _validate_namespace(final, objects.parent.parent)
        _validate_namespace(part, objects.parent.parent)
        _validate_namespace(part_meta, objects.parent.parent)
        if final.is_symlink() or _is_reparse(final):
            raise SecEdgarBulkUnavailable("SEC bulk artifact destination is a link")
        if final.exists():
            if _sha256_file(final) != _sha256_file(part):
                raise SecEdgarBulkUnavailable("immutable SEC bulk artifact checksum conflict")
            part.unlink()
        else:
            part.replace(final)
            _fsync_directory(final.parent)
        part_meta.unlink(missing_ok=True)


def _cached_result(metadata: dict[str, object], paths: dict[str, Path], url: str, dataset: str) -> RawDocument:
    artifact = _metadata_artifact(metadata, paths, url)
    if artifact is None:
        raise SecEdgarBulkUnavailable(f"no cached SEC {dataset} bulk artifact is available")
    return _result(artifact, url, metadata, _int_value(metadata.get("status"), 200), dataset)


def _result(path: Path, url: str, metadata: dict[str, object], status: int, dataset: str) -> RawDocument:
    if not path.is_file() or _sha256_file(path) != str(metadata.get("sha256", "")):
        raise SecEdgarBulkUnavailable("cached SEC bulk artifact checksum is invalid")
    try:
        retrieved = datetime.fromisoformat(str(metadata.get("retrieved_at", "")))
    except (TypeError, ValueError) as exc:
        raise SecEdgarBulkUnavailable("cached SEC bulk acquisition time is invalid") from exc
    if retrieved.tzinfo is None or retrieved.utcoffset() is None:
        raise SecEdgarBulkUnavailable("cached SEC bulk acquisition time is not timezone-aware")
    _validate_zip(path)
    return RawDocument(path, url, retrieved, str(metadata["sha256"]), "sec_edgar", f"sec_{dataset}_bulk", "application/zip", status)


def _metadata_artifact(metadata: dict[str, object], paths: dict[str, Path], url: str) -> Path | None:
    required = {
        "schema_version", "dataset", "source_url", "retrieved_at", "sha256",
        "raw_path", "status", "etag", "last_modified", "complete", "bytes",
    }
    if set(metadata) != required:
        return None
    if (
        metadata.get("schema_version") != 2
        or metadata.get("dataset") != paths["objects"].name
        or metadata.get("source_url") != url
        or metadata.get("complete") is not True
    ):
        return None
    status = metadata.get("status")
    if isinstance(status, bool) or not isinstance(status, int) or status not in {200, 206}:
        return None
    size = metadata.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > MAX_BULK_BYTES:
        return None
    sha256 = metadata.get("sha256")
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        return None
    retrieved_at = metadata.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        return None
    try:
        parsed = datetime.fromisoformat(retrieved_at)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    etag = metadata.get("etag")
    if not isinstance(etag, str) or (etag and _strong_validator(etag) != etag):
        return None
    if not isinstance(metadata.get("last_modified"), str):
        return None
    raw_value = metadata.get("raw_path")
    if not isinstance(raw_value, str):
        return None
    raw_path = Path(raw_value)
    expected_path = paths["objects"] / f"{sha256}.zip"
    if os.path.normcase(str(raw_path.absolute())) != os.path.normcase(str(expected_path.absolute())):
        return None
    try:
        _validate_namespace(raw_path, paths["root"])
    except SecEdgarBulkUnavailable:
        return None
    if not raw_path.is_file() or raw_path.stat().st_size != size:
        return None
    return raw_path


def _paths(root: Path, dataset: str) -> dict[str, Path]:
    return {
        "root": root,
        "objects": root / "objects" / dataset,
        "partials": root / "partials",
        "part": root / "partials" / f"{dataset}.part",
        "part_meta": root / "partials" / f"{dataset}.json",
        "metadata": root / f"{dataset}.meta.json",
        "lock": root / "locks" / f"{dataset}.guard",
    }


def _prepare_paths(paths: dict[str, Path], root: Path) -> None:
    try:
        for path in (root, paths["objects"], paths["partials"], paths["lock"].parent):
            _validate_namespace(path, root.parent if path == root else root)
            path.mkdir(parents=True, exist_ok=True)
            _validate_namespace(path, root.parent if path == root else root)
        # Reject pre-existing link leaves before any atomic replacement.  This
        # keeps metadata/partial/guard writes inside the intended namespace.
        for leaf in (paths["metadata"], paths["part"], paths["part_meta"], paths["lock"]):
            _validate_namespace(leaf, root)
            if leaf.is_symlink() or _is_reparse(leaf):
                raise SecEdgarBulkUnavailable(f"SEC bulk destination is a link: {leaf.name}")
        # Create the persistent guard leaf while publication authorization is
        # held; later lock acquisition only opens this established file.
        paths["lock"].touch(exist_ok=True)
    except SecEdgarBulkUnavailable:
        raise
    except OSError as exc:
        raise SecEdgarBulkUnavailable("SEC bulk cache namespace cannot be prepared") from exc


def _validate_root(root: Path) -> None:
    _validate_namespace(root, root.parent)


def _validate_namespace(path: Path, root: Path) -> None:
    absolute = Path(path).absolute()
    root_absolute = Path(root).absolute()
    try:
        absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise SecEdgarBulkUnavailable(f"SEC bulk path escapes namespace: {path}") from exc
    current = absolute
    chain: list[Path] = []
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    for candidate in reversed(chain):
        if candidate.is_symlink() or _is_reparse(candidate):
            raise SecEdgarBulkUnavailable(f"SEC bulk path contains a link: {candidate}")


def _is_reparse(path: Path) -> bool:
    try:
        return bool(int(getattr(path.lstat(), "st_file_attributes", 0)) & 0x400)
    except OSError:
        return False


@contextmanager
def _guard(path: Path) -> Iterator[object]:
    _validate_namespace(path, path.parent.parent)
    with persistent_file_guard(path) as guard:
        yield guard


def _read_json(path: Path) -> dict[str, object]:
    try:
        if path.is_symlink() or _is_reparse(path):
            raise SecEdgarBulkUnavailable("SEC bulk metadata path is a link")
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _partial_state(paths: dict[str, Path], expected_url: str | None = None, expected_dataset: str | None = None) -> dict[str, object]:
    state = _read_json(paths["part_meta"])
    if not paths["part"].is_file() or state.get("bytes") != paths["part"].stat().st_size:
        return {}
    if expected_url is not None and state.get("source_url") != expected_url:
        return {}
    if expected_dataset is not None and state.get("dataset") != expected_dataset:
        return {}
    if state.get("schema_version") != _PARTIAL_SCHEMA_VERSION:
        return {}
    if state.get("complete") is not False:
        return {}
    offset = state.get("bytes")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return {}
    total = state.get("total")
    if total is not None and (isinstance(total, bool) or not isinstance(total, int) or total < offset):
        return {}
    validator = state.get("validator")
    if validator is not None and validator != "" and _strong_validator(validator) is None:
        return {}
    generation = state.get("generation")
    prefix_sha256 = state.get("prefix_sha256")
    if not isinstance(generation, str) or not generation or not isinstance(prefix_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", prefix_sha256):
        return {}
    if _sha256_file(paths["part"]) != prefix_sha256:
        return {}
    return state


def _write_partial_file(
    paths: dict[str, Path], dataset: str, source_url: str, bytes_written: int,
    total: int | None, validator: str | None, generation: str, prefix_sha256: str,
) -> None:
    payload = {
        "schema_version": _PARTIAL_SCHEMA_VERSION,
        "dataset": dataset,
        "source_url": source_url,
        "bytes": bytes_written,
        "total": total,
        "validator": validator,
        "generation": generation,
        "prefix_sha256": prefix_sha256,
        "complete": False,
    }
    atomic_write_json(paths["part_meta"], payload)


def _validate_zip(path: Path) -> None:
    try:
        _validate_zip_container(path)
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_BULK_MEMBERS:
                raise SecEdgarBulkUnavailable("SEC bulk ZIP central directory is too large")
            compressed_total = 0
            names: set[str] = set()
            for member in members:
                name = member.filename
                _validate_member_name(name)
                if name in names or member.flag_bits & 1 or stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF):
                    raise SecEdgarBulkUnavailable("SEC bulk ZIP contains duplicate, encrypted, or linked members")
                if member.file_size < 0 or member.compress_size < 0 or (member.file_size and member.compress_size == 0):
                    raise SecEdgarBulkUnavailable("SEC bulk ZIP member sizes are invalid")
                if member.compress_size and member.file_size / member.compress_size > MAX_BULK_COMPRESSION_RATIO:
                    raise SecEdgarBulkUnavailable("SEC bulk ZIP compression ratio is unsafe")
                compressed_total += member.compress_size
                if compressed_total > MAX_BULK_BYTES:
                    raise SecEdgarBulkUnavailable("SEC bulk ZIP compressed bytes exceed the bound")
                names.add(name)
    except SecEdgarBulkUnavailable:
        raise
    except zipfile.BadZipFile as exc:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP structure is invalid") from exc
    except (OSError, OverflowError, RuntimeError, ValueError, KeyError) as exc:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP structure could not be validated") from exc


def _validate_zip_container(path: Path) -> None:
    """Bound EOCD/ZIP64 metadata before asking ZipFile for all members."""

    file_size = path.stat().st_size
    if file_size < 22:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP is smaller than its EOCD")
    scan_size = min(file_size, _EOCD_SCAN_BYTES)
    with path.open("rb") as handle:
        handle.seek(file_size - scan_size)
        tail = handle.read(scan_size)
    eocd = -1
    search_end = len(tail)
    while True:
        candidate = tail.rfind(b"PK\x05\x06", 0, search_end)
        if candidate < 0 or candidate + 22 > len(tail):
            break
        comment_length = struct.unpack_from("<H", tail, candidate + 20)[0]
        if candidate + 22 + comment_length == len(tail):
            eocd = candidate
            break
        search_end = candidate
    if eocd < 0:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP EOCD is missing or malformed")
    disk, central_disk, entries_disk, entries, central_size, central_offset = struct.unpack_from(
        "<HHHHII", tail, eocd + 4
    )
    if disk != 0 or central_disk != 0 or entries_disk != entries:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP is multi-disk")
    if entries == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        locator = tail.rfind(b"PK\x06\x07", 0, eocd)
        if locator < 0 or locator + 20 > len(tail):
            raise SecEdgarBulkUnavailable("SEC ZIP64 locator is missing")
        locator_disk, zip64_offset, total_disks = struct.unpack_from("<IQI", tail, locator + 4)
        if locator_disk != 0 or total_disks != 1:
            raise SecEdgarBulkUnavailable("SEC ZIP64 is multi-disk")
        record = _read_at(path, zip64_offset, 56)
        if record[:4] != b"PK\x06\x06":
            raise SecEdgarBulkUnavailable("SEC ZIP64 EOCD is malformed")
        record_size = struct.unpack_from("<Q", record, 4)[0]
        if record_size < 44:
            raise SecEdgarBulkUnavailable("SEC ZIP64 EOCD size is invalid")
        _, _, disk, central_disk, entries_disk64, entries64, central_size64, central_offset64 = struct.unpack_from(
            "<2H2I4Q", record, 12
        )
        if disk != 0 or central_disk != 0 or entries_disk64 != entries64:
            raise SecEdgarBulkUnavailable("SEC ZIP64 is multi-disk")
        entries, central_size, central_offset = entries64, central_size64, central_offset64
    if entries > MAX_BULK_MEMBERS:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP central directory is too large")
    if central_size > MAX_CENTRAL_DIRECTORY_BYTES or central_offset > file_size or central_size > file_size - central_offset:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP central directory exceeds its bound")


def _read_at(path: Path, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or offset > path.stat().st_size or length > path.stat().st_size - offset:
        raise SecEdgarBulkUnavailable("SEC ZIP64 metadata points outside the archive")
    with path.open("rb") as handle:
        handle.seek(offset)
        payload = handle.read(length)
    if len(payload) != length:
        raise SecEdgarBulkUnavailable("SEC ZIP64 metadata is truncated")
    return payload


def _validate_member_name(name: object) -> None:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP member name is invalid")
    normalised = name.replace("\\", "/")
    parsed = PurePosixPath(normalised)
    if parsed.is_absolute() or re.match(r"^[A-Za-z]:", normalised) or ".." in parsed.parts:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP member escapes its namespace")


def _response(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        return _StreamResponse(io.BytesIO(bytes(raw)), 200, {})
    if isinstance(raw, tuple) and len(raw) == 3:
        payload, status, headers = raw
        return _StreamResponse(io.BytesIO(bytes(payload or b"")), int(status), _headers(headers))
    if hasattr(raw, "read"):
        effective = getattr(raw, "geturl", None)
        effective_url = effective() if callable(effective) else None
        return _StreamResponse(raw, int(getattr(raw, "status", 200)), _headers(getattr(raw, "headers", {})), raw, effective_url)
    raise TypeError("SEC bulk transport must return bytes, tuple, or readable response")


class _StreamResponse:
    def __init__(self, stream: Any, status: int, headers: dict[str, str], owner: Any | None = None, effective_url: object | None = None) -> None:
        self.stream = stream
        self.status = status
        self.headers = headers
        self._owner = owner
        self.effective_url = str(effective_url) if effective_url is not None else None

    def close(self) -> None:
        close = getattr(self._owner or self.stream, "close", None)
        if callable(close):
            close()


def _headers(value: object) -> dict[str, str]:
    if hasattr(value, "items"):
        return {str(key).lower(): str(item) for key, item in value.items()}
    return {}


def _header(headers: dict[str, str], name: str) -> str:
    return str(headers.get(name.lower(), "")).strip()


def _header_int(headers: dict[str, str], name: str) -> int | None:
    value = _header(headers, name)
    return int(value) if value.isdigit() else None


def _validated_content_length(headers: dict[str, str]) -> int | None:
    value = _header(headers, "content-length")
    if not value:
        return None
    if not value.isdigit():
        raise SecEdgarBulkUnavailable("SEC bulk Content-Length is invalid")
    return int(value)


def _int_value(value: object, default: int) -> int:
    """Read a non-negative integer from untrusted persisted metadata."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _strong_validator(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    # RFC 9110 opaque-tags are quoted; this intentionally accepts only the
    # ASCII strong form and rejects weak tags, bare tokens, and controls.
    return text if re.fullmatch(r'"[\x21\x23-\x7e]*"', text) else None


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()
