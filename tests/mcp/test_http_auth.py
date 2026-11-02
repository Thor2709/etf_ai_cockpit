from __future__ import annotations

import inspect
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
import json
import sys
from types import SimpleNamespace

import pytest

from etf_cockpit.mcp import http
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.errors import AuthorizationError, ConfirmationError
from etf_cockpit.mcp import registry
from etf_cockpit.mcp.registry import CallContext, RateLimiter, WRITE_TIERS, discover_tools, invoke_tool
from etf_cockpit.mcp.serialise import envelope_dict


def test_remote_defaults_are_disabled_and_scopes_grant_only_configured_tiers() -> None:
    config = http.load_mcp_config()
    assert config["remote"]["enabled"] is False
    assert config["remote"]["profile"] == "core"
    assert config["remote"]["allowed_tiers"] == ["read", "research", "paper"]

    grants = http.scope_tier_map(config)
    assert http.tiers_for_scopes(["cockpit:read", "unrelated:scope"], grants=grants) == frozenset({"read"})
    assert http.tiers_for_scopes(["cockpit:paper"], grants=grants) == frozenset({"paper"})
    with pytest.raises(AuthorizationError):
        http.tiers_for_scopes(["unrelated:scope"], grants=grants)


def test_remote_http_rejects_unauthenticated_requests() -> None:
    try:
        sdk_root = str(distribution("mcp").locate_file(""))
    except PackageNotFoundError:
        pytest.skip("optional MCP SDK unavailable: remote HTTP is disabled by default; transport integration requires etf-ai-cockpit[mcp]")
    # The tests/mcp directory shadows the optional top-level mcp package when
    # pytest prepends the test directory to sys.path.
    sys.modules.pop("mcp", None)
    sys.path.insert(0, sdk_root)
    try:
        import_module("mcp.server.fastmcp")
    finally:
        sys.path.remove(sdk_root)
    from starlette.testclient import TestClient

    class RejectAllTokens:
        async def verify_token(self, _token: str):
            return None

    enabled_config = {
        "remote": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8000,
            "path": "/mcp",
            "profile": "core",
            "allowed_tiers": ["read", "research", "paper"],
        },
        "scope_tiers": {
            "cockpit:read": ["read"],
            "cockpit:research": ["research"],
            "cockpit:paper": ["paper"],
        },
    }
    server = http.create_http_server(
        token_verifier=RejectAllTokens(),
        issuer_url="https://identity.example/",
        resource_url="https://cockpit.example/mcp",
        config=enabled_config,
        session=SimpleNamespace(root=http.ROOT),
    )
    app = server.streamable_http_app()
    with TestClient(app, base_url="https://cockpit.example") as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "initialize", "id": 1})
    assert response.status_code == 401


def test_verified_token_builds_core_context_from_its_scopes_without_edit_access() -> None:
    template = CallContext(
        enabled_tiers=http.REMOTE_ALLOWED_TIERS,
        profile="core",
        client_id="remote-bootstrap",
        session=object(),
    )
    config = http.load_mcp_config()
    grants = http.scope_tier_map(config)
    token = SimpleNamespace(client_id="oauth-client", scopes=["cockpit:read", "cockpit:paper", "edit"])

    context = http._verified_context(token, template=template, grants=grants)

    assert context.client_id == "oauth-client"
    assert context.profile == "core"
    assert context.enabled_tiers == frozenset({"read", "paper"})
    assert context.enabled_tiers.isdisjoint({"edit"})
    assert context.session is template.session


def test_every_core_remote_write_refuses_an_invalid_confirmation_before_handler(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = [
        spec
        for spec in discover_tools()
        if spec.tier in WRITE_TIERS and spec.tier in http.REMOTE_ALLOWED_TIERS
        and spec.name in {item.name for item in http.list_tools(profile="core", tiers=http.REMOTE_ALLOWED_TIERS)}
    ]
    assert specs
    context = CallContext(
        enabled_tiers=http.REMOTE_ALLOWED_TIERS,
        profile="core",
        client_id="remote-test",
        confirmation_store=ConfirmationStore(secret=b"h" * 32),
        audit=AuditRecorder(sink=lambda _record: None),
        rate_limiter=RateLimiter(path=tmp_path / "mcp-rate-limits.sqlite3"),
    )
    writes = []

    for spec in specs:
        arguments = {
            name: "fixture"
            for name, parameter in inspect.signature(spec.function).parameters.items()
            if parameter.default is inspect.Parameter.empty and name != "confirm_token"
        }
        arguments["confirm_token"] = "invalid"
        guarded_spec = registry.ToolSpec(
            name=spec.name,
            description=spec.description,
            tier=spec.tier,
            annotations=spec.annotations,
            requires_confirmation=spec.requires_confirmation,
            function=lambda **values: writes.append((spec.name, values)),
            output_model=spec.output_model,
            profiles=spec.profiles,
        )
        monkeypatch.setattr(registry, "find_tool", lambda _name, selected=guarded_spec: selected)
        with pytest.raises(ConfirmationError):
            invoke_tool(spec.name, arguments, context=context)

    assert len(context.audit.records) == len(specs)
    assert {record.outcome for record in context.audit.records} == {"refused"}
    assert writes == []


def test_http_output_preserves_unavailable_values_and_stays_paged(monkeypatch: pytest.MonkeyPatch) -> None:
    config = http.load_mcp_config()
    grants = http.scope_tier_map(config)
    template = CallContext(
        enabled_tiers=http.REMOTE_ALLOWED_TIERS,
        profile="core",
        client_id="remote-bootstrap",
        audit=AuditRecorder(sink=lambda _record: None),
    )
    spec = next(item for item in discover_tools() if item.name == "scores_ranked")
    page = {"rows": [{"instrument_id": "X", "score": None}], "next_cursor": "cursor-fixture"}
    monkeypatch.setattr(http, "invoke_tool", lambda _name, _arguments, *, context: page)

    result = http._dispatch_http_tool(
        spec,
        {"top_n": 1},
        SimpleNamespace(client_id="reader", scopes=["cockpit:read"]),
        template=template,
        grants=grants,
    )
    envelope = envelope_dict(http.build_envelope(result))

    assert envelope["data"]["rows"][0]["score"] is None
    assert envelope["next_cursor"] == "cursor-fixture"
    assert len(json.dumps(envelope, separators=(",", ":"))) < 2000


def test_http_dispatch_calls_the_registry_service_path_with_verified_context(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = next(item for item in discover_tools() if item.name == "scores_ranked")
    template = CallContext(
        enabled_tiers=http.REMOTE_ALLOWED_TIERS,
        profile="core",
        client_id="remote-bootstrap",
        audit=AuditRecorder(sink=lambda _record: None),
    )
    grants = http.scope_tier_map(http.load_mcp_config())
    observed = []

    def canonical_dispatch(name, arguments, *, context):
        observed.append((name, dict(arguments), context))
        return {"canonical_service": True}

    monkeypatch.setattr(http, "invoke_tool", canonical_dispatch)
    result = http._dispatch_http_tool(
        spec,
        {"asset_type": "etf", "top_n": 3},
        SimpleNamespace(client_id="reader", scopes=["cockpit:read"]),
        template=template,
        grants=grants,
    )

    assert result == {"canonical_service": True}
    assert observed[0][0] == "scores_ranked"
    assert observed[0][1] == {"asset_type": "etf", "top_n": 3}
    assert observed[0][2].client_id == "reader"


def test_tunnel_expiry_uses_stopwatch_elapsed_time_instead_of_wall_clock() -> None:
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2] / "scripts" / "mcp_tunnel.ps1").read_text(encoding="utf-8")

    assert "$timer = [System.Diagnostics.Stopwatch]::StartNew()" in script
    assert "while (-not $tunnelProcess.HasExited -and $timer.Elapsed.TotalMinutes -lt $MaxDurationMinutes)" in script
    assert "[DateTime]" not in script
    assert "$deadline" not in script
