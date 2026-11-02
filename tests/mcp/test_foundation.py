from __future__ import annotations

import ast
import builtins
import importlib
import inspect
from pathlib import Path
import sys

from decimal import Decimal

import pytest

import etf_cockpit.mcp as mcp_package
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import ConfirmationError, MCPServerUnavailable
from etf_cockpit.mcp.paging import CursorCodec
from etf_cockpit.mcp.registry import CallContext, discover_tools, invoke_tool
from etf_cockpit.mcp.serialise import build_envelope, envelope_dict
from etf_cockpit.mcp.server import list_tools


def _install_tools_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, name: str) -> str:
    module_path = tmp_path / f"{name}.py"
    module_path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(mcp_package, "__path__", [*mcp_package.__path__, str(tmp_path)])
    module_name = f"etf_cockpit.mcp.{name}"
    importlib.invalidate_caches()
    return module_name


def test_registry_autodiscovers_module_with_tier_and_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = _install_tools_module(
        tmp_path,
        monkeypatch,
        "from etf_cockpit.mcp.registry import tool\n"
        "@tool(tier='research', description='Record evidence', idempotent_hint=False, requires_confirmation=False)\n"
        "def test_discovered(value: str) -> dict:\n"
        "    return {'value': value}\n",
        "tools_test_autodiscovery",
    )

    specs = discover_tools()
    spec = next(item for item in specs if item.name == "test_discovered")

    assert spec.tier == "research"
    assert spec.annotations == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    sys.modules.pop(module_name, None)


def test_write_tier_without_valid_confirm_token_is_refused_before_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_name = _install_tools_module(
        tmp_path,
        monkeypatch,
        "from etf_cockpit.mcp.registry import tool\n"
        "writes = []\n"
        "@tool(tier='research', description='Write evidence')\n"
        "def test_write(value: str, confirm_token: str) -> dict:\n"
        "    writes.append(value)\n"
        "    return {'written': value}\n",
        "tools_test_confirm",
    )
    module = importlib.import_module(module_name)
    audit = AuditRecorder(sink=lambda record: None)
    context = CallContext(
        enabled_tiers=frozenset({"read", "research"}),
        profile="full",
        confirmation_store=ConfirmationStore(secret=b"c" * 32),
        audit=audit,
    )

    with pytest.raises(ConfirmationError):
        invoke_tool("test_write", {"value": "finding", "confirm_token": "invalid"}, context=context)

    assert module.writes == []
    assert len(audit.records) == 1
    assert audit.records[0].tool == "test_write"
    assert audit.records[0].tier == "research"
    assert audit.records[0].outcome == "refused"
    sys.modules.pop(module_name, None)


def test_each_call_writes_one_audit_record_with_tool_tier_hash_and_outcome() -> None:
    audit = AuditRecorder(sink=lambda record: None)
    context = CallContext(enabled_tiers=frozenset({"read"}), profile="core", audit=audit)

    invoke_tool("cockpit_status", {"detail": "brief"}, context=context)

    assert len(audit.records) == 1
    record = audit.records[0]
    assert record.tool == "cockpit_status"
    assert record.tier == "read"
    assert len(record.args_hash) == 64
    assert record.outcome == "ok"


def test_envelope_serialisation_and_paging_cursor_round_trip() -> None:
    envelope = build_envelope({"amount": Decimal("40.25"), "missing": float("nan"), "next_cursor": "next"})
    result = envelope_dict(envelope)
    cursor_codec = CursorCodec(secret=b"p" * 32)
    cursor = cursor_codec.encode(50, filters={"status": "queued"})

    assert isinstance(envelope, Envelope)
    assert result["execution_allowed"] is False
    assert result["data"]["amount"] == "40.25"
    assert result["data"]["missing"] is None
    assert result["next_cursor"] == "next"
    assert cursor_codec.decode(cursor, filters={"status": "queued"}) == 50


def test_server_lists_tools_without_sdk_and_fails_clearly_when_starting_without_it(monkeypatch: pytest.MonkeyPatch) -> None:
    names = {spec.name for spec in list_tools(profile="core", tiers=("read",))}
    assert {"cockpit_status", "job_status"} <= names

    real_import = builtins.__import__

    def without_sdk(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError("No module named 'mcp'", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_sdk)
    from etf_cockpit.mcp.server import create_server

    with pytest.raises(MCPServerUnavailable, match="optional MCP SDK"):
        create_server()


def test_tools_cannot_set_execution_allowed_or_import_broker_layers() -> None:
    specs = discover_tools()
    assert specs
    for spec in specs:
        names = set(inspect.signature(spec.function).parameters)
        assert "execution_allowed" not in names
        assert not names.intersection({"broker", "broker_client", "broker_api"})

    from etf_cockpit.governance.architecture_boundaries import find_violations

    root = Path(__file__).resolve().parents[2]
    assert find_violations(root) == ()
    imports: set[str] = set()
    for path in (root / "src" / "etf_cockpit" / "mcp").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imports
        for prefix in ("etf_cockpit.trading", "etf_cockpit.portfolio", "etf_cockpit.data")
    )
