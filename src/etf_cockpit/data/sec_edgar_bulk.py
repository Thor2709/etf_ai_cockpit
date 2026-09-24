"""Bounded, explicit acquisition of SEC's nightly bulk ZIP archives.

This module deliberately does not parse or publish filing facts.  It owns only
streaming transport, validator-bound resumption, immutable raw bytes, and
honest acquisition provenance.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from http.client import IncompleteRead
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
MAX_BULK_BYTES = 8 * 1024 * 1024 * 1024
# The SEC has historically published more than 780,000 submissions JSON
# members.  Keep a bounded ceiling with headroom for that known shape while
# rejecting pathological central directories before ZipInfo allocation.
MAX_BULK_MEMBERS = 1_000_000
MAX_CENTRAL_DIRECTORY_BYTES = 256 * 1024 * 1024
MAX_BULK_COMPRESSION_RATIO = 200.0
_CHUNK_BYTES = 1024 * 1024
_MAX_METADATA_BYTES = 64 * 1024
_PARTIAL_SCHEMA_VERSION = 2
# Explicit local resource policy, not a claim about current SEC archive sizes.
# Companyfacts matches the canonical local importer's existing 8 GiB ceiling;
# submissions has separate directory/member headroom for its all-filer history.
_DATASET_LIMITS = {
    "companyfacts": (8 * 1024**3, 50_000, 32 * 1024**2),
    "submissions": (8 * 1024**3, 1_000_000, 256 * 1024**2),
}


def _dataset_limits(dataset: str) -> tuple[int, int, int]:
    byte_limit, members, directory_bytes = _DATASET_LIMITS[dataset]
    return min(byte_limit, MAX_BULK_BYTES), min(members, MAX_BULK_MEMBERS), min(directory_bytes, MAX_CENTRAL_DIRECTORY_BYTES)


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
        document = _cached_result(_read_json(paths["metadata"]), paths, url, dataset)
        if not _cached_session_matches(provider, document):
            raise SecEdgarBulkUnavailable("cache-only SEC replay has no provider-owned session proof")
        return document
    # Directory and persistent-lock creation are durable namespace changes too;
    # keep them inside the caller's publication authorization boundary.
    with publication_scope(publish_guard):
        _prepare_paths(paths, root)
    with _guard(paths["lock"]):
        metadata = _read_json(paths["metadata"])
        document = _acquire(provider, dataset, url, paths, metadata, publish_guard)
        key = provider._ledger_key(document)
        if document.http_status == 304:
            provider._authority_ledger[key] = replace(provider._authority_ledger[key], revalidated=True)
            return document
        from etf_cockpit.data.sec_edgar_provider import _SessionGeneration
        provider._authority_ledger[key] = _SessionGeneration(
            document.source_url, document.sha256, document.document_type, document.path.absolute(),
            document.retrieved_at, document.provider_id, document.media_type, document.http_status,
        )
        provider._authority_ledger.move_to_end(key)
        while len(provider._authority_ledger) > provider.MAX_AUTHORITY_LEDGER:
            provider._authority_ledger.popitem(last=False)
        return document


def _cached_session_matches(provider: Any, document: RawDocument) -> bool:
    generation = provider._authority_ledger.get(provider._ledger_key(document))
    return bool(
        generation is not None
        and generation.http_status == document.http_status
        and provider._session_generation_matches(document)
    )


def _acquire(provider: Any, dataset: str, url: str, paths: dict[str, Path], metadata: dict[str, object], publish_guard: PublicationScopeFactory | None) -> RawDocument:
    headers = {"User-Agent": provider.user_agent, "Accept": "application/zip"}
    artifact = _metadata_artifact(metadata, paths, url)
    if artifact is not None:
        cached_document = _result(artifact, url, metadata, _int_value(metadata.get("status"), 200), dataset)
        same_session = _cached_session_matches(provider, cached_document)
        if same_session and metadata.get("etag"):
            headers["If-None-Match"] = str(metadata["etag"])
        if same_session and metadata.get("last_modified"):
            headers["If-Modified-Since"] = str(metadata["last_modified"])

    partial = _partial_state(paths, url, dataset)
    resume_offset = _int_value(partial.get("bytes"), 0) if partial else 0
    if partial and partial.get("total") is not None and resume_offset >= _int_value(partial.get("total"), 0):
        # A complete-but-invalid response (for example a bad ZIP) cannot be
        # resumed at EOF.  Let the next 200 response replace it safely.
        resume_offset = 0
    resume_validator = _strong_validator(partial.get("validator")) if partial else None
    partial_session = bool(
        partial
        and resume_offset
        and resume_validator
        and paths["part"].is_file()
        and provider._has_partial_session(dataset, url, str(partial["generation"]), _partial_identity(partial))
    )
    if partial_session:
        headers["Range"] = f"bytes={resume_offset}-"
        headers["If-Range"] = resume_validator
    else:
        resume_offset = 0
        resume_validator = None

    last_error: Exception | None = None
    cold_304_retried = False
    attempt_limit = int(provider.max_retries) + 1
    attempt = 0
    while attempt < attempt_limit:
        try:
            provider._respect_rate_limit()
            raw_response = provider._request_bulk_stream(url, headers)
            response = _response(raw_response)
            try:
                if response.effective_url is not None and response.effective_url != url:
                    raise SecEdgarBulkEndpointError("SEC bulk response followed an unexpected redirect")
                if response.status == 304:
                    if artifact is None:
                        if not cold_304_retried:
                            cold_304_retried = True
                            attempt_limit = max(attempt_limit, 2)
                            headers.pop("If-None-Match", None)
                            headers.pop("If-Modified-Since", None)
                            attempt += 1
                            continue
                        raise SecEdgarBulkUnavailable("SEC returned 304 without a cached artifact")
                    cached_document = _result(artifact, url, metadata, _int_value(metadata.get("status"), 200), dataset)
                    if not _cached_session_matches(provider, cached_document):
                        if not cold_304_retried:
                            cold_304_retried = True
                            attempt_limit = max(attempt_limit, 2)
                            headers.pop("If-None-Match", None)
                            headers.pop("If-Modified-Since", None)
                            attempt += 1
                            continue
                        raise SecEdgarBulkUnavailable("SEC returned 304 without a provider-owned session proof")
                    return _result(artifact, url, metadata, 304, dataset, revalidated=True)
                if response.status in {429} or response.status >= 500:
                    raise SecEdgarBulkUnavailable(f"SEC endpoint returned HTTP {response.status}")
                total: int | None
                generation: str | None = None
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
                        expected_length=response_length, prefix_sha256=str(partial["prefix_sha256"]), provider=provider,
                    )
                    generation = str(partial["generation"])
                elif response.status == 200:
                    total = _validated_content_length(response.headers)
                    generation = uuid.uuid4().hex
                    _stream_response(
                        response.stream, paths, publish_guard, 0, total,
                        response.headers, url, dataset, append=False, generation=generation,
                        expected_length=total, prefix_sha256=None, provider=provider,
                    )
                elif response.status < 200 or response.status >= 300:
                    raise SecEdgarBulkUnavailable(f"SEC endpoint returned HTTP {response.status}")
                else:
                    raise SecEdgarBulkUnavailable(f"SEC endpoint returned unsupported HTTP {response.status}")
            finally:
                response.close()
            payload_sha = _sha256_file(paths["part"])
            if total is not None and paths["part"].stat().st_size != total:
                raise SecEdgarBulkUnavailable("SEC bulk resource is not complete")
            _validate_zip(paths["part"], dataset)
            final = paths["objects"] / f"{payload_sha}.zip"
            _publish_artifact(paths["part"], final, paths["part_meta"], publish_guard, paths["objects"])
            if generation is not None:
                provider._forget_partial_session(dataset, url, generation)
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
            document = RawDocument(final, url, acquired_at, payload_sha, "sec_edgar", f"sec_{dataset}_bulk", "application/zip", response.status)
            return document
        except WorkflowTransitionError:
            raise
        except SecEdgarBulkEndpointError:
            raise
        except SecEdgarBulkResumeError:
            # A mismatched continuation must never be retried into a splice.
            raise
        except SecEdgarBulkUnavailable as exc:
            last_error = exc
            if attempt >= attempt_limit - 1:
                raise
            provider._sleep(min(2.0, 0.25 * (2**attempt)))
        except (OSError, IOError, TimeoutError, IncompleteRead, ValueError, TypeError, zipfile.BadZipFile) as exc:
            last_error = exc
            if attempt >= attempt_limit - 1:
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
            if (
                resume_offset
                and resume_validator
                and isinstance(partial.get("generation"), str)
                and provider._has_partial_session(dataset, url, str(partial["generation"]), _partial_identity(partial))
            ):
                headers["Range"] = f"bytes={resume_offset}-"
                headers["If-Range"] = resume_validator
            else:
                headers.pop("Range", None)
                headers.pop("If-Range", None)
                resume_offset = 0
                resume_validator = None
        attempt += 1
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
    provider: Any,
) -> None:
    """Read network bytes without the publication lock and checkpoint each write."""

    validator = _strong_validator(_header(headers, "etag"))
    byte_limit, _, _ = _dataset_limits(dataset)
    if append and validator is None:
        raise SecEdgarBulkResumeError("resumed response does not repeat a strong ETag")
    if expected_length is not None and expected_length < 0:
        raise SecEdgarBulkUnavailable("SEC bulk response length is invalid")
    if total is not None and total > byte_limit:
        raise SecEdgarBulkUnavailable("SEC bulk declared size exceeds the dataset byte limit")

    if append:
        current = _partial_state(paths, source_url, dataset)
        if not current or not provider._has_partial_session(dataset, source_url, str(generation), _partial_identity(current)):
            raise SecEdgarBulkResumeError("resumed partial session state changed before append")
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
        if generation is None:
            generation = uuid.uuid4().hex
        streamed = 0
        # Invalidate the previous generation before truncating its bytes.  If
        # authorization or metadata publication fails, no stale proof can
        # authorize a later append.
        with publication_scope(publish_guard):
            _start_generation(paths, dataset, source_url, total, validator, generation)
        digest = hashlib.sha256()

    def checkpoint_file() -> None:
        _checkpoint_partial_file(paths, dataset, source_url, streamed, total, validator, generation, digest.hexdigest())
        provider._remember_partial_session(
            dataset, source_url, generation,
            (streamed, total, validator, digest.hexdigest()),
        )

    def checkpoint() -> None:
        with publication_scope(publish_guard):
            checkpoint_file()

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
                if (
                    streamed + len(candidate) <= byte_limit
                    and (total is None or streamed + len(candidate) <= total)
                    and (expected_length is None or received + len(candidate) <= expected_length)
                ):
                    with publication_scope(publish_guard):
                        _append_chunk(paths, candidate)
                        streamed += len(candidate)
                        received += len(candidate)
                        digest.update(candidate)
            checkpoint()
            raise
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            checkpoint()
            raise TypeError("SEC bulk response returned a non-bytes chunk")
        chunk_bytes = bytes(chunk)
        next_size = streamed + len(chunk_bytes)
        if next_size > byte_limit or (total is not None and next_size > total):
            checkpoint()
            raise SecEdgarBulkUnavailable("SEC bulk response exceeds its bounded byte limit")
        if expected_length is not None and received + len(chunk_bytes) > expected_length:
            checkpoint()
            raise SecEdgarBulkResumeError("SEC bulk response body exceeds Content-Length") if append else SecEdgarBulkUnavailable("SEC bulk response body exceeds Content-Length")
        try:
            with publication_scope(publish_guard):
                _append_chunk(paths, chunk_bytes)
                streamed = next_size
                received += len(chunk_bytes)
                digest.update(chunk_bytes)
                checkpoint_file()
        except BaseException:
            provider._forget_partial_session(dataset, source_url, generation)
            # If the write itself partially succeeded, checkpoint the actual
            # on-disk prefix; a size/hash mismatch makes it non-resumable.
            actual = paths["part"].stat().st_size if paths["part"].is_file() else 0
            actual_sha = _sha256_file(paths["part"]) if actual else _EMPTY_SHA256
            with publication_scope(publish_guard):
                _write_partial_file(paths, dataset, source_url, actual, total, validator, generation, actual_sha)
            raise

    if (expected_length is not None and received != expected_length) or (total is not None and streamed != total):
        checkpoint()
        raise SecEdgarBulkUnavailable("SEC bulk response was truncated")
    checkpoint()


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


def _checkpoint_partial_file(paths: dict[str, Path], dataset: str, source_url: str, streamed: int, total: int | None, validator: str | None, generation: str, prefix_sha256: str) -> None:
    actual = paths["part"].stat().st_size if paths["part"].is_file() else 0
    if actual != streamed:
        raise SecEdgarBulkResumeError("partial size changed before checkpoint")
    _write_partial_file(paths, dataset, source_url, streamed, total, validator, generation, prefix_sha256)


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


def _result(
    path: Path,
    url: str,
    metadata: dict[str, object],
    status: int,
    dataset: str,
    *,
    revalidated: bool = False,
) -> RawDocument:
    if not path.is_file() or _sha256_file(path) != str(metadata.get("sha256", "")):
        raise SecEdgarBulkUnavailable("cached SEC bulk artifact checksum is invalid")
    try:
        retrieved = datetime.fromisoformat(str(metadata.get("retrieved_at", "")))
    except (TypeError, ValueError) as exc:
        raise SecEdgarBulkUnavailable("cached SEC bulk acquisition time is invalid") from exc
    if retrieved.tzinfo is None or retrieved.utcoffset() is None:
        raise SecEdgarBulkUnavailable("cached SEC bulk acquisition time is not timezone-aware")
    _validate_zip(path, dataset)
    return RawDocument(
        path,
        url,
        retrieved,
        str(metadata["sha256"]),
        "sec_edgar",
        f"sec_{dataset}_bulk",
        "application/zip",
        304 if revalidated else status,
    )


def _metadata_artifact(metadata: dict[str, object], paths: dict[str, Path], url: str) -> Path | None:
    required = {
        "schema_version", "dataset", "source_url", "retrieved_at", "sha256",
        "raw_path", "status", "etag", "last_modified", "complete", "bytes",
    }
    if set(metadata) != required:
        return None
    if (
        type(metadata.get("schema_version")) is not int
        or metadata.get("schema_version") != 2
        or metadata.get("dataset") != paths["objects"].name
        or metadata.get("source_url") != url
        or metadata.get("complete") is not True
    ):
        return None
    status = metadata.get("status")
    if isinstance(status, bool) or not isinstance(status, int) or status not in {200, 206}:
        return None
    size = metadata.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > _dataset_limits(paths["objects"].name)[0]:
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
        if not path.is_file() or path.stat().st_size > _MAX_METADATA_BYTES:
            return {}
        with path.open("rb") as handle:
            raw = handle.read(_MAX_METADATA_BYTES + 1)
        if len(raw) > _MAX_METADATA_BYTES:
            return {}
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError, RecursionError):
        return {}


def _partial_identity(state: dict[str, object]) -> tuple[object, ...]:
    return (state.get("bytes"), state.get("total"), state.get("validator"), state.get("prefix_sha256"))


def _partial_state(paths: dict[str, Path], expected_url: str | None = None, expected_dataset: str | None = None) -> dict[str, object]:
    state = _read_json(paths["part_meta"])
    byte_limit, _, _ = _dataset_limits(paths["objects"].name)
    required = {"schema_version", "dataset", "source_url", "bytes", "total", "validator", "generation", "prefix_sha256", "complete"}
    if set(state) != required or (paths["part"].is_file() and paths["part"].stat().st_size > byte_limit):
        return {}
    if not paths["part"].is_file() or state.get("bytes") != paths["part"].stat().st_size:
        return {}
    if expected_url is not None and state.get("source_url") != expected_url:
        return {}
    if expected_dataset is not None and state.get("dataset") != expected_dataset:
        return {}
    if type(state.get("schema_version")) is not int or state.get("schema_version") != _PARTIAL_SCHEMA_VERSION:
        return {}
    if state.get("complete") is not False:
        return {}
    offset = state.get("bytes")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return {}
    total = state.get("total")
    if total is not None and (isinstance(total, bool) or not isinstance(total, int) or total < offset or total > byte_limit):
        return {}
    validator = state.get("validator")
    if validator is not None and validator != "" and _strong_validator(validator) is None:
        return {}
    generation = state.get("generation")
    prefix_sha256 = state.get("prefix_sha256")
    if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation) or not isinstance(prefix_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", prefix_sha256):
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


def _validate_zip(path: Path, dataset: str) -> None:
    try:
        byte_limit, member_limit, _ = _dataset_limits(dataset)
        _validate_zip_container(path, dataset)
        with _open_zipfile(path) as archive:
            members = archive.infolist()
            if len(members) > member_limit:
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
                if compressed_total > byte_limit:
                    raise SecEdgarBulkUnavailable("SEC bulk ZIP compressed bytes exceed the bound")
                names.add(name)
    except SecEdgarBulkUnavailable:
        raise
    except zipfile.BadZipFile as exc:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP structure is invalid") from exc
    except (OSError, OverflowError, RuntimeError, ValueError, KeyError) as exc:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP structure could not be validated") from exc


def _validate_zip_container(path: Path, dataset: str) -> None:
    """Validate bounded EOCD/ZIP64 structures without private ``zipfile`` APIs."""

    byte_limit, member_limit, directory_limit = _dataset_limits(dataset)
    file_size = path.stat().st_size
    if not 22 <= file_size <= byte_limit:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP size is outside its bound")
    eocd_offset, eocd = _find_eocd(path)
    _, disk, central_disk, entries_disk, entries16, central_size32, central_offset32, comment_size = struct.unpack(
        "<4s4H2IH", eocd[:22]
    )
    if disk != 0 or central_disk != 0 or entries_disk != entries16:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP is multi-disk")
    if eocd_offset + 22 + comment_size != file_size:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP EOCD comment is malformed")
    sentinel = (
        entries_disk == 0xFFFF
        or entries16 == 0xFFFF
        or central_size32 == 0xFFFFFFFF
        or central_offset32 == 0xFFFFFFFF
    )
    entries = entries16
    central_size = central_size32
    central_offset = central_offset32
    zip64_record_offset = eocd_offset
    locator_offset = eocd_offset - 20
    has_locator = locator_offset >= 0 and _read_at(path, locator_offset, 4) == b"PK\x06\x07"
    if sentinel and not has_locator:
        raise SecEdgarBulkUnavailable("SEC ZIP64 locator is missing")
    if has_locator:
        zip64 = _read_zip64_record(path, locator_offset)
        if zip64 is None:
            raise SecEdgarBulkUnavailable("SEC ZIP64 locator or record is malformed")
        zip64_entries, zip64_size, zip64_offset, zip64_declared_record_offset, zip64_record_offset = zip64
        # An adjacent ZIP64 record is the authoritative directory declaration
        # even when a producer omitted the legacy EOCD sentinels.  This also
        # prevents a misleading legacy EOCD from selecting a different table.
        entries, central_size, central_offset = zip64_entries, zip64_size, zip64_offset
    if entries > member_limit or central_size > directory_limit:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP central directory exceeds its bound")
    directory_end = zip64_record_offset if has_locator else eocd_offset
    directory_start = directory_end - central_size
    concat = directory_start - central_offset
    if directory_start < 0 or concat < 0:
        raise SecEdgarBulkUnavailable("SEC bulk ZIP central directory offset is invalid")
    if has_locator and zip64_declared_record_offset + concat != zip64_record_offset:
        raise SecEdgarBulkUnavailable("SEC ZIP64 record offset is inconsistent")
    consumed = 0
    actual_entries = 0
    with path.open("rb") as handle:
        handle.seek(directory_start)
        while consumed < central_size:
            if central_size - consumed < 46:
                raise SecEdgarBulkUnavailable("SEC ZIP central directory is truncated")
            header = handle.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise SecEdgarBulkUnavailable("SEC ZIP central directory record is invalid")
            (
                _, _, _, flags, _, _, _, _, compressed_size, member_size,
                name_length, extra_length, comment_length, _, _, external_attr, _,
            ) = struct.unpack("<4s6H3I5H2I", header)
            name = handle.read(name_length)
            handle.seek(extra_length + comment_length, os.SEEK_CUR)
            try:
                member_name = name.decode("utf-8" if flags & 0x800 else "cp437")
            except UnicodeDecodeError as exc:
                raise SecEdgarBulkUnavailable("SEC ZIP member name is not UTF-8") from exc
            _validate_member_name(member_name)
            if flags & 1 or member_size < 0 or compressed_size < 0 or (member_size and compressed_size == 0):
                raise SecEdgarBulkUnavailable("SEC bulk ZIP contains an unsafe member")
            if compressed_size and member_size / compressed_size > MAX_BULK_COMPRESSION_RATIO:
                raise SecEdgarBulkUnavailable("SEC bulk ZIP compression ratio is unsafe")
            if stat.S_ISLNK((external_attr >> 16) & 0xFFFF):
                raise SecEdgarBulkUnavailable("SEC bulk ZIP contains a linked member")
            record_size = 46 + name_length + extra_length + comment_length
            consumed += record_size
            actual_entries += 1
            if consumed > central_size or actual_entries > member_limit or actual_entries > entries:
                raise SecEdgarBulkUnavailable("SEC ZIP central directory records exceed declared bounds")
    if actual_entries != entries:
        raise SecEdgarBulkUnavailable("SEC ZIP central directory count is inconsistent")


def _has_zip64_extensible_data(path: Path) -> bool:
    try:
        eocd_offset, _ = _find_eocd(path)
        locator_offset = eocd_offset - 20
        if locator_offset < 0 or _read_at(path, locator_offset, 4) != b"PK\x06\x07":
            return False
        record = _read_zip64_record(path, locator_offset)
        return record is not None and record[4] + 56 < locator_offset
    except (OSError, ValueError, SecEdgarBulkUnavailable):
        return False


@contextmanager
def _open_zipfile(path: Path) -> Iterator[zipfile.ZipFile]:
    """Open ordinary ZIPs or a ZIP64 archive with bounded extensible data."""

    view = _zip64_view(path)
    archive = zipfile.ZipFile(view or path)
    try:
        yield archive
    finally:
        archive.close()


def _zip64_view(path: Path) -> "_Zip64View | None":
    eocd_offset, _ = _find_eocd(path)
    locator_offset = eocd_offset - 20
    if locator_offset < 0 or _read_at(path, locator_offset, 4) != b"PK\x06\x07":
        return None
    record = _read_zip64_record(path, locator_offset)
    if record is None or record[4] + 56 >= locator_offset:
        return None
    return _Zip64View(path, record[4] + 56, locator_offset)


class _Zip64View:
    """Seekable file view with ZIP64 extensible bytes removed logically."""

    def __init__(self, path: Path, skip_start: int, skip_end: int) -> None:
        self._file = path.open("rb")
        self._skip_start = skip_start
        self._skip_end = skip_end
        self._length = path.stat().st_size - (skip_end - skip_start)
        self._position = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            position = offset
        elif whence == os.SEEK_CUR:
            position = self._position + offset
        elif whence == os.SEEK_END:
            position = self._length + offset
        else:
            raise ValueError("invalid ZIP64 view seek mode")
        if position < 0:
            raise ValueError("negative ZIP64 view seek")
        self._position = position
        return position

    def tell(self) -> int:
        return self._position

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._length - self._position
        size = min(size, max(0, self._length - self._position))
        logical_start = self._position
        remaining = size
        chunks: list[bytes] = []
        while remaining:
            physical = self._position if self._position < self._skip_start else self._position + (self._skip_end - self._skip_start)
            before_skip = self._skip_start - self._position if self._position < self._skip_start else remaining
            chunk_size = min(remaining, before_skip)
            self._file.seek(physical)
            chunk = self._file.read(chunk_size)
            if len(chunk) != chunk_size:
                break
            chunks.append(chunk)
            self._position += chunk_size
            remaining -= chunk_size
        payload = bytearray(b"".join(chunks))
        # Removing the extensible sector also normalises the ZIP64 record's
        # declared body length from ``44 + extensible`` to the fixed 44-byte
        # body exposed by this view. Patch only reads overlapping that field.
        size_field_start = self._skip_start - 52
        replacement = struct.pack("<Q", 44)
        overlap_start = max(logical_start, size_field_start)
        overlap_end = min(logical_start + len(payload), size_field_start + len(replacement))
        if overlap_start < overlap_end:
            payload[overlap_start - logical_start:overlap_end - logical_start] = replacement[
                overlap_start - size_field_start:overlap_end - size_field_start
            ]
        return bytes(payload)

    def close(self) -> None:
        self._file.close()


def _find_eocd(path: Path) -> tuple[int, bytes]:
    """Find the last EOCD in the APPNOTE-bounded comment search window."""

    size = path.stat().st_size
    window_start = max(0, size - (22 + 0xFFFF))
    with path.open("rb") as handle:
        handle.seek(window_start)
        tail = handle.read(size - window_start)
    for relative in range(len(tail) - 22, -1, -1):
        if tail[relative:relative + 4] != b"PK\x05\x06":
            continue
        comment_size = struct.unpack_from("<H", tail, relative + 20)[0]
        if relative + 22 + comment_size == len(tail):
            return window_start + relative, tail[relative:relative + 22]
    raise SecEdgarBulkUnavailable("SEC bulk ZIP EOCD is missing or malformed")


def _read_zip64_record(path: Path, locator_offset: int) -> tuple[int, int, int, int, int] | None:
    locator = _read_at(path, locator_offset, 20)
    if locator[:4] != b"PK\x06\x07":
        return None
    disk, declared_record_offset, disks = struct.unpack_from("<IQI", locator, 4)
    if disk != 0 or disks != 1 or declared_record_offset < 0:
        return None
    # APPNOTE permits extensible data after the fixed ZIP64 EOCD fields, so
    # the record is not always the historical 56 bytes. Search only the
    # bounded bytes immediately preceding the locator and require the record
    # length to land exactly at the locator.
    search_start = max(0, locator_offset - 12 - 1024)
    for record_offset in range(locator_offset - 12, search_start - 1, -1):
        fixed = _read_at(path, record_offset, 12)
        if fixed[:4] != b"PK\x06\x06":
            continue
        record_size = struct.unpack_from("<Q", fixed, 4)[0]
        if record_size < 44 or record_size > 1024:
            continue
        total_size = 12 + record_size
        if record_offset + total_size != locator_offset:
            continue
        record = _read_at(path, record_offset, total_size)
        if len(record) < 56:
            continue
        _, _, _, _, record_disk, record_central_disk, entries_disk, entries, central_size, central_offset = struct.unpack_from(
            "<4sQ2H2I4Q", record, 0
        )
        if record_disk != 0 or record_central_disk != 0 or entries_disk != entries:
            continue
        return entries, central_size, central_offset, declared_record_offset, record_offset
    return None


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
