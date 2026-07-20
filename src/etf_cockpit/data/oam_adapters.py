"""Optional, structured national OAM discovery adapters.

The adapters deliberately accept only declared JSON, CSV or XML exports from
allow-listed official hosts.  They never scrape HTML, infer issuer identity
from a page, or make a discovery request unless the caller explicitly enables
an endpoint.  Every response is retained as an immutable local snapshot before
any rows are returned to the application.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
from typing import Literal
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR


OAM_DISCOVERY_PATH = CLEAN_DIR / "oam_discovery.parquet"
FILING_COVERAGE_PATH = CLEAN_DIR / "filing_coverage.parquet"
MANUAL_FILING_QUEUE_PATH = CLEAN_DIR / "manual_filing_queue.parquet"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
MAX_MANUAL_FILING_BYTES = 300 * 1024 * 1024
OAMStatus = Literal["ok", "unavailable", "manual_review", "error"]
Transport = Callable[[str, Mapping[str, str]], object]


@dataclass(frozen=True)
class OAMDiscoveryRequest:
    issuer: str = ""
    isin: str = ""
    date_from: date | None = None
    date_to: date | None = None
    document_type: str = ""
    company_number: str = ""

    def query(self) -> dict[str, str]:
        values = {
            "issuer": self.issuer.strip(),
            "isin": self.isin.strip().upper(),
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
            "document_type": self.document_type.strip(),
            "company_number": self.company_number.strip().upper(),
        }
        return {key: value for key, value in values.items() if value}


@dataclass(frozen=True)
class OAMRecord:
    provider_id: str
    country: str
    issuer: str
    isin: str
    title: str
    document_type: str
    published_at: str | None
    available_at: str | None
    availability_precision: str
    source_url: str
    document_url: str
    source_id: str
    source_authority: str
    terms_url: str
    coverage_status: str
    identity_status: str
    amendment_of: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OAMSnapshot:
    path: str
    source_url: str
    sha256: str
    bytes: int
    media_type: str
    http_status: int
    retrieved_at: str


@dataclass(frozen=True)
class OAMDiscoveryResult:
    provider_id: str
    status: OAMStatus
    message: str
    records: tuple[OAMRecord, ...] = ()
    snapshot: OAMSnapshot | None = None
    coverage: dict[str, object] | None = None
    retry_count: int = 0
    manual_fallback: bool = True
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualFilingArchive:
    jurisdiction: str
    instrument_id: str
    document_type: str
    published_at: str | None
    available_at: str | None
    availability_precision: str
    source_url: str
    source_authority: str
    raw_path: str
    sha256: str
    bytes: int
    identity_status: str
    coverage_status: str
    manual_review: bool
    execution_allowed: bool = False


@dataclass(frozen=True)
class _Response:
    payload: bytes
    status: int
    headers: dict[str, str]


class OAMAdapter:
    """Base contract for one official structured OAM/export endpoint."""

    provider_id: str = "oam"
    country: str = "EU"
    allowed_hosts: tuple[str, ...] = ()
    default_endpoint: str = ""
    terms_url: str = ""

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        endpoint: str | None = None,
        transport: Transport | None = None,
        timeout: float = 20.0,
        retries: int = 2,
        enabled: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0:
            raise ValueError("OAM timeout must be positive")
        if retries < 0 or retries > 3:
            raise ValueError("OAM retries must be between zero and three")
        self.cache_dir = Path(cache_dir or (RAW_DIR / "oam"))
        self.endpoint = str(endpoint or self.default_endpoint).strip()
        self.transport = transport
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.enabled = bool(enabled)
        self.sleep = sleep

    def discover(self, request: OAMDiscoveryRequest | None = None) -> OAMDiscoveryResult:
        request = request or OAMDiscoveryRequest()
        if not self.enabled:
            return self._unavailable("Adapter disabled; use a user-owned import or explicitly enable an official endpoint.")
        try:
            url = self._validated_url(request)
        except ValueError as exc:
            return self._failure("error", str(exc))
        response, retry_count = self._fetch_with_retries(url)
        if response is None:
            return self._unavailable("Official OAM endpoint unavailable; local data was not changed.", retry_count=retry_count)
        snapshot = self._snapshot(url, response)
        try:
            rows = self._parse(response.payload, response.headers.get("content-type", ""))
            records = self._normalise_records(rows, request)
            if not records:
                return OAMDiscoveryResult(
                    self.provider_id,
                    "manual_review",
                    "No unambiguous official OAM records matched the request.",
                    snapshot=snapshot,
                    coverage=self._coverage(0, request, "manual_review"),
                    retry_count=retry_count,
                    warnings=("no_unambiguous_match",),
                )
            ambiguous = self._ambiguous(records, request)
            if ambiguous:
                return OAMDiscoveryResult(
                    self.provider_id,
                    "manual_review",
                    "Multiple issuer records matched; supply an ISIN before selecting a document.",
                    snapshot=snapshot,
                    coverage=self._coverage(len(records), request, "manual_review"),
                    retry_count=retry_count,
                    warnings=("ambiguous_issuer",),
                )
            return OAMDiscoveryResult(
                self.provider_id,
                "ok",
                f"Loaded {len(records)} official {self.country} OAM record(s).",
                records=tuple(records),
                snapshot=snapshot,
                coverage=self._coverage(len(records), request, "ok"),
                retry_count=retry_count,
                manual_fallback=False,
            )
        except (ValueError, ET.ParseError, UnicodeDecodeError, csv.Error) as exc:
            return OAMDiscoveryResult(
                self.provider_id,
                "error",
                f"Official OAM response was not a supported structured export: {type(exc).__name__}.",
                snapshot=snapshot,
                coverage=self._coverage(0, request, "error"),
                retry_count=retry_count,
                warnings=("unsupported_structured_export",),
            )

    def _validated_url(self, request: OAMDiscoveryRequest) -> str:
        if not self.endpoint:
            raise ValueError("No official structured OAM endpoint is configured.")
        parsed = urlparse(self.endpoint)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not host or not self._host_allowed(host):
            raise ValueError("OAM endpoint must be an HTTPS URL on the adapter's official host allowlist.")
        query = dict(request.query())
        existing = dict(parse_qsl(parsed.query, keep_blank_values=False))
        existing.update(query)
        return urlunparse(parsed._replace(query=urlencode(existing)))

    def _host_allowed(self, host: str) -> bool:
        return any(host == allowed or host.endswith("." + allowed) for allowed in self.allowed_hosts)

    def _official_url(self, value: str) -> bool:
        parsed = urlparse(str(value).strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme == "https" and bool(host) and self._host_allowed(host)

    def _fetch_with_retries(self, url: str) -> tuple[_Response | None, int]:
        last_retry = 0
        for attempt in range(self.retries + 1):
            last_retry = attempt
            try:
                response = self._get(url)
                if response.status == 429 or response.status >= 500:
                    if attempt < self.retries:
                        self.sleep(min(2**attempt, 4))
                        continue
                    return None, attempt
                if response.status < 200 or response.status >= 300:
                    return None, attempt
                return response, attempt
            except (OAMUnavailable, TimeoutError, OSError):
                if attempt < self.retries:
                    self.sleep(min(2**attempt, 4))
                    continue
                return None, attempt
        return None, last_retry

    def _get(self, url: str) -> _Response:
        headers = {"User-Agent": "ETF AI Evidence Cockpit/1.0", "Accept": "application/json, text/csv, application/xml"}
        if self.transport is not None:
            return _normalise_response(self.transport(url, headers))
        try:
            with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise OAMUnavailable("OAM response exceeds the bounded response size")
                return _Response(payload, int(getattr(response, "status", 200)), _headers_dict(getattr(response, "headers", {})))
        except (TimeoutError, OSError) as exc:
            raise OAMUnavailable("official OAM endpoint unavailable") from exc

    def _snapshot(self, url: str, response: _Response) -> OAMSnapshot:
        if len(response.payload) > MAX_RESPONSE_BYTES:
            raise ValueError("OAM response exceeds the bounded response size")
        digest = hashlib.sha256(response.payload).hexdigest()
        suffix = self._suffix(response.headers.get("content-type", ""))
        path = self.cache_dir / "snapshots" / f"{self.provider_id}-{digest[:16]}{suffix}"
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("OAM snapshot checksum mismatch")
        if not path.exists():
            atomic_write_bytes(path, response.payload, lambda candidate: _validate_checksum(candidate, digest))
        return OAMSnapshot(str(path), url, digest, len(response.payload), response.headers.get("content-type", ""), response.status, datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @staticmethod
    def _suffix(media_type: str) -> str:
        value = media_type.lower()
        if "xml" in value:
            return ".xml"
        if "csv" in value:
            return ".csv"
        if "pdf" in value:
            return ".pdf"
        if "zip" in value or "xbri" in value:
            return ".bin"
        return ".json"

    def _parse(self, payload: bytes, media_type: str) -> list[Mapping[str, object]]:
        text = payload.decode("utf-8-sig")
        if _looks_like_html(text) or "html" in media_type.lower():
            raise ValueError("HTML scraping is not supported")
        value = media_type.lower()
        if "xml" in value or text.lstrip().startswith("<?xml") or text.lstrip().startswith("<"):
            return _parse_xml(text)
        if "csv" in value or "\n" in text and "," in text.splitlines()[0]:
            return list(csv.DictReader(io.StringIO(text)))
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, Mapping)]
        if not isinstance(parsed, Mapping):
            raise ValueError("OAM JSON export must contain an object or list")
        for key in ("results", "data", "items", "documents", "records"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
        return [parsed]

    def _normalise_records(self, rows: Sequence[Mapping[str, object]], request: OAMDiscoveryRequest) -> list[OAMRecord]:
        normalised: list[OAMRecord] = []
        for raw in rows:
            values = _flatten_attributes(raw)
            issuer = _first(values, "issuer", "issuer_name", "company", "company_name", "entity", "name")
            isin = _first(values, "isin", "identifier", "security_id").upper()
            title = _first(values, "title", "document_title", "name")
            document_type = _first(values, "document_type", "documentType", "type")
            published = _first(values, "published_at", "publication_date", "published", "date", "as_of_date") or None
            available = _first(values, "available_at", "availability_date", "received_at", "processed_at") or published
            availability_precision = _timestamp_precision(available)
            amendment_of = _first(values, "amendment_of", "amends", "replaces", "previous_filing_id")
            source_url = _first(values, "source_url", "source", "url", "link")
            document_url = _first(values, "document_url", "download_url", "file_url", "url", "link")
            if not issuer and not isin:
                continue
            if request.issuer and request.issuer.casefold() not in issuer.casefold():
                continue
            if request.isin and request.isin.strip().upper() != isin:
                continue
            if request.document_type and request.document_type.casefold() not in document_type.casefold():
                continue
            if not _date_in_range(published, request.date_from, request.date_to):
                continue
            source = source_url or self.endpoint
            warnings: tuple[str, ...] = ()
            if not self._official_url(source):
                source = self.endpoint
                warnings = ("untrusted_source_url",)
            if document_url and not self._official_url(document_url):
                document_url = ""
                warnings = (*warnings, "untrusted_document_url")
            if availability_precision == "unavailable":
                warnings = (*warnings, "availability_timestamp_unavailable")
            elif availability_precision == "date":
                warnings = (*warnings, "availability_precision_date")
            source_id = "oam:" + hashlib.sha256("|".join((self.provider_id, source, isin, title, published or "")).encode("utf-8")).hexdigest()[:24]
            identity_status = "matched_isin" if isin else "issuer_only_manual_review"
            normalised.append(
                OAMRecord(
                    provider_id=self.provider_id,
                    country=self.country,
                    issuer=issuer,
                    isin=isin,
                    title=title,
                    document_type=document_type,
                    published_at=published,
                    available_at=available,
                    availability_precision=availability_precision,
                    source_url=source,
                    document_url=document_url,
                    source_id=source_id,
                    source_authority="official_oam",
                    terms_url=self.terms_url,
                    coverage_status="available",
                    identity_status=identity_status,
                    amendment_of=amendment_of,
                    warnings=warnings,
                )
            )
        return list({record.source_id: record for record in normalised}.values())

    @staticmethod
    def _ambiguous(records: Sequence[OAMRecord], request: OAMDiscoveryRequest) -> bool:
        return bool(request.issuer and not request.isin and len({record.isin or record.source_id for record in records}) > 1)

    @staticmethod
    def _coverage(count: int, request: OAMDiscoveryRequest, status: str) -> dict[str, object]:
        return {"status": status, "matched_records": count, "query": request.query(), "source_authority": "official_oam"}

    def _unavailable(self, message: str, *, retry_count: int = 0) -> OAMDiscoveryResult:
        return OAMDiscoveryResult(self.provider_id, "unavailable", message, retry_count=retry_count, manual_fallback=True, warnings=("manual_fallback_available",))

    def _failure(self, status: OAMStatus, message: str) -> OAMDiscoveryResult:
        return OAMDiscoveryResult(self.provider_id, status, message, manual_fallback=True, warnings=("manual_fallback_available",))


class FranceDilaOamAdapter(OAMAdapter):
    provider_id = "fr_dila_oam"
    country = "FR"
    allowed_hosts = ("data.gouv.fr",)
    default_endpoint = "https://www.data.gouv.fr/fr/dataservices/api-info-financiere/"
    terms_url = "https://www.data.gouv.fr/fr/dataservices/api-info-financiere/"


class NetherlandsAfmOamAdapter(OAMAdapter):
    provider_id = "nl_afm_oam"
    country = "NL"
    allowed_hosts = ("afm.nl",)
    default_endpoint = "https://www.afm.nl/en/sector/registers/meldingenregisters/financiele-verslaggeving"
    terms_url = "https://www.afm.nl/en/sector/registers/meldingenregisters/financiele-verslaggeving"


class DenmarkFinanstilsynetOamAdapter(OAMAdapter):
    provider_id = "dk_finanstilsynet_oam"
    country = "DK"
    allowed_hosts = ("finanstilsynet.dk",)
    terms_url = "https://www.finanstilsynet.dk/finansielle-temaer/kapitalmarked/indberetninger-til-finanstilsynet-via-oam-systemet"


class SwedenFiOamAdapter(OAMAdapter):
    provider_id = "se_fi_oam"
    country = "SE"
    allowed_hosts = ("fi.se",)
    terms_url = "https://www.fi.se/en/markets/issuers/periodic-financial-information/"


class FinlandFsaOamAdapter(OAMAdapter):
    provider_id = "fi_fsa_oam"
    country = "FI"
    allowed_hosts = ("finanssivalvonta.fi",)
    terms_url = "https://www.finanssivalvonta.fi/en/capital-markets/issuers-and-investors/"


class NorwayFinanstilsynetOamAdapter(OAMAdapter):
    provider_id = "no_finanstilsynet_oam"
    country = "NO"
    allowed_hosts = ("finanstilsynet.no",)
    terms_url = "https://www.finanstilsynet.no/en/"


class CompaniesHouseFilingAdapter(OAMAdapter):
    """Read one UK company filing-history endpoint with an explicit API key."""

    provider_id = "gb_companies_house"
    country = "GB"
    allowed_hosts = ("company-information.service.gov.uk", "companieshouse.gov.uk")
    default_endpoint = "https://api.company-information.service.gov.uk"
    terms_url = "https://developer.company-information.service.gov.uk/"

    def __init__(self, *, api_key: str = "", **kwargs: object) -> None:
        self.api_key = str(api_key or "")
        super().__init__(**kwargs)

    def discover(self, request: OAMDiscoveryRequest | None = None) -> OAMDiscoveryResult:
        request = request or OAMDiscoveryRequest()
        if self.transport is None and not self.api_key:
            return self._unavailable(
                "Companies House API authentication is absent; use the official accounts bulk file or manual official import."
            )
        return super().discover(request)

    def _validated_url(self, request: OAMDiscoveryRequest) -> str:
        company_number = str(request.company_number or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,8}", company_number):
            raise ValueError("Companies House discovery requires a valid company number.")
        parsed = urlparse(self.endpoint or self.default_endpoint)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or host != "api.company-information.service.gov.uk":
            raise ValueError("Companies House endpoint must use its official HTTPS API host.")
        path = f"/company/{quote(company_number)}/filing-history"
        query = {"items_per_page": "100"}
        if request.document_type:
            query["category"] = request.document_type.strip()
        return urlunparse(parsed._replace(path=path, query=urlencode(query), fragment=""))

    def _get(self, url: str) -> _Response:
        headers = {"User-Agent": "ETF AI Evidence Cockpit/1.0", "Accept": "application/json"}
        if self.api_key:
            token = base64.b64encode(f"{self.api_key}:".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        if self.transport is not None:
            return _normalise_response(self.transport(url, headers))
        try:
            with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise OAMUnavailable("Companies House response exceeds the bounded response size")
                return _Response(
                    payload,
                    int(getattr(response, "status", 200)),
                    _headers_dict(getattr(response, "headers", {})),
                )
        except (TimeoutError, OSError) as exc:
            raise OAMUnavailable("Companies House endpoint unavailable") from exc

    def _normalise_records(
        self,
        rows: Sequence[Mapping[str, object]],
        request: OAMDiscoveryRequest,
    ) -> list[OAMRecord]:
        company_number = request.company_number.strip().upper()
        source_url = self._validated_url(request)
        records: list[OAMRecord] = []
        for raw in rows:
            values = _flatten_attributes(raw)
            transaction_id = _first(values, "transaction_id", "id", "barcode")
            published = _first(values, "date", "filed_at") or None
            category = _first(values, "category", "type")
            description = _first(values, "description", "description_values", "type")
            if request.document_type and request.document_type.casefold() not in category.casefold():
                continue
            if not _date_in_range(published, request.date_from, request.date_to):
                continue
            links = raw.get("links")
            metadata_path = str(links.get("document_metadata") or "") if isinstance(links, Mapping) else ""
            document_url = ""
            if metadata_path:
                metadata_url = urljoin("https://document-api.company-information.service.gov.uk", metadata_path)
                document_url = metadata_url.rstrip("/") + "/content"
                if not self._official_url(document_url):
                    document_url = ""
            available = _first(values, "available_at") or published
            precision = _timestamp_precision(available)
            warnings = ("availability_precision_date",) if precision == "date" else ()
            if not transaction_id:
                warnings = (*warnings, "transaction_identity_unavailable")
            source_id = "companies-house:" + hashlib.sha256(
                "|".join((company_number, transaction_id, published or "", description)).encode("utf-8")
            ).hexdigest()[:24]
            records.append(
                OAMRecord(
                    provider_id=self.provider_id,
                    country=self.country,
                    issuer=company_number,
                    isin="",
                    title=description,
                    document_type=category,
                    published_at=published,
                    available_at=available,
                    availability_precision=precision,
                    source_url=source_url,
                    document_url=document_url,
                    source_id=source_id,
                    source_authority="official_companies_house",
                    terms_url=self.terms_url,
                    coverage_status="available",
                    identity_status="matched_company_number",
                    amendment_of="",
                    warnings=warnings,
                )
            )
        return list({record.source_id: record for record in records}.values())


OAM_ADAPTERS_BY_COUNTRY: dict[str, type[OAMAdapter]] = {
    "DK": DenmarkFinanstilsynetOamAdapter,
    "FI": FinlandFsaOamAdapter,
    "FR": FranceDilaOamAdapter,
    "GB": CompaniesHouseFilingAdapter,
    "NL": NetherlandsAfmOamAdapter,
    "NO": NorwayFinanstilsynetOamAdapter,
    "SE": SwedenFiOamAdapter,
}


def oam_adapter_for_country(country: str) -> type[OAMAdapter]:
    country_code = str(country or "").strip().upper()
    try:
        return OAM_ADAPTERS_BY_COUNTRY[country_code]
    except KeyError as exc:
        supported = ", ".join(sorted(OAM_ADAPTERS_BY_COUNTRY))
        raise ValueError(f"OAM country must be one of: {supported}") from exc


def download_oam_document(
    record: OAMRecord,
    *,
    cache_dir: Path | None = None,
    transport: Transport | None = None,
    timeout: float = 20.0,
) -> OAMSnapshot:
    """Retain one discovered official document without parsing or publishing it."""

    if not record.document_url:
        raise ValueError("OAM record does not contain a document URL")
    adapter_type = {
        adapter_type.provider_id: adapter_type
        for adapter_type in OAM_ADAPTERS_BY_COUNTRY.values()
    }.get(record.provider_id)
    if adapter_type is None:
        raise ValueError("OAM record provider is not supported")
    adapter = adapter_type(cache_dir=cache_dir, endpoint=record.document_url, transport=transport, timeout=timeout, enabled=True)
    url = record.document_url
    if not adapter._official_url(url):
        raise ValueError("OAM document URL must use the provider's official HTTPS host.")
    response, retry_count = adapter._fetch_with_retries(url)
    if response is None:
        raise OAMUnavailable(f"{record.provider_id} document unavailable after {retry_count} retry attempt(s)")
    return adapter._snapshot(url, response)


def write_oam_discovery_registry(result: OAMDiscoveryResult, *, destination: Path = OAM_DISCOVERY_PATH) -> Path:
    """Write only successful, evidence-labelled discovery rows locally."""

    rows = [asdict(record) for record in result.records]
    frame = pd.DataFrame(rows, columns=list(OAMRecord.__dataclass_fields__))
    if result.snapshot is not None:
        frame["snapshot_path"] = result.snapshot.path
        frame["snapshot_sha256"] = result.snapshot.sha256
        frame["retrieved_at"] = result.snapshot.retrieved_at
    else:
        frame["snapshot_path"] = None
        frame["snapshot_sha256"] = None
        frame["retrieved_at"] = None
    frame["adapter_status"] = result.status
    frame["manual_fallback"] = result.manual_fallback
    frame["coverage_json"] = json.dumps(result.coverage or {}, sort_keys=True)
    frame["warnings"] = frame["warnings"].map(lambda value: list(value) if isinstance(value, tuple) else value) if not frame.empty else pd.Series(dtype=object)
    destination = Path(destination)
    _write_parquet_atomic(frame, destination)
    return destination


def write_filing_coverage(
    result: OAMDiscoveryResult,
    *,
    country: str,
    request: OAMDiscoveryRequest,
    destination: Path = FILING_COVERAGE_PATH,
) -> Path:
    """Upsert one successful or unavailable jurisdiction coverage observation."""

    query = request.query()
    query_sha256 = hashlib.sha256(json.dumps(query, sort_keys=True).encode("utf-8")).hexdigest()
    row = {
        "provider_id": result.provider_id,
        "country": str(country).strip().upper(),
        "instrument_identity": request.isin.strip().upper() or request.company_number.strip().upper(),
        "issuer": request.issuer.strip(),
        "query_sha256": query_sha256,
        "status": result.status,
        "matched_records": len(result.records),
        "official_records": sum(record.source_authority.startswith("official") for record in result.records),
        "identity_matched_records": sum(record.identity_status.startswith("matched") for record in result.records),
        "available_at_records": sum(bool(record.available_at) for record in result.records),
        "manual_fallback": result.manual_fallback,
        "snapshot_sha256": result.snapshot.sha256 if result.snapshot else None,
        "snapshot_path": result.snapshot.path if result.snapshot else None,
        "retrieved_at": result.snapshot.retrieved_at if result.snapshot else datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message": result.message,
        "warnings": json.dumps(list(result.warnings), separators=(",", ":")),
        "execution_allowed": False,
    }
    destination = Path(destination)
    existing = _read_parquet_or_empty(destination)
    combined = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    combined = combined.drop_duplicates(["provider_id", "query_sha256"], keep="last")
    combined = combined.sort_values(["country", "provider_id", "instrument_identity", "query_sha256"], kind="stable")
    _write_parquet_atomic(combined, destination)
    return destination


_OFFICIAL_FILING_HOSTS: dict[str, tuple[str, ...]] = {
    adapter.country: adapter.allowed_hosts for adapter in OAM_ADAPTERS_BY_COUNTRY.values()
}
_OFFICIAL_FILING_HOSTS["EU"] = ("filings.xbrl.org",)
_MANUAL_SUFFIXES = frozenset({".csv", ".html", ".json", ".pdf", ".xbrl", ".xbri", ".xhtml", ".xml", ".zip"})


def archive_manual_official_filing(
    source_path: Path,
    *,
    jurisdiction: str,
    instrument_id: str,
    source_url: str,
    document_type: str = "annual_report",
    published_at: str | None = None,
    available_at: str | None = None,
    raw_dir: Path | None = None,
    queue_path: Path = MANUAL_FILING_QUEUE_PATH,
) -> ManualFilingArchive:
    """Archive a user-owned official filing without parsing or score authority."""

    path = Path(source_path)
    if not path.is_file():
        raise ValueError("Manual official filing import requires a readable local file.")
    suffix = path.suffix.casefold()
    if suffix not in _MANUAL_SUFFIXES:
        raise ValueError("Manual official filing type is not supported.")
    with path.open("rb") as stream:
        payload = stream.read(MAX_MANUAL_FILING_BYTES + 1)
    size = len(payload)
    if size <= 0 or size > MAX_MANUAL_FILING_BYTES:
        raise ValueError("Manual official filing size is empty or exceeds the bounded limit.")
    country = str(jurisdiction or "").strip().upper()
    hosts = _OFFICIAL_FILING_HOSTS.get(country)
    if not hosts:
        raise ValueError("Manual filing jurisdiction is not supported.")
    parsed_url = urlparse(str(source_url or "").strip())
    host = (parsed_url.hostname or "").lower().rstrip(".")
    if parsed_url.scheme != "https" or not any(host == allowed or host.endswith("." + allowed) for allowed in hosts):
        raise ValueError("Manual filing source URL must use the jurisdiction's official HTTPS host.")
    canonical_instrument = str(instrument_id or "").strip()
    if not canonical_instrument:
        raise ValueError("Manual filing import requires a canonical instrument identity.")
    publication, publication_precision = _normalise_optional_timestamp(published_at)
    availability, availability_precision = _normalise_optional_timestamp(available_at or published_at)
    digest = hashlib.sha256(payload).hexdigest()
    destination = Path(raw_dir or (RAW_DIR / "filings" / "manual")) / country / f"{digest}{suffix}"
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError("Manual filing immutable archive checksum mismatch.")
    if not destination.exists():
        atomic_write_bytes(destination, payload, lambda candidate: _validate_checksum(candidate, digest))
    identity_status = "matched_canonical_instrument"
    coverage_status = "archived_manual_review" if availability else "archived_timing_unavailable"
    record = ManualFilingArchive(
        jurisdiction=country,
        instrument_id=canonical_instrument,
        document_type=str(document_type or "annual_report").strip(),
        published_at=publication,
        available_at=availability,
        availability_precision=availability_precision or publication_precision,
        source_url=str(source_url).strip(),
        source_authority="official_manual_import",
        raw_path=str(destination),
        sha256=digest,
        bytes=size,
        identity_status=identity_status,
        coverage_status=coverage_status,
        manual_review=True,
    )
    queue = Path(queue_path)
    existing = _read_parquet_or_empty(queue)
    combined = pd.concat([existing, pd.DataFrame([asdict(record)])], ignore_index=True)
    combined = combined.drop_duplicates(["jurisdiction", "instrument_id", "sha256"], keep="last")
    combined = combined.sort_values(["jurisdiction", "instrument_id", "published_at", "sha256"], kind="stable")
    _write_parquet_atomic(combined, queue)
    return record


class OAMUnavailable(RuntimeError):
    """The bounded official OAM request could not be completed."""


def _validate_checksum(path: Path, expected: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise OAMUnavailable("OAM snapshot checksum validation failed")


def _normalise_response(value: object) -> _Response:
    if isinstance(value, (bytes, bytearray)):
        return _Response(bytes(value), 200, {})
    if isinstance(value, tuple) and len(value) == 3:
        payload, status, headers = value
        return _Response(bytes(payload or b""), int(status), _headers_dict(headers))
    if hasattr(value, "read"):
        payload = value.read(MAX_RESPONSE_BYTES + 1)
        return _Response(bytes(payload), int(getattr(value, "status", 200)), _headers_dict(getattr(value, "headers", {})))
    raise TypeError("OAM transport must return bytes, response tuple or response object")


def _headers_dict(value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {str(key).lower(): str(item) for key, item in value.items()}
    try:
        return {str(key).lower(): str(value[key]) for key in value.keys()}  # type: ignore[union-attr]
    except (AttributeError, KeyError, TypeError):
        return {}


def _flatten_attributes(raw: Mapping[str, object]) -> dict[str, object]:
    values = dict(raw)
    for key in ("attributes", "fields", "metadata"):
        nested = values.get(key)
        if isinstance(nested, Mapping):
            values = {**values, **nested}
    return {re.sub(r"(?<!^)(?=[A-Z])", "_", str(key).strip()).lower().replace("-", "_"): value for key, value in values.items()}


def _first(values: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = values.get(key.lower().replace("-", "_"))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _parse_xml(text: str) -> list[Mapping[str, object]]:
    root = ET.fromstring(text)
    rows: list[Mapping[str, object]] = []
    for element in root.iter():
        children = list(element)
        if not children:
            continue
        values: dict[str, object] = {}
        for child in children:
            key = child.tag.rsplit("}", 1)[-1]
            values[key] = (child.text or "").strip()
        if any(key.casefold() in {"issuer", "issuername", "company", "isin", "identifier"} for key in values):
            rows.append(values)
    if not rows:
        raise ValueError("XML export contains no structured filing records")
    return rows


def _looks_like_html(text: str) -> bool:
    start = text.lstrip().casefold()
    return start.startswith("<!doctype html") or start.startswith("<html") or "<html" in start[:512]


def _date_in_range(value: str | None, start: date | None, end: date | None) -> bool:
    if not start and not end:
        return True
    if not value:
        return False
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return False
    return (not start or parsed >= start) and (not end or parsed <= end)


def _timestamp_precision(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "unavailable"
    try:
        parsed = pd.to_datetime(text, errors="raise", utc=True)
    except (TypeError, ValueError):
        return "unavailable"
    if pd.isna(parsed):
        return "unavailable"
    return "timestamp" if "T" in text or ":" in text else "date"


def _normalise_optional_timestamp(value: str | None) -> tuple[str | None, str]:
    text = str(value or "").strip()
    if not text:
        return None, "unavailable"
    precision = _timestamp_precision(text)
    if precision == "unavailable":
        raise ValueError("Filing publication and availability timestamps must be valid and not in the future.")
    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed) or parsed > pd.Timestamp.now(tz="UTC"):
        raise ValueError("Filing publication and availability timestamps must be valid and not in the future.")
    return text, precision


def _read_parquet_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError):
        raise ValueError(f"Existing filing registry is unreadable: {path.name}") from None


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    payload = buffer.getvalue()

    def validate(candidate: Path) -> None:
        persisted = pd.read_parquet(candidate)
        if list(persisted.columns) != list(frame.columns) or len(persisted) != len(frame):
            raise ValueError("Filing registry write verification failed.")

    atomic_write_bytes(path, payload, validate)


__all__ = [
    "CompaniesHouseFilingAdapter",
    "DenmarkFinanstilsynetOamAdapter",
    "FILING_COVERAGE_PATH",
    "FinlandFsaOamAdapter",
    "FranceDilaOamAdapter",
    "MANUAL_FILING_QUEUE_PATH",
    "ManualFilingArchive",
    "NetherlandsAfmOamAdapter",
    "NorwayFinanstilsynetOamAdapter",
    "OAMAdapter",
    "OAM_ADAPTERS_BY_COUNTRY",
    "OAMDiscoveryRequest",
    "OAMDiscoveryResult",
    "OAMRecord",
    "OAMSnapshot",
    "OAM_DISCOVERY_PATH",
    "SwedenFiOamAdapter",
    "archive_manual_official_filing",
    "download_oam_document",
    "oam_adapter_for_country",
    "write_filing_coverage",
    "write_oam_discovery_registry",
]
