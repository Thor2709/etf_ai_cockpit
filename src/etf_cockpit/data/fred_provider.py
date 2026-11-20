from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority
from etf_cockpit.data.macro_warehouse import (
    FETCH_ERRORS,
    MacroFetchResult,
    MacroObservation,
    fetch_bytes,
    fetch_time,
    legal_terms_block,
)

_URL = "https://api.stlouisfed.org/fred/series/observations"
_VINTAGE_DATES_URL = "https://api.stlouisfed.org/fred/series/vintagedates"
_MAX_WINDOW_VINTAGES = 2000  # FRED json limit of vintage dates per observations request
_MAX_PAGES = 20  # FRED returns at most 100,000 rows per request
_EARLIEST_VINTAGE = "1776-07-04"
_LATEST_VINTAGE = "9999-12-31"
# Series behind the INT-19 indicators: series id -> (unit, frequency).
FRED_SERIES: dict[str, tuple[str, str]] = {
    "DGS10": ("percent", "daily"),
    "DGS2": ("percent", "daily"),
    "DGS3MO": ("percent", "daily"),
    "DFII10": ("percent", "daily"),
    "BAA10Y": ("percent", "daily"),
    "BAMLH0A0HYM2": ("percent", "daily"),
    "VIXCLS": ("index", "daily"),
    "NFCI": ("index", "irregular"),
    "UNRATE": ("percent", "monthly"),
    "GDP": ("billions_usd", "quarterly"),
    "BOGZ1LM893064105Q": ("millions_usd", "quarterly"),
}
# Legal-terms row per series; ICE BofA indices carry stricter terms than the generic FRED row.
_TERMS = {"BAMLH0A0HYM2": "fred_ice_bofa"}


@dataclass(frozen=True)
class OptionalProviderProbe:
    provider_id: str
    status: str
    message: str


class FredProvider:
    name = "fred"

    def __init__(
        self,
        api_key: str = "",
        section: ProviderSection | None = None,
        transport: Callable[[str], bytes] | None = None,
    ) -> None:
        self.section = section or ProviderSection(active_provider="fred" if api_key else "none", api_key=api_key)
        self.api_key = api_key or self.section.api_key
        self.transport = transport

    def probe(self) -> OptionalProviderProbe:
        if not self.api_key.strip():
            return OptionalProviderProbe("fred", "unavailable", "FRED is disabled until a local API key is configured.")
        return OptionalProviderProbe("fred", "configured", "FRED is configured but no network request was made by the probe.")

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        probe = self.probe()
        configured = bool(self.api_key.strip()) and (self.section.active_provider or "none").strip().lower() not in {"", "none"}
        return (ProviderCapability(
            provider_id="fred",
            dataset_type="macro",
            status="unavailable" if not configured else "unavailable",
            authority=SourceAuthority.OFFICIAL,
            configured=configured,
            entitlement="api_key_required" if not configured else "configured",
            rate_limit_note="probe only; no network request",
            last_success_at=None,
            error_fingerprint=None,
            secret_present=bool(self.api_key),
            message=probe.message,
        ),)

    def fetch_vintages(
        self,
        series_id: str,
        *,
        fetched_at: datetime | None = None,
    ) -> MacroFetchResult:
        """Fetch every ALFRED real-time vintage; each is one revision with exact availability."""

        return self._fetch(series_id, True, fetched_at)

    def fetch_latest(
        self,
        series_id: str,
        *,
        fetched_at: datetime | None = None,
    ) -> MacroFetchResult:
        """Fetch today's values only; their availability is inferred, so no historical feature may use them."""

        return self._fetch(series_id, False, fetched_at)

    def _fetch(self, series_id: str, vintages: bool, fetched_at: datetime | None) -> MacroFetchResult:
        if not self.api_key.strip():
            return MacroFetchResult.unavailable("FRED API key is not configured.")
        blocked = legal_terms_block(_TERMS.get(series_id, "fred"))
        if blocked:
            return MacroFetchResult.unavailable(blocked)
        if series_id not in FRED_SERIES:
            return MacroFetchResult.unavailable(f"FRED series {series_id} has no declared unit and frequency.")
        unit, frequency = FRED_SERIES[series_id]
        params = {"series_id": series_id, "api_key": self.api_key, "file_type": "json"}
        if vintages:
            params |= {"realtime_start": _EARLIEST_VINTAGE, "realtime_end": _LATEST_VINTAGE}
        try:
            raw_rows, payloads = self._vintage_pages(params) if vintages else self._pages(params)
            known_at = fetch_time(fetched_at)  # taken after the response arrived, never before
            rows, skipped = _observations(raw_rows, payloads, series_id, vintages, known_at, unit, frequency)
        except FETCH_ERRORS as exc:
            # Only the exception type is reported: the request URL carries the API key.
            return MacroFetchResult.unavailable(f"FRED fetch failed: {type(exc).__name__}.")
        if not rows:
            return MacroFetchResult.unavailable("FRED returned no usable observations.")
        reason = f"FRED skipped {skipped} vintage rows dated after their vintage." if skipped else None
        return MacroFetchResult("available", tuple(rows), reason)


    def _vintage_pages(self, params: dict[str, str]) -> tuple[list[dict[str, str]], bytes]:
        """Read every vintage. Above 2000 vintage dates FRED answers 400, so read windows of at most 2000."""

        try:
            return self._pages(params)
        except HTTPError as exc:
            if exc.code != 400:
                raise
        dates, _ = self._pages(params, _VINTAGE_DATES_URL, "vintage_dates")
        rows: list[dict[str, str]] = []
        payloads = b""
        carried: dict[str, dict[str, str]] = {}  # per date, the row still valid at the previous window's end
        for first in range(0, len(dates), _MAX_WINDOW_VINTAGES):
            start = dates[first] if first else _EARLIEST_VINTAGE
            last = first + _MAX_WINDOW_VINTAGES
            end = dates[last - 1] if last < len(dates) else _LATEST_VINTAGE
            batch, page = self._pages(params | {"realtime_start": start, "realtime_end": end})
            payloads += page
            still_valid: dict[str, dict[str, str]] = {}
            for row in batch:
                before = carried.get(row["date"])
                if before and before["value"] == row["value"] and row["realtime_start"] <= start:
                    before["realtime_end"] = row["realtime_end"]  # one vintage, cut at the window edge
                    row = before
                else:
                    rows.append(row)
                if row["realtime_end"] >= end:
                    still_valid[row["date"]] = row
            carried = still_valid
        return rows, payloads

    def _pages(
        self, params: dict[str, str], endpoint: str = _URL, key: str = "observations"
    ) -> tuple[list[dict[str, str]], bytes]:
        """Read every page of the response (bounded), so a long vintage history is complete."""

        rows: list[dict[str, str]] = []
        payloads = b""
        total = 0
        for _ in range(_MAX_PAGES):
            query = params | ({"offset": str(len(rows))} if rows else {})
            url = f"{endpoint}?{urlencode(query)}"
            page = self.transport(url) if self.transport else fetch_bytes(
                url, {"User-Agent": "ETF AI Evidence Cockpit/1.0"}
            )
            document = json.loads(page)
            batch = document[key]
            total = int(document.get("count", len(rows) + len(batch)))
            rows += batch
            payloads += page
            if len(rows) >= total or not batch:
                break
        if len(rows) < total:
            raise ValueError("truncated response")
        return rows, payloads


def _observations(
    rows: list[dict[str, str]], payload: bytes, series_id: str, vintages: bool, fetched_at: datetime, unit: str, frequency: str
) -> tuple[list[MacroObservation], int]:
    # "." is FRED's marker for a missing value; it is skipped, never filled.
    kept = sorted(
        (row for row in rows if str(row["value"]).strip() not in {"", "."}),
        key=lambda row: (str(row["date"]), str(row["realtime_start"])),
    )
    checksum = hashlib.sha256(payload).hexdigest()
    observed: list[MacroObservation] = []
    revisions: dict[str, int] = {}
    skipped = 0
    for row in kept:
        period = str(row["date"])
        if vintages:
            # ALFRED vintage dates are US Central dates; a vintage is known by the end of that local day.
            end_of_day = datetime.combine(
                date.fromisoformat(str(row["realtime_start"])), time(23, 59, 59), tzinfo=ZoneInfo("America/Chicago")
            ).astimezone(timezone.utc)
            if end_of_day > fetched_at:
                continue  # that vintage day is not over; the next refresh picks it up
            if datetime.combine(date.fromisoformat(period), time(0), tzinfo=timezone.utc) > end_of_day:
                skipped += 1
                continue  # the vintage dates a later observation (e.g. a US holiday); it cannot be point-in-time
            available_at, ingested_at = end_of_day, end_of_day
            revisions[period] = revisions.get(period, 0) + 1
            dataset_id = f"fred:{series_id}"
            source_id = f"fred:{series_id}:alfred"
            revision, confidence = revisions[period], "exact"
            methodology = (
                "FRED/ALFRED real-time vintages; one revision per vintage. A vintage is an archived "
                f"publication, so ingested_at is its vintage time; fetched {fetched_at.isoformat()}."
            )
        else:
            available_at = ingested_at = fetched_at
            dataset_id = f"fred_latest:{series_id}"
            source_id = f"fred_latest:{series_id}:{fetched_at:%Y%m%dT%H%M%SZ}"
            revision, confidence = 1, "inferred"
            methodology = "FRED latest values without real-time vintages; known only from the fetch time."
        observed.append(MacroObservation(
            dataset_id=dataset_id,
            series_id=series_id,
            period_start=period,
            value=float(row["value"]),
            unit=unit,
            frequency=frequency,
            country="US",
            currency="USD",
            source_id=source_id,
            source_authority="official_api",
            source_checksum=checksum,
            source_terms=_TERMS.get(series_id, "fred"),
            methodology=methodology,
            published_at=available_at.isoformat(),
            available_at=available_at.isoformat(),
            observed_at=period,
            ingested_at=ingested_at.isoformat(),
            revision=revision,
            availability_confidence=confidence,
        ))
    return observed, skipped
