from __future__ import annotations

from dataclasses import dataclass

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority


@dataclass(frozen=True)
class RssProbe:
    provider_id: str
    status: str
    message: str


class RssProvider:
    name = "rss"

    def __init__(self, feeds: tuple[str, ...] = (), section: ProviderSection | None = None) -> None:
        self.feeds = tuple(feeds)
        self.section = section or ProviderSection(active_provider="rss" if self.feeds else "none")

    def probe(self) -> RssProbe:
        if not self.feeds:
            return RssProbe("rss", "unavailable", "RSS is disabled until an explicit local feed list is configured.")
        return RssProbe("rss", "configured", "RSS feed list configured; no network request was made by the probe.")

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        configured = bool(self.feeds) and (self.section.active_provider or "none").strip().lower() not in {"", "none"}
        probe = self.probe()
        return (ProviderCapability(
            provider_id="rss",
            dataset_type="news",
            status="unavailable",
            authority=SourceAuthority.COMMUNITY,
            configured=configured,
            entitlement="configured" if configured else "disabled",
            rate_limit_note="probe only; no network request",
            last_success_at=None,
            error_fingerprint=None,
            secret_present=False,
            message=probe.message,
        ),)
