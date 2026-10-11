"""Tiingo OHLCV market data adapter.

Provides daily, intraday, and adjusted OHLCV data with corporate actions
(splits, dividends), per-provider rate limiting, credential redaction,
and normalisation to the canonical cockpit schema. Optional fallback provider.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import json
import os
from typing import Any

import pandas as pd
import requests

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.core.values import years_before
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority, redact_text
from etf_cockpit.data.ohlcv_discrepancy import normalise_ohlcv
from etf_cockpit.data.provenance import metadata_from_frame
from etf_cockpit.data.providers import DataProvider, PriceProvider, ProviderResult
from etf_cockpit.data.twelvedata_provider import RateLimiter, RateLimitState

DEFAULT_BASE_URL = "https://api.tiingo.com"
FREE_TIER_CALLS_PER_HOUR = 50
FREE_TIER_CALLS_PER_DAY = 1000


class TiingoProvider(DataProvider, PriceProvider):
    """Tiingo adapter for daily, intraday and split-adjusted OHLCV data."""

    name = "tiingo"
    authority = SourceAuthority.VENDOR
    supported_intervals = ("1min", "5min", "15min", "30min", "1hour", "4hour", "1day")

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
            or os.getenv("ETF_COCKPIT_TIINGO_API_KEY", "")
        ).strip()
        self.base_url = (base_url or self.section.base_url or DEFAULT_BASE_URL).rstrip("/")
        self.limiter = limiter or RateLimiter(
            calls_per_hour=FREE_TIER_CALLS_PER_HOUR,
            calls_per_day=FREE_TIER_CALLS_PER_DAY,
        )
        self.transport = transport
        self.default_currency = default_currency
        self.last_limiter_state: RateLimitState | None = None

    @property
    def is_configured(self) -> bool:
        active = (self.section.active_provider or "none").strip().lower()
        return active == self.name and bool(self._api_key)

    def _redact(self, text: str) -> str:
        redacted = redact_text(text)
        if self._api_key:
            redacted = redacted.replace(self._api_key, "***redacted***")
        return redacted

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        active = (self.section.active_provider or "none").strip().lower()
        is_active = active == self.name
        has_key = bool(self._api_key)

        if not is_active:
            status = "unavailable"
            entitlement = "disabled"
            message = "Tiingo is optional and disabled by configuration; no network request was made."
        elif not has_key:
            status = "unavailable"
            entitlement = "api_key_required"
            message = "Tiingo requires an API key (ETF_COCKPIT_TIINGO_API_KEY); none configured."
        else:
            status = "unavailable"
            entitlement = "free_tier"
            message = "Tiingo is configured for optional daily, intraday, and adjusted OHLCV; no score or release authority."

        return (
            ProviderCapability(
                provider_id=self.name,
                dataset_type="prices",
                status=status,
                authority=self.authority,
                configured=is_active and has_key,
                entitlement=entitlement,
                rate_limit_note=(
                    f"Free tier: {FREE_TIER_CALLS_PER_HOUR} requests/hour, {FREE_TIER_CALLS_PER_DAY} requests/day. "
                    "Daily, intraday, and split/dividend-adjusted OHLCV supported; non-blocking quota exhaustion."
                ),
                last_success_at=None,
                error_fingerprint=None,
                secret_present=has_key,
                message=self._redact(message),
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
                return None, f"HTTP 429: {self._redact(response.text)}"
            response.raise_for_status()
            return response.json(), None
        except Exception as exc:
            return None, self._redact(f"{type(exc).__name__}: {exc}")

    def fetch_daily_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch daily OHLCV from Tiingo and normalise to canonical schema."""
        if not self.is_configured:
            return pd.DataFrame()

        state = self.limiter.acquire()
        self.last_limiter_state = state
        if not state.allowed:
            return pd.DataFrame()

        clean_symbol = symbol.strip()
        url = (
            f"{self.base_url}/tiingo/daily/{clean_symbol}/prices?"
            f"startDate={start:%Y-%m-%d}&endDate={end:%Y-%m-%d}"
        )
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload, err = self._safe_request(url, headers)
        if err or not isinstance(payload, list) or not payload:
            return pd.DataFrame()

        raw_df = pd.DataFrame(payload)
        return normalise_ohlcv(raw_df, source=self.name, symbol=clean_symbol, currency=self.default_currency)

    def fetch_intraday_prices(
        self,
        symbol: str,
        interval: str = "5min",
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Fetch intraday OHLCV from Tiingo IEX endpoint."""
        if not self.is_configured:
            return pd.DataFrame()

        state = self.limiter.acquire()
        self.last_limiter_state = state
        if not state.allowed:
            return pd.DataFrame()

        clean_symbol = symbol.strip()
        url = f"{self.base_url}/iex/{clean_symbol}/prices?resampleFreq={interval}"
        if start:
            url += f"&startDate={start:%Y-%m-%d}"
        if end:
            url += f"&endDate={end:%Y-%m-%d}"

        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload, err = self._safe_request(url, headers)
        if err or not isinstance(payload, list) or not payload:
            return pd.DataFrame()

        return normalise_ohlcv(pd.DataFrame(payload), source=self.name, symbol=clean_symbol, currency=self.default_currency)

    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        """Bulk price fetch interface returning ProviderResult."""
        if not self.is_configured:
            msg = "Tiingo provider is disabled or missing required API key."
            return ProviderResult(self.name, "prices", "unavailable", msg)

        # Check rate limiter state
        limiter_check = self.limiter.check_limit()
        if not limiter_check.allowed:
            self.last_limiter_state = limiter_check
            msg = f"Tiingo rate limit reached: {limiter_check.message} (non-blocking)."
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
            msg = "Tiingo returned no usable price rows. " + "; ".join(errors)
            return ProviderResult(self.name, "prices", "unavailable", self._redact(msg))

        data = pd.concat(frames, ignore_index=True).sort_values(["provider_symbol", "date"]).reset_index(drop=True)
        latest = data["date"].max()
        meta = metadata_from_frame(
            data,
            source_name=self.name,
            source_type="prices",
            as_of_date=latest,
            currency=self.default_currency,
            provider_or_manual_source="Tiingo API",
            staleness_status="unknown",
            notes="; ".join(errors) if errors else "Downloaded from Tiingo API.",
        )
        status = "ok" if not errors else "unavailable"
        msg = f"Downloaded {len(data)} Tiingo rows for {data['provider_symbol'].nunique()} instruments."
        if errors:
            msg += " Partial fetch: " + "; ".join(errors)
        return ProviderResult(self.name, "prices", status, self._redact(msg), data, meta)

    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        """Explicit unavailable status for unsupported FX dataset."""
        return ProviderResult(
            self.name,
            "fx",
            "unavailable",
            "Tiingo adapter does not implement FX dataset fetching in this profile.",
        )

    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        """Explicit unavailable status for unsupported ETF metadata dataset."""
        return ProviderResult(
            self.name,
            "etf_metadata",
            "unavailable",
            "Tiingo adapter does not implement ETF metadata fetching.",
        )

    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        """Explicit unavailable status for unsupported ETF holdings dataset."""
        return ProviderResult(
            self.name,
            "etf_holdings",
            "unavailable",
            "Tiingo adapter does not implement ETF holdings fetching.",
        )

    def validate_symbol(self, symbol: str) -> bool:
        if not self.is_configured:
            return False
        clean = symbol.strip()
        if not clean:
            return False
        end = date.today()
        start = years_before(end, 1)
        try:
            return not self.fetch_daily_prices(clean, start, end).empty
        except Exception:
            return False
