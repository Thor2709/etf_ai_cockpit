"""Small, keyless SEC EDGAR acquisition adapter.

The provider deliberately owns only acquisition and immutable raw-cache
provenance.  Parsing and canonical mapping live in :mod:`sec_facts`; no
network response is allowed to bypass the identity and JSON checks here.
"""

from __future__ import annotations

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


class SecEdgarProvider:
    """Fetch SEC submissions/companyfacts using a deterministic local cache.

    ``transport`` is injectable for offline tests and may return bytes, a
    ``(bytes, status, headers)`` tuple, or an object exposing ``read``,
    ``status`` and ``headers`` like an ``urllib`` response.
    """

    BASE_URL = "https://data.sec.gov"

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

    def fetch_companyfacts(
        self,
        cik: str,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> RawDocument:
        cik_text = _normalise_cik(cik)
        return self._fetch(
            f"{self.BASE_URL}/api/xbrl/companyfacts/CIK{cik_text}.json",
            f"companyfacts_{cik_text}.json",
            "sec_companyfacts",
            cik_text,
            publish_guard=publish_guard,
        )

    def fetch_submissions(
        self,
        cik: str,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> RawDocument:
        cik_text = _normalise_cik(cik)
        return self._fetch(
            f"{self.BASE_URL}/submissions/CIK{cik_text}.json",
            f"submissions_{cik_text}.json",
            "sec_submissions",
            cik_text,
            publish_guard=publish_guard,
        )

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
        if cache_path.is_file():
            if metadata.get("etag"):
                headers["If-None-Match"] = str(metadata["etag"])
            if metadata.get("last_modified"):
                headers["If-Modified-Since"] = str(metadata["last_modified"])

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self._request(url, headers)
                if response.status == 304:
                    if not cache_path.is_file():
                        raise ValueError("SEC returned 304 but no cached document exists")
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
                    return RawDocument(
                        immutable_path,
                        url,
                        retrieved_at,
                        cached_sha,
                        "sec_edgar",
                        document_type,
                        "application/json",
                        304,
                    )
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
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                }
                with publication_scope(publish_guard):
                    atomic_write_json(metadata_path, next_metadata)
                return RawDocument(
                    immutable_path,
                    url,
                    retrieved_at,
                    next_metadata["sha256"],
                    "sec_edgar",
                    document_type,
                    "application/json",
                    response.status,
                )
            except (HTTPError, URLError, TimeoutError, OSError, SecEdgarUnavailable) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise SecEdgarUnavailable(f"SEC request unavailable after {attempt + 1} attempt(s)") from exc
                self._sleep(min(2.0, 0.25 * (2**attempt)))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                # A bad payload is not retried and never replaces the cache.
                raise ValueError(f"SEC response JSON validation failed: {exc}") from exc
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
