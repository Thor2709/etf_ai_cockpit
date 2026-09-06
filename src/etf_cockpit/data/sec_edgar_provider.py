"""Small, keyless SEC EDGAR acquisition adapter.

The provider deliberately owns only acquisition and immutable raw-cache
provenance.  Parsing and canonical mapping live in :mod:`sec_facts`; no
network response is allowed to bypass the identity and JSON checks here.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from etf_cockpit.core.atomic_io import atomic_write_bytes, atomic_write_json
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority
from etf_cockpit.parsers.contracts import RawDocument


Transport = Callable[[str, dict[str, str]], Any]


class SecEdgarError(RuntimeError):
    """Base class for controlled SEC acquisition failures."""


class SecEdgarUnavailable(SecEdgarError):
    """The SEC endpoint could not be reached after bounded retries."""


@dataclass(frozen=True)
class _Response:
    payload: bytes
    status: int
    headers: dict[str, str]


@dataclass(frozen=True)
class _SessionGeneration:
    """Immutable facts for one validated provider-session generation."""

    source_url: str
    sha256: str
    document_type: str
    path: Path
    retrieved_at: datetime
    provider_id: str
    media_type: str
    http_status: int


class SecEdgarProvider:
    """Fetch SEC submissions/companyfacts using a deterministic local cache.

    ``transport`` is injectable for offline tests and may return bytes, a
    ``(bytes, status, headers)`` tuple, or an object exposing ``read``,
    ``status`` and ``headers`` like an ``urllib`` response.
    """

    BASE_URL = "https://data.sec.gov"
    MAX_AUTHORITY_LEDGER = 128

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        return (ProviderCapability(
            provider_id="sec_edgar",
            dataset_type="filings",
            status="unavailable",
            authority=SourceAuthority.OFFICIAL,
            configured=True,
            entitlement="keyless_public",
            rate_limit_note="probe only; no network request",
            last_success_at=None,
            error_fingerprint=None,
            secret_present=False,
            message="SEC EDGAR is keyless but optional; acquisition is explicit and no probe network call was made.",
        ),)

    def __init__(
        self,
        user_agent: str,
        *,
        cache_dir: Path,
        transport: Transport | None = None,
        timeout: float = 20.0,
        rate_limit_seconds: float = 0.1,
        max_retries: int = 1,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        cleaned_agent = str(user_agent or "").strip()
        if not _valid_user_agent(cleaned_agent):
            raise ValueError("SEC provider requires an organisation name and a non-placeholder contact email")
        if timeout <= 0:
            raise ValueError("SEC provider timeout must be positive")
        if rate_limit_seconds < 0:
            raise ValueError("SEC provider rate limit cannot be negative")
        if max_retries < 0 or max_retries > 3:
            raise ValueError("SEC provider retries must be between 0 and 3")
        self.user_agent = cleaned_agent
        self.cache_dir = Path(cache_dir)
        self.transport = transport
        self.timeout = float(timeout)
        self.rate_limit_seconds = float(rate_limit_seconds)
        self.max_retries = int(max_retries)
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._authority_ledger: OrderedDict[tuple[str, str, str, str], _SessionGeneration] = OrderedDict()
        self._partial_sessions: OrderedDict[tuple[str, str, str], None] = OrderedDict()

    def fetch_companyfacts(
        self,
        cik: str,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> RawDocument:
        cik_text = _normalise_cik(cik)
        document = self._fetch(
            f"{self.BASE_URL}/api/xbrl/companyfacts/CIK{cik_text}.json",
            f"companyfacts_{cik_text}.json",
            "sec_companyfacts",
            cik_text,
            publish_guard=publish_guard,
        )
        return document

    def fetch_submissions(
        self,
        cik: str,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> RawDocument:
        cik_text = _normalise_cik(cik)
        document = self._fetch(
            f"{self.BASE_URL}/submissions/CIK{cik_text}.json",
            f"submissions_{cik_text}.json",
            "sec_submissions",
            cik_text,
            publish_guard=publish_guard,
        )
        return document

    def import_submissions(
        self,
        identity: Any,
        *,
        import_cache_dir: Path,
        **kwargs: Any,
    ) -> Any:
        """Acquire and import submissions through one provider-owned seam.

        The returned import may expose the live official document in memory,
        but the durable manifest is always local/manual.  A caller cannot
        reproduce the provider-owned session generation required by the importer.
        """

        from etf_cockpit.application.sec_submissions_import import _import_provider_submissions

        cik = _normalise_cik(getattr(identity, "cik", ""))
        document = self._fetch(
            f"{self.BASE_URL}/submissions/CIK{cik}.json",
            f"submissions_{cik}.json",
            "sec_submissions",
            cik,
        )
        return _import_provider_submissions(self, document, identity, cache_dir=import_cache_dir, **kwargs)

    fetch_and_import_submissions = import_submissions

    def import_submissions_bulk(
        self,
        identity: Any,
        *,
        import_cache_dir: Path,
        cache_only: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Acquire the submissions archive and import its selected member."""

        from etf_cockpit.application.sec_submissions_import import _import_provider_submissions
        from etf_cockpit.data.sec_edgar_bulk import fetch_bulk

        document = fetch_bulk(self, "submissions", cache_only=cache_only)
        return _import_provider_submissions(self, document, identity, cache_dir=import_cache_dir, **kwargs)

    def fetch_companyfacts_bulk(
        self,
        *,
        publish_guard: PublicationScopeFactory | None = None,
        cache_only: bool = False,
    ) -> RawDocument:
        """Explicitly acquire the SEC companyfacts bulk ZIP."""

        from etf_cockpit.data.sec_edgar_bulk import fetch_bulk

        return fetch_bulk(self, "companyfacts", publish_guard=publish_guard, cache_only=cache_only)

    def fetch_submissions_bulk(
        self,
        *,
        publish_guard: PublicationScopeFactory | None = None,
        cache_only: bool = False,
    ) -> RawDocument:
        """Explicitly acquire the SEC submissions bulk ZIP."""

        from etf_cockpit.data.sec_edgar_bulk import fetch_bulk

        return fetch_bulk(self, "submissions", publish_guard=publish_guard, cache_only=cache_only)

    def _ledger_key(self, document: RawDocument) -> tuple[str, str, str, str]:
        return (document.source_url, document.sha256, document.document_type, str(document.path.absolute()))

    def _session_generation_matches(self, document: RawDocument, *, allow_revalidated: bool = False) -> bool:
        key = self._ledger_key(document)
        generation = self._authority_ledger.get(key)
        if generation is None:
            return False
        if (
            generation.source_url != document.source_url
            or generation.sha256 != document.sha256
            or generation.document_type != document.document_type
            or generation.path != document.path.absolute()
            or generation.retrieved_at != document.retrieved_at
            or generation.provider_id != document.provider_id
            or generation.media_type != document.media_type
            or (
                document.http_status != generation.http_status
                and not (allow_revalidated and document.http_status == 304)
            )
        ):
            return False
        try:
            if not document.path.is_file() or _sha256(document.path.read_bytes()) != document.sha256:
                return False
        except OSError:
            return False
        self._authority_ledger.move_to_end(key)
        return True

    def _remember_partial_session(self, dataset: str, source_url: str, generation: str) -> None:
        key = (str(dataset), str(source_url), str(generation))
        self._partial_sessions[key] = None
        self._partial_sessions.move_to_end(key)
        while len(self._partial_sessions) > self.MAX_AUTHORITY_LEDGER:
            self._partial_sessions.popitem(last=False)

    def _has_partial_session(self, dataset: str, source_url: str, generation: str) -> bool:
        key = (str(dataset), str(source_url), str(generation))
        if key not in self._partial_sessions:
            return False
        self._partial_sessions.move_to_end(key)
        return True

    def _forget_partial_session(self, dataset: str, source_url: str, generation: str) -> None:
        self._partial_sessions.pop((str(dataset), str(source_url), str(generation)), None)

    def _request_bulk_stream(self, url: str, headers: dict[str, str]) -> Any:
        """Return a response with bounded ``read(size)`` access for bulk ZIPs."""

        if self.transport is not None:
            return self.transport(url, headers)
        request = Request(url, headers=headers)
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            if exc.code == 304:
                # Keep geturl(): redirects on error responses need the same
                # endpoint admission check as ordinary streamed responses.
                return exc
            raise

    def _fetch(
        self,
        url: str,
        filename: str,
        document_type: str,
        expected_cik: str,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> RawDocument:
        cache_path = self.cache_dir / filename
        metadata_path = cache_path.with_name(f"{cache_path.name}.meta.json")
        metadata = _read_metadata(metadata_path)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        same_session = False
        if cache_path.is_file():
            cached_sha = str(metadata.get("sha256") or "")
            cached_path = _immutable_cache_path(cache_path, cached_sha) if re.fullmatch(r"[0-9a-f]{64}", cached_sha) else cache_path
            try:
                cached_time = _retrieved_at(metadata)
                cached_status = int(metadata.get("status", 200))
            except (TypeError, ValueError):
                cached_time, cached_status = None, 200
            cached_document = RawDocument(cached_path, url, cached_time, cached_sha, "sec_edgar", document_type, "application/json", cached_status) if cached_path.is_file() and cached_time is not None else None
            same_session = cached_document is not None and self._session_generation_matches(cached_document)
            if same_session and metadata.get("etag"):
                headers["If-None-Match"] = str(metadata["etag"])
            if same_session and metadata.get("last_modified"):
                headers["If-Modified-Since"] = str(metadata["last_modified"])

        last_error: Exception | None = None
        attempt_limit = self.max_retries + 1
        attempt = 0
        cold_304_retried = False
        while attempt < attempt_limit:
            self._respect_rate_limit()
            try:
                response = self._request(url, headers)
                if response.status == 304:
                    if not same_session:
                        if not cold_304_retried:
                            cold_304_retried = True
                            attempt_limit = max(attempt_limit, 2)
                            headers.pop("If-None-Match", None)
                            headers.pop("If-Modified-Since", None)
                            attempt += 1
                            continue
                        raise ValueError("SEC returned 304 without a provider-owned session proof")
                    cached_payload = cache_path.read_bytes()
                    cached_sha = _sha256(cached_payload)
                    expected_sha = str(metadata.get("sha256") or "").strip().lower()
                    if expected_sha and cached_sha != expected_sha:
                        raise ValueError("SEC cached payload checksum mismatch")
                    _validate_identity(_parse_json(cached_payload), expected_cik)
                    retrieved_at = _retrieved_at(metadata)
                    immutable_path = _immutable_cache_path(cache_path, cached_sha)
                    with publication_scope(publish_guard):
                        _ensure_immutable_payload(immutable_path, cached_payload, expected_cik)
                    document = RawDocument(
                        immutable_path,
                        url,
                        retrieved_at,
                        cached_sha,
                        "sec_edgar",
                        document_type,
                        "application/json",
                        304,
                    )
                    if not self._session_generation_matches(document, allow_revalidated=True):
                        raise ValueError("SEC returned 304 without a provider-owned session proof")
                    revalidated = RawDocument(immutable_path, url, document.retrieved_at, cached_sha, "sec_edgar", document_type, "application/json", 304)
                    return revalidated
                if response.status == 429 or response.status >= 500:
                    raise SecEdgarUnavailable(f"SEC endpoint returned HTTP {response.status}")
                if response.status < 200 or response.status >= 300:
                    raise SecEdgarError(f"SEC endpoint returned HTTP {response.status}")
                payload = response.payload
                parsed = _parse_json(payload)
                _validate_identity(parsed, expected_cik)
                payload_sha = _sha256(payload)
                immutable_path = _immutable_cache_path(cache_path, payload_sha)
                with publication_scope(publish_guard):
                    _ensure_immutable_payload(immutable_path, payload, expected_cik)
                # Validation happens before replacement, so malformed/wrong-entity
                # responses cannot corrupt an already-good local cache.
                with publication_scope(publish_guard):
                    atomic_write_bytes(cache_path, payload, lambda candidate: _validate_json_file(candidate, expected_cik))
                retrieved_at = datetime.now(timezone.utc)
                next_metadata = {
                    "schema_version": 1,
                    "source_url": url,
                    "retrieved_at": retrieved_at.isoformat(),
                    "sha256": payload_sha,
                    "raw_path": str(immutable_path),
                    "status": response.status,
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                }
                with publication_scope(publish_guard):
                    atomic_write_json(metadata_path, next_metadata)
                document = RawDocument(
                    immutable_path,
                    url,
                    retrieved_at,
                    next_metadata["sha256"],
                    "sec_edgar",
                    document_type,
                    "application/json",
                    response.status,
                )
                key = self._ledger_key(document)
                self._authority_ledger[key] = _SessionGeneration(
                    document.source_url, document.sha256, document.document_type, document.path.absolute(),
                    document.retrieved_at, document.provider_id, document.media_type, document.http_status,
                )
                self._authority_ledger.move_to_end(key)
                while len(self._authority_ledger) > self.MAX_AUTHORITY_LEDGER:
                    self._authority_ledger.popitem(last=False)
                return document
            except (HTTPError, URLError, TimeoutError, OSError, SecEdgarUnavailable) as exc:
                last_error = exc
                if attempt >= attempt_limit - 1:
                    raise SecEdgarUnavailable(f"SEC request unavailable after {attempt + 1} attempt(s)") from exc
                self._sleep(min(2.0, 0.25 * (2**attempt)))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                # A bad payload is not retried and never replaces the cache.
                raise ValueError(f"SEC response JSON validation failed: {exc}") from exc
            attempt += 1
        raise SecEdgarUnavailable("SEC request unavailable") from last_error

    def _request(self, url: str, headers: dict[str, str]) -> _Response:
        if self.transport is not None:
            return _normalise_response(self.transport(url, headers))
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return _Response(response.read(), int(response.status), _headers_dict(response.headers))
        except HTTPError as exc:
            if exc.code == 304:
                return _Response(b"", 304, _headers_dict(exc.headers))
            raise

    def _respect_rate_limit(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self.rate_limit_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at = now


def _normalise_cik(value: object) -> str:
    text = str(value or "").strip().upper().removeprefix("CIK")
    if not text.isdigit() or len(text) > 10:
        raise ValueError("SEC CIK must contain one to ten digits")
    number = int(text)
    if number <= 0:
        raise ValueError("SEC CIK must be positive")
    return text.zfill(10)


def _valid_user_agent(value: str) -> bool:
    match = re.search(r"(?P<email>[^\s@]+@[^\s@]+\.[^\s@]+)$", value)
    if match is None:
        return False
    organisation = value[: match.start()].strip()
    email = match.group("email")
    local, domain = email.rsplit("@", 1)
    domain = domain.lower()
    if len(organisation) < 3 or not re.search(r"[A-Za-z]", organisation):
        return False
    reserved_domains = {"example.com", "example.net", "example.org"}
    if domain in reserved_domains or domain.endswith((".invalid", ".example", ".test", ".localhost")):
        return False
    reserved_domains = ("example.com", "example.net", "example.org")
    if domain in reserved_domains or any(domain.endswith(f".{reserved}") for reserved in reserved_domains):
        return False
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    labels = domain.split(".")
    if len(labels) < 2 or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
        return False
    if not re.fullmatch(r"[A-Za-z]{2,63}", labels[-1]):
        return False
    return True


def _normalise_response(value: Any) -> _Response:
    if isinstance(value, (bytes, bytearray)):
        return _Response(bytes(value), 200, {})
    if isinstance(value, tuple) and len(value) == 3:
        payload, status, headers = value
        return _Response(bytes(payload or b""), int(status), _headers_dict(headers))
    if hasattr(value, "read"):
        payload = value.read()
        return _Response(bytes(payload), int(getattr(value, "status", 200)), _headers_dict(getattr(value, "headers", {})))
    raise TypeError("SEC transport must return bytes, response tuple or response object")


def _headers_dict(value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {str(key): str(item) for key, item in value.items()}
    try:
        return {str(key): str(value[key]) for key in value.keys()}  # type: ignore[union-attr]
    except (AttributeError, KeyError, TypeError):
        return {}


def _parse_json(payload: bytes) -> dict[str, Any]:
    parsed = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("SEC response JSON must be an object")
    return parsed


def _validate_identity(payload: dict[str, Any], expected_cik: str) -> None:
    actual = payload.get("cik", payload.get("cik_str"))
    if actual is None:
        raise ValueError("SEC response is missing CIK identity")
    try:
        actual_cik = _normalise_cik(actual)
    except ValueError as exc:
        raise ValueError("SEC response contains an invalid CIK identity") from exc
    if actual_cik != expected_cik:
        raise ValueError(f"SEC response CIK {actual_cik} does not match requested CIK {expected_cik}")


def _validate_json_file(path: Path, expected_cik: str) -> None:
    _validate_identity(_parse_json(path.read_bytes()), expected_cik)


def _read_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _immutable_cache_path(cache_path: Path, payload_sha: str) -> Path:
    return cache_path.with_name(f"{cache_path.stem}_{payload_sha[:16]}{cache_path.suffix}")


def _ensure_immutable_payload(path: Path, payload: bytes, expected_cik: str) -> None:
    if path.is_file():
        existing = path.read_bytes()
        if _sha256(existing) != _sha256(payload):
            raise ValueError("SEC immutable raw payload checksum mismatch")
        _validate_identity(_parse_json(existing), expected_cik)
        return
    atomic_write_bytes(path, payload, lambda candidate: _validate_json_file(candidate, expected_cik))


def _retrieved_at(metadata: Mapping[str, Any]) -> datetime:
    value = metadata.get("retrieved_at")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("SEC cached metadata retrieved_at is missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("SEC cached metadata retrieved_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("SEC cached metadata retrieved_at must be timezone-aware")
    # Preserve the persisted aware instant and its original offset; 304 is a
    # revalidation, not a new acquisition timestamp.
    return parsed


def _cached_acquisition_status(metadata: Mapping[str, Any]) -> int:
    """Read only a validated acquisition status from the cache metadata."""

    status = metadata.get("status", 200)
    if type(status) is not int or status not in {200, 206}:
        raise ValueError("SEC cached metadata acquisition status is invalid")
    return status


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
