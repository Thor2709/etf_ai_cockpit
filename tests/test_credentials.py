from __future__ import annotations

import logging
import os

import pandas as pd
import pytest

from etf_cockpit.core.config import DataProvidersConfig, ProviderSection, resolve_provider_api_key
from etf_cockpit.core.exceptions import ConfigError
from etf_cockpit.data import provider_registry
from etf_cockpit.data.provider_registry import ProviderRegistry
from etf_cockpit.security import credentials
from etf_cockpit.security.credentials import CredentialVault, CredentialVaultError
from etf_cockpit.security.policy import redact_secrets


_SECRET = "credential-sentinel-do-not-disclose"


def _stub_dpapi(monkeypatch: pytest.MonkeyPatch) -> None:
    def transform(payload: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in payload)

    monkeypatch.setattr(credentials, "_protect", transform)
    monkeypatch.setattr(credentials, "_unprotect", transform)


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is available only on Windows")
def test_dpapi_secret_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_registry, "DEFAULT_PROBE_PATH", tmp_path / "probes.parquet")
    vault_path = tmp_path / "vault.dpapi"
    vault = CredentialVault(vault_path)

    vault.set("fred", _SECRET)

    assert vault.get("fred") == _SECRET
    assert _SECRET.encode() not in vault_path.read_bytes()


def test_secret_redacted_from_exports_and_logs(tmp_path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    _stub_dpapi(monkeypatch)
    monkeypatch.setattr(provider_registry, "DEFAULT_PROBE_PATH", tmp_path / "probes.parquet")
    vault = CredentialVault(tmp_path / "vault.dpapi")

    with caplog.at_level(logging.DEBUG):
        vault.set("fred", _SECRET)
        assert vault.get("fred") == _SECRET

    assert _SECRET not in caplog.text
    assert _SECRET not in str(redact_secrets({"provider": {"api_key": _SECRET}}))


def test_no_key_provider_operates_without_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider_registry,
        "resolve_provider_api_key",
        lambda _provider: pytest.fail("keyless provider must not consult the vault"),
    )
    calls: list[str] = []
    registry = ProviderRegistry(
        DataProvidersConfig(providers={"manual": ProviderSection(active_provider="manual_local")})
    )
    registry.register_probe("manual", lambda: calls.append("manual") or {"status": "ok"})

    capability = next(item for item in registry.probe_all() if item.provider_id == "manual")

    assert capability.status == "ok"
    assert calls == ["manual"]


def test_provider_registry_uses_resolved_credential_without_disclosing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_registry, "resolve_provider_api_key", lambda _provider: _SECRET)
    registry = ProviderRegistry(
        DataProvidersConfig(providers={"fred": ProviderSection(active_provider="fred")})
    )
    registry.register_probe("fred", lambda: {"status": "ok", "message": "ready"})

    capability = next(item for item in registry.probe_all() if item.provider_id == "fred")

    assert capability.status == "ok"
    assert capability.secret_present is True
    assert _SECRET not in str(capability.to_dict())


def test_provider_credential_resolution_prefers_vault_over_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / ".env").write_text('ETF_COCKPIT_FRED_API_KEY="env-secret"\n', encoding="utf-8")
    monkeypatch.delenv("ETF_COCKPIT_FRED_API_KEY", raising=False)

    class Vault:
        def get(self, account: str) -> str:
            assert account == "fred"
            return "vault-secret"

    assert resolve_provider_api_key("fred", config_dir=config_dir, vault=Vault()) == "vault-secret"


def test_provider_credential_resolution_falls_back_to_existing_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / ".env").write_text('ETF_COCKPIT_FRED_API_KEY="env-secret"\n', encoding="utf-8")
    monkeypatch.delenv("ETF_COCKPIT_FRED_API_KEY", raising=False)

    class EmptyVault:
        def get(self, _account: str) -> None:
            return None

    assert resolve_provider_api_key("fred", config_dir=config_dir, vault=EmptyVault()) == "env-secret"


def test_provider_credential_resolution_sanitizes_vault_errors(tmp_path) -> None:
    class BrokenVault:
        def get(self, _account: str) -> None:
            raise RuntimeError(f"failed for {_SECRET}")

    with pytest.raises(ConfigError) as error:
        resolve_provider_api_key("fred", config_dir=tmp_path / "configs", vault=BrokenVault())

    assert _SECRET not in str(error.value)


def _persist_fred_probe_cache(path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_registry, "resolve_provider_api_key", lambda _provider: "configured")
    registry = ProviderRegistry(DataProvidersConfig(providers={"fred": ProviderSection(active_provider="fred")}))
    registry.register_probe("fred", lambda: {"status": "ok"})
    registry.persist_probe_results(path)


def test_rotating_vault_credential_invalidates_dependent_probe_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dpapi(monkeypatch)
    cache_path = tmp_path / "provider_probe_results.parquet"
    monkeypatch.setattr(provider_registry, "DEFAULT_PROBE_PATH", cache_path)
    vault = CredentialVault(tmp_path / "vault.dpapi")
    vault.set("fred", "first-value")
    _persist_fred_probe_cache(cache_path, monkeypatch)

    vault.set("fred", "rotated-value")

    assert "fred" not in set(pd.read_parquet(cache_path)["provider_id"].astype(str))
    assert "fred" not in set(pd.read_csv(cache_path.with_suffix(".csv"))["provider_id"].astype(str))


def test_deleting_vault_credential_invalidates_dependent_probe_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dpapi(monkeypatch)
    cache_path = tmp_path / "provider_probe_results.parquet"
    monkeypatch.setattr(provider_registry, "DEFAULT_PROBE_PATH", cache_path)
    vault = CredentialVault(tmp_path / "vault.dpapi")
    vault.set("fred", "credential-value")
    _persist_fred_probe_cache(cache_path, monkeypatch)

    vault.delete("fred")

    assert "fred" not in set(pd.read_parquet(cache_path)["provider_id"].astype(str))
    assert "fred" not in set(pd.read_csv(cache_path.with_suffix(".csv"))["provider_id"].astype(str))


def test_vault_errors_never_echo_the_credential(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_registry, "DEFAULT_PROBE_PATH", tmp_path / "probes.parquet")

    def fail_protect(_payload: bytes) -> bytes:
        raise RuntimeError(f"crypto failure: {_SECRET}")

    monkeypatch.setattr(credentials, "_protect", fail_protect)
    with pytest.raises(CredentialVaultError) as error:
        CredentialVault(tmp_path / "vault.dpapi").set("fred", _SECRET)

    assert _SECRET not in str(error.value)
