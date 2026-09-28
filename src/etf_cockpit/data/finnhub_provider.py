"""Disabled-by-default Finnhub adapter with fail-closed historical gates.

Network access is limited to an explicit capability probe.  Each probe must
be enabled, terms-acknowledged, keyed, and supplied with caller-owned request
identifiers.  The adapter never turns a successful entitlement probe into
score or release authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority, redact_text
from etf_cockpit.data.providers import DataProvider, ProviderResult


Transport = Callable[[str, dict[str, str], float], Any]

BASE_URL = "https://finnhub.io/api/v1"
CAPABILITIES = ("prices", "fx", "etf_metadata", "etf_holdings")
_ENDPOINTS = {
    "prices": "/stock/candle",
    "fx": "/forex/candle",
    "etf_metadata": "/etf/profile",
    "etf_holdings": "/etf/holdings",
}
_REQUIRED_REQUEST_FIELDS = {
    "prices": frozenset({"symbol", "resolution", "from", "to"}),
    "fx": frozenset({"symbol", "resolution", "from", "to"}),
    "etf_metadata": frozenset(),
    "etf_holdings": frozenset({"date"}),
}

# Paste each section under the corresponding key in the shared YAML files.
SHARED_CONFIG_BLOCK = '''# configs/data_providers.yaml (under providers:)
  finnhub:
    active_provider: none
    api_key: ""
    base_url: ""
    symbols_map: {}

# configs/data_source_policy.yaml (under sources:)
  - {provider_id: finnhub, dataset_type: prices, source_tier: optional_commercial, mandatory_allowed: false, optional_provider: true, cache_path: data/raw/prices, licence: provider-terms, network_required: true, fair_use_note: Experimental and optional; probes are explicit, quota failures are non-blocking, and the provider has no score or release authority.}
'''


@dataclass(frozen=True)
class _CapabilityEvidence:
    entitled: bool = False
    coverage_start: date | None = None
    coverage_end: date | None = None
    identifiers: tuple[tuple[str, str], ...] = ()
    window_start: date | None = None
    window_end: date | None = None
    reason: str = "Entitlement and historical coverage have not been proven."
    error_fingerprint: str | None = None


class FinnhubProvider(DataProvider):
    """Experimental Finnhub capability probe; historical data stay gated."""

    name = "finnhub"

    def __init__(
        self,
        section: ProviderSection | None = None,
        *,
        enabled: bool = False,
        terms_accepted: bool = False,
        transport: Transport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.section = section or ProviderSection()
        self.enabled = bool(enabled)
        self.terms_accepted = bool(terms_accepted)
        self.transport = transport
        if timeout <= 0:
            raise ValueError("Finnhub timeout must be positive")
        self.timeout = float(timeout)
        self._evidence = {dataset: _CapabilityEvidence() for dataset in CAPABILITIES}

    @property
    def api_key(self) -> str:
        return self.section.api_key.strip()

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return cached or local-only state; this method never performs I/O."""

        return tuple(self._capability(dataset) for dataset in CAPABILITIES)

    def probe_entitlements(
        self,
        requests: Mapping[str, Mapping[str, object]],
    ) -> tuple[ProviderCapability, ...]:
        """Explicitly probe each capability using caller-supplied identifiers.

        ``requests`` is keyed by ``prices``, ``fx``, ``etf_metadata`` and
        ``etf_holdings``.  Missing inputs fail that capability closed; other
        capabilities are still probed independently.
        """

        guard_reason = self._probe_guard_reason()
        if guard_reason:
            self._evidence = {
                dataset: _CapabilityEvidence(reason=guard_reason)
                for dataset in CAPABILITIES
            }
            return self.probe_capabilities()

        for dataset in CAPABILITIES:
            request_values = requests.get(dataset)
            if request_values is None:
                self._evidence[dataset] = _CapabilityEvidence(
                    reason="Capability probe inputs are missing."
                )
                continue
            try:
                params = _validated_probe_params(dataset, request_values)
                status, payload = self._request(dataset, params)
                if status in {401, 403}:
                    self._evidence[dataset] = _CapabilityEvidence(
                        reason="Finnhub denied entitlement for this capability.",
                        error_fingerprint=_fingerprint(f"HTTP {status}: forbidden", self.api_key),
                    )
                    continue
                if status != 200:
                    self._evidence[dataset] = _CapabilityEvidence(
                        reason=f"Finnhub capability probe returned HTTP {status}.",
                        error_fingerprint=_fingerprint(f"HTTP {status}", self.api_key),
                    )
                    continue
                if not isinstance(payload, Mapping):
                    raise ValueError("Finnhub capability response is not a JSON object")
                coverage_start, coverage_end = _coverage(dataset, payload, params)
                coverage_reason = (
                    "Entitlement confirmed; historical coverage metadata is missing."
                    if coverage_start is None or coverage_end is None
                    else "Entitlement and the returned coverage window are recorded; point-in-time metadata is still required."
                )
                identifiers = _probe_identifiers(params)
                window_start, window_end = _probe_window(
                    dataset, params, coverage_start, coverage_end
                )
                self._evidence[dataset] = _CapabilityEvidence(
                    entitled=True,
                    coverage_start=coverage_start,
                    coverage_end=coverage_end,
                    identifiers=identifiers,
                    window_start=window_start,
                    window_end=window_end,
                    reason=coverage_reason,
                )
            except Exception as exc:
                safe_error = _safe_error(exc, self.api_key)
                self._evidence[dataset] = _CapabilityEvidence(
                    reason=f"Finnhub capability probe failed: {type(exc).__name__}.",
                    error_fingerprint=_fingerprint(safe_error, self.api_key),
                )
        return self.probe_capabilities()

    def validate_historical_data(
        self,
        dataset_type: str,
        frame: pd.DataFrame,
        *,
        start_date: date,
        end_date: date,
        decision_time: datetime,
    ) -> ProviderResult:
        """Accept only rows with provider entitlement, coverage, and PIT times."""

        dataset = str(dataset_type).strip().lower()
        if dataset not in CAPABILITIES:
            return self._unavailable(dataset, "Capability is not supported by Finnhub.")
        evidence = self._evidence[dataset]
        if not evidence.entitled:
            return self._unavailable(dataset, f"Historical use rejected: {evidence.reason}")
        if evidence.coverage_start is None or evidence.coverage_end is None:
            return self._unavailable(dataset, "Historical use rejected: proven time coverage is missing.")
        if start_date < evidence.coverage_start or end_date > evidence.coverage_end:
            return self._unavailable(dataset, "Historical use rejected: requested dates exceed proven time coverage.")
        if (
            evidence.window_start is None
            or evidence.window_end is None
            or start_date < evidence.window_start
            or end_date > evidence.window_end
        ):
            return self._unavailable(dataset, "Historical use rejected: requested dates exceed the probed request window.")
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            return self._unavailable(dataset, "Historical use rejected: decision time must be timezone-aware.")
        required = {"date", "known_at", "available_at"}
        if not required <= set(frame.columns):
            missing = ", ".join(sorted(required - set(frame.columns)))
            return self._unavailable(dataset, f"Historical use rejected: point-in-time metadata is missing ({missing}).")
        if frame.empty:
            return self._unavailable(dataset, "Historical use rejected: no rows were returned.")
        if not _frame_matches_identifiers(frame, evidence.identifiers):
            return self._unavailable(dataset, "Historical use rejected: row identifiers do not match the probed request.")

        try:
            row_dates = pd.to_datetime(frame["date"], errors="raise").dt.date
        except (TypeError, ValueError, AttributeError):
            return self._unavailable(dataset, "Historical use rejected: row dates are invalid.")
        if row_dates.isna().any() or any(day < start_date or day > end_date for day in row_dates):
            return self._unavailable(dataset, "Historical use rejected: row dates exceed the requested coverage window.")

        for field in ("known_at", "available_at"):
            timestamps = _aware_timestamp_series(frame[field])
            if timestamps is None:
                return self._unavailable(dataset, f"Historical use rejected: {field} is missing or invalid point-in-time metadata.")
            if (timestamps > pd.Timestamp(decision_time).tz_convert("UTC")).any():
                return self._unavailable(dataset, f"Historical use rejected: {field} is after the decision time.")
        return ProviderResult(
            self.name,
            dataset,
            "ok",
            "Historical rows passed entitlement, coverage, and point-in-time checks; source authority remains vendor-only.",
            frame.copy(),
        )

    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        return self._unavailable("prices", "Data acquisition is withheld until an explicit PIT-safe mapping is available.")

    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        return self._unavailable("fx", "Data acquisition is withheld until an explicit PIT-safe mapping is available.")

    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        return self._unavailable("etf_metadata", "Data acquisition is withheld until an explicit PIT-safe mapping is available.")

    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        return self._unavailable("etf_holdings", "Data acquisition is withheld until an explicit PIT-safe mapping is available.")

    def _probe_guard_reason(self) -> str:
        if not self.enabled:
            return "Finnhub experimental adapter is disabled; probe skipped."
        if not self.terms_accepted:
            return "Finnhub terms must be acknowledged before a probe."
        if not self.api_key:
            return "Finnhub API key is not configured."
        active = (self.section.active_provider or "none").strip().lower()
        if active != self.name:
            return "Finnhub is not the active provider in local configuration."
        return ""

    def _capability(self, dataset: str) -> ProviderCapability:
        evidence = self._evidence[dataset]
        active = (self.section.active_provider or "none").strip().lower() == self.name
        configured = active and bool(self.api_key)
        if not self.enabled:
            entitlement = "disabled"
            message = "Finnhub experimental adapter is disabled; probe skipped."
        elif not self.terms_accepted:
            entitlement = "terms_required"
            message = "Finnhub terms must be acknowledged before a probe."
        elif not configured:
            entitlement = "api_key_required" if not self.api_key else "inactive"
            message = "Finnhub is not active and keyed in local configuration."
        elif evidence.entitled:
            entitlement = "entitled"
            message = evidence.reason
        else:
            entitlement = "unknown"
            message = evidence.reason
        status = "unavailable"
        if "denied entitlement" in evidence.reason.lower() and self.enabled and self.terms_accepted:
            status = "forbidden"
            entitlement = "forbidden"
            message = evidence.reason
        message = f"{message} No score or release authority."
        return ProviderCapability(
            provider_id=self.name,
            dataset_type=dataset,
            status=status,
            authority=SourceAuthority.VENDOR,
            configured=configured,
            entitlement=entitlement,
            rate_limit_note="experimental optional source; quota failures are non-blocking",
            last_success_at=None,
            error_fingerprint=evidence.error_fingerprint,
            secret_present=bool(self.api_key),
            message=redact_text(message),
        )

    def _request(self, dataset: str, params: Mapping[str, object]) -> tuple[int, object]:
        query = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{BASE_URL}{_ENDPOINTS[dataset]}?{query}"
        headers = {"Accept": "application/json", "X-Finnhub-Token": self.api_key}
        transport = self.transport or _urlopen_transport
        try:
            response = transport(url, headers, self.timeout)
        except HTTPError as exc:
            return int(exc.code), exc.read()
        status, body = _response_parts(response)
        if status in {401, 403}:
            return status, body
        if isinstance(body, Mapping):
            return status, body
        if isinstance(body, str):
            body = body.encode("utf-8")
        if not isinstance(body, bytes):
            raise ValueError("Finnhub response body is not JSON bytes")
        try:
            return status, json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Finnhub returned invalid JSON") from exc

    @staticmethod
    def _unavailable(dataset: str, reason: str) -> ProviderResult:
        return ProviderResult("finnhub", dataset, "unavailable", reason)


def _validated_probe_params(dataset: str, raw: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "prices": frozenset({"symbol", "resolution", "from", "to"}),
        "fx": frozenset({"symbol", "resolution", "from", "to"}),
        "etf_metadata": frozenset({"symbol", "isin"}),
        "etf_holdings": frozenset({"symbol", "isin", "date"}),
    }.get(dataset)
    if allowed is None or set(raw) - allowed:
        raise ValueError("probe request contains unsupported fields")
    params = {key: value for key, value in raw.items() if key in allowed}
    if dataset in {"prices", "fx"}:
        missing = _REQUIRED_REQUEST_FIELDS[dataset] - set(params)
        if missing:
            raise ValueError(f"probe request is missing required {dataset} fields")
        start = _unix_timestamp(params["from"])
        end = _unix_timestamp(params["to"])
        if start >= end:
            raise ValueError("probe request time window is invalid")
        params["from"] = start
        params["to"] = end
    elif dataset in {"etf_metadata", "etf_holdings"}:
        if not params.get("symbol") and not params.get("isin"):
            raise ValueError("ETF probe requires a caller-supplied symbol or ISIN")
        if dataset == "etf_holdings":
            missing = _REQUIRED_REQUEST_FIELDS[dataset] - set(params)
            if missing:
                raise ValueError("ETF holdings probe requires an explicit date")
            params["date"] = date.fromisoformat(str(params["date"])).isoformat()
    else:
        raise ValueError("unknown Finnhub capability")
    return params


def _unix_timestamp(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("probe timestamp is invalid")
    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("probe timestamp is invalid") from exc
    if timestamp < 0:
        raise ValueError("probe timestamp is invalid")
    return timestamp


def _probe_identifiers(params: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    identifiers: list[tuple[str, str]] = []
    for key in ("symbol", "isin"):
        if key not in params:
            continue
        value = params[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("probe identifier is missing or invalid")
        identifiers.append((key, value.strip().casefold()))
    return tuple(identifiers)


def _probe_window(
    dataset: str,
    params: Mapping[str, object],
    coverage_start: date | None,
    coverage_end: date | None,
) -> tuple[date | None, date | None]:
    if dataset in {"prices", "fx"}:
        try:
            start = datetime.fromtimestamp(int(params["from"]), timezone.utc).date()
            end = datetime.fromtimestamp(int(params["to"]), timezone.utc).date()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return None, None
        return start, end
    if dataset == "etf_holdings":
        try:
            requested = date.fromisoformat(str(params["date"]))
        except (KeyError, TypeError, ValueError):
            return None, None
        return requested, requested
    return coverage_start, coverage_end


def _frame_matches_identifiers(
    frame: pd.DataFrame,
    identifiers: tuple[tuple[str, str], ...],
) -> bool:
    if not identifiers:
        return False
    for column, expected in identifiers:
        if column not in frame.columns:
            return False
        values = frame[column]
        if values.isna().any():
            return False
        if any(str(value).strip().casefold() != expected for value in values):
            return False
    return True


def _coverage(
    dataset: str,
    payload: Mapping[str, object],
    params: Mapping[str, object],
) -> tuple[date | None, date | None]:
    if dataset in {"prices", "fx"}:
        timestamps = payload.get("t")
        if str(payload.get("s", "")).lower() != "ok" or not isinstance(timestamps, list) or not timestamps:
            return None, None
        try:
            observed = sorted(_unix_timestamp(value) for value in timestamps)
            start_ts = int(params["from"])
            end_ts = int(params["to"])
        except (TypeError, ValueError, KeyError):
            return None, None
        if observed[0] > start_ts or observed[-1] < end_ts:
            return None, None
        return (
            datetime.fromtimestamp(observed[0], timezone.utc).date(),
            datetime.fromtimestamp(observed[-1], timezone.utc).date(),
        )
    if dataset == "etf_holdings":
        observed = payload.get("atDate")
        try:
            observed_date = date.fromisoformat(str(observed))
            requested_date = date.fromisoformat(str(params["date"]))
        except (TypeError, ValueError, KeyError):
            return None, None
        return (observed_date, observed_date) if observed_date == requested_date else (None, None)
    for key in ("asOfDate", "as_of_date", "atDate"):
        value = payload.get(key)
        if value:
            try:
                observed = date.fromisoformat(str(value))
            except ValueError:
                continue
            return observed, observed
    return None, None


def _response_parts(response: Any) -> tuple[int, object]:
    if isinstance(response, tuple) and len(response) >= 2:
        body, status = response[0], response[1]
        return int(status), body
    if hasattr(response, "read"):
        status = getattr(response, "status", None) or getattr(response, "code", 200)
        return int(status), response.read()
    if isinstance(response, Mapping):
        return 200, response
    if isinstance(response, (bytes, str)):
        return 200, response
    raise ValueError("Finnhub transport returned a malformed response")


def _urlopen_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[bytes, int]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "finnhub.io":
        raise ValueError("Finnhub request URL must use the official HTTPS host")
    with urlopen(Request(url, headers=headers, method="GET"), timeout=timeout) as response:
        return response.read(), int(response.status)


def _aware_timestamp_series(values: pd.Series) -> pd.Series | None:
    converted: list[pd.Timestamp] = []
    try:
        for value in values:
            stamp = pd.Timestamp(value)
            if pd.isna(stamp) or stamp.tzinfo is None or stamp.utcoffset() is None:
                return None
            converted.append(stamp.tz_convert("UTC"))
    except (TypeError, ValueError, OverflowError):
        return None
    return pd.Series(converted, index=values.index, dtype="datetime64[ns, UTC]")


def _safe_error(exc: Exception, api_key: str) -> str:
    message = str(exc)
    if api_key:
        message = message.replace(api_key, "***redacted***")
    return redact_text(message)


def _fingerprint(message: str, api_key: str) -> str:
    safe_message = message.replace(api_key, "***redacted***") if api_key else message
    return hashlib.sha256(safe_message.encode("utf-8", errors="replace")).hexdigest()[:16]


__all__ = ["BASE_URL", "CAPABILITIES", "SHARED_CONFIG_BLOCK", "FinnhubProvider"]
