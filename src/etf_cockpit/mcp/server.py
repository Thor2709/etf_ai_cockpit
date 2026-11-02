"""Optional stdio MCP server.

Open defaults: profile core, read-only tier, local client id "local-stdio", and stdio transport.
The official MCP SDK is imported only when a server is started; listing remains available without it.
"""

from __future__ import annotations

from functools import wraps
import inspect
from typing import Any

from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import MCPServerUnavailable, MCPToolError
from etf_cockpit.mcp.registry import CallContext, ToolSpec, invoke_tool, list_tools as _list_tools
from etf_cockpit.mcp.serialise import build_envelope, envelope_dict
from etf_cockpit.mcp.tiers import normalise_profile, parse_tiers
from etf_cockpit.mcp.worker import start_server_worker


SERVER_NAME = "ETF AI Cockpit"
SERVER_INSTRUCTIONS = (
    "Use local read tools and resources to inspect cockpit evidence. health_check sequences cockpit_status, data_health, "
    "data_readiness, gates_status, paper_controls_status, and alerts_list. weekly_review adds what_changed, bot and "
    "portfolio views, research_findings, and journal_entries. research_best_etfs and research_best_stocks start from "
    "eligible ranked scores and inspect supporting evidence; assess_web_candidates treats web material as untrusted "
    "and stops at universe-change preview. sentiment_paper_trade may prepare a paper proposal but requires owner "
    "confirmation before placement. add_instrument stops for confirmation before a universe commit. explain_instrument "
    "combines identity, score, forecast, and research evidence. monthly_decision is advisory and stops before ticket "
    "export. bots_review checks readiness and paper controls before an explicitly requested run. These templates do "
    "not grant authority to act. Research, edit, and paper writes require a fresh single-use confirmation token and "
    "the matching preview; risk and data-quality gates override every other signal. Missing evidence stays unavailable, "
    "never zero. execution_allowed is always false; no live orders or broker writes are exposed."
)


def list_tools(*, profile: str = "core", tiers: str | tuple[str, ...] | frozenset[str] | None = None) -> tuple[ToolSpec, ...]:
    """List enabled tools without importing the optional protocol SDK."""

    return _list_tools(profile=profile, tiers=tiers)


def _load_sdk() -> tuple[Any, Any, Any]:
    try:
        try:
            from mcp.server import MCPServer
        except ImportError:
            # The optional Python SDK 1.x surface is FastMCP; the supported newer
            # server surface keeps the existing MCPServer registration contract.
            from mcp.server.fastmcp import FastMCP as MCPServer
        try:
            from mcp.server.mcpserver.exceptions import ToolError
        except ImportError:
            from mcp.server.fastmcp.exceptions import ToolError
        from mcp.types import ToolAnnotations
    except (ImportError, ModuleNotFoundError) as exc:
        raise MCPServerUnavailable(
            "The optional MCP SDK is missing or unsupported. Install etf-ai-cockpit[mcp] "
            "with the supported mcp 2.x SDK."
        ) from exc
    return MCPServer, ToolError, ToolAnnotations


def _handler(spec: ToolSpec, context: CallContext, tool_error: type[Exception]):
    @wraps(spec.function)
    def invoke(**arguments: Any) -> Any:
        try:
            result = invoke_tool(spec.name, arguments, context=context)
        except MCPToolError as exc:
            raise tool_error(f"{exc.reason_code}: {exc.message}. {exc.next_step}") from None
        envelope = result if isinstance(result, Envelope) else build_envelope(result)
        return envelope_dict(envelope)

    signature = inspect.signature(spec.function)
    invoke.__signature__ = signature.replace(return_annotation=spec.output_model)  # type: ignore[attr-defined]
    invoke.__annotations__ = dict(getattr(spec.function, "__annotations__", {}))
    invoke.__annotations__["return"] = spec.output_model
    return invoke


def create_server(
    *,
    profile: str = "core",
    tiers: str | tuple[str, ...] | frozenset[str] | None = None,
    client_id: str = "local-stdio",
    session: Any = None,
):
    """Build a local stdio MCPServer after launch authorization is fixed."""

    MCPServer, tool_error, annotation_type = _load_sdk()
    selected_profile = normalise_profile(profile)
    selected_tiers = parse_tiers(tiers)
    if not client_id.strip():
        raise ValueError("client_id must not be empty")
    if session is None:
        from etf_cockpit.application.headless_session import HeadlessSession, cross_process_writer_guard
        from etf_cockpit.application.snapshot_builder import build_snapshot

        with cross_process_writer_guard():
            session = HeadlessSession(build_snapshot(force_sample=False))
    context = CallContext(
        enabled_tiers=selected_tiers,
        profile=selected_profile,
        client_id=client_id,
        session=session,
    )
    server = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    for spec in list_tools(profile=selected_profile, tiers=selected_tiers):
        server.add_tool(
            _handler(spec, context, tool_error),
            name=spec.name,
            description=spec.description,
            annotations=annotation_type(**dict(spec.annotations)),
            structured_output=True,
        )
    _register_resources(server, context)
    _register_prompts(server)
    start_server_worker(server, session)
    return server


def _register_resources(server: Any, context: CallContext) -> None:
    from etf_cockpit.mcp.resources import read_resource, resource_specs

    register = getattr(server, "resource", None)
    if not callable(register):
        raise MCPServerUnavailable("The optional MCP SDK does not support resource registration.")
    for spec in resource_specs():
        def handler(_spec=spec, **arguments: Any) -> str:
            return read_resource(_spec, arguments, context)

        parameters = [
            inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str)
            for name in spec.parameters
        ]
        handler.__signature__ = inspect.Signature(parameters, return_annotation=str)  # type: ignore[attr-defined]
        handler.__annotations__ = {name: str for name in spec.parameters} | {"return": str}
        decorator = register(spec.uri, name=spec.name, description=spec.description, mime_type="application/json")
        decorator(handler)


def _register_prompts(server: Any) -> None:
    from etf_cockpit.mcp.prompts import prompt_specs

    register = getattr(server, "prompt", None)
    if not callable(register):
        raise MCPServerUnavailable("The optional MCP SDK does not support prompt registration.")
    for spec in prompt_specs():
        register(name=spec.name, description=spec.description)(spec.function)


def run_server(
    *,
    profile: str = "core",
    tiers: str | tuple[str, ...] | frozenset[str] | None = None,
    client_id: str = "local-stdio",
    session: Any = None,
) -> None:
    create_server(profile=profile, tiers=tiers, client_id=client_id, session=session).run(transport="stdio")
