from __future__ import annotations

from etf_cockpit.data.fred_provider import FredProvider
from etf_cockpit.data.rss_provider import RssProvider
from etf_cockpit.core.config import DataProvidersConfig, ProviderSection
from etf_cockpit.data.provider_registry import ProviderRegistry
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.data.stooq_provider import StooqProvider


def test_optional_providers_are_disabled_by_default() -> None:
    assert FredProvider().probe().status == "unavailable"
    assert RssProvider().probe().status == "unavailable"


def test_optional_provider_adapters_expose_task8_capabilities_without_network() -> None:
    assert FredProvider().probe_capabilities()[0].status == "unavailable"
    assert RssProvider().probe_capabilities()[0].status == "unavailable"
    config = DataProvidersConfig(providers={
        "fred": ProviderSection(active_provider="none"),
        "rss": ProviderSection(active_provider="none"),
        "stooq": ProviderSection(active_provider="none"),
        "sec_edgar": ProviderSection(active_provider="none"),
    })
    statuses = {row.provider_id: row for row in ProviderRegistry(config).probe_all()}
    for provider_id in ("fred", "rss", "stooq", "sec_edgar"):
        assert statuses[provider_id].status == "unavailable"
        assert statuses[provider_id].score_eligible is False


def test_configured_optional_probes_are_visible_but_do_not_fetch(tmp_path) -> None:
    config = DataProvidersConfig(providers={
        "fred": ProviderSection(active_provider="fred", api_key="local-key"),
        "rss": ProviderSection(active_provider="rss"),
        "stooq": ProviderSection(active_provider="stooq"),
        "sec_edgar": ProviderSection(active_provider="sec_edgar"),
    })
    registry = ProviderRegistry(config)
    registry.register_adapter("fred", FredProvider(section=config.providers["fred"]))
    registry.register_adapter("rss", RssProvider(("https://example.invalid/feed",), section=config.providers["rss"]))
    registry.register_adapter("stooq", StooqProvider(config.providers["stooq"]))
    sec = SecEdgarProvider("ETF AI Cockpit tests research@openai.com", cache_dir=tmp_path)
    registry.register_adapter("sec_edgar", sec)
    statuses = {item.provider_id: item for item in registry.probe_all()}
    assert statuses["fred"].configured is True
    assert statuses["fred"].status == "unavailable"
    assert statuses["rss"].status == "unavailable"
    assert statuses["stooq"].status == "unavailable"
    assert statuses["sec_edgar"].status == "unavailable"
