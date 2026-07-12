"""Bounded filings.xbrl.org acquisition adapter for ESEF packages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.parsers.contracts import RawDocument, load_fixture_manifest
from etf_cockpit.data.providers import ProviderResult


Transport = Callable[[str, dict[str, str]], object]
BASE_URL = "https://filings.xbrl.org"
MAX_RESPONSE_BYTES = 300 * 1024 * 1024


class EsefProviderUnavailable(RuntimeError):
    """The official ESEF endpoint was unavailable within the bounded request."""


@dataclass(frozen=True)
class _Response:
    payload: bytes
    status: int
    headers: dict[str, str]


class FilingsXbrlOrgProvider:
    def __init__(
        self,
        *,
        cache_dir: Path,
        transport: Transport | None = None,
        timeout: float = 20.0,
        fixture_manifest: Path | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("ESEF provider timeout must be positive")
        self.cache_dir = Path(cache_dir)
        self.transport = transport
        self.timeout = float(timeout)
        self.fixture_manifest = Path(fixture_manifest) if fixture_manifest is not None else None
        self._filings: dict[str, dict[str, object]] = {}

    def list_filings(self, country: str, limit: int = 10) -> ProviderResult:
        country_code = str(country or "").strip().upper()
        if not country_code.isalpha() or not 2 <= len(country_code) <= 3:
            return ProviderResult("filings_xbrl_org", "filings", "error", "Country must be a two- or three-letter code.", pd.DataFrame())
        bounded_limit = max(1, min(int(limit), 100))
        url = f"{BASE_URL}/api/filings?filter[country]={quote(country_code)}&sort=-processed&page[size]={bounded_limit}"
        if self.transport is None and self.fixture_manifest is not None:
            fixture_result = self._fixture_list(country_code, bounded_limit)
            if fixture_result is not None:
                return fixture_result
        try:
            response = self._get(url)
            if response.status < 200 or response.status >= 300:
                raise EsefProviderUnavailable(f"official endpoint returned HTTP {response.status}")
            parsed = json.loads(response.payload.decode("utf-8"))
            rows = parsed.get("data", []) if isinstance(parsed, dict) else parsed
            if not isinstance(rows, list):
                raise ValueError("filings response data must be a list")
            frame = _flatten_rows(rows)
            self._filings = _index_filings(frame)
            return ProviderResult("filings_xbrl_org", "filings", "ok", f"Loaded {len(frame)} official filings.", data=frame)
        except (EsefProviderUnavailable, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return ProviderResult("filings_xbrl_org", "filings", "unavailable" if isinstance(exc, (EsefProviderUnavailable, TimeoutError, OSError)) else "error", f"Official filings discovery unavailable: {type(exc).__name__}", pd.DataFrame())

    def _fixture_list(self, country: str, limit: int) -> ProviderResult | None:
        try:
            fixtures = load_fixture_manifest(self.fixture_manifest)  # type: ignore[arg-type]
            api_fixture = next(item for item in fixtures if item.document_type == "esef_api_response")
            parsed = json.loads(api_fixture.path.read_text(encoding="utf-8"))
            rows = parsed.get("data", []) if isinstance(parsed, dict) else []
            frame = _flatten_rows(rows)
            if "country" in frame.columns:
                frame = frame[frame["country"].astype(str).str.upper() == country]
            frame = frame.head(limit).reset_index(drop=True)
            self._filings = _index_filings(frame)
            return ProviderResult("filings_xbrl_org", "filings", "ok", f"Loaded {len(frame)} retained official fixture filings.", data=frame)
        except (OSError, StopIteration, ValueError, json.JSONDecodeError):
            return None

    def download_report_package(self, filing_id: str, package_url: str | None = None) -> RawDocument:
        safe_id = _validate_filing_id(filing_id)
        selected_url = package_url or str(self._filings.get(safe_id, {}).get("package_url") or "")
        fixture_payload = self._fixture_package(safe_id)
        if fixture_payload is not None:
            selected_url, payload, status = fixture_payload
        else:
            if not selected_url:
                raise EsefProviderUnavailable("filing ID was not returned by discovery and has no package URL")
            selected_url = _safe_package_url(selected_url)
            response = self._get(selected_url)
            if response.status < 200 or response.status >= 300:
                raise EsefProviderUnavailable(f"official package endpoint returned HTTP {response.status}")
            payload, status = response.payload, response.status
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("ESEF report package exceeds the download size limit")
        digest = hashlib.sha256(payload).hexdigest()
        immutable_path = self.cache_dir / "immutable" / f"{safe_id}_{digest[:16]}.xbri"
        if immutable_path.exists() and hashlib.sha256(immutable_path.read_bytes()).hexdigest() != digest:
            raise ValueError("ESEF immutable raw payload checksum mismatch")
        if not immutable_path.exists():
            atomic_write_bytes(immutable_path, payload, lambda _candidate: None)
        return RawDocument(immutable_path, selected_url, datetime.now(timezone.utc), digest, "filings_xbrl_org", "esef_report_package", "application/octet-stream", status)

    def _fixture_package(self, filing_id: str) -> tuple[str, bytes, int] | None:
        manifest_path = self.fixture_manifest
        if manifest_path is None or not manifest_path.exists():
            return None
        try:
            fixtures = load_fixture_manifest(manifest_path)
            package = next((item for item in fixtures if item.document_type == "esef_report_package" and item.entity == filing_id), None)
            if package is None:
                api_fixture = next(item for item in fixtures if item.document_type == "esef_api_response")
                api_payload = json.loads(api_fixture.path.read_text(encoding="utf-8"))
                selected_entity = next(
                    str(item.get("attributes", {}).get("fxo_id", ""))
                    for item in api_payload.get("data", [])
                    if str(item.get("id", "")) == filing_id
                )
                package = next(item for item in fixtures if item.document_type == "esef_report_package" and item.entity == selected_entity)
        except (OSError, StopIteration, ValueError, json.JSONDecodeError):
            return None
        payload = package.path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != package.sha256:
            raise ValueError("ESEF fixture checksum mismatch")
        return package.source_url, payload, 200

    def _get(self, url: str) -> _Response:
        headers = {"User-Agent": "ETF AI Evidence Cockpit/1.0", "Accept": "application/json"}
        if self.transport is not None:
            return _normalise_response(self.transport(url, headers))
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                return _Response(payload, int(getattr(response, "status", 200)), _headers_dict(getattr(response, "headers", {})))
        except (TimeoutError, OSError) as exc:
            raise EsefProviderUnavailable("official ESEF endpoint unavailable") from exc


def _flatten_rows(rows: list[object]) -> pd.DataFrame:
    flattened: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes")
        values = dict(attrs) if isinstance(attrs, dict) else {}
        values["id"] = str(row.get("id") or "")
        links = row.get("links")
        if isinstance(links, dict) and links.get("self"):
            values["self_url"] = str(links["self"])
        if values.get("package_url"):
            values["package_url"] = _safe_package_url(str(values["package_url"]))
        flattened.append(values)
    columns = sorted({key for row in flattened for key in row})
    return pd.DataFrame(flattened, columns=columns)


def _index_filings(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for row in frame.to_dict(orient="records"):
        for key in ("fxo_id", "id"):
            value = str(row.get(key, "")).strip()
            if value:
                indexed[value] = row
    return indexed


def _validate_filing_id(value: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text or ":" in text or "\x00" in text:
        raise ValueError("filing_id must be a safe single path component")
    return text


def _safe_package_url(value: str) -> str:
    url = urljoin(BASE_URL, str(value).strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "filings.xbrl.org" or not parsed.path.lower().endswith((".xbri", ".zip")):
        raise ValueError("ESEF package URL must be an HTTPS filings.xbrl.org .xbri/.zip URL")
    return url


def _normalise_response(value: object) -> _Response:
    if isinstance(value, (bytes, bytearray)):
        return _Response(bytes(value), 200, {})
    if isinstance(value, tuple) and len(value) == 3:
        payload, status, headers = value
        return _Response(bytes(payload or b""), int(status), _headers_dict(headers))
    if hasattr(value, "read"):
        payload = value.read(MAX_RESPONSE_BYTES + 1)
        return _Response(bytes(payload), int(getattr(value, "status", 200)), _headers_dict(getattr(value, "headers", {})))
    raise TypeError("ESEF transport must return bytes, response tuple or response object")


def _headers_dict(value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {str(key): str(item) for key, item in value.items()}
    try:
        return {str(key): str(value[key]) for key in value.keys()}  # type: ignore[union-attr]
    except (AttributeError, KeyError, TypeError):
        return {}
