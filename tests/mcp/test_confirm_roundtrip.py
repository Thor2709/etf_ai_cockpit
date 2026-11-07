from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from etf_cockpit.mcp import registry, server, tools_data
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.registry import CallContext, RateLimiter, tool


@pytest.fixture
def transport(monkeypatch, tmp_path):
    # Replace only the optional SDK value object. The real _handler,
    # _protocol_result and tool_result_dict perform all dispatch/serialisation.
    class CallToolResult:
        def __init__(self, **fields):
            self.fields = fields

        def model_dump_json(self):
            return json.dumps(self.fields, allow_nan=False)

    sdk_types = ModuleType("mcp.types")
    sdk_types.CallToolResult = CallToolResult
    monkeypatch.setitem(sys.modules, "mcp.types", sdk_types)
    context = CallContext(
        enabled_tiers=frozenset({"read", "edit"}), profile="full", client_id="roundtrip-client",
        store_revision="R1", session=SimpleNamespace(root=tmp_path),
        audit=AuditRecorder(sink=lambda record: None),
        rate_limiter=RateLimiter(path=tmp_path / "quota.sqlite3", clock=lambda: 0.0),
    )
    submissions = []

    def submit(*args):
        submissions.append(args)
        return f"job-{len(submissions)}"

    monkeypatch.setattr(tools_data, "_submit_workflow", submit)

    def call(spec=tools_data.data_refresh.__mcp_tool_spec__, **arguments):
        result = server._handler(spec, context, RuntimeError)(**arguments)
        wire = json.loads(result.model_dump_json())
        assert wire["isError"] is False
        assert json.loads(wire["content"][0]["text"]) == wire["structuredContent"]
        return wire["structuredContent"]["data"]

    return SimpleNamespace(call=call, context=context, submissions=submissions)


def test_serialised_preview_exposes_real_confirm_token(transport):
    preview = transport.call(source="prices")
    token = preview["confirm_token"]
    assert token.startswith("v1.")
    assert transport.context.confirmation_store.consume(
        token, {"source": "prices"}, store_revision="R1", client_id="roundtrip-client",
    )
    assert preview["preview"]["execution_allowed"] is False
    assert transport.submissions == []


def test_serialised_payload_still_redacts_credentials(transport, monkeypatch):
    @tool(tier="read", description="Inspect redaction", read_only_hint=True)
    def inspect_secrets() -> dict:
        return {
            "api_key": "example-api-key", "bearer_token": "Bearer example-access-token",
            "password": "example-password", "access_token": "example-oauth-token",
            "token": "example-token", "authorization": "Bearer example-authorization",
            "refresh_token": "example-refresh-token", "confirm_token_extra": "example-other-token",
            "Confirm_token": "example-case-variant", "nested": [{"password": "example-nested-password"}],
        }

    spec = inspect_secrets.__mcp_tool_spec__
    monkeypatch.setattr(registry, "find_tool", lambda name: spec)
    payload = transport.call(spec)
    assert payload.pop("nested") == [{"password": "***redacted***"}]
    assert set(payload.values()) == {"***redacted***"}


def test_serialised_confirmation_commits_once_and_refuses_reuse(transport):
    preview = transport.call(source="prices", years=3)
    arguments = {"source": "prices", "years": 3, "confirm_token": preview["confirm_token"]}
    committed = transport.call(**arguments)
    assert committed["job_id"] == "job-1"
    assert committed["execution_allowed"] is False
    assert len(transport.submissions) == 1
    with pytest.raises(RuntimeError, match="CONFIRMATION_REQUIRED"):
        transport.call(**arguments)
    assert len(transport.submissions) == 1


def test_previews_do_not_consume_commit_rate_limit(transport):
    previews = [transport.call(source="prices") for _ in range(12)]
    assert transport.submissions == []
    assert not transport.context.rate_limiter._path.exists()
    for index in range(4):
        result = transport.call(source="prices", confirm_token=previews[index]["confirm_token"])
        assert result["job_id"] == f"job-{index + 1}"
    with pytest.raises(RuntimeError, match="RATE_LIMIT_EXCEEDED"):
        transport.call(source="prices", confirm_token=previews[4]["confirm_token"])
    # Previews also remain available after the commit quota is exhausted.
    assert transport.call(source="prices")["confirm_token"].startswith("v1.")
    assert len(transport.submissions) == 4
