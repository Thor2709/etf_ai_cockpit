from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from dataclasses import replace
from typing import Callable

from etf_cockpit.core.config import DataProvidersConfig
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority


Probe = Callable[[], object]


class ProviderRegistry:
    """Capability probes that never turn optional providers into startup dependencies."""

    def __init__(self, config: DataProvidersConfig) -> None:
        self.config = config
        self._probes: dict[str, Probe] = {}

    def register_probe(self, provider_id: str, probe: Probe) -> None:
        self._probes[str(provider_id)] = probe

    def probe_all(self) -> tuple[ProviderCapability, ...]:
        provider_ids = sorted(set(self.config.providers) | set(self._probes))
        return tuple(self._probe(provider_id) for provider_id in provider_ids)

    def _probe(self, provider_id: str) -> ProviderCapability:
        section = self.config.section(provider_id)
        active = (section.active_provider or "none").strip().lower()
        configured = active not in {"", "none"}
        authority = SourceAuthority.OFFICIAL if active in {"sec_edgar", "filings_xbrl_org"} else SourceAuthority.VENDOR
        base = ProviderCapability(
            provider_id=provider_id,
            dataset_type=provider_id,
            status="unavailable",
            authority=authority,
            configured=configured,
            entitlement="unknown",
            rate_limit_note="probe not run",
            last_success_at=None,
            error_fingerprint=None,
            secret_present=bool(section.api_key),
        )
        if not configured:
            return base.with_status("unavailable", message="Provider disabled by configuration.")
        if active not in {"yfinance", "manual_local", "manual_local_file", "sec_edgar", "rss", "stooq"} and not section.api_key:
            return base.with_status("unavailable", message="Provider requires a configured API key.")
        probe = self._probes.get(provider_id)
        if probe is None:
            return base.with_status("unavailable", message="No capability probe registered; no network call was made.")
        try:
            result = probe()
            if isinstance(result, dict):
                status = str(result.get("status") or "unavailable")
                message = str(result.get("message") or "")
            else:
                status = "ok" if result is not False else "unavailable"
                message = "Injected capability probe completed." if status == "ok" else "Injected capability probe unavailable."
            now = datetime.now(timezone.utc).isoformat(timespec="seconds") if status == "ok" else None
            return replace(base, status=status, last_success_at=now, error_fingerprint=None, message=message)
        except Exception as exc:
            return replace(
                base,
                status="error",
                error_fingerprint=hashlib.sha256(f"{type(exc).__name__}:{exc}".encode()).hexdigest()[:16],
                message=f"Capability probe failed: {type(exc).__name__}",
            )
