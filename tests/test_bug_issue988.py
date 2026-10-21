"""V8 intake items for issue #988: plugin registry / builtin policy hardening."""

from __future__ import annotations

import json
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from etf_cockpit.chatgpt_bridge.validation import validate_audit_text
from etf_cockpit.core.exceptions import AuditImportError
from etf_cockpit.security.policy import build_security_report
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


@pytest.mark.parametrize("method", ["sendto"] + (["sendmsg"] if hasattr(socket.socket, "sendmsg") else []))
def test_conformance_blocks_and_counts_connectionless_send(method: str, monkeypatch) -> None:
    native_calls = []
    original = getattr(socket.socket, method)

    def unexpected_send(*args, **kwargs):
        native_calls.append(method)
        raise AssertionError("connectionless send escaped the probe")

    monkeypatch.setattr(socket.socket, method, unexpected_send)

    class DatagramPlugin(_Plugin):
        def health(self, context):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                with pytest.raises(OSError, match="network access is blocked"):
                    if method == "sendto":
                        sock.sendto(b"probe", ("127.0.0.1", 9))
                    else:
                        sock.sendmsg([b"probe"], [], 0, ("127.0.0.1", 9))
            return PluginHealth(status=PluginStatus.AVAILABLE, message="ok")

    registry = PluginRegistry()
    registry.register(DatagramPlugin())
    report = registry.conformance_report()
    assert report["failures"] == ["fixture.plugin"]
    assert report["checks"][0]["network_calls"] is True
    assert report["checks"][0]["network_call_count"] == 1
    assert report["checks"][0]["status"] == "available"
    assert native_calls == []
    assert getattr(socket.socket, method) is unexpected_send
    assert original is not unexpected_send


@pytest.mark.parametrize("method", ["send", "sendall"])
def test_conformance_blocks_and_counts_connected_send(method: str, monkeypatch) -> None:
    class ConnectedSocket:
        connected = True
        connect = Mock()
        connect_ex = Mock()
        sendto = Mock()
        send = Mock(return_value=5)
        sendall = Mock(return_value=None)

    # Simulate a socket connected before health runs, without opening any network socket.
    sock = ConnectedSocket()
    native_send = getattr(ConnectedSocket, method)
    monkeypatch.setattr(socket, "socket", ConnectedSocket)

    class ConnectedPlugin(_Plugin):
        def health(self, context):
            assert sock.connected
            with pytest.raises(OSError, match="network access is blocked"):
                getattr(sock, method)(b"probe")
            return super().health(context)

    registry = PluginRegistry()
    registry.register(ConnectedPlugin())
    report = registry.conformance_report()

    assert report["failures"] == ["fixture.plugin"]
    assert report["checks"][0]["network_calls"] is True
    assert report["checks"][0]["network_call_count"] == 1
    assert report["checks"][0]["status"] == "available"
    assert report["checks"][0]["passed"] is False
    native_send.assert_not_called()
    assert getattr(ConnectedSocket, method) is native_send


def test_conformance_blocks_native_resolvers_without_lookup(monkeypatch) -> None:
    for method in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
        native_lookup = Mock(side_effect=AssertionError("native DNS lookup escaped the probe"))
        monkeypatch.setattr(socket, method, native_lookup)

        class ResolvingPlugin(_Plugin):
            def health(self, context):
                with pytest.raises(OSError, match="network access is blocked"):
                    getattr(socket, method)("example.com")
                return super().health(context)

        registry = PluginRegistry()
        registry.register(ResolvingPlugin())
        report = registry.conformance_report()

        assert report["failures"] == ["fixture.plugin"]
        assert report["checks"][0]["network_calls"] is True
        assert report["checks"][0]["network_call_count"] == 1
        assert report["checks"][0]["status"] == "available"
        assert report["checks"][0]["passed"] is False
        native_lookup.assert_not_called()
        assert getattr(socket, method) is native_lookup


@pytest.mark.parametrize("text", [
    "Do not hesitate to place the order.",
    "automatic execution not only improves speed",
    "The broker should not hesitate to buy shares.",
])
def test_indirect_negation_does_not_admit_execution(text: str) -> None:
    audit = {
        "schema_version": "1.0", "review_date": "2026-10-05", "overall_view": "neutral",
        "portfolio_actions": [],
        "model_audit": {"toto_usefulness": "n/a", "timesfm_usefulness": "n/a",
                        "baseline_comparison": text, "overfitting_concerns": []},
    }
    with pytest.raises(AuditImportError, match="automatic trading"):
        validate_audit_text(json.dumps(audit), set())


@pytest.mark.parametrize("status", ["pending-triage", None, "", "missing"])
def test_unknown_status_blocks_low_severity_independently(status) -> None:
    finding = {"id": "fixture", "severity": "low"}
    if status != "missing":
        finding["status"] = status
    assert build_security_report(findings=[finding])["status"] == "failed"
    for status in ("open", "active", "in_progress", "reopened", "new", "unresolved"):
        finding["status"] = status
        assert build_security_report(findings=[finding])["status"] == "passed"


def test_plugin_context_rejects_unsupported_mutable_input() -> None:
    source = {"row": SimpleNamespace(value=1)}
    with pytest.raises(TypeError, match="unsupported plugin input type: SimpleNamespace"):
        PluginContext(request_id="fixture", inputs=source)
    assert source["row"].value == 1


@pytest.mark.parametrize("key", [
    "refreshToken", "refresh_token", "refresh-token", "privateKey", "private_key", "private-key",
    "signingKey", "signing_key", "signing-key", "apiKey", "accessToken", "clientSecret", "credential",
])
def test_plugin_audit_redacts_secrets_before_retention(key: str) -> None:
    class SecretPlugin(_Plugin):
        def fetch(self, payload, context):
            context.record_audit(f"{key}=abc123supersecret", f'{key}="abc123supersecret"')
            return PluginResult(status="ok", message="done")

    registry = PluginRegistry()
    registry.register(SecretPlugin())
    assert registry.invoke("fixture.plugin", "fetch").status == "ok"
    event = registry.audit_events()[0]
    assert "abc123supersecret" not in json.dumps(event)
    assert "***redacted***" in event["event"] and "***redacted***" in event["detail"]
    assert "abc123supersecret" not in repr(registry._audit_log)


def test_health_failure_retains_recorded_audit() -> None:
    class FailingHealthPlugin(_Plugin):
        def health(self, context):
            context.record_audit("health-started", "probe attempted")
            raise RuntimeError("failure")

    registry = PluginRegistry()
    registry.register(FailingHealthPlugin())
    assert registry.health("fixture.plugin").status is PluginStatus.UNAVAILABLE
    assert registry.audit_events() == ({"plugin_id": "fixture.plugin", "operation": "health",
                                        "event": "health-started", "detail": "probe attempted"},)

def test_conformance_fails_closed_when_enabled_plugin_health_is_unavailable() -> None:
    class _Broken(_Plugin):
        def health(self, context: PluginContext) -> PluginHealth:
            raise RuntimeError("health backend down")

    registry = PluginRegistry(allowlist={"fixture.plugin"})
    registry.register(_Broken())

    report = registry.conformance_report()

    assert report["failures"] == ["fixture.plugin"]
    assert report["checks"][0]["passed"] is False
    assert report["checks"][0]["status"] == PluginStatus.UNAVAILABLE.value
