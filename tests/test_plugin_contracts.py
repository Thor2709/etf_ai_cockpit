from __future__ import annotations

import pytest
from pydantic import ValidationError

from etf_cockpit.plugins.builtins import default_plugin_registry
from etf_cockpit.plugins.contracts import (
    PluginHealth,
    PluginManifest,
    PluginResult,
    PluginStatus,
)
from etf_cockpit.plugins.registry import PluginRegistrationError, PluginRegistry


def test_plugin_manifest_declares_policy_without_executable_or_store_authority() -> None:
    manifest = PluginManifest(
        plugin_id="fixture.local-provider",
        version="1.0.0",
        kind="provider",
        capabilities=("health", "fetch", "import"),
        licence="MIT",
        network_access=False,
        credential_requirements=(),
        quota="none",
        retention="local-cache-only",
        authority="evidence_only",
    )

    assert manifest.schema_version == "plugin-contract.v1"
    assert manifest.executable_authority is False
    assert manifest.writes_canonical_stores is False

    with pytest.raises(ValidationError, match="writes_canonical_stores"):
        PluginManifest(
            plugin_id="fixture.local-provider",
            version="1.0.0",
            kind="provider",
            capabilities=("health",),
            licence="MIT",
            writes_canonical_stores=True,
        )


def test_manifest_rejects_authority_escalation() -> None:
    with pytest.raises(ValidationError, match="executable_authority"):
        PluginManifest(
            plugin_id="fixture.bad-broker",
            version="1.0.0",
            kind="broker_adapter",
            capabilities=("health",),
            licence="MIT",
            authority="paper_only",
            executable_authority=True,
        )


class FixturePlugin:
    manifest = PluginManifest(
        plugin_id="fixture.local-provider",
        version="1.0.0",
        kind="provider",
        capabilities=("health", "fetch", "import"),
        licence="MIT",
        network_access=False,
        credential_requirements=(),
        quota="none",
        retention="local-cache-only",
        authority="evidence_only",
    )

    def __init__(self) -> None:
        self.health_calls = 0

    def health(self, _context) -> PluginHealth:
        self.health_calls += 1
        return PluginHealth(status=PluginStatus.AVAILABLE, message="fixture ready")

    def fetch(self, _payload, _context) -> PluginResult:
        return PluginResult(status="ok", message="fixture fetched", data={"rows": 0})

    def import_data(self, _payload, _context) -> PluginResult:
        return PluginResult(status="unsupported", message="fixture import is not needed")


class UnlistedPlugin(FixturePlugin):
    manifest = PluginManifest(
        plugin_id="fixture.unlisted-provider",
        version="1.0.0",
        kind="provider",
        capabilities=("health",),
        licence="MIT",
    )


def test_registry_enforces_allowlist_and_disabled_plugins_are_not_called() -> None:
    plugin = FixturePlugin()
    registry = PluginRegistry(allowlist={"fixture.local-provider"})
    registry.register(plugin, enabled=False)

    health = registry.health("fixture.local-provider")
    assert health.status == PluginStatus.DISABLED
    assert plugin.health_calls == 0
    assert registry.invoke("fixture.local-provider", "fetch", {}).status == "unavailable"

    rows = registry.status_rows()
    assert rows[0]["provider_id"] == "plugin:fixture.local-provider"
    assert rows[0]["configured"] is False
    assert rows[0]["executable_authority"] is False

    with pytest.raises(PluginRegistrationError, match="allow-list"):
        registry.register(UnlistedPlugin(), enabled=True)


def test_registry_conformance_uses_no_secrets_and_normalises_failures() -> None:
    plugin = FixturePlugin()
    registry = PluginRegistry(allowlist={plugin.manifest.plugin_id})
    registry.register(plugin)

    report = registry.conformance_report()
    assert report["schema_version"] == "plugin-conformance.v1"
    assert report["failures"] == []
    assert report["checks"][0]["network_calls"] is False
    assert registry.invoke(plugin.manifest.plugin_id, "fetch", {"symbol": "LOCAL"}).status == "ok"


def test_default_registry_keeps_mandatory_local_capabilities_available_and_broker_disabled() -> None:
    registry = default_plugin_registry()
    rows = {row["provider_id"]: row for row in registry.status_rows()}

    assert rows["plugin:builtin.local-provider"]["status"] == "available"
    assert rows["plugin:builtin.baseline-model"]["status"] == "available"
    assert rows["plugin:builtin.paper-broker"]["status"] == "disabled"
    assert all(row["executable_authority"] is False for row in rows.values())


def test_invalid_plugin_policy_fails_closed_without_disabling_core_contracts(tmp_path) -> None:
    policy = tmp_path / "plugin_registry.yaml"
    policy.write_text("schema_version: plugin-registry.v1\nexecution_allowed: true\n", encoding="utf-8")

    registry = default_plugin_registry(policy)
    rows = {row["provider_id"]: row for row in registry.status_rows()}

    assert rows["plugin:builtin.local-provider"]["status"] == "available"
    assert rows["plugin:builtin.paper-broker"]["status"] == "disabled"
