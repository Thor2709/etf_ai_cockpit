"""Optional Alpha Vantage verification adapter.

This adapter is deliberately narrower than the canonical price providers.  It
accepts one explicitly selected ticker at a time, keeps a small local replay
cache, and never writes canonical application data.  Alpha Vantage responses
are vendor evidence only and therefore cannot become score or release
authority by themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority, redact_text
from etf_cockpit.data.providers import DataProvider, PriceProvider, ProviderResult


Transport = Callable[..., Any]

_TIME_SERIES_PREFIX = "Time Series"


@dataclass(frozen=True)
class AlphaVantageResult(ProviderResult):
    """Provider result with quota state kept separate from ProviderStatus."""

    quota_exhausted: bool = False


class AlphaVantageProvider(DataProvider, PriceProvider):
    """Fetch one selected ticker from Alpha Vantage under a daily call budget."""

    name = "alphavantage"
    BASE_URL = "https://www.alphavantage.co/query"
    DEFAULT_DAILY_CALL_BUDGET = 5
    execution_allowed = False
    score_authoritative = False

    def __init__(
        self,
        section: ProviderSection | None = None,
        *,
        api_key: str = "",
        cache_dir: Path | None = None,
        transport: Transport | None = None,
        daily_call_budget: int = DEFAULT_DAILY_CALL_BUDGET,
        clock: Callable[[], date | datetime] = date.today,
    ) -> None:
        supplied_key = str(api_key or "").strip()
        self.section = section or ProviderSection(
            active_provider=self.name if supplied_key else "none",
            api_key=supplied_key,
            base_url=self.BASE_URL,
        )
        self.api_key = supplied_key or str(self.section.api_key or "").strip()
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.transport = transport
        if type(daily_call_budget) is not int or daily_call_budget < 1:
            raise ValueError("Alpha Vantage daily call budget must be a positive integer")
        self.daily_call_budget = daily_call_budget
        self._clock = clock
        self._calls_by_day: dict[date, int] = {}
        self._memory_cache: dict[str, pd.DataFrame] = {}

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        active = str(self.section.active_provider or "none").strip().lower()
        enabled = active in {self.name, "alpha_vantage"}
        configured = enabled and bool(self.api_key)
        if not enabled:
            entitlement = "disabled"
            message = "Alpha Vantage verification is disabled; no network request was made."
        elif not self.api_key:
            entitlement = "api_key_required"
            message = "Alpha Vantage verification requires a local API key; no network request was made."
        else:
            entitlement = "configured"
            message = "Alpha Vantage is configured for selected-ticker verification; no network request was made by the probe."
        return (
            ProviderCapability(
                provider_id=self.name,
                dataset_type="prices",
                status="unavailable",
                authority=SourceAuthority.VENDOR,
                configured=configured,
                entitlement=entitlement,
                rate_limit_note=f"selected ticker only; {self.daily_call_budget} call(s) per UTC day",
                last_success_at=None,
                error_fingerprint=None,
                secret_present=bool(self.api_key),
                message=redact_text(message),
            ),
        )

    def fetch_prices(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        *,
        decision_time: date | datetime | None = None,
    ) -> ProviderResult:
        """Verify exactly one selected ticker; bulk refresh is refused."""

        requested = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
        if len(requested) != 1:
            return self._result(
                "unavailable",
                "Alpha Vantage verification accepts exactly one selected ticker; universe-wide and bulk refresh requests are refused.",
            )
        if start_date > end_date:
            return self._result("unavailable", "Alpha Vantage verification start date must not be after the end date.")
        if not self._enabled():
            return self._result("unavailable", "Alpha Vantage verification is disabled; no network request was made.")
        if not self.api_key:
            return self._result("unavailable", "Alpha Vantage verification requires a local API key; no network request was made.")

        symbol = requested[0]
        provider_symbol = str(self.section.symbols_map.get(symbol, symbol)).strip() or symbol
        cached = self._load_cache(provider_symbol)
        today = self._today()
        effective_decision_time = self._decision_time(decision_time)
        used = self._calls_by_day.get(today, 0)
        if used >= self.daily_call_budget:
            return self._replay_or_unavailable(
                cached,
                start_date,
                end_date,
                effective_decision_time,
                f"Alpha Vantage daily call budget exhausted; {self.daily_call_budget} call(s) allowed per UTC day.",
            )
        self._calls_by_day[today] = used + 1

        url = self._request_url(provider_symbol)
        try:
            response = self._request(url)
            if response[1] == 429:
                return self._replay_or_unavailable(cached, start_date, end_date, effective_decision_time, "Alpha Vantage quota exhausted (HTTP 429).")
            if response[1] < 200 or response[1] >= 300:
                return self._replay_or_unavailable(cached, start_date, end_date, effective_decision_time, f"Alpha Vantage request returned HTTP {response[1]}.")
            payload = _decode_json(response[0])
            notice = _quota_notice(payload)
            if notice:
                return self._replay_or_unavailable(cached, start_date, end_date, effective_decision_time, f"Alpha Vantage quota exhausted: {notice}")
            frame = _normalise_payload(
                payload,
                symbol=symbol,
                provider_symbol=provider_symbol,
                available_at=self._observation_time(),
            )
            if frame.empty:
                return self._replay_or_unavailable(cached, start_date, end_date, effective_decision_time, "Alpha Vantage returned no usable daily price rows.")
            self._store_cache(provider_symbol, frame)
            selected = _select_dates(frame, start_date, end_date, effective_decision_time)
            if selected.empty:
                return self._result("unavailable", "Alpha Vantage returned no rows in the requested date range.")
            return self._result("ok", f"Alpha Vantage verification returned {len(selected)} row(s) for the selected ticker.", selected)
        except Exception as exc:
            return self._replay_or_unavailable(
                cached,
                start_date,
                end_date,
                effective_decision_time,
                redact_text(f"Alpha Vantage verification unavailable: {type(exc).__name__}: {exc}"),
            )

    def fetch_daily_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        result = self.fetch_prices([symbol], start, end)
        return result.data.copy() if result.data is not None else pd.DataFrame()

    def verify_ticker(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        *,
        decision_time: date | datetime | None = None,
    ) -> ProviderResult:
        return self.fetch_prices([symbol], start_date, end_date, decision_time=decision_time)

    fetch_selected_ticker = verify_ticker

    def validate_symbol(self, symbol: str) -> bool:
        return bool(str(symbol or "").strip())

    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        return self._result("unavailable", "Alpha Vantage verification is limited to selected ticker prices; FX requests are refused.")

    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        return self._result("unavailable", "Alpha Vantage verification is limited to selected ticker prices; metadata requests are refused.")

    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        return self._result("unavailable", "Alpha Vantage verification is limited to selected ticker prices; holdings requests are refused.")

    def _enabled(self) -> bool:
        return str(self.section.active_provider or "none").strip().lower() in {self.name, "alpha_vantage"}

    def _today(self) -> date:
        value = self._clock()
        return value.date() if isinstance(value, datetime) else value

    def _observation_time(self) -> datetime:
        value = self._clock()
        return value if isinstance(value, datetime) else datetime.combine(value, time.min)

    def _decision_time(self, value: date | datetime | None) -> date | datetime:
        return self._observation_time() if value is None else value

    def _request_url(self, symbol: str) -> str:
        base = str(self.section.base_url or self.BASE_URL).strip() or self.BASE_URL
        if self.api_key:
            base = base.replace(self.api_key, "[REDACTED]")
        return f"{base}?{urlencode({'function': 'TIME_SERIES_DAILY', 'symbol': symbol, 'outputsize': 'full'})}"

    def _request(self, url: str) -> tuple[bytes, int]:
        headers = {"Accept": "application/json", "X-Alpha-Vantage-Api-Key": self.api_key}
        if self.transport is not None:
            try:
                value = self.transport(url, headers, {"api_key": self.api_key})
            except TypeError:
                try:
                    value = self.transport(url, headers)
                except TypeError:
                    value = self.transport(url)
            return _normalise_response(value)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=20.0) as response:
                return bytes(response.read()), int(getattr(response, "status", 200))
        except HTTPError as exc:
            return b"", int(exc.code)

    def _cache_path(self, symbol: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"alpha_vantage_{digest}.json"

    def _load_cache(self, symbol: str) -> pd.DataFrame | None:
        cached = self._memory_cache.get(symbol)
        if cached is not None:
            return cached.copy()
        path = self._cache_path(symbol)
        if path is None or not path.is_file():
            return None
        try:
            frame = _normalise_frame(pd.read_json(path, orient="records"))
        except (OSError, ValueError, TypeError, KeyError):
            return None
        self._memory_cache[symbol] = frame
        return frame.copy()

    def _store_cache(self, symbol: str, frame: pd.DataFrame) -> None:
        self._memory_cache[symbol] = frame.copy()
        path = self._cache_path(symbol)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(frame.to_json(orient="records", date_format="iso"), encoding="utf-8")
        except OSError:
            # A cache write failure is non-blocking; the in-memory response is
            # still valid for the current selected-ticker verification.
            return

    def _replay_or_unavailable(
        self,
        cached: pd.DataFrame | None,
        start_date: date,
        end_date: date,
        decision_time: date | datetime,
        message: str,
    ) -> ProviderResult:
        quota_exhausted = "quota" in message.lower() or "budget" in message.lower()
        if cached is not None:
            replay = _select_dates(cached, start_date, end_date, decision_time)
            if not replay.empty:
                return self._result(
                    "unavailable",
                    redact_text(message) + " Cached verification replay is available.",
                    replay,
                    quota_exhausted=quota_exhausted,
                )
        return self._result("unavailable", redact_text(message), quota_exhausted=quota_exhausted)

    def _result(
        self,
        status: str,
        message: str,
        data: pd.DataFrame | None = None,
        *,
        quota_exhausted: bool = False,
    ) -> ProviderResult:
        safe_message = redact_text(message)
        if self.api_key:
            safe_message = safe_message.replace(self.api_key, "[REDACTED]")
        return AlphaVantageResult(self.name, "prices", status, safe_message, data, quota_exhausted=quota_exhausted)


def _normalise_response(value: Any) -> tuple[bytes, int]:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value), 200
    if isinstance(value, tuple) and len(value) >= 2:
        payload, status = value[:2]
        return _payload_bytes(payload), int(status)
    if isinstance(value, Mapping):
        return json.dumps(value).encode("utf-8"), 200
    if hasattr(value, "read"):
        return bytes(value.read()), int(getattr(value, "status", 200))
    raise TypeError("Alpha Vantage transport must return JSON, bytes, a response tuple or a response object")


def _payload_bytes(value: Any) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value).encode("utf-8")


def _decode_json(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Alpha Vantage response JSON must be an object")
    return value


def _quota_notice(payload: Mapping[str, Any]) -> str | None:
    for key in ("Note", "Information"):
        value = str(payload.get(key) or "").strip()
        if value and ("limit" in value.lower() or "frequency" in value.lower() or "call" in value.lower()):
            return redact_text(value)
    return None


def _normalise_payload(
    payload: Mapping[str, Any],
    *,
    symbol: str,
    provider_symbol: str,
    available_at: datetime,
) -> pd.DataFrame:
    series_key = next((str(key) for key in payload if str(key).startswith(_TIME_SERIES_PREFIX)), None)
    series = payload.get(series_key) if series_key else None
    if not isinstance(series, Mapping):
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for day, values in series.items():
        if not isinstance(values, Mapping):
            continue
        rows.append(
            {
                "date": str(day),
                "etf_id": symbol,
                "open": _number(values.get("1. open")),
                "high": _number(values.get("2. high")),
                "low": _number(values.get("3. low")),
                "close": _number(values.get("4. close")),
                "adjusted_close": _number(values.get("4. close")),
                "volume": _number(values.get("5. volume")),
                "currency": "",
                "provider_symbol": provider_symbol,
                "source": "alphavantage",
                "is_adjusted": False,
                "dividends": None,
                "stock_splits": None,
                "capital_gains": None,
                "known_at": available_at,
                "available_at": available_at,
            }
        )
    return _normalise_frame(pd.DataFrame(rows))


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"], errors="coerce").dt.date
    for column in ("open", "high", "low", "close", "adjusted_close", "volume"):
        if column in output:
            output[column] = pd.to_numeric(output[column], errors="coerce")
    for column in ("known_at", "available_at"):
        if column in output:
            output[column] = pd.to_datetime(output[column], errors="coerce", utc=True).dt.tz_convert(None)
    required = ["date", "open", "high", "low", "close", "adjusted_close"]
    required.extend(["known_at", "available_at"])
    return output.dropna(subset=[column for column in required if column in output]).sort_values("date").reset_index(drop=True)


def _select_dates(
    frame: pd.DataFrame,
    start_date: date,
    end_date: date,
    decision_time: date | datetime,
) -> pd.DataFrame:
    if frame is None or frame.empty or "date" not in frame or "known_at" not in frame or "available_at" not in frame:
        return pd.DataFrame()
    dates = pd.to_datetime(frame["date"], errors="coerce").dt.date
    known = pd.to_datetime(frame["known_at"], errors="coerce", utc=True).dt.tz_convert(None)
    available = pd.to_datetime(frame["available_at"], errors="coerce", utc=True).dt.tz_convert(None)
    cutoff = pd.Timestamp(datetime.combine(decision_time, time.min) if isinstance(decision_time, date) and not isinstance(decision_time, datetime) else decision_time)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert(None)
    return frame.loc[(dates >= start_date) & (dates <= end_date) & (known <= cutoff) & (available <= cutoff)].copy().reset_index(drop=True)


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None
