from __future__ import annotations

from pathlib import Path

from etf_cockpit.core.config import DataProvidersConfig, ProviderSection, load_config
from etf_cockpit.data import alphavantage_provider, finnhub_provider, fmp_provider
from etf_cockpit.data import tiingo_provider, twelvedata_provider
from etf_cockpit.data.provider_registry import REQUIRED_PROVIDER_IDS, ProviderRegistry
from etf_cockpit.data.source_policy import load_source_policies


T8_PROVIDER_IDS = {"alphavantage", "fmp", "finnhub", "twelvedata", "tiingo"}


def test_t8_default_registry_is_disabled_offline_and_redacts_loaded_keys(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    repository_root = Path(__file__).resolve().parents[1]
    (config_dir / "data_providers.yaml").write_text(
        (repository_root / "configs" / "data_providers.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for provider_id in T8_PROVIDER_IDS:
        env_prefix = provider_id.upper().replace("-", "_")
        monkeypatch.setenv(f"ETF_COCKPIT_{env_prefix}_PROVIDER", "none")
        monkeypatch.setenv(f"ETF_COCKPIT_{env_prefix}_API_KEY", "")

    network_calls: list[str] = []

    def reject_network(*args, **kwargs):  # type: ignore[no-untyped-def]
        network_calls.append("called")
        raise AssertionError("registry capability probing must not perform network I/O")

    monkeypatch.setattr(alphavantage_provider, "urlopen", reject_network)
    monkeypatch.setattr(fmp_provider, "urlopen", reject_network)
    monkeypatch.setattr(finnhub_provider, "urlopen", reject_network)
    monkeypatch.setattr(twelvedata_provider.requests, "get", reject_network)
    monkeypatch.setattr(tiingo_provider.requests, "get", reject_network)

    config = load_config(config_dir)
    capabilities = ProviderRegistry(config.data_providers).probe_all()
    by_provider = {
        provider_id: [item for item in capabilities if item.provider_id == provider_id]
        for provider_id in T8_PROVIDER_IDS
    }

    assert REQUIRED_PROVIDER_IDS <= {item.provider_id for item in capabilities}
    assert all(by_provider.values())
    assert all(
        item.status == "unavailable"
        and item.entitlement == "disabled"
        and item.authority.value == "vendor"
        and not item.score_eligible
        for items in by_provider.values()
        for item in items
    )
    assert network_calls == []

    keyless_sections = {
        provider_id: ProviderSection(active_provider=provider_id)
        for provider_id in T8_PROVIDER_IDS
    }
    keyless_capabilities = ProviderRegistry(
        DataProvidersConfig(providers=keyless_sections)
    ).probe_all()
    assert all(
        item.status == "unavailable"
        and item.entitlement == "api_key_required"
        and not item.score_eligible
        for item in keyless_capabilities
        if item.provider_id in T8_PROVIDER_IDS
    )
    assert len([item for item in keyless_capabilities if item.provider_id in T8_PROVIDER_IDS]) == len(T8_PROVIDER_IDS)

    keyed_sections = {
        provider_id: ProviderSection(active_provider=provider_id, api_key="local-test-key")
        for provider_id in T8_PROVIDER_IDS
    }
    keyed_capabilities = ProviderRegistry(DataProvidersConfig(providers=keyed_sections)).probe_all()
    assert all(
        item.status == "unavailable" and not item.score_eligible
        for item in keyed_capabilities
        if item.provider_id in T8_PROVIDER_IDS
    )

    policies = {item.provider_id: item for item in load_source_policies()}
    assert T8_PROVIDER_IDS <= policies.keys()
    assert all(
        policies[provider_id].source_tier.value == "optional_commercial"
        and not policies[provider_id].mandatory_allowed
        and policies[provider_id].optional_provider
        and policies[provider_id].quota_failure == "non_blocking"
        for provider_id in T8_PROVIDER_IDS
    )

    keyed_config_dir = tmp_path / "keyed-config"
    keyed_config_dir.mkdir()
    secret = "t8-test-secret"
    monkeypatch.delenv("ETF_COCKPIT_ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ETF_COCKPIT_ALPHAVANTAGE_PROVIDER", raising=False)
    (tmp_path / ".env").write_text(
        f'ETF_COCKPIT_ALPHAVANTAGE_API_KEY="{secret}"\n',
        encoding="utf-8",
    )
    (keyed_config_dir / "data_providers.yaml").write_text(
        'providers:\n  alphavantage:\n    active_provider: alphavantage\n    api_key: ""\n',
        encoding="utf-8",
    )
    keyed_config = load_config(keyed_config_dir)
    redacted = str(keyed_config.data_providers.redacted())
    assert secret not in redacted
    assert "***redacted***" in redacted
    exported_rows = str(ProviderRegistry(keyed_config.data_providers).status_rows())
    assert secret not in exported_rows
