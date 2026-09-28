"""Twelve Data OHLCV market data adapter.

Provides daily, intraday, and adjusted OHLCV data with per-provider
rate limiting, credential redaction, and normalisation to the canonical
cockpit schema. Optional fallback provider, disabled unless configured.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
import json
import os
import time
from typing import Any

import pandas as pd
import requests

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority, redact_text
from etf_cockpit.data.ohlcv_discrepancy import normalise_ohlcv
from etf_cockpit.data.provenance import metadata_from_frame
from etf_cockpit.data.providers import DataProvider, PriceProvider, ProviderResult

DEFAULT_BASE_URL = "https://api.twelvedata.com"
FREE_TIER_CALLS_PER_MIN = 8
FREE_TIER_CALLS_PER_DAY = 800


@dataclass(frozen=True)
class RateLimitState:
    """Non-blocking rate limit / quota state snapshot."""

    allowed: bool
    status: str  # "ok", "rate_limited", "quota_exhausted"
    retry_after: float = 0.0
    non_blocking: bool = True
    message: str = ""


class RateLimiter:
    """Sliding-window per-provider rate limiter.

    Enforces call limits without blocking execution. When quota is exhausted,
    requests are refused immediately with an attributable quota state.
    """

    def __init__(
        self,
        *,
        calls_per_minute: int | None = None,
        calls_per_hour: int | None = None,
        calls_per_day: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.calls_per_minute = calls_per_minute
        self.calls_per_hour = calls_per_hour
        self.calls_per_day = calls_per_day
        self._clock = clock
        self._minute_calls: list[float] = []
        self._hour_calls: list[float] = []
        self._day_calls: list[float] = []

    def check_limit(self) -> RateLimitState:
        now = self._clock()
        self._prune(now)

        if self.calls_per_minute is not None and len(self._minute_calls) >= self.calls_per_minute:
            oldest = self._minute_calls[0] if self._minute_calls else now
            retry_after = max(0.0, round(60.0 - (now - oldest), 2))
            return RateLimitState(
                allowed=False,
                status="rate_limited",
                retry_after=retry_after,
                non_blocking=True,
                message=f"Minute rate limit reached ({self.calls_per_minute}/min). Retry after {retry_after}s.",
            )

        if self.calls_per_hour is not None and len(self._hour_calls) >= self.calls_per_hour:
            oldest = self._hour_calls[0] if self._hour_calls else now
            retry_after = max(0.0, round(3600.0 - (now - oldest), 2))
            return RateLimitState(
                allowed=False,
                status="rate_limited",
                retry_after=retry_after,
                non_blocking=True,
                message=f"Hourly rate limit reached ({self.calls_per_hour}/hr). Retry after {retry_after}s.",
            )

        if self.calls_per_day is not None and len(self._day_calls) >= self.calls_per_day:
            oldest = self._day_calls[0] if self._day_calls else now
            retry_after = max(0.0, round(86400.0 - (now - oldest), 2))
            return RateLimitState(
                allowed=False,
                status="quota_exhausted",
                retry_after=retry_after,
                non_blocking=True,
                message=f"Daily quota exhausted ({self.calls_per_day}/day). Retry after {retry_after}s.",
            )

        return RateLimitState(allowed=True, status="ok", retry_after=0.0, non_blocking=True, message="OK")

    def acquire(self) -> RateLimitState:
        state = self.check_limit()
        if state.allowed:
            now = self._clock()
            if self.calls_per_minute is not None:
                self._minute_calls.append(now)
            if self.calls_per_hour is not None:
                self._hour_calls.append(now)
            if self.calls_per_day is not None:
                self._day_calls.append(now)
        return state

    def _prune(self, now: float) -> None:
        self._minute_calls = [t for t in self._minute_calls if now - t < 60.0]
        self._hour_calls = [t for t in self._hour_calls if now - t < 3600.0]
        self._day_calls = [t for t in self._day_calls if now - t < 86400.0]

    def reset(self) -> None:
        self._minute_calls.clear()
        self._hour_calls.clear()
        self._day_calls.clear()


class TwelveDataProvider(DataProvider, PriceProvider):
    """Twelve Data adapter for daily, intraday and adjusted OHLCV data."""

    name = "twelvedata"
    authority = SourceAuthority.VENDOR
    supported_intervals = ("1min", "5min", "15min", "30min", "45min", "1h", "2h", "4h", "1day", "1week", "1month")

    def __init__(
        self,
        section: ProviderSection | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        limiter: RateLimiter | None = None,
        transport: Callable[[str, dict[str, str]], Any] | None = None,
        default_currency: str = "USD",
    ) -> None:
        self.section = section or ProviderSection()
        self._api_key = (
            api_key
            or self.section.api_key
            or os.getenv("ETF_COCKPIT_TWELVEDATA_API_KEY", "")
            or os.getenv("ETF_COCKPIT_TWELVE_DATA_API_KEY", "")
        ).strip()
        self.base_url = (base_url or self.section.base_url or DEFAULT_BASE_URL).rstrip("/")
        self.limiter = limiter or RateLimiter(
            calls_per_minute=FREE_TIER_CALLS_PER_MIN,
            calls_per_day=FREE_TIER_CALLS_PER_DAY,
        )
        self.transport = transport
        self.default_currency = default_currency
        self.last_limiter_state: RateLimitState | None = None

    @property
    def is_configured(self) -> bool:
        active = (self.section.active_provider or "none").strip().lower()
        return active not in {"", "none"} and bool(self._api_key)

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        active = (self.section.active_provider or "none").strip().lower()
        configured_flag = active not in {"", "none"}
        has_key = bool(self._api_key)

        if not configured_flag:
            status = "unavailable"
            entitlement = "disabled"
            message = "Twelve Data is optional and disabled by configuration; no network request was made."
        elif not has_key:
            status = "unavailable"
            entitlement = "api_key_required"
            message = "Twelve Data requires an API key (ETF_COCKPIT_TWELVEDATA_API_KEY); none configured."
        else:
            status = "ok"
            entitlement = "free_tier"
            message = "Twelve Data adapter configured for daily, intraday, and adjusted OHLCV."

        return (
            ProviderCapability(
                provider_id=self.name,
                dataset_type="prices",
                status=status,
                authority=self.authority,
                configured=configured_flag and has_key,
                entitlement=entitlement,
                rate_limit_note=(
                    f"Free tier: {FREE_TIER_CALLS_PER_MIN} credits/min, {FREE_TIER_CALLS_PER_DAY} credits/day. "
                    "Daily, intraday, and adjusted OHLCV supported; non-blocking quota exhaustion."
                ),
                last_success_at=None,
                error_fingerprint=None,
                secret_present=has_key,
                message=redact_text(message),
            ),
        )

    def _safe_request(self, url: str, headers: dict[str, str]) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
        """Dispatch HTTP request via injected transport or requests session."""
        try:
            if self.transport is not None:
                resp = self.transport(url, headers)
                if hasattr(resp, "json"):
                    return resp.json(), None
                if isinstance(resp, (dict, list)):
                    return resp, None
                if isinstance(resp, (str, bytes)):
                    return json.loads(resp), None
                return None, "Unexpected transport return type."

            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 429:
                return None, f"HTTP 429: {redact_text(response.text)}"
            response.raise_for_status()
            return response.json(), None
        except Exception as exc:
            return None, redact_text(f"{type(exc).__name__}: {exc}")

    def fetch_daily_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch daily OHLCV from Twelve Data and normalise to canonical schema."""
        if not self.is_configured:
            return pd.DataFrame()

        state = self.limiter.acquire()
        self.last_limiter_state = state
        if not state.allowed:
            return pd.DataFrame()

        clean_symbol = symbol.strip()
        url = (
            f"{self.base_url}/time_series?"
            f"symbol={clean_symbol}&interval=1day&"
            f"start_date={start:%Y-%m-%d}&end_date={end:%Y-%m-%d}&"
            f"apikey={self._api_key}"
        )
        headers = {"Accept": "application/json"}

        payload, err = self._safe_request(url, headers)
        if err or not isinstance(payload, dict):
            return pd.DataFrame()

        # Handle API error payload
        if payload.get("status") == "error":
            return pd.DataFrame()

        values = payload.get("values", [])
        if not values or not isinstance(values, list):
            return pd.DataFrame()

        meta = payload.get("meta", {})
        currency = meta.get("currency") or self.default_currency

        raw_df = pd.DataFrame(values)
        return normalise_ohlcv(raw_df, source=self.name, symbol=clean_symbol, currency=currency)

    def fetch_intraday_prices(
        self,
        symbol: str,
        interval: str = "5min",
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Fetch intraday OHLCV for the requested interval."""
        if not self.is_configured:
            return pd.DataFrame()

        if interval not in self.supported_intervals:
            return pd.DataFrame()

        state = self.limiter.acquire()
        self.last_limiter_state = state
        if not state.allowed:
            return pd.DataFrame()

        clean_symbol = symbol.strip()
        url = f"{self.base_url}/time_series?symbol={clean_symbol}&interval={interval}&apikey={self._api_key}"
        if start:
            url += f"&start_date={start:%Y-%m-%d}"
        if end:
            url += f"&end_date={end:%Y-%m-%d}"

        headers = {"Accept": "application/json"}
        payload, err = self._safe_request(url, headers)
        if err or not isinstance(payload, dict) or payload.get("status") == "error":
            return pd.DataFrame()

        values = payload.get("values", [])
        if not values or not isinstance(values, list):
            return pd.DataFrame()

        meta = payload.get("meta", {})
        currency = meta.get("currency") or self.default_currency
        return normalise_ohlcv(pd.DataFrame(values), source=self.name, symbol=clean_symbol, currency=currency)

    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        """Bulk price fetch interface returning ProviderResult."""
        if not self.is_configured:
            msg = "Twelve Data provider is disabled or missing required API key."
            return ProviderResult(self.name, "prices", "unavailable", msg)

        # Check rate limiter state
        limiter_check = self.limiter.check_limit()
        if not limiter_check.allowed:
            self.last_limiter_state = limiter_check
            msg = f"Twelve Data rate limit reached: {limiter_check.message} (non-blocking)."
            return ProviderResult(self.name, "prices", "unavailable", msg)

        frames: list[pd.DataFrame] = []
        errors: list[str] = []

        for symbol in symbols:
            check = self.limiter.check_limit()
            if not check.allowed:
                self.last_limiter_state = check
                errors.append(f"{symbol}: rate limit reached (non-blocking)")
                break

            df = self.fetch_daily_prices(symbol, start_date, end_date)
            if df.empty:
                errors.append(f"{symbol}: no rows returned")
            else:
                frames.append(df)

        if not frames:
            msg = "Twelve Data returned no usable price rows. " + "; ".join(errors)
            return ProviderResult(self.name, "prices", "unavailable", redact_text(msg))

        data = pd.concat(frames, ignore_index=True).sort_values(["provider_symbol", "date"]).reset_index(drop=True)
        latest = data["date"].max()
        meta = metadata_from_frame(
            data,
            source_name=self.name,
            source_type="prices",
            as_of_date=latest,
            currency=self.default_currency,
            provider_or_manual_source="Twelve Data API",
            staleness_status="unknown",
            notes="; ".join(errors) if errors else "Downloaded from Twelve Data API.",
        )
        status = "ok" if not errors else "unavailable"
        msg = f"Downloaded {len(data)} Twelve Data rows for {data['provider_symbol'].nunique()} instruments."
        if errors:
            msg += " Partial fetch: " + "; ".join(errors)
        return ProviderResult(self.name, "prices", status, redact_text(msg), data, meta)

    def validate_symbol(self, symbol: str) -> bool:
        if not self.is_configured:
            return False
        clean = symbol.strip()
        if not clean:
            return False
        end = date.today()
        start = end.replace(year=end.year - 1)
        try:
            return not self.fetch_daily_prices(clean, start, end).empty
        except Exception:
            return False
