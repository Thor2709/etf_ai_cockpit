"""Response budgets against wide payloads and a 5,000-row synthetic data root."""

from datetime import datetime, timezone
from dataclasses import replace
from functools import wraps
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.mcp import registry, resources, tools_scores
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import MCPToolError
from etf_cockpit.mcp.registry import CallContext, invoke_tool, tool
from etf_cockpit.mcp.serialise import build_envelope, envelope_dict, to_json


def _context(root):
    return CallContext(profile="full", session=SimpleNamespace(root=root),
                       audit=AuditRecorder(sink=lambda _record: None))


def _envelope(value):
    return envelope_dict(value if isinstance(value, Envelope) else build_envelope(value))


def _read_link(link, context):
    spec = next(spec for spec in resources.RESOURCE_SPECS if spec.uri == "cockpit://overflow/{id}")
    return json.loads(resources.read_resource(spec, {"id": link["uri"].rsplit("/", 1)[1]}, context))


def _large_tool(monkeypatch, payload):
    @tool(tier="read", description="Synthetic wide response")
    def wide():
        return payload

    monkeypatch.setattr(registry, "find_tool", lambda _name: wide.__mcp_tool_spec__)


def test_over_budget_response_becomes_overflow_and_resource_link(monkeypatch, tmp_path):
    payload = {"status": "available", "rows": [{"id": i, "value": None, "evidence": "x" * 100} for i in range(5000)]}
    _large_tool(monkeypatch, payload)
    result = invoke_tool("wide", {}, context=_context(tmp_path))
    assert len(to_json(_envelope(result))) <= 32_000
    assert result["status"] == "available" and result["truncated"] is True
    assert result["rows_total"] == 5000 and result["preview"]
    assert result["execution_allowed"] is False
    assert result["resource_link"]["type"] == "resource_link"
    assert result["resource_link"]["uri"].startswith("cockpit://overflow/")


def test_overflow_resource_returns_the_full_payload(monkeypatch, tmp_path):
    payload = {"rows": [{"value": None, "evidence": "\u00e9\n" * 5000} for _ in range(5)], "next_cursor": "unchanged"}
    _large_tool(monkeypatch, payload)
    context = _context(tmp_path)
    result = invoke_tool("wide", {}, context=context)
    full = _read_link(result["resource_link"], context)
    assert full["data"] == {"rows": payload["rows"]}
    assert full["next_cursor"] == result["next_cursor"] == "unchanged"
    assert full["execution_allowed"] is False
    assert len(to_json(full)) > 32_000
    assert len(to_json(_envelope(result))) <= 32_000


def test_overflow_path_stays_inside_the_root(monkeypatch, tmp_path):
    root = tmp_path / "root"
    link = resources.write_overflow(root, '{"value":null}')
    call_id = link["uri"].rsplit("/", 1)[1]
    path = resources._overflow_path(root, call_id)
    assert path == root / "runtime" / "mcp_overflow" / f"{call_id}.json"
    assert path.is_relative_to(root.resolve())
    for invalid in ("../outside", "a/../../outside", "C:/outside", "0" * 32 + ".json"):
        with pytest.raises(MCPToolError, match="RESOURCE_PATH_INVALID"):
            resources._overflow_path(root, invalid)
    # Model a resolved symlink/junction without requiring Windows symlink privileges.
    original_resolve = Path.resolve
    directory = root / "runtime" / "mcp_overflow"
    outside = tmp_path / "outside"
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **kw: outside if self == directory else original_resolve(self, *a, **kw))
    with pytest.raises(MCPToolError, match="RESOURCE_PATH_INVALID"):
        resources.write_overflow(root, "{}")
    with pytest.raises(MCPToolError, match="RESOURCE_PATH_INVALID"):
        resources._read_overflow(call_id, root)
    assert not outside.exists()


def test_expired_overflow_returns_unavailable(tmp_path):
    link = resources.write_overflow(tmp_path, '{"data":{"value":null}}')
    call_id = link["uri"].rsplit("/", 1)[1]
    path = resources._overflow_path(tmp_path, call_id)
    expired = datetime.now(timezone.utc).timestamp() - resources.OVERFLOW_TTL_SECONDS - 1
    os.utime(path, (expired, expired))
    response = _read_link(link, _context(tmp_path))
    assert response["data"]["status"] == "unavailable"
    assert "expired" in response["unavailable_reason"]
    assert response["execution_allowed"] is False


@pytest.fixture
def large_root(tmp_path):
    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    dates = pd.date_range("2010-01-01", periods=5000, freq="D")
    history = pd.DataFrame({"instrument_id": "ONE", "run_id": [f"run-{i}" for i in range(5000)],
                            "run_completed_at": dates, "data_as_of_date": dates,
                            "final_combined_score_10": 5.0, "reason_full": "stored evidence " * 100})
    history.to_parquet(derived / "score_history.parquet")
    prices = pd.concat([pd.DataFrame({"etf_id": instrument, "date": dates,
                                     "adjusted_close": [100 + i / 10 for i in range(5000)]})
                        for instrument in ("ONE", "TWO")], ignore_index=True)
    prices.to_parquet(derived / "prices.parquet")
    rows = [{"instrument_id": f"row-{i}", "event_type": "fixture", "value": None,
             "evidence": "wide stored evidence " * 160} for i in range(5000)]
    (derived / "screen.json").write_text(json.dumps(rows), encoding="utf-8")
    (derived / "activity.json").write_text(json.dumps(rows), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("name,arguments", [
    ("score_history", {"instrument_id": "ONE", "range": "all"}),
    ("compare_instruments", {"ids": ["ONE", "TWO"], "range": "5Y", "max_points": None}),
    ("screen_run", {}),
    ("activity_log", {}),
])
def test_large_data_tools_fit_budget_and_preserve_full_overflow(monkeypatch, large_root, name, arguments):
    from etf_cockpit.application import decision_views, etf_economics_view, overlap, score_views, screening_data
    from etf_cockpit.core import session_log

    root = large_root
    derived = root / "data" / "derived"
    snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=())),
                               prices=pd.read_parquet(derived / "prices.parquet"))
    session = SimpleNamespace(root=root, snapshot=snapshot)
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (session, snapshot))
    monkeypatch.setattr(score_views, "published_scores", lambda *_a: [])
    monkeypatch.setattr(etf_economics_view, "build_etf_economics_panel", lambda *_a: {})
    monkeypatch.setattr(overlap, "build_direct_overlap_view", lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("no holdings")))
    screen_rows = json.loads((derived / "screen.json").read_text(encoding="utf-8"))
    events = json.loads((derived / "activity.json").read_text(encoding="utf-8"))
    assert len(screen_rows) == len(events) == len(pd.read_parquet(derived / "score_history.parquet")) == 5000
    monkeypatch.setattr(session_log, "read_session_events", lambda _limit: events)
    monkeypatch.setattr(screening_data, "load_screening_fundamentals", lambda _root: pd.DataFrame())
    monkeypatch.setattr(decision_views, "build_screen_rows", lambda *_a: pd.DataFrame(screen_rows))
    # A wide canonical query summary must also pass through the central budget.
    query = SimpleNamespace(rows=screen_rows, total_input=5000, total_matched=5000,
                            available_fields=("instrument_id",), unavailable_fields=(),
                            warnings=("stored query evidence " * 2000,), query_checksum="large")
    monkeypatch.setattr(screening_data, "run_screen_query", lambda *_a, **_kw: query)
    context = _context(root)
    context.session = session
    spec = registry.find_tool(name)
    dispatched = []

    @wraps(spec.function)
    def capture(**kwargs):
        value = spec.function(**kwargs)
        dispatched.append(value)
        return value

    monkeypatch.setattr(registry, "find_tool", lambda _name: replace(spec, function=capture))
    result = invoke_tool(name, arguments, context=context)
    assert len(to_json(_envelope(result))) <= 32_000
    assert result["truncated"] is True
    full = _read_link(result["resource_link"], context)
    expected_envelope = _envelope(dispatched[0])
    assert full["data"] == expected_envelope["data"]
    assert full["next_cursor"] == expected_envelope["next_cursor"]
    assert full["execution_allowed"] is False
    assert len(to_json(full)) > 32_000
    if name == "score_history":
        assert len(full["data"]["series"]) == 5000
        default = invoke_tool(name, {"instrument_id": "ONE"}, context=context)
        default_data = _read_link(default["resource_link"], context)["data"] if "resource_link" in default else default
        assert 365 <= len(default_data["series"]) <= 367
    if name == "compare_instruments":
        default = invoke_tool(name, {"ids": ["ONE", "TWO"]}, context=context)
        default_data = _read_link(default["resource_link"], context)["data"] if "resource_link" in default else default
        for collection in ("price_return_comparison", "drawdown_comparison"):
            series = default_data[collection]["ONE|TWO"]
            assert len(series["x"]) == len(series["a"]) == len(series["b"]) == 252


@pytest.mark.parametrize("rows", [list(range(5000)), [{"id": i, "evidence": '"\\\n\u00e9' * 100} for i in range(5000)]])
def test_full_tool_result_budget_counts_both_representations(monkeypatch, tmp_path, rows):
    from etf_cockpit.mcp.serialise import tool_result_dict

    monkeypatch.delenv("ETF_COCKPIT_MCP_MAX_CHARS", raising=False)
    _large_tool(monkeypatch, {"rows": rows})
    context = _context(tmp_path)
    result = invoke_tool("wide", {}, context=context)
    wire = tool_result_dict(result)
    text = wire["content"][0]["text"]
    assert len(json.dumps(wire["structuredContent"], separators=(",", ":"))) + len(text) <= 32_000
    assert len(json.dumps(wire, ensure_ascii=True, separators=(",", ":"))) <= 32_000
    assert result["truncated"] is True
    assert _read_link(result["resource_link"], context)["data"] == {"rows": rows}


@pytest.mark.parametrize("transport", ["stdio", "http"])
@pytest.mark.parametrize("payload", [
    {"rows": [1, None], "evidence": 'quoted "text"\n\u00e9'},
    {"rows": list(range(5000))},
    {"token=" + "k" * 17000: None},
])
def test_tool_text_is_compact_json_equal_to_structured_payload(monkeypatch, tmp_path, transport, payload):
    import sys

    from etf_cockpit.mcp import http, server

    # Exercise both real transport handlers without importing the optional SDK.
    monkeypatch.setitem(sys.modules, "mcp.types", SimpleNamespace(CallToolResult=lambda **fields: fields))
    _large_tool(monkeypatch, payload)
    spec = replace(registry.find_tool("wide"), name="scores_ranked")
    monkeypatch.setattr(registry, "find_tool", lambda _name: spec)
    context = _context(tmp_path)
    if transport == "stdio":
        handler = server._handler(spec, context, RuntimeError)
    else:
        token = SimpleNamespace(client_id="test", scopes=["cockpit:read"])
        monkeypatch.setattr(http, "_access_token_getter", lambda: lambda: token)
        handler = http._tool_handler(spec, template=context, grants={"cockpit:read": frozenset({"read"})}, tool_error=RuntimeError)
    wire = handler()
    text = wire["content"][0]["text"]
    structured = wire["structuredContent"]
    assert json.loads(text) == structured
    assert text == json.dumps(structured, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert wire["isError"] is False
    assert len(json.dumps(wire, ensure_ascii=True, separators=(",", ":"))) <= 32_000


def test_environment_budget_caps_full_result_and_invalid_values_fail_startup(monkeypatch, tmp_path):
    from etf_cockpit.mcp import http, server
    from etf_cockpit.mcp.serialise import response_char_limit, tool_result_dict

    variable = "ETF_COCKPIT_MCP_MAX_CHARS"
    payload = {f"summary-{i}-" + "k" * 80: "e" * 160 for i in range(20)}
    payload.update(rows=list(range(5000)), next_cursor="c" * 2048)
    _large_tool(monkeypatch, payload)
    for limit in (8000, 4000, 200000):
        monkeypatch.setenv(variable, str(limit))
        assert response_char_limit() == limit
        result = invoke_tool("wide", {}, context=_context(tmp_path))
        wire = tool_result_dict(result)
        assert len(json.dumps(wire, ensure_ascii=True, separators=(",", ":"))) <= limit
        assert json.loads(wire["content"][0]["text"]) == wire["structuredContent"]
        if limit <= 8000:
            assert result["truncated"] is True
            assert result["resource_link"]["uri"].startswith("cockpit://overflow/")

    def unexpected_sdk_load():
        raise AssertionError("Invalid budget must fail before loading the SDK")

    monkeypatch.setattr(server, "_load_sdk", unexpected_sdk_load)
    for invalid in ("invalid", "", "8000.5", "3999", "200001"):
        monkeypatch.setenv(variable, invalid)
        with pytest.raises(ValueError, match=variable):
            server.create_server(session=object())
        with pytest.raises(ValueError, match=variable):
            http.create_http_server(token_verifier=None, config={})
