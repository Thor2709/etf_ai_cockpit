"""V8 intake items for issue #988: plugin registry / builtin policy hardening."""

from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.plugins.builtins import default_plugin_registry
from etf_cockpit.plugins.contracts import PluginContext, PluginHealth, PluginManifest, PluginResult, PluginStatus
from etf_cockpit.plugins.registry import PluginRegistrationError, PluginRegistry


class _Plugin:
    def __init__(self, *, network: bool = False, capabilities=("health", "fetch"), plugin_id="fixture.plugin") -> None:
        self.manifest = PluginManifest(
            plugin_id=plugin_id,
            version="1.0.0",
            kind="provider",
            capabilities=capabilities,
            licence="MIT",
            authority="evidence_only",
            network_access=network,
        )

    def health(self, context: PluginContext) -> PluginHealth:
        return PluginHealth(status=PluginStatus.AVAILABLE, message="ok")

    def fetch(self, payload, context: PluginContext) -> PluginResult:
        context.record_audit("fetch", "called")
        return PluginResult(status="ok", message="done")


def test_n002_registry_rejects_network_access() -> None:  # E.C3.S16.N002
    registry = PluginRegistry(allowlist={"fixture.plugin"})
    with pytest.raises(PluginRegistrationError, match="network"):
        registry.register(_Plugin(network=True))


def test_n003_duplicate_plugin_id_is_rejected() -> None:  # E.C3.S16.N003
    registry = PluginRegistry(allowlist={"fixture.plugin"})
    first = _Plugin()
    registry.register(first)
    with pytest.raises(PluginRegistrationError, match="already registered"):
        registry.register(_Plugin())
    assert registry._plugins["fixture.plugin"] is first


def test_n004_quoted_false_is_not_enabled(tmp_path: Path) -> None:  # E.C3.S16.N004
    source = Path("configs/plugin_registry.yaml").read_text(encoding="utf-8")
    assert "enabled: " in source
    policy = tmp_path / "plugin_registry.yaml"
    policy.write_text(source.replace("enabled: true", 'enabled: "false"').replace("enabled: false", 'enabled: "false"'), encoding="utf-8")

    rows = {row["provider_id"]: row for row in default_plugin_registry(policy).status_rows()}

    # a malformed (non-boolean) flag falls back to the safe built-in policy; never truthy-by-string
    assert rows["plugin:builtin.paper-broker"]["enabled"] is False
    assert rows["plugin:fixed-income.ecb"]["enabled"] is False


def test_c4_n002_conformance_fails_when_declared_capability_is_not_callable() -> None:  # E.C4.S16.N002
    registry = PluginRegistry(allowlist={"fixture.plugin"})
    registry.register(_Plugin(capabilities=("health", "fetch", "score")))

    report = registry.conformance_report()

    assert report["failures"] == ["fixture.plugin"]
    assert report["checks"][0]["missing_capabilities"] == ["score"]


def test_default_registry_conformance_still_passes() -> None:
    assert default_plugin_registry().conformance_report()["failures"] == []


def test_c5_n001_audit_events_are_exposed_by_the_registry() -> None:  # E.C5.S16.N001
    registry = PluginRegistry(allowlist={"fixture.plugin"})
    registry.register(_Plugin())

    registry.invoke("fixture.plugin", "fetch", {})

    assert registry.audit_events() == (
        {"plugin_id": "fixture.plugin", "operation": "fetch", "event": "fetch", "detail": "called"},
    )
