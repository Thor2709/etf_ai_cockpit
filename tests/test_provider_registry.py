from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import DataProvidersConfig, ProviderSection, load_config
from etf_cockpit.data.contracts import ProviderCapability
import etf_cockpit.data.provider_registry as provider_registry
from etf_cockpit.data.provider_registry import ProviderRegistry
from etf_cockpit.data.providers import GenericHTTPProvider, ManualLocalFileProvider
from etf_cockpit.data import trust_artifacts


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


def test_registry_covers_canonical_provider_ids_and_disabled_providers_never_probe() -> None:
    required_provider_ids = getattr(provider_registry, "REQUIRED_PROVIDER_IDS", ())
    assert required_provider_ids
    config = DataProvidersConfig(providers={"fred": ProviderSection(active_provider="none")})
    registry = ProviderRegistry(config)
    calls: list[str] = []
    for provider_id in required_provider_ids:
        registry.register_probe(provider_id, lambda provider_id=provider_id: calls.append(provider_id))

    capabilities = registry.probe_all()
    assert required_provider_ids <= {item.provider_id for item in capabilities}
    assert calls == []
    assert all(item.status == "unavailable" for item in capabilities)


def test_registry_normalises_probe_states_and_maps_failures_without_leaking_errors() -> None:
    config = DataProvidersConfig(
        providers={
            "ok": ProviderSection(active_provider="manual_local"),
            "limited": ProviderSection(active_provider="manual_local"),
            "timed": ProviderSection(active_provider="manual_local"),
            "bad": ProviderSection(active_provider="manual_local"),
        }
    )
    registry = ProviderRegistry(config)
    registry.register_probe("ok", lambda: {"status": "ok", "message": "fixture"})
    registry.register_probe("limited", lambda: {"status": "rate_limited", "message": "quota"})
    registry.register_probe("timed", lambda: (_ for _ in ()).throw(TimeoutError("token=secret")))
    registry.register_probe("bad", lambda: ["malformed"])

    states = {item.provider_id: item for item in registry.probe_all()}
    assert states["ok"].status == "ok"
    assert states["limited"].status == "rate_limited"
    assert states["timed"].status == "timeout"
    assert states["bad"].status == "malformed"
    assert "token=secret" not in str(states["timed"].to_dict())


def test_registry_preserves_forbidden_probe_state_without_score_or_execution_authority() -> None:
    config = DataProvidersConfig(providers={"forbidden": ProviderSection(active_provider="manual_local")})
    registry = ProviderRegistry(config)
    registry.register_probe("forbidden", lambda: {"status": "forbidden", "message": "Provider access is forbidden."})

    capability = next(item for item in registry.probe_all() if item.provider_id == "forbidden")
    row = next(item for item in registry.status_rows((capability,)))

    assert capability.status == "forbidden"
    assert capability.score_eligible is False
    assert row["score_eligible"] is False
    assert row.get("executable_authority", False) is False


def test_registry_persists_versioned_probe_results_atomically_without_secrets(tmp_path) -> None:
    config = DataProvidersConfig(
        providers={"fred": ProviderSection(active_provider="fred", api_key="super-secret", base_url="https://fred")}
    )
    registry = ProviderRegistry(config)
    registry.register_probe("fred", lambda: {"status": "ok", "message": "ready"})

    path = registry.persist_probe_results(tmp_path / "provider_probe_results.parquet")
    assert path.exists()
    assert path.with_suffix(".csv").exists()
    frame = pd.read_parquet(path)
    assert frame.attrs.get("schema_version") == "provider_probe_results.v1"
    assert "super-secret" not in path.read_bytes().decode("latin1", errors="ignore")
    assert "super-secret" not in path.with_suffix(".csv").read_text(encoding="utf-8")
    assert {"provider_id", "status", "authority", "score_eligible"} <= set(frame.columns)


def test_data_provider_adapters_expose_non_network_probe_contract() -> None:
    for provider in (ManualLocalFileProvider(), GenericHTTPProvider()):
        capabilities = provider.probe_capabilities()
        assert isinstance(capabilities, tuple)
        assert capabilities
        assert all(isinstance(item, ProviderCapability) for item in capabilities)
        assert all(item.status == "unavailable" for item in capabilities)


def test_startup_probe_writer_persists_versioned_registry_rows_and_legacy_columns(tmp_path, monkeypatch) -> None:
    path = tmp_path / "provider_probe_results.parquet"
    monkeypatch.setattr(trust_artifacts, "PROVIDER_PROBE_PATH", path)
    config = load_config()
    config = config.model_copy(
        update={
            "data_providers": DataProvidersConfig(
                providers={
                    **config.data_providers.providers,
                    "fred": ProviderSection(active_provider="fred", api_key="super-secret", base_url="https://fred"),
                }
            )
        }
    )

    written = trust_artifacts.write_provider_probe_results(config)
    frame = pd.read_parquet(written)
    csv_text = written.with_suffix(".csv").read_text(encoding="utf-8")

    assert frame["schema_version"].eq(provider_registry.PROBE_SCHEMA_VERSION).all()
    assert frame.attrs["schema_version"] == provider_registry.PROBE_SCHEMA_VERSION
    assert {
        "authority",
        "configured",
        "entitlement",
        "rate_limit_note",
        "last_success_at",
        "error_fingerprint",
        "score_eligible",
        "schema_version",
        "provider_name",
        "source_authority",
        "active_provider",
        "enabled",
        "requires_api_key",
        "has_api_key",
        "base_url_configured",
        "capabilities",
        "last_probe_at",
        "executable_authority",
    } <= set(frame.columns)
    csv_frame = pd.read_csv(written.with_suffix(".csv"))
    assert set(frame.columns) == set(csv_frame.columns)
    assert "super-secret" not in csv_text
    assert "super-secret" not in written.read_bytes().decode("latin1", errors="ignore")
