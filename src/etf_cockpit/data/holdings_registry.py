"""Configured issuer acquisition; only iShares is enabled.

No issuer URL, fund identity, listing calendar or bond format is guessed.
Product page and slug identify the recon-verified latest CSV route. Duplicate
products/identities are rejected: deduplication across different share classes
requires instrument-master subfund evidence and is not inferred from tickers.
Other issuers have no URLs and remain inactive pending verified configuration.
Collection runs threads across funds; a shared host lock spaces request starts
by at least one second. Redirects are disabled so they cannot bypass politeness
or silently return a different product. Missing config is an error; an explicit
empty fund list is a no-op without creating a store or contacting a provider.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

import yaml

from etf_cockpit.core.http_fetch import get_checked
from etf_cockpit.data.ishares_holdings import COLUMNS, utc_timestamp
from etf_cockpit.data.market_calendar import ListingCalendarEvidence

REQUIRED_FIELDS = (
    "verified_download_route", "verified_csv_schema", "as_of_field",
    "publication_known_at", "instrument_identity", "calendar_evidence",
    "licence_and_provenance", "ticker_exchange_isin_mapping",
)
ISSUERS = {name: {"active": name == "iShares", "required_fields": REQUIRED_FIELDS}
           for name in ("iShares", "Xtrackers", "Vanguard", "Amundi", "SPDR")}
_HOST_LOCK = threading.Lock()
_LAST_REQUEST: dict[str, float] = {}
_MAX_BYTES = 8 * 1024 * 1024


def _listing(config: dict) -> ListingCalendarEvidence:
    fields = dict(config)
    for key in ("valid_from", "valid_to"):
        if fields.get(key) is not None:
            fields[key] = date.fromisoformat(str(fields[key]))
    fields["known_at"] = utc_timestamp(fields.get("known_at"))
    return ListingCalendarEvidence(**fields)


def listing_evidence(root: Path, instrument_id: str) -> ListingCalendarEvidence:
    """Return the validated listing evidence for one explicitly configured fund."""

    matches = [fund for fund in load_funds(Path(root))["funds"] if fund["instrument_id"] == instrument_id]
    if len(matches) != 1:
        raise ValueError("instrument is not present exactly once in the configured holdings registry")
    return matches[0]["_listing"]


def load_funds(root: Path) -> dict:
    path = Path(root) / "configs" / "ishares_ucits_funds_v1.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1 or config.get("execution_allowed") is not False:
        raise ValueError("invalid holdings configuration or execution_allowed")
    funds = config.get("funds")
    if not isinstance(funds, list):
        raise ValueError("explicit fund list required")
    ua = config.get("user_agent")
    if not isinstance(ua, str) or not ua.startswith("Mozilla/5.0") or any(c in ua for c in "\r\n"):
        raise ValueError("configured browser-style User-Agent required")
    seen_products, seen_ids = set(), set()
    for fund in funds:
        if not isinstance(fund, dict):
            raise ValueError("invalid fund entry")
        for key in ("ticker", "ISIN", "product_page_url", "slug", "instrument_id"):
            if not isinstance(fund.get(key), str) or not fund[key].strip():
                raise ValueError("missing fund field: " + key)
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", fund["ISIN"]):
            raise ValueError("invalid fund ISIN")
        page = urlsplit(fund["product_page_url"])
        match = re.fullmatch(r"/uk/individual/en/products/(\d+)/([a-z0-9-]+)/?", page.path)
        if (page.scheme != "https" or page.netloc != "www.ishares.com" or page.query or page.fragment
                or match is None or match[2] != fund["slug"]):
            raise ValueError("unverified iShares product route or slug mismatch")
        if match[1] in seen_products or fund["instrument_id"] in seen_ids:
            raise ValueError("duplicate product or instrument; resolve identity in instrument master")
        seen_products.add(match[1])
        seen_ids.add(fund["instrument_id"])
        listing = _listing(fund.get("calendar", {}))
        if listing.instrument_id != fund["instrument_id"]:
            raise ValueError("calendar identity mismatch")
        mapping = {}
        entries = fund.get("isin_mapping", [])
        if not isinstance(entries, list):
            raise ValueError("ISIN mapping must be a list")
        for row in entries:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                                for key in ("ticker", "exchange", "ISIN")):
                raise ValueError("invalid ISIN mapping")
            key = (row["ticker"], row["exchange"])
            if key in mapping or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", row["ISIN"]):
                raise ValueError("duplicate or invalid ISIN mapping")
            mapping[key] = row["ISIN"]
        columns = fund.get("expected_columns", list(COLUMNS))
        bonds = fund.get("bond_asset_classes", [])
        if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                or len(set(columns)) != len(columns) or not set(COLUMNS).issubset(columns)
                or not isinstance(bonds, list) or not all(isinstance(c, str) and c.strip() for c in bonds)):
            raise ValueError("invalid explicitly configured CSV schema")
        fund["_listing"], fund["_mapping"] = listing, mapping
        fund["_download_url"] = fund["product_page_url"].rstrip("/") + "/latest-holdings.csv"
    return config


def fetch_csv(url: str, user_agent: str) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.ishares.com" or not parts.path.endswith("/latest-holdings.csv") or parts.query or parts.fragment:
        raise ValueError("unsupported holdings source URL")
    # Keep the lock across the wait so simultaneous workers cannot reserve the
    # same slot. Requests run outside the lock and may overlap after one second.
    with _HOST_LOCK:
        delay = max(0.0, 1.0 - (time.monotonic() - _LAST_REQUEST.get(parts.netloc, float("-inf"))))
        if delay:
            time.sleep(delay)
        _LAST_REQUEST[parts.netloc] = time.monotonic()
    payload, status, headers = get_checked(url, allowed=lambda _: False,
        headers={"User-Agent": user_agent, "Accept": "text/csv,text/plain"},
        timeout=30, max_bytes=_MAX_BYTES, max_redirects=0)
    content_type = next((str(value) for key, value in headers.items() if key.lower() == "content-type"), "")
    media = content_type.split(";", 1)[0].strip().lower()
    if (status != 200 or len(payload) > _MAX_BYTES
            or media not in {"text/plain", "text/csv", "application/csv"}
            or not payload.decode("utf-8-sig").startswith("Fund Holdings as of,")):
        raise ValueError("non-CSV/HTML, oversized or unsuccessful holdings response")
    return payload


def collect_daily(root: Path, *, workers: int = 6, fetcher=None, publish_guard=None) -> list[dict]:
    """Collect configured latest files; return a status for each configured fund.

    Network/parse errors are isolated by fund and reported without provider
    payloads or URLs. Configuration errors abort before any network requests.
    Publication remains under the refresh workflow's existing authority scope.
    """
    from etf_cockpit.core.workflow import WorkflowTransitionError, publication_scope
    from etf_cockpit.data.holdings_snapshots import write_snapshot

    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    config = load_funds(root)
    if not config["funds"]:
        return []
    get = fetcher or fetch_csv

    def fetch(fund):
        # Network only: the publication scope is thread-bound (AppState.shared_activity_id), so writes stay on the caller thread.
        try:
            return get(fund["_download_url"], config["user_agent"]), datetime.now(timezone.utc), None
        except Exception as exc:
            return None, None, exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = list(pool.map(fetch, config["funds"]))

    statuses = []
    for fund, (payload, receipt, error) in zip(config["funds"], fetched):
        try:
            if error is not None:
                raise error
            with publication_scope(publish_guard):
                result = write_snapshot(root, payload, instrument_id=fund["instrument_id"],
                    source_url=fund["_download_url"], fetched_at=receipt, listing=fund["_listing"],
                    isin_mapping=fund["_mapping"], expected_columns=tuple(fund.get("expected_columns", COLUMNS)),
                    bond_asset_classes=tuple(fund.get("bond_asset_classes", [])))
            statuses.append(dict(ticker=fund["ticker"], status=result["status"], as_of=result["snapshot"]["as_of"]))
        except WorkflowTransitionError:
            raise
        except Exception as exc:
            statuses.append(dict(ticker=fund["ticker"], status="failed", reason=type(exc).__name__))
    return statuses
