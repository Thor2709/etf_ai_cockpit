from __future__ import annotations

from dataclasses import dataclass

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority


@dataclass(frozen=True)
class OptionalProviderProbe:
    provider_id: str
    status: str
    message: str


class FredProvider:
    name = "fred"

    def __init__(self, api_key: str = "", section: ProviderSection | None = None) -> None:
        self.section = section or ProviderSection(active_provider="fred" if api_key else "none", api_key=api_key)
        self.api_key = api_key or self.section.api_key

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
