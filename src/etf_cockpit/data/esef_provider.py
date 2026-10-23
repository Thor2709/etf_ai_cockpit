"""Bounded filings.xbrl.org acquisition adapter for ESEF packages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from decimal import Decimal, InvalidOperation
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
_TRANSIENT_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_RESPONSE_BYTES = 300 * 1024 * 1024


def parse_reported_shares(facts: pd.DataFrame, *, source_ref: str) -> list[dict[str, Any]]:
    """Prefer DEI shares; otherwise require matching IFRS outstanding and treasury facts.

    Require ``filed`` or registry ``date_added``: imported ``known_at`` alone
    can be acquisition time and does not prove publication. Preserve each filing
    separately. Conflicting facts and missing treasury shares are unavailable.
    Weighted averages, issued shares and EPS are ineligible.
    """
    from etf_cockpit.analysis.stock_metrics import as_utc

    # Filter missing dimensions before to_dict converts pd.NA to undimensioned None.
    if "dimensions" in facts:
        facts = facts.loc[facts["dimensions"].map(
            lambda value: value is None or not (pd.api.types.is_scalar(value) and pd.isna(value))
        )]

    def fact_text(value: object) -> str:
        if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
            return ""
        return str(value)

    grouped: dict[tuple[str, str, str, str], dict[str, list[tuple[Decimal | None, str]]]] = {}
    for fact in facts.to_dict("records"):
        taxonomy = fact_text(fact.get("taxonomy")).casefold()
        concept = fact_text(fact.get("concept")).split(":")[-1]
        namespace = fact_text(fact.get("namespace"))
        dei_namespace = bool(re.fullmatch(r"https?://xbrl\.sec\.gov/dei/\d{4}(?:-\d{2}-\d{2})?", namespace))
        if concept == "EntityCommonStockSharesOutstanding" and (taxonomy == "dei" or dei_namespace):
            share_group = "dei"
        elif taxonomy == "ifrs-full" and concept in {"NumberOfSharesOutstanding", "TreasuryShares"}:
            share_group = concept
        else:
            continue
        if fact_text(fact.get("consolidation_scope")) != "consolidated" or fact_text(fact.get("unit")) != "shares":
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
        try:
            value = Decimal(str(fact.get("value")))
            valid = (
                not isinstance(fact.get("value"), bool)
                and value.is_finite()
                and Decimal(0) <= value <= Decimal(2 ** 53)
                and value == value.to_integral_value()
                and (share_group == "TreasuryShares" or value > 0)
            )
        except (InvalidOperation, ValueError):
            valid, value = False, None
        raw_reference = fact.get("source_id")
        reference = str(raw_reference) if raw_reference is not None and pd.notna(raw_reference) else source_ref
        filing = next((
            str(fact.get(name)).strip()
            for name in ("filing_version", "accession", "sha256", "source_url")
            if fact.get(name) is not None and pd.notna(fact.get(name)) and str(fact.get(name)).strip()
        ), reference)
        key = (end.date().isoformat(), published.isoformat(), max(known, published).isoformat(), filing)
        grouped.setdefault(key, {}).setdefault(share_group, []).append((value if valid else None, reference))
    rows = []
    for (end, published, known, _filing), concepts in sorted(grouped.items()):
        def agreed(group: str) -> tuple[Decimal | None, str | None]:
            entries = concepts.get(group, [])
            values = [value for value, _ in entries]
            if not values or any(value is None for value in values) or len(set(values)) != 1:
                return None, None
            return values[0], next((reference for value, reference in entries if value is not None), None)

        if concepts.get("dei"):
            shares, reference = agreed("dei")
        elif concepts.get("NumberOfSharesOutstanding"):
            outstanding, reference = agreed("NumberOfSharesOutstanding")
            treasury, _treasury_reference = agreed("TreasuryShares")
            shares = outstanding - treasury if outstanding is not None and treasury is not None else None
            if shares is not None and shares <= 0:
                shares = None
        else:
            continue
        reference = reference or source_ref
        usable = shares is not None
        rows.append({
            "period_end": end, "period_type": "SHARES", "fiscal_year": int(end[:4]),
            "currency": "", "source": "esef_reported", "source_ref": reference,
            "known_at": known, "available_at": published,
            "shares_outstanding": float(shares) if usable else None,
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


def extract_issuer_shares(facts, *, lei: str, filing: Mapping[str, Any],
                          share_class_members: Mapping[str, list[str]] | None = None) -> dict[str, Any] | None:
    """Extract a consolidated instant count using the existing XbrlFact contract.

    DEI outstanding is preferred. The requested IFRS fallback subtracts explicit
    treasury counts, including an explicit zero; missing treasury is not zero.
    Share-class totals require a configured exhaustive axis/member set and exact
    matching treasury coverage. Conflicting duplicates, mixed totals/classes,
    durations, extensions and unknown consolidation are unusable. No issued or
    weighted-average substitution is permitted. Only the registry period end is
    used; other share instants require independent publication evidence.
    """
    from etf_cockpit.parsers.esef_ixbrl import is_ifrs_full_namespace

    period = str(filing["period_end"])
    known = datetime.fromisoformat(str(filing["known_at"]).replace("Z", "+00:00"))
    if known.tzinfo is None or period > known.date().isoformat():
        raise ValueError("shares require proven known_at")
    groups: dict[str, dict[tuple, set[Decimal]]] = {}
    bad = set()
    if share_class_members and (len(share_class_members) != 1 or any(
        not isinstance(members, list) or not members or len(set(members)) != len(members)
        for members in share_class_members.values()
    )):
        return None
    for fact in facts:
        if (fact.entity_lei != lei or fact.period_end != period or fact.period_start
                or fact.consolidation_scope != "consolidated" or fact.unit != "shares"
                or not fact.is_numeric):
            continue
        concept = fact.concept.split(":")[-1]
        dei = bool(re.fullmatch(r"https?://xbrl.sec.gov/dei/\d{4}(?:-\d{2}-\d{2})?", fact.namespace or ""))
        if concept == "EntityCommonStockSharesOutstanding" and dei:
            group = "dei"
        elif is_ifrs_full_namespace(fact.namespace) and concept in {"NumberOfSharesOutstanding", "TreasuryShares"}:
            group = concept
        else:
            continue
        dims = tuple(sorted(fact.context_dimensions))
        if group == "dei" and dims:
            continue
        if dims and (len(dims) != 1 or dims[0][0] not in (share_class_members or {})
                     or dims[0][1] not in share_class_members[dims[0][0]]):
            bad.add(group)
            continue
        try:
            value = Decimal(fact.value)
            if (fact.mapping_status == "unsupported_numeric" or not value.is_finite()
                    or value < 0 or value != value.to_integral_value()):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            bad.add(group)
            continue
        groups.setdefault(group, {}).setdefault(dims, set()).add(value)

    def total(group):
        values = groups.get(group, {})
        if group in bad or not values or any(len(v) != 1 for v in values.values()):
            return None
        if () in values:
            return next(iter(values[()])) if len(values) == 1 else None
        expected = {((axis, member),) for axis, members in (share_class_members or {}).items() for member in members}
        if set(values) != expected:
            return None
        return sum((next(iter(v)) for v in values.values()), Decimal(0))

    value, source = total("dei"), "dei:EntityCommonStockSharesOutstanding"
    if value is None and ("dei" in groups or "dei" in bad):
        return None
    if value is None:
        outstanding, treasury = total("NumberOfSharesOutstanding"), total("TreasuryShares")
        if outstanding is None or treasury is None or set(groups.get("NumberOfSharesOutstanding", {})) != set(groups.get("TreasuryShares", {})):
            return None
        value = outstanding - treasury
        source = "ifrs-full:NumberOfSharesOutstanding-ifrs-full:TreasuryShares"
    if value <= 0 or value > Decimal(2 ** 53):
        return None
    reference = json.dumps({"filing_id": filing["id"], "lei": lei, "concept": source,
                            "sha256": filing.get("package_sha256"), "share_class_members": share_class_members or {}}, sort_keys=True)
    return {"period_end": period, "period_type": "SHARES", "fiscal_year": int(period[:4]),
            "currency": "", "source": "esef_reported", "source_ref": reference,
            "known_at": known.astimezone(timezone.utc).isoformat(),
            "available_at": known.astimezone(timezone.utc).isoformat(),
            "shares_outstanding": float(value),
            "value_status": json.dumps({"shares_outstanding": "observed"})}


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
        request_interval: float = 1.0,
        request_gate: Callable[[], None] | None = None,
        retries: int = 0,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0:
            raise ValueError("ESEF provider timeout must be positive")
        self.cache_dir = Path(cache_dir)
        self.transport = transport
        self.timeout = float(timeout)
        self.fixture_manifest = Path(fixture_manifest) if fixture_manifest is not None else None
        self._filings: dict[str, dict[str, object]] = {}
        if request_interval < 0 or not float(request_interval) < float("inf"):
            raise ValueError("request_interval must be finite and non-negative")
        self.request_interval = float(request_interval)
        self.request_gate = request_gate
        if retries < 0:
            raise ValueError("retries must be non-negative")
        # Bounded exponential backoff for transient HTTP/network failures only.
        self.retries, self._retry_sleep = int(retries), retry_sleep
        self._last_request = None

    def list_issuer_filings(self, lei: str, *, error_limit: int = 0,
                           page_size: int = 100, history: bool = False,
                           entity_type: str = "entity", date_added_timezone: str | None = None) -> ProviderResult:
        """Discover every page; validate entity joins and select valid sequences.

        date_added is a conservative ceiling for public availability, rather
        than the issuer's publication date. Missing/naive timestamps, sequence
        numbers, error counts and entity relationships are unusable. With
        history=True retain successive sequence winners at their own known_at
        so a later restatement never erases evidence available earlier.
        The undocumented filter shape is checked against included entities.
        """
        try:
            if not re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", lei):
                raise ValueError("invalid LEI")
            if error_limit < 0 or not 1 <= page_size <= 100 or entity_type not in {"entity", "entities"}:
                raise ValueError("invalid error limit or page size")
            query = quote(json.dumps([{"name": "entity.identifier", "op": "eq", "val": lei}], separators=(",", ":")))
            url = f"{BASE_URL}/api/filings?filter={query}&include=entity&page[size]={page_size}"
            seen, records, rows_seen = set(), [], 0
            while url:
                parsed_url = urlparse(url)
                if (parsed_url.scheme != "https" or parsed_url.netloc != "filings.xbrl.org"
                        or parsed_url.path != "/api/filings" or url in seen or len(seen) >= 10000):
                    raise ValueError("unsafe, cyclic or excessive pagination")
                seen.add(url)
                response = self._get(url)
                if not 200 <= response.status < 300:
                    raise EsefProviderUnavailable("issuer discovery HTTP failure")
                payload = json.loads(response.payload)
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("issuer discovery requires JSON:API data")
                rows_seen += len(payload["data"])
                included = payload.get("included", [])
                if not isinstance(included, list):
                    raise ValueError("invalid included entities")
                entities = {}
                for item in included:
                    if item.get("type") == entity_type:
                        entity_id = str(item["id"])
                        identifier = item["attributes"]["identifier"]
                        if entity_id in entities and entities[entity_id] != identifier:
                            raise ValueError("conflicting included entity")
                        entities[entity_id] = identifier
                for item in payload["data"]:
                    if not isinstance(item, dict) or not isinstance(item.get("attributes"), dict):
                        raise ValueError("invalid filing row")
                    relationship = item.get("relationships", {}).get("entity", {})
                    relation = relationship.get("data")
                    if relation is not None:
                        matches = relation.get("type") == entity_type and entities.get(str(relation.get("id"))) == lei
                    else:
                        related = urljoin(BASE_URL, str(relationship.get("links", {}).get("related") or ""))
                        matches = related == f"{BASE_URL}/api/entities/{lei}"
                    if not matches:
                        raise ValueError("filing entity does not match requested LEI")
                    attrs = item["attributes"]
                    error_count = attrs.get("error_count")
                    if type(error_count) is not int or error_count < 0:
                        raise ValueError("unproven error count")
                    if error_count > error_limit:
                        continue
                    period = str(attrs.get("period_end") or "")
                    if len(period) != 10:
                        raise ValueError("missing period_end")
                    from datetime import date
                    date.fromisoformat(period)
                    if period < "2020-01-01":
                        continue
                    known = datetime.fromisoformat(str(attrs.get("date_added") or "").replace("Z", "+00:00"))
                    if known.tzinfo is None and date_added_timezone == "UTC":
                        # A date-only value (midnight) is known only by the end of that UTC day.
                        known = datetime.combine(known.date(), datetime.max.time(), timezone.utc) if known.time() == datetime.min.time() else known.replace(tzinfo=timezone.utc)
                    if known.tzinfo is None or known.date() < date.fromisoformat(period):
                        raise ValueError("unproven date_added")
                    package_url = _safe_package_url(str(attrs.get("package_url") or ""))
                    sequence = re.search(r"/" + re.escape(lei) + "/" + re.escape(period) + r"/ESEF/[A-Z]{2}/(\d+)/", urlparse(package_url).path)
                    if sequence is None or not item.get("id"):
                        raise ValueError("unproven filing sequence or identity")
                    records.append({**attrs, "id": str(item["id"]), "entity_lei": lei,
                                    "package_url": package_url, "sequence": int(sequence[1]),
                                    "known_at": known.astimezone(timezone.utc).isoformat()})
                links = payload.get("links")
                if not isinstance(links, dict):
                    raise ValueError("pagination requires an explicit next link or null")
                if "next" not in links:
                    # The live registry omits `next` on its final page: accept that only
                    # when meta.count proves every row was returned.
                    meta = payload.get("meta")
                    count = meta.get("count") if isinstance(meta, dict) else None
                    if type(count) is not int or count != rows_seen:
                        raise ValueError("pagination requires an explicit next link or null")
                    links = {**links, "next": None}
                next_link = links["next"]
                if isinstance(next_link, dict):
                    next_link = next_link.get("href")
                if next_link is not None and (not isinstance(next_link, str) or not next_link):
                    raise ValueError("invalid next link")
                url = urljoin(BASE_URL, next_link) if next_link is not None else ""
            winners = {}
            selected = []
            identities = {}
            for row in sorted(records, key=lambda r: (r["known_at"], r["sequence"], r["id"])):
                identity = (lei, row["period_end"], row["sequence"])
                if identity in identities and identities[identity] != row:
                    raise ValueError("conflicting filing sequence")
                if identity in identities:
                    continue
                identities[identity] = row
                key = (lei, row["period_end"])
                if key not in winners or row["sequence"] > winners[key]["sequence"]:
                    if key in winners and winners[key]["known_at"] == row["known_at"]:
                        selected.remove(winners[key])  # superseded at the same instant: never a separate version
                    winners[key] = row
                    selected.append(row)
            frame = pd.DataFrame(selected if history else list(winners.values()))
            self._filings.update(_index_filings(frame))
            return ProviderResult("filings_xbrl_org", "filings", "ok", "Complete issuer pagination.", frame)
        except (EsefProviderUnavailable, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            return ProviderResult("filings_xbrl_org", "filings", "error", f"Issuer discovery failed closed: {exc}", pd.DataFrame())

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
        for attempt in range(self.retries + 1):
            try:
                return self._get_once(url)
            except EsefProviderUnavailable as exc:
                cause = exc.__cause__
                transient = not isinstance(cause, ValueError) and (
                    not hasattr(cause, "code") or getattr(cause, "code") in _TRANSIENT_HTTP)
                if attempt >= self.retries or not transient:
                    raise
                self._retry_sleep(min(60.0, 2.0 ** attempt))
        raise AssertionError("unreachable")

    def _get_once(self, url: str) -> _Response:
        if self.request_gate is not None:
            self.request_gate()
        else:
            now = time.monotonic()
            if self._last_request is not None:
                time.sleep(max(0.0, self.request_interval - (now - self._last_request)))
            self._last_request = time.monotonic()
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
            raise EsefProviderUnavailable(f"official ESEF endpoint unavailable: {type(exc).__name__}: {str(exc)[:100]}") from exc
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
