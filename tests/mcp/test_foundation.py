from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib
import inspect
import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

from decimal import Decimal

import pytest

import etf_cockpit.mcp as mcp_package
import etf_cockpit.mcp.registry as registry
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import ConfirmationError, MCPToolError, RateLimitError
from etf_cockpit.mcp.paging import CursorCodec
from etf_cockpit.mcp.registry import CallContext, RateLimiter, discover_tools, invoke_tool, tool
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
        "@tool(tier='research', description='Record evidence', idempotent_hint=False, preview=lambda **kwargs: kwargs)\n"
        "def test_discovered(value: str, confirm_token: str) -> dict:\n"
        "    return {'value': value}\n",
        "tools_test_autodiscovery",
    )

    specs = discover_tools()
    spec = next(item for item in specs if item.name == "test_discovered")

    assert spec.tier == "research"
    assert spec.annotations == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    assert spec.requires_confirmation is True
    sys.modules.pop(module_name, None)


@pytest.mark.parametrize("tier", ["research", "edit", "paper"])
def test_write_tiers_cannot_exempt_confirmation(tier: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="write-tier tools must require confirmation"):
        tool(tier=tier, description="Write", requires_confirmation=False)

    writes = []

    @tool(tier=tier, description="Write", preview=lambda **kwargs: kwargs)
    def write(confirm_token: str) -> None:
        writes.append(True)

    # Dispatch also fails closed if a declaration's metadata is altered after decoration.
    spec = replace(write.__mcp_tool_spec__, requires_confirmation=False)
    monkeypatch.setattr(registry, "find_tool", lambda name: spec)
    context = CallContext(enabled_tiers=frozenset({tier}), profile="full", audit=AuditRecorder(sink=lambda record: None))
    with pytest.raises(ConfirmationError):
        invoke_tool(spec.name, {"confirm_token": "invalid"}, context=context)
    assert writes == []
    assert context.audit.records[-1].outcome == "refused"


def test_read_job_compute_keeps_confirmation_exemption(monkeypatch: pytest.MonkeyPatch) -> None:
    @tool(tier="read_job", description="Derived compute", read_only_hint=False, requires_confirmation=False)
    def compute() -> dict:
        return {"computed": True}

    monkeypatch.setattr(registry, "find_tool", lambda name: compute.__mcp_tool_spec__)
    context = CallContext(
        enabled_tiers=frozenset({"read_job"}), profile="full", audit=AuditRecorder(sink=lambda record: None)
    )
    assert invoke_tool("compute", {}, context=context) == {"computed": True}
    assert context.audit.records[-1].outcome == "ok"


def test_write_without_token_previews_then_commits_once(monkeypatch: pytest.MonkeyPatch) -> None:
    previews = []
    writes = []

    def preview(value: str) -> dict[str, str]:
        previews.append(value)
        return {"value": value, "would_write": "yes"}

    @tool(tier="edit", description="Update source data", preview=preview)
    def write(value: str, confirm_token: str) -> dict[str, str]:
        writes.append(value)
        return {"written": value}

    monkeypatch.setattr(registry, "find_tool", lambda name: write.__mcp_tool_spec__)
    context = CallContext(
        enabled_tiers=frozenset({"edit"}), profile="full", audit=AuditRecorder(sink=lambda record: None)
    )

    staged = invoke_tool("write", {"value": "candidate"}, context=context)
    assert staged["preview"] == {"value": "candidate", "would_write": "yes"}
    assert isinstance(staged["confirm_token"], str)
    assert previews == ["candidate"]
    assert writes == []

    with pytest.raises(ConfirmationError):
        invoke_tool("write", {"value": "candidate", "confirm_token": "invalid"}, context=context)
    assert writes == []

    committed = invoke_tool("write", {"value": "candidate", "confirm_token": staged["confirm_token"]}, context=context)
    assert committed == {"written": "candidate"}
    assert writes == ["candidate"]
    with pytest.raises(ConfirmationError):
        invoke_tool("write", {"value": "candidate", "confirm_token": staged["confirm_token"]}, context=context)
    assert writes == ["candidate"]


def test_handler_dry_run_is_centralized_and_caller_cannot_skip_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bool, str]] = []

    @tool(tier="edit", description="Update through a handler dry run")
    def write(value: str, dry_run: bool = True, confirm_token: str | None = None) -> dict[str, object]:
        calls.append((dry_run, value))
        return {"status": "confirmation_required" if dry_run else "written", "value": value, "confirm_token": "handler-token"}

    monkeypatch.setattr(registry, "find_tool", lambda name: write.__mcp_tool_spec__)
    context = CallContext(
        enabled_tiers=frozenset({"edit"}), profile="full", audit=AuditRecorder(sink=lambda record: None)
    )

    staged = invoke_tool("write", {"value": "candidate", "dry_run": False}, context=context)
    assert calls == [(True, "candidate")]
    assert staged["preview"] == {"status": "confirmation_required", "value": "candidate"}
    assert isinstance(staged["confirm_token"], str)

    committed = invoke_tool("write", {"value": "candidate", "confirm_token": staged["confirm_token"]}, context=context)
    assert calls == [(True, "candidate"), (False, "candidate")]
    assert committed["status"] == "written"


def test_write_without_preview_callback_gets_a_confirmation_bound_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[str] = []

    @tool(tier="edit", description="Write with no calculation preview")
    def write(value: str, confirm_token: str | None = None) -> dict[str, str]:
        writes.append(value)
        return {"written": value}

    monkeypatch.setattr(registry, "find_tool", lambda name: write.__mcp_tool_spec__)
    context = CallContext(
        enabled_tiers=frozenset({"edit"}), profile="full", audit=AuditRecorder(sink=lambda record: None)
    )

    staged = invoke_tool("write", {"value": "candidate"}, context=context)
    assert staged["preview"] == {
        "status": "confirmation_required",
        "operation": "write",
        "arguments": {"value": "candidate"},
        "execution_allowed": False,
    }
    assert isinstance(staged["confirm_token"], str)
    assert writes == []

    committed = invoke_tool("write", {"value": "candidate", "confirm_token": staged["confirm_token"]}, context=context)
    assert committed == {"written": "candidate"}
    assert writes == ["candidate"]


@pytest.mark.parametrize("module_name", ["etf_cockpit.mcp.tools_paper", "etf_cockpit.mcp.tools_portfolio"])
@pytest.mark.parametrize("arguments", [{}, {"dry_run": True}, {"dry_run": False}])
def test_handler_owned_preview_requires_token_before_dispatch(
    module_name: str, arguments: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def write(value: str, dry_run: bool = True, confirm_token: str | None = None) -> dict:
        calls.append((value, dry_run))
        return {"status": "confirmation_required", "confirm_token": "handler-token"}

    monkeypatch.setattr(write, "__module__", module_name)
    write = tool(tier="paper", description="Handler-owned preview")(write)
    spec = write.__mcp_tool_spec__
    assert spec.preview_function is None
    monkeypatch.setattr(registry, "find_tool", lambda name: spec)
    context = CallContext(
        enabled_tiers=frozenset({"paper"}), profile="full", audit=AuditRecorder(sink=lambda record: None)
    )

    with pytest.raises(ConfirmationError):
        invoke_tool("write", {"value": "candidate", **arguments}, context=context)
    assert calls == []
    assert context.audit.records[-1].outcome == "refused"


@pytest.mark.parametrize("module_name", ["etf_cockpit.mcp.tools_paper", "etf_cockpit.mcp.tools_portfolio"])
def test_handler_owned_token_preserves_dry_run_binding_and_is_single_use(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def write(value: str, dry_run: bool = True, confirm_token: str | None = None) -> dict:
        calls.append((value, dry_run))
        return {"written": value}

    monkeypatch.setattr(write, "__module__", module_name)
    write = tool(tier="paper", description="Handler-owned preview")(write)
    monkeypatch.setattr(registry, "find_tool", lambda name: write.__mcp_tool_spec__)
    context = CallContext(
        enabled_tiers=frozenset({"paper"}), profile="full", store_revision="R2",
        audit=AuditRecorder(sink=lambda record: None),
    )
    payload = {"value": "candidate", "dry_run": False}
    token = context.confirmation_store.issue(payload, store_revision="R2", client_id=context.client_id)
    for changed in ({"value": "candidate"}, {**payload, "dry_run": True}, {**payload, "value": "changed"}):
        with pytest.raises(ConfirmationError):
            invoke_tool("write", {**changed, "confirm_token": token}, context=context)
    assert calls == []

    arguments = {**payload, "confirm_token": token, "store_revision": "R2"}
    assert invoke_tool("write", arguments, context=context) == {"written": "candidate"}
    assert calls == [("candidate", False)]
    with pytest.raises(ConfirmationError):
        invoke_tool("write", arguments, context=context)
    assert calls == [("candidate", False)]


def test_edit_tier_read_only_preview_needs_no_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    @tool(tier="edit", description="Inspect an import", read_only_hint=True)
    def preview(path: str) -> dict[str, str]:
        return {"path": path, "status": "valid"}

    spec = preview.__mcp_tool_spec__
    assert spec.annotations["readOnlyHint"] is True
    assert spec.requires_confirmation is False
    monkeypatch.setattr(registry, "find_tool", lambda name: spec)
    context = CallContext(
        enabled_tiers=frozenset({"edit"}), profile="full", audit=AuditRecorder(sink=lambda record: None)
    )

    assert invoke_tool("preview", {"path": "local.csv"}, context=context) == {
        "path": "local.csv", "status": "valid"
    }


@pytest.mark.parametrize(
    ("token_revision", "echoed_revision"), [("R1", "R1"), ("R1", "R2"), ("R1", None), ("R2", "R1")]
)
def test_confirmation_uses_current_revision_and_rejects_conflicting_echo(
    token_revision: str, echoed_revision: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes = []

    @tool(tier="research", description="Write evidence", preview=lambda value: {"value": value})
    def write(value: str, confirm_token: str, store_revision: str | None = None) -> None:
        writes.append(value)

    monkeypatch.setattr(registry, "find_tool", lambda name: write.__mcp_tool_spec__)
    context = CallContext(
        enabled_tiers=frozenset({"research"}), profile="full", store_revision="R2",
        audit=AuditRecorder(sink=lambda record: None),
    )
    payload = {"value": "finding"}
    token = context.confirmation_store.issue(payload, store_revision=token_revision, client_id=context.client_id)
    arguments = {**payload, "confirm_token": token}
    if echoed_revision is not None:
        arguments["store_revision"] = echoed_revision
    with pytest.raises(ConfirmationError):
        invoke_tool("write", arguments, context=context)
    assert writes == []
    assert context.audit.records[-1].outcome == "refused"

    # A conflicting caller revision must be rejected before consuming an otherwise valid token.
    fresh_token = token if token_revision == "R2" else context.confirmation_store.issue(
        payload, store_revision="R2", client_id=context.client_id
    )
    invoke_tool("write", {**payload, "confirm_token": fresh_token, "store_revision": "R2"}, context=context)
    assert writes == ["finding"]
    with pytest.raises(ConfirmationError):
        invoke_tool("write", {**payload, "confirm_token": fresh_token, "store_revision": "R2"}, context=context)
    assert writes == ["finding"]


@pytest.mark.parametrize(
    ("name", "tier", "limit", "window"),
    [("paper_order_place", "paper", 20, 86400), ("ticket_export", "edit", 10, 86400), ("data_refresh", "edit", 4, 3600)],
)
def test_dispatch_rate_limits_before_handler_and_audits_refusals(
    name: str, tier: str, limit: int, window: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [0.0]
    path = tmp_path / "quota.sqlite3"
    limiter = RateLimiter(path=path, clock=lambda: now[0])
    monkeypatch.setattr(registry, "_RATE_LIMITER", limiter)
    audit = AuditRecorder(sink=lambda record: None)
    writes = []

    @tool(name=name, tier=tier, description="Rate-limited operation", preview=lambda **kwargs: kwargs)
    def write(confirm_token: str) -> None:
        writes.append(True)

    monkeypatch.setattr(registry, "find_tool", lambda name: write.__mcp_tool_spec__)
    contexts = [
        CallContext(enabled_tiers=frozenset({tier}), profile="full", client_id=client, audit=audit)
        for client in ("first", "second")
    ]
    for index in range(limit):
        context = contexts[index % 2]
        token = context.confirmation_store.issue({}, store_revision="", client_id=context.client_id)
        invoke_tool(name, {"confirm_token": token}, context=context)

    # A newly started server/client must see reservations made by the previous instances.
    context = CallContext(
        enabled_tiers=frozenset({tier}), profile="full", audit=audit,
        rate_limiter=RateLimiter(path=path, clock=lambda: now[0]),
    )
    token = context.confirmation_store.issue({}, store_revision="", client_id=context.client_id)
    for moment in (0.0, window - 0.001):
        now[0] = moment
        with pytest.raises(RateLimitError) as exc_info:
            invoke_tool(name, {"confirm_token": token}, context=context)
        assert exc_info.value.retry_after_seconds > 0
    assert len(writes) == limit
    assert len(audit.records) == limit + 2
    assert [record.outcome for record in audit.records] == ["ok"] * limit + ["refused", "refused"]
    assert audit.records[-1].reason_code == "RATE_LIMIT_EXCEEDED"

    # A quota refusal preserves the token; it can be used once the rolling window expires.
    now[0] = window
    invoke_tool(name, {"confirm_token": token}, context=context)
    assert len(writes) == limit + 1
    assert audit.records[-1].outcome == "ok"


def test_parallel_quota_reservations_cannot_exceed_limit(tmp_path: Path) -> None:
    path = tmp_path / "quota.sqlite3"

    def reserve(_: int) -> str:
        try:
            RateLimiter(path=path, clock=lambda: 0.0).acquire("data_refresh")
        except RateLimitError:
            return "refused"
        return "ok"

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(reserve, range(12)))
    assert outcomes.count("ok") == 4
    assert outcomes.count("refused") == 8


def test_quota_storage_failure_refuses_handler_and_is_audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "not_a_directory"
    path.write_text("blocked", encoding="utf-8")
    writes = []

    @tool(name="data_refresh", tier="edit", description="Refresh", preview=lambda **kwargs: kwargs)
    def refresh(confirm_token: str) -> None:
        writes.append(True)

    monkeypatch.setattr(registry, "find_tool", lambda name: refresh.__mcp_tool_spec__)
    context = CallContext(
        enabled_tiers=frozenset({"edit"}), profile="full", audit=AuditRecorder(sink=lambda record: None),
        rate_limiter=RateLimiter(path=path / "quota.sqlite3"),
    )
    token = context.confirmation_store.issue({}, store_revision="", client_id=context.client_id)
    with pytest.raises(MCPToolError) as exc_info:
        invoke_tool("data_refresh", {"confirm_token": token}, context=context)
    assert exc_info.value.reason_code == "RATE_LIMIT_UNAVAILABLE"
    assert writes == []
    assert context.audit.records[-1].outcome == "refused"
    assert context.audit.records[-1].reason_code == "RATE_LIMIT_UNAVAILABLE"


def test_write_tier_without_valid_confirm_token_is_refused_before_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_name = _install_tools_module(
        tmp_path,
        monkeypatch,
        "from etf_cockpit.mcp.registry import tool\n"
        "writes = []\n"
        "@tool(tier='research', description='Write evidence', preview=lambda **kwargs: kwargs)\n"
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


def test_server_lists_tools_without_sdk_and_fails_clearly_when_starting_without_it() -> None:
    names = {spec.name for spec in list_tools(profile="core", tiers=("read",))}
    assert {"cockpit_status", "job_status"} <= names

    _assert_server_without_sdk()


@pytest.mark.parametrize("pythonpath", [None, "src"])
def test_server_without_sdk_subprocess_resolves_checkout_source(
    pythonpath: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if pythonpath is None:
        monkeypatch.delenv("PYTHONPATH", raising=False)
    else:
        monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.chdir(tmp_path)

    _assert_server_without_sdk()


def _assert_server_without_sdk() -> None:
    code = dedent("""
        import builtins
        import sys
        real_import = builtins.__import__
        def without_sdk(name, *args, **kwargs):
            if name == "mcp" or name.startswith("mcp."):
                raise ModuleNotFoundError("No module named 'mcp'", name=name)
            return real_import(name, *args, **kwargs)
        builtins.__import__ = without_sdk
        from etf_cockpit.mcp.server import create_server, list_tools
        from etf_cockpit.mcp.errors import MCPServerUnavailable
        assert {"cockpit_status", "job_status"} <= {spec.name for spec in list_tools()}
        assert not any(name == "mcp" or name.startswith("mcp.") for name in sys.modules)
        try:
            create_server()
        except MCPServerUnavailable as exc:
            assert "optional MCP SDK" in str(exc)
        else:
            raise AssertionError("server started without the SDK")
        print("disabled-safe")
    """)
    environment = dict(os.environ)
    # Pytest's source-path setup is not inherited by a fresh Python process.
    source_root = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (source_root, environment.get("PYTHONPATH"))))
    result = subprocess.run(
        [sys.executable, "-c", code], env=environment, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "disabled-safe"


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


@pytest.mark.parametrize("entrypoint", ["refresh_sparebanks", "rescore_sparebanks_at"])
@pytest.mark.parametrize("loader_source", ["script", "application", "explicit"])
def test_sparebank_loader_patch_points_delegate_without_changing_application_globals(
    entrypoint: str, loader_source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from scripts import sparebank_refresh as script
    from etf_cockpit.application import sparebank_refresh as application

    record = SimpleNamespace(instrument_id="PATCHED", lei="")
    loaded_roots = []
    scored = []

    def loader(root):
        loaded_roots.append(root)
        return (record,)

    def forbidden_loader(root):
        raise AssertionError("the selected loader was bypassed")

    def rescorer(rec, data_root, universe_root, decision_time):
        scored.append((rec, data_root, universe_root, decision_time))
        return 7.5, 0.4, "partial"

    monkeypatch.setattr(script, "load_sparebank_records", loader if loader_source == "script" else forbidden_loader)
    application_loader = loader if loader_source == "application" else forbidden_loader
    monkeypatch.setattr(application, "load_sparebank_records", application_loader)
    module = application if loader_source == "application" else script
    kwargs = {"rescorer": rescorer}
    if loader_source == "explicit":
        kwargs["record_loader"] = loader
    if entrypoint == "refresh_sparebanks":
        kwargs.update(universe_root=tmp_path, decision_time="2024-06-28T23:59:59+00:00", fetch=False, write_summary=False)
        rows = module.refresh_sparebanks(tmp_path, **kwargs)
    else:
        rows = module.rescore_sparebanks_at(tmp_path, "2024-06-28", **kwargs)

    assert loaded_roots == [tmp_path.resolve()]
    assert scored == [(record, tmp_path.resolve(), tmp_path.resolve(), "2024-06-28T23:59:59+00:00")]
    assert rows[0]["id"] == "PATCHED" and rows[0]["composite"] == 7.5
    assert application.load_sparebank_records is application_loader
    assert not (tmp_path / "evidence").exists()
