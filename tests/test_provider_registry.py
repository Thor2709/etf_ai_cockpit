from __future__ import annotations

from etf_cockpit.core.config import DataProvidersConfig, ProviderSection
from etf_cockpit.data.provider_registry import ProviderRegistry


def test_disabled_provider_is_not_probed() -> None:
    config = DataProvidersConfig(providers={"fred": ProviderSection(active_provider="none")})
    registry = ProviderRegistry(config)
    calls: list[str] = []
    registry.register_probe("fred", lambda: calls.append("fred"))
    capabilities = registry.probe_all()
    assert calls == []
    assert capabilities[0].status == "unavailable"


def test_missing_key_is_unavailable_and_ok_capabilities_are_score_eligible() -> None:
    config = DataProvidersConfig(providers={"fred": ProviderSection(active_provider="fred", base_url="https://api.stlouisfed.org")})
    registry = ProviderRegistry(config)
    capabilities = registry.probe_all()
    assert any(item.provider_id == "fred" and item.status == "unavailable" for item in capabilities)
    assert all(not item.score_eligible for item in capabilities if item.provider_id == "fred")


def test_injected_probe_can_return_ok_without_exposing_secret() -> None:
    config = DataProvidersConfig(providers={"manual": ProviderSection(active_provider="manual_local")})
    registry = ProviderRegistry(config)
    registry.register_probe("manual", lambda: {"status": "ok", "message": "local fixture loaded"})
    capabilities = registry.probe_all()
    item = next(item for item in capabilities if item.provider_id == "manual")
    assert item.status == "ok"
    assert item.score_eligible is True
    assert "api_key" not in str(item.to_dict()).lower()
