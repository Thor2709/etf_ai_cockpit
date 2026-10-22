"""Bounded filings.xbrl.org acquisition adapter for ESEF packages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.http_fetch import get_checked
from etf_cockpit.core.values import string_dict_or_empty as _headers_dict
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.parsers.contracts import RawDocument, load_fixture_manifest
from etf_cockpit.data.providers import ProviderResult


Transport = Callable[[str, dict[str, str]], object]
BASE_URL = "https://filings.xbrl.org"
MAX_RESPONSE_BYTES = 300 * 1024 * 1024


def parse_reported_shares(facts: pd.DataFrame, *, source_ref: str) -> list[dict[str, Any]]:
    """Only named, consolidated, undimensioned outstanding-share instant facts.

    Require ``filed`` or registry ``date_added``: imported ``known_at`` alone
    can be acquisition time and does not prove publication. Preserve each filing
    separately. Weighted averages, issued shares and EPS are ineligible.
    """
    from etf_cockpit.analysis.stock_metrics import as_utc

    grouped: dict[tuple[str, str, str, str], list[float | None]] = {}
    for fact in facts.to_dict("records"):
        if (str(fact.get("taxonomy")) != "ifrs-full"
                or str(fact.get("concept")) != "NumberOfSharesOutstanding"
                or str(fact.get("consolidation_scope")) != "consolidated"
                or str(fact.get("unit")) != "shares"):
            continue
        dimensions = fact.get("dimensions")
        if dimensions is not None and not (isinstance(dimensions, str) and dimensions in ("", "{}")) and dimensions != {}:
            continue
        start = fact.get("start")
        if start is not None and pd.notna(start) and str(start):
            continue
        instant = fact.get("instant")
        if instant is None or pd.isna(instant) or not str(instant):
            instant = fact.get("end")
        end, known = as_utc(instant), as_utc(fact.get("known_at"))
        published = as_utc(fact.get("filed")) or as_utc(fact.get("date_added"))
        if end is None or known is None or published is None or end.date() > published.date():
            continue
        value = pd.to_numeric(fact.get("value"), errors="coerce")
        valid = pd.notna(value) and float("-inf") < value < float("inf") and value > 0 and not isinstance(fact.get("value"), bool)
        reference = fact.get("source_id")
        reference = str(reference) if reference is not None and pd.notna(reference) else source_ref
        key = (end.date().isoformat(), published.isoformat(), max(known, published).isoformat(), reference)
        grouped.setdefault(key, []).append(float(value) if valid else None)
    rows = []
    for (end, published, known, reference), values in sorted(grouped.items()):
        usable = None not in values and len(set(values)) == 1
        rows.append({
            "period_end": end, "period_type": "SHARES", "fiscal_year": int(end[:4]),
            "currency": "", "source": "esef_reported", "source_ref": reference,
            "known_at": known, "available_at": published,
            "shares_outstanding": values[0] if usable else None,
            "value_status": json.dumps({"shares_outstanding": "observed" if usable else "conflicted"}),
        })
    return rows


def fetch_stock_fundamentals(
    instrument_id: str, config: Mapping[str, Any], *, root: Path | None = None,
    facts: pd.DataFrame | None = None,
) -> Any:
    """Read the rooted canonical fact store once for statements and reported counts."""
    from etf_cockpit.core.paths import STATEMENT_FACTS_PATH
    from etf_cockpit.data import stock_sources as src

    if facts is None:
        path = Path(root) / "data" / "clean" / "statement_facts.parquet" if root else Path(STATEMENT_FACTS_PATH)
        if not path.exists():
            return src.FetchResult("esef", status="unavailable", reason=f"no ESEF statement facts store at {path}")
        try:
            facts = pd.read_parquet(path)
        except Exception as exc:
            return src.FetchResult("esef", status="error", reason=f"ESEF statement facts store unreadable: {str(exc)[:120]}")
    result = src.fetch_esef(instrument_id, config, facts=facts)
    if "instrument_id" in facts.columns:
        own = facts[facts["instrument_id"].astype(str) == str(instrument_id)]
        reported = parse_reported_shares(own, source_ref=f"esef:filings_xbrl_org:{instrument_id}")
        result.rows.extend(reported)
        if reported and result.status == "no_statements":
            result.status, result.reason = "ok", ""
    return result


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

    def download_report_package(
        self,
        filing_id: str,
        package_url: str | None = None,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> RawDocument:
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
            with publication_scope(publish_guard):
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
        def allowed(address: str) -> bool:
            parsed = urlparse(address)
            return parsed.scheme == "https" and parsed.hostname == "filings.xbrl.org"

        try:
            payload, status, response_headers = get_checked(
                url, allowed=allowed, headers=headers, timeout=self.timeout, max_bytes=MAX_RESPONSE_BYTES
            )
        except (TimeoutError, OSError, ValueError) as exc:
            raise EsefProviderUnavailable("official ESEF endpoint unavailable") from exc
        return _Response(payload, status, _headers_dict(response_headers))


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
