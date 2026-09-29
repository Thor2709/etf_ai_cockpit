"""Optional Financial Modeling Prep enrichment and verification adapter.

FMP data is vendor authority and is kept separate from official inputs. The
adapter is disabled unless explicitly enabled with a key; probes never use I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
import hashlib
import json
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.core.types import DatasetMetadata
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority, redact_text
from etf_cockpit.data.provenance import metadata_from_frame
from etf_cockpit.data.providers import DataProvider, ProviderResult, ProviderStatus


FMP_BASE_URL = "https://financialmodelingprep.com/stable/"
FMP_PRICE_ENDPOINT = "historical-price-eod/full"
FMP_SHARED_CONFIG_BLOCK = """  fmp:
    active_provider: none
    api_key: ""
    base_url: https://financialmodelingprep.com/stable/
    symbols_map: {}

# data_source_policy.yaml source row:
- {provider_id: fmp, dataset_type: prices, source_tier: optional_commercial, mandatory_allowed: false, optional_provider: true, cache_path: data/raw/fmp, licence: fmp-plan-terms, network_required: true, quota_failure: non_blocking, fair_use_note: Optional vendor enrichment; verify plan rights and never use as official evidence or mandatory scoring input.}"""

Transport = Callable[[str, dict[str, str], float], Any]


class FmpProvider(DataProvider):
    """Explicit, key-gated FMP EOD enrichment with a bounded memory cache."""

    name = "fmp"
    DEFAULT_CACHE_TTL_SECONDS = 300
    DEFAULT_TIMEOUT_SECONDS = 15.0
    MAX_CACHE_ENTRIES = 128

    def __init__(
        self,
        api_key: str = "",
        section: ProviderSection | None = None,
        *,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        monotonic: Callable[[], float] = monotonic,
    ) -> None:
        if timeout <= 0:
            raise ValueError("FMP timeout must be positive")
        if cache_ttl_seconds < 0:
            raise ValueError("FMP cache TTL cannot be negative")
        self.section = section or ProviderSection(
            active_provider="fmp" if api_key else "none",
            api_key=api_key,
            base_url=FMP_BASE_URL,
        )
        self.api_key = str(api_key or self.section.api_key or "").strip()
        self.transport = transport
        self.timeout = float(timeout)
        self.cache_ttl_seconds = int(cache_ttl_seconds)
        self._monotonic = monotonic
        self._cache: dict[str, tuple[float, pd.DataFrame, str]] = {}

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        enabled = (self.section.active_provider or "none").strip().lower() == self.name
        configured = enabled and bool(self.api_key)
        entitlement = "configured" if configured else "api_key_required" if enabled else "disabled"
        message = (
            "FMP is optional vendor enrichment; probe made no network request."
            if configured
            else "FMP is disabled; no network request was made."
            if not enabled
            else "FMP requires a local API key; no network request was made."
        )
        return (ProviderCapability(
            provider_id=self.name,
            dataset_type="prices",
            status="unavailable",
            authority=SourceAuthority.VENDOR,
            configured=configured,
            entitlement=entitlement,
            rate_limit_note="optional quota; failures are non-blocking",
            last_success_at=None,
            error_fingerprint=None,
            secret_present=bool(self.api_key),
            message=message,
        ),)

    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        if start_date > end_date:
            return self._result("unavailable", "Start date is after end date.")
        if not symbols:
            return self._result("unavailable", "No FMP symbols were requested.")
        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            result = self._fetch_symbol(str(symbol), start_date, end_date)
            if result.status != "ok" or result.data is None:
                return result
            frames.append(result.data)
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        frame.attrs["source_authority"] = SourceAuthority.VENDOR.value
        frame.attrs["score_eligible"] = False
        return self._result(
            "ok", f"Retrieved optional FMP vendor prices for {len(symbols)} symbol(s).", frame,
            quota_status="ok",
            cache_hit=all(bool(item.attrs.get("cache_hit")) for item in frames),
            known_at=max((str(item["known_at"].max()) for item in frames if "known_at" in item), default=None),
        )

    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        return self._result("unavailable", "FMP FX enrichment is not implemented by this adapter.", dataset_type="fx")

    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        return self._result("unavailable", "FMP ETF metadata enrichment is not implemented by this adapter.", dataset_type="etf_metadata")

    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        return self._result("unavailable", "FMP ETF holdings enrichment is not implemented by this adapter.", dataset_type="etf_holdings")

    def verify_against_official(
        self,
        vendor_data: pd.DataFrame,
        official_data: pd.DataFrame,
        *,
        decision_time: datetime | None = None,
        key_columns: tuple[str, ...] = ("symbol", "date"),
        value_columns: tuple[str, ...] = ("close",),
    ) -> ProviderResult:
        """Record disagreements while returning official rows unchanged.

        Both sources need known_at or available_at at or before decision_time.
        This method never combines vendor values into official output.
        """

        if any(column not in vendor_data for column in key_columns):
            return self._result("unavailable", "Vendor data lacks identity fields.", dataset_type="verification")
        if any(column not in official_data for column in (*key_columns, *value_columns)):
            return self._result("unavailable", "Official data lacks comparison fields.", dataset_type="verification")
        cutoff = _as_utc(decision_time or datetime.now(timezone.utc))
        vendors = vendor_data.copy()
        if not _evidence_available(vendors, cutoff):
            return self._result("unavailable", "Vendor values lack valid availability evidence at the requested decision time.", dataset_type="verification")
        official = official_data.copy()
        if not _evidence_available(official, cutoff):
            return self._result("unavailable", "Official values lack valid availability evidence at the requested decision time.", dataset_type="verification")
        joined = vendors.merge(
            official.loc[:, [*key_columns, *value_columns]],
            on=list(key_columns),
            how="inner",
            suffixes=("_vendor", "_official"),
        )
        conflicts: list[Mapping[str, object]] = []
        for _, row in joined.iterrows():
            for column in value_columns:
                vendor_value = row.get(f"{column}_vendor")
                official_value = row.get(f"{column}_official")
                if pd.notna(vendor_value) and pd.notna(official_value) and vendor_value != official_value:
                    conflicts.append({
                        **{key: row[key] for key in key_columns},
                        "field": column,
                        "vendor_value": vendor_value,
                        "official_value": official_value,
                        "selected_authority": SourceAuthority.OFFICIAL.value,
                    })
        return self._result(
            "ok", "Official values retained; vendor disagreements were recorded.",
            official, dataset_type="verification", conflicts=tuple(conflicts),
        )

    def _fetch_symbol(self, symbol: str, start_date: date, end_date: date) -> ProviderResult:
        if not self._enabled():
            capability = self.probe_capabilities()[0]
            return self._result("unavailable", capability.message)
        if not symbol.strip():
            return self._result("unavailable", "FMP symbol is empty.")
        base_url = (self.section.base_url or FMP_BASE_URL).strip().rstrip("/") + "/"
        params = {"symbol": symbol, "from": start_date.isoformat(), "to": end_date.isoformat()}
        cache_key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        cached = self._cache.get(cache_key)
        now = self._monotonic()
        if cached is not None and now - cached[0] <= self.cache_ttl_seconds:
            frame = cached[1].copy()
            frame.attrs.update(cached[1].attrs)
            frame.attrs["cache_hit"] = True
            return self._result("ok", "Returned cached FMP vendor prices.", frame, cache_hit=True, known_at=cached[2])
        url = f"{base_url}{FMP_PRICE_ENDPOINT}?{urlencode(params)}"
        try:
            status, payload = self._request(url)
            if status == 429:
                return self._quota_failure("FMP quota or rate limit was reached.", "HTTP 429")
            if status < 200 or status >= 300:
                return self._failure(f"FMP endpoint returned HTTP {status}.", f"HTTP {status}")
            parsed = json.loads(payload.decode("utf-8"))
            if not isinstance(parsed, list):
                return self._failure("FMP returned an invalid price payload.", "invalid JSON shape")
            frame = pd.DataFrame(parsed)
            if frame.empty:
                return self._result("unavailable", "FMP returned no price rows for the requested range.")
            if "symbol" not in frame:
                frame["symbol"] = symbol
            frame["known_at"] = _utc_now()
            frame["source_authority"] = SourceAuthority.VENDOR.value
            frame["score_eligible"] = False
            known_at = _utc_now()
            frame.attrs["cache_hit"] = False
            self._cache[cache_key] = (now, frame.copy(), known_at)
            if len(self._cache) > self.MAX_CACHE_ENTRIES:
                oldest = min(self._cache, key=lambda key: self._cache[key][0])
                self._cache.pop(oldest, None)
            return self._result("ok", "Retrieved optional FMP vendor prices.", frame, known_at=known_at)
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            return self._failure(f"FMP request unavailable ({type(exc).__name__}).", f"{type(exc).__name__}:{redact_text(exc)}")

    def _request(self, url: str) -> tuple[int, bytes]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "ETF AI Cockpit optional data adapter",
            "apikey": self.api_key,
        }
        if self.transport is not None:
            value = self.transport(url, headers, self.timeout)
            if isinstance(value, tuple) and len(value) == 2:
                return int(value[0]), bytes(value[1])
            if isinstance(value, bytes):
                return 200, value
            raise TypeError("FMP transport must return bytes or a (status, bytes) tuple")
        try:
            with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
                return int(response.status), response.read()
        except HTTPError as exc:
            if exc.code == 429:
                return 429, b""
            raise

    def _enabled(self) -> bool:
        return (self.section.active_provider or "none").strip().lower() == self.name and bool(self.api_key)

    def _quota_failure(self, message: str, fingerprint_source: str) -> ProviderResult:
        fingerprint = _fingerprint(fingerprint_source)
        return self._result("unavailable", message, quota_status="rate_limited", error_fingerprint=fingerprint)

    def _failure(self, message: str, fingerprint_source: str) -> ProviderResult:
        fingerprint = _fingerprint(fingerprint_source)
        return self._result("unavailable", message, quota_status="error", error_fingerprint=fingerprint)

    def _result(
        self,
        status: ProviderStatus,
        message: str,
        data: pd.DataFrame | None = None,
        *,
        dataset_type: str = "prices",
        quota_status: str = "not_requested",
        error_fingerprint: str | None = None,
        cache_hit: bool = False,
        conflicts: tuple[Mapping[str, object], ...] = (),
        known_at: str | None = None,
    ) -> ProviderResult:
        quota = {
            "status": quota_status,
            "failure_policy": "non_blocking",
            "error_fingerprint": error_fingerprint,
        }
        cache = {"enabled": True, "hit": cache_hit, "ttl_seconds": self.cache_ttl_seconds}
        metadata_details = {
            "licence": "fmp-plan-terms; caller must confirm applicable rights",
            "quota": quota,
            "cache": cache,
            "authority": SourceAuthority.VENDOR.value,
            "error_fingerprint": error_fingerprint,
            "conflicts": list(conflicts),
            "known_at": known_at,
        }
        result_frame = data if data is not None else pd.DataFrame()
        metadata: DatasetMetadata = metadata_from_frame(
            result_frame,
            source_name=self.name,
            source_type=dataset_type,
            as_of_date=None,
            provider_or_manual_source=self.name,
            notes=json.dumps(metadata_details, sort_keys=True, default=str),
        )
        return ProviderResult(
            provider_name=self.name,
            dataset_type=dataset_type,
            status=status,
            message=redact_text(message),
            data=data,
            metadata=metadata,
        )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision_time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _evidence_available(frame: pd.DataFrame, cutoff: datetime) -> bool:
    if frame.empty:
        return False
    columns = [column for column in ("known_at", "available_at") if column in frame]
    if not columns:
        return False
    for column in columns:
        timestamps = pd.to_datetime(frame[column], utc=True, errors="coerce")
        if timestamps.isna().any() or (timestamps > cutoff).any():
            return False
    return True


__all__ = ["FMP_BASE_URL", "FMP_PRICE_ENDPOINT", "FMP_SHARED_CONFIG_BLOCK", "FmpProvider"]
