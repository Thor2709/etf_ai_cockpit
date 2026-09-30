from __future__ import annotations

import logging

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
    monkeypatch.setattr(credentials, "_dpapi_available", lambda: True)


def test_dpapi_secret_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dpapi(monkeypatch)
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
    monkeypatch.setattr(provider_registry, "resolve_provider_api_key", lambda _provider, **_kwargs: _SECRET)
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
    _stub_dpapi(monkeypatch)
    monkeypatch.setattr(provider_registry, "DEFAULT_PROBE_PATH", tmp_path / "probes.parquet")

    def fail_protect(_payload: bytes) -> bytes:
        raise RuntimeError(f"crypto failure: {_SECRET}")

    monkeypatch.setattr(credentials, "_protect", fail_protect)
    with pytest.raises(CredentialVaultError) as error:
        CredentialVault(tmp_path / "vault.dpapi").set("fred", _SECRET)

    assert _SECRET not in str(error.value)


@pytest.mark.parametrize("operation", ["set", "delete"])
def test_credential_mutations_leave_vault_unchanged_when_probe_invalidation_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    _stub_dpapi(monkeypatch)
    monkeypatch.setattr(provider_registry, "DEFAULT_PROBE_PATH", tmp_path / "probes.parquet")
    vault_path = tmp_path / "vault.dpapi"
    vault = CredentialVault(vault_path)
    vault.set("fred", "before")
    original_bytes = vault_path.read_bytes()

    def fail_invalidation(_provider: str) -> None:
        raise CredentialVaultError("cached probes could not be invalidated")

    monkeypatch.setattr(credentials, "_invalidate_probe_cache", fail_invalidation)
    with pytest.raises(CredentialVaultError):
        if operation == "set":
            vault.set("fred", "after")
        else:
            vault.delete("fred")

    assert vault_path.read_bytes() == original_bytes
    assert vault.get("fred") == "before"


def test_optional_finnhub_credential_resolves_and_limits_capabilities_to_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved: list[str] = []
    calls: list[bool] = []

    def resolve(provider: str, **_kwargs: object) -> str:
        assert provider == "finnhub"
        resolved.append(provider)
        return _SECRET

    def probe() -> tuple[provider_registry.ProviderCapability, ...]:
        calls.append(True)
        return tuple(
            provider_registry.ProviderCapability(
                provider_id="finnhub",
                dataset_type=dataset,
                status="ok",
                authority=provider_registry.SourceAuthority.VENDOR,
                configured=True,
                entitlement="configured",
                rate_limit_note="credential-enhanced limit",
                last_success_at=None,
                error_fingerprint=None,
                secret_present=True,
                message="Capability available.",
            )
            for dataset in ("prices", "fx", "etf_metadata", "etf_holdings", "undeclared")
        )

    monkeypatch.setattr(provider_registry, "resolve_provider_api_key", resolve)
    registry = ProviderRegistry(
        DataProvidersConfig(providers={"finnhub": ProviderSection(active_provider="finnhub")})
    )
    registry.register_probe("finnhub", probe)

    capabilities = [item for item in registry.probe_all() if item.provider_id == "finnhub"]

    assert resolved == ["finnhub"]
    assert calls == [True]
    assert {item.dataset_type for item in capabilities} == {"prices", "fx", "etf_metadata", "etf_holdings"}
    assert all(item.rate_limit_note == "credential-enhanced limit" for item in capabilities)
    assert all(item.secret_present for item in capabilities)
    assert _SECRET not in str([item.to_dict() for item in capabilities])


def test_registered_finnhub_adapter_preserves_all_dataset_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_registry,
        "resolve_provider_api_key",
        lambda provider, **_kwargs: _SECRET if provider == "finnhub" else None,
    )
    registry = ProviderRegistry(
        DataProvidersConfig(providers={"finnhub": ProviderSection(active_provider="finnhub")})
    )

    capabilities = [item for item in registry.probe_all() if item.provider_id == "finnhub"]

    assert {item.dataset_type for item in capabilities} == {
        "prices",
        "fx",
        "etf_metadata",
        "etf_holdings",
    }
    assert all(item.status == "unavailable" for item in capabilities)
    assert all(item.secret_present for item in capabilities)
    assert all(not item.score_eligible for item in capabilities)


@pytest.mark.parametrize(
    ("provider_id", "providers"),
    [
        ("sec_edgar", {"sec_edgar": ProviderSection(active_provider="sec_edgar")}),
        ("ecb", {"fx": ProviderSection(active_provider="ecb")}),
    ],
)
def test_sec_and_ecb_probes_run_without_vault_access(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    providers: dict[str, ProviderSection],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        provider_registry,
        "resolve_provider_api_key",
        lambda *_args, **_kwargs: pytest.fail("keyless provider must not consult the vault"),
    )
    registry = ProviderRegistry(DataProvidersConfig(providers=providers))
    registry.register_probe(provider_id, lambda: calls.append(provider_id) or {"status": "ok"})

    capabilities = [item for item in registry.probe_all() if item.provider_id == provider_id]

    assert provider_id in calls
    assert len(capabilities) == 1
    assert capabilities[0].status == "ok"
    assert not capabilities[0].secret_present


def test_valid_rejected_and_missing_credentials_have_distinct_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current: dict[str, str | None] = {"credential": None}

    def resolve(_provider: str, **_kwargs: object) -> str | None:
        return current["credential"]

    def probe() -> dict[str, str]:
        if current["credential"] == "valid-key":
            return {"status": "ok", "entitlement": "configured"}
        raise PermissionError("HTTP 403")

    monkeypatch.setattr(provider_registry, "resolve_provider_api_key", resolve)
    registry = ProviderRegistry(
        DataProvidersConfig(providers={"fred": ProviderSection(active_provider="fred")})
    )
    registry.register_probe("fred", probe)

    current["credential"] = "valid-key"
    valid = next(item for item in registry.probe_all() if item.provider_id == "fred")
    current["credential"] = "wrong-key"
    rejected = next(item for item in registry.probe_all() if item.provider_id == "fred")
    current["credential"] = None
    missing = next(item for item in registry.probe_all() if item.provider_id == "fred")

    assert (valid.status, valid.entitlement, valid.secret_present) == ("ok", "configured", True)
    assert (rejected.status, rejected.secret_present) == ("forbidden", True)
    assert (missing.status, missing.entitlement, missing.secret_present) == ("unavailable", "api_key_required", False)
    assert "valid-key" not in str([valid.to_dict(), rejected.to_dict(), missing.to_dict()])
    assert "wrong-key" not in str([valid.to_dict(), rejected.to_dict(), missing.to_dict()])


def test_non_windows_vault_reports_unavailable_and_keeps_env_fallback(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / ".env").write_text('ETF_COCKPIT_FRED_API_KEY="env-secret"\n', encoding="utf-8")
    monkeypatch.delenv("ETF_COCKPIT_FRED_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "_dpapi_available", lambda: False)
    vault = CredentialVault(tmp_path / "vault.dpapi")

    assert vault.status() == {
        "status": "unavailable",
        "reason": "Windows DPAPI is unavailable; credentials remain disabled.",
    }
    assert resolve_provider_api_key("fred", config_dir=config_dir, vault=vault) == "env-secret"
